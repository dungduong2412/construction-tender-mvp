from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from openpyxl import load_workbook

from integration_train1.pipeline import Train1Pipeline


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "parser_api_recorded_train1.json"


def _run(coro):
    return asyncio.run(coro)


def test_train1_single_item_e2e_from_fixture():
    pipeline = Train1Pipeline()
    payload = _run(pipeline.start_from_fixture(FIXTURE_PATH))

    assert payload["source_document_id"] == "train1-fixture-001"
    assert payload["required_row_count"] == 3
    assert payload["resolved_required_row_count"] == 3
    assert payload["status"] == "COMPLETE"
    assert payload["official_tender_total"] == payload["tender_partial_subtotal"]
    assert payload["official_approval_total"] == payload["approval_partial_subtotal"]


def test_train1_duplicate_code_different_quantities_kept_separate():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "dup-rows",
        "rows": [
            {
                "row_id": "d1",
                "row_type": "line_item",
                "description_vi": "CF row A",
                "unit_raw": "điểm",
                "quantity_raw": "8",
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "A"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.9, "evidence": "A"}],
            },
            {
                "row_id": "d2",
                "row_type": "line_item",
                "description_vi": "CF row B",
                "unit_raw": "điểm",
                "quantity_raw": "10",
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "B"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.91, "evidence": "B"}],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)

    rows = {r["row_id"]: r for r in payload["rows"]}
    assert rows["d1"]["canonical_code"] == "CF.11620"
    assert rows["d2"]["canonical_code"] == "CF.11620"
    assert rows["d1"]["tender_extension"] != rows["d2"]["tender_extension"]


def test_train1_ambiguous_mapping_requires_manual_review():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "ambiguous",
        "rows": [
            {
                "row_id": "a1",
                "row_type": "line_item",
                "description_vi": "Ambiguous row",
                "unit_raw": "",
                "quantity_raw": "1",
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "Ambiguous"}],
                "ai_suggestions": [
                    {"code": "CF.21120", "confidence": 0.7, "evidence": "candidate 1"},
                    {"code": "AG.11112", "confidence": 0.69, "evidence": "candidate 2"},
                ],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)

    row = payload["rows"][0]
    assert row["mapping_status"] == "mapping_ambiguous"
    assert payload["status"] == "INCOMPLETE"

    run_id = payload["run_id"]
    updated = pipeline.apply_manual_mapping(run_id, "a1", "CF.21120")
    assert updated["rows"][0]["mapping_status"] == "resolved"


def test_train1_unsupported_blocking_item_marks_incomplete():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "blocked",
        "rows": [
            {
                "row_id": "b1",
                "row_type": "line_item",
                "description_vi": "Traffic survey blocked",
                "unit_raw": "Công",
                "quantity_raw": "2",
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "KS4/8"}],
                "ai_suggestions": [{"code": "KS.4/8", "confidence": 0.9, "evidence": "code"}],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)

    row = payload["rows"][0]
    assert row["mapping_status"] == "unsupported_blocking_item"
    assert row["missing_dependencies"]
    assert payload["official_tender_total"] is None
    assert payload["status"] == "INCOMPLETE"


def test_train1_shared_price_mutation_updates_all_dependents():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "shared-price",
        "rows": [
            {
                "row_id": "s1",
                "row_type": "line_item",
                "description_vi": "CF 11620",
                "unit_raw": "điểm",
                "quantity_raw": "8",
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "CF.11620"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "s2",
                "row_type": "line_item",
                "description_vi": "CF 21120",
                "unit_raw": "mốc",
                "quantity_raw": "3",
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "CF.21120"}],
                "ai_suggestions": [{"code": "CF.21120", "confidence": 0.95, "evidence": "code"}],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    run_id = payload["run_id"]
    before = {r["row_id"]: r["loaded_unit_price"] for r in payload["rows"]}

    after_payload = pipeline.mutate_runtime_prices(run_id, {"A28.0341": "2000"})
    after = {r["row_id"]: r["loaded_unit_price"] for r in after_payload["rows"]}

    assert before["s1"] != after["s1"]
    assert before["s2"] != after["s2"]


def test_train1_excel_totals_match_review_and_incomplete_hides_official_totals():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "xlsx",
        "rows": [
            {
                "row_id": "x1",
                "row_type": "line_item",
                "description_vi": "CF 11620",
                "unit_raw": "điểm",
                "quantity_raw": "8",
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "CF.11620"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "x2",
                "row_type": "line_item",
                "description_vi": "unmatched",
                "unit_raw": "m",
                "quantity_raw": "1",
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "unknown"}],
                "ai_suggestions": [],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    assert payload["status"] == "INCOMPLETE"

    xlsx = pipeline.export_excel(payload["run_id"])
    wb = load_workbook(filename=__import__("io").BytesIO(xlsx))
    summary = wb["Train1-Summary"]

    assert summary["B1"].value == "INCOMPLETE"
    assert str(summary["B2"].value) == payload["tender_partial_subtotal"]
    assert summary["B4"].value is None
    assert summary["B5"].value is None


@pytest.mark.skipif(True, reason="Enable when external parser API endpoint/contract is provided")
def test_train1_real_parser_api_contract_placeholder():
    assert True
