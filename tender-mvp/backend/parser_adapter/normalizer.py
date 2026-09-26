"""
ParsedDocument normalizer — converts Azure Document Intelligence output into
a canonical ParsedDocument structure with typed BOQ rows.

Canonical structure:
    ParsedDocument
        pages: list[Page]
            tables: list[Table]
                rows: list[TableRow]
                    cells: list[Cell]
        boq_rows: list[NormalizedRow]   ← flat, document-order list

NormalizedRow.row_type is one of: heading | metadata | line_item
"""
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# -----------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------

@dataclass
class Cell:
    row_index: int
    col_index: int
    kind: str          # "columnHeader" | "content"
    content: str
    page: int
    polygon: list[float]


@dataclass
class TableRow:
    row_index: int
    cells: list[Cell]

    def cell(self, col: int) -> Optional[Cell]:
        for c in self.cells:
            if c.col_index == col:
                return c
        return None

    def text(self, col: int) -> str:
        c = self.cell(col)
        return c.content.strip() if c else ""


@dataclass
class Table:
    page: int
    rows: list[TableRow]


@dataclass
class NormalizedRow:
    stt: str                    # raw STT cell text (e.g. "7", "II", "IV.1")
    description_vi: str
    unit_raw: str
    quantity_raw: str           # preserved verbatim, e.g. "29,5"
    quantity: Optional[float]   # parsed; None if not a number
    page: int
    polygon: list[float]
    row_type: str               # "heading" | "metadata" | "line_item"
    doc_order: int              # global position across all pages


@dataclass
class ParsedDocument:
    pages: list[dict]           # raw page dicts preserved
    tables: list[Table]
    boq_rows: list[NormalizedRow]
    page_count: int
    model_id: str
    api_version: str


# -----------------------------------------------------------------------
# Heading / metadata detection patterns
# -----------------------------------------------------------------------

# Roman numerals (section headings like I, II, III, IV, V)
_ROMAN = re.compile(r"^(I{1,3}|IV|V?I{0,3}|IX|X{0,3})$", re.IGNORECASE)

# Sub-section headings like I.1, II.2, IV.1
_SUBSECTION = re.compile(r"^(I{1,3}|IV|V?I{0,3})\.\d+$", re.IGNORECASE)

# Metadata-only: subsection label with trailing km/ha/m number (e.g. "IV.1" with "18.57 Km")
_METADATA_CONTENT = re.compile(r"^\d+[,\.]\d+\s*(km|ha|m)\s*$", re.IGNORECASE)

# Pure numeric STT = line_item
_NUMERIC_STT = re.compile(r"^\d+$")


def _classify_row(stt: str, description: str, unit: str, quantity: str) -> str:
    """Return 'heading', 'metadata', or 'line_item'."""
    stt_stripped = stt.strip()
    desc_stripped = description.strip()

    if _NUMERIC_STT.match(stt_stripped) and desc_stripped:
        # Even numeric STT rows can be metadata if unit and quantity are empty
        # and description looks like a group label. But typically they're items.
        if not unit and not quantity and not _looks_like_item_description(desc_stripped):
            return "metadata"
        return "line_item"

    if _ROMAN.match(stt_stripped):
        return "heading"

    if _SUBSECTION.match(stt_stripped):
        # e.g. "IV.1" with description "18.57 Km" → metadata
        if _METADATA_CONTENT.match(desc_stripped) or not unit:
            return "metadata"
        return "heading"  # sub-section without distance label

    if not stt_stripped and desc_stripped:
        return "metadata"

    return "line_item"


def _looks_like_item_description(text: str) -> bool:
    """Heuristic: a proper work-item description is longer than a section title."""
    return len(text.split()) >= 3


def _parse_vn_number(raw: str) -> Optional[float]:
    """
    Parse a Vietnamese-formatted number where comma is the decimal separator.
    e.g. "29,5" → 29.5, "0,030" → 0.030, "342,34" → 342.34, "624" → 624.0
    Returns None if not parseable.
    """
    s = raw.strip()
    if not s:
        return None
    # Replace comma decimal with dot decimal
    # Handle thousands separator: if there's a period followed by 3 digits,
    # treat period as thousands sep — not applicable in this data, but guard it.
    # Simple rule: replace last comma with dot if it looks like decimal
    if "," in s:
        # "29,5" "0,030" "342,34" — comma is decimal separator
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# -----------------------------------------------------------------------
# Normalizer
# -----------------------------------------------------------------------

class DocumentNormalizer:
    """
    Converts the raw Azure Document Intelligence AnalyzedDocument dict
    into a canonical ParsedDocument.
    """

    # Expected column indices in the BOQ table (0-based)
    COL_STT = 0
    COL_DESC = 1
    COL_UNIT = 2
    COL_QTY = 3

    def normalize(self, raw_result: dict[str, Any]) -> ParsedDocument:
        analyze = raw_result.get("analyzeResult", raw_result)
        pages_raw = analyze.get("pages", [])

        # Tables may be top-level OR nested inside pages (fixture uses pages[].tables)
        tables_raw_top = analyze.get("tables", [])
        tables_raw_pages: list[dict] = []
        for page in pages_raw:
            for tbl in page.get("tables", []):
                tables_raw_pages.append(tbl)
        tables_raw = tables_raw_top if tables_raw_top else tables_raw_pages

        tables = self._extract_tables(tables_raw)
        boq_rows = self._extract_boq_rows(tables)

        return ParsedDocument(
            pages=pages_raw,
            tables=tables,
            boq_rows=boq_rows,
            page_count=len(pages_raw),
            model_id=analyze.get("modelId", ""),
            api_version=analyze.get("apiVersion", ""),
        )

    def _extract_tables(self, tables_raw: list[dict]) -> list[Table]:
        tables: list[Table] = []
        for t in tables_raw:
            cells_raw = t.get("cells", [])
            row_map: dict[int, list[Cell]] = {}
            page = 1
            for cr in cells_raw:
                br = cr.get("boundingRegions", [{}])[0]
                pg = br.get("pageNumber", 1)
                page = max(page, pg)
                poly = br.get("polygon", [])
                cell = Cell(
                    row_index=cr["rowIndex"],
                    col_index=cr["columnIndex"],
                    kind=cr.get("kind", "content"),
                    content=cr.get("content", ""),
                    page=pg,
                    polygon=poly,
                )
                row_map.setdefault(cr["rowIndex"], []).append(cell)
            row_objs = [
                TableRow(row_index=ri, cells=cells)
                for ri, cells in sorted(row_map.items())
            ]
            # Get dominant page from cells
            pages_seen = [c.page for row in row_objs for c in row.cells]
            dominant_page = max(set(pages_seen), key=pages_seen.count) if pages_seen else 1
            tables.append(Table(page=dominant_page, rows=row_objs))
        return tables

    def _extract_boq_rows(self, tables: list[Table]) -> list[NormalizedRow]:
        rows: list[NormalizedRow] = []
        doc_order = 0

        for table in tables:
            for row in table.rows:
                # Skip header rows
                if any(c.kind == "columnHeader" for c in row.cells):
                    continue

                stt = row.text(self.COL_STT)
                desc = row.text(self.COL_DESC)
                unit = row.text(self.COL_UNIT)
                qty_raw = row.text(self.COL_QTY)

                # Skip completely empty rows
                if not stt and not desc:
                    continue

                row_type = _classify_row(stt, desc, unit, qty_raw)
                qty = _parse_vn_number(qty_raw) if row_type == "line_item" else None

                # Page from first data cell
                page = next(
                    (c.page for c in row.cells if c.col_index in (self.COL_STT, self.COL_DESC)),
                    table.page,
                )
                poly = next(
                    (c.polygon for c in row.cells if c.col_index == self.COL_STT),
                    [],
                )

                rows.append(NormalizedRow(
                    stt=stt,
                    description_vi=desc,
                    unit_raw=unit,
                    quantity_raw=qty_raw,
                    quantity=qty,
                    page=page,
                    polygon=poly,
                    row_type=row_type,
                    doc_order=doc_order,
                ))
                doc_order += 1

        return rows
