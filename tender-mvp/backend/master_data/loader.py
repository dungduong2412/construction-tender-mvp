"""
Master data loader — reads JSON seed files and upserts into SQLite at startup.
One-time, idempotent: uses (version, item_code) as the natural key.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import select

from database import AsyncSessionLocal, Coefficient, ConfigurationHistory, MasterItem, UnitRule

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
        now = datetime.now(timezone.utc)
        existing = await session.scalar(
            select(MasterItem).where(
                MasterItem.version == item["version"],
                MasterItem.item_code == item["item_code"],
                MasterItem.tenant_id == TENANT_ID,
            )
        )
        if existing is None:
            existing = MasterItem(
                    tenant_id=TENANT_ID,
                    version=item["version"],
                    item_code=item["item_code"],
                    description_vi=item["description_vi"],
                    unit=item["unit"],
                    unit_price=float(item["unit_price"]) if item.get("unit_price") is not None else None,
                    formula_ref=item.get("formula_ref"),
                    source_sheet=item.get("source_sheet"),
                    tags_json=json.dumps(item.get("tags", {}), ensure_ascii=False),
                    created_by=item.get("created_by", "source-import"),
                    created_at=now,
                    last_updated_by=item.get("last_updated_by", "source-import"),
                    last_updated_at=now,
                    price_source_reference=item.get("price_source_reference") or item.get("source_sheet"),
                    price_effective_date=item.get("price_effective_date"),
                    price_expiry_date=item.get("price_expiry_date"),
                    approval_status=item.get("approval_status", "approved"),
                    approved_by=item.get("approved_by", "source-import"),
                    zero_price_authorized=bool(item.get("zero_price_authorized", False)),
                )
            session.add(existing)
            await session.flush()
        else:
            existing.created_by = existing.created_by or item.get("created_by", "source-import")
            existing.created_at = existing.created_at or now
            existing.last_updated_by = existing.last_updated_by or item.get("last_updated_by", "source-import")
            existing.last_updated_at = existing.last_updated_at or existing.created_at or now
            existing.price_source_reference = existing.price_source_reference or item.get("price_source_reference") or item.get("source_sheet")
            existing.price_effective_date = existing.price_effective_date or item.get("price_effective_date")
            existing.price_expiry_date = existing.price_expiry_date or item.get("price_expiry_date")
            existing.approval_status = existing.approval_status or item.get("approval_status", "approved")
            existing.approved_by = existing.approved_by or item.get("approved_by", "source-import")
        await _record_import_history(session, "master_item", item["item_code"], item["version"], item)


async def _load_unit_rules(session) -> None:
    path = MASTER_DATA_DIR / f"unit_rules_{VERSION}.json"
    if not path.exists():
        print(f"[master_data] WARNING: {path} not found; skipping unit rules seed.")
        return
    rules = json.loads(path.read_text(encoding="utf-8"))
    for rule in rules:
        now = datetime.now(timezone.utc)
        existing = await session.scalar(
            select(UnitRule).where(
                UnitRule.version == rule["version"],
                UnitRule.from_unit == rule["from_unit"],
                UnitRule.to_unit == rule["to_unit"],
            )
        )
        if existing is None:
            existing = UnitRule(
                    version=rule["version"],
                    from_unit=rule["from_unit"],
                    to_unit=rule["to_unit"],
                    factor=float(rule["factor"]),
                    note=rule.get("note"),
                    created_by=rule.get("created_by", "source-import"), last_updated_by=rule.get("last_updated_by", "source-import"),
                    created_at=now, last_updated_at=now,
                    source_reference=rule.get("source_reference") or rule.get("note"), effective_date=rule.get("effective_date"),
                    expiry_date=rule.get("expiry_date"), approval_status=rule.get("approval_status", "approved"),
                    approved_by=rule.get("approved_by", "source-import"),
                )
            session.add(existing)
            await session.flush()
        else:
            existing.created_by = existing.created_by or rule.get("created_by", "source-import")
            existing.created_at = existing.created_at or now
            existing.last_updated_by = existing.last_updated_by or rule.get("last_updated_by", "source-import")
            existing.last_updated_at = existing.last_updated_at or existing.created_at or now
            existing.source_reference = existing.source_reference or rule.get("source_reference") or rule.get("note")
            existing.effective_date = existing.effective_date or rule.get("effective_date")
            existing.expiry_date = existing.expiry_date or rule.get("expiry_date")
            existing.approval_status = existing.approval_status or rule.get("approval_status", "approved")
            existing.approved_by = existing.approved_by or rule.get("approved_by", "source-import")
        await _record_import_history(session, "unit_rule", f"{rule['from_unit']}->{rule['to_unit']}", rule["version"], rule)


async def _load_coefficients(session) -> None:
    path = MASTER_DATA_DIR / f"coeff_{VERSION}.json"
    if not path.exists():
        print(f"[master_data] WARNING: {path} not found; skipping coefficients seed.")
        return
    coeffs = json.loads(path.read_text(encoding="utf-8"))
    for c in coeffs:
        now = datetime.now(timezone.utc)
        existing = await session.scalar(
            select(Coefficient).where(
                Coefficient.version == c["version"],
                Coefficient.coeff_code == c["coeff_code"],
            )
        )
        if existing is None:
            existing = Coefficient(
                    version=c["version"],
                    coeff_code=c["coeff_code"],
                    description_vi=c["description_vi"],
                    value=float(c["value"]),
                    applies_to=json.dumps(c.get("applies_to", "all"), ensure_ascii=False),
                    created_by=c.get("created_by", "source-import"), last_updated_by=c.get("last_updated_by", "source-import"),
                    created_at=now, last_updated_at=now,
                    source_reference=c.get("source_reference") or "Hệ số", effective_date=c.get("effective_date"),
                    expiry_date=c.get("expiry_date"), approval_status=c.get("approval_status", "approved"),
                    approved_by=c.get("approved_by", "source-import"),
                )
            session.add(existing)
            await session.flush()
        else:
            existing.created_by = existing.created_by or c.get("created_by", "source-import")
            existing.created_at = existing.created_at or now
            existing.last_updated_by = existing.last_updated_by or c.get("last_updated_by", "source-import")
            existing.last_updated_at = existing.last_updated_at or existing.created_at or now
            existing.source_reference = existing.source_reference or c.get("source_reference") or "Hệ số"
            existing.effective_date = existing.effective_date or c.get("effective_date")
            existing.expiry_date = existing.expiry_date or c.get("expiry_date")
            existing.approval_status = existing.approval_status or c.get("approval_status", "approved")
            existing.approved_by = existing.approved_by or c.get("approved_by", "source-import")
        await _record_import_history(session, "coefficient", c["coeff_code"], c["version"], c)


async def _record_import_history(session, record_type: str, record_key: str, version: str, payload: dict) -> None:
    existing = await session.scalar(
        select(ConfigurationHistory).where(
            ConfigurationHistory.record_type == record_type,
            ConfigurationHistory.record_key == record_key,
            ConfigurationHistory.version == version,
            ConfigurationHistory.event == "imported",
        )
    )
    if existing is None:
        session.add(ConfigurationHistory(
            record_type=record_type,
            record_key=record_key,
            version=version,
            event="imported",
            actor=payload.get("created_by", "source-import"),
            change_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ))
