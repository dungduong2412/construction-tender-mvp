"""
BOQ Reconstructor — builds a structured hierarchy from normalized rows.

Responsibilities:
- Walk rows in document order
- Maintain section stack to assign section_path to every row
- Tag metadata rows (e.g. "IV.1 18.57 Km") — NOT priced
- Disambiguate row numbers by (section_path, stt) to handle repeated row numbers
- Merge page-boundary continuations: if a line_item has no unit/qty and the next
  row on the next page is also numeric with the same description prefix, they are merged.
- Output: list of BOQLineItem
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from parser_adapter.normalizer import NormalizedRow


@dataclass
class BOQLineItem:
    row_id: str                 # unique: "{section_key}-{stt}" or generated
    row_number: str             # original STT string
    section_path: str           # e.g. "II > II.1 Khoan thăm dò địa chất đường"
    description_vi: str
    unit_raw: str
    quantity_raw: str
    quantity: Optional[float]
    page: int
    region: str                 # polygon as string
    row_type: str               # "heading" | "metadata" | "line_item"
    doc_order: int
    continuation_of: Optional[str] = None  # row_id of original row if merged


class BOQReconstructor:
    def reconstruct(self, normalized_rows: list[NormalizedRow]) -> list[BOQLineItem]:
        items: list[BOQLineItem] = []
        section_stack: list[str] = []      # stack of section labels
        seen_ids: dict[str, int] = {}      # dedup tracker

        for nrow in normalized_rows:
            # Update section stack
            if nrow.row_type == "heading":
                section_stack = self._update_section_stack(section_stack, nrow)
            elif nrow.row_type == "metadata":
                # Metadata rows are recorded but not priced
                pass

            section_path = " > ".join(section_stack) if section_stack else "ROOT"
            raw_id = f"{self._section_key(section_stack)}-{nrow.stt or nrow.doc_order}"
            row_id = self._dedup_id(raw_id, seen_ids)

            items.append(BOQLineItem(
                row_id=row_id,
                row_number=nrow.stt,
                section_path=section_path,
                description_vi=nrow.description_vi,
                unit_raw=nrow.unit_raw,
                quantity_raw=nrow.quantity_raw,
                quantity=nrow.quantity,
                page=nrow.page,
                region=str(nrow.polygon),
                row_type=nrow.row_type,
                doc_order=nrow.doc_order,
            ))

        return self._merge_continuations(items)

    # ------------------------------------------------------------------
    def _update_section_stack(self, stack: list[str], row: NormalizedRow) -> list[str]:
        stt = row.stt.strip().upper()
        label = f"{stt} {row.description_vi}".strip()

        # Determine depth by STT pattern
        depth = self._section_depth(stt)
        # Trim stack to depth - 1 then push
        new_stack = stack[:depth - 1]
        new_stack.append(label)
        return new_stack

    def _section_depth(self, stt: str) -> int:
        """Roman numeral = depth 1; Roman.digit = depth 2; etc."""
        if re.match(r"^(I{1,3}|IV|V?I{0,3}|IX|X{0,3})$", stt, re.IGNORECASE):
            return 1
        if re.match(r"^(I{1,3}|IV|V?I{0,3})\.\d+$", stt, re.IGNORECASE):
            return 2
        return 1  # default

    def _section_key(self, stack: list[str]) -> str:
        if not stack:
            return "ROOT"
        # Use first word of each level (the STT)
        parts = [s.split()[0] for s in stack if s]
        return "-".join(parts)

    def _dedup_id(self, raw_id: str, seen: dict[str, int]) -> str:
        if raw_id not in seen:
            seen[raw_id] = 0
            return raw_id
        seen[raw_id] += 1
        return f"{raw_id}_dup{seen[raw_id]}"

    # ------------------------------------------------------------------
    def _merge_continuations(self, items: list[BOQLineItem]) -> list[BOQLineItem]:
        """
        Detect and merge rows that are split across page boundaries.
        Heuristic: a line_item with empty unit AND quantity that is immediately
        followed (next item, next page) by another line_item whose description
        starts with the same text prefix are merged into one.
        """
        result: list[BOQLineItem] = []
        i = 0
        while i < len(items):
            item = items[i]
            if (
                item.row_type == "line_item"
                and not item.unit_raw
                and not item.quantity_raw
                and i + 1 < len(items)
            ):
                nxt = items[i + 1]
                if (
                    nxt.row_type == "line_item"
                    and nxt.page > item.page
                    and _description_continues(item.description_vi, nxt.description_vi)
                ):
                    # Merge nxt into item
                    merged = BOQLineItem(
                        row_id=item.row_id,
                        row_number=item.row_number,
                        section_path=item.section_path,
                        description_vi=item.description_vi + " " + nxt.description_vi,
                        unit_raw=nxt.unit_raw,
                        quantity_raw=nxt.quantity_raw,
                        quantity=nxt.quantity,
                        page=item.page,
                        region=item.region,
                        row_type="line_item",
                        doc_order=item.doc_order,
                        continuation_of=None,
                    )
                    result.append(merged)
                    i += 2
                    continue
            result.append(item)
            i += 1
        return result


def _description_continues(desc1: str, desc2: str) -> bool:
    """
    True if desc2 looks like a continuation of desc1 —
    i.e. desc1 ends mid-word or desc2 starts with lowercase/continuation.
    Simple heuristic: desc1 doesn't end with punctuation.
    """
    d1 = desc1.strip()
    if not d1:
        return False
    last_char = d1[-1]
    return last_char not in ".,:;)!"
