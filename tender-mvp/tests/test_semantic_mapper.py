"""
Tests for semantic mapper — distinction rules, unit mismatch, schema validation.
"""
import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from boq.reconstructor import BOQLineItem
from semantic_mapper.mapper import MasterCandidate, SemanticMapper, _apply_distinction_rules, _unit_mismatch_check


def make_item(desc, unit="m", qty_raw="100", qty=100.0, row_type="line_item") -> BOQLineItem:
    return BOQLineItem(
        row_id="test-row",
        row_number="1",
        section_path="II > II.1",
        description_vi=desc,
        unit_raw=unit,
        quantity_raw=qty_raw,
        quantity=qty,
        page=1,
        region="",
        row_type=row_type,
        doc_order=0,
    )


def make_candidate(id_, desc, unit="m", road_bridge=None, drilling_depth=None) -> MasterCandidate:
    tags = {}
    if road_bridge:
        tags["road_bridge_context"] = road_bridge
    if drilling_depth:
        tags["drilling_depth"] = drilling_depth
    return MasterCandidate(
        id=id_,
        item_code=f"KS-{id_:03d}",
        description_vi=desc,
        unit=unit,
        unit_price=380000.0,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# Distinction rules
# ---------------------------------------------------------------------------

class TestDistinctionRules:
    def test_road_drilling_excludes_bridge_candidates(self):
        item = make_item("Khoan thăm dò địa chất đường, lỗ khoan 0–30m")
        candidates = [
            make_candidate(1, "Khoan đường", road_bridge="road"),
            make_candidate(2, "Khoan cầu", road_bridge="bridge"),
        ]
        result = _apply_distinction_rules(item, candidates)
        assert all(c.tags.get("road_bridge_context") != "bridge" for c in result)
        assert any(c.id == 1 for c in result)
        assert not any(c.id == 2 for c in result)

    def test_bridge_drilling_excludes_road_candidates(self):
        item = make_item("Khoan thăm dò địa chất cầu, lỗ khoan 0–60m")
        candidates = [
            make_candidate(1, "Khoan đường", road_bridge="road"),
            make_candidate(2, "Khoan cầu", road_bridge="bridge"),
        ]
        result = _apply_distinction_rules(item, candidates)
        assert not any(c.id == 1 for c in result)
        assert any(c.id == 2 for c in result)

    def test_road_624m_vs_bridge_600m_distinct(self):
        """Non-negotiable: road 624m ≠ bridge 600m."""
        road_item = make_item("Khoan thăm dò địa chất đường, lỗ khoan 0–30m", qty_raw="624", qty=624)
        bridge_item = make_item("Khoan thăm dò địa chất cầu, lỗ khoan 0–60m", qty_raw="600", qty=600)

        candidates = [
            make_candidate(6, "Khoan đường 0-30m", road_bridge="road", drilling_depth="0-30m"),
            make_candidate(7, "Khoan cầu 0-60m", road_bridge="bridge", drilling_depth="0-60m"),
        ]

        road_result = _apply_distinction_rules(road_item, candidates)
        bridge_result = _apply_distinction_rules(bridge_item, candidates)

        assert any(c.id == 6 for c in road_result), "Road item must match road candidate"
        assert not any(c.id == 7 for c in road_result), "Road item must NOT match bridge candidate"
        assert any(c.id == 7 for c in bridge_result), "Bridge item must match bridge candidate"
        assert not any(c.id == 6 for c in bridge_result), "Bridge item must NOT match road candidate"

    def test_ambiguous_item_passes_all_candidates(self):
        """Item with neither 'đường' nor 'cầu' should pass all candidates."""
        item = make_item("Lấy mẫu đất nguyên dạng")
        candidates = [
            make_candidate(1, "Khoan đường", road_bridge="road"),
            make_candidate(2, "Khoan cầu", road_bridge="bridge"),
        ]
        result = _apply_distinction_rules(item, candidates)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Unit mismatch check
# ---------------------------------------------------------------------------

class TestUnitMismatch:
    @pytest.mark.parametrize("item_unit,cand_unit,expected_compatible", [
        ("ha", "100ha", False),   # silent conflation forbidden
        ("100ha", "ha", False),
        ("m", "100m", False),
        ("100m", "m", False),
        ("TN", "thí nghiệm", False),
        ("tn", "Thí nghiệm", False),
        ("m", "m", True),         # same unit OK
        ("ha", "ha", True),
        ("km", "km", True),
        ("mẫu", "mẫu", True),
        ("m", "km", True),        # different pair, not in forbidden set
    ])
    def test_unit_mismatch(self, item_unit, cand_unit, expected_compatible):
        result = _unit_mismatch_check(item_unit, cand_unit)
        assert result == expected_compatible, (
            f"_unit_mismatch_check('{item_unit}', '{cand_unit}') = {result}, expected {expected_compatible}"
        )


# ---------------------------------------------------------------------------
# Semantic mapper mock mode
# ---------------------------------------------------------------------------

class TestSemanticMapperMock:
    @pytest.mark.asyncio
    async def test_non_line_item_returns_error(self):
        mapper = SemanticMapper(mock_ai=True)
        item = make_item("CÔNG TÁC TRẮC ĐỊA", row_type="heading")
        result = await mapper.map_item(item, [], "v1")
        assert result.status == "error"
        assert result.master_item_id is None

    @pytest.mark.asyncio
    async def test_no_candidates_returns_unresolved(self):
        mapper = SemanticMapper(mock_ai=True)
        item = make_item("Đo vẽ bình đồ")
        result = await mapper.map_item(item, [], "v1")
        assert result.status == "unresolved"
        assert result.master_item_id is None

    @pytest.mark.asyncio
    async def test_unit_mismatch_all_candidates_returns_unresolved(self):
        mapper = SemanticMapper(mock_ai=True)
        item = make_item("Đo vẽ", unit="ha")
        candidates = [make_candidate(1, "Bình đồ 1/500", unit="100ha")]
        result = await mapper.map_item(item, candidates, "v1")
        # All candidates have unit mismatch → unresolved
        assert result.status == "unresolved"

    @pytest.mark.asyncio
    async def test_resolved_with_good_candidate(self):
        mapper = SemanticMapper(mock_ai=True)
        item = make_item("Đo vẽ bình đồ tỷ lệ 1/500", unit="ha")
        candidates = [make_candidate(1, "Đo vẽ bình đồ 1/500 đồng bằng", unit="ha")]
        result = await mapper.map_item(item, candidates, "v1")
        assert result.status == "resolved"
        assert result.master_item_id == 1

    @pytest.mark.asyncio
    async def test_caching(self):
        mapper = SemanticMapper(mock_ai=True)
        item = make_item("Test item", unit="m")
        candidates = [make_candidate(1, "Test master", unit="m")]
        r1 = await mapper.map_item(item, candidates, "v1")
        r2 = await mapper.map_item(item, candidates, "v1")
        assert r1 is r2, "Cached result must be the same object"
