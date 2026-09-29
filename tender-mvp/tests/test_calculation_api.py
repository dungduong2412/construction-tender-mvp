import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from main import app


def test_calculation_configuration_reconciliation_and_trace_endpoints(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    client = TestClient(app)

    configuration = client.get("/api/calculation/configuration")
    assert configuration.status_code == 200
    assert len(configuration.json()["rules"]) == 144

    reconciliation = client.get("/api/calculation/reconciliation")
    assert reconciliation.status_code == 200
    payload = reconciliation.json()
    assert payload["tender"]["status"] == "EXACT"
    assert payload["approval"]["status"] == "EXACT"
    assert payload["j51"]["status"] == "REFERENCE ONLY — NOT ENGINE TARGET"

    trace = client.get("/api/calculation/trace/CF.11620")
    assert trace.status_code == 200
    trace_payload = trace.json()
    assert trace_payload["project_quantity"] == "8.0"
    assert trace_payload["trace"]
    assert trace_payload["loaded_unit_price"] == "3808696"


def test_calculation_endpoints_are_uat_access_protected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "uat")
    monkeypatch.setenv("UAT_ACCESS_PASSWORD", "secret")
    client = TestClient(app)
    assert client.get("/api/calculation/reconciliation").status_code == 401
    assert client.get("/api/calculation/reconciliation", auth=("uat", "secret")).status_code == 200
