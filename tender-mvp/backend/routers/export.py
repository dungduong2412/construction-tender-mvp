"""Export router — internal draft and governed final submission workbooks."""
import hashlib
import os
import re
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import ExportRecord, Job, get_db
from calculation_snapshots import build_snapshot, load_snapshot
from excel_exporter.exporter import (
    generate_estimate_schedule,
    generate_internal_workbook,
    generate_submission_workbook,
)

router = APIRouter()


def _export_storage_dir() -> Path:
    configured = os.getenv("EXPORT_STORAGE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "runtime" / "exports").resolve()


async def _persist_export(
    db: AsyncSession,
    *,
    job_id: str,
    snapshot_id: str,
    export_type: str,
    filename: str,
    content: bytes,
) -> ExportRecord:
    export_id = str(uuid.uuid4())
    stored_name = f"{export_id}_{filename}"
    destination = _export_storage_dir() / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
        record = ExportRecord(
            id=export_id,
            job_id=job_id,
            snapshot_id=snapshot_id,
            export_type=export_type,
            file_name=stored_name,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record
    except Exception:
        destination.unlink(missing_ok=True)
        await db.rollback()
        raise
    finally:
        temporary.unlink(missing_ok=True)


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
    content = generate_internal_workbook(snapshot)
    filename = f'{_safe_stem(job.filename)}_internal_{snapshot["snapshot_id"]}.xlsx'
    record = await _persist_export(
        db, job_id=job_id, snapshot_id=snapshot["snapshot_id"], export_type="internal",
        filename=filename, content=content,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Calculation-Snapshot": snapshot["snapshot_id"],
            "X-Export-Status": "draft" if not snapshot["export_policy"]["final_submission_allowed"] else "complete",
            "X-Export-ID": record.id,
            "X-Export-Path": record.file_name,
        },
    )


@router.get("/{job_id}/estimate.xlsx")
async def export_estimate_schedule(
    job_id: str,
    view: str = Query(default="tender", pattern="^(approval|tender)$"),
    snapshot_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    job, snapshot = await _snapshot_for_export(job_id, snapshot_id, db)
    content = generate_estimate_schedule(snapshot, view)
    label = "phe_duyet_noi_bo" if view == "approval" else "du_thau"
    filename = f'{_safe_stem(job.filename)}_{label}_{snapshot["snapshot_id"]}.xlsx'
    incomplete = (snapshot.get(view) or {}).get("status") != "COMPLETE"
    record = await _persist_export(db, job_id=job_id, snapshot_id=snapshot["snapshot_id"],
                                   export_type=f"estimate_{view}", filename=filename, content=content)
    return Response(content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Calculation-Snapshot": snapshot["snapshot_id"],
                 "X-Export-Status": "draft-incomplete" if incomplete else "complete",
                 "X-Export-ID": record.id, "X-Export-Path": record.file_name})


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
    filename = f'{_safe_stem(job.filename)}_submission_{snapshot["snapshot_id"]}.xlsx'
    record = await _persist_export(
        db, job_id=job_id, snapshot_id=snapshot["snapshot_id"], export_type="final",
        filename=filename, content=content,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Calculation-Snapshot": snapshot["snapshot_id"],
            "X-Export-Status": "final",
            "X-Export-ID": record.id,
            "X-Export-Path": record.file_name,
        },
    )


@router.get("/{job_id}/xlsx")
async def export_xlsx(job_id: str, db: AsyncSession = Depends(get_db)):
    # Backwards-compatible draft link; all new exports share the immutable snapshot path.
    return await export_internal_xlsx(job_id=job_id, snapshot_id=None, db=db)


@router.get("/{job_id}/records")
async def list_export_records(job_id: str, db: AsyncSession = Depends(get_db)):
    if not await db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    records = list((await db.execute(
        select(ExportRecord).where(ExportRecord.job_id == job_id).order_by(ExportRecord.created_at)
    )).scalars())
    return [{
        "export_id": record.id,
        "snapshot_id": record.snapshot_id,
        "export_type": record.export_type,
        "file_name": record.file_name,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    } for record in records]


@router.get("/{job_id}/records/{export_id}")
async def download_export_record(job_id: str, export_id: str, db: AsyncSession = Depends(get_db)):
    record = await db.get(ExportRecord, export_id)
    if not record or record.job_id != job_id:
        raise HTTPException(404, "Export record not found")
    path = _export_storage_dir() / record.file_name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record.sha256:
        raise HTTPException(409, "Stored export is missing or failed integrity validation")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=record.file_name.split("_", 1)[-1],
        headers={"X-Export-ID": record.id, "X-Calculation-Snapshot": record.snapshot_id},
    )
