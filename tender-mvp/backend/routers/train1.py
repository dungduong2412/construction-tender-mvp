from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi import File, UploadFile
from fastapi import Header
from fastapi.responses import Response
from pydantic import BaseModel

from integration_train1.pipeline import (
    PIPELINE,
    ParserProviderAuthError,
    ParserProviderContractError,
    ParserProviderError,
    ParserProviderTimeoutError,
    Train2PipelineError,
)

router = APIRouter()


class ManualOverrideRequest(BaseModel):
    row_id: str
    canonical_code: str
    reason: str | None = None


class PriceMutationRequest(BaseModel):
    price_updates: dict[str, str]


@router.post("/runs/fixture")
async def start_run_from_fixture():
    return await PIPELINE.start_from_fixture()


@router.post("/runs/real-fixture")
async def start_run_from_recorded_real_fixture():
    return await PIPELINE.start_from_real_fixture()


@router.post("/runs/upload")
async def start_run_from_upload(file: UploadFile = File(...), authorization: str | None = Header(default=None)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    expected_token = os.getenv("TRAIN2_UPLOAD_AUTH_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="LIVE INTEGRATION BLOCKED: TRAIN2_UPLOAD_AUTH_TOKEN is not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer authorization token")
    supplied_token = authorization.split(" ", 1)[1].strip()
    if supplied_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid upload authorization token")

    endpoint = os.getenv("TRAIN2_PARSER_API_ENDPOINT", "").strip()
    api_key = os.getenv("TRAIN2_PARSER_API_KEY", "").strip() or None
    api_key_header = os.getenv("TRAIN2_PARSER_API_KEY_HEADER", "Authorization")
    api_key_prefix = os.getenv("TRAIN2_PARSER_API_KEY_PREFIX", "Bearer")
    timeout_seconds = float(os.getenv("TRAIN2_PARSER_API_TIMEOUT_SECONDS", "30"))

    try:
        pdf_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to read uploaded PDF") from exc
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

    max_upload_bytes = int(os.getenv("TRAIN2_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    if len(pdf_bytes) > max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Uploaded PDF exceeds size limit ({max_upload_bytes} bytes)")

    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file does not have a valid PDF signature")

    if not endpoint:
        raise HTTPException(status_code=503, detail="LIVE INTEGRATION BLOCKED: TRAIN2_PARSER_API_ENDPOINT is not configured")
    if not api_key:
        raise HTTPException(status_code=503, detail="LIVE INTEGRATION BLOCKED: TRAIN2_PARSER_API_KEY is not configured")

    try:
        return await PIPELINE.start_from_parser_api(
            pdf_bytes=pdf_bytes,
            endpoint=endpoint,
            api_key=api_key,
            api_key_header=api_key_header,
            api_key_prefix=api_key_prefix,
            timeout_seconds=timeout_seconds,
        )
    except ParserProviderAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ParserProviderTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ParserProviderContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ParserProviderError, Train2PipelineError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/runs/{run_id}/review")
async def get_review(run_id: str):
    try:
        return PIPELINE.get_review(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/override")
async def override_mapping(run_id: str, req: ManualOverrideRequest):
    try:
        return PIPELINE.apply_manual_mapping(run_id, req.row_id, req.canonical_code, req.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/mutate-prices")
async def mutate_prices(run_id: str, req: PriceMutationRequest):
    try:
        return PIPELINE.mutate_runtime_prices(run_id, req.price_updates)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/export.xlsx")
async def export_xlsx(run_id: str):
    try:
        content = PIPELINE.export_excel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="train1_{run_id}.xlsx"'},
    )
