"""Recursive parent-child aggregation for tender and approval branches."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round(value: Decimal, quantum: str) -> Decimal:
    return value.quantize(Decimal(quantum), rounding=ROUND_HALF_UP)


def path_parts(path: str | None) -> list[str]:
    value = str(path or "Unsectioned").strip()
    for separator in (" > ", " / ", "|"):
        if separator in value:
            return [part.strip() for part in value.split(separator) if part.strip()]
    return [value or "Unsectioned"]


def build_recursive_money_tree(
    leaves: list[dict[str, Any]],
    *,
    branch: str,
    rounding_quantum: str = "1",
) -> dict[str, Any]:
    """Aggregate leaf monetary amounts recursively without treating NULL as zero."""
    root: dict[str, Any] = {"name": "Project", "kind": "project", "children": {}}
    for leaf in leaves:
        node = root
        for part in path_parts(leaf.get("path")):
            node = node["children"].setdefault(part, {"name": part, "kind": "group", "children": {}})
        key = str(leaf.get("row_id"))
        node["children"][key] = {
            "name": str(leaf.get("label") or key),
            "kind": "row",
            "row_id": key,
            "amount": leaf.get("amount"),
            "available": bool(leaf.get("available")),
            "availability_status": leaf.get("availability_status"),
            "children": {},
        }

    def calculate(node: dict[str, Any], depth: int) -> dict[str, Any]:
        children = [calculate(child, depth + 1) for child in node.get("children", {}).values()]
        if node["kind"] == "row":
            amount = _d(node["amount"]) if node["available"] and node.get("amount") is not None else None
            return {
                **{key: value for key, value in node.items() if key != "children"},
                "depth": depth,
                "partial_subtotal": amount,
                "official_total": amount,
                "status": "COMPLETE" if node["available"] else "INCOMPLETE",
                "unresolved_descendants": 0 if node["available"] else 1,
                "children": [],
            }
        available_values = [child["partial_subtotal"] for child in children if child["partial_subtotal"] is not None]
        partial = _round(sum(available_values, Decimal("0")), rounding_quantum) if available_values else None
        unresolved = sum(int(child["unresolved_descendants"]) for child in children)
        complete = unresolved == 0
        return {
            "name": node["name"], "kind": node["kind"], "branch": branch, "depth": depth,
            "partial_subtotal": partial,
            "official_total": partial if complete else None,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "unresolved_descendants": unresolved,
            "children": children,
        }

    return calculate(root, 0)


def build_recursive_component_tree(
    leaves: list[dict[str, Any]],
    *,
    group_calculator: Callable[[str, dict[str, Decimal]], Decimal],
    rounding_quantum: str = "1",
) -> dict[str, Any]:
    """Aggregate child resources first, then calculate approval totals by group."""
    root: dict[str, Any] = {"name": "Project", "kind": "project", "children": {}}
    for leaf in leaves:
        node = root
        for part in path_parts(leaf.get("path")):
            node = node["children"].setdefault(part, {"name": part, "kind": "group", "children": {}})
        key = str(leaf.get("row_id"))
        node["children"][key] = {
            "name": str(leaf.get("label") or key), "kind": "row", "row_id": key,
            "available": bool(leaf.get("available")), "components_by_group": deepcopy(leaf.get("components_by_group") or {}),
            "children": {},
        }

    def calculate(node: dict[str, Any], depth: int) -> dict[str, Any]:
        children = [calculate(child, depth + 1) for child in node.get("children", {}).values()]
        if node["kind"] == "row":
            groups = {
                group: {component: _d(value) for component, value in values.items()}
                for group, values in node.get("components_by_group", {}).items()
            } if node["available"] else {}
            unresolved = 0 if node["available"] else 1
        else:
            groups: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"material": Decimal("0"), "labour": Decimal("0"), "machine": Decimal("0")})
            for child in children:
                for group, values in child["components_by_group"].items():
                    for component in ("material", "labour", "machine"):
                        groups[group][component] += _d(values.get(component, 0))
            groups = dict(groups)
            unresolved = sum(int(child["unresolved_descendants"]) for child in children)
        group_totals = {group: _round(group_calculator(group, values), rounding_quantum) for group, values in groups.items()}
        partial = _round(sum(group_totals.values(), Decimal("0")), rounding_quantum) if group_totals else None
        complete = unresolved == 0
        return {
            "name": node["name"], "kind": node["kind"], "branch": "approval", "depth": depth,
            "partial_subtotal": partial, "official_total": partial if complete else None,
            "status": "COMPLETE" if complete else "INCOMPLETE", "unresolved_descendants": unresolved,
            "components_by_group": groups, "group_totals": group_totals, "children": children,
        }

    return calculate(root, 0)
