"""Storage-free normalization and provider views for authoritative ChapterPlans."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


PLAN_FIELDS = (
    "chapter_function", "chapter_objective", "point_of_view", "time_scope",
    "location_scope", "cast", "relationship_pairs", "opening_state", "closing_state",
    "scene_sequence", "scene_goals", "character_goals", "conflict_chain",
    "information_reveals", "misdirection", "emotional_curve", "suspense_curve",
    "reward_setup", "reward_payoff", "reader_promise_actions", "foreshadow_actions",
    "canon_expected_changes", "world_rule_usages", "power_state_changes",
    "theme_movement", "antagonist_pressure", "chapter_hook", "next_chapter_bridge",
    "prohibited_outcomes", "style_constraints", "target_word_count", "quality_targets",
)
LIST_FIELDS = frozenset({
    "cast", "relationship_pairs", "scene_sequence", "scene_goals", "character_goals",
    "conflict_chain", "information_reveals", "misdirection", "emotional_curve",
    "suspense_curve", "reward_setup", "reward_payoff", "reader_promise_actions",
    "foreshadow_actions", "canon_expected_changes", "world_rule_usages",
    "power_state_changes", "prohibited_outcomes", "style_constraints", "quality_targets",
})


@dataclass(frozen=True, slots=True)
class ChapterPlanQualificationReport:
    decision: str
    blocking_missing_fields: tuple[str, ...]
    warning_missing_fields: tuple[str, ...]
    compatibility_mappings: dict[str, str]
    input_asset_version_id: str
    input_content_hash: str
    normalized_digest: str
    contract_version: str = "chapter-plan-qualification-v2"


def normalize_authoritative_chapter_plan(
    *,
    project_id: str,
    expected_chapter: int,
    content: dict[str, Any],
    asset_version_id: str,
    content_hash: str,
) -> tuple[dict[str, Any], ChapterPlanQualificationReport]:
    declared_project = str(content.get("project_id") or project_id)
    if declared_project != project_id:
        raise KernelError("CHAPTER_PLAN_CROSS_PROJECT", "ChapterPlan project does not match Operation")
    try:
        chapter = int(content.get("chapter"))
    except (TypeError, ValueError) as exc:
        raise KernelError("CHAPTER_PLAN_CHAPTER_INVALID", "ChapterPlan chapter is missing") from exc
    if chapter != expected_chapter:
        raise KernelError("CHAPTER_PLAN_CHAPTER_MISMATCH", "ChapterPlan targets another chapter")

    mappings: dict[str, str] = {}
    objective = content.get("chapter_objective")
    if not objective and content.get("objective"):
        objective = content["objective"]
        mappings["objective"] = "chapter_objective"
    scenes = content.get("scene_sequence")
    if not scenes and content.get("scenes"):
        scenes = content["scenes"]
        mappings["scenes"] = "scene_sequence"
    if not scenes and content.get("beats"):
        scenes = content["beats"]
        mappings["beats"] = "scene_sequence"
    hook = content.get("chapter_hook")
    if not hook and content.get("closing_hook"):
        hook = content["closing_hook"]
        mappings["closing_hook"] = "chapter_hook"

    normalized: dict[str, Any] = {
        "type": "AuthoritativeChapterPlan",
        "project_id": project_id,
        "chapter": chapter,
        "title": str(content.get("title") or "").strip(),
        "premise": str(content.get("premise") or "").strip(),
        "chapter_objective": str(objective or "").strip(),
        "scene_sequence": list(scenes) if isinstance(scenes, (list, tuple)) else [],
        "chapter_hook": str(hook or "").strip(),
        "source_chapter_plan_asset_version_id": asset_version_id,
        "source_chapter_plan_content_hash": content_hash,
        "source_schema_version": str(content.get("schema_version") or content.get("contract_version") or "legacy"),
        "contract_version": "authoritative-chapter-plan-v2",
    }
    for field in PLAN_FIELDS:
        if field in {"chapter_objective", "scene_sequence", "chapter_hook"}:
            continue
        value = content.get(field)
        normalized[field] = list(value) if field in LIST_FIELDS and isinstance(value, (list, tuple)) else (
            [] if field in LIST_FIELDS else value
        )
    known = {"project_id", "chapter", "title", "premise", "objective", "beats", "scenes", "closing_hook", "schema_version", "contract_version", *PLAN_FIELDS}
    normalized["source_extensions"] = {
        key: value for key, value in content.items() if key not in known
    }
    blocking = tuple(
        field for field, value in (
            ("title", normalized["title"]),
            ("premise", normalized["premise"]),
            ("chapter_objective", normalized["chapter_objective"]),
            ("scene_sequence", normalized["scene_sequence"]),
            ("chapter_hook", normalized["chapter_hook"]),
        )
        if not value
    )
    warnings = tuple(field for field in PLAN_FIELDS if not normalized.get(field) and field not in blocking)
    digest = "sha256:" + hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    report = ChapterPlanQualificationReport(
        decision="BLOCKED" if blocking else "ELIGIBLE_WITH_WARNINGS" if warnings else "ELIGIBLE",
        blocking_missing_fields=blocking,
        warning_missing_fields=warnings,
        compatibility_mappings=mappings,
        input_asset_version_id=asset_version_id,
        input_content_hash=content_hash,
        normalized_digest=digest,
    )
    if blocking:
        raise KernelError(
            "CHAPTER_PLAN_SEMANTIC_FIELDS_MISSING",
            "ChapterPlan is missing blocking semantic fields: " + ", ".join(blocking),
        )
    normalized["qualification"] = json.loads(json.dumps(asdict(report), sort_keys=True))
    normalized["normalized_digest"] = digest
    return json.loads(json.dumps(normalized, sort_keys=True)), report


def build_draft_plan_view(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "draft-plan-view-v1",
        **{key: plan.get(key) for key in (
            "chapter", "title", "premise", "chapter_function", "chapter_objective",
            "point_of_view", "time_scope", "location_scope", "cast",
            "relationship_pairs", "opening_state", "closing_state", "scene_sequence",
            "scene_goals", "character_goals", "conflict_chain", "information_reveals",
            "misdirection", "emotional_curve", "suspense_curve", "reward_setup",
            "reward_payoff", "reader_promise_actions", "foreshadow_actions",
            "canon_expected_changes", "world_rule_usages", "power_state_changes",
            "theme_movement", "antagonist_pressure", "chapter_hook",
            "next_chapter_bridge", "prohibited_outcomes", "target_word_count",
            "quality_targets",
        )},
        "source_chapter_plan_asset_version_id": plan["source_chapter_plan_asset_version_id"],
        "source_chapter_plan_content_hash": plan["source_chapter_plan_content_hash"],
    }


def build_draft_context_view(context_bundle: dict[str, Any]) -> dict[str, Any]:
    view = dict(context_bundle.get("stage_context_view") or {})
    return {
        "contract_version": "draft-context-view-v1",
        "stage": "draft",
        "segments": list(view.get("segments") or view.get("context_segments") or []),
        "token_budget": context_bundle.get("token_budget"),
        "actual_context_digest": context_bundle.get("actual_context_digest"),
        "source_isolation_result": dict(context_bundle.get("source_isolation_result") or {}),
        "copyright_boundary": context_bundle.get("copyright_boundary"),
    }


def build_draft_style_view(context_bundle: dict[str, Any]) -> dict[str, Any]:
    style_segments = [
        segment for segment in context_bundle.get("context_segments", [])
        if segment.get("asset_type") == "style_policy"
    ]
    return {
        "contract_version": "draft-style-view-v1",
        "style_policy_version_id": str(
            context_bundle.get("production_input_manifest", {}).get("style_policy_version_id") or ""
        ),
        "policies": [
            {
                "asset_version_id": segment.get("asset_version_id"),
                "safe_summary": segment.get("safe_summary", ""),
                "structured_facts": list(segment.get("structured_facts") or []),
            }
            for segment in style_segments
        ],
    }


__all__ = [
    "ChapterPlanQualificationReport", "build_draft_context_view",
    "build_draft_plan_view", "build_draft_style_view",
    "normalize_authoritative_chapter_plan",
]
