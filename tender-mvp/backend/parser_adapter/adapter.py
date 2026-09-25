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


class ParserAdapterAuthError(ParserAdapterError):
    pass


class ParserAdapterTimeoutError(ParserAdapterError):
    pass


class ParserAdapterContractError(ParserAdapterError):
    pass


class ParserAdapterTransportError(ParserAdapterError):
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
            raise ParserAdapterContractError("Azure parser configuration is incomplete")
        url = (
            f"{endpoint.rstrip('/')}/formrecognizer/documentModels/"
            f"{MODEL_ID}:analyze?api-version={API_VERSION}"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/pdf",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(url, content=pdf_bytes, headers=headers)
            except httpx.TimeoutException as exc:
                raise ParserAdapterTimeoutError("Azure parser submit timed out") from exc
            except httpx.HTTPError as exc:
                raise ParserAdapterTransportError("Azure parser submit transport error") from exc
            if resp.status_code != 202:
                if resp.status_code in {401, 403}:
                    raise ParserAdapterAuthError(f"Azure parser submit failed with status {resp.status_code}")
                raise ParserAdapterContractError(f"Azure parser submit failed with status {resp.status_code}")
            operation_url = resp.headers.get("Operation-Location", "")
            if not operation_url:
                raise ParserAdapterContractError("Azure parser submit response did not include Operation-Location")

            return await self._poll(client, operation_url)

    async def _poll(self, client: httpx.AsyncClient, operation_url: str) -> dict[str, Any]:
        import asyncio
        headers = {"Ocp-Apim-Subscription-Key": _azure_key()}
        for attempt in range(60):  # max ~5 minutes
            await asyncio.sleep(5)
            try:
                resp = await client.get(operation_url, headers=headers)
            except httpx.TimeoutException as exc:
                raise ParserAdapterTimeoutError("Azure parser poll timed out") from exc
            except httpx.HTTPError as exc:
                raise ParserAdapterTransportError("Azure parser poll transport error") from exc
            if resp.status_code != 200:
                if resp.status_code in {401, 403}:
                    raise ParserAdapterAuthError(f"Azure parser poll failed with status {resp.status_code}")
                raise ParserAdapterContractError(f"Azure parser poll failed with status {resp.status_code}")
            result = resp.json()
            status = result.get("status", "")
            if status == "succeeded":
                return result
            if status == "failed":
                raise ParserAdapterContractError("Azure parser analysis failed")
            # running / notStarted — keep polling
        raise ParserAdapterTimeoutError("Azure parser analysis timed out after 60 poll attempts")
