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
import re
import unicodedata
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
    status: str
    classification: Optional[str] = None


def _normalize_mapping_status(status: Optional[str]) -> Optional[str]:
    if status in {"mapped_and_priced", "resolved"}:
        return "mapped_and_priced"
    if status in {"mapped_price_unavailable", "unresolved"}:
        return "mapped_price_unavailable"
    if status in {"mapping_ambiguous"}:
        return "mapping_ambiguous"
    if status in {"mapping_unresolved", "error"}:
        return "mapping_unresolved"
    if status in {"invalid_quantity_or_unit"}:
        return "invalid_quantity_or_unit"
    if status in {"non_billable_heading"}:
        return "non_billable_heading"
    if status in {"non_billable_metadata"}:
        return "non_billable_metadata"
    return status


def _normalize_text(value: str) -> str:
    lowered = (value or "").lower().replace("–", "-").replace("—", "-")
    lowered = lowered.replace("đ", "d")
    return "".join(
        ch for ch in unicodedata.normalize("NFD", lowered)
        if unicodedata.category(ch) != "Mn"
    )


def _extract_row_features(item: BOQLineItem) -> dict[str, Optional[str]]:
    text = _normalize_text(f"{item.section_path} {item.description_vi}")
    features: dict[str, Optional[str]] = {
        "survey_discipline": None,
        "road_bridge_context": None,
        "terrain_class": None,
        "scale": None,
        "work_method": None,
        "drilling_depth": None,
        "soil_rock_class": None,
    }

    scale_match = re.search(r"1\s*/\s*(200|500)", text)
    if scale_match:
        features["scale"] = f"1/{scale_match.group(1)}"

    if "doi nui" in text:
        features["terrain_class"] = "hilly"
    elif "dong bang" in text:
        features["terrain_class"] = "plain"

    if "spt" in text or "xuyen tieu chuan" in text:
        features["survey_discipline"] = "in_situ_testing"
        features["work_method"] = "SPT"
    elif "mau dat nguyen dang" in text or ("lay mau" in text and "dat" in text):
        features["survey_discipline"] = "sample_collection"
    elif "do ve" in text or "binh do" in text:
        features["survey_discipline"] = "topography"
    elif "trac doc" in text or "mat cat doc" in text:
        features["survey_discipline"] = "longitudinal_section"
    elif "trac ngang" in text or "mat cat ngang" in text:
        features["survey_discipline"] = "cross_section"
    elif "khoan" in text and "dia chat" in text:
        features["survey_discipline"] = "geotechnical_drilling"

    if features["survey_discipline"] == "geotechnical_drilling":
        if "duong" in text and "cau" not in text:
            features["road_bridge_context"] = "road"
        elif "cau" in text and "duong" not in text:
            features["road_bridge_context"] = "bridge"

        if "0-30m" in text:
            features["drilling_depth"] = "0-30m"
        elif "0-60m" in text:
            features["drilling_depth"] = "0-60m"

        if "cap iii" in text or "cap 3" in text:
            features["soil_rock_class"] = "dat_cap_III"
        elif "cap ii" in text or "cap 2" in text:
            features["soil_rock_class"] = "dat_cap_II"

    return features


def _tag_value(candidate: MasterCandidate, key: str) -> Optional[str]:
    value = (candidate.tags or {}).get(key)
    if value is None:
        return None
    return str(value)


def _is_hard_compatible(
    item: BOQLineItem,
    candidate: MasterCandidate,
    features: dict[str, Optional[str]],
) -> bool:
    item_unit = (item.unit_raw or "").strip()
    if item_unit and not _units_are_compatible(item_unit, candidate.unit):
        return False

    discipline = features.get("survey_discipline")
    if discipline:
        cand_discipline = _tag_value(candidate, "survey_discipline")
        if cand_discipline != discipline:
            return False

    for feature_key, tag_key in (
        ("scale", "scale"),
        ("terrain_class", "terrain_class"),
        ("work_method", "work_method"),
    ):
        expected = features.get(feature_key)
        if expected:
            actual = _tag_value(candidate, tag_key)
            if actual is None or _normalize_text(actual) != _normalize_text(expected):
                return False

    if discipline == "geotechnical_drilling":
        for feature_key, tag_key in (
            ("road_bridge_context", "road_bridge_context"),
            ("drilling_depth", "drilling_depth"),
            ("soil_rock_class", "soil_rock_class"),
        ):
            expected = features.get(feature_key)
            if expected:
                actual = _tag_value(candidate, tag_key)
                if actual is None or _normalize_text(actual) != _normalize_text(expected):
                    return False

    return True


# ------------------------------------------------------------------
# Hard-coded distinction guard
# ------------------------------------------------------------------

def _apply_distinction_rules(
    item: BOQLineItem,
    candidates: list[MasterCandidate],
) -> list[MasterCandidate]:
    """Filter incompatible candidates based on discipline, context, scale, and work method."""
    desc_lower = item.description_vi.lower()
    item_unit = (item.unit_raw or "").strip().lower()

    is_road_drill = "đường" in desc_lower and "khoan" in desc_lower
    is_bridge_drill = "cầu" in desc_lower and "khoan" in desc_lower
    is_longitudinal = "trắc dọc" in desc_lower or "mặt cắt dọc" in desc_lower
    is_cross_section = "trắc ngang" in desc_lower or "mặt cắt ngang" in desc_lower
    is_topo = "đo vẽ" in desc_lower or "bình đồ" in desc_lower
    is_geotech = "khoan" in desc_lower or "lấy mẫu" in desc_lower or "thí nghiệm" in desc_lower

    if is_road_drill and not is_bridge_drill:
        candidates = [c for c in candidates if c.tags.get("road_bridge_context") != "bridge"]
    elif is_bridge_drill and not is_road_drill:
        candidates = [c for c in candidates if c.tags.get("road_bridge_context") != "road"]

    if is_longitudinal:
        candidates = [
            c for c in candidates
            if c.tags.get("survey_discipline") in ("longitudinal_section", "longitudinal_profile")
            or c.tags.get("work_method") == "longitudinal"
            or not c.tags.get("survey_discipline")
        ]
    if is_cross_section:
        candidates = [
            c for c in candidates
            if c.tags.get("survey_discipline") in ("cross_section", "river_cross_section")
            or not c.tags.get("survey_discipline")
        ]
    if is_topo:
        candidates = [
            c for c in candidates
            if c.tags.get("survey_discipline") == "topography" or not c.tags.get("survey_discipline")
        ]
    is_spt_line = "spt" in desc_lower or "xuyên tiêu chuẩn" in desc_lower
    if is_geotech and "khoan" in desc_lower and not is_spt_line:
        candidates = [
            c for c in candidates
            if c.tags.get("survey_discipline") in ("geotechnical_drilling", "sample_collection")
            or not c.tags.get("survey_discipline")
        ]

    if item_unit:
        candidates = [c for c in candidates if not _unit_conflict(item_unit, c.unit)]

    return candidates


def _units_are_compatible(item_unit: str, candidate_unit: str) -> bool:
    """Hard guard: do not silently map across different unit systems."""
    i = (item_unit or "").strip().lower()
    c = (candidate_unit or "").strip().lower()
    if not i or not c:
        return True
    if i == c:
        return True
    return False


def _unit_conflict(item_unit: str, candidate_unit: str) -> bool:
    if item_unit == candidate_unit:
        return False
    return not _units_are_compatible(item_unit, candidate_unit)


# ------------------------------------------------------------------
# Semantic mapper
# ------------------------------------------------------------------

class SemanticMapper:
    def __init__(self, mock_ai: Optional[bool] = None):
        self._cache: dict[tuple, MappingOutput] = {}
        self._mock_ai = (
            mock_ai
            if mock_ai is not None
            else os.getenv("MOCK_AI", "false").lower() in ("1", "true", "yes")
        )
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

        if item.row_type == "heading":
            out = MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="Heading row skipped from billable mapping.",
                unresolved_reason="Non-billable heading row.",
                status="error",
                classification="non_billable_heading",
            )
            self._cache[cache_key] = out
            return out

        if item.row_type == "metadata":
            out = MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="Metadata row skipped from billable mapping.",
                unresolved_reason="Non-billable metadata row.",
                status="error",
                classification="non_billable_metadata",
            )
            self._cache[cache_key] = out
            return out

        # Apply hard-coded distinction rules
        filtered = _apply_distinction_rules(item, candidates)

        features = _extract_row_features(item)
        compatible_candidates = [
            c for c in filtered
            if _is_hard_compatible(item, c, features)
        ]

        if not compatible_candidates and filtered:
            out = MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="No candidate passed hard technical compatibility checks.",
                unresolved_reason=(
                    "No candidate satisfies hard technical constraints "
                    "(discipline/work method/scale/terrain/depth/soil class/unit)."
                ),
                status="unresolved",
                classification="mapping_unresolved",
            )
            self._cache[cache_key] = out
            return out

        effective_candidates = compatible_candidates if compatible_candidates else filtered

        if self._mock_ai:
            out = self._mock_map(item, effective_candidates)
        elif not self._client:
            out = MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="OpenAI client is not configured.",
                unresolved_reason="Semantic AI mapping requires OPENAI_API_KEY or MOCK_AI=true for demo mode.",
                status="mapping_unresolved",
                classification="mapping_unresolved",
            )
        else:
            out = await self._ai_map(item, effective_candidates)

        self._cache[cache_key] = out
        return out

    # ------------------------------------------------------------------
    def _mock_map(self, item: BOQLineItem, candidates: list[MasterCandidate]) -> MappingOutput:
        """Deterministic mock: context-aware scoring for offline demos/tests."""
        if not candidates:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="No candidates available.",
                unresolved_reason="No matching master data candidates found.",
                status="unresolved",
                classification="mapping_unresolved",
            )
        desc = f"{item.section_path} {item.description_vi}".lower()

        def score(c: MasterCandidate) -> float:
            s = 0.0
            tags = c.tags or {}
            if c.unit.strip().lower() == item.unit_raw.strip().lower():
                s += 1.0
            if tags.get("road_bridge_context") == "road" and "đường" in desc:
                s += 2.0
            if tags.get("road_bridge_context") == "bridge" and "cầu" in desc:
                s += 2.0
            if tags.get("drilling_depth") and tags.get("drilling_depth") in desc:
                s += 2.0
            if tags.get("survey_discipline") and tags.get("survey_discipline") in desc:
                s += 1.0
            return s

        ranked = sorted(((score(c), c) for c in candidates), key=lambda x: x[0], reverse=True)
        best_score, best = ranked[0]
        if best_score <= 0:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence="[MOCK] No context-supported candidate found.",
                unresolved_reason="No confident mock match from section context.",
                status="unresolved",
                classification="mapping_unresolved",
            )

        if best_score < 1.0:
            return MappingOutput(
                master_item_id=None,
                confidence=min(0.7, 0.55 + best_score * 0.1),
                tags=best.tags,
                evidence="[MOCK] Candidate fit is too weak for an authoritative assignment; manual review required.",
                unresolved_reason="Manual review required: mapping confidence is below the authoritative threshold.",
                status="unresolved",
                classification="mapping_ambiguous",
            )

        return MappingOutput(
            master_item_id=best.id,
            confidence=min(0.95, 0.55 + best_score * 0.1),
            tags=best.tags,
            evidence=(
                f"[MOCK] Context match selected '{best.description_vi}' (code: {best.item_code}) "
                f"using section_path + description + unit + tagged constraints."
            ),
            unresolved_reason=None,
            status="resolved",
            classification="mapped_and_priced",
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
                classification=(
                    "mapped_and_priced" if data.get("master_item_id") is not None else "mapping_unresolved"
                ),
            )
        except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence=f"AI response failed schema validation: {exc}",
                unresolved_reason="AI returned invalid JSON or schema mismatch.",
                status="unresolved",
                classification="mapping_unresolved",
            )
        except Exception as exc:
            return MappingOutput(
                master_item_id=None,
                confidence=0.0,
                tags={},
                evidence=f"AI call error: {exc}",
                unresolved_reason=f"AI mapping failed: {exc}",
                status="error",
                classification="mapping_unresolved",
            )
