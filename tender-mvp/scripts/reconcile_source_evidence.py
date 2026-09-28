#!/usr/bin/env python3
"""Build a source-cell reconciliation for Bang TIen Luong.pdf.

This is an acceptance/audit utility, not a production parser.  It consumes the
raw Azure result and the original 62-sheet .xls workbook so every conclusion is
traceable to supplied source material.  It never reads credentials or calls an
external service.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import xlrd
from openpyxl import load_workbook


# PDF document-order row -> Công trình worksheet row.  Every mapping below was
# independently reviewed against description, method/terrain qualifiers, and
# units.  Omitted rows are deliberately blocked below rather than guessed.
SOURCE_MAP: dict[int, int] = {
    2: 8,
    6: 12,
    9: 15,
    10: 16,
    11: 17,
    13: 42,
    14: 45,
    15: 43,
    16: 46,
    17: 44,
    18: 47,
    21: 28,
    22: 21,
    23: 30,
    24: 31,
    25: 32,
    26: 35,
    28: 37,
    29: 31,
    30: 39,
    32: 42,
    33: 45,
    34: 43,
    35: 46,
    36: 44,
    37: 47,
    39: 52,
    40: 53,
    41: 54,
    42: 55,
    43: 56,
    44: 57,
    45: 58,
    49: 63,
    51: 71,
    55: 77,
    56: 78,
    57: 80,
    58: 79,
    59: 81,
    60: 82,
    61: 83,
    62: 92,
    63: 90,
    64: 84,
    65: 96,
    66: 73,
    68: 66,
    69: 71,
    74: 77,
    75: 78,
    76: 80,
    77: 79,
    78: 81,
    79: 82,
    80: 83,
    81: 92,
    82: 90,
    83: 84,
    84: 85,
    85: 96,
    86: 100,
    87: 102,
    91: 73,
    93: 109,
    94: 110,
}

BLOCKERS: dict[int, str] = {
    3: "No workbook work item for 'Thị sát hiện trường'; no rate or norm supplied.",
    7: "PDF requires a class-II elevation monument; workbook literal is class III.",
    8: "Candidate CF.11220 is priced per point, while the PDF requires monuments; no verified conversion.",
    27: "PDF requires 1/500 underwater terrain class I; workbook row 36 is class II.",
    46: "No workbook work item, norm, or literal rate for the hydrology calculation report.",
    50: "PDF says field vane-shear test; workbook CE.11310 says rotary shear. Equivalence is not evidenced.",
    52: "No workbook work item or price for an intact cohesive-soil sample as a separately billed sample.",
    53: "No workbook work item or price for a disturbed non-sand/gravel sample.",
    54: "No workbook work item or price for a disturbed sand/gravel sample.",
    70: "PDF says field vane-shear test; workbook CE.11310 says rotary shear. Equivalence is not evidenced.",
    71: "No workbook work item or price for an intact cohesive-soil sample as a separately billed sample.",
    72: "No workbook work item or price for a disturbed non-sand/gravel sample.",
    73: "No workbook work item or price for a disturbed sand/gravel sample.",
    88: "No workbook code/norm/price for water CO2 content; DC.01003 is sulfate and cannot be substituted.",
    89: "No workbook code/norm/price for water NH4+ content.",
    90: "No workbook code/norm/price for water Mg++ content.",
}

UNIT_ALIASES = {
    ("m", "m khoan"),
    ("tn", "1 lần tn"),
    ("thí nghiệm", "1 lần tn"),
    ("chỉ tiêu", "1 chỉ tiêu"),
}


def d(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def round1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def norm(value: Any) -> str:
    value = unicodedata.normalize("NFD", clean(value).casefold())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn").replace("đ", "d")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def parse_quantity(raw: str) -> Decimal | None:
    raw = clean(raw)
    if not raw or raw == "-":
        return None
    try:
        return Decimal(raw.replace(".", "").replace(",", ".")) if "," in raw else Decimal(raw)
    except Exception:
        return None


def azure_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    analyze = raw.get("analyzeResult", raw)
    result: list[dict[str, Any]] = []
    for table_no, table in enumerate(analyze["tables"], 1):
        cells_by_row: dict[int, dict[int, dict[str, Any]]] = {}
        for cell in table["cells"]:
            cells_by_row.setdefault(int(cell["rowIndex"]), {})[int(cell["columnIndex"])] = cell
        for row_no in sorted(cells_by_row):
            cells = cells_by_row[row_no]
            if any(cell.get("kind") == "columnHeader" for cell in cells.values()):
                continue
            values = [clean(cells.get(i, {}).get("content")) for i in range(4)]
            if not any(values):
                continue
            page = int(next(iter(cells.values()))["boundingRegions"][0]["pageNumber"])
            evidence = []
            for col, cell in sorted(cells.items()):
                text = clean(cell.get("content"))
                if text:
                    region = cell["boundingRegions"][0]
                    evidence.append({
                        "locator": f"p{page}:tbl{table_no}:r{row_no}:c{col}",
                        "page": page,
                        "table": table_no,
                        "row": row_no,
                        "column": col,
                        "text": text,
                        "polygon": region.get("polygon", []),
                    })
            result.append({
                "stt": values[0],
                "description": values[1],
                "unit": values[2],
                "quantity_raw": values[3],
                "quantity": parse_quantity(values[3]),
                "page": page,
                "evidence": evidence,
            })
    return result


def canonical_source_rows(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Return the 95-row source contract without rewriting the Azure fixture."""
    historical = azure_rows(raw)
    for index, row in enumerate(historical, 1):
        row["historical_azure_source_index"] = index
        row["source_origin"] = "azure_document_intelligence"
        row["azure_polygon_available"] = True
    if any(row["stt"].strip().upper() == "II.3.2" for row in historical):
        return historical, len(historical)
    insertion = next(
        index for index, row in enumerate(historical)
        if row["page"] == 2 and row["stt"] == "1"
        and row["description"] == "Đo vẽ bình đồ cầu trên cạn, tỷ lệ 1/500, địa hình cấp II"
    )
    recovered = {
        "stt": "II.3.2",
        "description": "Cầu nhỏ, cầu trung, tỷ lệ 1/500: bình đồ, cắt dọc",
        "unit": "",
        "quantity_raw": "-",
        "quantity": None,
        "page": 2,
        "evidence": [],
        "historical_azure_source_index": None,
        "source_origin": "source_document_inspection",
        "azure_polygon_available": False,
        "source_provenance": (
            "Visible in the original PDF and recovered by source-document inspection; "
            "the historical Azure fixture omitted it, so no Azure polygon exists."
        ),
    }
    return [*historical[:insertion], recovered, *historical[insertion:]], len(historical)


def parse_recipe(raw: Any, resource_type: str, cell_ref: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for ordinal, segment in enumerate(str(raw or "").split("ž"), 1):
        fields = segment.split("~")
        if len(fields) < 8 or not clean(fields[0]):
            continue
        quantity = d(fields[4])
        # Serialized recipe layout: code, description, unit, base norm,
        # effective norm, old price, effective price, ...
        unit_price = d(fields[6])
        if clean(fields[2]) == "%":
            line_total = round1(quantity * unit_price)
            pricing_rule = f"PCT_{resource_type.upper()}_SUBTOTAL"
        else:
            line_total = round1(quantity * unit_price)
            pricing_rule = "PRICE_BOOK"
        lines.append({
            "resource_type": resource_type,
            "code": clean(fields[0]),
            "description": clean(fields[1]),
            "unit": clean(fields[2]),
            "norm_quantity": str(quantity),
            "unit_price": str(unit_price),
            "line_total": str(line_total),
            "pricing_rule": pricing_rule,
            "provenance": f"Công trình!{cell_ref} (serialized recipe item {ordinal})",
        })
    return lines


def work_item_code(sheet: xlrd.sheet.Sheet, row: int) -> str:
    return clean(sheet.cell_value(row - 1, 4) or sheet.cell_value(row - 1, 2)) or f"WORKBOOK.LITERAL.R{row}"


def direct_components(sheet: xlrd.sheet.Sheet, row: int) -> tuple[dict[str, Decimal], list[dict[str, Any]]]:
    idx = row - 1
    stored = {
        "material": d(sheet.cell_value(idx, 16)),
        "other": d(sheet.cell_value(idx, 17)),
        "labour": d(sheet.cell_value(idx, 18)),
        "machine": d(sheet.cell_value(idx, 19)),
    }
    recipes = (
        parse_recipe(sheet.cell_value(idx, 30), "material", f"AE{row}"),
        parse_recipe(sheet.cell_value(idx, 31), "labour", f"AF{row}"),
        parse_recipe(sheet.cell_value(idx, 32), "machine", f"AG{row}"),
    )
    lines = [line for group in recipes for line in group]
    computed = {kind: sum((d(x["line_total"]) for x in group), Decimal("0")) for kind, group in zip(("material", "labour", "machine"), recipes)}
    # Q/S/T are authoritative cached direct totals where present.  Otherwise
    # the serialized norm is the only source for the component.
    for kind in ("material", "labour", "machine"):
        if stored[kind] == 0 and computed[kind] != 0:
            stored[kind] = round1(computed[kind])
    return stored, lines


def loaded_components(material: Decimal, labour: Decimal, machine: Decimal, category: str, approval: bool) -> dict[str, Decimal]:
    laboratory = category == "laboratory"
    vat_rate = Decimal("0.10")
    tt_rate = Decimal("0")
    lt_rate = Decimal("0") if laboratory else Decimal("0.02")
    gdp_rate = Decimal("0.10") if approval else Decimal("0")
    total = round1(material + labour + machine)
    common = round1(labour * Decimal("0.60"))
    unidentified = round1(total * tt_rate)
    indirect = round1(common + unidentified)
    pre_tax_income = round1((total + indirect) * Decimal("0.06"))
    base = total + indirect + pre_tax_income
    technical_plan = Decimal("0") if laboratory else round1(base * Decimal("0.015"))
    report = round1(base * Decimal("0.025"))
    service = round1(technical_plan + report)
    before_tax = round1(total + indirect + pre_tax_income + service)
    vat = round1(before_tax * vat_rate)
    after_tax = round1(before_tax + vat)
    camp = round1(after_tax * lt_rate)
    contingency = round1(after_tax * gdp_rate)
    final = (after_tax + camp + contingency).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {
        "T": total, "C": common, "TT": unidentified, "GT": indirect,
        "TL": pre_tax_income, "Cpa": technical_plan, "Cbc": report,
        "Cpvks": service, "G": before_tax, "VAT": vat, "Gks": after_tax,
        "LT": camp, "Gdp": contingency, "FINAL": final,
    }


def category_for(source_row: int) -> str:
    if 77 <= source_row <= 105:
        return "laboratory"
    if 63 <= source_row <= 73:
        return "geotechnical_drilling"
    return "topography"


def block_index(sheet: xlrd.sheet.Sheet) -> list[tuple[int, str, str, str]]:
    blocks = []
    for r in range(sheet.nrows):
        code = clean(sheet.cell_value(r, 1))
        desc = clean(sheet.cell_value(r, 2))
        unit = clean(sheet.cell_value(r, 3))
        try:
            is_header = d(sheet.cell_value(r, 4)) == 1
        except Exception:
            is_header = False
        if code and desc and unit and is_header:
            blocks.append((r + 1, code, desc, unit))
    return blocks


def find_block(blocks: list[tuple[int, str, str, str]], desc: str, unit: str) -> int | None:
    matches = [r for r, _code, candidate_desc, candidate_unit in blocks if norm(candidate_desc) == norm(desc) and norm(candidate_unit) == norm(unit)]
    return matches[0] if matches else None


def final_cell(sheet: xlrd.sheet.Sheet, header_row: int, next_header: int | None) -> tuple[str, Decimal] | None:
    stop = (next_header - 1) if next_header else sheet.nrows
    for r in range(header_row, stop):
        label = clean(sheet.cell_value(r, 2))
        if label.startswith("Chi phí khảo sát xây dựng"):
            return f"{sheet.name}!H{r + 1}", d(sheet.cell_value(r, 7))
    return None


def excel_formula(formula_sheet: Any, ref: str) -> str | None:
    _sheet, cell = ref.split("!", 1)
    value = formula_sheet[cell].value
    return value if isinstance(value, str) and value.startswith("=") else None


def serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def build(args: argparse.Namespace) -> dict[str, Any]:
    raw = json.loads(Path(args.azure_json).read_text(encoding="utf-8"))
    rows, historical_azure_count = canonical_source_rows(raw)
    workbook = xlrd.open_workbook(args.workbook)
    ct = workbook.sheet_by_name("Công trình")
    chiet = workbook.sheet_by_name("Chiết tính")
    blocks = block_index(chiet)
    formula_book = load_workbook(args.formula_xlsx, data_only=False, read_only=True)
    formula_chiet = formula_book["Chiết tính"]
    tender_sheet = workbook.sheet_by_name("Dự thầu")
    approval_sheet = workbook.sheet_by_name("THKP ks duyet")
    formula_tender = formula_book["Dự thầu"]
    formula_approval = formula_book["THKP ks duyet"]
    analyze = raw.get("analyzeResult", raw)

    audited_rows = []
    tender_partial = Decimal("0")
    approval_direct_by_category: dict[str, dict[str, Decimal]] = {}
    mapped_count = 0
    corrected_non_billable = 0

    for index, row in enumerate(rows, 1):
        historical_index = row.get("historical_azure_source_index")
        base = {
            "source_index": index,
            "historical_azure_source_index": historical_index,
            "page": row["page"],
            "stt": row["stt"],
            "description": row["description"],
            "source_unit": row["unit"],
            "source_quantity_raw": row["quantity_raw"],
            "source_quantity": row["quantity"],
            "source_evidence": row["evidence"],
            "source_origin": row.get("source_origin"),
            "source_provenance": row.get("source_provenance"),
            "azure_polygon_available": row.get("azure_polygon_available", True),
        }
        if row["stt"] in {"II.3.1", "II.3.2"}:
            corrected_non_billable += 1
            treatment = "recovered_non_billable_subsection" if row["stt"] == "II.3.2" else "non_billable_nested_subsection"
            reason = ("II.3.2 is visible in the PDF but absent from the historical Azure extraction; "
                      "it is a structural parent with no applicable price or Azure polygon.") if row["stt"] == "II.3.2" else "II.3.1 is a nested subsection with dash quantity."
            audited_rows.append({**base, "treatment": treatment, "status": "VERIFIED", "reason": reason,
                                 "pricing_availability": "not_applicable", "price_display": "Not applicable",
                                 "unit_price": None, "unit_price_editable": False})
            continue
        if row["quantity"] is None or not row["stt"].isdigit():
            audited_rows.append({**base, "treatment": "non_billable", "status": "VERIFIED"})
            continue
        if historical_index in BLOCKERS:
            audited_rows.append({**base, "treatment": "blocked", "status": "BLOCKED", "reason": BLOCKERS[historical_index]})
            continue
        source_row = SOURCE_MAP.get(historical_index)
        if source_row is None:
            raise AssertionError(f"No verified treatment configured for numeric PDF row {index}")

        mapped_count += 1
        code = work_item_code(ct, source_row)
        description = clean(ct.cell_value(source_row - 1, 5))
        master_unit = clean(ct.cell_value(source_row - 1, 6))
        source_unit_n, master_unit_n = norm(row["unit"]), norm(master_unit)
        conversion = "1"
        unit_status = "exact" if source_unit_n == master_unit_n else "verified_alias" if (source_unit_n, master_unit_n) in UNIT_ALIASES else "section_specific_match"
        direct, norms = direct_components(ct, source_row)
        category = category_for(source_row)
        tender = loaded_components(direct["material"], direct["labour"], direct["machine"], category, False)
        approval = loaded_components(direct["material"], direct["labour"], direct["machine"], category, True)

        header = find_block(blocks, description, master_unit)
        workbook_loaded = None
        loaded_provenance = None
        loaded_formula = None
        if header is not None:
            position = [r for r, *_ in blocks].index(header)
            nxt = blocks[position + 1][0] if position + 1 < len(blocks) else None
            found = final_cell(chiet, header, nxt)
            if found:
                loaded_provenance, workbook_loaded = found
                loaded_formula = excel_formula(formula_chiet, loaded_provenance)

        # Prefer the exact workbook formula result when the mapped work item is
        # present in Chiết tính. Otherwise report the independently recomputed
        # value and make the absence of an original final cell explicit.
        tender_unit_loaded = workbook_loaded if workbook_loaded is not None else tender["FINAL"]
        tender_unit = (tender_unit_loaded / Decimal("1000")).to_integral_value(rounding=ROUND_DOWN) * Decimal("1000")
        tender_extension = row["quantity"] * tender_unit
        approval_extension = row["quantity"] * approval["FINAL"]
        tender_partial += tender_extension
        approval_bucket = approval_direct_by_category.setdefault(
            category,
            {"material": Decimal("0"), "labour": Decimal("0"), "machine": Decimal("0")},
        )
        for component in ("material", "labour", "machine"):
            approval_bucket[component] += row["quantity"] * direct[component]

        audited_rows.append({
            **base,
            "treatment": "mapped_and_priced",
            "status": "VERIFIED",
            "mapped_work_item": code,
            "mapped_description": description,
            "master_unit": master_unit,
            "unit_match": unit_status,
            "conversion_factor": conversion,
            "converted_quantity": row["quantity"],
            "category": category,
            "workbook_provenance": {
                "master_row": f"Công trình!A{source_row}:AM{source_row}",
                "source_specification": clean(ct.cell_value(source_row - 1, 28)) or None,
                "machine_price_basis": clean(ct.cell_value(source_row - 1, 29)) or None,
                "material_direct_cell": f"Công trình!Q{source_row}",
                "labour_direct_cell": f"Công trình!S{source_row}",
                "machine_direct_cell": f"Công trình!T{source_row}",
                "loaded_price_cell": loaded_provenance,
                "loaded_price_formula": loaded_formula,
            },
            "norms": norms,
            "direct_components": direct,
            "tender": {
                "recomputed_components": tender,
                "workbook_loaded_unit_price": workbook_loaded,
                "loaded_unit_price_used": tender_unit_loaded,
                "rounded_unit_price": tender_unit,
                "extension": tender_extension,
            },
            "approval": {
                "indicative_unit_components_only": approval,
                "indicative_unit_price_only": approval["FINAL"],
                "indicative_extension_only": approval_extension,
                "note": "Official approval rules are aggregate-first; the auditable partial total is computed by category below, not by summing these indicative row values.",
            },
        })

    billable_source = [row for i, row in enumerate(rows, 1) if row["quantity"] is not None and row["stt"].isdigit()]
    blockers = [row for row in audited_rows if row["status"] == "BLOCKED"]
    approval_groups = {}
    approval_partial = Decimal("0")
    for category, totals in sorted(approval_direct_by_category.items()):
        components = loaded_components(totals["material"], totals["labour"], totals["machine"], category, True)
        approval_groups[category] = {"aggregated_direct_components": totals, "approval_components": components}
        approval_partial += components["FINAL"]
    status = "INCOMPLETE_MISSING_AUTHORITATIVE_INPUTS" if blockers else "COMPLETE"
    tender_sections = [d(tender_sheet.cell_value(row - 1, 9)) for row in (22, 30, 46)]
    tender_formula_total = d(tender_sheet.cell_value(46, 9))
    tender_recomputed_total = sum(tender_sections, Decimal("0"))
    tender_control = d(tender_sheet.cell_value(48, 9))
    tender_rounded_copy = d(tender_sheet.cell_value(49, 9))
    tender_snapshot = d(tender_sheet.cell_value(50, 9))
    approval_formula_total = d(approval_sheet.cell_value(28, 9))
    approval_unrounded = d(approval_sheet.cell_value(28, 14))
    workbook_total_evidence = {
        "tender": {
            "section_total_cells": ["Dự thầu!J22", "Dự thầu!J30", "Dự thầu!J46"],
            "section_totals": tender_sections,
            "recomputed_sum": tender_recomputed_total,
            "formula_total_cell": "Dự thầu!J47",
            "formula": formula_tender["J47"].value,
            "formula_total": tender_formula_total,
            "formula_parity_difference": tender_recomputed_total - tender_formula_total,
            "control_cell": "Dự thầu!J49",
            "control_formula": formula_tender["J49"].value,
            "control_value": tender_control,
            "control_minus_formula": tender_control - tender_formula_total,
            "rounded_copy_cell": "Dự thầu!J50",
            "rounded_copy_formula": formula_tender["J50"].value,
            "rounded_copy_value": tender_rounded_copy,
            "snapshot_cell": "Dự thầu!J51",
            "snapshot_formula": formula_tender["J51"].value,
            "snapshot_value": tender_snapshot,
            "snapshot_minus_current_formula": tender_snapshot - tender_formula_total,
        },
        "approval": {
            "formula_total_cell": "THKP ks duyet!J29",
            "formula": formula_approval["J29"].value,
            "formula_total": approval_formula_total,
            "unrounded_control_cell": "THKP ks duyet!O29",
            "unrounded_formula": formula_approval["O29"].value,
            "unrounded_value": approval_unrounded,
            "rounded_control": approval_unrounded.quantize(Decimal("1"), rounding=ROUND_HALF_UP),
            "formula_parity_difference": approval_formula_total - approval_unrounded.quantize(Decimal("1"), rounding=ROUND_HALF_UP),
            "approval_minus_current_tender": approval_formula_total - tender_formula_total,
            "approval_minus_tender_snapshot": approval_formula_total - tender_snapshot,
        },
    }
    result = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "pdf_name": "Bang TIen Luong.pdf",
            "azure_api_version": analyze.get("apiVersion"),
            "azure_model_id": analyze.get("modelId"),
            "azure_page_count": len(analyze.get("pages", [])),
            "azure_table_count": len(analyze.get("tables", [])),
            "azure_status": raw.get("status"),
            "workbook_name": Path(args.workbook).name,
            "workbook_sheet_count": workbook.nsheets,
        },
        "reconciliation": {
            "pdf_rows": len(rows),
            "source_row_count": len(rows),
            "canonical_source_row_count": len(rows),
            "historical_azure_extraction_count": historical_azure_count,
            "numeric_billable_rows": len(billable_source),
            "billable_count": len(billable_source),
            "non_billable_count": len(rows) - len(billable_source),
            "corrected_required_count": 82,
            "historical_pre_correction_count": 83,
            "structural_subsections_verified": corrected_non_billable,
            "nested_subsections_corrected": 1,
            "source_rows_recovered_from_document_inspection": 1,
            "verified_mapped_rows": mapped_count,
            "blocked_rows": len(blockers),
            "all_rows_have_treatment": len(audited_rows) == len(rows),
            "tender_partial_total": tender_partial,
            "approval_partial_total": approval_partial,
            "approval_partial_groups": approval_groups,
            "totals_are_official": False,
            "total_note": "Partial only: blocked source rows have no invented price; no complete PDF tender/approval total can be stated.",
        },
        "workbook_total_evidence": workbook_total_evidence,
        "blockers": [{"source_index": row["source_index"], "page": row["page"], "description": row["description"], "reason": row["reason"]} for row in blockers],
        "rows": audited_rows,
    }
    return serialize(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--azure-json", required=True)
    parser.add_argument("--workbook", required=True)
    parser.add_argument("--formula-xlsx", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(args)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], **result["reconciliation"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
