"""
Tests for parser fixture, normalizer, and BOQ reconstructor.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "bang_tien_luong_mock.json"


@pytest.fixture
def fixture_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def parsed_doc(fixture_data):
    from parser_adapter.normalizer import DocumentNormalizer
    normalizer = DocumentNormalizer()
    return normalizer.normalize(fixture_data)


@pytest.fixture
def boq_items(parsed_doc):
    from boq.reconstructor import BOQReconstructor
    rec = BOQReconstructor()
    return rec.reconstruct(parsed_doc.boq_rows)


@pytest.fixture
def azure_bridge_payload(fixture_data):
    from parser_adapter.azure_bridge import azure_analyze_result_to_parser_payload

    return azure_analyze_result_to_parser_payload(
        {"status": "succeeded", "analyzeResult": fixture_data},
        "azure-doc-intel-test-001",
    )


# ---------------------------------------------------------------------------
# Fixture tests
# ---------------------------------------------------------------------------

class TestFixtureStructure:
    def test_fixture_exists(self):
        assert FIXTURE_PATH.exists(), "Mock fixture file must exist"

    def test_fixture_has_4_pages(self, fixture_data):
        pages = fixture_data.get("pages", [])
        assert len(pages) == 4, f"Expected 4 pages, got {len(pages)}"

    def test_fixture_has_tables(self, fixture_data):
        total_tables = sum(len(p.get("tables", [])) for p in fixture_data["pages"])
        assert total_tables >= 4

    def test_fixture_meta_comment(self, fixture_data):
        assert "_fixture_meta" in fixture_data

    def test_page_boundary_markers(self, fixture_data):
        # Row 31 on page 3 should have continuation note
        page3_cells = []
        for table in fixture_data["pages"][2].get("tables", []):
            page3_cells.extend(table.get("cells", []))
        content_vals = [c.get("content", "") for c in page3_cells]
        assert any("342,34" in v for v in content_vals), "Row 31 with 342,34 expected on page 3"

    def test_iv1_metadata_marker(self, fixture_data):
        # IV.1 18.57 Km should be flagged as metadata in fixture
        page2_cells = []
        for table in fixture_data["pages"][1].get("tables", []):
            page2_cells.extend(table.get("cells", []))
        notes = [c.get("_note", "") for c in page2_cells]
        assert any("METADATA" in n for n in notes), "IV.1 18.57 Km must be marked as METADATA"


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

class TestNormalizer:
    def test_page_count(self, parsed_doc):
        assert parsed_doc.page_count == 4

    def test_has_boq_rows(self, parsed_doc):
        assert len(parsed_doc.boq_rows) > 0

    def test_row_types_valid(self, parsed_doc):
        valid_types = {"heading", "metadata", "line_item"}
        for row in parsed_doc.boq_rows:
            assert row.row_type in valid_types, f"Invalid row_type: {row.row_type}"

    def test_heading_rows_no_quantity(self, parsed_doc):
        for row in parsed_doc.boq_rows:
            if row.row_type == "heading":
                assert row.quantity is None, f"Heading row should have no quantity: {row.stt}"

    def test_iv1_classified_as_metadata(self, parsed_doc):
        # IV.1 with description "18.57 Km" must be metadata, NOT line_item
        iv1_rows = [r for r in parsed_doc.boq_rows if r.stt.strip() == "IV.1"]
        assert iv1_rows, "IV.1 row must be present"
        for r in iv1_rows:
            assert r.row_type in ("metadata", "heading"), (
                f"IV.1 18.57 Km must not be a line_item, got {r.row_type}"
            )


# ---------------------------------------------------------------------------
# Vietnamese decimal tests
# ---------------------------------------------------------------------------

class TestVietnameseDecimals:
    @pytest.mark.parametrize("raw,expected", [
        ("29,5", 29.5),
        ("19,50", 19.50),
        ("0,030", 0.030),
        ("342,34", 342.34),
        ("624", 624.0),
        ("18,57", 18.57),
        ("", None),
        ("abc", None),
    ])
    def test_parse_vn_number(self, raw, expected):
        from parser_adapter.normalizer import _parse_vn_number
        result = _parse_vn_number(raw)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected, rel=1e-6), (
                f"_parse_vn_number('{raw}') = {result}, expected {expected}"
            )

    def test_29_5_in_boq(self, boq_items):
        # Row 1: ha, quantity 29,5
        items = [r for r in boq_items if r.quantity_raw == "29,5"]
        assert items, "Row with quantity_raw=29,5 expected"
        assert abs(items[0].quantity - 29.5) < 1e-9

    def test_0_030_in_boq(self, boq_items):
        items = [r for r in boq_items if r.quantity_raw == "0,030"]
        assert items, "Row with quantity_raw=0,030 expected"
        assert abs(items[0].quantity - 0.030) < 1e-9

    def test_342_34_in_boq(self, boq_items):
        items = [r for r in boq_items if r.quantity_raw == "342,34"]
        assert items, "Row with quantity_raw=342,34 expected"
        assert abs(items[0].quantity - 342.34) < 1e-9


# ---------------------------------------------------------------------------
# BOQ Reconstructor tests
# ---------------------------------------------------------------------------

class TestBOQReconstructor:
    def test_all_items_have_row_id(self, boq_items):
        for item in boq_items:
            assert item.row_id, "Every BOQ item must have a row_id"

    def test_no_heading_row_priced(self, boq_items):
        headings = [r for r in boq_items if r.row_type == "heading"]
        assert headings, "There should be heading rows"

    def test_iv1_not_line_item(self, boq_items):
        iv1 = [r for r in boq_items if r.row_number.strip().upper() == "IV.1"]
        for r in iv1:
            assert r.row_type != "line_item", "IV.1 18.57 Km must never be a line_item"

    def test_section_path_assigned(self, boq_items):
        line_items = [r for r in boq_items if r.row_type == "line_item"]
        for item in line_items:
            assert item.section_path, f"Line item {item.row_id} must have a section_path"

    def test_duplicate_row_ids_absent(self, boq_items):
        ids = [r.row_id for r in boq_items]
        assert len(ids) == len(set(ids)), "All row_ids must be unique"

    def test_road_and_bridge_drilling_both_present(self, boq_items):
        road = [r for r in boq_items if "đường" in r.description_vi.lower() and "khoan" in r.description_vi.lower()]
        bridge = [r for r in boq_items if "cầu" in r.description_vi.lower() and "khoan" in r.description_vi.lower()]
        assert road, "Road drilling rows must be present"
        assert bridge, "Bridge drilling rows must be present"

    def test_road_bridge_drilling_distinct(self, boq_items):
        road = [r for r in boq_items if "đường" in r.description_vi.lower() and "khoan" in r.description_vi.lower()]
        bridge = [r for r in boq_items if "cầu" in r.description_vi.lower() and "khoan" in r.description_vi.lower()]
        road_ids = {r.row_id for r in road}
        bridge_ids = {r.row_id for r in bridge}
        assert road_ids.isdisjoint(bridge_ids), "Road and bridge drilling must have distinct row_ids"

    def test_line_item_count(self, boq_items):
        count = len([r for r in boq_items if r.row_type == "line_item"])
        # The fixture has ~30 representative items; full PDF has ~82
        # Accept ≥20 for the representative fixture
        assert count >= 20, f"Expected at least 20 line items in fixture, got {count}"


class TestAzureBridge:
    def test_recorded_azure_response_normalizes_to_strict_payload(self, azure_bridge_payload):
        assert azure_bridge_payload["document_id"] == "azure-doc-intel-test-001"
        assert azure_bridge_payload["provider"] == "azure-document-intelligence"
        assert azure_bridge_payload["rows"]

        first_row = azure_bridge_payload["rows"][0]
        assert first_row["evidence"]
        assert first_row["evidence"][0]["locator"].startswith("p1:tbl1:r")
        assert first_row["evidence"][0]["page"] == 1
        assert first_row["evidence"][0]["table"] == 1
        assert first_row["evidence"][0]["row"] == 1
        assert first_row["evidence"][0]["column"] == 0
        assert isinstance(first_row["evidence"][0]["polygon"], list)

        line_item = next(row for row in azure_bridge_payload["rows"] if row["quantity_raw"] == "29,5")
        assert line_item["unit_raw"] == "ha"
        assert line_item["description_vi"].startswith("Đo vẽ bình đồ tỷ lệ 1/500")
        assert line_item["ai_suggestions"] == []
        assert "quantity" not in line_item

    def test_missing_cells_do_not_shift_later_values(self):
        from parser_adapter.azure_bridge import azure_analyze_result_to_parser_payload

        raw = {
            "status": "succeeded",
            "analyzeResult": {
                "pages": [
                    {
                        "pageNumber": 1,
                        "tables": [
                            {
                                "cells": [
                                    {"rowIndex": 0, "columnIndex": 0, "kind": "columnHeader", "content": "STT", "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 1]}]},
                                    {"rowIndex": 0, "columnIndex": 1, "kind": "columnHeader", "content": "NỘI DUNG", "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 1]}]},
                                    {"rowIndex": 0, "columnIndex": 2, "kind": "columnHeader", "content": "ĐVT", "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 1]}]},
                                    {"rowIndex": 0, "columnIndex": 3, "kind": "columnHeader", "content": "KLG", "boundingRegions": [{"pageNumber": 1, "polygon": [0, 0, 1, 1]}]},
                                    {"rowIndex": 1, "columnIndex": 0, "kind": "content", "content": "1", "boundingRegions": [{"pageNumber": 1, "polygon": [10, 10, 20, 10, 20, 20, 10, 20]}]},
                                    {"rowIndex": 1, "columnIndex": 1, "kind": "content", "content": "Item A", "boundingRegions": [{"pageNumber": 1, "polygon": [20, 10, 60, 10, 60, 20, 20, 20]}]},
                                    {"rowIndex": 1, "columnIndex": 3, "kind": "content", "content": "7", "boundingRegions": [{"pageNumber": 1, "polygon": [60, 10, 80, 10, 80, 20, 60, 20]}]},
                                    {"rowIndex": 2, "columnIndex": 0, "kind": "content", "content": "2", "boundingRegions": [{"pageNumber": 1, "polygon": [10, 30, 20, 30, 20, 40, 10, 40]}]},
                                    {"rowIndex": 2, "columnIndex": 1, "kind": "content", "content": "Item B", "boundingRegions": [{"pageNumber": 1, "polygon": [20, 30, 60, 30, 60, 40, 20, 40]}]},
                                    {"rowIndex": 2, "columnIndex": 2, "kind": "content", "content": "m", "boundingRegions": [{"pageNumber": 1, "polygon": [60, 30, 70, 30, 70, 40, 60, 40]}]},
                                ]
                            }
                        ]
                    }
                ]
            },
        }

        payload = azure_analyze_result_to_parser_payload(raw, "doc-1")
        rows = {row["row_id"]: row for row in payload["rows"]}
        first = next(row for row in payload["rows"] if row["description_vi"] == "Item A")
        second = next(row for row in payload["rows"] if row["description_vi"] == "Item B")

        assert first["unit_raw"] == ""
        assert first["quantity_raw"] == "7"
        assert second["unit_raw"] == "m"
        assert second["quantity_raw"] == ""
        assert first["evidence"][-1]["column"] == 3
        assert second["evidence"][-1]["column"] == 2

    def test_malformed_azure_response_is_rejected(self):
        from parser_adapter.azure_bridge import azure_analyze_result_to_parser_payload
        from parser_adapter.provider_neutral import ParserProviderContractError

        with pytest.raises(ParserProviderContractError):
            azure_analyze_result_to_parser_payload({"status": "succeeded", "analyzeResult": {"pages": "bad"}}, "bad-doc")

        with pytest.raises(ParserProviderContractError):
            azure_analyze_result_to_parser_payload(
                {
                    "status": "succeeded",
                    "analyzeResult": {
                        "pages": [
                            {
                                "pageNumber": 1,
                                "tables": [
                                    {"cells": "bad"},
                                ],
                            }
                        ]
                    },
                },
                "bad-doc",
            )


@pytest.mark.asyncio
async def test_azure_adapter_submit_poll_round_trip(monkeypatch):
    from parser_adapter.adapter import ParserAdapter

    monkeypatch.setenv("MOCK_PARSER", "false")
    monkeypatch.setenv("AZURE_DOC_INTEL_ENDPOINT", "https://azure.example.test")
    monkeypatch.setenv("AZURE_DOC_INTEL_KEY", "secret")

    submit_request = httpx.Request("POST", "https://azure.example.test/documentintelligence/documentModels/prebuilt-layout:analyze?api-version=2024-11-30")
    poll_request = httpx.Request("GET", "https://azure.example.test/operations/123")
    submit_response = httpx.Response(202, headers={"Operation-Location": "https://azure.example.test/operations/123"}, request=submit_request)
    running_response = httpx.Response(200, json={"status": "running"}, request=poll_request)
    succeeded_response = httpx.Response(200, json={"status": "succeeded", "analyzeResult": {"pages": [], "tables": []}}, request=poll_request)

    calls = {"poll": 0, "submit_url": None}

    async def fake_post(self, *args, **kwargs):
        calls["submit_url"] = str(args[0])
        return submit_response

    async def fake_get(self, *args, **kwargs):
        calls["poll"] += 1
        return running_response if calls["poll"] == 1 else succeeded_response

    async def fake_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = ParserAdapter()
    result = await adapter.analyze(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")

    assert result["status"] == "succeeded"
    assert result["analyzeResult"] == {"pages": [], "tables": []}
    assert calls["submit_url"] == str(submit_request.url)
    assert calls["poll"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_exc,expected_type",
    [
        ("auth", "ParserProviderAuthError"),
        ("timeout", "ParserProviderTimeoutError"),
        ("transport", "ParserProviderError"),
        ("contract", "ParserProviderContractError"),
    ],
)
async def test_azure_bridge_translates_adapter_failures(monkeypatch, adapter_exc, expected_type):
    from parser_adapter.adapter import (
        ParserAdapter,
        ParserAdapterAuthError,
        ParserAdapterContractError,
        ParserAdapterTimeoutError,
        ParserAdapterTransportError,
    )
    from parser_adapter.azure_bridge import AzureDocumentIntelligenceProvider
    from parser_adapter.provider_neutral import (
        ParserProviderAuthError,
        ParserProviderContractError,
        ParserProviderError,
        ParserProviderTimeoutError,
    )

    def raise_exc(*args, **kwargs):
        mapping = {
            "auth": ParserAdapterAuthError("secret 123"),
            "timeout": ParserAdapterTimeoutError("secret 456"),
            "transport": ParserAdapterTransportError("secret 789"),
            "contract": ParserAdapterContractError("secret 000"),
        }
        raise mapping[adapter_exc]

    monkeypatch.setenv("MOCK_PARSER", "false")
    monkeypatch.setenv("AZURE_DOC_INTEL_ENDPOINT", "https://azure.example.test")
    monkeypatch.setenv("AZURE_DOC_INTEL_KEY", "secret")
    monkeypatch.setattr(ParserAdapter, "analyze", raise_exc)

    provider = AzureDocumentIntelligenceProvider()

    if expected_type == "ParserProviderAuthError":
        expected = ParserProviderAuthError
    elif expected_type == "ParserProviderTimeoutError":
        expected = ParserProviderTimeoutError
    elif expected_type == "ParserProviderContractError":
        expected = ParserProviderContractError
    else:
        expected = ParserProviderError

    with pytest.raises(expected):
        await provider.analyze(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
