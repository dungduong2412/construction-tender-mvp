"""Master-data and formula-governance API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Coefficient, ConfigurationHistory, MappingResult, MasterItem, UnitRule, get_db
from formula_config import approve_proposal, create_proposal, list_versions, preview_change
from master_data.governance import add_project_override, decide_candidate, overview
from pricing_availability import classify_price, price_freshness


router = APIRouter()


class CandidateDecision(BaseModel):
    decision: str
    actor: str = "local-admin"
    note: str | None = None


class ProjectOverride(BaseModel):
    project_id: str
    resource_code: str
    unit_price: str
    source_reference: str
    effective_date: str | None = None
    expiry_date: str | None = None
    approval_status: str = "approved"
    approved_by: str | None = None
    zero_price_authorized: bool = False
    actor: str = "local-admin"


class MasterPriceUpdate(BaseModel):
    code: str | None = None
    name_vi: str | None = None
    name_en: str | None = None
    long_description: str | None = None
    aliases: list[str] | None = None
    category: str | None = None
    unit: str | None = None
    status: str | None = None
    unit_price: str | None = None
    source_reference: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    approval_status: str = "approved"
    approved_by: str | None = None
    zero_price_authorized: bool = False
    actor: str = "local-admin"


class CatalogueItemCreate(BaseModel):
    code: str
    name_vi: str
    name_en: str | None = None
    long_description: str = ""
    aliases: list[str] = Field(default_factory=list)
    category: str = ""
    unit: str
    unit_price: str | None = None
    source_reference: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    approval_status: str = "approved"
    approved_by: str | None = None
    zero_price_authorized: bool = False
    status: str = "active"
    actor: str = "local-admin"


class FormulaPreview(BaseModel):
    changes: dict[str, Any]
    category: str = "default"
    basis: dict[str, Any] = Field(default_factory=lambda: {"material": "1000000", "labour": "1000000", "machine": "500000"})


class FormulaProposal(FormulaPreview):
    name: str
    effective_from: str
    actor: str = "local-admin"


class FormulaApproval(BaseModel):
    actor: str = "local-approver"


@router.get("/master-data")
async def get_master_data(db: AsyncSession = Depends(get_db)):
    data = overview()
    tenant = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")
    version = os.getenv("MASTER_DATA_VERSION", "v1")
    items = list((await db.execute(select(MasterItem).where(MasterItem.tenant_id == tenant, MasterItem.version == version))).scalars())
    rules = list((await db.execute(select(UnitRule).where(UnitRule.version == version))).scalars())
    coefficients = list((await db.execute(select(Coefficient).where(Coefficient.version == version))).scalars())
    data["catalogue"] = []
    for item in items:
        source = item.price_source_reference or item.source_sheet
        availability = classify_price(
            item.unit_price, source_reference=source, approval_status=item.approval_status,
            approved_by=item.approved_by, zero_price_authorized=item.zero_price_authorized,
        )
        history = list((await db.execute(select(ConfigurationHistory).where(
            ConfigurationHistory.record_type == "master_item",
            ConfigurationHistory.record_key == item.item_code,
        ).order_by(ConfigurationHistory.id))).scalars())
        data["catalogue"].append({
            "id": item.id, "code": item.item_code, "description": item.description_vi, "unit": item.unit,
            "name_vi": item.description_vi, "name_en": item.name_en,
            "long_description": item.long_description or item.description_vi,
            "aliases": json.loads(item.aliases_json or "[]"), "category": item.category,
            "status": item.catalogue_status,
            "unit_price": str(item.unit_price) if item.unit_price is not None else None,
            "price_display": str(item.unit_price) if availability.available else "Not available",
            "pricing_available": availability.available, "pricing_availability": availability.status,
            "price_freshness": price_freshness(item.price_effective_date, item.price_expiry_date, available=availability.available),
            "formula_ref": item.formula_ref, "source_reference": source,
            "price_effective_date": item.price_effective_date, "price_expiry_date": item.price_expiry_date,
            "approval_status": item.approval_status, "approved_by": item.approved_by,
            "original_creator": item.created_by, "created_at": item.created_at.isoformat() if item.created_at else None,
            "last_updated_by": item.last_updated_by, "last_updated_at": item.last_updated_at.isoformat() if item.last_updated_at else None,
            "version": item.version, "tags": json.loads(item.tags_json or "{}"),
            "version_history": [{"version": event.version, "event": event.event, "actor": event.actor,
                                 "change": json.loads(event.change_json),
                                 "at": event.created_at.isoformat() if event.created_at else None} for event in history],
        })
    data["controlled_conversion_rules"] = [{
        "id": rule.id, "from_unit": rule.from_unit, "to_unit": rule.to_unit, "factor": str(rule.factor),
        "note": rule.note, "version": rule.version, "source_reference": rule.source_reference,
        "effective_date": rule.effective_date, "expiry_date": rule.expiry_date,
        "approval_status": rule.approval_status, "approved_by": rule.approved_by,
        "original_creator": rule.created_by, "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "last_updated_by": rule.last_updated_by, "last_updated_at": rule.last_updated_at.isoformat() if rule.last_updated_at else None,
    } for rule in rules]
    data["coefficients"] = [{
        "code": coefficient.coeff_code, "description": coefficient.description_vi,
        "value": str(coefficient.value), "applies_to": json.loads(coefficient.applies_to or '"all"'),
        "version": coefficient.version, "source_reference": coefficient.source_reference,
        "effective_date": coefficient.effective_date, "expiry_date": coefficient.expiry_date,
        "approval_status": coefficient.approval_status, "approved_by": coefficient.approved_by,
        "original_creator": coefficient.created_by, "created_at": coefficient.created_at.isoformat() if coefficient.created_at else None,
        "last_updated_by": coefficient.last_updated_by,
        "last_updated_at": coefficient.last_updated_at.isoformat() if coefficient.last_updated_at else None,
    } for coefficient in coefficients]
    return data


@router.post("/master-data/catalogue", status_code=201)
async def create_catalogue_item(body: CatalogueItemCreate, db: AsyncSession = Depends(get_db)):
    tenant = os.getenv("DEMO_TENANT_ID", "demo-tenant-001")
    version = os.getenv("MASTER_DATA_VERSION", "v1")
    if body.status not in {"active", "retired"}:
        raise HTTPException(400, "status must be active or retired")
    if not body.code.strip() or not body.name_vi.strip() or not body.unit.strip():
        raise HTTPException(400, "Code, Vietnamese name and unit are required")
    duplicate = await db.scalar(select(MasterItem).where(
        MasterItem.tenant_id == tenant, MasterItem.version == version,
        MasterItem.item_code == body.code.strip(),
    ))
    if duplicate:
        raise HTTPException(409, "Catalogue code already exists")
    availability = classify_price(
        body.unit_price, source_reference=body.source_reference,
        approval_status=body.approval_status, approved_by=body.approved_by,
        zero_price_authorized=body.zero_price_authorized,
    )
    if body.unit_price is not None and not availability.available:
        raise HTTPException(400, availability.reason or "Price is not available")
    if body.unit_price is not None and (not body.effective_date or not body.approved_by):
        raise HTTPException(400, "Approved source evidence, effective date and approver are required")
    now = datetime.now(timezone.utc)
    item = MasterItem(
        tenant_id=tenant, version=version, item_code=body.code.strip(),
        description_vi=body.name_vi.strip(), name_en=(body.name_en or "").strip() or None,
        long_description=(body.long_description or "").strip() or body.name_vi.strip(),
        aliases_json=json.dumps([value.strip() for value in body.aliases if value.strip()], ensure_ascii=False),
        category=(body.category or "").strip() or None, unit=body.unit.strip(),
        unit_price=float(availability.value) if availability.available and availability.value is not None else None,
        price_source_reference=body.source_reference, source_sheet=body.source_reference,
        price_effective_date=body.effective_date, price_expiry_date=body.expiry_date,
        approval_status=body.approval_status, approved_by=body.approved_by,
        zero_price_authorized=body.zero_price_authorized, catalogue_status=body.status,
        created_by=body.actor, created_at=now, last_updated_by=body.actor, last_updated_at=now,
        tags_json=json.dumps({"category": body.category}, ensure_ascii=False),
    )
    db.add(item)
    await db.flush()
    db.add(ConfigurationHistory(
        record_type="master_item", record_key=item.item_code, version=f"{version}.1",
        event="created", actor=body.actor,
        change_json=json.dumps(body.model_dump(exclude={"actor"}), ensure_ascii=False),
    ))
    await db.commit()
    await db.refresh(item)
    return {"status": "created", "item_id": item.id, "code": item.item_code}


@router.patch("/master-data/catalogue/{item_id}")
async def update_master_price(item_id: int, body: MasterPriceUpdate, db: AsyncSession = Depends(get_db)):
    """Version catalogue changes and flag dependants without silently repricing them."""
    item = await db.get(MasterItem, item_id)
    if not item:
        raise HTTPException(404, "Master item not found")
    fields = body.model_fields_set
    proposed_price = body.unit_price if "unit_price" in fields else (str(item.unit_price) if item.unit_price is not None else None)
    proposed_source = body.source_reference if "source_reference" in fields else item.price_source_reference
    proposed_effective = body.effective_date if "effective_date" in fields else item.price_effective_date
    proposed_approval = body.approval_status if "approval_status" in fields else item.approval_status
    proposed_approver = body.approved_by if "approved_by" in fields else item.approved_by
    proposed_zero = body.zero_price_authorized if "zero_price_authorized" in fields else item.zero_price_authorized
    current_price = None if item.unit_price is None else str(item.unit_price)
    try:
        normalized_proposed = None if proposed_price is None else Decimal(str(proposed_price))
        normalized_current = None if current_price is None else Decimal(str(current_price))
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "unit_price must be a valid number")
    price_changed = any((
        normalized_proposed != normalized_current,
        proposed_source != item.price_source_reference,
        proposed_effective != item.price_effective_date,
        (body.expiry_date if "expiry_date" in fields else item.price_expiry_date) != item.price_expiry_date,
        proposed_approval != item.approval_status,
        proposed_approver != item.approved_by,
        proposed_zero != item.zero_price_authorized,
    ))
    availability = classify_price(proposed_price, source_reference=proposed_source,
        approval_status=proposed_approval, approved_by=proposed_approver, zero_price_authorized=proposed_zero)
    if price_changed and proposed_price is not None and not availability.available:
        raise HTTPException(400, availability.reason or "Price is not available")
    if price_changed and proposed_price is not None and (not proposed_effective or proposed_approval != "approved" or not proposed_approver):
        raise HTTPException(400, "Approved source evidence, effective date and approver are required")
    if body.status is not None and body.status not in {"active", "retired"}:
        raise HTTPException(400, "status must be active or retired")
    before = {
        "unit_price": item.unit_price, "source_reference": item.price_source_reference,
        "effective_date": item.price_effective_date, "expiry_date": item.price_expiry_date,
        "approval_status": item.approval_status, "approved_by": item.approved_by,
    }
    now = datetime.now(timezone.utc)
    if "code" in fields and body.code and body.code.strip() != item.item_code:
        duplicate = await db.scalar(select(MasterItem).where(MasterItem.tenant_id == item.tenant_id,
            MasterItem.version == item.version, MasterItem.item_code == body.code.strip(), MasterItem.id != item.id))
        if duplicate:
            raise HTTPException(409, "Catalogue code already exists")
        item.item_code = body.code.strip()
    if "name_vi" in fields:
        if not body.name_vi or not body.name_vi.strip(): raise HTTPException(400, "Vietnamese name is required")
        item.description_vi = body.name_vi.strip()
    if "name_en" in fields: item.name_en = (body.name_en or "").strip() or None
    if "long_description" in fields: item.long_description = (body.long_description or "").strip() or item.description_vi
    if "aliases" in fields: item.aliases_json = json.dumps([v.strip() for v in (body.aliases or []) if v.strip()], ensure_ascii=False)
    if "category" in fields: item.category = (body.category or "").strip() or None
    if "unit" in fields:
        if not body.unit or not body.unit.strip(): raise HTTPException(400, "Unit is required")
        item.unit = body.unit.strip()
    if "status" in fields: item.catalogue_status = body.status or "active"
    if price_changed:
        item.unit_price = float(availability.value) if availability.available and availability.value is not None else None
        item.price_source_reference = proposed_source
        item.price_effective_date = proposed_effective
        item.price_expiry_date = body.expiry_date if "expiry_date" in fields else item.price_expiry_date
        item.approval_status = proposed_approval
        item.approved_by = proposed_approver
        item.zero_price_authorized = proposed_zero
    item.last_updated_by = body.actor
    item.last_updated_at = now
    existing_history = list((await db.execute(select(ConfigurationHistory).where(
        ConfigurationHistory.record_type == "master_item", ConfigurationHistory.record_key == item.item_code,
    ))).scalars())
    db.add(ConfigurationHistory(
        record_type="master_item", record_key=item.item_code,
        version=f"{item.version}.{len(existing_history) + 1}", event="catalogue_updated", actor=body.actor,
        change_json=json.dumps({"before": before, "after": body.model_dump(exclude={"actor"})}, ensure_ascii=False),
    ))
    dependents = list((await db.execute(select(MappingResult).where(
        MappingResult.master_item_id == item.id,
        MappingResult.price_source != "user_override",
    ))).scalars())
    for mapping in dependents:
        mapping.price_review_required = True
    await db.commit()
    return {"status": "updated", "item_id": item.id, "pricing_availability": availability.status,
            "dependent_mappings_requiring_review": len(dependents), "last_updated_by": item.last_updated_by,
            "last_updated_at": item.last_updated_at.isoformat()}


@router.delete("/master-data/catalogue/{item_id}")
async def retire_catalogue_item(item_id: int, actor: str = "local-admin", db: AsyncSession = Depends(get_db)):
    item = await db.get(MasterItem, item_id)
    if not item:
        raise HTTPException(404, "Master item not found")
    if item.catalogue_status == "retired":
        return {"status": "retired", "item_id": item.id, "physically_deleted": False}
    now = datetime.now(timezone.utc)
    item.catalogue_status = "retired"
    item.last_updated_by = actor
    item.last_updated_at = now
    history_count = len(list((await db.execute(select(ConfigurationHistory).where(
        ConfigurationHistory.record_type == "master_item", ConfigurationHistory.record_key == item.item_code,
    ))).scalars()))
    db.add(ConfigurationHistory(record_type="master_item", record_key=item.item_code,
        version=f"{item.version}.{history_count + 1}", event="retired", actor=actor,
        change_json=json.dumps({"status": "retired", "physically_deleted": False}, ensure_ascii=False)))
    dependents = list((await db.execute(select(MappingResult).where(MappingResult.master_item_id == item.id))).scalars())
    for mapping in dependents:
        mapping.price_review_required = True
    await db.commit()
    return {"status": "retired", "item_id": item.id, "physically_deleted": False,
            "referenced_records_preserved": len(dependents)}


@router.post("/master-data/candidates/{scoped_id}/decision")
async def candidate_decision(scoped_id: str, body: CandidateDecision):
    try:
        return decide_candidate(scoped_id, body.decision, body.actor, body.note)
    except KeyError as exc:
        raise HTTPException(404, "Candidate not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/master-data/project-overrides")
async def project_override(body: ProjectOverride):
    try:
        return add_project_override(body.model_dump(exclude={"actor"}), body.actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/formula-versions")
async def formula_versions():
    return {"versions": list_versions()}


@router.post("/formula-versions/preview")
async def formula_preview(body: FormulaPreview):
    try:
        return preview_change(body.changes, body.category, body.basis)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/formula-versions/proposals")
async def formula_proposal(body: FormulaProposal):
    try:
        return create_proposal(body.model_dump(exclude={"actor"}), body.actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/formula-versions/{version_id}/approve")
async def formula_approve(version_id: str, body: FormulaApproval):
    try:
        return approve_proposal(version_id, body.actor)
    except KeyError as exc:
        raise HTTPException(404, "Formula version not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
