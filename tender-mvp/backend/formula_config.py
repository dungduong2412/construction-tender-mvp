"""Versioned configuration facade for the validated CalculationEngineV2 rules."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from governance_store import read_json, utc_now, write_json
from pricing_engine.calculation_engine_v2 import CalculationEngineV2


STATE_FILE = "formula_versions.json"
ALLOWED_COEFFICIENTS = {"c_rate", "tt_rate", "vat_rate", "lt_rate", "cpa_rate", "cbc_rate", "gdp_rate"}
ALLOWED_ROUNDING = {"whole_dong", "down_to_thousand", "nearest_thousand", "none"}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def default_version() -> dict[str, Any]:
    engine = CalculationEngineV2()
    return {
        "version_id": "calculation-v2.1",
        "status": "approved",
        "effective_from": "2026-09-27",
        "name": "Workbook-audited tender and aggregate-first approval rules",
        "tender": {
            "calculation": "per-work-item loaded cost then configured tender rounding",
            "rounding": "down_to_thousand",
            "defaults": _json_safe(engine.tender_rules_for("default")),
        },
        "approval": {
            "calculation": "aggregate direct resources by approval group before overhead and tax",
            "rounding": "whole_dong",
            "defaults": _json_safe(engine.approval_rules_for("default")),
            "category_rules": _json_safe(engine.CATEGORY_RULES),
        },
        "created_at": "2026-09-27T00:00:00+00:00",
        "original_creator": "system",
        "last_updated_by": "system",
        "last_updated_at": "2026-09-27T00:00:00+00:00",
        "source_reference": "audited CalculationEngineV2 baseline",
        "price_effective_date": "2026-09-27",
        "price_expiry_date": None,
        "approval_status": "approved",
        "approved_by": "system",
        "approved_at": "2026-09-27T00:00:00+00:00",
        "audit": [{"event": "baseline_imported", "actor": "system", "at": "2026-09-27T00:00:00+00:00"}],
    }


def list_versions() -> list[dict[str, Any]]:
    state = read_json(STATE_FILE, {"versions": []})
    return [default_version(), *state.get("versions", [])]


def approved_version(effective_on: str | None = None) -> dict[str, Any]:
    effective_on = effective_on or date.today().isoformat()
    approved = [version for version in list_versions() if version.get("status") == "approved"]
    approved = [version for version in approved if str(version.get("effective_from", "")) <= effective_on]
    return sorted(approved, key=lambda value: (str(value.get("effective_from", "")), str(value.get("approved_at", ""))))[-1]


def _rules_for(version: dict[str, Any], branch: str) -> dict[str, Any]:
    return dict((version.get(branch) or {}).get("defaults") or {})


def preview_change(changes: dict[str, Any], category: str, basis: dict[str, Any]) -> dict[str, Any]:
    engine = CalculationEngineV2()
    current = approved_version()
    branch = str(changes.get("branch") or "approval")
    if branch not in {"tender", "approval"}:
        raise ValueError("branch must be tender or approval")
    coefficients = dict(changes.get("coefficients") or {})
    unknown = set(coefficients) - ALLOWED_COEFFICIENTS
    if unknown:
        raise ValueError(f"Unsupported coefficients: {', '.join(sorted(unknown))}")
    for key, value in coefficients.items():
        number = Decimal(str(value))
        if number < 0 or number > 10:
            raise ValueError(f"{key} must be between 0 and 10")
    rounding = changes.get("rounding")
    if rounding is not None and rounding not in ALLOWED_ROUNDING:
        raise ValueError("Unsupported rounding rule")

    before_rules = engine.approval_rules_for(category) if branch == "approval" else engine.tender_rules_for(category)
    after_rules = dict(before_rules)
    after_rules.update({key: Decimal(str(value)) for key, value in coefficients.items()})
    if rounding:
        after_rules["rounding"] = rounding
    material = Decimal(str(basis.get("material", 0)))
    labour = Decimal(str(basis.get("labour", 0)))
    machine = Decimal(str(basis.get("machine", 0)))
    before = engine._compute_loaded_components(material, labour, machine, before_rules)
    after = engine._compute_loaded_components(material, labour, machine, after_rules)
    return {
        "branch": branch,
        "category": category,
        "basis": _json_safe({"material": material, "labour": labour, "machine": machine}),
        "current_version": current["version_id"],
        "before_rules": _json_safe(before_rules),
        "after_rules": _json_safe(after_rules),
        "before": _json_safe(before),
        "after": _json_safe(after),
        "difference": str(after["FINAL"] - before["FINAL"]),
    }


def create_proposal(payload: dict[str, Any], actor: str) -> dict[str, Any]:
    preview = preview_change(payload.get("changes") or {}, payload.get("category") or "default", payload.get("basis") or {})
    created_at = utc_now()
    proposal = {
        "version_id": f"proposal-{uuid4().hex[:10]}",
        "status": "proposed",
        "name": payload.get("name") or "Formula change proposal",
        "effective_from": payload.get("effective_from"),
        "tender": deepcopy(default_version()["tender"]),
        "approval": deepcopy(default_version()["approval"]),
        "changes": payload.get("changes") or {},
        "preview": preview,
        "created_at": created_at,
        "original_creator": actor,
        "last_updated_by": actor,
        "last_updated_at": created_at,
        "source_reference": payload.get("source_reference") or "formula change proposal",
        "price_effective_date": payload.get("effective_from"),
        "price_expiry_date": payload.get("expiry_date"),
        "approval_status": "proposed",
        "approved_by": None,
        "approved_at": None,
        "audit": [{"event": "proposed", "actor": actor, "at": utc_now()}],
    }
    branch = proposal["changes"].get("branch", "approval")
    proposal[branch]["defaults"].update(proposal["changes"].get("coefficients") or {})
    if proposal["changes"].get("rounding"):
        proposal[branch]["rounding"] = proposal["changes"]["rounding"]
        proposal[branch]["defaults"]["rounding"] = proposal["changes"]["rounding"]
    state = read_json(STATE_FILE, {"versions": []})
    state.setdefault("versions", []).append(proposal)
    write_json(STATE_FILE, state)
    return proposal


def approve_proposal(version_id: str, actor: str) -> dict[str, Any]:
    state = read_json(STATE_FILE, {"versions": []})
    for version in state.get("versions", []):
        if version.get("version_id") != version_id:
            continue
        if version.get("status") != "proposed" or not version.get("preview"):
            raise ValueError("Only a previewed proposal can be approved")
        if not version.get("effective_from"):
            raise ValueError("An effective date is required before approval")
        version["status"] = "approved"
        now = utc_now()
        version["approved_at"] = now
        version["last_updated_by"] = actor
        version["last_updated_at"] = now
        version["approval_status"] = "approved"
        version["approved_by"] = actor
        version.setdefault("audit", []).append({"event": "approved", "actor": actor, "at": now})
        write_json(STATE_FILE, state)
        return version
    raise KeyError(version_id)


def apply_version_to_runtime(runtime: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    """Apply only an approved version to an in-memory calculation runtime."""
    if version.get("status") != "approved":
        raise ValueError("Official calculations require an approved formula version")
    updated = deepcopy(runtime)
    updated["approval_project_rules"] = {
        key: value for key, value in _rules_for(version, "approval").items() if key in ALLOWED_COEFFICIENTS
    }
    tender_rules = _rules_for(version, "tender")
    for item in (updated.get("work_item_master") or {}).values():
        item["tender_rules"] = {key: value for key, value in tender_rules.items() if key in ALLOWED_COEFFICIENTS}
        item["tender_rounding_mode"] = tender_rules.get("rounding", version["tender"].get("rounding"))
    return updated
