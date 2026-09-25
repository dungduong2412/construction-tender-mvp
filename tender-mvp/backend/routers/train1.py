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


def _parser_provider_mode() -> str:
    mode = os.getenv("TRAIN2_PARSER_PROVIDER", "").strip().lower()
    if mode in {"azure", "document-intelligence", "docintel", "doc_intel"}:
        return "azure"
    if mode in {"http_json", "http-json", "normalized", "parser_api", "http"}:
        return "http_json"
    return "http_json"


def _require_train_auth(authorization: str | None) -> None:
    expected_token = os.getenv("TRAIN2_UPLOAD_AUTH_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="LIVE INTEGRATION BLOCKED: TRAIN2_UPLOAD_AUTH_TOKEN is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer authorization token")
    supplied_token = authorization.split(" ", 1)[1].strip()
    if supplied_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid upload authorization token")


def _fixture_mode_enabled() -> bool:
    env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "")).strip().lower()
    return env in {"", "local", "test", "testing", "dev", "development"}


class ManualOverrideRequest(BaseModel):
    row_id: str
    canonical_code: str
    reason: str | None = None
    unit_confirmed: bool = False
    unit_correction: str | None = None


class PriceMutationRequest(BaseModel):
    price_updates: dict[str, str]


@router.post("/runs/fixture")
async def start_run_from_fixture(authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    if not _fixture_mode_enabled():
        raise HTTPException(status_code=403, detail="Fixture mode is disabled outside local/test environments")
    return await PIPELINE.start_from_fixture()


@router.post("/runs/real-fixture")
async def start_run_from_recorded_real_fixture(authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    if not _fixture_mode_enabled():
        raise HTTPException(status_code=403, detail="Fixture mode is disabled outside local/test environments")
    return await PIPELINE.start_from_real_fixture()


@router.post("/runs/upload")
async def start_run_from_upload(file: UploadFile = File(...), authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    provider_mode = _parser_provider_mode()

    max_upload_bytes = int(os.getenv("TRAIN2_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    chunks: list[bytes] = []
    total_bytes = 0
    chunk_size = 1024 * 1024
    try:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_upload_bytes:
                raise HTTPException(status_code=413, detail=f"Uploaded PDF exceeds size limit ({max_upload_bytes} bytes)")
            chunks.append(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to read uploaded PDF") from exc

    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty")

    pdf_bytes = b"".join(chunks)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file does not have a valid PDF signature")

    if provider_mode == "azure":
        if not os.getenv("AZURE_DOC_INTEL_ENDPOINT", "").strip():
            raise HTTPException(status_code=503, detail="LIVE INTEGRATION BLOCKED: AZURE_DOC_INTEL_ENDPOINT is not configured")
        if not os.getenv("AZURE_DOC_INTEL_KEY", "").strip():
            raise HTTPException(status_code=503, detail="LIVE INTEGRATION BLOCKED: AZURE_DOC_INTEL_KEY is not configured")
        try:
            return await PIPELINE.start_from_azure_parser(pdf_bytes=pdf_bytes)
        except ParserProviderAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ParserProviderTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except ParserProviderContractError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ParserProviderError, Train2PipelineError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    endpoint = os.getenv("TRAIN2_PARSER_API_ENDPOINT", "").strip()
    api_key = os.getenv("TRAIN2_PARSER_API_KEY", "").strip() or None
    api_key_header = os.getenv("TRAIN2_PARSER_API_KEY_HEADER", "Authorization")
    api_key_prefix = os.getenv("TRAIN2_PARSER_API_KEY_PREFIX", "Bearer")
    timeout_seconds = float(os.getenv("TRAIN2_PARSER_API_TIMEOUT_SECONDS", "30"))

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
async def get_review(run_id: str, authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    try:
        return PIPELINE.get_review(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/override")
async def override_mapping(run_id: str, req: ManualOverrideRequest, authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    try:
        return PIPELINE.apply_manual_mapping(
            run_id,
            req.row_id,
            req.canonical_code,
            req.reason,
            unit_confirmed=req.unit_confirmed,
            unit_correction=req.unit_correction,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/mutate-prices")
async def mutate_prices(run_id: str, req: PriceMutationRequest, authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    try:
        return PIPELINE.mutate_runtime_prices(run_id, req.price_updates)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/export.xlsx")
async def export_xlsx(run_id: str, authorization: str | None = Header(default=None)):
    _require_train_auth(authorization)
    try:
        content = PIPELINE.export_excel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="train1_{run_id}.xlsx"'},
    )
