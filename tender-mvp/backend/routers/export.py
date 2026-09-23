"""Export router — generate and download the Excel bid worksheet."""
import json
import os
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import BOQRow, Job, MappingResult, MasterItem, Override, get_db
from excel_exporter.exporter import ExportRow, generate_excel

DEMO_TENANT_ID = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")
MASTER_VERSION = os.getenv("MASTER_DATA_VERSION", "v1")

router = APIRouter()


@router.get("/{job_id}/xlsx")
async def export_xlsx(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    rows_q = await db.execute(
        select(BOQRow).where(BOQRow.job_id == job_id).order_by(BOQRow.doc_order)
    )
    boq_rows = rows_q.scalars().all()
    boq_row_ids = [r.id for r in boq_rows]

    mapping_map = {}
    if boq_row_ids:
        mr_q = await db.execute(select(MappingResult).where(MappingResult.boq_row_id.in_(boq_row_ids)))
        mapping_map = {m.boq_row_id: m for m in mr_q.scalars().all()}

    masters_q = await db.execute(
        select(MasterItem).where(
            MasterItem.tenant_id == DEMO_TENANT_ID,
            MasterItem.version == MASTER_VERSION,
        )
    )
    master_map = {m.id: m for m in masters_q.scalars().all()}

    overrides_q = await db.execute(select(Override).where(Override.job_id == job_id))
    override_map: dict[str, list[dict]] = {}
    for ov in overrides_q.scalars().all():
        override_map.setdefault(ov.row_id, []).append({
            "field": ov.field,
            "old_value": ov.old_value,
            "new_value": ov.new_value,
        })

    export_rows: list[ExportRow] = []
    for row in boq_rows:
        mr = mapping_map.get(row.id)
        master = master_map.get(mr.master_item_id) if mr and mr.master_item_id else None
        status = mr.status.value if mr else "mapping_unresolved"
        if row.row_type.value == "heading":
            status = "non_billable_heading"
        elif row.row_type.value == "metadata":
            status = "non_billable_metadata"
        elif mr and mr.status.value == "mapped_and_priced" and mr.unit_price_str and mr.extended_amount_str:
            status = "mapped_and_priced"
        coeff_applied = json.loads(mr.coeff_applied_json) if (mr and mr.coeff_applied_json) else []

        export_rows.append(ExportRow(
            stt=row.row_number or row.row_id,
            section=row.section_path,
            description_vi=row.description_vi,
            unit=row.unit_raw or "",
            quantity_raw=row.quantity_raw or "",
            quantity=row.quantity,
            master_code=master.item_code if master else None,
            master_desc=master.description_vi if master else None,
            unit_price_str=mr.unit_price_str if mr else None,
            extended_amount_str=mr.extended_amount_str if mr else None,
            confidence=mr.confidence if mr else None,
            page=row.page,
            status=status,
            error_reason=mr.unresolved_reason if mr else "Not yet mapped",
            formula_ref=mr.formula_ref if mr else None,
            coeff_applied=coeff_applied,
            unit_rule_ref=str(mr.unit_rule_id) if (mr and mr.unit_rule_id is not None) else None,
            evidence=mr.evidence if mr else None,
            overrides=override_map.get(row.row_id, []),
        ))

    xlsx_bytes = generate_excel(export_rows, job_id)
    safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", job.filename.replace(".pdf", ""))
    if not safe_filename:
        safe_filename = "boq"

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}_du_thau.xlsx"'
        },
    )
