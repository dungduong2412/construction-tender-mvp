from __future__ import annotations

import hashlib
from typing import Any

from parser_adapter.adapter import (
    ParserAdapter,
    ParserAdapterAuthError,
    ParserAdapterContractError,
    ParserAdapterError,
    ParserAdapterTimeoutError,
    ParserAdapterTransportError,
)
from parser_adapter.normalizer import _classify_row, _parse_vn_number
from parser_adapter.provider_neutral import (
    ParserEvidence,
    ParserPayload,
    ParserProviderContractError,
    ParserProviderAuthError,
    ParserProviderError,
    ParserProviderTimeoutError,
)


def _document_id_from_bytes(document_bytes: bytes) -> str:
    digest = hashlib.sha256(document_bytes).hexdigest()[:16]
    return f"azure-doc-intel-{digest}"


def _collect_tables(analyze: dict[str, Any]) -> list[dict[str, Any]]:
    tables_raw = list(analyze.get("tables", []) or [])
    if tables_raw:
        if not all(isinstance(tbl, dict) for tbl in tables_raw):
            raise ParserProviderContractError("Azure analyzeResult tables must be objects")
        return tables_raw

    tables_from_pages: list[dict[str, Any]] = []
    for page in analyze.get("pages", []) or []:
        if not isinstance(page, dict):
            raise ParserProviderContractError("Azure analyzeResult pages must be a list of objects")
        tables_from_pages.extend(page.get("tables", []) or [])
    return tables_from_pages


def _require_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ParserProviderContractError(f"Azure analyzeResult cell field '{field_name}' must be an integer") from exc


def _cell_region(cell: dict[str, Any]) -> tuple[int, list[float]]:
    regions = cell.get("boundingRegions")
    if not isinstance(regions, list) or not regions:
        raise ParserProviderContractError("Azure analyzeResult cell requires boundingRegions")
    first_region = regions[0]
    if not isinstance(first_region, dict):
        raise ParserProviderContractError("Azure analyzeResult boundingRegions entries must be objects")
    page_number = _require_int(first_region.get("pageNumber", 1), "pageNumber")
    polygon_raw = first_region.get("polygon", [])
    if not isinstance(polygon_raw, list):
        raise ParserProviderContractError("Azure analyzeResult polygon must be a list")
    polygon: list[float] = []
    for point in polygon_raw:
        try:
            polygon.append(float(point))
        except (TypeError, ValueError) as exc:
            raise ParserProviderContractError("Azure analyzeResult polygon values must be numeric") from exc
    return page_number, polygon


def _row_evidence(page_number: int, table_index: int, row_index: int, cells: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for column_index in sorted(cells):
        cell = cells[column_index]
        content = str(cell.get("content") or "").strip()
        if not content:
            continue
        cell_page, polygon = _cell_region(cell)
        locator = f"p{cell_page}:tbl{table_index}:r{row_index}:c{column_index}"
        evidence.append(
            ParserEvidence(
                type="azure_table_cell",
                locator=locator,
                text=content,
                page=cell_page,
                table=table_index,
                row=row_index,
                column=column_index,
                polygon=polygon,
            ).model_dump()
        )
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
        if not isinstance(table, dict):
            raise ParserProviderContractError("Azure analyzeResult table must be an object")
        cells_raw = table.get("cells", [])
        if not isinstance(cells_raw, list):
            raise ParserProviderContractError("Azure table cells must be a list")

        row_map: dict[int, dict[int, dict[str, Any]]] = {}
        row_pages: dict[int, int] = {}
        for cell in cells_raw:
            if not isinstance(cell, dict):
                raise ParserProviderContractError("Azure analyzeResult cells must be objects")
            row_index = _require_int(cell.get("rowIndex"), "rowIndex")
            column_index = _require_int(cell.get("columnIndex"), "columnIndex")
            row_cells = row_map.setdefault(row_index, {})
            if column_index in row_cells:
                raise ParserProviderContractError("Azure analyzeResult table contains duplicate cell coordinates")
            row_cells[column_index] = cell
            page_number, _ = _cell_region(cell)
            row_pages[row_index] = max(row_pages.get(row_index, 1), page_number)

        for row_index in sorted(row_map):
            row_cells = row_map[row_index]
            cells = row_cells
            row_has_content = any(str(cell.get("content") or "").strip() for cell in cells.values())
            if not row_has_content:
                continue
            if any(str(cell.get("kind") or "").strip() == "columnHeader" for cell in cells.values()):
                continue

            stt = str(cells.get(0, {}).get("content") or "").strip()
            desc = str(cells.get(1, {}).get("content") or "").strip()
            unit = str(cells.get(2, {}).get("content") or "").strip()
            qty_raw = str(cells.get(3, {}).get("content") or "").strip()

            if not stt and not desc and not unit and not qty_raw:
                continue

            row_type = _classify_row(stt, desc, unit, qty_raw)
            page_number = row_pages.get(row_index, 1)
            if row_type == "line_item" and (not stt or not desc):
                raise ParserProviderContractError("Azure analyzeResult line items must include STT and description cells")

            rows.append(
                {
                    "row_id": f"azure-p{page_number}-t{table_index}-r{row_index}",
                    "row_type": row_type,
                    "description_vi": desc,
                    "unit_raw": unit,
                    "quantity_raw": qty_raw,
                    "page": page_number,
                    "evidence": _row_evidence(page_number, table_index, row_index, row_cells),
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
            raise ParserProviderContractError("Azure parser requires PDF bytes")
        try:
            raw_result = await self.adapter.analyze(document_bytes)
        except ParserAdapterAuthError as exc:
            raise ParserProviderAuthError(str(exc)) from exc
        except ParserAdapterTimeoutError as exc:
            raise ParserProviderTimeoutError(str(exc)) from exc
        except ParserAdapterTransportError as exc:
            raise ParserProviderError(str(exc)) from exc
        except ParserAdapterContractError as exc:
            raise ParserProviderContractError(str(exc)) from exc
        except ParserAdapterError as exc:
            raise ParserProviderError(str(exc)) from exc
        document_id = _document_id_from_bytes(document_bytes)
        return azure_analyze_result_to_parser_payload(raw_result, document_id)