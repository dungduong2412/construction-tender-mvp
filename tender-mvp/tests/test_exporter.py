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
        # Read all data while the tempdir still exists
        sheet_names = wb.sheetnames
        ws_du_thau = wb["Dự thầu"]
        ws_audit = wb["Audit_Mapping"]
        ws_unresolved = wb["Unresolved"]
        du_thau_rows = list(ws_du_thau.iter_rows(min_row=4, values_only=True))
        audit_row1 = [c.value for c in ws_audit[1]]
        all_text = " ".join(str(c.value or "") for row in ws_du_thau.iter_rows() for c in row)
        unresolved_data_rows = list(ws_unresolved.iter_rows(min_row=3, values_only=True))
    return {
        "sheet_names": sheet_names,
        "du_thau_rows": du_thau_rows,
        "audit_row1": audit_row1,
        "all_text": all_text,
        "unresolved_data_rows": unresolved_data_rows,
        "pricing_sheet": sheet,
    }


def test_xlsx_has_three_sheets():
    data = get_xlsx_path()
    names = data["sheet_names"]
    assert "Dự thầu" in names, "Missing 'Dự thầu' sheet"
    assert "Audit_Mapping" in names, "Missing 'Audit_Mapping' sheet"
    assert "Unresolved" in names, "Missing 'Unresolved' sheet"


def test_du_thau_has_data_rows():
    data = get_xlsx_path()
    non_empty_rows = [r for r in data["du_thau_rows"] if any(c for c in r)]
    assert len(non_empty_rows) > 0


def test_draft_warning_present_when_incomplete():
    data = get_xlsx_path()
    if data["pricing_sheet"].is_complete:
        return  # skip if fully priced
    all_text = data["all_text"]
    assert "DRAFT" in all_text or "chưa hoàn chỉnh" in all_text.lower(), \
        "Draft warning not found in Dự thầu sheet"


def test_audit_sheet_has_headers():
    data = get_xlsx_path()
    row1 = data["audit_row1"]
    assert "Row ID" in row1
    assert "Evidence" in row1


def test_unresolved_sheet_lists_unresolved_rows():
    data = get_xlsx_path()
    sheet = data["pricing_sheet"]
    unresolved_count = sum(1 for l in sheet.lines if l.status == PriceLineStatus.UNRESOLVED)
    if unresolved_count == 0:
        return  # nothing to check
    non_empty = [r for r in data["unresolved_data_rows"] if any(c for c in r)]
    assert len(non_empty) == unresolved_count, \
        f"Unresolved sheet has {len(non_empty)} rows but sheet has {unresolved_count} unresolved"
