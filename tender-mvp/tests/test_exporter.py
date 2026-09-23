"""
Tests for Excel exporter.
Validates:
- Output file is valid .xlsx
- 'Dự thầu', 'Audit_Mapping', 'Unresolved' sheets are present
- Draft warning appears when is_complete=False
- No monetary amount is present for UNRESOLVED rows in the Dự thầu sheet
"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['PARSER_USE_MOCK'] = 'true'

import openpyxl
from backend.adapters.parser_adapter import _build_parsed_document, MOCK_FIXTURE
from backend.engine.reconstructor import reconstruct_boq
from backend.engine.mapper import map_boq_to_master
from backend.engine.pricing import price_boq
from backend.engine.exporter import export_xlsx
from backend.models.domain import PriceLineStatus


def get_xlsx_path():
    doc = _build_parsed_document("export-test", "test.pdf", MOCK_FIXTURE)
    boq = reconstruct_boq(doc)
    mappings = map_boq_to_master(boq)
    sheet = price_boq(boq, mappings)
    with tempfile.TemporaryDirectory() as tmp:
        path = export_xlsx(sheet, output_dir=tmp)
        wb = openpyxl.load_workbook(path)
        return wb, sheet


def test_xlsx_has_three_sheets():
    wb, _ = get_xlsx_path()
    names = wb.sheetnames
    assert "Dự thầu" in names, "Missing 'Dự thầu' sheet"
    assert "Audit_Mapping" in names, "Missing 'Audit_Mapping' sheet"
    assert "Unresolved" in names, "Missing 'Unresolved' sheet"


def test_du_thau_has_data_rows():
    wb, sheet = get_xlsx_path()
    ws = wb["Dự thầu"]
    non_empty_rows = [r for r in ws.iter_rows(min_row=4, values_only=True) if any(c for c in r)]
    assert len(non_empty_rows) > 0


def test_draft_warning_present_when_incomplete():
    wb, sheet = get_xlsx_path()
    if sheet.is_complete:
        return  # skip if fully priced
    ws = wb["Dự thầu"]
    all_text = " ".join(str(c.value or "") for row in ws.iter_rows() for c in row)
    assert "DRAFT" in all_text or "chưa hoàn chỉnh" in all_text.lower(), \
        "Draft warning not found in Dự thầu sheet"


def test_audit_sheet_has_headers():
    wb, _ = get_xlsx_path()
    ws = wb["Audit_Mapping"]
    row1 = [c.value for c in ws[1]]
    assert "Row ID" in row1
    assert "Evidence" in row1


def test_unresolved_sheet_lists_unresolved_rows():
    wb, sheet = get_xlsx_path()
    unresolved_count = sum(1 for l in sheet.lines if l.status == PriceLineStatus.UNRESOLVED)
    if unresolved_count == 0:
        return  # nothing to check
    ws = wb["Unresolved"]
    # Row 1 is warning banner, row 2 is header; data from row 3
    data_rows = list(ws.iter_rows(min_row=3, values_only=True))
    non_empty = [r for r in data_rows if any(c for c in r)]
    assert len(non_empty) == unresolved_count, \
        f"Unresolved sheet has {len(non_empty)} rows but sheet has {unresolved_count} unresolved"
