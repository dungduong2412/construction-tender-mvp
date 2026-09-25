from __future__ import annotations

import hashlib
from typing import Any

from parser_adapter.adapter import ParserAdapter, ParserAdapterError
from parser_adapter.normalizer import _classify_row, _parse_vn_number
from parser_adapter.provider_neutral import (
    ParserEvidence,
    ParserPayload,
    ParserProviderContractError,
)


def _document_id_from_bytes(document_bytes: bytes) -> str:
    digest = hashlib.sha256(document_bytes).hexdigest()[:16]
    return f"azure-doc-intel-{digest}"


def _collect_tables(analyze: dict[str, Any]) -> list[dict[str, Any]]:
    tables_raw = list(analyze.get("tables", []) or [])
    if tables_raw:
        return tables_raw

    tables_from_pages: list[dict[str, Any]] = []
    for page in analyze.get("pages", []) or []:
        if not isinstance(page, dict):
            raise ParserProviderContractError("Azure analyzeResult pages must be a list of objects")
        tables_from_pages.extend(page.get("tables", []) or [])
    return tables_from_pages


def _row_evidence(page_number: int, table_index: int, row_index: int, cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for cell in sorted(cells, key=lambda item: int(item.get("columnIndex", 0))):
        content = str(cell.get("content") or "").strip()
        if not content:
            continue
        regions = cell.get("boundingRegions") or [{}]
        region = regions[0] or {}
        cell_page = int(region.get("pageNumber") or page_number or 1)
        locator = f"p{cell_page}:tbl{table_index}:r{row_index}:c{int(cell.get('columnIndex', 0))}"
        evidence.append(ParserEvidence(type="azure_table_cell", locator=locator, text=content).model_dump())
    return evidence


def azure_analyze_result_to_parser_payload(raw_result: dict[str, Any], document_id: str) -> dict[str, Any]:
    analyze = raw_result.get("analyzeResult", raw_result)
    if not isinstance(analyze, dict):
        raise ParserProviderContractError("Azure analyzeResult payload must be a JSON object")

    tables = _collect_tables(analyze)
    if not isinstance(tables, list):
        raise ParserProviderContractError("Azure analyzeResult tables must be a list")

    rows: list[dict[str, Any]] = []

    for table_index, table in enumerate(tables, start=1):
        cells_raw = table.get("cells", []) if isinstance(table, dict) else []
        if not isinstance(cells_raw, list):
            raise ParserProviderContractError("Azure table cells must be a list")

        row_map: dict[int, list[dict[str, Any]]] = {}
        row_pages: dict[int, int] = {}
        for cell in cells_raw:
            if not isinstance(cell, dict):
                continue
            row_index = int(cell.get("rowIndex", 0))
            row_map.setdefault(row_index, []).append(cell)
            region = (cell.get("boundingRegions") or [{}])[0] or {}
            page_number = int(region.get("pageNumber") or 1)
            row_pages[row_index] = max(row_pages.get(row_index, 1), page_number)

        for row_index in sorted(row_map):
            cells = sorted(row_map[row_index], key=lambda item: int(item.get("columnIndex", 0)))
            if any(str(cell.get("kind") or "").strip() == "columnHeader" for cell in cells):
                continue

            stt = str(cells[0].get("content") or "").strip() if len(cells) > 0 else ""
            desc = str(cells[1].get("content") or "").strip() if len(cells) > 1 else ""
            unit = str(cells[2].get("content") or "").strip() if len(cells) > 2 else ""
            qty_raw = str(cells[3].get("content") or "").strip() if len(cells) > 3 else ""

            if not stt and not desc:
                continue

            row_type = _classify_row(stt, desc, unit, qty_raw)
            page_number = row_pages.get(row_index, 1)

            rows.append(
                {
                    "row_id": f"azure-p{page_number}-t{table_index}-r{row_index}",
                    "row_type": row_type,
                    "description_vi": desc,
                    "unit_raw": unit,
                    "quantity_raw": qty_raw,
                    "page": page_number,
                    "evidence": _row_evidence(page_number, table_index, row_index, cells),
                    "ai_suggestions": [],
                }
            )

    payload = ParserPayload.model_validate(
        {
            "document_id": document_id,
            "provider": "azure-document-intelligence",
            "rows": rows,
        }
    )
    return payload.model_dump()


class AzureDocumentIntelligenceProvider:
    def __init__(self, adapter: ParserAdapter | None = None):
        self.adapter = adapter or ParserAdapter()

    async def analyze(self, document_bytes: bytes | None = None) -> dict[str, Any]:
        if document_bytes is None:
            raise ParserAdapterError("Azure parser requires PDF bytes")
        raw_result = await self.adapter.analyze(document_bytes)
        document_id = _document_id_from_bytes(document_bytes)
        return azure_analyze_result_to_parser_payload(raw_result, document_id)