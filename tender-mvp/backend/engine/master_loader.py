"""
Master Data Loader
==================
Loads the versioned JSON master dataset into memory.
The JSON file is read once at startup (or on first request).
The external Excel workbook is NOT re-parsed on every upload.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List

from ..models.domain import MasterItem, UnitRule

_SEEDS_DIR = Path(__file__).parent.parent / "seeds"
_MASTER_FILE = _SEEDS_DIR / "master_data_v1.json"


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    with open(_MASTER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_master_items() -> List[MasterItem]:
    raw = _load_raw()
    return [MasterItem(**item) for item in raw["items"]]


def load_unit_rules() -> List[UnitRule]:
    raw = _load_raw()
    return [UnitRule(**r) for r in raw.get("unit_rules", [])]


def get_master_version() -> str:
    return _load_raw().get("version", "unknown")


def get_unit_conversion(from_unit: str, to_unit: str) -> float | None:
    """
    Return the conversion factor to go from from_unit to to_unit.
    Returns None if no approved rule exists.
    Unit normalisation NEVER silently conflates different units.
    """
    rules = load_unit_rules()
    from_norm = from_unit.strip().lower()
    to_norm = to_unit.strip().lower()

    if from_norm == to_norm:
        return 1.0

    for rule in rules:
        if rule.from_unit.lower() == from_norm and rule.to_unit.lower() == to_norm:
            return rule.factor
    return None
