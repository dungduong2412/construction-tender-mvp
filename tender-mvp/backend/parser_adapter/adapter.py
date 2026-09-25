"""
Parser Adapter — wraps the Azure Document Intelligence API.

CONTRACT
--------
Real mode (MOCK_PARSER=false):
  POST {AZURE_DOC_INTEL_ENDPOINT}/formrecognizer/documentModels/prebuilt-layout:analyze
       ?api-version=2024-02-29-preview
  → 202 Accepted, Operation-Location header for polling
  GET  {Operation-Location}
  → 200 {"status": "succeeded", "analyzeResult": {...}}

Mock mode (MOCK_PARSER=true):
  Returns fixture JSON from fixtures/bang_tien_luong_mock.json synchronously.

All external-API logic stays in this module; business logic must not import httpx directly.
"""
import json
import os
from pathlib import Path
from typing import Any

import httpx

API_VERSION = "2024-02-29-preview"
MODEL_ID = "prebuilt-layout"
FIXTURE_PATH = Path(__file__).parent.parent.parent / "fixtures" / "bang_tien_luong_mock.json"


def _mock_parser_enabled() -> bool:
    return os.getenv("MOCK_PARSER", "true").lower() in ("1", "true", "yes")


def _azure_endpoint() -> str:
    return os.getenv("AZURE_DOC_INTEL_ENDPOINT", "").strip()


def _azure_key() -> str:
    return os.getenv("AZURE_DOC_INTEL_KEY", "").strip()


class ParserAdapterError(Exception):
    pass


class ParserAdapter:
    """
    Submits a PDF to Azure Document Intelligence (or returns mock fixture).

    Usage:
        adapter = ParserAdapter()
        result = await adapter.analyze(pdf_bytes)   # returns AnalyzedDocument dict
    """

    async def analyze(self, pdf_bytes: bytes) -> dict[str, Any]:
        if _mock_parser_enabled():
            return self._load_mock()
        return await self._analyze_real(pdf_bytes)

    # ------------------------------------------------------------------
    def _load_mock(self) -> dict[str, Any]:
        if not FIXTURE_PATH.exists():
            raise ParserAdapterError(f"Mock fixture not found: {FIXTURE_PATH}")
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        # Wrap in analyzeResult envelope if the fixture is the raw analyzeResult
        if "analyzeResult" not in data:
            return {"status": "succeeded", "analyzeResult": data}
        return data

    # ------------------------------------------------------------------
    async def _analyze_real(self, pdf_bytes: bytes) -> dict[str, Any]:
        endpoint = _azure_endpoint()
        key = _azure_key()
        if not endpoint or not key:
            raise ParserAdapterError(
                "AZURE_DOC_INTEL_ENDPOINT and AZURE_DOC_INTEL_KEY must be set when MOCK_PARSER=false"
            )
        url = (
            f"{endpoint.rstrip('/')}/formrecognizer/documentModels/"
            f"{MODEL_ID}:analyze?api-version={API_VERSION}"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/pdf",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, content=pdf_bytes, headers=headers)
            if resp.status_code != 202:
                raise ParserAdapterError(
                    f"Azure API submit failed: {resp.status_code} {resp.text[:400]}"
                )
            operation_url = resp.headers.get("Operation-Location", "")
            if not operation_url:
                raise ParserAdapterError("Azure API did not return Operation-Location header")

            return await self._poll(client, operation_url)

    async def _poll(self, client: httpx.AsyncClient, operation_url: str) -> dict[str, Any]:
        import asyncio
        headers = {"Ocp-Apim-Subscription-Key": _azure_key()}
        for attempt in range(60):  # max ~5 minutes
            await asyncio.sleep(5)
            resp = await client.get(operation_url, headers=headers)
            if resp.status_code != 200:
                raise ParserAdapterError(
                    f"Azure API poll failed: {resp.status_code} {resp.text[:400]}"
                )
            result = resp.json()
            status = result.get("status", "")
            if status == "succeeded":
                return result
            if status == "failed":
                raise ParserAdapterError(f"Azure analysis failed: {result}")
            # running / notStarted — keep polling
        raise ParserAdapterError("Azure analysis timed out after 60 poll attempts")
