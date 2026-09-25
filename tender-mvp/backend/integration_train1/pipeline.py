from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from parser_adapter.provider_neutral import ProviderNeutralParserAdapter, RecordedFixtureProvider
from pricing_engine.calculation_engine_v2 import CalculationEngineV2


FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "fixtures" / "parser_api_recorded_train1.json"


def _d(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _parse_quantity(raw: str) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return Decimal("0")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _unit_compatible(lhs: str, rhs: str) -> bool:
    a = (lhs or "").strip().lower()
    b = (rhs or "").strip().lower()
    if not a or not b:
        return True
    return a == b


@dataclass
class Train1Run:
    run_id: str
    source_document_id: str
    parsed_rows: list[dict[str, Any]]
    runtime: dict[str, Any]
    review: dict[str, Any]


class Train1Pipeline:
    def __init__(self):
        self.engine = CalculationEngineV2()
        self._runs: dict[str, Train1Run] = {}

    async def start_from_fixture(self, fixture_path: Path | None = None) -> dict[str, Any]:
        provider = RecordedFixtureProvider(fixture_path or FIXTURE_PATH)
        adapter = ProviderNeutralParserAdapter(provider)
        parsed = await adapter.parse()
        return self.start_from_parsed_payload(parsed)

    def start_from_parsed_payload(self, parsed: dict[str, Any]) -> dict[str, Any]:
        runtime = self.engine.load_runtime_data()
        review = self._build_review(parsed, runtime)
        run_id = str(uuid.uuid4())
        run = Train1Run(
            run_id=run_id,
            source_document_id=str(parsed.get("document_id") or "fixture-document"),
            parsed_rows=copy.deepcopy(parsed.get("rows", [])),
            runtime=runtime,
            review=review,
        )
        self._runs[run_id] = run
        return {"run_id": run_id, **review}

    def get_review(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        return {"run_id": run_id, **run.review}

    def apply_manual_mapping(self, run_id: str, row_id: str, canonical_code: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")

        rows = copy.deepcopy(run.parsed_rows)
        target = next((r for r in rows if str(r.get("row_id")) == row_id), None)
        if target is None:
            raise KeyError(f"Row not found: {row_id}")

        target["manual_selected_code"] = canonical_code
        target["manual_override_evidence"] = "manual_override"

        run.parsed_rows = rows
        run.review = self._build_review({"document_id": run.source_document_id, "rows": rows}, run.runtime)
        return {"run_id": run_id, **run.review}

    def mutate_runtime_prices(self, run_id: str, price_updates: dict[str, str]) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        mutated_runtime = copy.deepcopy(run.runtime)
        price_book = mutated_runtime.get("resource_price_book") or {}
        for code, new_price in price_updates.items():
            if code not in price_book:
                continue
            price_book[code]["unit_price"] = str(_d(new_price))
        run.runtime = mutated_runtime
        run.review = self._build_review({"document_id": run.source_document_id, "rows": run.parsed_rows}, run.runtime)
        return {"run_id": run_id, **run.review}

    def export_excel(self, run_id: str) -> bytes:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        review = run.review

        wb = Workbook()
        ws = wb.active
        ws.title = "Train1-Review"

        ws.append([
            "row_id",
            "description_vi",
            "unit",
            "quantity",
            "mapping_status",
            "canonical_code",
            "loaded_unit_price",
            "tender_unit_price",
            "tender_extension",
            "approval_unit_price",
            "approval_extension",
            "confidence",
            "evidence",
        ])
        for row in review["rows"]:
            ws.append(
                [
                    row["row_id"],
                    row["description_vi"],
                    row["unit_raw"],
                    row["quantity_raw"],
                    row["mapping_status"],
                    row.get("canonical_code"),
                    row.get("loaded_unit_price"),
                    row.get("tender_unit_price"),
                    row.get("tender_extension"),
                    row.get("approval_unit_price"),
                    row.get("approval_extension"),
                    row.get("confidence"),
                    row.get("mapping_evidence"),
                ]
            )

        ws2 = wb.create_sheet("Train1-Summary")
        ws2.append(["status", review["status"]])
        ws2.append(["tender_partial_subtotal", review["tender_partial_subtotal"]])
        ws2.append(["approval_partial_subtotal", review["approval_partial_subtotal"]])
        ws2.append(["official_tender_total", review["official_tender_total"] if review["status"] == "COMPLETE" else None])
        ws2.append(["official_approval_total", review["official_approval_total"] if review["status"] == "COMPLETE" else None])

        ws3 = wb.create_sheet("Train1-Unresolved")
        ws3.append(["row_id", "mapping_status", "reason", "missing_dependencies"])
        for row in review["rows"]:
            if row["mapping_status"] != "resolved":
                ws3.append([
                    row["row_id"],
                    row["mapping_status"],
                    row.get("reason"),
                    ", ".join(row.get("missing_dependencies") or []),
                ])

        import io

        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    def _build_review(self, parsed: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        work_master = runtime.get("work_item_master") or {}

        rows_out: list[dict[str, Any]] = []
        tender_partial = Decimal("0")
        approval_partial = Decimal("0")
        unresolved_required = 0
        required_rows = 0

        for index, row in enumerate(parsed.get("rows", [])):
            row_id = str(row.get("row_id") or f"row-{index+1}")
            row_type = str(row.get("row_type") or "line_item")
            description_vi = str(row.get("description_vi") or "")
            unit_raw = str(row.get("unit_raw") or "")
            quantity_raw = str(row.get("quantity_raw") or "")
            quantity = _parse_quantity(quantity_raw)
            evidence = list(row.get("evidence") or [])
            suggestions = list(row.get("ai_suggestions") or [])
            manual_selected_code = str(row.get("manual_selected_code") or "").strip()

            if row_type == "line_item":
                required_rows += 1

            mapping_status = "resolved"
            canonical_code: str | None = None
            confidence = None
            reason = None
            missing_dependencies: list[str] = []
            loaded_unit_price = None
            tender_unit_price = None
            tender_extension = None
            approval_unit_price = None
            approval_extension = None

            unique_codes: dict[str, dict[str, Any]] = {}
            if manual_selected_code:
                if manual_selected_code in work_master:
                    unique_codes[manual_selected_code] = {
                        "code": manual_selected_code,
                        "confidence": 1.0,
                        "evidence": str(row.get("manual_override_evidence") or "manual_override"),
                        "source": "manual",
                    }
                else:
                    mapping_status = "mapping_unmatched"
                    reason = "Manual code is not in verified WorkItemMaster"
            if mapping_status == "resolved" and not manual_selected_code:
                for s in suggestions:
                    code = str(s.get("code") or "").strip()
                    if not code:
                        continue
                    if code in work_master:
                        unique_codes[code] = s

            candidate_codes = sorted(unique_codes.keys())
            compatible_codes = [
                code for code in candidate_codes if _unit_compatible(unit_raw, str((work_master.get(code) or {}).get("unit") or ""))
            ]

            if row_type != "line_item":
                mapping_status = "non_billable"
                reason = "Non-billable row type"
            elif quantity is None:
                mapping_status = "invalid_quantity"
                reason = "Quantity is unparseable"
            elif not candidate_codes:
                mapping_status = "mapping_unmatched"
                reason = "No verified WorkItemMaster suggestion"
            elif not compatible_codes:
                mapping_status = "unit_incompatible"
                reason = "Suggested code exists but unit is incompatible"
            elif len(compatible_codes) > 1:
                mapping_status = "mapping_ambiguous"
                reason = "Multiple compatible verified codes require manual review"
            else:
                canonical_code = compatible_codes[0]
                confidence = float(unique_codes[canonical_code].get("confidence") or 0)
                item_result = self.engine.calculate_work_item_from_runtime(canonical_code, runtime)
                if item_result.get("calculation_status") != "resolved":
                    mapping_status = "unsupported_blocking_item"
                    reason = "Mapped item has unresolved required dependencies"
                    missing_dependencies = list(item_result.get("missing_dependencies") or [])
                else:
                    work_item = work_master.get(canonical_code) or {}
                    category = str(work_item.get("category") or "default")
                    approval_group = str(work_item.get("approval_rule_group") or "") or None
                    approval_rules = self.engine.approval_rules_for(category, work_item, runtime=runtime, approval_group=approval_group)
                    approval_components = self.engine._compute_loaded_components(
                        item_result["direct_material_total"],
                        item_result["direct_labour_total"],
                        item_result["direct_machine_total"],
                        approval_rules,
                    )
                    loaded_unit_price = str(item_result.get("loaded_unit_price"))
                    tender_unit_price = str(item_result.get("tender_rounded_unit_price"))
                    approval_unit_price = str(approval_components["FINAL"])
                    tender_extension_value = (item_result["tender_rounded_unit_price"] * quantity).quantize(Decimal("1"))
                    approval_extension_value = (approval_components["FINAL"] * quantity).quantize(Decimal("1"))
                    tender_extension = str(tender_extension_value)
                    approval_extension = str(approval_extension_value)
                    tender_partial += tender_extension_value
                    approval_partial += approval_extension_value

            if row_type == "line_item" and mapping_status != "resolved":
                unresolved_required += 1

            rows_out.append(
                {
                    "row_id": row_id,
                    "row_type": row_type,
                    "description_vi": description_vi,
                    "unit_raw": unit_raw,
                    "quantity_raw": quantity_raw,
                    "quantity": str(quantity) if quantity is not None else None,
                    "evidence": evidence,
                    "mapping_status": mapping_status,
                    "canonical_code": canonical_code,
                    "confidence": confidence,
                    "mapping_evidence": unique_codes.get(canonical_code, {}).get("evidence") if canonical_code else None,
                    "candidate_codes": candidate_codes,
                    "reason": reason,
                    "missing_dependencies": missing_dependencies,
                    "loaded_unit_price": loaded_unit_price,
                    "tender_unit_price": tender_unit_price,
                    "tender_extension": tender_extension,
                    "approval_unit_price": approval_unit_price,
                    "approval_extension": approval_extension,
                }
            )

        complete = required_rows > 0 and unresolved_required == 0
        return {
            "source_document_id": str(parsed.get("document_id") or "fixture-document"),
            "required_row_count": required_rows,
            "resolved_required_row_count": required_rows - unresolved_required,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "official_tender_total": str(tender_partial) if complete else None,
            "official_approval_total": str(approval_partial) if complete else None,
            "tender_partial_subtotal": str(tender_partial),
            "approval_partial_subtotal": str(approval_partial),
            "rows": rows_out,
        }


PIPELINE = Train1Pipeline()
