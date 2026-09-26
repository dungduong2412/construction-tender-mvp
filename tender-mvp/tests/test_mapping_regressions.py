"""Regression tests for exact mapping outcomes and status classification."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from boq.reconstructor import BOQLineItem
from database import MappingStatus
from pricing_engine.engine import PriceResult
from routers.jobs import _derive_mapping_status
from semantic_mapper.mapper import MasterCandidate, MappingOutput, SemanticMapper


def _make_item(desc: str, unit: str, qty_raw: str = "1", qty: float = 1.0, row_id: str = "regression-row") -> BOQLineItem:
    return BOQLineItem(
        row_id=row_id,
        row_number="1",
        section_path="II > II.1",
        description_vi=desc,
        unit_raw=unit,
        quantity_raw=qty_raw,
        quantity=qty,
        page=1,
        region="",
        row_type="line_item",
        doc_order=0,
    )


def _load_candidates() -> list[MasterCandidate]:
    path = Path(__file__).parent.parent / "master-data" / "items_v1.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    candidates = []
    for idx, item in enumerate(items, start=1):
        candidates.append(
            MasterCandidate(
                id=idx,
                item_code=item["item_code"],
                description_vi=item["description_vi"],
                unit=item["unit"],
                unit_price=float(item["unit_price"]),
                tags=item.get("tags", {}),
            )
        )
    return candidates


def _code_for_id(candidates: list[MasterCandidate], master_id: int | None) -> str | None:
    if master_id is None:
        return None
    m = next((c for c in candidates if c.id == master_id), None)
    return m.item_code if m else None


@pytest.mark.asyncio
async def test_exact_required_mappings_in_mock_mode():
    mapper = SemanticMapper(mock_ai=True)
    candidates = _load_candidates()

    cases = [
        (_make_item("Đo vẽ bình đồ tỷ lệ 1/500 vùng đồi núi", "ha", "19,5", 19.5, row_id="case-1"), "KS-002"),
        (_make_item("Đo vẽ bình đồ tỷ lệ 1/200 vùng đồng bằng", "ha", "5", 5.0, row_id="case-2"), "KS-003"),
        (_make_item("Khoan thăm dò địa chất đường, lỗ khoan 0–30m, đất cấp III", "m", "120", 120.0, row_id="case-3"), "KS-029"),
        (_make_item("Lấy mẫu đất nguyên dạng (trong lỗ khoan đường)", "mẫu", "24", 24.0, row_id="case-4"), "KS-008"),
        (_make_item("Thí nghiệm xuyên tiêu chuẩn SPT (trong lỗ khoan đường)", "TN", "120", 120.0, row_id="case-5"), "KS-014"),
    ]

    for item, expected_code in cases:
        out = await mapper.map_item(item, candidates, "v1")
        got_code = _code_for_id(candidates, out.master_item_id)
        assert got_code == expected_code, f"Expected {expected_code} but got {got_code} for '{item.description_vi}'"


def test_billable_unpriced_never_marked_mapped_and_priced():
    mapping_out = MappingOutput(
        master_item_id=6,
        confidence=0.91,
        tags={},
        evidence="mock",
        unresolved_reason=None,
        status="resolved",
        classification="mapped_and_priced",
    )
    price_out = PriceResult(
        row_id="r-1",
        status="unresolved",
        unit_price_str=None,
        extended_amount_str=None,
        price_source="master_v1",
        formula_ref=None,
        coeff_applied=[],
        unit_rule_ref=None,
        error_reason="Mapped master price is missing or zero; manual review required.",
    )

    derived = _derive_mapping_status(mapping_out, price_out)
    assert derived == MappingStatus.mapped_price_unavailable
