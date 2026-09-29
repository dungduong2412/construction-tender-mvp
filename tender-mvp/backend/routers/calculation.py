from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException

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
