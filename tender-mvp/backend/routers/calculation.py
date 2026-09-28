"""Calculation snapshot API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from calculation_snapshots import build_snapshot, load_snapshot
from database import get_db


router = APIRouter()


@router.get("/{job_id}")
async def get_calculation(job_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await build_snapshot(db, job_id)
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


@router.get("/snapshots/{snapshot_id}/immutable")
async def get_immutable_snapshot(snapshot_id: str):
    snapshot = load_snapshot(snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Calculation snapshot not found")
    return snapshot
