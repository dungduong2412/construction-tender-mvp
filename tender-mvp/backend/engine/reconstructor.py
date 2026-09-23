"""
BOQ Reconstructor
=================
Converts a ParsedDocument into a BOQDocument with explicit hierarchy,
distinguishing section headings, metadata rows and billable line items.

Key rules implemented:
- Repeated row numbers under different section headings get unique row_ids
- IV.1 18.57 Km group metadata is classified as METADATA, not a line item
- Page-continuation headings (marked "tiếp") preserve section context
- Comma-decimal quantities (Vietnamese notation) are parsed correctly
- Zero is never the default for a missing quantity – None is used instead
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..models.domain import (
    BOQDocument,
    BOQRow,
    ParsedDocument,
    ParsedTable,
    RowType,
)

# Roman numerals and section codes used in Vietnamese BOQ headings
_SECTION_HEADING_PATTERNS = [
    re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)(\.[\w]+)?$"),
    re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)\b.{0,80}$", re.IGNORECASE),
]

# Patterns that identify metadata rows (not billable)
_METADATA_PATTERNS = [
    re.compile(r"\d+[,\.]\d+\s*[Kk][Mm]\b"),  # "18,57 Km" group label
    re.compile(r"tiếp\s*theo\s*trang", re.IGNORECASE),  # "Tiếp theo trang"
    re.compile(r"^\(.*tiếp.*\)$", re.IGNORECASE),       # "(tiếp)"
    re.compile(r"tổng\s*hợp\s*dự\s*toán", re.IGNORECASE),
    re.compile(r"cộng\s*chi\s*phí", re.IGNORECASE),
    re.compile(r"thuế\s*vat", re.IGNORECASE),
    re.compile(r"tổng\s*cộng", re.IGNORECASE),
    re.compile(r"thu\s*nhập\s*chịu\s*thuế", re.IGNORECASE),
    re.compile(r"chi\s*phí\s*chung", re.IGNORECASE),
]

# Known continuation headings that should NOT reset the section
_CONTINUATION_PATTERN = re.compile(r"\(tiếp\)", re.IGNORECASE)

# Roman numeral heading with sub-key like "IV.1"
_SUB_SECTION_PATTERN = re.compile(r"^(I{1,3}V?|V?I{0,3})(\.[\w]+)+$")


def _is_section_heading(tt: str, description: str) -> bool:
    """True if the TT column value looks like a section identifier."""
    stripped = tt.strip()
    if re.match(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)(\.[\w]+)?$", stripped):
        return True
    return False


def _is_metadata(tt: str, description: str) -> bool:
    """True if the row is contextual metadata, not a billable item."""
    combined = f"{tt} {description}"
    for p in _METADATA_PATTERNS:
        if p.search(combined):
            return True
    # Check sub-section patterns like IV.1
    if re.match(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\w+$", tt.strip()):
        return True
    return False


def _parse_vi_decimal(raw: Optional[str]) -> Optional[Decimal]:
    """
    Parse Vietnamese comma-decimal notation.
    '29,5' → Decimal('29.5'), '2,50' → Decimal('2.50'), '42' → Decimal('42')
    Returns None if blank; raises on unparseable non-blank input.
    """
    if not raw or not raw.strip():
        return None
    # Replace comma decimal separator (Vietnamese) with period
    normalised = raw.strip().replace(",", ".")
    # Remove thousands separators if any (period used as separator → already replaced above,
    # so only plain numbers remain after the replace)
    try:
        return Decimal(normalised)
    except InvalidOperation:
        return None


def _extract_table_rows(table: ParsedTable) -> list[dict]:
    """
    Convert a ParsedTable cells list into a list of row dicts keyed by col_index.
    """
    rows: dict[int, dict[int, str]] = {}
    for cell in table.cells:
        rows.setdefault(cell.row_index, {})[cell.col_index] = cell.text
    return [rows[r] for r in sorted(rows.keys())]


def reconstruct_boq(parsed: ParsedDocument) -> BOQDocument:
    """
    Walk all pages and their tables in document order.
    Return a BOQDocument with fully typed BOQRows.
    """
    rows: list[BOQRow] = []
    current_section = ""
    current_section_label = ""
    row_counter = 0

    for page in sorted(parsed.pages, key=lambda p: p.page_number):
        for table in page.tables:
            table_rows = _extract_table_rows(table)

            for row_dict in table_rows:
                tt = row_dict.get(0, "").strip()
                description = row_dict.get(1, "").strip()
                unit_raw = row_dict.get(2, "").strip() or None
                qty_raw = row_dict.get(3, "").strip() or None

                if not description and not tt:
                    continue

                row_counter += 1
                row_id = f"p{page.page_number}_t{table.table_index}_r{row_counter}"

                # ------------------------------------------------------------------
                # Classify row type
                # ------------------------------------------------------------------
                if _is_metadata(tt, description):
                    row_type = RowType.METADATA
                    # If this is a new section group like IV.1, update metadata context
                    if re.match(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\w+$", tt):
                        current_section = tt
                        current_section_label = description
                elif _is_section_heading(tt, description):
                    row_type = RowType.SECTION_HEADING
                    # Update section context (skip continuation headings)
                    if not _CONTINUATION_PATTERN.search(description):
                        current_section = tt
                        current_section_label = description
                else:
                    row_type = RowType.LINE_ITEM

                quantity = None
                if row_type == RowType.LINE_ITEM:
                    quantity = _parse_vi_decimal(qty_raw)

                boq_row = BOQRow(
                    row_id=row_id,
                    page_number=page.page_number,
                    source_section=current_section,
                    section_label=current_section_label,
                    row_number_raw=tt if row_type == RowType.LINE_ITEM else None,
                    row_type=row_type,
                    description_vi=description,
                    unit_raw=unit_raw,
                    quantity_raw=qty_raw,
                    quantity=quantity,
                )
                rows.append(boq_row)

    return BOQDocument(
        job_id=parsed.job_id,
        rows=rows,
        metadata={
            "page_count": parsed.page_count,
            "source_filename": parsed.source_filename,
        },
    )
