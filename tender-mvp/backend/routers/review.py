"""Review router — return BOQ rows with pricing, accept user overrides."""
import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    BOQRow, Job, MappingResult, MappingStatus, MasterItem, Override, get_db,
)

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
        mr = row.mapping_result
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
    await db.commit()
    return {"status": "override_recorded"}


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
