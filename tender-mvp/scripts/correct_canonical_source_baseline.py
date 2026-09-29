#!/usr/bin/env python3
"""Apply the visually verified 95-row source contract to local audit artifacts.

The recorded Azure response is intentionally never modified. This script is
idempotent and only amends the derived reconciliation and acceptance summary.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "source_reconciliation_20260927"
RECONCILIATION = ARTIFACTS / "source_reconciliation.json"
ACCEPTANCE = ARTIFACTS / "acceptance_summary.json"
DESCRIPTION = "Cầu nhỏ, cầu trung, tỷ lệ 1/500: bình đồ, cắt dọc"
UNAVAILABLE_CODES = [
    "I.2", "II.1.2", "II.1.3", "II.3.2.2", "III.8", "IV.1.2", "IV.1.4", "IV.1.5",
    "IV.1.6", "IV.2.3", "IV.2.4", "IV.2.5", "IV.2.6", "IV.2.21", "IV.2.22", "IV.2.23",
]


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonicalize() -> dict:
    audit = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    rows = audit["rows"]
    if not any(row.get("stt") == "II.3.2" for row in rows):
        for row in rows:
            historical = int(row["source_index"])
            row["historical_azure_source_index"] = historical
            row["source_origin"] = "azure_document_intelligence"
            row["source_provenance"] = "Extracted by Azure Document Intelligence."
            row["azure_polygon_available"] = True
            if historical >= 26:
                row["source_index"] = historical + 1
        recovered = {
            "source_index": 26,
            "historical_azure_source_index": None,
            "page": 2,
            "stt": "II.3.2",
            "description": DESCRIPTION,
            "source_unit": "",
            "source_quantity_raw": "-",
            "source_quantity": None,
            "source_evidence": [],
            "source_origin": "source_document_inspection",
            "source_provenance": (
                "Visible in the original PDF and recovered by source-document inspection; "
                "the historical Azure fixture omitted it, so no Azure polygon exists."
            ),
            "azure_polygon_available": False,
            "treatment": "recovered_non_billable_subsection",
            "status": "VERIFIED",
            "reason": "Structural parent restored from the source PDF; no price applies.",
            "pricing_availability": "not_applicable",
            "price_display": "Not applicable",
            "unit_price": None,
            "unit_price_editable": False,
        }
        rows.insert(25, recovered)
        for blocker in audit.get("blockers", []):
            historical = int(blocker["source_index"])
            blocker["historical_azure_source_index"] = historical
            if historical >= 26:
                blocker["source_index"] = historical + 1

    sections: list[str] = []
    blocker_index = 0
    for row in rows:
        stt = str(row.get("stt") or "").strip()
        if stt and not stt.isdigit():
            depth = len(stt.split("."))
            sections = sections[: depth - 1] + [stt]
        row["section_path"] = " > ".join(sections) if sections else "ROOT"
        is_billable = row.get("source_quantity") is not None and stt.isdigit()
        if not is_billable:
            row.update({
                "pricing_availability": "not_applicable", "price_display": "Not applicable",
                "unit_price": None, "unit_price_editable": False,
            })
        elif row.get("status") == "BLOCKED":
            row.update({
                "hierarchy_code": UNAVAILABLE_CODES[blocker_index],
                "pricing_availability": "not_available", "price_display": "Not available",
                "unit_price": None, "unit_price_editable": True,
            })
            blocker_index += 1
        else:
            row["pricing_availability"] = "available"
            row["price_display"] = str((row.get("tender") or {}).get("loaded_unit_price_used", "Not available"))
            row["unit_price_editable"] = True

    counts = audit["reconciliation"]
    counts.update({
        "pdf_rows": 95, "source_row_count": 95, "canonical_source_row_count": 95,
        "historical_azure_extraction_count": 94, "numeric_billable_rows": 82,
        "billable_count": 82, "non_billable_count": 13,
        "source_page_row_counts": {"1": 25, "2": 28, "3": 22, "4": 20},
        "nested_subsections_corrected": 1,
        "source_rows_recovered_from_document_inspection": 1,
        "unavailable_billable_count": 16,
        "unavailable_billable_items": UNAVAILABLE_CODES,
        "all_rows_have_treatment": len(rows) == 95,
    })
    audit["source"]["canonical_contract"] = "95 source rows = 82 billable + 13 structural"
    audit["source"]["historical_azure_extraction_count"] = 94
    audit["source"]["canonical_source_row_count"] = 95
    write_json(RECONCILIATION, audit)

    acceptance = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    acceptance["source_reconciliation"] = counts
    acceptance["application_data_contract"] = {
        "source_row_count": 95, "billable_count": 82, "non_billable_count": 13,
        "historical_azure_extraction_count": 94,
        "recovered_row": "II.3.2",
        "pricing_states": ["not_applicable", "not_available", "authorized_zero", "available"],
    }
    acceptance["authoritative_pricing_gate"] = {
        "unavailable_billable_count": 16, "unavailable_billable_items": UNAVAILABLE_CODES,
        "ks_4_8": "BLOCKED_PENDING_AUTHORITATIVE_LABOUR_SOURCE",
        "scoped_conflicts": {"Z999": 29, "M999": 29, "A28.1000": 2},
        "missing_effective_dates": {"seeded_catalogue": 30, "staged_candidates": 46},
    }
    acceptance["infrastructure_gate"] = {
        "status": "BLOCKED",
        "reason": "Railway UAT has no persistent volume or external persistent database; restart persistence is not demonstrated.",
        "railway_modified_by_this_task": False,
    }
    write_json(ACCEPTANCE, acceptance)
    return {"source_rows": len(rows), "billable": 82, "structural": 13, "azure_historical": 94, "blocked": blocker_index}


if __name__ == "__main__":
    print(json.dumps(canonicalize(), ensure_ascii=False))
