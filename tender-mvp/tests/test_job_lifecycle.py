from __future__ import annotations

import asyncio
import base64
import io
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import fitz
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import database
from boq.reconstructor import BOQLineItem
from database import (
    Base, Job, JobStageEvent, JobStatus, MappingResult, MappingStatus,
    MasterItem, get_db,
)
from main import app
from routers import jobs
from semantic_mapper.mapper import MappingOutput


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _four_page_pdf() -> bytes:
    document = fitz.open()
    for page_number in range(1, 5):
        page = document.new_page()
        page.insert_text((72, 72), f"UAT regression page {page_number}")
    payload = document.tobytes()
    document.close()
    return payload


def test_uat_fresh_import_reaches_review_with_distinct_lifecycle_counts(monkeypatch, tmp_path):
    """Missing prices are business blockers, never a processing-state blocker."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setenv("APP_ENV", "uat")
    monkeypatch.setenv("ALLOW_UAT_FIXTURE_IMPORT", "true")
    monkeypatch.setenv("UAT_ACCESS_USERNAME", "uat-operator")
    monkeypatch.setenv("UAT_ACCESS_PASSWORD", "test-only-password")
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("CALCULATION_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("EXPORT_STORAGE_DIR", str(tmp_path / "exports"))
    headers = _basic("uat-operator", "test-only-password")

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/jobs/uat-validation-import",
                headers=headers,
                files={"file": ("Bang TIen Luong.pdf", io.BytesIO(_four_page_pdf()), "application/pdf")},
            )
            assert created.status_code == 200
            payload = created.json()
            job_id = payload["job_id"]
            assert payload["status"] == "needs_review"
            assert payload["source_row_count"] == payload["row_count"] == 95
            assert payload["billable_count"] == 82
            assert payload["structural_count"] == 13
            assert payload["mapping_unresolved_count"] == 0
            assert payload["pricing_unavailable_count"] == payload["unresolved_count"] == 16
            assert payload["pricing_conflict_count"] == 0
            assert [event["stage"] for event in payload["stage_sequence"]] == [
                "uploaded", "parsing", "mapping", "pricing", "needs_review",
            ]

            polled = client.get(f"/api/jobs/{job_id}", headers=headers)
            assert polled.status_code == 200
            assert polled.json()["status"] == "needs_review"

            rows = client.get(f"/api/review/{job_id}/rows", headers=headers).json()
            assert len(rows) == 95
            structural = [row for row in rows if row["row_type"] != "line_item"]
            unavailable = [row for row in rows if row["status"] == "mapped_price_unavailable"]
            assert len(structural) == 13
            assert all(row["pricing_availability"] == "not_applicable" for row in structural)
            assert len(unavailable) == 16
            assert all(row["unit_price"] is None and row["price_display"] == "Not available" for row in unavailable)

            calculation = client.get(f"/api/calculation/{job_id}", headers=headers)
            assert calculation.status_code == 200
            snapshot = calculation.json()
            assert snapshot["tender"]["status"] == "INCOMPLETE"
            assert snapshot["export_policy"]["internal_draft_allowed"] is True
            assert snapshot["export_policy"]["final_submission_allowed"] is False

            internal = client.get(
                f"/api/export/{job_id}/internal.xlsx",
                headers=headers,
                params={"snapshot_id": snapshot["snapshot_id"]},
            )
            assert internal.status_code == 200
            final = client.get(
                f"/api/export/{job_id}/final.xlsx",
                headers=headers,
                params={"snapshot_id": snapshot["snapshot_id"]},
            )
            assert final.status_code == 409
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_real_pipeline_maps_before_pricing_and_null_price_reaches_terminal_review(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pipeline.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    job_id = str(uuid.uuid4())

    billable_missing = BOQLineItem(
        row_id="missing", row_number="1", section_path="A", description_vi="Missing price",
        unit_raw="m", quantity_raw="2", quantity=2, page=1, region="[]",
        row_type="line_item", doc_order=1,
    )
    billable_zero = BOQLineItem(
        row_id="zero", row_number="2", section_path="A", description_vi="Authorized zero",
        unit_raw="m", quantity_raw="3", quantity=3, page=1, region="[]",
        row_type="line_item", doc_order=2,
    )
    structural = BOQLineItem(
        row_id="heading", row_number="A", section_path="A", description_vi="Heading",
        unit_raw="", quantity_raw="", quantity=None, page=1, region="[]",
        row_type="heading", doc_order=3,
    )

    class FakeParser:
        async def analyze(self, _pdf):
            return {"analyzeResult": {"pages": [{}]}}

    class FakeNormalizer:
        def normalize(self, _raw):
            return SimpleNamespace(page_count=1, model_id="fixture", api_version="test", boq_rows=[])

    class FakeReconstructor:
        def reconstruct(self, _rows):
            return [billable_missing, billable_zero, structural]

    class FakeMapper:
        def __init__(self):
            pass

        async def map_item(self, item, candidates, _version):
            async with sessions() as session:
                persisted = await session.get(Job, job_id)
                assert persisted.status == JobStatus.mapping
            candidate = next((value for value in candidates if value.item_code == item.row_id), None)
            if item.row_type != "line_item":
                return MappingOutput(
                    master_item_id=None, confidence=0, tags={}, evidence="structural",
                    unresolved_reason="Not billable", status="error",
                    classification="non_billable_heading",
                )
            return MappingOutput(
                master_item_id=candidate.id, confidence=1, tags={}, evidence="verified fixture",
                unresolved_reason=None, status="resolved", classification="mapped_and_priced",
            )

    async def scenario():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(Job(
                id=job_id, tenant_id=jobs.DEMO_TENANT_ID,
                filename="fixture.pdf", status=JobStatus.uploaded,
            ))
            session.add(JobStageEvent(job_id=job_id, stage="uploaded"))
            session.add_all([
                MasterItem(
                    tenant_id=jobs.DEMO_TENANT_ID, version=jobs.MASTER_VERSION,
                    item_code="missing", description_vi="Missing price", unit="m",
                    unit_price=None, price_source_reference="approved-source",
                    approval_status="approved",
                ),
                MasterItem(
                    tenant_id=jobs.DEMO_TENANT_ID, version=jobs.MASTER_VERSION,
                    item_code="zero", description_vi="Authorized zero", unit="m",
                    unit_price=0, price_source_reference="approved-zero-decision",
                    approval_status="approved", approved_by="approver", zero_price_authorized=True,
                ),
            ])
            await session.commit()

        await jobs._process_job(job_id, b"%PDF-fixture", "fixture.pdf")

        async with sessions() as session:
            persisted = await session.get(Job, job_id)
            assert persisted.status == JobStatus.needs_review
            events = (await session.execute(
                select(JobStageEvent).where(JobStageEvent.job_id == job_id).order_by(JobStageEvent.id)
            )).scalars().all()
            assert [event.stage for event in events] == [
                "uploaded", "parsing", "mapping", "pricing", "needs_review",
            ]
            mappings = (await session.execute(select(MappingResult))).scalars().all()
            by_status = {mapping.status: mapping for mapping in mappings}
            missing = by_status[MappingStatus.mapped_price_unavailable]
            assert missing.unit_price_str is None
            assert missing.extended_amount_str is None
            zero = by_status[MappingStatus.mapped_and_priced]
            assert zero.unit_price_str == "0"
            assert zero.extended_amount_str == "0"
            nonbillable = by_status[MappingStatus.non_billable_heading]
            assert nonbillable.pricing_availability == "not_applicable"

    monkeypatch.setattr(database, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(jobs, "ParserAdapter", FakeParser)
    monkeypatch.setattr(jobs, "DocumentNormalizer", FakeNormalizer)
    monkeypatch.setattr(jobs, "BOQReconstructor", FakeReconstructor)
    monkeypatch.setattr(jobs, "SemanticMapper", FakeMapper)
    asyncio.run(scenario())
    asyncio.run(engine.dispose())
