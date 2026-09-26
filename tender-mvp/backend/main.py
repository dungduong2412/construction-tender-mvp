"""
Construction Tender MVP — FastAPI Backend
Entry point: uvicorn main:app --reload
"""
import base64
import binascii
import os
import secrets
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Load backend-only configuration before importing modules that initialize
# provider clients or database engines from environment variables.
load_dotenv()

from database import init_db
from master_data.loader import load_master_data
from parser_adapter.adapter import API_VERSION
from routers import jobs, parser, review, export, train1


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await load_master_data()
    yield


app = FastAPI(
    title="Construction Tender MVP",
    version="0.1.0",
    lifespan=lifespan,
)


def _requires_uat_access(path: str) -> bool:
    if path == "/health":
        return False
    if path.startswith("/api/train1") or path.startswith("/api/parser"):
        return False
    return not path.startswith("/api/") or path.startswith(
        ("/api/jobs", "/api/review", "/api/export")
    )


@app.middleware("http")
async def protect_uat_content(request: Request, call_next):
    environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "")).strip().lower()
    if environment != "uat" or not _requires_uat_access(request.url.path):
        return await call_next(request)

    expected_username = os.getenv("UAT_ACCESS_USERNAME", "uat").strip() or "uat"
    expected_password = os.getenv("UAT_ACCESS_PASSWORD", "")
    if not expected_password:
        return JSONResponse(
            status_code=503,
            content={"detail": "UAT access protection is not configured"},
        )

    authorization = request.headers.get("Authorization", "")
    supplied_username = ""
    supplied_password = ""
    if authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            supplied_username, supplied_password = decoded.split(":", 1)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass

    if not (
        secrets.compare_digest(supplied_username, expected_username)
        and secrets.compare_digest(supplied_password, expected_password)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "UAT access required"},
            headers={"WWW-Authenticate": 'Basic realm="Construction Tender UAT"'},
        )

    return await call_next(request)


@app.get("/health", include_in_schema=False)
async def health():
    return {
        "status": "ok",
        "environment": os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "")).strip().lower() or "local",
        "azure_document_intelligence_api_version": API_VERSION,
        "mock_parser": os.getenv("MOCK_PARSER", "").strip().lower() == "true",
        "mock_ai": os.getenv("MOCK_AI", "").strip().lower() == "true",
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(parser.router, prefix="/api/parser", tags=["parser"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(train1.router, prefix="/api/train1", tags=["train1"])

# Serve frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
