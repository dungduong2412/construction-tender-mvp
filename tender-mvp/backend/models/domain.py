"""
Domain models for the Construction Tender MVP.
All monetary amounts are integers (VND). Decimal quantities use Python Decimal.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job state machine
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    MAPPING = "mapping"
    PRICING = "pricing"
    NEEDS_REVIEW = "needs_review"
    READY = "ready"
    EXPORTED = "exported"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Parsed document structures (output of ParserAdapter)
# ---------------------------------------------------------------------------

class BoundingRegion(BaseModel):
    page_number: int
    polygon: Optional[List[float]] = None  # [x1,y1, x2,y2, x3,y3, x4,y4]


class CellContent(BaseModel):
    row_index: int
    col_index: int
    text: str
    confidence: Optional[float] = None
    bounding_regions: List[BoundingRegion] = Field(default_factory=list)


class ParsedTable(BaseModel):
    table_index: int
    page_number: int
    row_count: int
    col_count: int
    cells: List[CellContent]


class ParsedPage(BaseModel):
    page_number: int
    text: str
    tables: List[ParsedTable] = Field(default_factory=list)


class RawParserOutput(BaseModel):
    """Preserves raw Azure Document Intelligence response."""
    api_version: str
    model_id: str
    pages: List[ParsedPage]
    confidence: Optional[float] = None
    raw_json: Optional[Dict[str, Any]] = None  # full original payload


class ParsedDocument(BaseModel):
    """Canonical normalized structure after adapter processing."""
    job_id: str
    source_filename: str
    page_count: int
    pages: List[ParsedPage]
    raw_output: RawParserOutput


# ---------------------------------------------------------------------------
# BOQ hierarchy structures
# ---------------------------------------------------------------------------

class RowType(str, Enum):
    SECTION_HEADING = "section_heading"
    METADATA = "metadata"
    LINE_ITEM = "line_item"


class BOQRow(BaseModel):
    """A single reconstructed BOQ row from the PDF."""
    row_id: str                           # unique within job, e.g. "p1_t0_r3"
    page_number: int
    source_section: str                   # e.g. "IV.1"
    section_label: Optional[str] = None  # e.g. "Khảo sát địa chất"
    row_number_raw: Optional[str] = None  # original numbering from PDF, e.g. "1", "2"
    row_type: RowType
    description_vi: str                   # original Vietnamese text
    unit_raw: Optional[str] = None        # raw unit string from PDF
    quantity_raw: Optional[str] = None    # raw quantity string (may use comma decimals)
    quantity: Optional[Decimal] = None    # parsed Decimal
    notes: Optional[str] = None
    continues_from_page: Optional[int] = None  # if row spans pages
    bounding_regions: List[BoundingRegion] = Field(default_factory=list)

    class Config:
        json_encoders = {Decimal: str}


class BOQDocument(BaseModel):
    job_id: str
    rows: List[BOQRow]
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

class MasterItem(BaseModel):
    id: str
    code: str
    description: str
    tags: Dict[str, Any]
    unit: str
    unit_price: int  # VND
    source_sheet: str
    resolved: bool


class UnitRule(BaseModel):
    from_unit: str
    to_unit: str
    factor: float
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# AI Semantic Mapping
# ---------------------------------------------------------------------------

class MappingStatus(str, Enum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    HEADING = "heading"


class SemanticTag(BaseModel):
    discipline: Optional[str] = None
    work_type: Optional[str] = None
    context: Optional[str] = None          # road / bridge / etc.
    terrain: Optional[str] = None
    condition: Optional[str] = None        # on_land / underwater
    soil_class: Optional[str] = None
    depth_range: Optional[str] = None
    scale: Optional[str] = None
    test_type: Optional[str] = None
    sample_type: Optional[str] = None


class MappingResult(BaseModel):
    row_id: str
    status: MappingStatus
    master_id: Optional[str] = None
    master_code: Optional[str] = None
    master_description: Optional[str] = None
    tags: Optional[SemanticTag] = None
    unit_pdf: Optional[str] = None
    unit_master: Optional[str] = None
    unit_conversion_factor: float = 1.0
    confidence: float = 0.0
    evidence: Optional[str] = None         # why this match was chosen
    exception_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

class PriceLineStatus(str, Enum):
    PRICED = "priced"
    UNRESOLVED = "unresolved"
    HEADING = "heading"
    USER_OVERRIDE = "user_override"


class PriceLine(BaseModel):
    row_id: str
    description_vi: str
    source_section: str
    unit_pdf: Optional[str]
    quantity: Optional[Decimal]
    master_id: Optional[str]
    master_code: Optional[str]
    master_description: Optional[str]
    unit_master: Optional[str]
    unit_price: Optional[int]              # VND, from master data
    unit_conversion_factor: float = 1.0
    extended_amount: Optional[int]         # VND = quantity * unit_price * factor
    confidence: float = 0.0
    status: PriceLineStatus
    exception_reason: Optional[str]
    source_page: int
    evidence: Optional[str]

    class Config:
        json_encoders = {Decimal: str}


class PricingSheet(BaseModel):
    job_id: str
    tenant_id: str
    master_data_version: str
    lines: List[PriceLine]
    subtotal_priced_vnd: int
    unresolved_count: int
    is_complete: bool                      # False if any line is UNRESOLVED
    notes: str = ""


# ---------------------------------------------------------------------------
# User review / override
# ---------------------------------------------------------------------------

class RowOverride(BaseModel):
    row_id: str
    master_id: Optional[str] = None        # replacement master item
    unit_price_override: Optional[int] = None
    quantity_override: Optional[Decimal] = None
    approved: bool = False
    override_reason: Optional[str] = None

    class Config:
        json_encoders = {Decimal: str}


# ---------------------------------------------------------------------------
# Job record (in-memory store for MVP)
# ---------------------------------------------------------------------------

class TenderJob(BaseModel):
    job_id: str
    tenant_id: str
    filename: str
    status: JobStatus = JobStatus.UPLOADED
    error: Optional[str] = None
    parsed_document: Optional[ParsedDocument] = None
    boq_document: Optional[BOQDocument] = None
    pricing_sheet: Optional[PricingSheet] = None
    overrides: List[RowOverride] = Field(default_factory=list)
    excel_path: Optional[str] = None

    class Config:
        json_encoders = {Decimal: str}
