"""
In-memory job store for the Construction Tender MVP.
Production deployments should replace this with a persistent backend.
"""
from __future__ import annotations

import uuid
from typing import Dict, Optional

from ..models.domain import TenderJob


_jobs: Dict[str, TenderJob] = {}


def create_job(filename: str) -> TenderJob:
    job_id = str(uuid.uuid4())
    job = TenderJob(job_id=job_id, tenant_id="demo-internal", filename=filename)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[TenderJob]:
    return _jobs.get(job_id)


def update_job(job: TenderJob) -> None:
    _jobs[job.job_id] = job


def list_jobs() -> list[TenderJob]:
    return list(_jobs.values())
