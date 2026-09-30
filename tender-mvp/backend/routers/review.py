"""Review router — return BOQ rows with pricing, accept user overrides."""
import json
import os
import ast
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    BOQRow, Job, JobStatus, MappingResult, MappingStatus, MasterItem, Override,
    RowType, UnitRule, Coefficient, get_db,
)
from boq.reconstructor import BOQLineItem
from pricing_engine.engine import PricingEngine
from pricing_availability import NOT_APPLICABLE, classify_price, display_price_state, price_freshness
from semantic_mapper.mapper import MappingOutput

DEMO_TENANT_ID = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")
MASTER_VERSION = os.getenv("MASTER_DATA_VERSION", "v1")

router = APIRouter()


class ReviewRow(BaseModel):
    row_id: str
    row_number: str
    row_type: str
    section_path: str
    description_vi: str
    unit: str
    quantity_raw: str
    quantity: Optional[float]
    master_item_id: Optional[int]
    master_code: Optional[str]
    master_description: Optional[str]
    unit_price: Optional[str]
    extended_amount: Optional[str]
    pricing_available: bool
    pricing_availability: str
    price_display: str
    price_applicability: str
    unit_price_editable: bool
    price_freshness: str
    price_effective_date: Optional[str]
    price_expiry_date: Optional[str]
    price_source_reference: Optional[str]
    price_last_updated_by: Optional[str]
    price_last_updated_at: Optional[str]
    mapping_last_updated_by: Optional[str]
    mapping_last_updated_at: Optional[str]
    mapped_by: Optional[str]
    price_change_pending_review: bool
    confidence: Optional[float]
    status: str
    page: int
    source_polygon: list[float]
    source_origin: str
    source_provenance: Optional[str]
    azure_polygon_available: bool
    error_reason: Optional[str]
    evidence: Optional[str]
    overrides: list[dict]


class OverrideRequest(BaseModel):
    row_id: str
    field: str
    old_value: Optional[str]
    new_value: str
    user: str = "demo-user"
    price_source_reference: Optional[str] = None
    price_effective_date: Optional[str] = None
    price_expiry_date: Optional[str] = None
    price_approval_status: Optional[str] = None
    price_approved_by: Optional[str] = None
    zero_price_authorized: bool = False


class AddRowRequest(BaseModel):
    description_vi: str
    row_number: str | None = None
    unit: str = ""
    quantity_raw: str = ""
    section_path: str = "Bổ sung thủ công"
    row_type: str = "line_item"
    user: str = "local-reviewer"


EDITABLE_SOURCE_FIELDS = {
    "description_vi", "unit", "quantity_raw", "row_type", "section_path"
}


def _source_polygon(region: Optional[str]) -> list[float]:
    if not region:
        return []
    try:
        parsed = ast.literal_eval(region)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    try:
        return [float(value) for value in parsed]
    except (TypeError, ValueError):
        return []


def _parse_quantity(raw: str) -> Optional[float]:
    value = raw.strip()
    if not value:
        return None
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    try:
        return float(value)
    except ValueError as exc:
        raise HTTPException(400, "quantity_raw must be a valid Vietnamese-formatted number") from exc


@router.get("/{job_id}/rows", response_model=list[ReviewRow])
async def get_review_rows(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    rows_q = await db.execute(
        select(BOQRow).where(BOQRow.job_id == job_id).order_by(BOQRow.doc_order)
    )
    boq_rows = rows_q.scalars().all()
    boq_row_ids = [r.id for r in boq_rows]

    mapping_map: dict[int, MappingResult] = {}
    if boq_row_ids:
        mapping_q = await db.execute(
            select(MappingResult).where(MappingResult.boq_row_id.in_(boq_row_ids))
        )
        mapping_map = {m.boq_row_id: m for m in mapping_q.scalars().all()}

    # Load master items for lookup
    masters_q = await db.execute(
        select(MasterItem).where(
            MasterItem.tenant_id == DEMO_TENANT_ID,
            MasterItem.version == MASTER_VERSION,
            MasterItem.catalogue_status == "active",
        )
    )
    master_map = {m.id: m for m in masters_q.scalars().all()}
    referenced_master_ids = {
        mapping.master_item_id for mapping in mapping_map.values()
        if mapping.master_item_id and mapping.master_item_id not in master_map
    }
    if referenced_master_ids:
        referenced = await db.execute(select(MasterItem).where(MasterItem.id.in_(referenced_master_ids)))
        master_map.update({item.id: item for item in referenced.scalars().all()})

    # Load overrides
    overrides_q = await db.execute(
        select(Override).where(Override.job_id == job_id)
    )
    override_list = overrides_q.scalars().all()
    override_map: dict[str, list[dict]] = {}
    for ov in override_list:
        override_map.setdefault(ov.row_id, []).append({
            "field": ov.field,
            "old_value": ov.old_value,
            "new_value": ov.new_value,
            "user": ov.user,
            "created_at": ov.created_at.isoformat() if ov.created_at else None,
        })

    result = []
    for row in boq_rows:
        mr = mapping_map.get(row.id)
        master = master_map.get(mr.master_item_id) if mr and mr.master_item_id else None
        source_reference = ((mr.price_source_reference if mr else None)
                            or (master.price_source_reference if master else None)
                            or (master.source_sheet if master else None))
        is_billable = row.row_type == RowType.line_item
        availability = classify_price(
            mr.unit_price_str if mr else None,
            source_reference=source_reference,
            approval_status="approved" if mr and mr.pricing_availability == "authorized_zero" else (master.approval_status if master else None),
            approved_by=(mr.price_last_updated_by if mr and mr.pricing_availability == "authorized_zero" else (master.approved_by if master else None)),
            zero_price_authorized=bool(mr and mr.pricing_availability == "authorized_zero"),
        )
        master_changed = bool(
            mr and master and (
                mr.price_review_required
                or (master.last_updated_at and mr.price_last_updated_at and master.last_updated_at > mr.price_last_updated_at)
                or (master.unit_price is None and mr.unit_price_str is not None)
                or (master.unit_price is not None and mr.unit_price_str is not None and Decimal(str(master.unit_price)) != Decimal(str(mr.unit_price_str)))
            )
        )

        availability_status = availability.status if is_billable else NOT_APPLICABLE
        result.append(ReviewRow(
            row_id=row.row_id,
            row_number=row.row_number or "",
            row_type=row.row_type.value,
            section_path=row.section_path,
            description_vi=row.description_vi,
            unit=row.unit_raw or "",
            quantity_raw=row.quantity_raw or "",
            quantity=row.quantity,
            master_item_id=mr.master_item_id if mr else None,
            master_code=master.item_code if master else None,
            master_description=master.description_vi if master else None,
            unit_price=mr.unit_price_str if mr else None,
            extended_amount=mr.extended_amount_str if mr else None,
            pricing_available=availability.available if is_billable else False,
            pricing_availability=availability_status,
            price_display=display_price_state(mr.unit_price_str if mr else None, availability_status),
            price_applicability="required" if is_billable else NOT_APPLICABLE,
            unit_price_editable=is_billable,
            price_freshness=price_freshness(
                (mr.price_effective_date if mr else None) or (master.price_effective_date if master else None),
                (mr.price_expiry_date if mr else None) or (master.price_expiry_date if master else None),
                available=availability.available,
            ),
            price_effective_date=(mr.price_effective_date if mr else None) or (master.price_effective_date if master else None),
            price_expiry_date=(mr.price_expiry_date if mr else None) or (master.price_expiry_date if master else None),
            price_source_reference=source_reference,
            price_last_updated_by=(mr.price_last_updated_by if mr and mr.price_source == "user_override"
                                   else (master.last_updated_by if master else (mr.price_last_updated_by if mr else None))),
            price_last_updated_at=(mr.price_last_updated_at.isoformat() if mr and mr.price_source == "user_override" and mr.price_last_updated_at
                                   else (master.last_updated_at.isoformat() if master and master.last_updated_at
                                         else (mr.price_last_updated_at.isoformat() if mr and mr.price_last_updated_at else None))),
            mapping_last_updated_by=mr.mapping_last_updated_by if mr else None,
            mapping_last_updated_at=mr.mapping_last_updated_at.isoformat() if mr and mr.mapping_last_updated_at else None,
            mapped_by=mr.mapped_by if mr else None,
            price_change_pending_review=master_changed,
            confidence=mr.confidence if mr else None,
            status=mr.status.value if mr else "mapping_unresolved",
            page=row.page,
            source_polygon=_source_polygon(row.region),
            source_origin=row.source_origin,
            source_provenance=row.source_provenance,
            azure_polygon_available=row.azure_polygon_available,
            error_reason=mr.unresolved_reason if mr else "Not yet mapped",
            evidence=mr.evidence if mr else None,
            overrides=override_map.get(row.row_id, []),
        ))

    return result


@router.post("/{job_id}/override")
async def record_override(
    job_id: str,
    req: OverrideRequest,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    row_q = await db.execute(
        select(BOQRow).where(BOQRow.job_id == job_id, BOQRow.row_id == req.row_id)
    )
    row = row_q.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Row '{req.row_id}' not found in job")

    allowed_fields = EDITABLE_SOURCE_FIELDS | {"master_item_id", "unit_price"}
    if req.field not in allowed_fields:
        raise HTTPException(400, f"Unsupported override field: {req.field}")

    actual_old_value = await _current_field_value(db, row, req.field)
    ov = Override(
        job_id=job_id,
        row_id=req.row_id,
        field=req.field,
        old_value=actual_old_value,
        new_value=req.new_value,
        user=req.user.strip() or "review-user",
    )
    db.add(ov)

    if req.field in EDITABLE_SOURCE_FIELDS:
        await _apply_source_correction(db, row, req)
    else:
        await _apply_override_and_reprice(db, row, req)

    await _refresh_job_status(db, job_id)
    await db.commit()
    return {
        "status": "override_recorded",
        "field": req.field,
        "old_value": actual_old_value,
        "new_value": req.new_value,
        "recalculated": req.field in {"unit", "quantity_raw", "row_type", "master_item_id", "unit_price"},
    }


@router.post("/{job_id}/rows", status_code=201)
async def add_review_row(job_id: str, req: AddRowRequest, db: AsyncSession = Depends(get_db)):
    """Append a user-authored row while preserving its manual provenance."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not req.description_vi.strip():
        raise HTTPException(400, "Vietnamese description is required")
    try:
        row_type = RowType(req.row_type)
    except ValueError as exc:
        raise HTTPException(400, "row_type must be heading, metadata, or line_item") from exc
    existing = list((await db.execute(
        select(BOQRow).where(BOQRow.job_id == job_id).order_by(BOQRow.doc_order)
    )).scalars())
    doc_order = (existing[-1].doc_order + 1) if existing else 1
    quantity = _parse_quantity(req.quantity_raw) if req.quantity_raw.strip() else None
    row_id = f"manual-{uuid.uuid4().hex[:12]}"
    section_path = req.section_path.strip() or "Bổ sung thủ công"
    inferred_group_code = section_path.replace(" / ", " > ").split(" > ")[-1].strip()
    row_number = ((req.row_number or "").strip()
                  or (inferred_group_code if row_type == RowType.heading else str(doc_order)))
    row = BOQRow(
        job_id=job_id, row_id=row_id, row_number=row_number,
        section_path=section_path,
        description_vi=req.description_vi.strip(), unit_raw=req.unit.strip() or None,
        quantity_raw=req.quantity_raw.strip() or None, quantity=quantity, page=1,
        region=None, row_type=row_type, doc_order=doc_order,
        source_origin="manual_entry",
        source_provenance=f"Added in Bản kê dự thầu by {req.user.strip() or 'local-reviewer'}",
        azure_polygon_available=False,
    )
    db.add(row)
    await db.flush()
    status = (MappingStatus.mapping_unresolved if row_type == RowType.line_item else
              MappingStatus.non_billable_heading if row_type == RowType.heading else MappingStatus.non_billable_metadata)
    db.add(MappingResult(
        boq_row_id=row.id, master_item_id=None, status=status,
        confidence=0.0 if row_type == RowType.line_item else 1.0,
        tags_json=json.dumps({}, ensure_ascii=False), evidence="User-authored row; catalogue selection required." if row_type == RowType.line_item else "User-authored structural row.",
        unresolved_reason="Chọn công việc trong danh mục và đơn giá có căn cứ." if row_type == RowType.line_item else None,
        master_version=MASTER_VERSION, pricing_availability="not_available" if row_type == RowType.line_item else NOT_APPLICABLE,
        mapping_last_updated_by=req.user.strip() or "local-reviewer", mapping_last_updated_at=datetime.now(timezone.utc),
        mapped_by=req.user.strip() or "local-reviewer",
    ))
    db.add(Override(job_id=job_id, row_id=row_id, field="row_added", old_value=None,
                    new_value=req.description_vi.strip(), user=req.user.strip() or "local-reviewer"))
    job.status = JobStatus.needs_review
    await db.commit()
    return {"status": "created", "row_id": row_id, "doc_order": doc_order,
            "source_origin": "manual_entry"}


async def _current_field_value(
    db: AsyncSession, row: BOQRow, field: str
) -> Optional[str]:
    values = {
        "description_vi": row.description_vi,
        "unit": row.unit_raw,
        "quantity_raw": row.quantity_raw,
        "row_type": row.row_type.value,
        "section_path": row.section_path,
    }
    if field in values:
        value = values[field]
        return None if value is None else str(value)
    mr_q = await db.execute(select(MappingResult).where(MappingResult.boq_row_id == row.id))
    mr = mr_q.scalar_one_or_none()
    if not mr:
        return None
    if field == "master_item_id":
        return None if mr.master_item_id is None else str(mr.master_item_id)
    if field == "unit_price":
        return mr.unit_price_str
    return None


async def _apply_source_correction(db: AsyncSession, row: BOQRow, req: OverrideRequest) -> None:
    new_value = req.new_value.strip()
    if req.field == "description_vi":
        if not new_value:
            raise HTTPException(400, "description_vi cannot be empty")
        row.description_vi = new_value
    elif req.field == "unit":
        row.unit_raw = new_value or None
    elif req.field == "quantity_raw":
        row.quantity_raw = new_value or None
        row.quantity = _parse_quantity(new_value)
    elif req.field == "section_path":
        row.section_path = new_value
    elif req.field == "row_type":
        try:
            row.row_type = RowType(new_value)
        except ValueError as exc:
            raise HTTPException(400, "row_type must be heading, metadata, or line_item") from exc

    mr_q = await db.execute(select(MappingResult).where(MappingResult.boq_row_id == row.id))
    mr = mr_q.scalar_one_or_none()
    if mr is None:
        return
    mr.mapping_last_updated_by = req.user.strip() or "review-user"
    mr.mapping_last_updated_at = datetime.now(timezone.utc)

    if row.row_type != RowType.line_item:
        mr.master_item_id = None
        mr.status = (
            MappingStatus.non_billable_heading
            if row.row_type == RowType.heading
            else MappingStatus.non_billable_metadata
        )
        mr.confidence = 1.0
        mr.unresolved_reason = None
        mr.unit_price_str = None
        mr.extended_amount_str = None
        mr.price_source = None
        mr.pricing_availability = NOT_APPLICABLE
        return

    if req.field == "description_vi":
        # A text correction changes the semantic evidence.  Preserve the old
        # candidate for provenance, but require the reviewer to confirm it.
        mr.status = MappingStatus.mapping_ambiguous
        mr.confidence = 0.0
        mr.unresolved_reason = "Description changed; confirm the master mapping before pricing."
        mr.unit_price_str = None
        mr.extended_amount_str = None
        mr.pricing_availability = "not_available"
        return

    if req.field in {"unit", "quantity_raw", "row_type"}:
        await _reprice_row(db, row, mr, unit_price_override=None)


async def _refresh_job_status(db: AsyncSession, job_id: str) -> None:
    job = await db.get(Job, job_id)
    if not job:
        return
    results = await db.execute(
        select(MappingResult)
        .join(BOQRow, BOQRow.id == MappingResult.boq_row_id)
        .where(BOQRow.job_id == job_id, BOQRow.row_type == RowType.line_item)
    )
    mappings = results.scalars().all()
    job.status = (
        JobStatus.ready
        if mappings and all(item.status == MappingStatus.mapped_and_priced for item in mappings)
        else JobStatus.needs_review
    )


@router.get("/{job_id}/candidates/{row_id}")
async def get_candidates(job_id: str, row_id: str, db: AsyncSession = Depends(get_db)):
    """Return all master items as replacement candidates for a BOQ row."""
    masters_q = await db.execute(
        select(MasterItem).where(
            MasterItem.tenant_id == DEMO_TENANT_ID,
            MasterItem.version == MASTER_VERSION,
            MasterItem.catalogue_status == "active",
        )
    )
    return [
        {
            "id": m.id,
            "item_code": m.item_code,
            "description_vi": m.description_vi,
            "long_description": m.long_description,
            "aliases": json.loads(m.aliases_json or "[]"),
            "category": m.category,
            "unit": m.unit,
            "unit_price": str(m.unit_price) if m.unit_price is not None else None,
            "pricing_availability": classify_price(
                m.unit_price, source_reference=m.price_source_reference or m.source_sheet,
                approval_status=m.approval_status, approved_by=m.approved_by,
                zero_price_authorized=m.zero_price_authorized,
            ).status,
            "price_effective_date": m.price_effective_date,
            "price_expiry_date": m.price_expiry_date,
            "price_source_reference": m.price_source_reference or m.source_sheet,
            "price_last_updated_by": m.last_updated_by,
            "price_last_updated_at": m.last_updated_at.isoformat() if m.last_updated_at else None,
        }
        for m in masters_q.scalars().all()
    ]


async def _apply_override_and_reprice(db: AsyncSession, row: BOQRow, req: OverrideRequest) -> None:
    if row.row_type != RowType.line_item:
        raise HTTPException(400, "Mapping and pricing overrides apply only to billable line items")

    mr_q = await db.execute(select(MappingResult).where(MappingResult.boq_row_id == row.id))
    mr = mr_q.scalar_one_or_none()

    if mr is None:
        mr = MappingResult(
            boq_row_id=row.id,
            master_item_id=None,
            status=MappingStatus.mapping_unresolved,
            confidence=0.0,
            tags_json=json.dumps({}, ensure_ascii=False),
            evidence="Created from manual override.",
            unresolved_reason="Awaiting user-selected master item",
            master_version=MASTER_VERSION,
            pricing_availability="not_available",
            mapping_last_updated_by=req.user.strip() or "review-user",
            mapping_last_updated_at=datetime.now(timezone.utc),
            mapped_by=None,
        )
        db.add(mr)
        await db.flush()

    if req.field == "master_item_id":
        if not req.new_value.strip():
            mr.master_item_id = None
            mr.status = MappingStatus.mapping_unresolved
            mr.confidence = 0.0
            mr.unresolved_reason = "Master mapping cleared by reviewer"
            mr.unit_price_str = None
            mr.extended_amount_str = None
            mr.price_source = None
            mr.pricing_availability = "not_available"
            mr.mapping_last_updated_by = req.user.strip() or "review-user"
            mr.mapping_last_updated_at = datetime.now(timezone.utc)
            return
        try:
            master_id = int(req.new_value)
        except ValueError as exc:
            raise HTTPException(400, "master_item_id must be an integer") from exc

        master = await db.get(MasterItem, master_id)
        if not master or master.tenant_id != DEMO_TENANT_ID or master.version != MASTER_VERSION:
            raise HTTPException(400, "Selected master item is not available for this tenant/version")

        mr.master_item_id = master_id
        if not mr.mapped_by:
            mr.mapped_by = req.user.strip() or "review-user"
        mr.status = MappingStatus.mapping_ambiguous
        mr.confidence = max(float(mr.confidence or 0.0), 0.99)
        mr.unresolved_reason = "Manual review required: selected master item must still pass price validation."
        mr.evidence = f"{(mr.evidence or '').strip()} [override: master_item_id={master_id}]".strip()
        mr.mapping_last_updated_by = req.user.strip() or "review-user"
        mr.mapping_last_updated_at = datetime.now(timezone.utc)
        mr.price_review_required = False
        await _reprice_row(db, row, mr, unit_price_override=None)
        return

    if req.field == "unit_price":
        try:
            unit_price = Decimal(req.new_value)
        except InvalidOperation as exc:
            raise HTTPException(400, "unit_price must be a valid decimal number") from exc
        if unit_price < 0:
            raise HTTPException(400, "unit_price must be non-negative")
        if mr.master_item_id is None:
            raise HTTPException(400, "Set master_item_id before overriding unit_price")
        availability = classify_price(
            unit_price,
            source_reference=req.price_source_reference,
            approval_status=req.price_approval_status,
            approved_by=req.price_approved_by,
            zero_price_authorized=req.zero_price_authorized,
        )
        if not availability.available:
            raise HTTPException(400, availability.reason or "Price is not available")
        if not req.price_effective_date:
            raise HTTPException(400, "price_effective_date is required for a manual price")
        await _reprice_row(db, row, mr, unit_price_override=unit_price, price_context={
            "availability": availability.status,
            "source_reference": req.price_source_reference,
            "effective_date": req.price_effective_date,
            "expiry_date": req.price_expiry_date,
            "approved_by": req.price_approved_by,
            "actor": req.user.strip() or "review-user",
        })


async def _reprice_row(
    db: AsyncSession,
    row: BOQRow,
    mr: MappingResult,
    unit_price_override: Optional[Decimal],
    price_context: Optional[dict] = None,
) -> None:
    if mr.master_item_id is None:
        mr.status = MappingStatus.mapping_unresolved
        mr.unresolved_reason = "No master item selected"
        mr.unit_price_str = None
        mr.extended_amount_str = None
        mr.pricing_availability = "not_available"
        return

    master = await db.get(MasterItem, mr.master_item_id)
    if not master:
        mr.status = MappingStatus.mapping_unresolved
        mr.unresolved_reason = f"Master item id={mr.master_item_id} not found"
        mr.unit_price_str = None
        mr.extended_amount_str = None
        mr.pricing_availability = "not_available"
        return

    boq_item = BOQLineItem(
        row_id=row.row_id,
        row_number=row.row_number or "",
        section_path=row.section_path,
        description_vi=row.description_vi,
        unit_raw=row.unit_raw or "",
        quantity_raw=row.quantity_raw or "",
        quantity=row.quantity,
        page=row.page,
        region=row.region or "",
        row_type=row.row_type.value,
        doc_order=row.doc_order,
        source_origin=row.source_origin,
        source_provenance=row.source_provenance or "",
        azure_polygon_available=row.azure_polygon_available,
    )

    rules_q = await db.execute(select(UnitRule).where(UnitRule.version == MASTER_VERSION))
    unit_rules = [{"from_unit": r.from_unit, "to_unit": r.to_unit, "factor": r.factor} for r in rules_q.scalars().all()]

    if unit_price_override is not None:
        if boq_item.quantity is None:
            mr.status = MappingStatus.invalid_quantity_or_unit
            mr.unresolved_reason = "Quantity is missing/unparseable — not defaulting to zero"
            mr.unit_price_str = None
            mr.extended_amount_str = None
            mr.pricing_availability = "not_available"
            return

        conversion_factor = Decimal("1")
        from_unit = (boq_item.unit_raw or "").strip().lower()
        to_unit = (master.unit or "").strip().lower()
        if from_unit != to_unit:
            rule = next(
                (r for r in unit_rules if r["from_unit"].strip().lower() == from_unit and r["to_unit"].strip().lower() == to_unit),
                None,
            )
            if rule is None:
                mr.status = MappingStatus.invalid_quantity_or_unit
                mr.unresolved_reason = f"Unit mismatch: PDF='{boq_item.unit_raw}' master='{master.unit}' with no approved conversion rule"
                mr.unit_price_str = None
                mr.extended_amount_str = None
                mr.pricing_availability = "not_available"
                return
            conversion_factor = Decimal(str(rule["factor"]))

        qty = Decimal(str(boq_item.quantity)) * conversion_factor
        extended = (unit_price_override * qty).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        mr.status = MappingStatus.mapped_and_priced
        mr.unresolved_reason = None
        mr.unit_price_str = str(unit_price_override.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        mr.extended_amount_str = str(extended)
        mr.price_source = "user_override"
        mr.pricing_availability = (price_context or {}).get("availability", "available")
        mr.price_source_reference = (price_context or {}).get("source_reference")
        mr.price_effective_date = (price_context or {}).get("effective_date")
        mr.price_expiry_date = (price_context or {}).get("expiry_date")
        mr.price_last_updated_by = (price_context or {}).get("actor")
        mr.price_last_updated_at = datetime.now(timezone.utc)
        mr.price_review_required = False
        mr.formula_ref = "OVERRIDE_UNIT_PRICE"
        mr.coeff_applied_json = json.dumps([], ensure_ascii=False)
        mr.master_version = MASTER_VERSION
        return

    coeff_q = await db.execute(select(Coefficient).where(Coefficient.version == MASTER_VERSION))
    coefficients = [
        {
            "coeff_code": c.coeff_code,
            "value": c.value,
            "applies_to": json.loads(c.applies_to) if c.applies_to else "all",
        }
        for c in coeff_q.scalars().all()
    ]
    master_dict = {
        master.id: {
            "id": master.id,
            "item_code": master.item_code,
            "description_vi": master.description_vi,
            "unit": master.unit,
            "unit_price": master.unit_price,
            "formula_ref": master.formula_ref,
            "source_sheet": master.source_sheet,
            "price_source_reference": master.price_source_reference,
            "approval_status": master.approval_status,
            "approved_by": master.approved_by,
            "zero_price_authorized": master.zero_price_authorized,
            "tags": json.loads(master.tags_json) if master.tags_json else {},
        }
    }

    mapping = MappingOutput(
        master_item_id=mr.master_item_id,
        confidence=float(mr.confidence or 0.0),
        tags=json.loads(mr.tags_json) if mr.tags_json else {},
        evidence=mr.evidence or "",
        unresolved_reason=mr.unresolved_reason,
        status="resolved",
    )
    engine = PricingEngine()
    price = engine.price_row(boq_item, mapping, master_dict, unit_rules, coefficients, MASTER_VERSION)
    if price.status == "priced":
        mr.status = MappingStatus.mapped_and_priced
        mr.unresolved_reason = None
    elif price.status == "unresolved":
        mr.status = MappingStatus.mapped_price_unavailable
        mr.unresolved_reason = price.error_reason
    else:
        mr.status = MappingStatus.mapping_unresolved
        mr.unresolved_reason = price.error_reason
    mr.unit_price_str = price.unit_price_str
    mr.extended_amount_str = price.extended_amount_str
    mr.price_source = price.price_source
    mr.pricing_availability = price.availability_status
    mr.price_source_reference = master.price_source_reference or master.source_sheet
    mr.price_effective_date = master.price_effective_date
    mr.price_expiry_date = master.price_expiry_date
    mr.price_last_updated_by = master.last_updated_by
    mr.price_last_updated_at = master.last_updated_at
    mr.price_review_required = False
    mr.formula_ref = price.formula_ref
    mr.coeff_applied_json = json.dumps(price.coeff_applied, ensure_ascii=False)
    mr.master_version = MASTER_VERSION
