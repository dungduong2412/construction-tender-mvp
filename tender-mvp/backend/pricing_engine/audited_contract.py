"""Audited calculation contract extracted from the source workbook.

This module is the executable companion to ``docs/calculation-spec.yaml``.  It
contains no guessed prices: only formula configuration, workbook targets and
cached values proven by the audit.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


CONTRACT_VERSION = "1.0"
SOURCE_WORKBOOK = "DuToan KS CauBinhGoi 2609.21 DuThau.xls"
UPDATED_BY = "workbook reverse-engineering audit"
UPDATED_AT = "2026-09-29"

CATEGORIES: dict[str, dict[str, Any]] = {
    "topography": {"hsxl_range": "HSXL!A5:D19", "c_base": "labour", "tt_rate": "0", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.10", "lt_rate": "0.02"},
    "waterway_safety": {"hsxl_range": "HSXL!A24:D38", "c_base": "labour", "tt_rate": "0", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.10", "lt_rate": "0.02", "approval_multiplier": "0", "approval_status": "Disabled by source workbook rule"},
    "geotechnical": {"hsxl_range": "HSXL!A43:D57", "c_base": "labour", "tt_rate": "0", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.10", "lt_rate": "0.02"},
    "laboratory": {"hsxl_range": "HSXL!A62:D76", "c_base": "labour", "tt_rate": "0", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.10", "lt_rate": "0", "disabled_components": {"cpa": True}},
    "material_sources_and_disposal": {"hsxl_range": "HSXL!A81:D95", "c_base": "labour", "tt_rate": "0.01", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.08", "lt_rate": "0.02"},
    "traffic_survey": {"hsxl_range": "HSXL!A100:D114", "c_base": "labour", "tt_rate": "0.01", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.08", "lt_rate": "0.02"},
    "gpmb_stake_setting": {"hsxl_range": "HSXL!A119:D133", "c_base": "labour", "tt_rate": "0.03", "c_rate": "0.60", "cpa_rate": "0.015", "cbc_rate": "0.025", "vat_rate": "0.08", "lt_rate": "0.02"},
    "gpmb_marker_production": {"hsxl_range": "HSXL!A138:D152", "c_base": "T", "tt_rate": "0.03", "c_rate": "0.60", "cpa_rate": "0.02", "cbc_rate": "0.03", "vat_rate": "0.08", "lt_rate": "0.02"},
    "road_marker_production": {"hsxl_range": "HSXL!A157:D171", "c_base": "T", "tt_rate": "0.03", "c_rate": "0.60", "cpa_rate": "0.02", "cbc_rate": "0.03", "vat_rate": "0.08", "lt_rate": "0.022"},
}

CATEGORY_ALIASES = {
    "geotechnical_drilling": "geotechnical",
    "gmpb_stake": "gpmb_stake_setting",
    "gmpb_marker": "gpmb_marker_production",
}

TENDER_SECTIONS = [
    {"category": "topography", "cell": "Dự thầu!J22", "amount": Decimal("114297433")},
    {"category": "geotechnical", "cell": "Dự thầu!J30", "amount": Decimal("3047732000")},
    {"category": "laboratory", "cell": "Dự thầu!J46", "amount": Decimal("966348000")},
]

APPROVAL_TRACE = [
    ("T", "Direct cost", "THKP ks duyet", Decimal("2125515983.0")),
    ("GT", "Indirect cost", "THKP ks duyet", Decimal("1151085965.4")),
    ("TL", "Taxable income", "THKP ks duyet", Decimal("196596116.9")),
    ("Cpvks", "Survey service", "THKP ks duyet", Decimal("128423991.5")),
    ("G", "Pre-VAT", "THKP ks duyet", Decimal("3601622056.8")),
    ("VAT", "VAT", "THKP ks duyet", Decimal("360162205.7")),
    ("Gks", "Post-VAT", "THKP ks duyet", Decimal("3961784262.5")),
    ("LT", "Temporary facilities", "THKP ks duyet", Decimal("63444775.5")),
    ("Gdp", "Contingency (10% of Gks)", "THKP ks duyet", Decimal("396178426.3")),
]

TARGETS = {
    "tender": Decimal("4128377433"),
    "approval": Decimal("4421407464"),
    "snapshot_j51": Decimal("4142692903"),
}

EXTERNAL_DEPENDENCIES = [
    {
        "workbook": "[2]Tong hop",
        "formula": "'[2]Tong hop'!D13",
        "affected_cells": ["THKP ks duyet!L32", "THKP ks (1)!L32", "THKP ks (2)!L32", "DuToan GoiThau!G19"],
        "affects_j47": False,
        "affects_j29": False,
        "cached_value_available": True,
        "classification": "CACHED/FROZEN OUTSIDE ACTIVE TARGET CLOSURE",
        "blocker": False,
    },
    {
        "workbook": "[1]Trang_tính2",
        "formula": "'[1]Trang_tính2'!C23",
        "affected_cells": ["Máy!D178", "Máy!D188"],
        "affects_j47": False,
        "affects_j29": False,
        "cached_value_available": True,
        "classification": "CACHED/FROZEN OUTSIDE ACTIVE TARGET CLOSURE",
        "blocker": False,
    },
]


def formula_configuration() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    components = (
        ("C", "c_rate", "overhead"),
        ("TT", "tt_rate", "other indirect"),
        ("TL", None, "taxable income"),
        ("Cpa", "cpa_rate", "survey plan"),
        ("Cbc", "cbc_rate", "survey report"),
        ("VAT", "vat_rate", "VAT"),
        ("LT", "lt_rate", "temporary facilities"),
        ("Gdp", None, "contingency"),
    )
    for category, rule in CATEGORIES.items():
        for branch in ("tender", "approved_estimate"):
            for symbol, rate_key, label in components:
                rate = "0.10" if symbol == "Gdp" and branch == "approved_estimate" else ("0.06" if symbol == "TL" else rule.get(rate_key, "0"))
                disabled = bool(rule.get("disabled_components", {}).get(symbol.lower(), False))
                if branch == "approved_estimate" and rule.get("approval_multiplier") == "0":
                    disabled = True
                rows.append({
                    "branch": branch,
                    "rule_id": f"{CONTRACT_VERSION}:{category}:{symbol}",
                    "category": category,
                    "component": symbol,
                    "label": label,
                    "coefficient": rate,
                    "coefficient_base": rule["c_base"] if symbol == "C" else ("T" if symbol == "TT" else "audited formula base"),
                    "rounding_rule": "ROUNDDOWN to 1,000 VND at tender presentation" if branch == "tender" else "ROUND final to whole VND",
                    "effective_status": "Disabled by source workbook rule" if disabled else "Effective",
                    "source_workbook_reference": rule["hsxl_range"],
                    "last_updated_by": UPDATED_BY,
                    "last_updated_at": UPDATED_AT,
                })
    return rows


def reconciliation_report() -> dict[str, Any]:
    tender_engine = sum(row["amount"] for row in TENDER_SECTIONS)
    approval_unrounded = APPROVAL_TRACE[6][3] + APPROVAL_TRACE[7][3] + APPROVAL_TRACE[8][3]
    approval_engine = approval_unrounded.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {
        "contract_version": CONTRACT_VERSION,
        "source_workbook": SOURCE_WORKBOOK,
        "tender": {
            "target_cell": "Dự thầu!J47",
            "workbook_amount": TARGETS["tender"],
            "engine_amount": tender_engine,
            "delta": tender_engine - TARGETS["tender"],
            "status": "EXACT" if tender_engine == TARGETS["tender"] else "MISMATCH",
            "formula": "J22 + J30 + J46",
            "rounding": "billable unit prices ROUNDDOWN to 1,000 VND before quantity extension",
            "sections": TENDER_SECTIONS,
        },
        "approval": {
            "target_cell": "THKP ks duyet!J29",
            "control_cell": "THKP ks duyet!O29",
            "workbook_amount": TARGETS["approval"],
            "engine_amount": approval_engine,
            "unrounded_amount": approval_unrounded,
            "delta": approval_engine - TARGETS["approval"],
            "status": "EXACT" if approval_engine == TARGETS["approval"] else "MISMATCH",
            "aggregation": "aggregate-first",
            "rounding": "ROUND(Gks + LT + Gdp, 0)",
            "trace": [{"symbol": s, "label": l, "source": src, "amount": amount} for s, l, src, amount in APPROVAL_TRACE],
        },
        "j51": {
            "cell": "Dự thầu!J51",
            "amount": TARGETS["snapshot_j51"],
            "status": "REFERENCE ONLY — NOT ENGINE TARGET",
            "description": "Historical / approved snapshot from source workbook — provenance not established",
        },
        "external_dependencies": EXTERNAL_DEPENDENCIES,
    }
