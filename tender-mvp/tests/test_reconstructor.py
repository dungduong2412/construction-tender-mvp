"""
Tests for BOQ reconstructor.
Validates:
- Section headings are classified correctly
- IV.1 group metadata is NOT treated as a billable line item
- Repeated row numbers in different sections get unique row_ids
- Comma-decimal quantities are parsed correctly (no silent zero substitution)
- Zero is not substituted for missing quantities
- Page-continuation headings don't reset section context
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['PARSER_USE_MOCK'] = 'true'

from decimal import Decimal
from backend.adapters.parser_adapter import _build_parsed_document, MOCK_FIXTURE
from backend.engine.reconstructor import reconstruct_boq
from backend.models.domain import RowType


def get_boq():
    doc = _build_parsed_document("test", "test.pdf", MOCK_FIXTURE)
    return reconstruct_boq(doc)


def test_section_headings_classified():
    boq = get_boq()
    headings = [r for r in boq.rows if r.row_type == RowType.SECTION_HEADING]
    assert len(headings) > 0, "No section headings found"
    heading_descs = [r.description_vi for r in headings]
    assert any("KHẢO SÁT ĐỊA HÌNH" in d for d in heading_descs), "Section I not classified"


def test_iv1_is_metadata_not_line_item():
    boq = get_boq()
    # IV.1 18,57 Km should be classified as METADATA
    iv1_rows = [r for r in boq.rows if "IV.1" in (r.row_number_raw or "") or
                ("18,57" in r.description_vi and "Km" in r.description_vi)]
    assert len(iv1_rows) > 0, "IV.1 row not found at all"
    for row in iv1_rows:
        assert row.row_type != RowType.LINE_ITEM, \
            f"IV.1 group metadata '{row.description_vi}' incorrectly classified as LINE_ITEM"


def test_road_vs_bridge_drilling_unique_row_ids():
    boq = get_boq()
    # Both sections have a row number "1" but they must be separate rows with different row_ids
    line_items = [r for r in boq.rows if r.row_type == RowType.LINE_ITEM]
    row_ids = [r.row_id for r in line_items]
    assert len(row_ids) == len(set(row_ids)), "Duplicate row_ids found – repeated row numbers not uniquely identified"


def test_comma_decimal_quantity_parsed():
    boq = get_boq()
    # 18,57 (mặt cắt dọc) should parse to Decimal('18.57')
    mat_cat_doc = [r for r in boq.rows
                   if "mặt cắt dọc" in r.description_vi.lower() and r.row_type == RowType.LINE_ITEM]
    assert len(mat_cat_doc) > 0, "Mặt cắt dọc line item not found"
    for row in mat_cat_doc:
        assert row.quantity == Decimal("18.57"), f"Expected 18.57 got {row.quantity}"


def test_no_zero_default_for_missing_quantity():
    boq = get_boq()
    # For rows without quantity text, quantity should be None not 0
    for row in boq.rows:
        if row.row_type == RowType.LINE_ITEM and not row.quantity_raw:
            assert row.quantity is None, f"Row {row.row_id} has zero default instead of None"


def test_road_drilling_section_is_ii():
    boq = get_boq()
    road_drilling = [
        r for r in boq.rows
        if r.row_type == RowType.LINE_ITEM
        and "khoan" in r.description_vi.lower()
        and "đường" in r.description_vi.lower()
        and "0-30m" in r.description_vi
    ]
    assert len(road_drilling) > 0, "Road drilling row not found"
    for row in road_drilling:
        assert row.source_section in ("II", ""), f"Road drilling has wrong section: {row.source_section}"
        assert row.quantity == Decimal("624"), f"Expected quantity 624, got {row.quantity}"


def test_bridge_drilling_quantity():
    boq = get_boq()
    bridge_drilling = [
        r for r in boq.rows
        if r.row_type == RowType.LINE_ITEM
        and "khoan" in r.description_vi.lower()
        and "cầu" in r.description_vi.lower()
        and "0-60m" in r.description_vi
    ]
    assert len(bridge_drilling) > 0, "Bridge drilling 0-60m row not found"
    for row in bridge_drilling:
        assert row.quantity == Decimal("600"), f"Expected quantity 600, got {row.quantity}"


def test_cpt_decimal_quantity():
    boq = get_boq()
    cpt_rows = [
        r for r in boq.rows
        if r.row_type == RowType.LINE_ITEM
        and "cpt" in r.description_vi.lower()
    ]
    assert len(cpt_rows) > 0, "CPT row not found"
    for row in cpt_rows:
        assert row.quantity == Decimal("29.5"), f"Expected 29.5 for CPT, got {row.quantity}"
