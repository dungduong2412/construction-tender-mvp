"""Review router — return BOQ rows with pricing, accept user overrides."""
import json
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    BOQRow, Job, MappingResult, MappingStatus, MasterItem, Override, UnitRule, Coefficient, get_db,
)
from boq.reconstructor import BOQLineItem
from pricing_engine.engine import PricingEngine
from semantic_mapper.mapper import MappingOutput

DEMO_TENANT_ID = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")
MASTER_VERSION = os.getenv("MASTER_DATA_VERSION", "v1")

router = APIRouter()


class ReviewRow(BaseModel):
    row_id: str
    row_number: str
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
    confidence: Optional[float]
    status: str
    page: int
    error_reason: Optional[str]
    evidence: Optional[str]
    overrides: list[dict]


class OverrideRequest(BaseModel):
    row_id: str
    field: str
    old_value: Optional[str]
    new_value: str
    user: str = "demo-user"


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
        )
    )
    master_map = {m.id: m for m in masters_q.scalars().all()}

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
        })

    result = []
    for row in boq_rows:
        mr = mapping_map.get(row.id)
        master = master_map.get(mr.master_item_id) if mr and mr.master_item_id else None

        result.append(ReviewRow(
            row_id=row.row_id,
            row_number=row.row_number or "",
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
            confidence=mr.confidence if mr else None,
            status=mr.status.value if mr else "unresolved",
            page=row.page,
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

    ov = Override(
        job_id=job_id,
        row_id=req.row_id,
        field=req.field,
        old_value=req.old_value,
        new_value=req.new_value,
        user=req.user,
    )
    db.add(ov)

    row_q = await db.execute(
        select(BOQRow).where(BOQRow.job_id == job_id, BOQRow.row_id == req.row_id)
    )
    row = row_q.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Row '{req.row_id}' not found in job")

    if req.field in {"master_item_id", "unit_price"}:
        await _apply_override_and_reprice(db, row, req)

    await db.commit()
    return {"status": "override_recorded", "recalculated": req.field in {"master_item_id", "unit_price"}}


@router.get("/{job_id}/candidates/{row_id}")
async def get_candidates(job_id: str, row_id: str, db: AsyncSession = Depends(get_db)):
    """Return all master items as replacement candidates for a BOQ row."""
    masters_q = await db.execute(
        select(MasterItem).where(
            MasterItem.tenant_id == DEMO_TENANT_ID,
            MasterItem.version == MASTER_VERSION,
        )
    )
    return [
        {
            "id": m.id,
            "item_code": m.item_code,
            "description_vi": m.description_vi,
            "unit": m.unit,
            "unit_price": m.unit_price,
        }
        for m in masters_q.scalars().all()
    ]


async def _apply_override_and_reprice(db: AsyncSession, row: BOQRow, req: OverrideRequest) -> None:
    mr_q = await db.execute(select(MappingResult).where(MappingResult.boq_row_id == row.id))
    mr = mr_q.scalar_one_or_none()

    if mr is None:
        mr = MappingResult(
            boq_row_id=row.id,
            master_item_id=None,
            status=MappingStatus.unresolved,
            confidence=0.0,
            tags_json=json.dumps({}, ensure_ascii=False),
            evidence="Created from manual override.",
            unresolved_reason="Awaiting user-selected master item",
            master_version=MASTER_VERSION,
        )
        db.add(mr)
        await db.flush()

    if req.field == "master_item_id":
        try:
            master_id = int(req.new_value)
        except ValueError as exc:
            raise HTTPException(400, "master_item_id must be an integer") from exc

        master = await db.get(MasterItem, master_id)
        if not master or master.tenant_id != DEMO_TENANT_ID or master.version != MASTER_VERSION:
            raise HTTPException(400, "Selected master item is not available for this tenant/version")

        mr.master_item_id = master_id
        mr.status = MappingStatus.resolved
        mr.confidence = max(float(mr.confidence or 0.0), 0.99)
        mr.unresolved_reason = None
        mr.evidence = f"{(mr.evidence or '').strip()} [override: master_item_id={master_id}]".strip()
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
        await _reprice_row(db, row, mr, unit_price_override=unit_price)


async def _reprice_row(
    db: AsyncSession,
    row: BOQRow,
    mr: MappingResult,
    unit_price_override: Optional[Decimal],
) -> None:
    if mr.master_item_id is None:
        mr.status = MappingStatus.unresolved
        mr.unresolved_reason = "No master item selected"
        mr.unit_price_str = None
        mr.extended_amount_str = None
        return

    master = await db.get(MasterItem, mr.master_item_id)
    if not master:
        mr.status = MappingStatus.error
        mr.unresolved_reason = f"Master item id={mr.master_item_id} not found"
        mr.unit_price_str = None
        mr.extended_amount_str = None
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
    )

    rules_q = await db.execute(select(UnitRule).where(UnitRule.version == MASTER_VERSION))
    unit_rules = [{"from_unit": r.from_unit, "to_unit": r.to_unit, "factor": r.factor} for r in rules_q.scalars().all()]

    if unit_price_override is not None:
        if boq_item.quantity is None:
            mr.status = MappingStatus.unresolved
            mr.unresolved_reason = "Quantity is missing/unparseable — not defaulting to zero"
            mr.unit_price_str = None
            mr.extended_amount_str = None
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
                mr.status = MappingStatus.unresolved
                mr.unresolved_reason = f"Unit mismatch: PDF='{boq_item.unit_raw}' master='{master.unit}' with no approved conversion rule"
                mr.unit_price_str = None
                mr.extended_amount_str = None
                return
            conversion_factor = Decimal(str(rule["factor"]))

        qty = Decimal(str(boq_item.quantity)) * conversion_factor
        extended = (unit_price_override * qty).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        mr.status = MappingStatus.resolved
        mr.unresolved_reason = None
        mr.unit_price_str = str(unit_price_override.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        mr.extended_amount_str = str(extended)
        mr.price_source = "user_override"
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
        mr.status = MappingStatus.resolved
        mr.unresolved_reason = None
    elif price.status == "unresolved":
        mr.status = MappingStatus.unresolved
        mr.unresolved_reason = price.error_reason
    else:
        mr.status = MappingStatus.error
        mr.unresolved_reason = price.error_reason
    mr.unit_price_str = price.unit_price_str
    mr.extended_amount_str = price.extended_amount_str
    mr.price_source = price.price_source
    mr.formula_ref = price.formula_ref
    mr.coeff_applied_json = json.dumps(price.coeff_applied, ensure_ascii=False)
    mr.master_version = MASTER_VERSION
