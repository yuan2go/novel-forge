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
KNOWLEDGE_PLAN_FIELDS = (
    "knowledge_translations", "knowledge_translation_policy_version", "craft_strategy",
)


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


def qualification_profile_for_plan(
    content: dict[str, Any],
) -> ChapterPlanQualificationProfile:
    chapter = int(content.get("chapter") or 0)
    function = str(content.get("chapter_function") or "ordinary").strip().lower()
    phase = str(content.get("book_phase") or ("opening" if chapter == 1 else "ordinary")).lower()
    from novel_forge.modules.story_design_authority.qualification import (
        uses_work_requirements,
    )

    if (
        uses_work_requirements(content)
        or content.get("chapter_contract_schema_version") == "chapter-mission-scene.v3"
    ):
        return ChapterPlanQualificationProfile(
            profile_id="chapter-plan-work-v1",
            required_fields=("title", "premise", "chapter_objective", "scene_sequence"),
            warning_fields=(),
            genre=str(content.get("genre") or "any"),
            platform=str(content.get("platform") or "any"),
            book_phase=phase,
            chapter_function=function,
            contract_version="chapter-plan-qualification-profile-v2",
        )
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


def resolve_chapter_plan_book_id(
    *, project_id: str, plan: dict[str, Any], host_book_id: str = ""
) -> str:
    extensions = plan.get("source_extensions")
    identities = [host_book_id, plan.get("book_id")]
    if isinstance(extensions, dict):
        identities.append(extensions.get("book_id"))
    declared = {str(value).strip() for value in identities if value}
    if len(declared) > 1:
        raise KernelError("CHAPTER_PLAN_CROSS_BOOK", "ChapterPlan Book differs from its frozen host command")
    return next(iter(declared)) if declared else f"book:{project_id}"


def normalize_authoritative_chapter_plan(
    *,
    project_id: str,
    expected_chapter: int,
    expected_book_id: str = "",
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
        "book_id": resolve_chapter_plan_book_id(project_id=project_id, plan=content, host_book_id=expected_book_id),
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
    normalized.update({key: content[key] for key in KNOWLEDGE_PLAN_FIELDS if key in content})
    known = {"project_id", "book_id", "chapter", "title", "premise", "objective", "beats", "scenes", "closing_hook", "schema_version", "contract_version", *PLAN_FIELDS, *KNOWLEDGE_PLAN_FIELDS}
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


def build_draft_plan_view(
    plan: dict[str, Any], *, work_requirements: bool = False
) -> dict[str, Any]:
    from novel_forge.modules.story_design_authority.author_input import project_author_design, without_author_private

    result = {
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
        **{key: plan[key] for key in KNOWLEDGE_PLAN_FIELDS if key in plan},
    }
    result = without_author_private(result)
    if work_requirements:
        result["contract_version"] = "draft-plan-view-v2"
        result["style_constraints"] = plan.get("style_constraints", [])
        source = {**dict(plan.get("source_extensions") or {}), **plan}
        if source.get("runtime_projection_version") == "2.0.0":
            result["contract_version"] = "draft-plan-view-v3"
            result["method_choices"] = {key: source[key] for key in (
                "reward_action", "promise_action", "ending_hook", "antagonist_actions",
            ) if key in source}
    binding = (plan.get("constraint_envelope") or {}).get("author_design")
    if binding:
        result["author_design_guidance"] = project_author_design(binding, target="CHAPTER", chapter=int(plan["chapter"]))
    return result


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


def build_draft_style_view(
    context_bundle: dict[str, Any], *, work_requirements: bool = False
) -> dict[str, Any]:
    style_segments = [
        segment for segment in context_bundle.get("context_segments", [])
        if segment.get("asset_type") == "style_policy"
    ]
    if work_requirements:
        selected = context_bundle.get("production_input_manifest", {}).get("style_policy_version_id")
        style_segments = [segment for segment in style_segments if segment.get("asset_version_id") == selected]
        if len(style_segments) != 1:
            raise KernelError("WORK_STYLE_SELECTION_INVALID", "The work baseline needs exactly its selected style version")
    return {
        "contract_version": "draft-style-view-v2"
        if work_requirements
        else "draft-style-view-v1",
        "style_policy_version_id": str(
            context_bundle.get("production_input_manifest", {}).get(
                "style_policy_version_id"
            )
            or ""
        ),
        "policies": [
            {
                "asset_version_id": segment.get("asset_version_id"),
                "safe_summary": segment.get("safe_summary", ""),
                "structured_facts": list(segment.get("structured_facts") or []),
                **(
                    {
                        "content_hash": segment.get("content_digest")
                        or segment.get("content_hash")
                    }
                    if work_requirements
                    else {}
                ),
                **(
                    {
                        "constraints": next(
                            (
                                fact.get("value")
                                for fact in segment.get("structured_facts", [])
                                if fact.get("key") == "style_constraints"
                            ),
                            segment.get("constraints"),
                        )
                    }
                    if work_requirements
                    else {}
                ),
            }
            for segment in style_segments
        ],
    }


def _method_requirements(plan: dict[str, Any], context_bundle: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "golden_opening": ("golden_opening",),
        "reader_promise": ("promise_action", "reader_promise_actions"),
        "reward": ("reward_action", "reward_setup", "reward_payoff"),
        "protagonist_charm": ("protagonist_charm_mechanism",),
        "antagonist_pressure": ("antagonist_pressure", "antagonist_actions"),
        "chapter_hook": ("ending_hook", "chapter_hook"),
        "suspense_progression": ("suspense_curve",),
        "emotional_curve": ("emotional_curve",),
        "serialization_function": ("serialization_function",),
    }
    source = {**dict(plan.get("source_extensions") or {}), **plan}
    result = {}
    for dimension, aliases in fields.items():
        present = [name for name in aliases if name in source]
        selected = [name for name in present if source[name] not in (None, "", [], {})]
        if (
            dimension == "golden_opening"
            and source.get("chapter_contract_schema_version")
            == "chapter-mission-scene.v3"
        ):
            selected = (
                ["primary_function"]
                if source.get("primary_function") == "golden_opening"
                else []
            )
            present = ["primary_function"]
        confirmed = plan.get(
            "chapter_contract_schema_version"
        ) == "chapter-mission-scene.v3" and bool(present)
        result[dimension] = {
            "status": "APPLICABLE"
            if selected
            else "NOT_APPLICABLE"
            if confirmed
            else "UNDETERMINED",
            "source_fields": present,
            **({"selected_values": {name: source[name] for name in present}}
               if source.get("runtime_projection_version") == "2.0.0" else {}),
        }
    aliases = {"$.serialization_potential": "serialization_function"}
    selected_style = context_bundle.get("production_input_manifest", {}).get("style_policy_version_id")
    book_id = context_bundle.get("book_id") or plan.get("book_id")
    bound_styles = [segment for segment in context_bundle.get("context_segments", [])
                    if segment.get("asset_type") == "style_policy" and segment.get("asset_version_id") == selected_style]
    if len(bound_styles) > 1:
        raise KernelError("WORK_APPLICABILITY_SOURCE_INVALID", "Selected style must have one exact Context projection")
    for segment in context_bundle.get("context_segments", []):
        if segment.get("asset_type") != "style_policy":
            continue
        for fact in segment.get("structured_facts", []):
            if fact.get("key") != "work_applicability":
                continue
            binding = fact.get("value") or {}
            if segment not in bound_styles:
                raise KernelError("WORK_APPLICABILITY_SOURCE_INVALID", "Unselected style cannot declare work requirements")
            if (not binding.get("source_asset_version_id") or not binding.get("source_content_hash")
                    or binding.get("scope") != "BOOK" or not book_id or binding.get("book_id") != book_id
                    or {"asset_version_id": binding.get("source_asset_version_id"),
                        "content_hash": binding.get("source_content_hash")} not in binding.get("source_bindings", [])):
                raise KernelError("WORK_APPLICABILITY_SOURCE_INVALID", "Work choices need exact approved Foundation provenance")
            for declaration in binding.get("declarations", []):
                dimension = aliases.get(declaration.get("field_path"))
                if not dimension:
                    continue
                status = declaration.get("status")
                if status not in {"APPLICABLE", "NOT_APPLICABLE", "PROHIBITED", "UNDETERMINED"}:
                    raise KernelError("WORK_APPLICABILITY_INVALID", "Unknown work method choice")
                local = result[dimension]
                prior = local.get("work_requirement")
                if prior and prior["status"] != status:
                    raise KernelError("QUALITY_APPLICABILITY_CONFLICT", "Frozen work decisions contradict each other")
                local["work_requirement"] = {**declaration, **{key: binding[key] for key in ("scope", "source_asset_version_id", "source_content_hash")}}
                if status in {"PROHIBITED", "NOT_APPLICABLE", "UNDETERMINED"}:
                    if local["status"] == "APPLICABLE":
                        raise KernelError("QUALITY_APPLICABILITY_CONFLICT", "Chapter selection contradicts the frozen work method decision")
                    local["status"] = status
                elif status == "APPLICABLE":
                    if local["status"] == "NOT_APPLICABLE":
                        raise KernelError("QUALITY_APPLICABILITY_CONFLICT", "Chapter omission contradicts the frozen work requirement")
                    local["status"] = status
    return result


def build_creative_baseline(
    plan: dict[str, Any], context_bundle: dict[str, Any]
) -> dict[str, Any]:
    from novel_forge.modules.story_design_authority.author_input import (
        compile_provider_author_projection,
    )

    view = build_draft_plan_view(plan, work_requirements=True)
    baseline = {
        "contract_version": "creative-baseline.v1",
        "chapter": view["chapter"],
        "source_plan": {
            "asset_version_id": view["source_chapter_plan_asset_version_id"],
            "content_hash": view["source_chapter_plan_content_hash"],
        },
        "style_constraints": view["style_constraints"],
        "method_requirements": _method_requirements(plan, context_bundle),
        "point_of_view": view.get("point_of_view"),
        "target_word_count": view.get("target_word_count"),
        "prohibited_outcomes": view.get("prohibited_outcomes"),
        "style": build_draft_style_view(context_bundle, work_requirements=True),
        "author_guidance": compile_provider_author_projection(
            view.get("author_design_guidance") or {}
        ),
    }
    baseline["baseline_digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                baseline, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    return baseline


def validate_creative_baseline(baseline: Any) -> dict[str, Any]:
    keys = {
        "contract_version",
        "chapter",
        "source_plan",
        "style_constraints",
        "point_of_view",
        "target_word_count",
        "prohibited_outcomes",
        "style",
        "author_guidance",
        "method_requirements",
        "baseline_digest",
    }
    if (
        not isinstance(baseline, dict)
        or set(baseline) != keys
        or baseline.get("contract_version") != "creative-baseline.v1"
    ):
        raise KernelError(
            "CREATIVE_BASELINE_REQUIRED",
            "The work contract requires an exact public creative baseline",
        )
    body = {key: value for key, value in baseline.items() if key != "baseline_digest"}
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
    )
    if (
        digest != baseline["baseline_digest"]
        or not isinstance(baseline["style"], dict)
        or baseline["style"].get("contract_version") != "draft-style-view-v2"
    ):
        raise KernelError(
            "CREATIVE_BASELINE_DRIFT",
            "Creative baseline bytes differ from their frozen digest",
        )
    return baseline


__all__ = [
    "ChapterPlanQualificationProfile",
    "ChapterPlanQualificationReport",
    "LEGACY_COMPATIBILITY_PROFILE",
    "PLAN_FIELDS",
    "build_draft_context_view",
    "build_draft_plan_view",
    "build_draft_style_view",
    "normalize_authoritative_chapter_plan",
    "qualification_profile_for_plan",
    "build_creative_baseline",
]
