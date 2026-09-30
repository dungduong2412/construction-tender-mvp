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
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
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


def generate_internal_workbook(snapshot: dict[str, Any]) -> bytes:
    """Create the reviewable internal workbook from one immutable snapshot."""
    wb = Workbook()
    wb.remove(wb.active)
    _internal_summary(wb, snapshot)
    _internal_boq(wb, snapshot)
    _internal_resources(wb, snapshot)
    _internal_branch(wb, snapshot, "tender", "Tender Calculation")
    _internal_branch(wb, snapshot, "approval", "Approval Calculation")
    _internal_formula_sources(wb, snapshot)
    _internal_review_history(wb, snapshot)
    _internal_unresolved(wb, snapshot)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_estimate_schedule(snapshot: dict[str, Any], view: str) -> bytes:
    """Export the estimator-facing schedule for either approval or tender review.

    This is deliberately available while incomplete. Missing authoritative values
    remain text markers and the workbook carries a visible DRAFT / INCOMPLETE band.
    """
    if view not in {"approval", "tender"}:
        raise ValueError("view must be approval or tender")
    branch = snapshot.get(view) or {}
    incomplete = branch.get("status") != "COMPLETE"
    wb = Workbook()
    ws = wb.active
    ws.title = "Phê duyệt nội bộ" if view == "approval" else "Dự thầu"
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A6"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    widths = [7, 14, 58, 12, 14, 16, 16, 16, 18, 20]
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.merge_cells("A1:J1")
    ws["A1"] = "BẢN KÊ PHÊ DUYỆT NỘI BỘ" if view == "approval" else "BẢN KÊ DỰ THẦU"
    ws["A1"].font = Font(name="Arial", bold=True, size=15)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A2:J2")
    ws["A2"] = snapshot.get("job", {}).get("filename") or "Bảng tiên lượng"
    ws["A2"].alignment = Alignment(horizontal="center")
    if incomplete:
        ws.merge_cells("A3:J3")
        ws["A3"] = "DRAFT / INCOMPLETE — CÒN HẠNG MỤC CHƯA ĐỦ CĂN CỨ"
        ws["A3"].font = Font(name="Arial", bold=True, color="9C2F16")
        ws["A3"].fill = PatternFill("solid", fgColor="FDE7D8")
        ws["A3"].alignment = Alignment(horizontal="center")
    headers = ["STT", "Mã số", "Mô tả công việc", "Đơn vị tính", "Khối lượng",
               "Vật liệu", "Nhân công", "Máy", "Đơn giá", "Thành tiền"]
    _headers(ws, 5, headers)
    thin = Side(style="thin", color="D6D3D1")
    row_index = 6
    for item in snapshot.get("rows", []):
        if item.get("row_type") != "line_item":
            continue
        detail = item.get("approval_detail") or {}
        approval_resolved = detail.get("calculation_status") == "resolved"
        material = _number(detail.get("direct_material_unit")) if view == "approval" and approval_resolved else None
        labour = _number(detail.get("direct_labour_unit")) if view == "approval" and approval_resolved else None
        machine = _number(detail.get("direct_machine_unit")) if view == "approval" and approval_resolved else None
        price_available = bool(item.get("pricing_available")) if view == "tender" else approval_resolved
        unit_price = _number(item.get("tender_unit_price")) if view == "tender" and price_available else None
        amount = _number(item.get("tender_amount")) if view == "tender" and price_available else None
        if view == "approval" and approval_resolved:
            unit_price = (material or 0) + (labour or 0) + (machine or 0)
            qty = _number(item.get("quantity"))
            amount = unit_price * qty if qty is not None else None
        values = [item.get("row_number"), item.get("mapped_work_item"), item.get("description"),
                  item.get("unit"), _number(item.get("quantity")), material, labour, machine,
                  unit_price if price_available else "Chưa có đơn giá / Not available",
                  amount if amount is not None else "Chưa có đơn giá / Not available"]
        for col, value in enumerate(values, 1):
            cell = ws.cell(row_index, col, value)
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(horizontal="left" if col == 3 else "right" if col >= 5 else "center",
                                       vertical="top", wrap_text=True)
            cell.border = Border(bottom=thin)
            if col >= 5 and isinstance(value, (int, float)):
                cell.number_format = '#,##0.####' if col == 5 else '#,##0'
        if not price_available:
            ws.cell(row_index, 9).fill = PatternFill("solid", fgColor="FFF1D6")
            ws.cell(row_index, 10).fill = PatternFill("solid", fgColor="FFF1D6")
        row_index += 1
    ws.cell(row_index, 3, "TỔNG HỢP CHI PHÍ")
    ws.cell(row_index, 3).font = Font(name="Arial", bold=True)
    ws.cell(row_index, 10, _number(branch.get("official_total")) if branch.get("official_total") is not None else "DRAFT / INCOMPLETE")
    ws.cell(row_index, 10).font = Font(name="Arial", bold=True, color="9C2F16" if incomplete else "111827")
    row_index += 1
    if view == "approval":
        labels = {"T": "Cộng chi phí trực tiếp", "C": "Chi phí chung", "TT": "Chi phí gián tiếp khác",
                  "GT": "Cộng chi phí gián tiếp", "TL": "Thu nhập chịu thuế tính trước",
                  "Cpa": "Lập phương án kỹ thuật khảo sát", "Cbc": "Lập báo cáo kết quả khảo sát",
                  "Cpvks": "Cộng chi phí phục vụ khảo sát", "G": "Chi phí trước thuế",
                  "VAT": "Thuế giá trị gia tăng (VAT)", "Gks": "Chi phí sau thuế",
                  "LT": "Nhà tạm và điều hành", "Gdp": "Chi phí dự phòng (GDP)", "FINAL": "TỔNG CỘNG"}
        for category, components in (branch.get("category_components") or {}).items():
            ws.cell(row_index, 3, f"Nhóm: {category}")
            ws.cell(row_index, 3).font = Font(name="Arial", bold=True, italic=True)
            row_index += 1
            for key, label in labels.items():
                if key not in components:
                    continue
                ws.cell(row_index, 2, key)
                ws.cell(row_index, 3, label)
                ws.cell(row_index, 10, _number(components.get(key)))
                ws.cell(row_index, 10).number_format = '#,##0'
                for col in range(1, 11):
                    ws.cell(row_index, col).fill = PatternFill("solid", fgColor="F7F4EE")
                row_index += 1
    ws.auto_filter.ref = f"A5:J{max(5, row_index - 1)}"
    ws.print_area = f"A1:J{row_index - 1}"
    ws.oddFooter.left.text = f"Snapshot: {snapshot.get('snapshot_id', '')}"
    ws.oddFooter.right.text = "&P / &N"
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_submission_workbook(snapshot: dict[str, Any]) -> bytes:
    """Create the submission-only workbook using the audited Dự thầu contract."""
    policy = snapshot.get("export_policy") or {}
    if not policy.get("final_submission_allowed"):
        reasons = "; ".join(policy.get("final_block_reasons") or ["mandatory rows unresolved"])
        raise ValueError(f"Final submission is blocked: {reasons}")

    wb = Workbook()
    ws = wb.active
    ws.title = "Dự thầu"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=.236, right=.236, top=.551, bottom=.315, header=.512, footer=.315)
    ws.oddFooter.center.text = "&P"
    widths = {"A": 6.49, "B": 12.16, "C": 89.49, "D": 9.32, "E": 11.65,
              "F": 12.65, "G": 15.65, "H": 12.65, "I": 17.16, "J": 18.82, "K": 14.16, "L": 13.0}
    for column, width in widths.items():
        ws.column_dimensions[column].width = width
    for column in ["F", "G", "H", "K"]:
        ws.column_dimensions[column].hidden = True

    ws.merge_cells("A1:L1")
    ws.merge_cells("A2:L2")
    ws.merge_cells("A3:L3")
    ws["A1"] = "BẢNG DỰ TOÁN DỰ THẦU PHẦN KHẢO SÁT"
    ws["A2"] = f"Hồ sơ: {snapshot.get('job', {}).get('filename', '')}"
    ws["A3"] = f"Calculation snapshot: {snapshot.get('snapshot_id')}"
    for cell in (ws["A1"], ws["A2"], ws["A3"]):
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.font = Font(name="Times New Roman", bold=True, size=14 if cell.row == 1 else 11)

    headers = ["STT", "Mã số", "Mô tả công việc", "Đơn vị tính", "Khối lượng", "", "", "", "Đơn giá", "Thành tiền", "", ""]
    for col, value in enumerate(headers, 1):
        cell = ws.cell(5, col, value)
        cell.font = Font(name="Times New Roman", bold=True, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.fill = PatternFill("solid", fgColor="D9E1F2")
    ws.row_dimensions[5].height = 28.5

    thin = Side(style="thin", color="000000")
    row_index = 6
    last_section = None
    data_rows: list[int] = []
    for item in snapshot.get("rows", []):
        if item.get("row_type") != "line_item":
            continue
        section = item.get("section") or ""
        if section != last_section:
            ws.merge_cells(start_row=row_index, start_column=1, end_row=row_index, end_column=12)
            cell = ws.cell(row_index, 1, section)
            cell.font = Font(name="Times New Roman", bold=True, size=10)
            cell.fill = PatternFill("solid", fgColor="E7E6E6")
            row_index += 1
            last_section = section
        values = [
            item.get("row_number"), item.get("mapped_work_item"), item.get("description"), item.get("unit"),
            _number(item.get("quantity")), None, None, None, _number(item.get("tender_unit_price")), None, None, None,
        ]
        for col, value in enumerate(values, 1):
            cell = ws.cell(row_index, col, value)
            cell.font = Font(name="Times New Roman", size=10)
            cell.alignment = Alignment(horizontal="left" if col == 3 else "center", vertical="center", wrap_text=True)
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.cell(row_index, 10, f"=ROUND(E{row_index}*I{row_index},0)")
        ws.cell(row_index, 5).number_format = '#,##0.####'
        ws.cell(row_index, 9).number_format = '#,##0'
        ws.cell(row_index, 10).number_format = '#,##0'
        ws.row_dimensions[row_index].height = 30
        data_rows.append(row_index)
        row_index += 1
    total_row = row_index
    ws.cell(total_row, 3, "TỔNG CỘNG")
    ws.cell(total_row, 10, f"=ROUND(SUM(J{data_rows[0]}:J{data_rows[-1]}),0)" if data_rows else 0)
    for col in range(1, 13):
        ws.cell(total_row, col).font = Font(name="Times New Roman", bold=True, size=10)
        ws.cell(total_row, col).border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.cell(total_row, 10).number_format = '#,##0'
    ws.freeze_panes = "A6"
    ws.auto_filter.ref = f"A5:J{max(total_row - 1, 5)}"
    ws.print_area = f"A1:L{total_row}"
    ws.print_title_rows = "1:5"
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _number(value: Any) -> float | None:
    parsed = _parse_decimal(str(value)) if value not in (None, "") else None
    return float(parsed) if parsed is not None else None


def _number_or_na(value: Any) -> float | str:
    parsed = _number(value)
    return parsed if parsed is not None else "Not available"


def _title(ws, title: str, subtitle: str = "") -> None:
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=15, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="1F4E78")
    if subtitle:
        ws.append([subtitle])
        ws["A2"].font = Font(italic=True, color="666666")


def _headers(ws, row: int, values: list[str]) -> None:
    for col, value in enumerate(values, 1):
        cell = ws.cell(row, col, value)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4472C4")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = f"A{row + 1}"
    ws.auto_filter.ref = f"A{row}:{get_column_letter(len(values))}{row}"


def _internal_summary(wb: Workbook, snapshot: dict[str, Any]) -> None:
    ws = wb.create_sheet("Summary")
    incomplete = not bool(snapshot.get("export_policy", {}).get("final_submission_allowed"))
    _title(ws, "DRAFT / INCOMPLETE — INTERNAL CALCULATION SNAPSHOT" if incomplete else "INTERNAL CALCULATION SNAPSHOT",
           "Partial subtotals exclude unavailable children and are not official totals." if incomplete else "Complete immutable calculation snapshot.")
    pairs = [
        ("Snapshot ID", snapshot.get("snapshot_id")), ("Immutable", snapshot.get("immutable")),
        ("Project file", snapshot.get("job", {}).get("filename")), ("Extraction status", snapshot.get("job", {}).get("status")),
        ("Source rows", snapshot.get("counts", {}).get("source_rows")), ("Billable", snapshot.get("counts", {}).get("billable")),
        ("Structural / non-billable", snapshot.get("counts", {}).get("non_billable")),
        ("Mapped", snapshot.get("counts", {}).get("mapped")), ("Priced", snapshot.get("counts", {}).get("priced")),
        ("Billable price unavailable", snapshot.get("counts", {}).get("pricing_not_available")),
        ("Mandatory unresolved", snapshot.get("counts", {}).get("mandatory_unresolved")),
        ("Approval evidence unresolved", snapshot.get("counts", {}).get("approval_evidence_unresolved")),
        ("Tender partial", _number_or_na(snapshot.get("tender", {}).get("partial_subtotal"))),
        ("Tender official", _number_or_na(snapshot.get("tender", {}).get("official_total"))),
        ("Approval partial", _number_or_na(snapshot.get("approval", {}).get("partial_subtotal"))),
        ("Approval official", _number_or_na(snapshot.get("approval", {}).get("official_total"))),
        ("Final export allowed", snapshot.get("export_policy", {}).get("final_submission_allowed")),
        ("Final block reasons", "; ".join(snapshot.get("export_policy", {}).get("final_block_reasons") or [])),
    ]
    for key, value in pairs:
        ws.append([key, value])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 82
    for cell in ws["A"]:
        cell.font = Font(bold=True)
    for row in ws.iter_rows(min_row=3, min_col=2, max_col=2):
        if isinstance(row[0].value, (int, float)):
            row[0].number_format = '#,##0.00'


def _internal_boq(wb: Workbook, snapshot: dict[str, Any]) -> None:
    ws = wb.create_sheet("Original BOQ & Corrections")
    _title(ws, "ORIGINAL BOQ, CORRECTIONS AND PROVENANCE", snapshot.get("snapshot_id", ""))
    headers = ["Order", "Row", "Type", "Section", "Description", "Unit", "Quantity raw", "Quantity", "Page", "Region", "Source origin", "Source provenance", "Azure polygon", "Mapped item", "Mapped by", "Mapping status", "Pricing availability", "Price display", "Tender unit", "Tender amount", "Effective date", "Expiry date", "Price source", "Price updated by", "Price updated at", "Mapping updated by", "Mapping updated at", "Freshness", "Formula", "Conflicts"]
    _headers(ws, 3, headers)
    for item in snapshot.get("rows", []):
        billable = item.get("row_type") == "line_item"
        price_label = item.get("price_display") or (_number_or_na(item.get("tender_unit_price")) if billable else "Not applicable")
        tender_unit = _number(item.get("tender_unit_price")) if billable and item.get("tender_unit_price") is not None else price_label
        amount_label = _number_or_na(item.get("tender_amount")) if billable else "Not applicable"
        ws.append([item.get("doc_order"), item.get("row_number"), item.get("row_type"), item.get("section"), item.get("description"), item.get("unit"), item.get("quantity_raw"), _number(item.get("quantity")), item.get("source_page"), item.get("source_region"), item.get("source_origin"), item.get("source_provenance"), item.get("azure_polygon_available"), item.get("mapped_work_item"), item.get("mapped_by"), item.get("mapping_status"), item.get("pricing_availability") if billable else "not_applicable", price_label, tender_unit, amount_label, item.get("price_effective_date"), item.get("price_expiry_date"), item.get("price_source_reference") or item.get("price_source"), item.get("price_last_updated_by"), item.get("price_last_updated_at"), item.get("mapping_last_updated_by"), item.get("mapping_last_updated_at"), item.get("price_freshness"), item.get("tender_formula_ref"), "; ".join(item.get("evidence_conflicts") or [])])
    ws.column_dimensions["D"].width = 28; ws.column_dimensions["E"].width = 62; ws.column_dimensions["J"].width = 30; ws.column_dimensions["L"].width = 65; ws.column_dimensions["AD"].width = 45


def _internal_resources(wb: Workbook, snapshot: dict[str, Any]) -> None:
    ws = wb.create_sheet("Detailed Resource Costs")
    _title(ws, "DETAILED RESOURCE COSTS", "Only source-backed CalculationEngineV2 traces are included.")
    headers = ["Row", "Work item", "Type", "Resource code", "Description", "Quantity/norm", "Coefficient", "Unit price", "Line total", "Classification", "Source sheet", "Cell", "Parity", "Missing dependency"]
    _headers(ws, 3, headers)
    for item in snapshot.get("rows", []):
        detail = item.get("approval_detail") or {}
        missing = "; ".join(detail.get("missing_dependencies") or [])
        for trace in detail.get("resource_trace") or []:
            resource_available = trace.get("classification") != "EXTERNAL_UNRESOLVED"
            ws.append([item.get("row_number"), item.get("mapped_work_item"), trace.get("resource_type"), trace.get("code"), trace.get("description"), _number(trace.get("quantity")), _number(trace.get("coefficient")), _number_or_na(trace.get("unit_price")) if resource_available else "Not available", _number_or_na(trace.get("line_total")) if resource_available else "Not available", trace.get("classification"), trace.get("source_sheet"), trace.get("sheet_ref"), _number(trace.get("line_parity")), missing])
    ws.column_dimensions["E"].width = 48; ws.column_dimensions["N"].width = 40


def _internal_branch(wb: Workbook, snapshot: dict[str, Any], branch: str, sheet_name: str) -> None:
    data = snapshot.get(branch) or {}
    ws = wb.create_sheet(sheet_name)
    _title(ws, sheet_name.upper(), f"Method: {data.get('method', '')}; formula version {snapshot.get('formula_version', {}).get('version_id', '')}")
    for key in ["status", "partial_subtotal", "official_total"]:
        ws.append([key, _number_or_na(data.get(key)) if key.endswith("total") else data.get(key)])
    ws.append([])
    ws.append(["Level", "Node", "Status", "Partial subtotal", "Official total", "Unresolved descendants"])
    header_row = ws.max_row
    _headers(ws, header_row, ["Level", "Node", "Status", "Partial subtotal", "Official total", "Unresolved descendants"])
    hierarchy = data.get("hierarchy")
    if hierarchy:
        def add_node(node):
            ws.append([node.get("depth"), node.get("name"), node.get("status"),
                       _number_or_na(node.get("partial_subtotal")), _number_or_na(node.get("official_total")),
                       node.get("unresolved_descendants")])
            for child in node.get("children") or []:
                add_node(child)
        add_node(hierarchy)
    elif branch == "tender":
        for section, amount in (data.get("section_subtotals") or {}).items():
            ws.append([1, section, data.get("status"), _number_or_na(amount), _number_or_na(amount), 0])
    else:
        for group, components in (data.get("group_components") or {}).items():
            for component, amount in components.items():
                ws.append([1, f"{group}: {component}", data.get("status"), _number_or_na(amount), _number_or_na(amount), 0])
    ws.column_dimensions["A"].width = 10; ws.column_dimensions["B"].width = 48; ws.column_dimensions["C"].width = 18


def _internal_formula_sources(wb: Workbook, snapshot: dict[str, Any]) -> None:
    ws = wb.create_sheet("Formula & Sources")
    _title(ws, "FORMULA VERSION AND SOURCE REFERENCES", snapshot.get("snapshot_id", ""))
    ws.append(["Formula version", snapshot.get("formula_version", {}).get("version_id")])
    ws.append(["Effective from", snapshot.get("formula_version", {}).get("effective_from")])
    ws.append(["Tender rule", snapshot.get("formula_version", {}).get("tender", {}).get("calculation")])
    ws.append(["Approval rule", snapshot.get("formula_version", {}).get("approval", {}).get("calculation")])
    ws.append([])
    ws.append(["Row", "Work item", "Formula ref", "Source page", "Workbook/source cells"])
    _headers(ws, ws.max_row, ["Row", "Work item", "Formula ref", "Source page", "Workbook/source cells"])
    for item in snapshot.get("rows", []):
        detail = item.get("approval_detail") or {}
        ws.append([item.get("row_number"), item.get("mapped_work_item"), item.get("tender_formula_ref"), item.get("source_page"), "; ".join(detail.get("source_cells") or [])])
    ws.column_dimensions["E"].width = 80


def _internal_review_history(wb: Workbook, snapshot: dict[str, Any]) -> None:
    ws = wb.create_sheet("Review History")
    _title(ws, "REVIEW AND CORRECTION HISTORY", snapshot.get("snapshot_id", ""))
    _headers(ws, 3, ["Row", "Field", "Old value", "New value", "Reviewer", "Timestamp"])
    for item in snapshot.get("rows", []):
        for event in item.get("review_history") or []:
            ws.append([item.get("row_number"), event.get("field"), event.get("old_value"), event.get("new_value"), event.get("user"), event.get("created_at")])
    for column in ["C", "D"]: ws.column_dimensions[column].width = 42


def _internal_unresolved(wb: Workbook, snapshot: dict[str, Any]) -> None:
    ws = wb.create_sheet("Unresolved Register")
    _title(ws, "UNRESOLVED ITEM REGISTER", "Final submission is blocked while mandatory evidence remains unresolved.")
    _headers(ws, 3, ["Row ID", "Row", "Description", "Conflicts"])
    for item in snapshot.get("unresolved_register") or []:
        ws.append([item.get("row_id"), item.get("row_number"), item.get("description"), "; ".join(item.get("conflicts") or [])])
    ws.column_dimensions["C"].width = 62; ws.column_dimensions["D"].width = 64


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
        if row.status == "mapped_and_priced" and row.unit_price_str is not None and row.extended_amount_str is not None:
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
