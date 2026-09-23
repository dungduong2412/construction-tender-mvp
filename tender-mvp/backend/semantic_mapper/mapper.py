"""
Semantic Mapper — calls OpenAI to match BOQ line items to master data.

Contract:
- Input: BOQLineItem + section_path context + top-N master candidates
- Output: MappingOutput (JSON validated against strict schema)
- The LLM NEVER calculates monetary amounts.
- Hard-coded distinction rules applied BEFORE calling the LLM.
- Responses are cached by (row_id, master_version).

Output schema:
{
  "master_item_id": <int or null>,
  "confidence": <float 0-1>,
  "tags": {
    "survey_discipline": <str or null>,
    "road_bridge_context": <"road"|"bridge"|null>,
    "work_method": <str or null>,
    "terrain_class": <str or null>,
    "scale": <str or null>,
    "water_on_land": <"water"|"on_land"|null>,
    "drilling_depth": <str or null>,
    "soil_rock_class": <str or null>,
    "unit_match": <bool or null>
  },
  "evidence": <str>,
  "unresolved_reason": <str or null>
}
"""
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import jsonschema

from boq.reconstructor import BOQLineItem

try:
    from openai import AsyncOpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MOCK_AI = os.getenv("MOCK_AI", "false").lower() in ("1", "true", "yes")

# Strict output schema
MAPPING_SCHEMA = {
    "type": "object",
    "required": ["master_item_id", "confidence", "tags", "evidence"],
    "properties": {
        "master_item_id": {"type": ["integer", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "tags": {
            "type": "object",
            "properties": {
                "survey_discipline": {"type": ["string", "null"]},
                "road_bridge_context": {"type": ["string", "null"], "enum": ["road", "bridge", None]},
                "work_method": {"type": ["string", "null"]},
                "terrain_class": {"type": ["string", "null"]},
                "scale": {"type": ["string", "null"]},
                "water_on_land": {"type": ["string", "null"], "enum": ["water", "on_land", None]},
                "drilling_depth": {"type": ["string", "null"]},
                "soil_rock_class": {"type": ["string", "null"]},
                "unit_match": {"type": ["boolean", "null"]},
            },
            "additionalProperties": False,
        },
        "evidence": {"type": "string"},
        "unresolved_reason": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


@dataclass
class MasterCandidate:
    id: int
    item_code: str
    description_vi: str
    unit: str
    unit_price: float
    tags: dict


@dataclass
class MappingOutput:
    master_item_id: Optional[int]
    confidence: float
    tags: dict
    evidence: str
    unresolved_reason: Optional[str]
    status: str  # "resolved" | "unresolved" | "error"


# ------------------------------------------------------------------
# Hard-coded distinction guard
# ------------------------------------------------------------------

def _apply_distinction_rules(
    item: BOQLineItem,
    candidates: list[MasterCandidate],
) -> list[MasterCandidate]:
    """
    Enforce non-negotiable distinction rules by filtering candidates.
    Road drilling 0-30m ≠ Bridge drilling 0-60m.
    """
    desc_lower = item.description_vi.lower()

    is_road_drill = "đường" in desc_lower and "khoan" in desc_lower
    is_bridge_drill = "cầu" in desc_lower and "khoan" in desc_lower

    if is_road_drill and not is_bridge_drill:
        candidates = [c for c in candidates if c.tags.get("road_bridge_context") != "bridge"]
    elif is_bridge_drill and not is_road_drill:
        candidates = [c for c in candidates if c.tags.get("road_bridge_context") != "road"]

    return candidates


def _unit_mismatch_check(item_unit: str, candidate_unit: str) -> bool:
    """
    Returns True if units are compatible WITHOUT an explicit unit rule.
    Flagged mismatches: ha vs 100ha, m vs 100m, TN vs thí nghiệm
    """
    FORBIDDEN_SILENT = {
        frozenset(["ha", "100ha"]),
        frozenset(["m", "100m"]),
        frozenset(["tn", "thí nghiệm"]),
        frozenset(["tn", "thi nghiem"]),
    }
    pair = frozenset([item_unit.strip().lower(), candidate_unit.strip().lower()])
    return pair not in FORBIDDEN_SILENT


# ------------------------------------------------------------------
# Semantic mapper
# ------------------------------------------------------------------

class SemanticMapper:
    def __init__(self):
        self._cache: dict[tuple, MappingOutput] = {}
        if _OPENAI_AVAILABLE and OPENAI_API_KEY:
            self._client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        else:
            self._client = None

    async def map_item(
        self,
        item: BOQLineItem,
        candidates: list[MasterCandidate],
        master_version: str = "v1",
    ) -> MappingOutput:
        cache_key = (item.row_id, master_version)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Not a line item — don't map
        if item.row_type != "line_item":
            out = MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="Row is not a billable line item.",
                unresolved_reason="Not a line item — heading or metadata.",
                status="error",
            )
            self._cache[cache_key] = out
            return out

        # Apply hard-coded distinction rules
        filtered = _apply_distinction_rules(item, candidates)

        # Filter out silent unit mismatches
        unit_filtered = [
            c for c in filtered
            if _unit_mismatch_check(item.unit_raw, c.unit)
        ]

        if not unit_filtered and filtered:
            # All candidates had unit mismatches
            out = MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="All candidates have unit mismatches with no approved unit rule.",
                unresolved_reason=(
                    f"Unit mismatch: PDF unit '{item.unit_raw}' vs candidate units "
                    f"{[c.unit for c in filtered]}"
                ),
                status="unresolved",
            )
            self._cache[cache_key] = out
            return out

        effective_candidates = unit_filtered if unit_filtered else filtered

        if MOCK_AI or not self._client:
            out = self._mock_map(item, effective_candidates)
        else:
            out = await self._ai_map(item, effective_candidates)

        self._cache[cache_key] = out
        return out

    # ------------------------------------------------------------------
    def _mock_map(self, item: BOQLineItem, candidates: list[MasterCandidate]) -> MappingOutput:
        """Deterministic mock: pick first candidate if any."""
        if not candidates:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="No candidates available.",
                unresolved_reason="No matching master data candidates found.",
                status="unresolved",
            )
        best = candidates[0]
        return MappingOutput(
            master_item_id=best.id,
            confidence=0.75,
            tags=best.tags,
            evidence=f"[MOCK] Matched to '{best.description_vi}' (code: {best.item_code}) by first-candidate heuristic.",
            unresolved_reason=None,
            status="resolved",
        )

    # ------------------------------------------------------------------
    async def _ai_map(self, item: BOQLineItem, candidates: list[MasterCandidate]) -> MappingOutput:
        candidates_json = json.dumps(
            [
                {
                    "id": c.id,
                    "item_code": c.item_code,
                    "description_vi": c.description_vi,
                    "unit": c.unit,
                    "tags": c.tags,
                }
                for c in candidates
            ],
            ensure_ascii=False,
            indent=2,
        )

        prompt = f"""You are a Vietnamese construction survey BOQ specialist.
Your task: select the best matching master item for the BOQ line item below, or return unresolved.

BOQ LINE ITEM:
- Section path: {item.section_path}
- Description (Vietnamese): {item.description_vi}
- Unit: {item.unit_raw}
- Quantity (raw): {item.quantity_raw}
- Page: {item.page}

MASTER CANDIDATES:
{candidates_json}

RULES:
1. Return ONLY valid JSON matching the schema. Do NOT calculate any monetary amounts.
2. Road drilling 0-30m is DISTINCT from bridge drilling 0-60m — they must map to different items.
3. Never conflate ha with 100ha, m with 100m, TN with thí nghiệm without explicit approval.
4. If no candidate is a confident match, set master_item_id to null and provide unresolved_reason.
5. Extract tags only from evidence in the PDF description and master record; never invent attributes.

OUTPUT SCHEMA:
{{
  "master_item_id": <integer id from candidates, or null>,
  "confidence": <float 0.0-1.0>,
  "tags": {{
    "survey_discipline": <string or null>,
    "road_bridge_context": <"road"|"bridge"|null>,
    "work_method": <string or null>,
    "terrain_class": <string or null>,
    "scale": <string or null>,
    "water_on_land": <"water"|"on_land"|null>,
    "drilling_depth": <string or null>,
    "soil_rock_class": <string or null>,
    "unit_match": <true|false|null>
  }},
  "evidence": <string explaining your reasoning>,
  "unresolved_reason": <string if unresolved, else null>
}}"""

        try:
            resp = await self._client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw_json = resp.choices[0].message.content or "{}"
            data = json.loads(raw_json)
            jsonschema.validate(data, MAPPING_SCHEMA)

            status = "resolved" if data.get("master_item_id") is not None else "unresolved"
            return MappingOutput(
                master_item_id=data.get("master_item_id"),
                confidence=float(data.get("confidence", 0)),
                tags=data.get("tags", {}),
                evidence=data.get("evidence", ""),
                unresolved_reason=data.get("unresolved_reason"),
                status=status,
            )
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence=f"AI response failed schema validation: {exc}",
                unresolved_reason="AI returned invalid JSON or schema mismatch.",
                status="unresolved",
            )
        except Exception as exc:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence=f"AI call error: {exc}",
                unresolved_reason=f"AI mapping failed: {exc}",
                status="error",
            )
