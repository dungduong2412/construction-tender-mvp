from __future__ import annotations

import json
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ParserProviderError(Exception):
    pass


class ParserProviderAuthError(ParserProviderError):
    pass


class ParserProviderTimeoutError(ParserProviderError):
    pass


class ParserProviderContractError(ParserProviderError):
    pass


class ParserEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: str
    locator: str
    text: str = ""


class ParserSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str
    confidence: float = Field(ge=0, le=1)
    evidence: str = ""
    source: str | None = None


class ParserRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    row_id: str
    row_type: str
    description_vi: str
    unit_raw: str = ""
    quantity_raw: str = ""
    page: int = Field(ge=1)
    evidence: list[ParserEvidence] = Field(default_factory=list)
    ai_suggestions: list[ParserSuggestion] = Field(default_factory=list)
    manual_selected_code: str | None = None
    manual_unit_confirmed: bool = False
    manual_unit_correction: str | None = None


class ParserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str
    provider: str | None = None
    rows: list[ParserRow]

    @model_validator(mode="after")
    def validate_unique_row_ids(self) -> "ParserPayload":
        seen: set[str] = set()
        dupes: set[str] = set()
        for row in self.rows:
            if row.row_id in seen:
                dupes.add(row.row_id)
            seen.add(row.row_id)
        if dupes:
            dupes_text = ", ".join(sorted(dupes))
            raise ValueError(f"Duplicate row_id values in parser payload: {dupes_text}")
        return self

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ParserProvider(Protocol):
    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        ...


@dataclass
class RecordedFixtureProvider:
    fixture_path: Path

    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        if not self.fixture_path.exists():
            raise ParserProviderError(f"Fixture not found: {self.fixture_path}")
        try:
            return json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ParserProviderContractError(f"Fixture is not valid JSON: {self.fixture_path}") from exc


@dataclass
class HttpJsonProvider:
    endpoint: str
    api_key: str | None = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer"
    timeout_seconds: float = 30.0

    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            if self.api_key_header.lower() == "authorization":
                headers[self.api_key_header] = f"{self.api_key_prefix} {self.api_key}".strip()
            else:
                headers[self.api_key_header] = self.api_key

        payload: dict[str, Any] = {}
        if document_bytes is not None:
            payload["document_base64"] = base64.b64encode(document_bytes).decode("ascii")

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(self.endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ParserProviderTimeoutError(f"Parser provider request timed out after {self.timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise ParserProviderError(f"Parser provider transport error: {exc}") from exc

        if resp.status_code in {401, 403}:
            raise ParserProviderAuthError(
                f"Parser provider authentication failed: {resp.status_code} {resp.text[:400]}"
            )
        if resp.status_code >= 400:
            raise ParserProviderError(
                f"Parser provider request failed: {resp.status_code} {resp.text[:400]}"
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise ParserProviderContractError("Parser provider returned non-JSON response") from exc


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
            raise ParserProviderContractError("Parser payload must be a JSON object")
        try:
            model = ParserPayload.model_validate(payload)
        except ValidationError as exc:
            raise ParserProviderContractError(f"Parser payload contract validation failed: {exc}") from exc
        return model.as_dict()
