import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ITEMS_PATH = PROJECT_ROOT / "master-data" / "items_v1.json"
GAP_REPORT_PATH = PROJECT_ROOT / "MASTER_DATA_GAP_REPORT.md"


def _load_items() -> list[dict]:
    return json.loads(ITEMS_PATH.read_text(encoding="utf-8"))


def test_seed_items_file_exists():
    assert ITEMS_PATH.exists(), "master-data/items_v1.json must exist"


def test_unit_prices_are_positive_and_non_placeholder():
    placeholder_tokens = {"placeholder", "tbd", "todo", "mock", "sample", "dummy"}
    for item in _load_items():
        assert float(item["unit_price"]) > 0, f"{item['item_code']} has non-positive price"
        text = f"{item.get('description_vi', '')} {item.get('formula_ref', '')}".lower()
        assert not any(token in text for token in placeholder_tokens), (
            f"{item['item_code']} appears to use placeholder metadata"
        )


def test_seed_items_have_traceable_source_sheet_only():
    approved_sheets = {"Đơn giá chi tiết", "Giá tổng hợp"}
    for item in _load_items():
        assert item.get("source_sheet") in approved_sheets, (
            f"{item['item_code']} has non-approved source_sheet={item.get('source_sheet')}"
        )


def test_item_codes_unique_and_road_bridge_drilling_both_present():
    items = _load_items()
    codes = [item["item_code"] for item in items]
    assert len(codes) == len(set(codes)), "Duplicate item_code values in master seed"

    road = [
        item
        for item in items
        if item.get("tags", {}).get("road_bridge_context") == "road"
        and item.get("tags", {}).get("drilling_depth") == "0-30m"
    ]
    bridge = [
        item
        for item in items
        if item.get("tags", {}).get("road_bridge_context") == "bridge"
        and item.get("tags", {}).get("drilling_depth") == "0-60m"
    ]
    assert road, "Missing road drilling 0-30m master item"
    assert bridge, "Missing bridge drilling 0-60m master item"


def test_gap_report_documents_unresolved_and_not_fully_approved_prices():
    assert GAP_REPORT_PATH.exists(), "MASTER_DATA_GAP_REPORT.md must exist"
    content = GAP_REPORT_PATH.read_text(encoding="utf-8").lower()
    assert "one-time, read-only" in content
    assert "unresolved" in content
    assert "must be updated" in content
