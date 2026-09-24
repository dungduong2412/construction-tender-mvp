import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from pricing_engine.calculation_engine_v2 import CalculationEngineV2, load_golden_fixture


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "docs" / "golden_calculation_v2.json"

EXPECTED_RUNTIME_ITEMS = {
    "CF.11620": {
        "direct_material_total": Decimal("34642.1"),
        "direct_labour_total": Decimal("1852359.6"),
        "direct_machine_total": Decimal("80827.6"),
        "direct_total": Decimal("1967829.3"),
        "loaded_unit_price": Decimal("3808696"),
        "provenance_status": "accepted",
    },
    "CC.21310": {
        "direct_material_total": Decimal("38703.5"),
        "direct_labour_total": Decimal("683941.7"),
        "direct_machine_total": Decimal("10428.8"),
        "direct_total": Decimal("733074.0"),
        "loaded_unit_price": Decimal("1414311"),
        "provenance_status": "accepted",
    },
    "DC.02001": {
        "direct_material_total": Decimal("42775.0"),
        "direct_labour_total": Decimal("289379.9"),
        "direct_machine_total": Decimal("25370.1"),
        "direct_total": Decimal("357525.0"),
        "loaded_unit_price": Decimal("634808"),
        "provenance_status": "accepted",
    },
    "KS.4/8": {
        "direct_material_total": Decimal("0.0"),
        "direct_labour_total": Decimal("0.0"),
        "direct_machine_total": Decimal("0.0"),
        "direct_total": None,
        "loaded_unit_price": None,
        "provenance_status": "blocked",
    },
    "CF.21120": {
        "direct_material_total": Decimal("60078.5"),
        "direct_labour_total": Decimal("978002.2"),
        "direct_machine_total": Decimal("27500.0"),
        "direct_total": Decimal("1065580.7"),
        "loaded_unit_price": Decimal("2045481"),
        "provenance_status": "accepted",
    },
    "AG.11112": {
        "direct_material_total": Decimal("981729.4"),
        "direct_labour_total": Decimal("364303.6"),
        "direct_machine_total": Decimal("114636.6"),
        "direct_total": Decimal("1460669.6"),
        "loaded_unit_price": Decimal("2919165"),
        "provenance_status": "accepted",
    },
}


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


def test_runtime_data_model_resolves_all_audited_items_and_coverage_report():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    for code, expected in EXPECTED_RUNTIME_ITEMS.items():
        result = engine.calculate_work_item_from_runtime(code, runtime)
        assert result["work_item_code"] == code
        assert result["direct_material_total"] == expected["direct_material_total"]
        assert result["direct_labour_total"] == expected["direct_labour_total"]
        assert result["direct_machine_total"] == expected["direct_machine_total"]
        assert result["direct_total"] == expected["direct_total"]
        assert result["loaded_unit_price"] == expected["loaded_unit_price"]
        if code == "KS.4/8":
            assert result["calculation_status"] == "blocked"
        else:
            assert result["calculation_status"] == "resolved"
        if code == "KS.4/8":
            assert any(dep.endswith("UNRESOLVED.KS4_8.LABOUR") for dep in result["missing_dependencies"])
            assert result["direct_total_parity"] is None
            assert result["loaded_unit_price_parity"] is None
        else:
            assert result["missing_dependencies"] == []
            assert result["direct_total_parity"] == Decimal("0")
            assert result["loaded_unit_price_parity"] == Decimal("0")
            assert result["components"]["T"] == expected["direct_total"]

    coverage = engine.coverage_report(runtime)
    assert coverage["resolved_items"] == 5
    assert coverage["item_count"] == 6
    assert coverage["snapshot_is_unlinked_literal"] is True
    assert any(entry.startswith("KS.4/8:") and entry.endswith("UNRESOLVED.KS4_8.LABOUR") for entry in coverage["missing_dependencies"])
    assert coverage["full_project_coverage"] is False


def test_cf_11620_source_provenance_and_runtime_mutation_gate():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    provenance = engine.provenance_report("CF.11620", runtime)
    assert provenance["work_item_code"] == "CF.11620"
    assert provenance["status"] == "accepted"
    assert all(item["classification"] != "ASSUMED" for item in provenance["items"])
    assert any(item["element"] == "material_total" and item["classification"] == "SOURCE_VERIFIED" for item in provenance["items"])
    assert any(item["element"] == "material.Z999" and item["classification"] == "FORMULA_DERIVED" for item in provenance["items"])
    assert "golden_calculation_v2.json" not in str(runtime)

    mutation = engine.runtime_mutation_report("CF.11620", runtime)
    assert mutation["baseline"]["loaded_unit_price"] == Decimal("3808696")
    assert mutation["material_up_10pct"]["direct_material_total"] > Decimal("34642.1")
    assert mutation["labour_up_10pct"]["direct_labour_total"] > Decimal("1852359.6")
    assert mutation["machine_up_10pct"]["direct_machine_total"] > Decimal("80827.6")
    assert mutation["quantity_8_to_10"]["project_quantity"] == Decimal("10")
    assert mutation["hsxl_10pct"]["loaded_unit_price"] > Decimal("3808696")

    baseline = engine.calculate_work_item_from_runtime("CF.11620", runtime)
    mutated = engine.calculate_work_item_from_runtime("CF.11620", engine.apply_runtime_mutation(runtime, {"material_price_factor": 1.10}))
    assert baseline["direct_material_total"] != mutated["direct_material_total"]


def test_runtime_provenance_status_for_all_six_items():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    for code, expected in EXPECTED_RUNTIME_ITEMS.items():
        provenance = engine.provenance_report(code, runtime)
        assert provenance["work_item_code"] == code
        assert provenance["status"] == expected["provenance_status"]
        assert all(item["classification"] != "ASSUMED" for item in provenance["items"])


def test_runtime_mutations_preserve_unaffected_components_on_other_items():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    for code in ["CC.21310", "DC.02001", "CF.21120", "AG.11112"]:
        baseline = engine.calculate_work_item_from_runtime(code, runtime)
        mat_mut = engine.calculate_work_item_from_runtime(
            code,
            engine.apply_runtime_mutation(runtime, {"work_item_code": code, "material_price_factor": 1.10}),
        )
        lab_mut = engine.calculate_work_item_from_runtime(
            code,
            engine.apply_runtime_mutation(runtime, {"work_item_code": code, "labour_rate_factor": 1.10}),
        )
        mac_mut = engine.calculate_work_item_from_runtime(
            code,
            engine.apply_runtime_mutation(runtime, {"work_item_code": code, "machine_rate_factor": 1.10}),
        )

        assert mat_mut["direct_material_total"] > baseline["direct_material_total"]
        assert mat_mut["direct_labour_total"] == baseline["direct_labour_total"]
        assert mat_mut["direct_machine_total"] == baseline["direct_machine_total"]

        assert lab_mut["direct_labour_total"] > baseline["direct_labour_total"]
        assert lab_mut["direct_material_total"] == baseline["direct_material_total"]
        assert lab_mut["direct_machine_total"] == baseline["direct_machine_total"]

        assert mac_mut["direct_machine_total"] > baseline["direct_machine_total"]
        assert mac_mut["direct_material_total"] == baseline["direct_material_total"]
        assert mac_mut["direct_labour_total"] == baseline["direct_labour_total"]


def test_shared_cement_price_change_recalculates_cf11620_and_cf21120_only():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    cf_base = engine.calculate_work_item_from_runtime("CF.11620", runtime)
    cf21120_base = engine.calculate_work_item_from_runtime("CF.21120", runtime)
    cc_base = engine.calculate_work_item_from_runtime("CC.21310", runtime)

    # Keep recipes and cached workbook expected values untouched; mutate only price-book cement.
    mutated = engine.apply_runtime_mutation(
        runtime,
        {
            "work_item_code": "CF.11620",
            "resource_price_updates": {"A28.0341": "2000"},
        },
    )

    cf_mut = engine.calculate_work_item_from_runtime("CF.11620", mutated)
    cf21120_mut = engine.calculate_work_item_from_runtime("CF.21120", mutated)
    cc_mut = engine.calculate_work_item_from_runtime("CC.21310", mutated)

    assert cf_mut["loaded_unit_price"] != cf_base["loaded_unit_price"]
    assert cf21120_mut["loaded_unit_price"] != cf21120_base["loaded_unit_price"]
    assert cc_mut["loaded_unit_price"] == cc_base["loaded_unit_price"]

    base_recipe = runtime["work_item_master"]["CF.11620"]["resource_recipe"]
    mutated_recipe = mutated["work_item_master"]["CF.11620"]["resource_recipe"]
    assert base_recipe == mutated_recipe


def test_project_quantity_changes_extension_not_unit_price():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    base = engine.calculate_work_item_from_runtime("CF.11620", runtime)
    mutated_runtime = engine.apply_runtime_mutation(runtime, {"work_item_code": "CF.11620", "quantity": 10})
    mutated = engine.calculate_work_item_from_runtime("CF.11620", mutated_runtime)

    assert mutated["loaded_unit_price"] == base["loaded_unit_price"]

    base_tender = engine.calculate_tender_estimate(runtime)
    mut_tender = engine.calculate_tender_estimate(mutated_runtime)
    assert mut_tender["tender_total"] != base_tender["tender_total"]


def test_hsxl_edits_change_component_bases_not_generic_multiplier():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    base = engine.calculate_work_item_from_runtime("CF.11620", runtime)
    mutated_runtime = engine.apply_runtime_mutation(
        runtime,
        {
            "work_item_code": "CF.11620",
            "hsxl_rules": {"c_rate": "0.66"},
        },
    )
    mutated = engine.calculate_work_item_from_runtime("CF.11620", mutated_runtime)

    assert mutated["direct_total"] == base["direct_total"]
    assert mutated["components"]["C"] > base["components"]["C"]
    assert mutated["loaded_unit_price"] > base["loaded_unit_price"]


def test_aggregate_first_approval_and_unit_first_tender_use_fresh_calculations():
    engine = CalculationEngineV2()
    runtime = engine.load_runtime_data()

    approval = engine.calculate_approval_estimate(runtime)
    tender = engine.calculate_tender_estimate(runtime)

    assert approval["approved_estimate_total"] > Decimal("0")
    assert tender["tender_total"] > Decimal("0")
    assert "KS.4/8" in approval["blocked_items"]
    assert "KS.4/8" in tender["blocked_items"]

    mutated_runtime = engine.apply_runtime_mutation(
        runtime,
        {
            "work_item_code": "CF.11620",
            "resource_price_updates": {"A28.0341": "2200"},
        },
    )
    approval_mut = engine.calculate_approval_estimate(mutated_runtime)
    tender_mut = engine.calculate_tender_estimate(mutated_runtime)

    assert approval_mut["approved_estimate_total"] != approval["approved_estimate_total"]
    assert tender_mut["tender_total"] != tender["tender_total"]
