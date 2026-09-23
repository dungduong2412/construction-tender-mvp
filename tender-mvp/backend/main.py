"""
FastAPI application entry point for the Construction Tender MVP.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes.jobs import router as jobs_router

app = FastAPI(
    title="Construction Tender MVP",
    description=(
        "Upload a Vietnamese construction/survey BOQ PDF. "
        "Azure Document Intelligence extracts its structure. "
        "AI maps items to master data. A deterministic engine calculates bid prices."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "construction-tender-mvp"}
