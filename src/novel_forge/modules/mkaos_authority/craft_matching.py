from __future__ import annotations

import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

LEGACY_SELECTION = "craft-context-affinity-selection.v1"
NEED_DRIVEN_SELECTION = "craft-need-driven-selection.v2"
LEGACY_SIGNATURE = "abstract-mechanism-affinity-terms.v1"
SEMANTIC_SIGNATURE = "abstract-mechanism-terms.v2"

_NEED_FIELDS = {
    "writing_problem": ("narrative_problem",),
    "chapter_function": ("narrative_problem", "abstract_mechanism"),
    "scene_goal": ("narrative_problem", "abstract_mechanism"),
    "scene_demand": ("narrative_problem", "abstract_mechanism"),
    "reader_effect": ("desired_reader_effect",),
    "emotion": ("desired_reader_effect",),
    "conflict": ("narrative_problem",),
    "information": ("narrative_problem",),
    "relationship": ("narrative_problem",),
    "style": ("narrative_problem", "prose_realization_guidance"),
}


def require_selection_version(version: str) -> str:
    if version not in {LEGACY_SELECTION, NEED_DRIVEN_SELECTION}:
        raise KernelError("CRAFT_SELECTION_POLICY_INVALID", "Unknown frozen Craft selection contract")
    return version


def semantic_terms(value: Any) -> set[str]:
    if isinstance(value, str):
        words = set(re.findall(r"[a-z][a-z_-]+|[\u4e00-\u9fff]+", value.casefold()))
        return words | {word[index:index + 2] for word in words if re.fullmatch(r"[\u4e00-\u9fff]+", word) for index in range(len(word) - 1)}
    if isinstance(value, (list, tuple)):
        return set().union(*(semantic_terms(item) for item in value))
    return set()


def assess_need(mechanism: Mapping[str, Any], context: Mapping[str, Any], *, applicability_status: str) -> dict[str, Any]:
    matches = []
    for dimension, fields in _NEED_FIELDS.items():
        overlap = semantic_terms(context.get(dimension)) & semantic_terms([mechanism[field] for field in fields])
        if overlap:
            matches.append({"dimension": dimension, "fields": list(fields), "terms": sorted(overlap), "score": min(5, len(overlap))})
    need_score = sum(item["score"] for item in matches)
    adjustments = []
    evidence = {(item["dimension"], item["value"].casefold()): item["asset_version_id"] for item in mechanism.get("affinity_evidence", [])}
    for dimension, tags in mechanism["affinity"].items():
        values = context.get(dimension) or []
        values = [values] if isinstance(values, str) else values
        requested = {value.casefold() for value in values if isinstance(value, str)} if isinstance(values, (list, tuple)) else set()
        for tag in tags:
            if tag.casefold() not in requested:
                continue
            reference = evidence.get((dimension, tag.casefold()))
            status = "APPLIED" if need_score and reference and applicability_status == "APPLICABLE" else "NO_NEED_MATCH" if not need_score else "NO_AFFINITY_EVIDENCE" if not reference else "APPLICABILITY_UNRESOLVED"
            adjustments.append({"dimension": dimension, "value": tag, "evidence_asset_version_id": reference or "", "status": status})
    bonus = min(2, sum(item["status"] == "APPLIED" for item in adjustments))
    return {"policy_version": NEED_DRIVEN_SELECTION, "need_score": need_score,
        "need_matches": matches, "affinity_adjustment": bonus, "affinity_adjustments": adjustments,
        "affinity_adjustment_limit": 2, "applicability_status": applicability_status,
        "evidence_ceiling": "SEMANTIC_TERM_RETRIEVAL_NOT_CREATIVE_QUALITY"}


def inherit_reselection_contract(need: Any, previous: Mapping[str, Any]) -> Any:
    from dataclasses import replace
    version = require_selection_version(previous.get("craft_selection_policy_version", LEGACY_SELECTION))
    context = dict(need.craft_context)
    if version == LEGACY_SELECTION:
        prior_context = previous.get("need", {}).get("craft_context", {})
        for dimension in ("writing_problem", "scene_demand", "scene_type"):
            if dimension not in prior_context:
                context.pop(dimension, None)
    return replace(need, craft_selection_policy_version=version, craft_context=context)
