"""
Tests for Excel exporter — sheet names, DRAFT label, totals.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from excel_exporter.exporter import ExportRow, generate_excel


def make_row(stt="1", status="priced", unit_price="380000", extended="237120000",
             unit="m", qty_raw="624", qty=624.0, error_reason=None) -> ExportRow:
    return ExportRow(
        stt=stt,
        section="II > II.1",
        description_vi="Khoan thăm dò địa chất đường",
        unit=unit,
        quantity_raw=qty_raw,
        quantity=qty,
        master_code="KS-006" if status == "priced" else None,
        master_desc="Khoan đường" if status == "priced" else None,
        unit_price_str=unit_price if status == "priced" else None,
        extended_amount_str=extended if status == "priced" else None,
        confidence=0.9 if status == "priced" else None,
        page=1,
        status=status,
        error_reason=error_reason,
        formula_ref="DT_KS_006",
        coeff_applied=[],
        unit_rule_ref=None,
        evidence="test",
        overrides=[],
    )


class TestExcelExporter:
    def test_generates_bytes(self):
        rows = [make_row()]
        result = generate_excel(rows, "test-job-1")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_valid_xlsx_magic_bytes(self):
        rows = [make_row()]
        result = generate_excel(rows, "test-job-1")
        # xlsx is a zip file starting with PK
        assert result[:2] == b"PK"

    def test_three_sheets_present(self):
        from openpyxl import load_workbook
        import io
        rows = [make_row()]
        result = generate_excel(rows, "test-job-1")
        wb = load_workbook(io.BytesIO(result))
        assert "Dự thầu" in wb.sheetnames
        assert "Mapping-Audit" in wb.sheetnames
        assert "Unresolved" in wb.sheetnames

    def test_draft_label_when_unresolved(self):
        from openpyxl import load_workbook
        import io
        rows = [make_row(status="unresolved", unit_price=None, extended=None,
                         error_reason="No master match")]
        result = generate_excel(rows, "test-job-2")
        wb = load_workbook(io.BytesIO(result))
        ws = wb["Dự thầu"]
        cell_a1 = ws["A1"].value or ""
        assert "DRAFT" in str(cell_a1).upper() or "CHƯA" in str(cell_a1).upper(), (
            f"DRAFT warning expected in A1, got: '{cell_a1}'"
        )

    def test_no_grand_total_when_partial(self):
        from openpyxl import load_workbook
        import io
        rows = [
            make_row(stt="1", status="priced"),
            make_row(stt="2", status="unresolved", unit_price=None, extended=None,
                     error_reason="No master match"),
        ]
        result = generate_excel(rows, "test-job-3")
        wb = load_workbook(io.BytesIO(result))
        ws = wb["Dự thầu"]
        # Should not have a numeric grand total in column F
        col_f_values = [ws.cell(row=r, column=6).value for r in range(1, ws.max_row + 1)]
        numeric_totals = [v for v in col_f_values if isinstance(v, (int, float)) and v > 0]
        # Only one numeric value (the priced row's extended amount); no grand total
        assert len(numeric_totals) <= 1, (
            f"Should not have grand total when partial; found {numeric_totals}"
        )

    def test_unresolved_sheet_populated(self):
        from openpyxl import load_workbook
        import io
        rows = [
            make_row(stt="1", status="priced"),
            make_row(stt="2", status="unresolved", unit_price=None, extended=None,
                     error_reason="No master match"),
        ]
        result = generate_excel(rows, "test-job-4")
        wb = load_workbook(io.BytesIO(result))
        ws = wb["Unresolved"]
        # Should have header + at least 1 data row
        assert ws.max_row >= 2

    def test_audit_sheet_row_count(self):
        from openpyxl import load_workbook
        import io
        rows = [make_row(stt=str(i)) for i in range(1, 6)]
        result = generate_excel(rows, "test-job-5")
        wb = load_workbook(io.BytesIO(result))
        ws = wb["Mapping-Audit"]
        # 1 header + 5 data rows
        assert ws.max_row == 6

    def test_full_priced_has_total(self):
        from openpyxl import load_workbook
        import io
        rows = [
            make_row(stt="1", extended="237120000"),
            make_row(stt="2", extended="45600000"),
        ]
        result = generate_excel(rows, "test-job-6")
        wb = load_workbook(io.BytesIO(result))
        ws = wb["Dự thầu"]
        # Should have TỔNG CỘNG row
        texts = [str(ws.cell(row=r, column=2).value or "") for r in range(1, ws.max_row + 1)]
        assert any("TỔNG" in t for t in texts), "Grand total row expected when all rows priced"
