from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata
from typing import Any


@dataclass
class MappingDecision:
    mapping_status: str
    canonical_code: str | None
    confidence: float | None
    mapping_evidence: str | None
    reason: str | None
    candidates: list[dict[str, Any]]
    missing_dependencies: list[str]
    quantity_factor: Decimal
    source_unit: str | None
    master_unit: str | None


class Train2SemanticMapper:
    """Deterministic mapper constrained to verified WorkItemMaster candidates.

    AI suggestions are treated as hints only. This mapper never invents codes,
    norms, or prices.
    """

    def __init__(self, confidence_threshold: Decimal):
        self.confidence_threshold = confidence_threshold

    @staticmethod
    def _normalize_text(text: str) -> str:
        lowered = (text or "").lower().replace("đ", "d")
        normalized = "".join(
            ch for ch in unicodedata.normalize("NFD", lowered)
            if unicodedata.category(ch) != "Mn"
        )
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = Train2SemanticMapper._normalize_text(text)
        tokens = [t for t in re.split(r"[^a-z0-9./]+", normalized) if t]
        return set(tokens)

    def _generate_catalog_candidates(
        self,
        description_vi: str,
        work_master: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        desc_tokens = self._tokens(description_vi)
        candidates: dict[str, dict[str, Any]] = {}
        if not desc_tokens:
            return candidates

        for code, item in work_master.items():
            text = f"{code} {item.get('description') or ''}"
            item_tokens = self._tokens(text)
            if not item_tokens:
                continue
            overlap = desc_tokens.intersection(item_tokens)
            if not overlap:
                continue
            score = Decimal(len(overlap)) / Decimal(max(len(desc_tokens), 1))
            if score <= Decimal("0"):
                continue
            candidates[code] = {
                "code": code,
                "confidence": float(min(Decimal("0.9"), Decimal("0.5") + score)),
                "evidence": f"catalogue token overlap: {', '.join(sorted(overlap)[:6])}",
                "source": "catalogue",
            }
        return candidates

    @staticmethod
    def _units_equal(a: str, b: str) -> bool:
        lhs = (a or "").strip().lower()
        rhs = (b or "").strip().lower()
        if not lhs or not rhs:
            return True
        return lhs == rhs

    @staticmethod
    def _find_verified_conversion(pdf_unit: str, master_unit: str, unit_rules: list[dict[str, Any]]) -> dict[str, Any] | None:
        lhs = (pdf_unit or "").strip().lower()
        rhs = (master_unit or "").strip().lower()
        for rule in unit_rules:
            if (rule.get("from_unit") or "").strip().lower() == lhs and (rule.get("to_unit") or "").strip().lower() == rhs:
                return rule
        return None

    def decide(
        self,
        *,
        row_id: str,
        row_type: str,
        description_vi: str,
        unit_raw: str,
        quantity_raw: str,
        quantity,
        suggestions: list[dict[str, Any]],
        work_master: dict[str, dict[str, Any]],
        unit_rules: list[dict[str, Any]],
        manual_selected_code: str | None,
        allow_zero_quantity: bool,
    ) -> MappingDecision:
        if row_type != "line_item":
            return MappingDecision(
                mapping_status="non_billable",
                canonical_code=None,
                confidence=None,
                mapping_evidence="Non-billable row",
                reason="Non-billable row type",
                candidates=[],
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )

        if quantity is None:
            return MappingDecision(
                mapping_status="invalid_quantity",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="Missing or invalid quantity",
                candidates=[],
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )
        if quantity < 0:
            return MappingDecision(
                mapping_status="negative_quantity_blocked",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="Negative quantity is blocked",
                candidates=[],
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )
        if quantity == 0 and not allow_zero_quantity:
            return MappingDecision(
                mapping_status="zero_quantity_review_required",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="Zero quantity requires explicit policy override",
                candidates=[],
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )

        candidate_map: dict[str, dict[str, Any]] = self._generate_catalog_candidates(description_vi, work_master)

        if manual_selected_code:
            code = manual_selected_code.strip()
            if code not in work_master:
                return MappingDecision(
                    mapping_status="mapping_unmatched",
                    canonical_code=None,
                    confidence=None,
                    mapping_evidence=None,
                    reason="Manual selected code is not in verified WorkItemMaster",
                    candidates=[],
                    missing_dependencies=[],
                )
            candidate_map[code] = {
                "code": code,
                "confidence": 1.0,
                "evidence": "manual selection",
                "source": "manual",
            }
        else:
            for hint in suggestions:
                code = str(hint.get("code") or "").strip()
                if not code or code not in work_master:
                    continue
                existing = candidate_map.get(code)
                hint_confidence = float(hint.get("confidence") or 0.0)
                if existing is None or hint_confidence > float(existing.get("confidence") or 0.0):
                    candidate_map[code] = {
                        "code": code,
                        "confidence": hint_confidence,
                        "evidence": str(hint.get("evidence") or ""),
                        "source": str(hint.get("source") or "ai"),
                    }

        if not candidate_map:
            return MappingDecision(
                mapping_status="mapping_unmatched",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="No verified WorkItemMaster suggestion",
                candidates=[],
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )

        source_unit_missing = not (unit_raw or "").strip()
        if source_unit_missing and not manual_selected_code:
            return MappingDecision(
                mapping_status="unit_verification_required",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="Source unit is missing and requires manual verification",
                candidates=[
                    {
                        "code": code,
                        "confidence": float(hint.get("confidence") or 0.0),
                        "evidence": hint.get("evidence"),
                        "source": hint.get("source"),
                        "unit_match": False,
                        "conversion_rule": None,
                        "conversion_factor": "1",
                        "compatible": False,
                        "source_unit": None,
                        "master_unit": str((work_master.get(code) or {}).get("unit") or "") or None,
                    }
                    for code, hint in sorted(candidate_map.items())
                ],
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=None,
                master_unit=None,
            )

        candidates: list[dict[str, Any]] = []
        compatible_codes: list[str] = []
        for code, hint in sorted(candidate_map.items()):
            master = work_master.get(code) or {}
            master_unit = str(master.get("unit") or "")
            unit_match = self._units_equal(unit_raw, master_unit)
            conversion_rule = None
            conversion_factor = Decimal("1")
            if not unit_match:
                conversion_rule = self._find_verified_conversion(unit_raw, master_unit, unit_rules)
                if conversion_rule is not None:
                    conversion_factor = Decimal(str(conversion_rule.get("factor") or "1"))
            compatible = unit_match or conversion_rule is not None
            if compatible:
                compatible_codes.append(code)
            candidates.append(
                {
                    "code": code,
                    "confidence": float(hint.get("confidence") or 0.0),
                    "evidence": hint.get("evidence"),
                    "source": hint.get("source"),
                    "unit_match": unit_match,
                    "conversion_rule": conversion_rule,
                    "conversion_factor": str(conversion_factor),
                    "compatible": compatible,
                    "source_unit": (unit_raw or "").strip() or None,
                    "master_unit": master_unit.strip() or None,
                }
            )

        if not compatible_codes:
            return MappingDecision(
                mapping_status="unit_incompatible",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="No candidate has compatible units or verified conversion rule",
                candidates=candidates,
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )

        if len(compatible_codes) > 1:
            return MappingDecision(
                mapping_status="mapping_ambiguous",
                canonical_code=None,
                confidence=None,
                mapping_evidence=None,
                reason="Multiple compatible verified candidates require manual review",
                candidates=candidates,
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=(unit_raw or "").strip() or None,
                master_unit=None,
            )

        selected = compatible_codes[0]
        selected_candidate = next(c for c in candidates if c["code"] == selected)
        confidence = Decimal(str(selected_candidate.get("confidence") or 0))
        source_unit = selected_candidate.get("source_unit")
        master_unit = selected_candidate.get("master_unit")

        if (not source_unit or not master_unit) and not manual_selected_code:
            return MappingDecision(
                mapping_status="unit_verification_required",
                canonical_code=None,
                confidence=float(confidence),
                mapping_evidence=selected_candidate.get("evidence"),
                reason="Missing source/master unit requires manual verification",
                candidates=candidates,
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=source_unit,
                master_unit=master_unit,
            )

        if not manual_selected_code and confidence < self.confidence_threshold:
            return MappingDecision(
                mapping_status="low_confidence_review_required",
                canonical_code=None,
                confidence=float(confidence),
                mapping_evidence=selected_candidate.get("evidence"),
                reason=f"Confidence {confidence} below threshold {self.confidence_threshold}",
                candidates=candidates,
                missing_dependencies=[],
                quantity_factor=Decimal("1"),
                source_unit=source_unit,
                master_unit=master_unit,
            )

        factor_text = selected_candidate.get("conversion_factor") or "1"
        quantity_factor = Decimal(str(factor_text))

        return MappingDecision(
            mapping_status="resolved",
            canonical_code=selected,
            confidence=float(confidence),
            mapping_evidence=selected_candidate.get("evidence"),
            reason=None,
            candidates=candidates,
            missing_dependencies=[],
            quantity_factor=quantity_factor,
            source_unit=source_unit,
            master_unit=master_unit,
        )
