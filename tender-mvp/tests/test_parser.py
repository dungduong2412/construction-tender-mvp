"""
Tests for the Parser Adapter mock fixture and ParsedDocument normalization.
Validates that:
- Mock fixture parses without errors
- All 4 pages are present
- Key BOQ rows are identifiable (e.g. road drilling 0-30m vs bridge drilling 0-60m)
- Vietnamese comma-decimal text is preserved in raw output
"""
import sys
import os
import asyncio
import pytest

# Allow imports from the backend package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ['PARSER_USE_MOCK'] = 'true'

from backend.adapters.parser_adapter import parse_pdf, MOCK_FIXTURE, _build_parsed_document
from backend.models.domain import ParsedDocument


def test_mock_fixture_parses_four_pages():
    doc = _build_parsed_document("test-job", "test.pdf", MOCK_FIXTURE)
    assert isinstance(doc, ParsedDocument)
    assert doc.page_count == 4


def test_all_pages_have_tables():
    doc = _build_parsed_document("test-job", "test.pdf", MOCK_FIXTURE)
    for page in doc.pages:
        assert len(page.tables) >= 1, f"Page {page.page_number} has no tables"


def test_road_drilling_row_present():
    """Road drilling (0-30m, 624m) must be on page 1."""
    doc = _build_parsed_document("test-job", "test.pdf", MOCK_FIXTURE)
    page1 = next(p for p in doc.pages if p.page_number == 1)
    texts = [c.text for t in page1.tables for c in t.cells]
    assert any("0-30m" in t for t in texts), "Road drilling 0-30m not found on page 1"
    assert any("624" in t for t in texts), "Road drilling quantity 624 not found on page 1"


def test_bridge_drilling_row_present():
    """Bridge drilling (0-60m, 600m) must be on page 2, in a different section."""
    doc = _build_parsed_document("test-job", "test.pdf", MOCK_FIXTURE)
    page2 = next(p for p in doc.pages if p.page_number == 2)
    texts = [c.text for t in page2.tables for c in t.cells]
    assert any("0-60m" in t for t in texts), "Bridge drilling 0-60m not found on page 2"
    assert any("600" in t for t in texts), "Bridge drilling quantity 600 not found on page 2"


def test_iv1_metadata_preserved():
    """IV.1 18,57 Km group metadata must be present on page 2."""
    doc = _build_parsed_document("test-job", "test.pdf", MOCK_FIXTURE)
    page2 = next(p for p in doc.pages if p.page_number == 2)
    texts = [c.text for t in page2.tables for c in t.cells]
    assert any("IV.1" in t for t in texts), "IV.1 metadata row not found on page 2"
    assert any("18,57" in t for t in texts), "18,57 Km metadata not found on page 2"


def test_vietnamese_comma_decimal_preserved():
    """Comma-decimal quantities must not be silently corrupted."""
    doc = _build_parsed_document("test-job", "test.pdf", MOCK_FIXTURE)
    all_texts = [c.text for p in doc.pages for t in p.tables for c in t.cells]
    # 18,57 and 29,5 must appear verbatim
    assert any("18,57" in t for t in all_texts), "18,57 (mặt cắt dọc) not found"
    assert any("29,5" in t for t in all_texts), "29,5 (CPT depth) not found"


@pytest.mark.asyncio
async def test_async_parse_pdf():
    doc = await parse_pdf("async-test", "dummy.pdf", b"%PDF-1.4 fake bytes")
    assert doc.page_count == 4
    assert doc.job_id == "async-test"
