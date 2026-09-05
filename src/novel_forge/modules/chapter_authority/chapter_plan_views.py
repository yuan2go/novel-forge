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
    "protagonist_charm_mechanism", "serialization_function",
    "chapter_economy_function", "reader_dropoff_risks", "payoff_schedule",
    "platform_rhythm", "conflict_escalation",
    "constraint_envelope",
    "narrative_architecture_version", "narrative_segment_ref", "chapter_intent",
    "arc_schedule", "setups", "payoffs", "character_participation",
    "knowledge_boundaries", "disclosures", "required_state_transitions",
    "reader_experience", "scene_plan", "expected_exit_state",
    "narrative_realization_slice",
    "chapter_contract_schema_version", "primary_function", "obligation_actions",
    "required_arc_contributions",
)
LIST_FIELDS = frozenset({
    "cast", "relationship_pairs", "scene_sequence", "scene_goals", "character_goals",
    "conflict_chain", "information_reveals", "misdirection", "emotional_curve",
    "suspense_curve", "reward_setup", "reward_payoff", "reader_promise_actions",
    "foreshadow_actions", "canon_expected_changes", "world_rule_usages",
    "power_state_changes", "prohibited_outcomes", "style_constraints", "quality_targets",
    "reader_dropoff_risks", "payoff_schedule", "platform_rhythm", "conflict_escalation",
    "arc_schedule", "setups", "payoffs", "character_participation",
    "knowledge_boundaries", "disclosures", "required_state_transitions", "scene_plan",
    "obligation_actions", "required_arc_contributions",
})


@dataclass(frozen=True, slots=True)
class ChapterPlanQualificationProfile:
    profile_id: str
    required_fields: tuple[str, ...]
    warning_fields: tuple[str, ...]
    genre: str = "any"
    platform: str = "any"
    book_phase: str = "ordinary"
    chapter_function: str = "ordinary"
    contract_version: str = "chapter-plan-qualification-profile-v1"


BASE_REQUIRED_FIELDS = (
    "title", "premise", "chapter_objective", "scene_sequence", "chapter_hook",
)


def qualification_profile_for_plan(content: dict[str, Any]) -> ChapterPlanQualificationProfile:
    chapter = int(content.get("chapter") or 0)
    function = str(content.get("chapter_function") or "ordinary").strip().lower()
    phase = str(content.get("book_phase") or ("opening" if chapter == 1 else "ordinary")).lower()
    if chapter == 1 or function in {"opening", "golden_opening"}:
        required = BASE_REQUIRED_FIELDS + (
            "conflict_chain", "reader_promise_actions", "protagonist_charm_mechanism",
            "information_reveals", "next_chapter_bridge",
        )
        profile_id = "chapter-plan-v3:opening"
    elif function in {"payoff", "reward_payoff", "pleasure_payoff"}:
        required = BASE_REQUIRED_FIELDS + (
            "reward_setup", "reward_payoff", "conflict_escalation",
            "reader_promise_actions", "next_chapter_bridge",
        )
        profile_id = "chapter-plan-v3:payoff"
    elif function in {"climax", "volume_climax", "ending"} or phase in {"climax", "ending"}:
        required = BASE_REQUIRED_FIELDS + (
            "reward_payoff", "antagonist_pressure", "canon_expected_changes",
            "closing_state", "next_chapter_bridge",
        )
        profile_id = "chapter-plan-v3:climax"
    else:
        required = BASE_REQUIRED_FIELDS + (
            "conflict_chain", "emotional_curve", "suspense_curve",
            "reader_promise_actions", "antagonist_pressure", "next_chapter_bridge",
        )
        profile_id = "chapter-plan-v3:ordinary"
    warnings = tuple(field for field in PLAN_FIELDS if field not in required)
    return ChapterPlanQualificationProfile(
        profile_id=profile_id,
        required_fields=required,
        warning_fields=warnings,
        genre=str(content.get("genre") or "any"),
        platform=str(content.get("platform") or "any"),
        book_phase=phase,
        chapter_function=function,
    )


LEGACY_COMPATIBILITY_PROFILE = ChapterPlanQualificationProfile(
    profile_id="chapter-plan-v2:compatibility",
    required_fields=BASE_REQUIRED_FIELDS,
    warning_fields=PLAN_FIELDS,
)


@dataclass(frozen=True, slots=True)
class ChapterPlanQualificationReport:
    decision: str
    blocking_missing_fields: tuple[str, ...]
    warning_missing_fields: tuple[str, ...]
    compatibility_mappings: dict[str, str]
    input_asset_version_id: str
    input_content_hash: str
    normalized_digest: str
    qualification_profile_id: str = "chapter-plan-v2:compatibility"
    source_schema_version: str = "legacy"
    contract_version: str = "chapter-plan-qualification-v3"


def normalize_authoritative_chapter_plan(
    *,
    project_id: str,
    expected_chapter: int,
    content: dict[str, Any],
    asset_version_id: str,
    content_hash: str,
    qualification_profile: ChapterPlanQualificationProfile | None = None,
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
    if content.get("chapter_contract_schema_version"):
        from novel_forge.modules.hierarchical_planning.chapter_contracts import (
            require_chapter_contracts,
        )

        require_chapter_contracts(content)

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
        "contract_version": "authoritative-chapter-plan-v4",
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
    profile = qualification_profile or LEGACY_COMPATIBILITY_PROFILE
    blocking = tuple(field for field in profile.required_fields if not normalized.get(field))
    warnings = tuple(
        field for field in profile.warning_fields
        if not normalized.get(field) and field not in blocking
    )
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
        qualification_profile_id=profile.profile_id,
        source_schema_version=normalized["source_schema_version"],
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
            "protagonist_charm_mechanism", "serialization_function",
            "chapter_economy_function", "reader_dropoff_risks", "payoff_schedule",
            "platform_rhythm", "conflict_escalation",
            "constraint_envelope",
            "narrative_architecture_version", "narrative_segment_ref",
            "chapter_intent", "arc_schedule", "setups", "payoffs",
            "character_participation", "knowledge_boundaries", "disclosures",
            "required_state_transitions", "reader_experience", "scene_plan",
            "expected_exit_state", "narrative_realization_slice",
            "chapter_contract_schema_version", "primary_function", "obligation_actions",
            "required_arc_contributions",
        )},
        "source_chapter_plan_asset_version_id": plan["source_chapter_plan_asset_version_id"],
        "source_chapter_plan_content_hash": plan["source_chapter_plan_content_hash"],
    }


def build_draft_context_view(context_bundle: dict[str, Any]) -> dict[str, Any]:
    view = dict(context_bundle.get("stage_context_view") or {})
    manifest = dict(context_bundle.get("context_manifest") or {})
    task = dict(manifest.get("task") or {})
    replay = dict(manifest.get("replay") or {})
    return {
        "contract_version": "draft-context-view-v1",
        "stage": "draft",
        "segments": list(view.get("segments") or view.get("context_segments") or []),
        "target_capability_id": str(task.get("target_capability_id") or ""),
        "narrative_position": dict(manifest.get("narrative_position") or {}),
        "authority_state_boundary": dict(
            manifest.get("authority_state_boundary") or {}
        ),
        "narrative_boundaries": dict(manifest.get("narrative_boundaries") or {}),
        "context_replay_input_digest": str(replay.get("input_digest") or ""),
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
    "ChapterPlanQualificationProfile", "ChapterPlanQualificationReport",
    "LEGACY_COMPATIBILITY_PROFILE", "PLAN_FIELDS", "build_draft_context_view",
    "build_draft_plan_view", "build_draft_style_view",
    "normalize_authoritative_chapter_plan", "qualification_profile_for_plan",
]
