import base64
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from main import app


def _basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_uat_health_is_public_and_reports_safe_runtime_config(monkeypatch):
    monkeypatch.setenv("APP_ENV", "uat")
    monkeypatch.setenv("MOCK_PARSER", "false")
    monkeypatch.setenv("MOCK_AI", "false")
    monkeypatch.delenv("UAT_ACCESS_PASSWORD", raising=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "uat",
        "azure_document_intelligence_api_version": "2024-11-30",
        "mock_parser": False,
        "mock_ai": False,
    }


def test_uat_ui_and_legacy_routes_require_basic_access(monkeypatch):
    monkeypatch.setenv("APP_ENV", "uat")
    monkeypatch.setenv("UAT_ACCESS_USERNAME", "uat-operator")
    monkeypatch.setenv("UAT_ACCESS_PASSWORD", "test-only-password")

    with TestClient(app) as client:
        ui_denied = client.get("/")
        legacy_denied = client.get("/api/jobs/")
        legacy_wrong = client.get(
            "/api/jobs/",
            headers=_basic("uat-operator", "wrong-password"),
        )
        ui_allowed = client.get(
            "/",
            headers=_basic("uat-operator", "test-only-password"),
        )
        legacy_allowed = client.get(
            "/api/jobs/",
            headers=_basic("uat-operator", "test-only-password"),
        )

    assert ui_denied.status_code == 401
    assert ui_denied.headers["www-authenticate"].startswith("Basic ")
    assert legacy_denied.status_code == 401
    assert legacy_wrong.status_code == 401
    assert ui_allowed.status_code == 200
    assert legacy_allowed.status_code == 200


def test_uat_protected_routes_fail_closed_without_password(monkeypatch):
    monkeypatch.setenv("APP_ENV", "uat")
    monkeypatch.delenv("UAT_ACCESS_PASSWORD", raising=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 503
    assert response.json()["detail"] == "UAT access protection is not configured"


def test_v2_routes_keep_dedicated_bearer_auth(monkeypatch):
    monkeypatch.setenv("APP_ENV", "uat")
    monkeypatch.setenv("UAT_ACCESS_PASSWORD", "test-only-password")
    monkeypatch.setenv("TRAIN2_UPLOAD_AUTH_TOKEN", "train2-token")

    with TestClient(app) as client:
        response = client.get("/api/train1/runs/not-found/review")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Bearer authorization token"
