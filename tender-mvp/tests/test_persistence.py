from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from database import Base, ExportRecord, Job, JobStatus
from integration_train1.pipeline import Train1Pipeline
from routers.export import _export_storage_dir, _persist_export


def _run(coro):
    return asyncio.run(coro)


def test_train2_run_survives_new_pipeline_instance(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAIN2_RUN_STORAGE_DIR", str(tmp_path / "train2-runs"))
    first = Train1Pipeline()
    created = _run(first.start_from_fixture())

    second = Train1Pipeline()
    restored = second.get_review(created["run_id"])

    assert restored == created
    assert (tmp_path / "train2-runs" / f'{created["run_id"]}.json').is_file()


def test_export_file_and_metadata_survive_new_database_session(monkeypatch, tmp_path):
    monkeypatch.setenv("EXPORT_STORAGE_DIR", str(tmp_path / "exports"))

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'uat.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        job_id = str(uuid.uuid4())
        async with sessions() as session:
            session.add(Job(id=job_id, tenant_id="uat", filename="fixture.pdf", status=JobStatus.needs_review))
            await session.commit()
            record = await _persist_export(
                session,
                job_id=job_id,
                snapshot_id="snapshot-immutable",
                export_type="internal",
                filename="fixture_internal.xlsx",
                content=b"durable-workbook",
            )
            export_id = record.id

        async with sessions() as restarted_session:
            restored = await restarted_session.get(ExportRecord, export_id)
            assert restored is not None
            stored = _export_storage_dir() / restored.file_name
            assert stored.read_bytes() == b"durable-workbook"
            assert restored.sha256 == hashlib.sha256(b"durable-workbook").hexdigest()
        await engine.dispose()

    _run(scenario())


def test_uat_baseline_fixture_preserves_commercial_blockers():
    fixture = json.loads((ROOT / "fixtures/bang_tien_luong_uat_baseline_95.json").read_text())
    rows = fixture["rows"]
    assert len(rows) == 95
    assert sum(row["billable"] for row in rows) == 82
    assert sum(not row["billable"] for row in rows) == 13
    assert sum(row["treatment"] == "blocked" for row in rows) == 16
    assert all(row["unit_price"] is None for row in rows if row["treatment"] == "blocked")
    recovered = next(row for row in rows if row["stt"] == "II.3.2")
    assert recovered["billable"] is False
    assert recovered["azure_polygon_available"] is False
