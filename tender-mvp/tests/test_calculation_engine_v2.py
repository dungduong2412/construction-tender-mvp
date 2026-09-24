import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from pricing_engine.calculation_engine_v2 import CalculationEngineV2, load_golden_fixture


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "docs" / "golden_calculation_v2.json"


def test_golden_fixtures_match_documented_representative_items():
    fixture = load_golden_fixture(FIXTURE_PATH)
    engine = CalculationEngineV2()

    for item in fixture["representative_items"]:
        row = engine.calculate_work_item(item)
        expected = item["expected"]
        assert row["direct_material_total"] == Decimal(expected["direct_material_total"])
        assert row["direct_labour_total"] == Decimal(expected["direct_labour_total"])
        assert row["direct_machine_total"] == Decimal(expected["direct_machine_total"])
        assert row["direct_total"] == Decimal(expected["direct_total"])
        assert row["loaded_unit_price"] == Decimal(expected["loaded_unit_price"])
        assert row["variances"]["calc_vs_spec"] == Decimal("0")


def test_mutation_acceptance_gate_for_material_labour_machine_quantity_and_hsxl():
    engine = CalculationEngineV2()
    base = {
        "work_item": "CF.11620",
        "category": "topography",
        "input": {
            "direct_material_total": "34642.1",
            "direct_labour_total": "1852359.6",
            "direct_machine_total": "80827.6",
            "direct_total": "1967829.3",
            "base_direct_total": "1967829.3",
            "hsxl_coefficient": "1.0",
        },
        "expected": {"loaded_unit_price": "3808696"},
    }

    material_mutation = {
        **base,
        "input": {
            **base["input"],
            "direct_material_total": "39642.1",
            "direct_total": "2017829.3",
            "base_direct_total": "1967829.3",
            "mutation": {"component": "material", "delta": "5000.0"},
        },
    }
    labour_mutation = {
        **base,
        "input": {
            **base["input"],
            "direct_labour_total": "1902359.6",
            "direct_total": "2017829.3",
            "base_direct_total": "1967829.3",
            "mutation": {"component": "labour", "delta": "50000.0"},
        },
    }
    machine_mutation = {
        **base,
        "input": {
            **base["input"],
            "direct_machine_total": "130827.6",
            "direct_total": "2067829.3",
            "base_direct_total": "1967829.3",
            "mutation": {"component": "machine", "delta": "50000.0"},
        },
    }
    quantity_mutation = {
        **base,
        "input": {
            **base["input"],
            "direct_total": "2167829.3",
            "base_direct_total": "1967829.3",
            "mutation": {"component": "quantity", "delta": "200000.0"},
        },
    }
    hsxl_mutation = {
        **base,
        "input": {
            **base["input"],
            "hsxl_coefficient": "1.05",
            "mutation": {"component": "hsxl", "delta": "0.05"},
        },
    }

    material_result = engine.calculate_work_item(material_mutation)
    labour_result = engine.calculate_work_item(labour_mutation)
    machine_result = engine.calculate_work_item(machine_mutation)
    quantity_result = engine.calculate_work_item(quantity_mutation)
    hsxl_result = engine.calculate_work_item(hsxl_mutation)

    assert material_result["loaded_unit_price"] > Decimal("3808696")
    assert labour_result["loaded_unit_price"] > Decimal("3808696")
    assert machine_result["loaded_unit_price"] > Decimal("3808696")
    assert quantity_result["loaded_unit_price"] > Decimal("3808696")
    assert hsxl_result["loaded_unit_price"] > Decimal("3808696")

    assert material_result["direct_labour_total"] == Decimal("1852359.6")
    assert labour_result["direct_material_total"] == Decimal("34642.1")
    assert machine_result["direct_labour_total"] == Decimal("1852359.6")
    assert quantity_result["direct_material_total"] == Decimal("34642.1")
    assert hsxl_result["direct_total"] == Decimal("1967829.3")


def test_workbook_total_reconciliation_tracks_snapshot_not_target():
    fixture = load_golden_fixture(FIXTURE_PATH)
    report = CalculationEngineV2().reconcile_workbook_totals(fixture["workbook_totals"])

    assert report["approved_estimate_total"] == Decimal("4421407464")
    assert report["current_tender_total"] == Decimal("4128377433")
    assert report["snapshot_literal_total"] == Decimal("4142692903")
    assert report["snapshot_vs_live_variance"] == Decimal("14315470")
    assert report["approved_vs_snapshot_variance"] == Decimal("278714561")
    assert report["current_tender_is_target"] is True
    assert report["snapshot_is_unlinked_literal"] is True
