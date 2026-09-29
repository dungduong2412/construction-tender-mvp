from decimal import Decimal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from pricing_engine.audited_contract import CATEGORIES, formula_configuration, reconciliation_report
from pricing_engine.calculation_engine_v2 import CalculationEngineV2


def test_all_nine_hsxl_categories_are_executable_and_audited():
    engine = CalculationEngineV2()
    assert len(CATEGORIES) == 9
    for category, expected in CATEGORIES.items():
        rule = engine.tender_rules_for(category)
        assert rule["c_base"] == expected["c_base"]
        assert rule["vat_rate"] == Decimal(expected["vat_rate"])
        assert rule["lt_rate"] == Decimal(expected["lt_rate"])


def test_disabled_source_rules_remain_visible_in_configuration():
    rows = formula_configuration()
    assert len(rows) == 9 * 2 * 8
    assert any(
        row["category"] == "laboratory"
        and row["component"] == "Cpa"
        and row["effective_status"] == "Disabled by source workbook rule"
        for row in rows
    )
    assert any(
        row["category"] == "waterway_safety"
        and row["branch"] == "approved_estimate"
        and row["effective_status"] == "Disabled by source workbook rule"
        for row in rows
    )


def test_tender_and_approval_reconcile_exactly_and_j51_is_reference_only():
    report = reconciliation_report()
    assert report["tender"]["engine_amount"] == Decimal("4128377433")
    assert report["tender"]["delta"] == 0
    assert report["tender"]["status"] == "EXACT"
    assert report["approval"]["unrounded_amount"] == Decimal("4421407464.3")
    assert report["approval"]["engine_amount"] == Decimal("4421407464")
    assert report["approval"]["delta"] == 0
    assert report["approval"]["status"] == "EXACT"
    assert report["j51"]["status"] == "REFERENCE ONLY — NOT ENGINE TARGET"


def test_approval_contingency_is_ten_percent_of_post_vat_gks():
    trace = {row["symbol"]: row["amount"] for row in reconciliation_report()["approval"]["trace"]}
    # Displayed Gks is already rounded to one decimal; the workbook applies 10%
    # to its underlying value, producing a one-tenth VND display difference.
    assert abs(trace["Gdp"] - (trace["Gks"] * Decimal("0.10"))) <= Decimal("0.1")


def test_missing_price_is_not_zero_but_explicit_approved_zero_is_valid():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()
    item = runtime["work_item_master"]["KS.4/8"]
    item["work_item_norm"][0]["code"] = "NO.PRICE"
    result = engine.calculate_work_item_from_runtime("KS.4/8", runtime)
    assert result["calculation_status"] == "blocked"
    assert result["direct_total"] is None

    runtime = engine.load_runtime_data()
    runtime["resource_price_book"]["KS4_8.CACHED"]["unit_price"] = "0"
    result = engine.calculate_work_item_from_runtime("KS.4/8", runtime)
    assert result["calculation_status"] == "resolved"
    assert result["direct_total"] == Decimal("0.0")


def test_rounding_boundary_zero_quantity_and_recursive_parent_incompleteness():
    engine = CalculationEngineV2()
    assert engine._round_tender_unit_price(Decimal("1999.999")) == Decimal("1000")
    assert engine._round_tender_unit_price(Decimal("2000")) == Decimal("2000")
    runtime = engine.load_runtime_data()
    assert engine.build_project_boq(runtime)["KS.4/8"]["tender_extension"] == 0
    runtime["work_item_master"]["CF.11620"]["missing_dependencies"] = ["resource_price:missing"]
    assert engine.calculate_tender_estimate(runtime)["tender_total"] is None


def test_external_links_are_classified_and_not_in_active_target_closure():
    for dependency in reconciliation_report()["external_dependencies"]:
        assert dependency["affects_j47"] is False
        assert dependency["affects_j29"] is False
        assert dependency["cached_value_available"] is True
        assert dependency["blocker"] is False
