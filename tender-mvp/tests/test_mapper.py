"""
Tests for AI semantic mapping and unit normalization.
Validates:
- Road drilling maps to MD-003 (not MD-006 bridge item)
- Bridge drilling maps to MD-006 (not MD-003 road item)
- Section headings/metadata get HEADING status
- Ambiguous rows are flagged correctly
- Unit normalization: 100m ≠ m without approved conversion
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['PARSER_USE_MOCK'] = 'true'

from backend.adapters.parser_adapter import _build_parsed_document, MOCK_FIXTURE
from backend.engine.reconstructor import reconstruct_boq
from backend.engine.mapper import map_boq_to_master, _extract_tags
from backend.engine.master_loader import get_unit_conversion
from backend.models.domain import MappingStatus, RowType


def get_boq():
    doc = _build_parsed_document("test", "test.pdf", MOCK_FIXTURE)
    return reconstruct_boq(doc)


def get_mappings():
    boq = get_boq()
    return {r.row_id: r for r in map_boq_to_master(boq)}


def test_headings_get_heading_status():
    boq = get_boq()
    mappings = {r.row_id: r for r in map_boq_to_master(boq)}
    for row in boq.rows:
        if row.row_type != RowType.LINE_ITEM:
            m = mappings.get(row.row_id)
            assert m is not None
            assert m.status == MappingStatus.HEADING, \
                f"Expected HEADING for row_type={row.row_type}, got {m.status}"


def test_road_drilling_maps_to_road_master():
    boq = get_boq()
    road_drill_rows = [
        r for r in boq.rows
        if r.row_type == RowType.LINE_ITEM
        and "khoan" in r.description_vi.lower()
        and "đường" in r.description_vi.lower()
        and "0-30m" in r.description_vi
    ]
    assert len(road_drill_rows) > 0
    mappings = get_mappings()
    for row in road_drill_rows:
        m = mappings[row.row_id]
        assert m.status in (MappingStatus.MATCHED, MappingStatus.AMBIGUOUS), \
            f"Road drilling should be MATCHED/AMBIGUOUS, got {m.status}"
        if m.master_id:
            # Must be a road-context master item, NOT a bridge item
            assert m.master_id in ("MD-003", "MD-004", "MD-020"), \
                f"Road drilling mapped to wrong master: {m.master_id}"


def test_bridge_drilling_maps_to_bridge_master():
    boq = get_boq()
    bridge_drill_rows = [
        r for r in boq.rows
        if r.row_type == RowType.LINE_ITEM
        and "khoan" in r.description_vi.lower()
        and "cầu" in r.description_vi.lower()
    ]
    assert len(bridge_drill_rows) > 0
    mappings = get_mappings()
    for row in bridge_drill_rows:
        m = mappings[row.row_id]
        if m.master_id:
            assert m.master_id in ("MD-005", "MD-006", "MD-007", "MD-023"), \
                f"Bridge drilling mapped to wrong (road) master: {m.master_id} for '{row.description_vi}'"


def test_road_bridge_not_conflated():
    """Critical: road drilling must NOT map to bridge master and vice versa."""
    boq = get_boq()
    mappings = get_mappings()
    for row in boq.rows:
        if row.row_type != RowType.LINE_ITEM:
            continue
        m = mappings.get(row.row_id)
        if not m or not m.master_id:
            continue
        if "cầu" in row.description_vi and "khoan" in row.description_vi.lower():
            assert m.master_id not in ("MD-003", "MD-004", "MD-020"), \
                f"Bridge row mapped to road master: {m.master_id}"
        if "đường" in row.description_vi and "khoan" in row.description_vi.lower():
            assert m.master_id not in ("MD-005", "MD-006", "MD-007", "MD-023"), \
                f"Road row mapped to bridge master: {m.master_id}"


def test_tag_extraction_road_drilling():
    tags = _extract_tags("Khoan địa chất công trình đường, đất cấp I-II, độ sâu 0-30m", "II KHẢO SÁT ĐỊA CHẤT ĐƯỜNG")
    assert tags.context == "road"
    assert tags.work_type == "drilling"
    assert tags.depth_range == "0-30m"
    assert tags.soil_class == "I-II"


def test_tag_extraction_bridge_drilling():
    tags = _extract_tags("Khoan địa chất công trình cầu, đất cấp I-II, độ sâu 0-60m, trên cạn", "III KHẢO SÁT ĐỊA CHẤT CẦU")
    assert tags.context == "bridge"
    assert tags.work_type == "drilling"
    assert tags.depth_range == "0-60m"
    assert tags.condition == "on_land"


def test_tag_extraction_topo_map_scale():
    tags = _extract_tags("Đo đạc bình đồ tỷ lệ 1/500, địa hình đồng bằng", "I KHẢO SÁT ĐỊA HÌNH")
    assert tags.work_type == "topographic_mapping"
    assert tags.scale == "1:500"
    assert tags.terrain == "flat"


def test_unit_rule_100m_to_m():
    """100m → m must have an approved conversion factor of 100."""
    factor = get_unit_conversion("100m", "m")
    assert factor == 100.0


def test_unit_rule_100ha_to_ha():
    factor = get_unit_conversion("100ha", "ha")
    assert factor == 100.0


def test_unit_no_silent_conflation():
    """Units without an approved rule return None, not 1.0."""
    factor = get_unit_conversion("TN", "thí nghiệm")
    assert factor is None, "TN → thí nghiệm should not have an implicit conversion"


def test_same_unit_conversion_is_one():
    factor = get_unit_conversion("m", "m")
    assert factor == 1.0
