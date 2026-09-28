"""Immutable project calculation snapshots built from reviewed backend data."""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import BOQRow, Job, MappingResult, MasterItem, Override, RowType
from formula_config import apply_version_to_runtime, approved_version
from pricing_availability import NOT_APPLICABLE, classify_price, display_price_state, price_freshness
from pricing_engine.aggregation import build_recursive_component_tree, build_recursive_money_tree
from pricing_engine.calculation_engine_v2 import CalculationEngineV2


ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = Path(os.getenv("CALCULATION_SNAPSHOT_DIR", ROOT / "runtime" / "calculation_snapshots"))


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(_json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _persist(snapshot: dict[str, Any]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{snapshot['snapshot_id']}.json"
    if not path.exists():
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / f"{snapshot_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


async def build_snapshot(db: AsyncSession, job_id: str) -> dict[str, Any]:
    job = await db.get(Job, job_id)
    if not job:
        raise KeyError(job_id)
    rows = list((await db.execute(select(BOQRow).where(BOQRow.job_id == job_id).order_by(BOQRow.doc_order))).scalars())
    row_ids = [row.id for row in rows]
    mappings = list((await db.execute(select(MappingResult).where(MappingResult.boq_row_id.in_(row_ids)))).scalars()) if row_ids else []
    mapping_map = {mapping.boq_row_id: mapping for mapping in mappings}
    master_ids = [mapping.master_item_id for mapping in mappings if mapping.master_item_id]
    masters = list((await db.execute(select(MasterItem).where(MasterItem.id.in_(master_ids)))).scalars()) if master_ids else []
    master_map = {master.id: master for master in masters}
    overrides = list((await db.execute(select(Override).where(Override.job_id == job_id).order_by(Override.id))).scalars())
    override_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for override in overrides:
        override_map[override.row_id].append({
            "field": override.field,
            "old_value": override.old_value,
            "new_value": override.new_value,
            "user": override.user,
            "created_at": override.created_at.isoformat() if override.created_at else None,
        })

    version = approved_version()
    engine = CalculationEngineV2()
    base_runtime = engine.load_runtime_data()
    runtime_items = engine.build_work_item_master(base_runtime)
    selected_runtime = deepcopy(base_runtime)
    selected_runtime["work_item_master"] = {}
    runtime_quantities: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    calculation_rows: list[dict[str, Any]] = []
    tender_leaves: list[dict[str, Any]] = []
    approval_leaves: list[dict[str, Any]] = []
    approval_group_categories: dict[str, str] = {}
    mapped_count = priced_count = 0

    for row in rows:
        mapping = mapping_map.get(row.id)
        master = master_map.get(mapping.master_item_id) if mapping and mapping.master_item_id else None
        status = mapping.status.value if mapping else "mapping_unresolved"
        is_billable = row.row_type == RowType.line_item
        is_mapped = bool(is_billable and master)
        source_reference = ((mapping.price_source_reference if mapping else None)
                            or (master.price_source_reference if master else None)
                            or (master.source_sheet if master else None))
        availability = classify_price(
            mapping.unit_price_str if mapping else None,
            source_reference=source_reference,
            approval_status="approved" if mapping and mapping.pricing_availability == "authorized_zero" else (master.approval_status if master else None),
            approved_by=(mapping.price_last_updated_by if mapping and mapping.pricing_availability == "authorized_zero" else (master.approved_by if master else None)),
            zero_price_authorized=bool(mapping and mapping.pricing_availability == "authorized_zero"),
        )
        tender_amount = _decimal(mapping.extended_amount_str) if mapping and availability.available else None
        price_review_required = bool(mapping and mapping.price_review_required)
        is_priced = bool(is_billable and status == "mapped_and_priced" and availability.available
                         and tender_amount is not None and not price_review_required)
        if is_mapped:
            mapped_count += 1
        if is_priced:
            priced_count += 1
        if is_billable:
            tender_leaves.append({
                "row_id": row.row_id, "label": row.description_vi, "path": row.section_path,
                "amount": tender_amount, "available": is_priced,
                "availability_status": "review_required" if price_review_required else availability.status,
            })

        code = master.item_code if master else None
        runtime_detail = None
        evidence_conflicts: list[str] = []
        approval_row_available = False
        approval_components: dict[str, dict[str, Decimal]] = {}
        if is_billable and code in runtime_items:
            quantity = _decimal(row.quantity)
            if quantity is not None:
                runtime_quantities[code] += quantity
            result = engine.calculate_work_item_from_runtime(code, base_runtime)
            runtime_detail = {
                "calculation_status": result.get("calculation_status"),
                "approval_group": runtime_items[code].get("approval_rule_group") or runtime_items[code].get("category"),
                "direct_material_unit": result.get("direct_material_total"),
                "direct_labour_unit": result.get("direct_labour_total"),
                "direct_machine_unit": result.get("direct_machine_total"),
                "resource_trace": result.get("trace"),
                "source_cells": result.get("source_cells"),
                "missing_dependencies": result.get("missing_dependencies"),
            }
            evidence_conflicts.extend(result.get("missing_dependencies") or [])
            if result.get("calculation_status") == "resolved" and quantity is not None:
                group = runtime_detail["approval_group"] or "default"
                approval_group_categories[group] = str(runtime_items[code].get("category") or "default")
                approval_components[group] = {
                    "material": _decimal(result.get("direct_material_total")) * quantity,
                    "labour": _decimal(result.get("direct_labour_total")) * quantity,
                    "machine": _decimal(result.get("direct_machine_total")) * quantity,
                }
                approval_row_available = True
            elif quantity is None:
                evidence_conflicts.append("quantity_unavailable")
        elif is_billable:
            evidence_conflicts.append("approval_resource_evidence_unavailable")
        if is_billable and not is_priced:
            evidence_conflicts.append(
                "master_price_changed_review_required" if price_review_required
                else (mapping.unresolved_reason if mapping and mapping.unresolved_reason else "mandatory_tender_price_unresolved")
            )
        if is_billable:
            approval_leaves.append({
                "row_id": row.row_id, "label": row.description_vi, "path": row.section_path,
                "available": approval_row_available, "components_by_group": approval_components,
            })

        calculation_rows.append(_json_safe({
            "row_id": row.row_id,
            "row_number": row.row_number,
            "doc_order": row.doc_order,
            "row_type": row.row_type.value,
            "section": row.section_path,
            "description": row.description_vi,
            "unit": row.unit_raw,
            "quantity_raw": row.quantity_raw,
            "quantity": row.quantity,
            "source_page": row.page,
            "source_region": row.region,
            "source_origin": row.source_origin,
            "source_provenance": row.source_provenance,
            "azure_polygon_available": row.azure_polygon_available,
            "mapping_status": status,
            "mapped_by": mapping.mapped_by if mapping else None,
            "mapping_last_updated_by": mapping.mapping_last_updated_by if mapping else None,
            "mapping_last_updated_at": mapping.mapping_last_updated_at.isoformat() if mapping and mapping.mapping_last_updated_at else None,
            "mapped_work_item": code,
            "master_description": master.description_vi if master else None,
            "conversion_rule": str(mapping.unit_rule_id) if mapping and mapping.unit_rule_id else None,
            "tender_unit_price": mapping.unit_price_str if mapping else None,
            "tender_amount": tender_amount,
            "pricing_available": is_priced,
            "pricing_availability": (NOT_APPLICABLE if not is_billable else
                                     ("review_required" if price_review_required else availability.status)),
            "price_display": ("Not applicable" if not is_billable else
                              display_price_state(mapping.unit_price_str if mapping else None, availability.status)),
            "price_applicability": "required" if is_billable else NOT_APPLICABLE,
            "unit_price_editable": is_billable,
            "price_freshness": price_freshness(
                (mapping.price_effective_date if mapping else None) or (master.price_effective_date if master else None),
                (mapping.price_expiry_date if mapping else None) or (master.price_expiry_date if master else None),
                available=availability.available,
            ),
            "price_effective_date": (mapping.price_effective_date if mapping else None) or (master.price_effective_date if master else None),
            "price_expiry_date": (mapping.price_expiry_date if mapping else None) or (master.price_expiry_date if master else None),
            "price_source_reference": source_reference,
            "price_last_updated_by": (mapping.price_last_updated_by if mapping and mapping.price_source == "user_override"
                                      else (master.last_updated_by if master else (mapping.price_last_updated_by if mapping else None))),
            "price_last_updated_at": (mapping.price_last_updated_at.isoformat() if mapping and mapping.price_source == "user_override" and mapping.price_last_updated_at
                                      else (master.last_updated_at.isoformat() if master and master.last_updated_at
                                      else (mapping.price_last_updated_at.isoformat() if mapping and mapping.price_last_updated_at else None))),
            "price_change_pending_review": price_review_required,
            "tender_formula_ref": mapping.formula_ref if mapping else None,
            "price_source": mapping.price_source if mapping else None,
            "master_version": mapping.master_version if mapping else None,
            "approval_detail": runtime_detail,
            "evidence_conflicts": [value for value in evidence_conflicts if value],
            "review_history": override_map.get(row.row_id, []),
        }))

    for code, quantity in runtime_quantities.items():
        selected_runtime["work_item_master"][code] = deepcopy(runtime_items[code])
        selected_runtime["work_item_master"][code]["project_quantity"] = str(quantity)
    selected_runtime = apply_version_to_runtime(selected_runtime, version)
    tender_v2 = engine.calculate_tender_estimate(selected_runtime) if selected_runtime["work_item_master"] else {
        "status": "INCOMPLETE", "tender_partial_subtotal": Decimal("0"), "tender_total": None,
        "blocked_items": [], "blocked_item_details": []
    }
    approval_v2 = engine.calculate_approval_estimate(selected_runtime) if selected_runtime["work_item_master"] else {
        "status": "INCOMPLETE", "approved_estimate_partial_subtotal": Decimal("0"), "approved_estimate_total": None,
        "approval_group_components": {}, "category_components": {}, "blocked_items": [], "blocked_item_details": []
    }

    def approval_group_total(group: str, components: dict[str, Decimal]) -> Decimal:
        rules = engine.approval_rules_for(
            approval_group_categories.get(group, "default"),
            runtime=selected_runtime,
            approval_group=group,
        )
        return engine._compute_loaded_components(
            components["material"], components["labour"], components["machine"], rules,
        )["FINAL"]

    tender_hierarchy = build_recursive_money_tree(tender_leaves, branch="tender", rounding_quantum="1")
    approval_hierarchy = build_recursive_component_tree(
        approval_leaves, group_calculator=approval_group_total, rounding_quantum="1",
    )
    billable_count = sum(row.row_type == RowType.line_item for row in rows)
    non_billable_count = len(rows) - billable_count
    mandatory_unresolved = billable_count - priced_count
    approval_covered = sum(
        1 for item in calculation_rows
        if item["row_type"] == "line_item" and item["approval_detail"] and item["approval_detail"]["calculation_status"] == "resolved"
    )
    approval_unresolved = billable_count - approval_covered
    tender_partial = tender_hierarchy["partial_subtotal"]
    approval_partial = approval_hierarchy["partial_subtotal"]

    input_payload = {
        "job": {"id": job.id, "filename": job.filename, "status": job.status.value},
        "rows": calculation_rows,
        "formula_version": version["version_id"],
    }
    input_hash = _canonical_hash(input_payload)
    snapshot_id = f"calc-{input_hash[:20]}"
    existing = load_snapshot(snapshot_id)
    if existing:
        return existing

    snapshot = _json_safe({
        "snapshot_id": snapshot_id,
        "input_hash": input_hash,
        "immutable": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "job": input_payload["job"],
        "formula_version": version,
        "master_version": sorted({item.get("master_version") for item in calculation_rows if item.get("master_version")}),
        "counts": {
            "source_rows": len(rows),
            "billable": billable_count,
            "non_billable": non_billable_count,
            "structural": non_billable_count,
            "mapped": mapped_count,
            "priced": priced_count,
            "pricing_available": priced_count,
            "pricing_not_available": mandatory_unresolved,
            "mandatory_unresolved": mandatory_unresolved,
            "approval_evidence_covered": approval_covered,
            "approval_evidence_unresolved": approval_unresolved,
        },
        "tender": {
            "method": "reviewed row pricing from the validated legacy pricing engine",
            "partial_subtotal": tender_partial,
            "official_total": tender_hierarchy["official_total"],
            "status": tender_hierarchy["status"],
            "unresolved_descendants": tender_hierarchy["unresolved_descendants"],
            "hierarchy": tender_hierarchy,
            "runtime_cross_check": tender_v2,
        },
        "approval": {
            "method": "CalculationEngineV2 aggregate-first by approval group",
            "partial_subtotal": approval_partial,
            "official_total": approval_hierarchy["official_total"],
            "status": approval_hierarchy["status"],
            "unresolved_descendants": approval_hierarchy["unresolved_descendants"],
            "hierarchy": approval_hierarchy,
            "group_components": approval_hierarchy.get("components_by_group", {}),
            "category_components": approval_v2.get("category_components", {}),
            "blocked_items": approval_v2.get("blocked_item_details", []),
        },
        "rows": calculation_rows,
        "unresolved_register": [
            {"row_id": item["row_id"], "row_number": item["row_number"], "description": item["description"], "conflicts": item["evidence_conflicts"]}
            for item in calculation_rows if item["row_type"] == "line_item" and item["evidence_conflicts"]
        ],
        "export_policy": {
            "internal_draft_allowed": True,
            "final_submission_allowed": mandatory_unresolved == 0 and approval_unresolved == 0,
            "final_block_reasons": [
                *([f"{mandatory_unresolved} mandatory billable rows lack tender pricing"] if mandatory_unresolved else []),
                *([f"{approval_unresolved} billable rows lack approval resource evidence"] if approval_unresolved else []),
            ],
        },
    })
    _persist(snapshot)
    return snapshot
