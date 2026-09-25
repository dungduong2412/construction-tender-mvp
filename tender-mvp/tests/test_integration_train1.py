from __future__ import annotations

import asyncio
import io
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from main import app
from integration_train1.pipeline import (
    REAL_RESPONSE_FIXTURE_PATH,
    Train1Pipeline,
    Train2PipelineError,
)
from parser_adapter.provider_neutral import (
    HttpJsonProvider,
    ParserProviderAuthError,
    ParserProviderContractError,
    ParserProviderTimeoutError,
    ProviderNeutralParserAdapter,
)


def _run(coro):
    return asyncio.run(coro)


def test_train2_parser_fixture_to_excel_numeric_and_complete_flag():
    pipeline = Train1Pipeline()
    payload = _run(pipeline.start_from_real_fixture())

    assert payload["source_document_id"] == "real-response-sample-001"
    assert payload["live_integration_verified"] is False
    assert payload["integration_label"] == "recorded_real_response"

    xlsx = pipeline.export_excel(payload["run_id"])
    wb = load_workbook(filename=io.BytesIO(xlsx))
    review = wb["Train1-Review"]
    summary = wb["Train1-Summary"]

    assert isinstance(review["D2"].value, (int, float))
    assert isinstance(review["I2"].value, (int, float))
    assert isinstance(summary["B2"].value, (int, float))


def test_train2_low_confidence_unique_match_requires_review():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "low-confidence",
        "rows": [
            {
                "row_id": "lc-1",
                "row_type": "line_item",
                "description_vi": "row",
                "unit_raw": "điểm",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "row"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.6, "evidence": "weak"}],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)

    row = payload["rows"][0]
    assert row["mapping_status"] == "low_confidence_review_required"
    assert payload["status"] == "INCOMPLETE"


def test_train2_missing_source_unit_requires_review_not_auto_accept():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "missing-unit",
        "rows": [
            {
                "row_id": "mu-1",
                "row_type": "line_item",
                "description_vi": "Đo lưới khống chế mặt bằng đường chuyền cấp 2",
                "unit_raw": "",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "missing unit"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.99, "evidence": "strong"}],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)

    row = payload["rows"][0]
    assert row["mapping_status"] == "unit_verification_required"
    assert payload["status"] == "INCOMPLETE"


def test_train2_invalid_units_and_quantities_block():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "invalids",
        "rows": [
            {
                "row_id": "u-1",
                "row_type": "line_item",
                "description_vi": "unit mismatch",
                "unit_raw": "kg",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "unit mismatch"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "q-1",
                "row_type": "line_item",
                "description_vi": "invalid quantity",
                "unit_raw": "điểm",
                "quantity_raw": "abc",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "invalid qty"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "q-2",
                "row_type": "line_item",
                "description_vi": "negative quantity",
                "unit_raw": "điểm",
                "quantity_raw": "-2",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l3", "text": "negative qty"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    statuses = {r["row_id"]: r["mapping_status"] for r in payload["rows"]}

    assert statuses["u-1"] == "unit_incompatible"
    assert statuses["q-1"] == "invalid_quantity"
    assert statuses["q-2"] == "negative_quantity_blocked"


def test_train2_duplicate_row_ids_rejected():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "dupe-rows",
        "rows": [
            {
                "row_id": "dup",
                "row_type": "line_item",
                "description_vi": "A",
                "unit_raw": "điểm",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "A"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "dup",
                "row_type": "line_item",
                "description_vi": "B",
                "unit_raw": "điểm",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "B"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
        ],
    }
    with pytest.raises(Train2PipelineError):
        pipeline.start_from_parsed_payload(parsed)


def test_train2_duplicate_canonical_codes_are_preserved_per_row():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "dup-code",
        "rows": [
            {
                "row_id": "d1",
                "row_type": "line_item",
                "description_vi": "first",
                "unit_raw": "điểm",
                "quantity_raw": "8",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "first"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "d2",
                "row_type": "line_item",
                "description_vi": "second",
                "unit_raw": "điểm",
                "quantity_raw": "10",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "second"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    rows = {r["row_id"]: r for r in payload["rows"]}

    assert rows["d1"]["canonical_code"] == "CF.11620"
    assert rows["d2"]["canonical_code"] == "CF.11620"
    assert rows["d1"]["tender_extension"] != rows["d2"]["tender_extension"]


def test_train2_generates_candidates_from_description_without_ai_hints():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "generated-candidates",
        "rows": [
            {
                "row_id": "gc-1",
                "row_type": "line_item",
                "description_vi": "Định vì và cắm cọc GPMB cấp địa hình II",
                "unit_raw": "mốc",
                "quantity_raw": "2",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "GPMB"}],
                "ai_suggestions": [],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    row = payload["rows"][0]

    assert row["candidates"], "semantic candidate generation must run without ai_suggestions"
    assert row["mapping_status"] == "resolved"
    assert row["canonical_code"] == "CF.21120"


def test_train2_aggregate_first_approval_for_group_matches_independent_calculation():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "approval-aggregate",
        "rows": [
            {
                "row_id": "a1",
                "row_type": "line_item",
                "description_vi": "CF row 1",
                "unit_raw": "điểm",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "CF"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "a2",
                "row_type": "line_item",
                "description_vi": "CF row 2",
                "unit_raw": "điểm",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "CF"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)

    runtime = pipeline.engine.load_runtime_data()
    cf = pipeline.engine.calculate_work_item_from_runtime("CF.11620", runtime)
    work_item = runtime["work_item_master"]["CF.11620"]
    group = work_item["approval_rule_group"]
    rules = pipeline.engine.approval_rules_for("topography", runtime=runtime, approval_group=group)
    expected_components = pipeline.engine._compute_loaded_components(
        cf["direct_material_total"] * Decimal("2"),
        cf["direct_labour_total"] * Decimal("2"),
        cf["direct_machine_total"] * Decimal("2"),
        rules,
    )

    assert Decimal(payload["approval_partial_subtotal"]) == expected_components["FINAL"]


def test_train2_tender_independence_from_approval_rule_mutation():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "independence",
        "rows": [
            {
                "row_id": "i1",
                "row_type": "line_item",
                "description_vi": "CF",
                "unit_raw": "điểm",
                "quantity_raw": "8",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "CF"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    run_id = payload["run_id"]

    mutated = pipeline.mutate_approval_group_rules(run_id, "topography_main", {"gdp_rate": "0.20"})

    assert mutated["tender_partial_subtotal"] == payload["tender_partial_subtotal"]
    assert mutated["approval_partial_subtotal"] != payload["approval_partial_subtotal"]


def test_train2_incomplete_export_keeps_partial_and_null_official_totals():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "incomplete",
        "rows": [
            {
                "row_id": "ok",
                "row_type": "line_item",
                "description_vi": "CF",
                "unit_raw": "điểm",
                "quantity_raw": "8",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "CF"}],
                "ai_suggestions": [{"code": "CF.11620", "confidence": 0.95, "evidence": "code"}],
            },
            {
                "row_id": "bad",
                "row_type": "line_item",
                "description_vi": "unknown",
                "unit_raw": "m",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l2", "text": "unknown"}],
                "ai_suggestions": [],
            },
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    assert payload["status"] == "INCOMPLETE"

    xlsx = pipeline.export_excel(payload["run_id"])
    wb = load_workbook(filename=io.BytesIO(xlsx))
    summary = wb["Train1-Summary"]

    assert summary["B1"].value == "INCOMPLETE"
    assert isinstance(summary["B2"].value, (int, float))
    assert isinstance(summary["B3"].value, (int, float))
    assert summary["B4"].value is None
    assert summary["B5"].value is None


def test_parser_contract_malformed_response_rejected():
    class BadProvider:
        async def analyze(self, document_bytes=None):
            return {"document_id": "bad", "rows": [{"row_id": "a"}]}

    adapter = ProviderNeutralParserAdapter(BadProvider())
    with pytest.raises(ParserProviderContractError):
        _run(adapter.parse())


def test_parser_http_auth_failure(monkeypatch):
    request = httpx.Request("POST", "https://example.test/parser")
    response = httpx.Response(401, request=request, text="unauthorized")

    async def fake_post(self, *args, **kwargs):
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = HttpJsonProvider(endpoint="https://example.test/parser", api_key="bad")
    with pytest.raises(ParserProviderAuthError):
        _run(provider.analyze(b"%PDF"))


def test_parser_http_timeout(monkeypatch):
    async def fake_post(self, *args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = HttpJsonProvider(endpoint="https://example.test/parser")
    with pytest.raises(ParserProviderTimeoutError):
        _run(provider.analyze(b"%PDF"))


def test_train2_upload_requires_endpoint_no_fixture_fallback(monkeypatch):
    monkeypatch.delenv("TRAIN2_PARSER_API_ENDPOINT", raising=False)
    monkeypatch.setenv("TRAIN2_UPLOAD_AUTH_TOKEN", "token")

    with TestClient(app) as client:
        resp = client.post(
            "/api/train1/runs/upload",
            headers={"Authorization": "Bearer token"},
            files={"file": ("sample.pdf", b"%PDF-1.4\nabc", "application/pdf")},
        )

    assert resp.status_code == 503
    assert "TRAIN2_PARSER_API_ENDPOINT" in resp.text


def test_train2_upload_requires_auth_signature_and_size(monkeypatch):
    monkeypatch.setenv("TRAIN2_PARSER_API_ENDPOINT", "https://example.test/parser")
    monkeypatch.setenv("TRAIN2_UPLOAD_AUTH_TOKEN", "token")
    monkeypatch.setenv("TRAIN2_MAX_UPLOAD_BYTES", "16")

    with TestClient(app) as client:
        no_auth = client.post(
            "/api/train1/runs/upload",
            files={"file": ("sample.pdf", b"%PDF-1.4\nabc", "application/pdf")},
        )
        assert no_auth.status_code == 401

        bad_sig = client.post(
            "/api/train1/runs/upload",
            headers={"Authorization": "Bearer token"},
            files={"file": ("sample.pdf", b"NOTPDF", "application/pdf")},
        )
        assert bad_sig.status_code == 400

        too_big = client.post(
            "/api/train1/runs/upload",
            headers={"Authorization": "Bearer token"},
            files={"file": ("sample.pdf", b"%PDF-1.4\n0123456789ABCDEFZZ", "application/pdf")},
        )
        assert too_big.status_code == 413


def test_train2_manual_correction_retains_source_evidence():
    pipeline = Train1Pipeline()
    parsed = {
        "document_id": "manual-evidence",
        "rows": [
            {
                "row_id": "m1",
                "row_type": "line_item",
                "description_vi": "Ambiguous",
                "unit_raw": "",
                "quantity_raw": "1",
                "page": 1,
                "evidence": [{"type": "pdf_span", "locator": "p1:l1", "text": "proof"}],
                "ai_suggestions": [
                    {"code": "CF.21120", "confidence": 0.8, "evidence": "maybe"},
                    {"code": "AG.11112", "confidence": 0.8, "evidence": "maybe"},
                ],
            }
        ],
    }
    payload = pipeline.start_from_parsed_payload(parsed)
    updated = pipeline.apply_manual_mapping(payload["run_id"], "m1", "CF.21120", reason="user decision")

    row = updated["rows"][0]
    assert row["mapping_status"] == "resolved"
    assert row["corrections"]
    assert row["corrections"][-1]["retained_evidence"][0]["text"] == "proof"


@pytest.mark.skipif(not REAL_RESPONSE_FIXTURE_PATH.exists(), reason="Recorded real response fixture missing")
def test_recorded_real_fixture_path_exists():
    assert REAL_RESPONSE_FIXTURE_PATH.exists()
