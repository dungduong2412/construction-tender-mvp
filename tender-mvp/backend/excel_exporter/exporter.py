"""
Excel Exporter — generates .xlsx bid worksheet using openpyxl.

Sheets:
  1. "Dự thầu"       — main bid sheet (DRAFT watermark if any unresolved rows)
  2. "Mapping-Audit"  — full mapping traceability
  3. "Unresolved"    — rows with unresolved or error status

NEVER sums partial amounts into a grand total when any rows are unresolved.
"""
import io
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


@dataclass
class ExportRow:
    stt: str
    section: str
    description_vi: str
    unit: str
    quantity_raw: str
    quantity: Optional[float]
    master_code: Optional[str]
    master_desc: Optional[str]
    unit_price_str: Optional[str]
    extended_amount_str: Optional[str]
    confidence: Optional[float]
    page: int
    status: str           # "priced" | "unresolved" | "error"
    error_reason: Optional[str]
    formula_ref: Optional[str]
    coeff_applied: list[str]
    unit_rule_ref: Optional[str]
    evidence: Optional[str]
    overrides: list[dict]


def generate_excel(rows: list[ExportRow], job_id: str) -> bytes:
    wb = Workbook()
    priced_statuses = {"mapped_and_priced"}
    unresolved_statuses = {
        "mapped_price_unavailable",
        "mapping_ambiguous",
        "mapping_unresolved",
        "invalid_quantity_or_unit",
    }
    is_partial = any(r.status not in priced_statuses and r.status not in {"non_billable_heading", "non_billable_metadata"} for r in rows)

    _build_du_thau(wb, rows, is_partial)
    _build_audit(wb, rows)
    _build_unresolved(wb, rows)
    # wb.active is set by first sheet creation

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sheet 1 — Dự thầu
# ---------------------------------------------------------------------------

def _build_du_thau(wb: Workbook, rows: list[ExportRow], is_partial: bool) -> None:
    ws = wb.active
    ws.title = "Dự thầu"

    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # DRAFT watermark row
    if is_partial:
        ws.append(["⚠ DRAFT — CÒN CÁC KHOẢN CHƯA ĐỊNH GIÁ — KHÔNG DÙNG LÀM GIÁ DỰ THẦU CHÍNH THỨC"])
        ws["A1"].font = Font(bold=True, color="FF0000", size=12)
        ws.merge_cells("A1:F1")
        ws.row_dimensions[1].height = 24

    headers = ["STT", "NỘI DUNG CÔNG VIỆC", "ĐVT", "KHỐI LƯỢNG", "ĐƠN GIÁ (đ)", "THÀNH TIỀN (đ)"]
    header_row = ws.max_row + 1
    ws.append(headers)
    for col_idx, _ in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    priced_rows = []

    for row in rows:
        if row.status == "mapped_and_priced" and row.unit_price_str and row.extended_amount_str:
            up = _parse_decimal(row.unit_price_str)
            ea = _parse_decimal(row.extended_amount_str)
            priced_rows.append(ea)
        else:
            up = None
            ea = None

        ws.append([
            row.stt,
            row.description_vi,
            row.unit,
            row.quantity_raw,
            float(up) if up is not None else None,
            float(ea) if ea is not None else None,
        ])

        data_row = ws.max_row
        if row.status not in {"mapped_and_priced", "non_billable_heading", "non_billable_metadata"}:
            err_fill = PatternFill("solid", fgColor="FFCCCC")
            for col in range(1, 7):
                ws.cell(row=data_row, column=col).fill = err_fill
            ws.cell(row=data_row, column=6).value = row.error_reason or "UNRESOLVED"

    # Grand total — only when all rows are priced
    if not is_partial and priced_rows:
        total = sum(priced_rows, Decimal("0"))
        total_row = ["", "TỔNG CỘNG", "", "", "", float(total)]
        ws.append(total_row)
        total_r = ws.max_row
        for col in range(1, 7):
            ws.cell(row=total_r, column=col).font = Font(bold=True)
    elif is_partial:
        ws.append(["", "⚠ TỔNG CỘNG CHƯA ĐẦY ĐỦ — XEM SHEET UNRESOLVED", "", "", "", ""])
        ws.cell(row=ws.max_row, column=2).font = Font(bold=True, color="FF0000")

    # Column widths
    col_widths = [8, 60, 10, 14, 16, 16]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Number format for price columns
    for row_cells in ws.iter_rows(min_row=header_row + 1, min_col=5, max_col=6):
        for cell in row_cells:
            if isinstance(cell.value, (int, float)):
                cell.number_format = '#,##0'


# ---------------------------------------------------------------------------
# Sheet 2 — Mapping/Audit
# ---------------------------------------------------------------------------

def _build_audit(wb: Workbook, rows: list[ExportRow]) -> None:
    ws = wb.create_sheet("Mapping-Audit")
    header_font = Font(bold=True)
    headers = [
        "row_id", "STT", "Mô tả PDF", "Đơn vị PDF", "Klg (raw)",
        "master_code", "Mô tả master", "Trạng thái", "Độ tin cậy",
        "Bằng chứng", "formula_ref", "coeff_applied", "unit_rule_ref",
        "Ghi đè", "Trang PDF",
    ]
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        ws.cell(row=1, column=col_idx).font = header_font

    for r in rows:
        ws.append([
            _derive_row_id(r),
            r.stt,
            r.description_vi,
            r.unit,
            r.quantity_raw,
            r.master_code or "",
            r.master_desc or "",
            r.status,
            r.confidence if r.confidence is not None else "",
            r.evidence or "",
            r.formula_ref or "",
            ", ".join(r.coeff_applied),
            r.unit_rule_ref or "",
            _format_overrides(r.overrides),
            r.page,
        ])

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["C"].width = 50
    ws.column_dimensions["J"].width = 40


# ---------------------------------------------------------------------------
# Sheet 3 — Unresolved
# ---------------------------------------------------------------------------

def _build_unresolved(wb: Workbook, rows: list[ExportRow]) -> None:
    ws = wb.create_sheet("Unresolved")
    header_font = Font(bold=True)
    warn_fill = PatternFill("solid", fgColor="FFCCCC")

    headers = ["STT", "Mô tả", "ĐVT", "Khối lượng", "Lý do", "Trang PDF"]
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        ws.cell(row=1, column=col_idx).font = header_font

    unresolved = [r for r in rows if r.status in ("mapped_price_unavailable", "mapping_ambiguous", "mapping_unresolved", "invalid_quantity_or_unit")]
    if not unresolved:
        ws.append(["(Không có khoản nào chưa định giá)"])
        return

    for r in unresolved:
        row_num = ws.max_row + 1
        ws.append([r.stt, r.description_vi, r.unit, r.quantity_raw, r.error_reason or "", r.page])
        for col in range(1, 7):
            ws.cell(row=row_num, column=col).fill = warn_fill

    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["E"].width = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_decimal(s: str) -> Optional[Decimal]:
    try:
        return Decimal(s)
    except Exception:
        return None


def _derive_row_id(r: ExportRow) -> str:
    return f"row-{r.stt}-p{r.page}"


def _format_overrides(overrides: list[dict]) -> str:
    if not overrides:
        return ""
    parts = [f"{o.get('field')}:{o.get('old_value')}→{o.get('new_value')}" for o in overrides]
    return "; ".join(parts)
