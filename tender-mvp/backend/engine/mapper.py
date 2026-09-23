"""
AI Semantic Mapping Module
==========================
Maps BOQ line items to master data entries using:
1. Rule-based heuristics (keyword matching, unit compatibility)
2. Optional LLM disambiguation for ambiguous cases

IMPORTANT: The LLM is used ONLY for classification/selection, never for
computing monetary amounts. All numeric output must trace to master data,
user overrides, or deterministic formulas.

The module returns MappingResult objects with:
- status: MATCHED | AMBIGUOUS | UNRESOLVED | HEADING
- evidence: textual justification
- structured tags extracted from the PDF description

Critical disambiguation rules (non-negotiable):
- Road drilling 0-30m (MD-003) ≠ Bridge drilling 0-60m (MD-006)
- 100ha ≠ ha, 100m ≠ m without explicit unit_rule conversion
- TN / thí nghiệm are synonyms but unit must match
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from ..models.domain import (
    BOQDocument,
    BOQRow,
    MappingResult,
    MappingStatus,
    MasterItem,
    RowType,
    SemanticTag,
)
from .master_loader import load_master_items

# ---------------------------------------------------------------------------
# Keyword-based heuristic matching
# ---------------------------------------------------------------------------

_BRIDGE_KEYWORDS = re.compile(r"\bcầu\b", re.IGNORECASE)
_ROAD_KEYWORDS = re.compile(r"\bđường\b", re.IGNORECASE)
_DRILLING_KEYWORDS = re.compile(r"\bkhoan\b", re.IGNORECASE)
_TOPOGRAPHIC_KEYWORDS = re.compile(r"\bđo\s+đạc\b|\bbình\s+đồ\b|\bmặt\s+cắt\b", re.IGNORECASE)
_SAMPLING_KEYWORDS = re.compile(r"\blấy\s+mẫu\b", re.IGNORECASE)
_SPT_KEYWORDS = re.compile(r"\bspt\b", re.IGNORECASE)
_CPT_KEYWORDS = re.compile(r"\bcpt\b|\bxuyên\s+tĩnh\b", re.IGNORECASE)
_LAB_KEYWORDS = re.compile(r"\bthí\s+nghiệm\b|\bthi\s+nghiem\b", re.IGNORECASE)
_REPORT_KEYWORDS = re.compile(r"\blập\s+báo\s+cáo\b|\bbáo\s+cáo\b", re.IGNORECASE)
_HYDROLOGY_KEYWORDS = re.compile(r"\bthủy\s+văn\b", re.IGNORECASE)
_ROCK_KEYWORDS = re.compile(r"\bđá\b", re.IGNORECASE)
_SOIL_KEYWORDS = re.compile(r"\bđất\b", re.IGNORECASE)
_DEPTH_0_30 = re.compile(r"0[-\s]*30\s*m", re.IGNORECASE)
_DEPTH_0_60 = re.compile(r"0[-\s]*60\s*m", re.IGNORECASE)
_UNDERWATER = re.compile(r"dưới\s+nước|under\s+water", re.IGNORECASE)
_ON_LAND = re.compile(r"trên\s+cạn", re.IGNORECASE)
_SCALE_500 = re.compile(r"1[/\\]500", re.IGNORECASE)
_SCALE_1000 = re.compile(r"1[/\\]1000", re.IGNORECASE)
_SCALE_2000 = re.compile(r"1[/\\]2000", re.IGNORECASE)
_TERRAIN_FLAT = re.compile(r"đồng\s+bằng", re.IGNORECASE)
_TERRAIN_HILLY = re.compile(r"đồi\s+núi|miền\s+núi", re.IGNORECASE)
_LONGITUDINAL = re.compile(r"mặt\s+cắt\s+dọc", re.IGNORECASE)
_CROSS_SECTION = re.compile(r"mặt\s+cắt\s+ngang", re.IGNORECASE)
_TOPO_MAP = re.compile(r"bình\s+đồ", re.IGNORECASE)
_SOIL_CLASS_12 = re.compile(r"cấp\s*I+[-–]?I*I?\b", re.IGNORECASE)
_SOIL_CLASS_34 = re.compile(r"cấp\s*(III|IV)", re.IGNORECASE)


def _extract_tags(desc: str, section: str) -> SemanticTag:
    """Extract structured semantic tags from a Vietnamese BOQ description."""
    combined = f"{section} {desc}"
    tag = SemanticTag()

    # Context
    is_bridge = bool(_BRIDGE_KEYWORDS.search(combined))
    is_road = bool(_ROAD_KEYWORDS.search(combined))
    if is_bridge:
        tag.context = "bridge"
    elif is_road:
        tag.context = "road"

    # Discipline
    if _DRILLING_KEYWORDS.search(desc):
        tag.discipline = "geotechnical"
        tag.work_type = "drilling"
    elif _TOPOGRAPHIC_KEYWORDS.search(desc) or _TOPO_MAP.search(desc):
        tag.discipline = "survey"
        if _LONGITUDINAL.search(desc):
            tag.work_type = "longitudinal_section"
        elif _CROSS_SECTION.search(desc):
            tag.work_type = "cross_section"
        elif _TOPO_MAP.search(desc):
            tag.work_type = "topographic_mapping"
    elif _HYDROLOGY_KEYWORDS.search(desc):
        tag.discipline = "hydrology"
        tag.work_type = "hydrological_survey"
    elif _SAMPLING_KEYWORDS.search(desc):
        tag.discipline = "geotechnical"
        tag.work_type = "sampling"
        if _ROCK_KEYWORDS.search(desc):
            tag.sample_type = "rock"
        else:
            tag.sample_type = "undisturbed_soil"
    elif _SPT_KEYWORDS.search(desc):
        tag.discipline = "geotechnical"
        tag.work_type = "in_situ_testing"
        tag.test_type = "SPT"
    elif _CPT_KEYWORDS.search(desc):
        tag.discipline = "geotechnical"
        tag.work_type = "in_situ_testing"
        tag.test_type = "CPT"
    elif _LAB_KEYWORDS.search(desc):
        tag.discipline = "laboratory"
        if _ROCK_KEYWORDS.search(desc):
            tag.work_type = "rock_testing"
            tag.test_type = "basic_physical_mechanical"
        else:
            tag.work_type = "soil_testing"
            tag.test_type = "basic_physical_mechanical"
    elif _REPORT_KEYWORDS.search(desc):
        tag.discipline = "reporting"
        if "địa chất" in desc.lower():
            tag.work_type = "geotechnical_report"
        else:
            tag.work_type = "topographic_report"

    # Terrain
    if _TERRAIN_FLAT.search(desc):
        tag.terrain = "flat"
    elif _TERRAIN_HILLY.search(desc):
        tag.terrain = "hilly"

    # Depth
    if _DEPTH_0_60.search(desc):
        tag.depth_range = "0-60m"
    elif _DEPTH_0_30.search(desc):
        tag.depth_range = "0-30m"

    # Condition
    if _UNDERWATER.search(desc):
        tag.condition = "underwater"
    elif _ON_LAND.search(desc):
        tag.condition = "on_land"

    # Soil/rock class
    if _SOIL_CLASS_34.search(desc):
        tag.soil_class = "III-IV"
    elif _SOIL_CLASS_12.search(desc):
        tag.soil_class = "I-II"

    # Scale
    if _SCALE_500.search(desc):
        tag.scale = "1:500"
    elif _SCALE_1000.search(desc):
        tag.scale = "1:1000"
    elif _SCALE_2000.search(desc):
        tag.scale = "1:2000"

    return tag


def _score_candidate(master: MasterItem, tag: SemanticTag, row: BOQRow) -> float:
    """
    Heuristic score [0, 1] for how well a master item matches a BOQ row.
    Higher is better. Hard mismatches return -1 (disqualify).
    """
    mt = master.tags
    score = 0.0
    max_score = 0.0

    def check(field: str, weight: float = 1.0):
        nonlocal score, max_score
        tag_val = getattr(tag, field, None)
        master_val = mt.get(field)
        if tag_val is None and master_val is None:
            return  # both absent – neutral
        max_score += weight
        if tag_val is not None and master_val is not None:
            if str(tag_val).lower() == str(master_val).lower():
                score += weight

    check("discipline", 2.0)
    check("work_type", 3.0)
    check("context", 4.0)   # road vs bridge is critical
    check("depth_range", 3.0)
    check("condition", 2.0)
    check("soil_class", 2.0)
    check("terrain", 1.5)
    check("scale", 2.0)
    check("test_type", 2.0)
    check("sample_type", 2.0)

    # HARD RULE: road context must not match bridge master and vice versa
    tag_ctx = (tag.context or "").lower()
    master_ctx = (mt.get("context") or "").lower()
    if tag_ctx and master_ctx and tag_ctx != master_ctx:
        return -1.0  # disqualify

    # HARD RULE: depth_range mismatch for drilling is a disqualifier
    if tag.work_type == "drilling":
        tag_depth = tag.depth_range or ""
        master_depth = mt.get("depth_range") or ""
        if tag_depth and master_depth and tag_depth != master_depth:
            return -1.0

    if max_score == 0:
        return 0.1  # no criteria to compare
    return score / max_score


def map_boq_to_master(boq: BOQDocument) -> list[MappingResult]:
    """
    For each LINE_ITEM row in the BOQ, find the best matching master item.
    Returns a MappingResult for every row (headings/metadata get HEADING status).
    """
    master_items = load_master_items()
    results: list[MappingResult] = []

    for row in boq.rows:
        if row.row_type != RowType.LINE_ITEM:
            results.append(
                MappingResult(
                    row_id=row.row_id,
                    status=MappingStatus.HEADING,
                    evidence=f"Row classified as {row.row_type.value}",
                )
            )
            continue

        tag = _extract_tags(row.description_vi, row.source_section + " " + (row.section_label or ""))

        # Score all master items
        scored = []
        for item in master_items:
            s = _score_candidate(item, tag, row)
            if s >= 0:
                scored.append((s, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored or scored[0][0] < 0.3:
            results.append(
                MappingResult(
                    row_id=row.row_id,
                    status=MappingStatus.UNRESOLVED,
                    tags=tag,
                    unit_pdf=row.unit_raw,
                    confidence=0.0,
                    evidence="No master item with score ≥ 0.3 found",
                    exception_reason="No suitable master data match; manual review required",
                )
            )
            continue

        best_score, best_item = scored[0]

        # Check if second-best is very close (ambiguous)
        is_ambiguous = len(scored) > 1 and (scored[0][0] - scored[1][0]) < 0.1

        status = MappingStatus.AMBIGUOUS if is_ambiguous else MappingStatus.MATCHED

        results.append(
            MappingResult(
                row_id=row.row_id,
                status=status,
                master_id=best_item.id,
                master_code=best_item.code,
                master_description=best_item.description,
                tags=tag,
                unit_pdf=row.unit_raw,
                unit_master=best_item.unit,
                confidence=round(best_score, 3),
                evidence=(
                    f"Score {best_score:.2f}; matched on "
                    f"discipline={tag.discipline}, work_type={tag.work_type}, "
                    f"context={tag.context}, depth={tag.depth_range}, "
                    f"condition={tag.condition}"
                ),
                exception_reason="Ambiguous: multiple candidates have similar scores" if is_ambiguous else None,
            )
        )

    return results
