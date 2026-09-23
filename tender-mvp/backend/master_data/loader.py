"""
Master data loader — reads JSON seed files and upserts into SQLite at startup.
One-time, idempotent: uses (version, item_code) as the natural key.
"""
import json
import os
from pathlib import Path

from sqlalchemy import select

from database import AsyncSessionLocal, Coefficient, MasterItem, UnitRule

MASTER_DATA_DIR = Path(__file__).parent.parent.parent / "master-data"
VERSION = os.getenv("MASTER_DATA_VERSION", "v1")
TENANT_ID = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")


async def load_master_data() -> None:
    async with AsyncSessionLocal() as session:
        await _load_items(session)
        await _load_unit_rules(session)
        await _load_coefficients(session)
        await session.commit()
    print("[master_data] Seed loaded successfully.")


async def _load_items(session) -> None:
    path = MASTER_DATA_DIR / f"items_{VERSION}.json"
    if not path.exists():
        print(f"[master_data] WARNING: {path} not found; skipping items seed.")
        return
    items = json.loads(path.read_text(encoding="utf-8"))
    for item in items:
        existing = await session.scalar(
            select(MasterItem).where(
                MasterItem.version == item["version"],
                MasterItem.item_code == item["item_code"],
                MasterItem.tenant_id == TENANT_ID,
            )
        )
        if existing is None:
            session.add(
                MasterItem(
                    tenant_id=TENANT_ID,
                    version=item["version"],
                    item_code=item["item_code"],
                    description_vi=item["description_vi"],
                    unit=item["unit"],
                    unit_price=float(item["unit_price"]),
                    formula_ref=item.get("formula_ref"),
                    source_sheet=item.get("source_sheet"),
                    tags_json=json.dumps(item.get("tags", {}), ensure_ascii=False),
                )
            )


async def _load_unit_rules(session) -> None:
    path = MASTER_DATA_DIR / f"unit_rules_{VERSION}.json"
    if not path.exists():
        print(f"[master_data] WARNING: {path} not found; skipping unit rules seed.")
        return
    rules = json.loads(path.read_text(encoding="utf-8"))
    for rule in rules:
        existing = await session.scalar(
            select(UnitRule).where(
                UnitRule.version == rule["version"],
                UnitRule.from_unit == rule["from_unit"],
                UnitRule.to_unit == rule["to_unit"],
            )
        )
        if existing is None:
            session.add(
                UnitRule(
                    version=rule["version"],
                    from_unit=rule["from_unit"],
                    to_unit=rule["to_unit"],
                    factor=float(rule["factor"]),
                    note=rule.get("note"),
                )
            )


async def _load_coefficients(session) -> None:
    path = MASTER_DATA_DIR / f"coeff_{VERSION}.json"
    if not path.exists():
        print(f"[master_data] WARNING: {path} not found; skipping coefficients seed.")
        return
    coeffs = json.loads(path.read_text(encoding="utf-8"))
    for c in coeffs:
        existing = await session.scalar(
            select(Coefficient).where(
                Coefficient.version == c["version"],
                Coefficient.coeff_code == c["coeff_code"],
            )
        )
        if existing is None:
            session.add(
                Coefficient(
                    version=c["version"],
                    coeff_code=c["coeff_code"],
                    description_vi=c["description_vi"],
                    value=float(c["value"]),
                    applies_to=json.dumps(c.get("applies_to", "all"), ensure_ascii=False),
                )
            )
