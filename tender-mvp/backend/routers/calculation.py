"""Integrated calculation snapshot and audited workbook-contract API."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from calculation_snapshots import build_snapshot, load_snapshot
from database import get_db
from pricing_engine.audited_contract import formula_configuration, reconciliation_report
from pricing_engine.calculation_engine_v2 import CalculationEngineV2


router = APIRouter()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@router.get("/configuration")
async def get_formula_configuration():
    return _json_safe({"rules": formula_configuration()})


@router.get("/reconciliation")
async def get_reconciliation():
    return _json_safe(reconciliation_report())


@router.get("/trace/{work_item_code}")
async def get_calculation_trace(work_item_code: str):
    engine = CalculationEngineV2()
    try:
        result = engine.calculate_work_item_from_runtime(work_item_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _json_safe(result)


@router.get("/snapshots/{snapshot_id}/immutable")
async def get_immutable_snapshot(snapshot_id: str):
    snapshot = load_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Calculation snapshot not found")
    return snapshot


@router.get("/{job_id}")
async def get_calculation(job_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await build_snapshot(db, job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc
