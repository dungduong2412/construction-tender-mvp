from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from integration_train1.pipeline import PIPELINE

router = APIRouter()


class ManualOverrideRequest(BaseModel):
    row_id: str
    canonical_code: str


class PriceMutationRequest(BaseModel):
    price_updates: dict[str, str]


@router.post("/runs/fixture")
async def start_run_from_fixture():
    return await PIPELINE.start_from_fixture()


@router.get("/runs/{run_id}/review")
async def get_review(run_id: str):
    try:
        return PIPELINE.get_review(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/override")
async def override_mapping(run_id: str, req: ManualOverrideRequest):
    try:
        return PIPELINE.apply_manual_mapping(run_id, req.row_id, req.canonical_code)
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
