"""
Pricing Engine — deterministic price calculation.

Rules:
- Fetch master unit price for confirmed master_item_id
- Apply unit conversion factor from unit_rules (must be explicit)
- Apply applicable coefficients from coeff table
- extended_amount = unit_price_converted × quantity
- ALL arithmetic uses Python Decimal; no floats
- Reject if: master ID not found, unit incompatible without rule, quantity null/missing
- Mark heading/metadata rows as error
- Every output carries price_source, formula_ref, coeff_applied, unit_rule_ref
"""
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from boq.reconstructor import BOQLineItem
from semantic_mapper.mapper import MappingOutput


@dataclass
class PriceResult:
    row_id: str
    status: str                          # "priced" | "unresolved" | "error"
    unit_price_str: Optional[str]        # Decimal as string, e.g. "380000"
    extended_amount_str: Optional[str]   # Decimal as string
    price_source: str                    # e.g. "master_v1"
    formula_ref: Optional[str]
    coeff_applied: list[str]
    unit_rule_ref: Optional[str]
    error_reason: Optional[str]


class PricingEngine:
    """
    Deterministic pricing engine.
    Accepts pre-fetched master_items and unit_rules dicts to avoid DB coupling.
    """

    def price_row(
        self,
        item: BOQLineItem,
        mapping: MappingOutput,
        master_items: dict[int, dict],   # id → {unit_price, formula_ref, unit, ...}
        unit_rules: list[dict],           # [{from_unit, to_unit, factor, ...}]
        coefficients: list[dict],         # [{coeff_code, value, applies_to}]
        master_version: str = "v1",
    ) -> PriceResult:

        # Guard: non-billable rows
        if item.row_type != "line_item":
            return PriceResult(
                row_id=item.row_id,
                status="error",
                unit_price_str=None,
                extended_amount_str=None,
                price_source=f"master_{master_version}",
                formula_ref=None,
                coeff_applied=[],
                unit_rule_ref=None,
                error_reason=f"Not a billable item: row_type={item.row_type}",
            )

        # Guard: unresolved mapping
        if mapping.status != "resolved" or mapping.master_item_id is None:
            return PriceResult(
                row_id=item.row_id,
                status="unresolved",
                unit_price_str=None,
                extended_amount_str=None,
                price_source=f"master_{master_version}",
                formula_ref=None,
                coeff_applied=[],
                unit_rule_ref=None,
                error_reason=mapping.unresolved_reason or "Mapping unresolved",
            )

        # Guard: master item not found
        master = master_items.get(mapping.master_item_id)
        if master is None:
            return PriceResult(
                row_id=item.row_id,
                status="error",
                unit_price_str=None,
                extended_amount_str=None,
                price_source=f"master_{master_version}",
                formula_ref=None,
                coeff_applied=[],
                unit_rule_ref=None,
                error_reason=f"Master item id={mapping.master_item_id} not found in version {master_version}",
            )

        # Guard: quantity must not be None (zero is allowed if explicitly stated)
        if item.quantity is None:
            return PriceResult(
                row_id=item.row_id,
                status="unresolved",
                unit_price_str=None,
                extended_amount_str=None,
                price_source=f"master_{master_version}",
                formula_ref=master.get("formula_ref"),
                coeff_applied=[],
                unit_rule_ref=None,
                error_reason="Quantity is missing/unparseable — not defaulting to zero",
            )

        # Unit compatibility check
        pdf_unit = item.unit_raw.strip()
        master_unit = master.get("unit", "").strip()
        unit_rule_ref = None
        conversion_factor = Decimal("1")

        if pdf_unit.lower() != master_unit.lower():
            rule = self._find_unit_rule(pdf_unit, master_unit, unit_rules)
            if rule is None:
                return PriceResult(
                    row_id=item.row_id,
                    status="unresolved",
                    unit_price_str=None,
                    extended_amount_str=None,
                    price_source=f"master_{master_version}",
                    formula_ref=master.get("formula_ref"),
                    coeff_applied=[],
                    unit_rule_ref=None,
                    error_reason=(
                        f"Unit mismatch: PDF='{pdf_unit}' master='{master_unit}' "
                        f"with no approved conversion rule"
                    ),
                )
            conversion_factor = Decimal(str(rule["factor"]))
            unit_rule_ref = f"{rule['from_unit']}→{rule['to_unit']}×{rule['factor']}"

        # Arithmetic — all Decimal
        try:
            base_price = Decimal(str(master["unit_price"]))
            quantity = Decimal(str(item.quantity))
        except InvalidOperation as exc:
            return PriceResult(
                row_id=item.row_id,
                status="error",
                unit_price_str=None,
                extended_amount_str=None,
                price_source=f"master_{master_version}",
                formula_ref=master.get("formula_ref"),
                coeff_applied=[],
                unit_rule_ref=unit_rule_ref,
                error_reason=f"Decimal conversion error: {exc}",
            )

        # Apply unit conversion to the price (or to quantity — whichever direction the rule specifies)
        # Convention: unit_rule converts PDF unit → master unit; price is per master unit
        # so quantity_in_master_unit = quantity_pdf × factor
        quantity_converted = quantity * conversion_factor
        unit_price_final = base_price

        # Apply coefficients
        coeff_applied: list[str] = []
        item_code = master.get("item_code", "")
        for coeff in coefficients:
            applies_to = coeff.get("applies_to", "all")
            if applies_to == "all" or (isinstance(applies_to, list) and item_code in applies_to):
                cv = Decimal(str(coeff["value"]))
                unit_price_final = unit_price_final * cv
                coeff_applied.append(f"{coeff['coeff_code']}×{coeff['value']}")

        extended = (unit_price_final * quantity_converted).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )

        return PriceResult(
            row_id=item.row_id,
            status="priced",
            unit_price_str=str(unit_price_final.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            extended_amount_str=str(extended),
            price_source=f"master_{master_version}",
            formula_ref=master.get("formula_ref"),
            coeff_applied=coeff_applied,
            unit_rule_ref=unit_rule_ref,
            error_reason=None,
        )

    def _find_unit_rule(
        self, from_unit: str, to_unit: str, rules: list[dict]
    ) -> Optional[dict]:
        fu = from_unit.strip().lower()
        tu = to_unit.strip().lower()
        for r in rules:
            if r["from_unit"].lower() == fu and r["to_unit"].lower() == tu:
                return r
        return None
