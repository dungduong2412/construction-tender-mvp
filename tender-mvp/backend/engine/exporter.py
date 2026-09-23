"""
Excel Exporter
==============
Generates a .xlsx workbook with:
  Sheet 1: Dự thầu    – editable bid worksheet (style resembles reference workbook)
  Sheet 2: Audit/Mapping – row-by-row traceability (master ID, evidence, confidence)
  Sheet 3: Unresolved  – rows with no price (prominently labelled DRAFT)

Rules:
- Partial totals are never displayed as a complete bid total
- Unresolved rows are highlighted in orange
- The workbook header always carries the DRAFT label if is_complete = False
- No monetary amounts are fabricated; empty cells are left blank
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from ..models.domain import PriceLine, PriceLineStatus, PricingSheet

_ORANGE_FILL = PatternFill("solid", fgColor="FFAA33")
_YELLOW_FILL = PatternFill("solid", fgColor="FFF3CD")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_SECTION_FILL = PatternFill("solid", fgColor="BDD7EE")
_THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
_HEADER_FONT = Font(name="Times New Roman", bold=True, color="FFFFFF", size=11)
_BODY_FONT = Font(name="Times New Roman", size=10)
_TITLE_FONT = Font(name="Times New Roman", bold=True, size=13)
_DRAFT_FONT = Font(name="Times New Roman", bold=True, color="CC0000", size=12)


def _fmt_vnd(val: Optional[int]) -> str:
    if val is None:
        return ""
    return f"{val:,}"


def _fmt_qty(val) -> str:
    if val is None:
        return ""
    return str(val).rstrip("0").rstrip(".")


def export_xlsx(sheet: PricingSheet, output_dir: str = "/tmp") -> str:
    """
    Write the pricing sheet to a .xlsx file and return the file path.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    _write_du_thau(wb, sheet)
    _write_audit(wb, sheet)
    _write_unresolved(wb, sheet)

    out_path = Path(output_dir) / f"du_thau_{sheet.job_id[:8]}.xlsx"
    wb.save(str(out_path))
    return str(out_path)


# ---------------------------------------------------------------------------
# Sheet 1 – Dự thầu
# ---------------------------------------------------------------------------

def _write_du_thau(wb: openpyxl.Workbook, sheet: PricingSheet) -> None:
    ws = wb.create_sheet("Dự thầu")
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 22

    row = 1

    # Title
    ws.merge_cells(f"A{row}:F{row}")
    title_cell = ws[f"A{row}"]
    title_cell.value = "BẢNG DỰ TOÁN CHI PHÍ KHẢO SÁT XÂY DỰNG"
    title_cell.font = _TITLE_FONT
    title_cell.alignment = Alignment(horizontal="center")
    row += 1

    # Draft warning if incomplete
    if not sheet.is_complete:
        ws.merge_cells(f"A{row}:F{row}")
        warn = ws[f"A{row}"]
        warn.value = (
            "⚠ DRAFT – Bảng giá CHƯA HOÀN CHỈNH. "
            f"{sheet.unresolved_count} hạng mục chưa có đơn giá. "
            "Không sử dụng tổng cộng dưới đây làm giá dự thầu chính thức."
        )
        warn.font = _DRAFT_FONT
        warn.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.row_dimensions[row].height = 30
        row += 1

    row += 1

    # Column headers
    headers = ["TT", "Nội dung công việc", "Đơn vị", "Khối lượng", "Đơn giá (đồng)", "Thành tiền (đồng)"]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border = _THIN_BORDER
    ws.row_dimensions[row].height = 28
    row += 1

    # Data rows
    for line in sheet.lines:
        is_heading = line.status == PriceLineStatus.HEADING
        is_unresolved = line.status == PriceLineStatus.UNRESOLVED

        fill = None
        if is_unresolved:
            fill = _ORANGE_FILL
        elif is_heading:
            fill = _SECTION_FILL

        # Determine display number (TT)
        tt_val = ""
        if is_heading:
            tt_val = line.source_section or ""

        cells_data = [
            (tt_val, Alignment(horizontal="center")),
            (line.description_vi, Alignment(horizontal="left", wrap_text=True)),
            (line.unit_pdf or "", Alignment(horizontal="center")),
            (_fmt_qty(line.quantity) if not is_heading else "", Alignment(horizontal="right")),
            (_fmt_vnd(line.unit_price) if not is_heading else "", Alignment(horizontal="right")),
            (
                _fmt_vnd(line.extended_amount) if (not is_heading and line.extended_amount is not None) else "",
                Alignment(horizontal="right"),
            ),
        ]

        for col_idx, (val, align) in enumerate(cells_data, start=1):
            c = ws.cell(row=row, column=col_idx, value=val)
            c.font = Font(name="Times New Roman", bold=is_heading, size=10)
            c.alignment = align
            c.border = _THIN_BORDER
            if fill:
                c.fill = fill

        ws.row_dimensions[row].height = 18 if not is_heading else 22
        row += 1

    # Subtotal row
    row += 1
    subtotal_label = ws.cell(row=row, column=5, value="Cộng chi phí trực tiếp:")
    subtotal_label.font = Font(name="Times New Roman", bold=True, size=11)
    subtotal_label.alignment = Alignment(horizontal="right")

    subtotal_val = ws.cell(row=row, column=6, value=_fmt_vnd(sheet.subtotal_priced_vnd))
    subtotal_val.font = Font(name="Times New Roman", bold=True, size=11)
    subtotal_val.alignment = Alignment(horizontal="right")
    subtotal_val.border = _THIN_BORDER
    row += 1

    if not sheet.is_complete:
        ws.merge_cells(f"A{row}:F{row}")
        note = ws[f"A{row}"]
        note.value = (
            "* Tổng cộng trên chỉ bao gồm các hạng mục đã có đơn giá. "
            "Các hạng mục tô màu cam chưa được định giá và PHẢI được bổ sung trước khi nộp thầu."
        )
        note.font = Font(name="Times New Roman", italic=True, size=9, color="CC0000")
        note.alignment = Alignment(horizontal="left", wrap_text=True)
        ws.row_dimensions[row].height = 28

    # Footer metadata
    row += 2
    ws.cell(row=row, column=1, value=f"Phiên bản dữ liệu định mức: {sheet.master_data_version}").font = Font(size=8, italic=True)
    row += 1
    ws.cell(row=row, column=1, value=f"Job ID: {sheet.job_id}").font = Font(size=8, italic=True)


# ---------------------------------------------------------------------------
# Sheet 2 – Audit / Mapping
# ---------------------------------------------------------------------------

def _write_audit(wb: openpyxl.Workbook, sheet: PricingSheet) -> None:
    ws = wb.create_sheet("Audit_Mapping")
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 12
    ws.column_dimensions["H"].width = 60

    headers = [
        "Row ID", "Mô tả (PDF)", "Đơn vị PDF", "Khối lượng",
        "Master ID", "Master Code", "Confidence", "Evidence",
    ]
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col_idx, value=h)
        c.font = _HEADER_FONT
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.border = _THIN_BORDER

    for r_idx, line in enumerate(sheet.lines, start=2):
        vals = [
            line.row_id,
            line.description_vi,
            line.unit_pdf or "",
            _fmt_qty(line.quantity),
            line.master_id or "",
            line.master_code or "",
            f"{line.confidence:.1%}" if line.confidence else "",
            line.evidence or "",
        ]
        for col_idx, val in enumerate(vals, start=1):
            c = ws.cell(row=r_idx, column=col_idx, value=val)
            c.font = _BODY_FONT
            c.border = _THIN_BORDER
            c.alignment = Alignment(horizontal="left", wrap_text=True)
            if line.status == PriceLineStatus.UNRESOLVED:
                c.fill = _ORANGE_FILL


# ---------------------------------------------------------------------------
# Sheet 3 – Unresolved
# ---------------------------------------------------------------------------

def _write_unresolved(wb: openpyxl.Workbook, sheet: PricingSheet) -> None:
    ws = wb.create_sheet("Unresolved")
    unresolved = [l for l in sheet.lines if l.status == PriceLineStatus.UNRESOLVED]

    if not unresolved:
        ws.cell(row=1, column=1, value="Tất cả hạng mục đã được định giá.")
        return

    ws.merge_cells("A1:F1")
    warn = ws["A1"]
    warn.value = f"UNRESOLVED – {len(unresolved)} hạng mục chưa có đơn giá. Cần kiểm tra thủ công trước khi nộp thầu."
    warn.font = _DRAFT_FONT
    warn.fill = _ORANGE_FILL
    warn.alignment = Alignment(horizontal="center")

    headers = ["Row ID", "Phần", "Mô tả (PDF)", "Đơn vị", "Khối lượng", "Lý do chưa định giá"]
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=2, column=col_idx, value=h)
        c.font = Font(name="Times New Roman", bold=True, size=10)
        c.border = _THIN_BORDER

    for r_idx, line in enumerate(unresolved, start=3):
        vals = [
            line.row_id,
            line.source_section,
            line.description_vi,
            line.unit_pdf or "",
            _fmt_qty(line.quantity),
            line.exception_reason or "",
        ]
        for col_idx, val in enumerate(vals, start=1):
            c = ws.cell(row=r_idx, column=col_idx, value=val)
            c.font = _BODY_FONT
            c.fill = _YELLOW_FILL
            c.border = _THIN_BORDER
            c.alignment = Alignment(wrap_text=True)
