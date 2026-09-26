"""
Tests for the pricing engine — Decimal arithmetic, guards, unit rules.
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from boq.reconstructor import BOQLineItem
from pricing_engine.engine import PricingEngine
from semantic_mapper.mapper import MappingOutput


def make_line_item(qty=100.0, unit="m", row_type="line_item") -> BOQLineItem:
    return BOQLineItem(
        row_id="test-1",
        row_number="7",
        section_path="II > II.1",
        description_vi="Khoan thăm dò địa chất đường, lỗ khoan 0–30m",
        unit_raw=unit,
        quantity_raw=str(qty).replace(".", ","),
        quantity=qty,
        page=1,
        region="",
        row_type=row_type,
        doc_order=0,
    )


def make_mapping(master_id=1, status="resolved") -> MappingOutput:
    return MappingOutput(
        master_item_id=master_id if status == "resolved" else None,
        confidence=0.9,
        tags={},
        evidence="test",
        unresolved_reason=None if status == "resolved" else "test unresolved",
        status=status,
    )


MASTER_ITEMS = {
    1: {
        "id": 1, "item_code": "KS-006",
        "description_vi": "Khoan thăm dò địa chất đường, lỗ khoan 0–30m, đất cấp II",
        "unit": "m", "unit_price": 380000.0, "formula_ref": "DT_KS_006",
    }
}

UNIT_RULES = [
    {"from_unit": "100m", "to_unit": "m", "factor": 100},
    {"from_unit": "km", "to_unit": "m", "factor": 1000},
]

COEFFICIENTS = [
    {"coeff_code": "K_TT", "value": 1.0, "applies_to": "all"},
]


class TestPricingEngine:
    def test_basic_pricing(self):
        engine = PricingEngine()
        item = make_line_item(qty=624.0, unit="m")
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "priced"
        assert result.unit_price_str == "380000"
        assert result.extended_amount_str == str(380000 * 624)

    def test_decimal_arithmetic_not_float(self):
        """Verify result is computed with Decimal precision."""
        engine = PricingEngine()
        item = make_line_item(qty=0.030, unit="m")
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "priced"
        expected = Decimal("380000") * Decimal("0.03")
        assert Decimal(result.extended_amount_str) == expected.to_integral_value()

    def test_heading_row_rejected(self):
        engine = PricingEngine()
        item = make_line_item(row_type="heading")
        mapping = make_mapping()
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "error"
        assert "not a billable item" in result.error_reason.lower()

    def test_metadata_row_rejected(self):
        engine = PricingEngine()
        item = make_line_item(row_type="metadata")
        mapping = make_mapping()
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "error"

    def test_unresolved_mapping_returns_unresolved(self):
        engine = PricingEngine()
        item = make_line_item(qty=100.0, unit="m")
        mapping = make_mapping(status="unresolved")
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "unresolved"

    def test_missing_master_returns_error(self):
        engine = PricingEngine()
        item = make_line_item(qty=100.0, unit="m")
        mapping = make_mapping(master_id=999)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "error"
        assert "not found" in result.error_reason.lower()

    def test_null_quantity_returns_unresolved(self):
        engine = PricingEngine()
        item = make_line_item()
        item.quantity = None
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "unresolved"
        assert "missing" in result.error_reason.lower() or "quantity" in result.error_reason.lower()

    def test_unit_conversion_100m_to_m(self):
        engine = PricingEngine()
        item = make_line_item(qty=6.24, unit="100m")
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "priced"
        # 6.24 × 100 = 624 m → 624 × 380000
        assert result.unit_rule_ref is not None
        assert "100m" in result.unit_rule_ref

    def test_unit_mismatch_no_rule_returns_unresolved(self):
        engine = PricingEngine()
        item = make_line_item(qty=100.0, unit="ha")  # master uses "m", no ha→m rule
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.status == "unresolved"
        assert "unit mismatch" in result.error_reason.lower()

    def test_traceability_fields(self):
        engine = PricingEngine()
        item = make_line_item(qty=624.0, unit="m")
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        assert result.price_source == "master_v1"
        assert result.formula_ref == "DT_KS_006"
        assert isinstance(result.coeff_applied, list)

    def test_zero_quantity_allowed_when_explicit(self):
        """Explicit zero in PDF is allowed; None is not."""
        engine = PricingEngine()
        item = make_line_item(qty=0.0, unit="m")
        item.quantity = 0.0
        item.quantity_raw = "0"
        mapping = make_mapping(master_id=1)
        result = engine.price_row(item, mapping, MASTER_ITEMS, UNIT_RULES, COEFFICIENTS)
        # Zero quantity produces zero extended amount — not rejected
        assert result.status == "priced"
        assert result.extended_amount_str == "0"
