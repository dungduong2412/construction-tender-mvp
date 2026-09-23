"""Jobs router — upload PDF, query job status."""
import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    BOQRow, Job, JobStatus, MappingResult, MappingStatus,
    MasterItem, ParsedDocument, UnitRule, Coefficient, RowType, get_db,
)
from parser_adapter.adapter import ParserAdapter, ParserAdapterError
from parser_adapter.normalizer import DocumentNormalizer
from boq.reconstructor import BOQReconstructor
from semantic_mapper.mapper import MasterCandidate, SemanticMapper
from pricing_engine.engine import PricingEngine

DEMO_TENANT_ID = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")
MASTER_VERSION = os.getenv("MASTER_DATA_VERSION", "v1")

router = APIRouter()


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    filename: str
    error_message: Optional[str] = None
    row_count: Optional[int] = None
    unresolved_count: Optional[int] = None


@router.post("/upload", response_model=JobStatusResponse)
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        tenant_id=DEMO_TENANT_ID,
        filename=file.filename,
        status=JobStatus.uploaded,
    )
    db.add(job)
    await db.commit()

    pdf_bytes = await file.read()
    background_tasks.add_task(_process_job, job_id, pdf_bytes, file.filename)

    return JobStatusResponse(
        job_id=job_id,
        status=JobStatus.uploaded,
        filename=file.filename,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    row_count = await db.scalar(
        select(func.count()).select_from(BOQRow).where(BOQRow.job_id == job_id)
    )
    unresolved = await db.scalar(
        select(func.count())
        .select_from(MappingResult)
        .join(BOQRow, BOQRow.id == MappingResult.boq_row_id)
        .where(
            BOQRow.job_id == job_id,
            MappingResult.status.in_([MappingStatus.unresolved, MappingStatus.error]),
        )
    )

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        filename=job.filename,
        error_message=job.error_message,
        row_count=int(row_count or 0),
        unresolved_count=int(unresolved or 0),
    )


@router.get("/", response_model=list[JobStatusResponse])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(50))
    jobs = result.scalars().all()
    return [
        JobStatusResponse(
            job_id=j.id,
            status=j.status,
            filename=j.filename,
            error_message=j.error_message,
        )
        for j in jobs
    ]


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------

async def _process_job(job_id: str, pdf_bytes: bytes, filename: str) -> None:
    from database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        try:
            # --- PARSING ---
            job.status = JobStatus.parsing
            await db.commit()

            adapter = ParserAdapter()
            raw_result = await adapter.analyze(pdf_bytes)

            normalizer = DocumentNormalizer()
            parsed = normalizer.normalize(raw_result)

            pd_record = ParsedDocument(
                job_id=job_id,
                raw_json=json.dumps(raw_result, ensure_ascii=False),
                page_count=parsed.page_count,
                model_id=parsed.model_id,
                api_version=parsed.api_version,
            )
            db.add(pd_record)
            await db.commit()

            # --- BOQ RECONSTRUCTION ---
            reconstructor = BOQReconstructor()
            boq_items = reconstructor.reconstruct(parsed.boq_rows)

            for item in boq_items:
                row_type_enum = RowType[item.row_type]
                boq_row = BOQRow(
                    job_id=job_id,
                    row_id=item.row_id,
                    row_number=item.row_number,
                    section_path=item.section_path,
                    description_vi=item.description_vi,
                    unit_raw=item.unit_raw,
                    quantity_raw=item.quantity_raw,
                    quantity=item.quantity,
                    page=item.page,
                    region=item.region,
                    row_type=row_type_enum,
                    doc_order=item.doc_order,
                )
                db.add(boq_row)
            await db.commit()

            # --- MAPPING + PRICING ---
            job.status = JobStatus.mapping
            await db.commit()

            # Load master data
            masters_q = await db.execute(
                select(MasterItem).where(
                    MasterItem.tenant_id == DEMO_TENANT_ID,
                    MasterItem.version == MASTER_VERSION,
                )
            )
            master_list = masters_q.scalars().all()
            master_dict = {
                m.id: {
                    "id": m.id,
                    "item_code": m.item_code,
                    "description_vi": m.description_vi,
                    "unit": m.unit,
                    "unit_price": m.unit_price,
                    "formula_ref": m.formula_ref,
                    "tags": json.loads(m.tags_json) if m.tags_json else {},
                }
                for m in master_list
            }

            unit_rules_q = await db.execute(
                select(UnitRule).where(UnitRule.version == MASTER_VERSION)
            )
            unit_rules = [
                {"from_unit": r.from_unit, "to_unit": r.to_unit, "factor": r.factor}
                for r in unit_rules_q.scalars().all()
            ]

            coeffs_q = await db.execute(
                select(Coefficient).where(Coefficient.version == MASTER_VERSION)
            )
            coefficients = [
                {
                    "coeff_code": c.coeff_code,
                    "value": c.value,
                    "applies_to": json.loads(c.applies_to) if c.applies_to else "all",
                }
                for c in coeffs_q.scalars().all()
            ]

            mapper = SemanticMapper()
            engine = PricingEngine()

            boq_rows_q = await db.execute(
                select(BOQRow).where(BOQRow.job_id == job_id).order_by(BOQRow.doc_order)
            )
            db_rows = boq_rows_q.scalars().all()

            # --- PRICING ---
            job.status = JobStatus.pricing
            await db.commit()

            for db_row in db_rows:
                # Build candidates (all master items as candidates for now; real system would use embeddings)
                candidates = [
                    MasterCandidate(
                        id=v["id"],
                        item_code=v["item_code"],
                        description_vi=v["description_vi"],
                        unit=v["unit"],
                        unit_price=v["unit_price"],
                        tags=v["tags"],
                    )
                    for v in master_dict.values()
                ]

                # Reconstruct BOQLineItem
                from boq.reconstructor import BOQLineItem
                boq_item = BOQLineItem(
                    row_id=db_row.row_id,
                    row_number=db_row.row_number or "",
                    section_path=db_row.section_path,
                    description_vi=db_row.description_vi,
                    unit_raw=db_row.unit_raw or "",
                    quantity_raw=db_row.quantity_raw or "",
                    quantity=db_row.quantity,
                    page=db_row.page,
                    region=db_row.region or "",
                    row_type=db_row.row_type.value,
                    doc_order=db_row.doc_order,
                )

                mapping_out = await mapper.map_item(boq_item, candidates, MASTER_VERSION)

                price_out = engine.price_row(
                    boq_item, mapping_out, master_dict, unit_rules, coefficients, MASTER_VERSION
                )

                status_map = {
                    "resolved": MappingStatus.resolved,
                    "unresolved": MappingStatus.unresolved,
                    "error": MappingStatus.error,
                }

                mr = MappingResult(
                    boq_row_id=db_row.id,
                    master_item_id=mapping_out.master_item_id,
                    status=status_map.get(mapping_out.status, MappingStatus.unresolved),
                    confidence=mapping_out.confidence,
                    tags_json=json.dumps(mapping_out.tags, ensure_ascii=False),
                    evidence=mapping_out.evidence,
                    unresolved_reason=mapping_out.unresolved_reason,
                    unit_price_str=price_out.unit_price_str,
                    extended_amount_str=price_out.extended_amount_str,
                    price_source=price_out.price_source,
                    formula_ref=price_out.formula_ref,
                    coeff_applied_json=json.dumps(price_out.coeff_applied, ensure_ascii=False),
                    master_version=MASTER_VERSION,
                )
                db.add(mr)

            await db.commit()

            # Reload mapping results to determine final job status
            mrs = await db.execute(
                select(MappingResult).join(BOQRow).where(BOQRow.job_id == job_id)
            )
            mr_list = mrs.scalars().all()
            has_unresolved = any(
                m.status in (MappingStatus.unresolved, MappingStatus.error)
                for m in mr_list
            )
            job.status = JobStatus.needs_review if has_unresolved else JobStatus.ready
            await db.commit()

        except ParserAdapterError as exc:
            job.status = JobStatus.failed
            job.error_message = f"Parser error: {exc}"
            await db.commit()
        except Exception as exc:
            job.status = JobStatus.failed
            job.error_message = f"Pipeline error: {type(exc).__name__}: {exc}"
            await db.commit()
            raise
