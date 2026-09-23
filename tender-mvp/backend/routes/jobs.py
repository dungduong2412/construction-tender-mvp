"""
REST API Routes
===============
POST   /api/jobs                – upload PDF, trigger pipeline
GET    /api/jobs                – list jobs
GET    /api/jobs/{job_id}       – job status and pricing sheet
POST   /api/jobs/{job_id}/override  – record user override(s)
GET    /api/jobs/{job_id}/export    – download .xlsx
"""
from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..adapters.parser_adapter import parse_pdf
from ..engine.exporter import export_xlsx
from ..engine.mapper import map_boq_to_master
from ..engine.pricing import price_boq
from ..engine.reconstructor import reconstruct_boq
from ..models.domain import JobStatus, RowOverride, TenderJob
from ..models.store import create_job, get_job, list_jobs, update_job

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Background pipeline task
# ---------------------------------------------------------------------------

async def _run_pipeline(job_id: str, pdf_bytes: bytes, filename: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    try:
        # 1. Parse
        job.status = JobStatus.PARSING
        update_job(job)
        parsed = await parse_pdf(job_id, filename, pdf_bytes)
        job.parsed_document = parsed

        # 2. Reconstruct BOQ
        boq = reconstruct_boq(parsed)
        job.boq_document = boq

        # 3. Map to master
        job.status = JobStatus.MAPPING
        update_job(job)
        mapping_results = map_boq_to_master(boq)

        # 4. Price
        job.status = JobStatus.PRICING
        update_job(job)
        pricing_sheet = price_boq(boq, mapping_results, job.overrides)
        job.pricing_sheet = pricing_sheet

        # 5. Determine final status
        if pricing_sheet.unresolved_count > 0:
            job.status = JobStatus.NEEDS_REVIEW
        else:
            job.status = JobStatus.READY
        update_job(job)

    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error = str(exc) + "\n" + traceback.format_exc()
        update_job(job)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/jobs", summary="Upload PDF and start pipeline")
async def upload_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    job = create_job(file.filename)
    background_tasks.add_task(_run_pipeline, job.job_id, pdf_bytes, file.filename)
    return {"job_id": job.job_id, "status": job.status}


@router.get("/jobs", summary="List all jobs")
async def get_jobs():
    jobs = list_jobs()
    return [
        {
            "job_id": j.job_id,
            "filename": j.filename,
            "status": j.status,
            "unresolved_count": (
                j.pricing_sheet.unresolved_count if j.pricing_sheet else None
            ),
        }
        for j in jobs
    ]


@router.get("/jobs/{job_id}", summary="Get job status and pricing sheet")
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response: dict = {
        "job_id": job.job_id,
        "filename": job.filename,
        "status": job.status,
        "error": job.error,
    }

    if job.pricing_sheet:
        ps = job.pricing_sheet
        response["pricing"] = {
            "master_data_version": ps.master_data_version,
            "subtotal_priced_vnd": ps.subtotal_priced_vnd,
            "unresolved_count": ps.unresolved_count,
            "is_complete": ps.is_complete,
            "notes": ps.notes,
            "lines": [
                {
                    "row_id": l.row_id,
                    "description_vi": l.description_vi,
                    "source_section": l.source_section,
                    "unit_pdf": l.unit_pdf,
                    "quantity": str(l.quantity) if l.quantity is not None else None,
                    "master_id": l.master_id,
                    "master_code": l.master_code,
                    "master_description": l.master_description,
                    "unit_master": l.unit_master,
                    "unit_price": l.unit_price,
                    "extended_amount": l.extended_amount,
                    "confidence": l.confidence,
                    "status": l.status,
                    "exception_reason": l.exception_reason,
                    "source_page": l.source_page,
                    "evidence": l.evidence,
                }
                for l in ps.lines
            ],
        }

    return response


class OverrideRequest(BaseModel):
    overrides: List[RowOverride]


@router.post("/jobs/{job_id}/override", summary="Submit user overrides and re-price")
async def submit_override(job_id: str, body: OverrideRequest):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.NEEDS_REVIEW, JobStatus.READY):
        raise HTTPException(
            status_code=400,
            detail=f"Job is in status {job.status}; overrides only accepted in needs_review or ready",
        )
    if not job.boq_document or not job.pricing_sheet:
        raise HTTPException(status_code=400, detail="Job has no pricing sheet yet")

    # Merge overrides
    override_map = {o.row_id: o for o in job.overrides}
    for ov in body.overrides:
        override_map[ov.row_id] = ov
    job.overrides = list(override_map.values())

    # Re-map and re-price
    mapping_results = map_boq_to_master(job.boq_document)
    job.pricing_sheet = price_boq(job.boq_document, mapping_results, job.overrides)

    job.status = (
        JobStatus.READY if job.pricing_sheet.unresolved_count == 0 else JobStatus.NEEDS_REVIEW
    )
    update_job(job)

    return {
        "job_id": job_id,
        "status": job.status,
        "unresolved_count": job.pricing_sheet.unresolved_count,
    }


@router.get("/jobs/{job_id}/export", summary="Download .xlsx bid worksheet")
async def export_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.pricing_sheet:
        raise HTTPException(status_code=400, detail="Job has no pricing sheet to export")

    xlsx_path = export_xlsx(job.pricing_sheet, output_dir="/tmp")
    job.excel_path = xlsx_path
    job.status = JobStatus.EXPORTED
    update_job(job)

    return FileResponse(
        path=xlsx_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(xlsx_path).name,
    )
