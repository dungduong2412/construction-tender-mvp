"""Export router — internal draft and governed final submission workbooks."""
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from database import Job, get_db
from calculation_snapshots import build_snapshot, load_snapshot
from excel_exporter.exporter import (
    generate_internal_workbook,
    generate_submission_workbook,
)

router = APIRouter()


async def _snapshot_for_export(
    job_id: str, snapshot_id: str | None, db: AsyncSession
) -> tuple[Job, dict]:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    snapshot = load_snapshot(snapshot_id) if snapshot_id else await build_snapshot(db, job_id)
    if not snapshot or snapshot.get("job", {}).get("id") != job_id:
        raise HTTPException(404, "Calculation snapshot not found for this job")
    return job, snapshot


def _safe_stem(filename: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]", "_", filename.rsplit(".", 1)[0])
    return value or "boq"


@router.get("/{job_id}/internal.xlsx")
async def export_internal_xlsx(
    job_id: str,
    snapshot_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    job, snapshot = await _snapshot_for_export(job_id, snapshot_id, db)
    return Response(
        content=generate_internal_workbook(snapshot),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_stem(job.filename)}_internal_{snapshot["snapshot_id"]}.xlsx"',
            "X-Calculation-Snapshot": snapshot["snapshot_id"],
            "X-Export-Status": "draft" if not snapshot["export_policy"]["final_submission_allowed"] else "complete",
        },
    )


@router.get("/{job_id}/final.xlsx")
async def export_final_xlsx(
    job_id: str,
    snapshot_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    job, snapshot = await _snapshot_for_export(job_id, snapshot_id, db)
    try:
        content = generate_submission_workbook(snapshot)
    except ValueError as exc:
        raise HTTPException(409, {"message": str(exc), "block_reasons": snapshot["export_policy"]["final_block_reasons"]}) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{_safe_stem(job.filename)}_submission_{snapshot["snapshot_id"]}.xlsx"',
            "X-Calculation-Snapshot": snapshot["snapshot_id"],
            "X-Export-Status": "final",
        },
    )


@router.get("/{job_id}/xlsx")
async def export_xlsx(job_id: str, db: AsyncSession = Depends(get_db)):
    # Backwards-compatible draft link; all new exports share the immutable snapshot path.
    return await export_internal_xlsx(job_id=job_id, snapshot_id=None, db=db)
