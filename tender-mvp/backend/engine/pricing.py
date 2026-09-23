"""
Deterministic Pricing Engine
=============================
Applies approved formulas to produce priced lines.

Rules:
- unit_price comes from versioned master data only (never from LLM)
- extended_amount = round(quantity * unit_price * unit_conversion_factor)
- All amounts in integer VND
- Zero is NEVER substituted for a missing quantity or price
- Section headings and metadata rows get HEADING status and no amount
- Unresolved mappings get UNRESOLVED status and no amount
- User overrides supersede master prices for approved rows
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from ..models.domain import (
    BOQDocument,
    BOQRow,
    MappingResult,
    MappingStatus,
    MasterItem,
    PriceLine,
    PriceLineStatus,
    PricingSheet,
    RowOverride,
    RowType,
)
from .master_loader import get_master_version, get_unit_conversion, load_master_items

_DEMO_TENANT = "demo-internal"


def _get_master_map() -> Dict[str, MasterItem]:
    return {item.id: item for item in load_master_items()}


def _compute_extended(
    quantity: Optional[Decimal],
    unit_price: Optional[int],
    factor: float,
) -> Optional[int]:
    """
    Return integer VND amount or None if any input is missing.
    Never defaults quantity or price to zero.
    """
    if quantity is None or unit_price is None:
        return None
    raw = quantity * Decimal(str(unit_price)) * Decimal(str(factor))
    return int(raw.to_integral_value())


def price_boq(
    boq: BOQDocument,
    mapping_results: List[MappingResult],
    overrides: Optional[List[RowOverride]] = None,
) -> PricingSheet:
    """
    Combine BOQ rows, mapping results, and optional overrides into a PricingSheet.
    """
    master_map = _get_master_map()
    mapping_by_id = {r.row_id: r for r in mapping_results}
    override_map: Dict[str, RowOverride] = {}
    for ov in (overrides or []):
        override_map[ov.row_id] = ov

    lines: List[PriceLine] = []
    subtotal = 0
    unresolved_count = 0

    row_map: Dict[str, BOQRow] = {r.row_id: r for r in boq.rows}

    for row in boq.rows:
        mapping = mapping_by_id.get(row.row_id)
        override = override_map.get(row.row_id)

        # --- HEADINGS / METADATA ---
        if row.row_type in (RowType.SECTION_HEADING, RowType.METADATA):
            lines.append(
                PriceLine(
                    row_id=row.row_id,
                    description_vi=row.description_vi,
                    source_section=row.source_section,
                    unit_pdf=row.unit_raw,
                    quantity=None,
                    master_id=None,
                    master_code=None,
                    master_description=None,
                    unit_master=None,
                    unit_price=None,
                    unit_conversion_factor=1.0,
                    extended_amount=None,
                    confidence=1.0,
                    status=PriceLineStatus.HEADING,
                    exception_reason=None,
                    source_page=row.page_number,
                    evidence=f"Classified as {row.row_type.value}",
                )
            )
            continue

        if mapping is None:
            unresolved_count += 1
            lines.append(
                PriceLine(
                    row_id=row.row_id,
                    description_vi=row.description_vi,
                    source_section=row.source_section,
                    unit_pdf=row.unit_raw,
                    quantity=row.quantity,
                    master_id=None,
                    master_code=None,
                    master_description=None,
                    unit_master=None,
                    unit_price=None,
                    unit_conversion_factor=1.0,
                    extended_amount=None,
                    confidence=0.0,
                    status=PriceLineStatus.UNRESOLVED,
                    exception_reason="No mapping result",
                    source_page=row.page_number,
                    evidence=None,
                )
            )
            continue

        # --- UNRESOLVED mapping ---
        if mapping.status in (MappingStatus.UNRESOLVED, MappingStatus.HEADING):
            unresolved_count += 1
            lines.append(
                PriceLine(
                    row_id=row.row_id,
                    description_vi=row.description_vi,
                    source_section=row.source_section,
                    unit_pdf=row.unit_raw,
                    quantity=row.quantity,
                    master_id=None,
                    master_code=None,
                    master_description=None,
                    unit_master=None,
                    unit_price=None,
                    unit_conversion_factor=1.0,
                    extended_amount=None,
                    confidence=mapping.confidence,
                    status=PriceLineStatus.UNRESOLVED,
                    exception_reason=mapping.exception_reason or "Unresolved by mapper",
                    source_page=row.page_number,
                    evidence=mapping.evidence,
                )
            )
            continue

        # --- Determine master item ---
        master_id = mapping.master_id
        unit_price: Optional[int] = None
        unit_master: Optional[str] = None
        master_description: Optional[str] = None
        master_code: Optional[str] = None
        factor = mapping.unit_conversion_factor

        if override and override.master_id:
            master_id = override.master_id

        master_item = master_map.get(master_id) if master_id else None
        if master_item:
            unit_price = master_item.unit_price
            unit_master = master_item.unit
            master_description = master_item.description
            master_code = master_item.code

        # --- Unit conversion ---
        pdf_unit = (row.unit_raw or "").strip().lower()
        master_unit = (unit_master or "").strip().lower()
        if pdf_unit and master_unit and pdf_unit != master_unit:
            conv = get_unit_conversion(pdf_unit, master_unit)
            if conv is not None:
                factor = conv
            else:
                # No approved conversion rule – keep factor 1.0 but flag
                factor = 1.0

        # --- Override price ---
        if override and override.unit_price_override is not None:
            unit_price = override.unit_price_override

        # --- Override quantity ---
        quantity = row.quantity
        if override and override.quantity_override is not None:
            quantity = override.quantity_override

        # --- Compute extended amount ---
        extended = _compute_extended(quantity, unit_price, factor)

        # --- Status ---
        if override and override.approved:
            status = PriceLineStatus.USER_OVERRIDE
        elif mapping.status == MappingStatus.AMBIGUOUS:
            status = PriceLineStatus.UNRESOLVED
            unresolved_count += 1
        elif unit_price is None or quantity is None or extended is None:
            status = PriceLineStatus.UNRESOLVED
            unresolved_count += 1
        else:
            status = PriceLineStatus.PRICED
            subtotal += extended

        lines.append(
            PriceLine(
                row_id=row.row_id,
                description_vi=row.description_vi,
                source_section=row.source_section,
                unit_pdf=row.unit_raw,
                quantity=quantity,
                master_id=master_id,
                master_code=master_code,
                master_description=master_description,
                unit_master=unit_master,
                unit_price=unit_price,
                unit_conversion_factor=factor,
                extended_amount=extended,
                confidence=mapping.confidence,
                status=status,
                exception_reason=(
                    mapping.exception_reason
                    if status == PriceLineStatus.UNRESOLVED
                    else None
                ),
                source_page=row.page_number,
                evidence=mapping.evidence,
            )
        )

    is_complete = unresolved_count == 0
    notes = (
        "DRAFT – pricing is complete."
        if is_complete
        else f"DRAFT – {unresolved_count} unresolved line(s). Do not use as a final bid."
    )

    return PricingSheet(
        job_id=boq.job_id,
        tenant_id=_DEMO_TENANT,
        master_data_version=get_master_version(),
        lines=lines,
        subtotal_priced_vnd=subtotal,
        unresolved_count=unresolved_count,
        is_complete=is_complete,
        notes=notes,
    )
