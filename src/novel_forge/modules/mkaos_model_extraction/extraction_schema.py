from __future__ import annotations

from typing import Any


FORBIDDEN_FIELDS = {
    "raw_text",
    "clean_text",
    "source_text",
    "target_text",
    "quote",
    "quotation",
    "excerpt",
    "verbatim",
    "copied_sentence",
}

REQUIRED_CANDIDATE_FIELDS = [
    "concept_name",
    "source_type",
    "discipline",
    "knowledge_type",
    "abstraction_level",
    "core_explanation",
    "creative_principle",
    "narrative_function",
    "conflict_function",
    "character_function",
    "worldbuilding_function",
    "prose_function",
    "review_function",
    "positive_usage",
    "negative_usage",
    "anti_patterns",
    "applicable_flows",
    "originality_boundary",
    "evidence_refs",
    "confidence",
    "risk_level",
    "quality_dimensions",
]

ALLOWED_RISK_LEVELS = {"low", "medium", "high"}


def default_candidate_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": REQUIRED_CANDIDATE_FIELDS,
        "forbidden_fields": sorted(FORBIDDEN_FIELDS),
        "candidate_contract": {
            "abstraction_level": "mechanism",
            "source_isolation": "no raw source expression",
            "must_include": ["creative_principle", "applicable_flows", "originality_boundary", "evidence_refs"],
        },
    }
