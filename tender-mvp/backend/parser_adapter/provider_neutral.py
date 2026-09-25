from __future__ import annotations

import json
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx


class ParserProviderError(Exception):
    pass


class ParserProvider(Protocol):
    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        ...


@dataclass
class RecordedFixtureProvider:
    fixture_path: Path

    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        if not self.fixture_path.exists():
            raise ParserProviderError(f"Fixture not found: {self.fixture_path}")
        return json.loads(self.fixture_path.read_text(encoding="utf-8"))


@dataclass
class HttpJsonProvider:
    endpoint: str
    api_key: str | None = None
    timeout_seconds: float = 30.0

    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {}
        if document_bytes is not None:
            payload["document_base64"] = base64.b64encode(document_bytes).decode("ascii")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(self.endpoint, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise ParserProviderError(
                    f"Parser provider request failed: {resp.status_code} {resp.text[:400]}"
                )
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise ParserProviderError("Parser provider returned non-JSON response") from exc


class ProviderNeutralParserAdapter:
    """Provider-neutral parser adapter for external parser APIs.

    Expected payload contract:
    {
      "document_id": "...",
      "rows": [
        {
          "row_id": "...",
          "row_type": "line_item|heading|metadata",
          "description_vi": "...",
          "unit_raw": "...",
          "quantity_raw": "...",
          "page": 1,
          "evidence": [{"type": "pdf_span", "locator": "p1:...", "text": "..."}],
          "ai_suggestions": [{"code": "CF.11620", "confidence": 0.91, "evidence": "..."}]
        }
      ]
    }

    The adapter does not hardwire any cloud provider behavior.
    """

    def __init__(self, provider: ParserProvider):
        self.provider = provider

    async def parse(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        payload = await self.provider.analyze(document_bytes)
        if not isinstance(payload, dict):
            raise ParserProviderError("Parser payload must be a JSON object")
        if "rows" not in payload or not isinstance(payload["rows"], list):
            raise ParserProviderError("Parser payload must include a 'rows' array")
        return payload
