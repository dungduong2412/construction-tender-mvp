"""
Database models and session management.
All models use SQLAlchemy 2.x mapped_column style.
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Enum, Float, ForeignKey, Integer,
    String, Text, func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tender_mvp.db")
# Ensure aiosqlite driver for async
if DATABASE_URL.startswith("sqlite:///") and "aiosqlite" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsing = "parsing"
    mapping = "mapping"
    pricing = "pricing"
    needs_review = "needs_review"
    ready = "ready"
    exported = "exported"
    failed = "failed"


class RowType(str, enum.Enum):
    heading = "heading"
    metadata = "metadata"
    line_item = "line_item"


class MappingStatus(str, enum.Enum):
    mapped_and_priced = "mapped_and_priced"
    mapped_price_unavailable = "mapped_price_unavailable"
    mapping_ambiguous = "mapping_ambiguous"
    mapping_unresolved = "mapping_unresolved"
    invalid_quantity_or_unit = "invalid_quantity_or_unit"
    non_billable_heading = "non_billable_heading"
    non_billable_metadata = "non_billable_metadata"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.uploaded
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    parsed_document: Mapped[Optional["ParsedDocument"]] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    boq_rows: Mapped[list["BOQRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    overrides: Mapped[list["Override"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ParsedDocument(Base):
    """Raw Azure Document Intelligence output preserved verbatim."""
    __tablename__ = "parsed_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, unique=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)  # full API response
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    api_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(back_populates="parsed_document")


class BOQRow(Base):
    """Reconstructed BOQ line item / heading / metadata from the parsed document."""
    __tablename__ = "boq_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    row_id: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "IV.1-3"
    row_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    section_path: Mapped[str] = mapped_column(Text, nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    unit_raw: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    quantity_raw: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # original string
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # parsed float
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    region: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    row_type: Mapped[RowType] = mapped_column(Enum(RowType), nullable=False)
    doc_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    job: Mapped["Job"] = relationship(back_populates="boq_rows")
    mapping_result: Mapped[Optional["MappingResult"]] = relationship(
        back_populates="boq_row", uselist=False, cascade="all, delete-orphan"
    )


class MasterItem(Base):
    """Versioned master pricing record seeded from the reference XLS."""
    __tablename__ = "master_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    item_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)  # stored as float, Decimal in engine
    formula_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_sheet: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON dict


class UnitRule(Base):
    """Approved unit conversion rules — never convert without an explicit entry."""
    __tablename__ = "unit_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    from_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    to_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    factor: Mapped[float] = mapped_column(Float, nullable=False)  # to_unit = from_unit * factor
    note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class Coefficient(Base):
    """Coefficients from Hệ số sheet."""
    __tablename__ = "coefficients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    coeff_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description_vi: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    applies_to: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of item_codes or "all"


class MappingResult(Base):
    """AI semantic mapping output for a BOQ row."""
    __tablename__ = "mapping_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    boq_row_id: Mapped[int] = mapped_column(ForeignKey("boq_rows.id"), nullable=False, unique=True)
    master_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("master_items.id"), nullable=True)
    status: Mapped[MappingStatus] = mapped_column(Enum(MappingStatus), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON dict
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unresolved_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit_rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("unit_rules.id"), nullable=True)
    # Pricing outputs (set by engine, Decimal-precision stored as string)
    unit_price_str: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extended_amount_str: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    price_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    formula_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    coeff_applied_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    master_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    boq_row: Mapped["BOQRow"] = relationship(back_populates="mapping_result")
    master_item: Mapped[Optional["MasterItem"]] = relationship()


class Override(Base):
    """User-recorded overrides on mapping / pricing fields."""
    __tablename__ = "overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    row_id: Mapped[str] = mapped_column(String(128), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    user: Mapped[str] = mapped_column(String(128), nullable=False, default="demo-user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["Job"] = relationship(back_populates="overrides")
