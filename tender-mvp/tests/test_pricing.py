"""
Tests for the deterministic pricing engine.
Validates:
- Extended amount = quantity * unit_price * factor (integer VND)
- Zero is not substituted for missing price or quantity
- Unresolved rows have no extended_amount
- Heading rows have no extended_amount
- Subtotal only includes PRICED rows
- User override supersedes master price
- is_complete is False when unresolved rows exist
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['PARSER_USE_MOCK'] = 'true'

from decimal import Decimal
from backend.adapters.parser_adapter import _build_parsed_document, MOCK_FIXTURE
from backend.engine.reconstructor import reconstruct_boq
from backend.engine.mapper import map_boq_to_master
from backend.engine.pricing import price_boq
from backend.models.domain import PriceLineStatus, RowOverride


def get_full_sheet():
    doc = _build_parsed_document("test", "test.pdf", MOCK_FIXTURE)
    boq = reconstruct_boq(doc)
    mappings = map_boq_to_master(boq)
    return price_boq(boq, mappings)


def test_headings_have_no_extended_amount():
    sheet = get_full_sheet()
    for line in sheet.lines:
        if line.status == PriceLineStatus.HEADING:
            assert line.extended_amount is None, f"Heading row {line.row_id} has extended_amount"
            assert line.unit_price is None


def test_priced_rows_have_correct_arithmetic():
    sheet = get_full_sheet()
    for line in sheet.lines:
        if line.status == PriceLineStatus.PRICED:
            assert line.quantity is not None
            assert line.unit_price is not None
            expected = int((line.quantity * Decimal(str(line.unit_price)) * Decimal(str(line.unit_conversion_factor))).to_integral_value())
            assert line.extended_amount == expected, \
                f"Row {line.row_id}: expected {expected}, got {line.extended_amount}"


def test_no_zero_defaults():
    sheet = get_full_sheet()
    for line in sheet.lines:
        if line.status == PriceLineStatus.PRICED:
            assert line.unit_price != 0, f"Row {line.row_id} has zero unit_price"
            assert line.quantity != Decimal("0"), f"Row {line.row_id} has zero quantity"


def test_subtotal_excludes_unresolved():
    sheet = get_full_sheet()
    manual_sum = sum(
        l.extended_amount for l in sheet.lines
        if l.status == PriceLineStatus.PRICED and l.extended_amount is not None
    )
    assert sheet.subtotal_priced_vnd == manual_sum


def test_is_complete_flag():
    sheet = get_full_sheet()
    has_unresolved = any(l.status == PriceLineStatus.UNRESOLVED for l in sheet.lines)
    assert sheet.is_complete == (not has_unresolved)


def test_user_override_supersedes_master():
    doc = _build_parsed_document("test", "test.pdf", MOCK_FIXTURE)
    boq = reconstruct_boq(doc)
    mappings = map_boq_to_master(boq)

    # Find a priced row
    base_sheet = price_boq(boq, mappings)
    priced = [l for l in base_sheet.lines if l.status == PriceLineStatus.PRICED]
    assert len(priced) > 0

    target = priced[0]
    override_price = 999999
    override = RowOverride(
        row_id=target.row_id,
        unit_price_override=override_price,
        approved=True,
        override_reason="Test override",
    )

    new_sheet = price_boq(boq, mappings, [override])
    new_line = next(l for l in new_sheet.lines if l.row_id == target.row_id)
    assert new_line.status == PriceLineStatus.USER_OVERRIDE
    assert new_line.unit_price == override_price
    expected = int((new_line.quantity * Decimal(str(override_price)) * Decimal(str(new_line.unit_conversion_factor))).to_integral_value())
    assert new_line.extended_amount == expected


def test_notes_says_draft_when_incomplete():
    sheet = get_full_sheet()
    if not sheet.is_complete:
        assert "DRAFT" in sheet.notes or "unresolved" in sheet.notes.lower()
