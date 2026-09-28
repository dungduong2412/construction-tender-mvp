"""Governed staging view for workbook-derived master-data candidates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governance_store import read_json, utc_now, write_json
from pricing_availability import classify_price, price_freshness


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_FILE = ROOT / "master-data" / "verified_master_candidates.json"
STATE_FILE = "master_staging.json"


def _evidence() -> dict[str, Any]:
    if not CANDIDATE_FILE.exists():
        return {
            "status": "EVIDENCE_NOT_AVAILABLE",
            "reason": f"Candidate evidence file is missing: {CANDIDATE_FILE}",
            "work_item_candidates": [],
            "resource_price_conflicts": [],
            "global_price_book_mutation_allowed": False,
        }
    return json.loads(CANDIDATE_FILE.read_text(encoding="utf-8"))


def _state() -> dict[str, Any]:
    return read_json(STATE_FILE, {"decisions": {}, "project_overrides": [], "audit": []})


def overview() -> dict[str, Any]:
    evidence = _evidence()
    state = _state()
    decisions = state.get("decisions", {})
    candidates = []
    resource_index: dict[tuple[str, str], dict[str, Any]] = {}
    units: set[str] = set()
    for candidate in evidence.get("work_item_candidates", []):
        item = dict(candidate)
        review = decisions.get(candidate.get("scoped_id"), {"status": "pending"})
        item["review"] = review
        item["scope"] = "staging_only"
        item["original_creator"] = item.get("original_creator") or "evidence-import"
        item["created_at"] = item.get("created_at") or "2026-09-27T00:00:00+00:00"
        item["last_updated_by"] = review.get("actor") or item["original_creator"]
        item["last_updated_at"] = review.get("at") or item["created_at"]
        source_reference = (item.get("source_cells") or {}).get("master_row")
        price = item.get("tender_unit_price_evidence")
        availability = classify_price(price, source_reference=source_reference)
        item.update({
            "unit_price": price if availability.available else None,
            "price_display": str(price) if availability.available else "Not available",
            "pricing_availability": availability.status,
            "price_source_reference": source_reference,
            "price_effective_date": None,
            "price_expiry_date": None,
            "price_freshness": price_freshness(None, None, available=availability.available),
            "approval_status": review.get("status", "pending"),
            "approved_by": review.get("actor") if review.get("status") == "approved_for_staging" else None,
        })
        candidates.append(item)
        if item.get("unit"):
            units.add(str(item["unit"]))
        for norm in item.get("norms") or []:
            code = str(norm.get("code") or "")
            provenance = str(norm.get("provenance") or norm.get("sheet_ref") or "")
            availability = classify_price(
                norm.get("unit_price"), source_reference=provenance,
                approval_status=norm.get("approval_status") or "approved",
                approved_by=norm.get("approved_by") or "evidence-import",
                zero_price_authorized=bool(norm.get("zero_price_authorized")),
            )
            resource_index[(code, provenance)] = {
                "code": code,
                "description": norm.get("description"),
                "type": norm.get("resource_type"),
                "unit": norm.get("unit"),
                "unit_price": norm.get("unit_price") if availability.available else None,
                "price_display": str(norm.get("unit_price")) if availability.available else "Not available",
                "pricing_availability": availability.status,
                "source": provenance,
                "effective_date": norm.get("effective_date"),
                "expiry_date": norm.get("expiry_date"),
                "price_freshness": price_freshness(norm.get("effective_date"), norm.get("expiry_date"), available=availability.available),
                "original_creator": norm.get("original_creator") or "evidence-import",
                "created_at": norm.get("created_at") or "2026-09-27T00:00:00+00:00",
                "last_updated_by": norm.get("last_updated_by") or "evidence-import",
                "last_updated_at": norm.get("last_updated_at") or "2026-09-27T00:00:00+00:00",
                "approval_status": norm.get("approval_status") or "evidence_only",
                "approved_by": norm.get("approved_by"),
                "scope": "candidate_evidence",
            }
    return {
        "evidence_status": evidence.get("status"),
        "reason": evidence.get("reason"),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "units": sorted(units),
        "resources": list(resource_index.values()),
        "resource_price_conflicts": evidence.get("resource_price_conflicts", []),
        "global_price_book_mutation_allowed": False,
        "ks_4_8_restriction": "KS.4/8 labour remains project-scoped and blocked unless its authoritative dependency is supplied.",
        "project_overrides": state.get("project_overrides", []),
        "version_history": [
            {"version": "candidate-evidence-2026-09-27", "status": "staging", "candidate_count": len(candidates)},
        ],
        "effective_date_blockers": {
            "seeded_catalogue_missing": 30,
            "staged_candidates_missing": len(candidates),
            "authoritative_dates_must_not_be_invented": True,
        },
        "audit": state.get("audit", []),
    }


def decide_candidate(scoped_id: str, decision: str, actor: str, note: str | None) -> dict[str, Any]:
    if decision not in {"approved_for_staging", "rejected", "needs_evidence"}:
        raise ValueError("Unsupported candidate decision")
    evidence = _evidence()
    if not any(item.get("scoped_id") == scoped_id for item in evidence.get("work_item_candidates", [])):
        raise KeyError(scoped_id)
    state = _state()
    record = {"status": decision, "actor": actor, "note": note or "", "at": utc_now(), "applied_globally": False}
    state.setdefault("decisions", {})[scoped_id] = record
    state.setdefault("audit", []).append({"event": "candidate_decision", "scoped_id": scoped_id, **record})
    write_json(STATE_FILE, state)
    return record


def add_project_override(payload: dict[str, Any], actor: str) -> dict[str, Any]:
    if not payload.get("project_id") or not payload.get("resource_code"):
        raise ValueError("project_id and resource_code are required")
    availability = classify_price(
        payload.get("unit_price"), source_reference=payload.get("source_reference"),
        approval_status=payload.get("approval_status"), approved_by=payload.get("approved_by"),
        zero_price_authorized=bool(payload.get("zero_price_authorized")),
    )
    if not availability.available:
        raise ValueError(availability.reason or "Price is not available")
    if not payload.get("effective_date"):
        raise ValueError("effective_date is required")
    now = utc_now()
    record = {
        "project_id": str(payload["project_id"]),
        "resource_code": str(payload["resource_code"]),
        "unit_price": str(availability.value),
        "pricing_availability": availability.status,
        "source_reference": str(payload.get("source_reference") or ""),
        "effective_date": payload.get("effective_date"),
        "expiry_date": payload.get("expiry_date"),
        "approval_status": payload.get("approval_status"),
        "approved_by": payload.get("approved_by"),
        "zero_price_authorized": bool(payload.get("zero_price_authorized")),
        "scope": "project_only",
        "original_creator": actor, "created_at": now,
        "last_updated_by": actor, "last_updated_at": now,
        "version_history": [{"event": "created", "actor": actor, "at": now}],
    }
    state = _state()
    state.setdefault("project_overrides", []).append(record)
    state.setdefault("audit", []).append({"event": "project_override_recorded", **record})
    write_json(STATE_FILE, state)
    return record
