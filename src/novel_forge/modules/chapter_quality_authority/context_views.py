from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any, Protocol

from novel_forge.modules.command_kernel.errors import KernelError


STATE_ASSET_TYPES = (
    "canon_snapshot",
    "story_state_snapshot",
)

# WHY: Provider quality judges need narrative meaning and stable identity, not the
# extraction transport/evidence envelope retained by PostgreSQL Authority.  The
# full candidate remains addressable through its Canon Patch AssetVersion and
# the digests emitted by this view.
_AUTHORITY_EVIDENCE_KEYS = frozenset(
    {
        "approval_requirement",
        "approval_resolution",
        "confidence",
        "evidence_end",
        "evidence_start",
        "extraction_evidence",
        "extractor_type",
        "model_id",
        "prompt_version",
        "provider_id",
        "source_id",
        "source_revision_asset_version_id",
    }
)

_CONFLICT_CANDIDATE_SUMMARY_KEYS = (
    "entity_key",
    "subject",
    "predicate",
    "object",
    "character_id",
    "source_id",
    "source_character_id",
    "target_id",
    "target_character_id",
    "arc_id",
    "thread_id",
    "rule_id",
    "fact_id",
    "proposition_id",
    "disclosure_id",
    "audience",
    "disclosure_mode",
    "impact_type",
    "from_state",
    "from_status",
    "from_stage",
    "from_tier",
    "state",
    "status",
    "stage",
    "tier",
)


class TokenEstimator(Protocol):
    def estimate(self, value: str) -> int: ...


class ConservativeTokenEstimator:

    def estimate(self, value: str) -> int:
        if not value:
            return 0
        return max(1, (len(value.encode("utf-8")) + 2) // 3)


@dataclass(frozen=True, slots=True)
class CompiledQualityPolicy:
    source_asset_version_id: str
    thresholds: dict[str, Any]
    deterministic_policy_thresholds: tuple[str, ...]
    policy_digest: str
    contract_version: str = "compiled-quality-policy-v1"


@dataclass(frozen=True, slots=True)
class CompiledWorkQualityPolicy(CompiledQualityPolicy):
    dimension_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompiledPlatformPolicy:
    source_asset_version_id: str
    chapter_length_rules: dict[str, Any]
    format_rules: dict[str, Any]
    sensitive_content_rules: tuple[str, ...]
    ai_content_policy: dict[str, Any]
    opening_expectations: tuple[str, ...]
    rhythm_expectations: tuple[str, ...]
    publish_metadata_rules: dict[str, Any]
    policy_digest: str
    contract_version: str = "compiled-platform-policy-v1"


def compile_quality_policy(
    *,
    profile_asset_version_id: str,
    segment: dict[str, Any],
    work_requirements: bool = False,
) -> CompiledQualityPolicy:
    _require_profile_segment(profile_asset_version_id, segment, "quality")
    facts = _facts(segment)
    configured = dict(facts.get("thresholds") or facts.get("quality_thresholds") or {})
    defaults = {
        "readability": 70,
        "maximum_average_paragraph": 270,
        "maximum_duplicate_sentence_ratio": 0.25,
        "minimum_prose_characters": 80,
    }
    if work_requirements:
        defaults = {
            "readability": None,
            "maximum_average_paragraph": None,
            "maximum_duplicate_sentence_ratio": None,
            "minimum_prose_characters": 80,
            "minimum_sentences": 1,
            "sentence_length_unit": "CODEPOINTS",
            "readability_sentence_target": 36,
            "readability_penalty": 2,
        }
    thresholds = {**defaults, **configured}
    if work_requirements:
        for key in defaults.keys() - {"sentence_length_unit"}:
            value = thresholds[key]
            if value is None and key in {
                "readability",
                "maximum_average_paragraph",
                "maximum_duplicate_sentence_ratio",
            }:
                continue
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise KernelError(
                    "QUALITY_POLICY_THRESHOLD_INVALID",
                    f"{key} needs a finite nonnegative measurement",
                )
        if thresholds["readability"] is not None and thresholds["readability"] > 100:
            raise KernelError(
                "QUALITY_POLICY_THRESHOLD_INVALID", "Readability scores use 0 to 100"
            )
        if (
            thresholds["maximum_duplicate_sentence_ratio"] is not None
            and thresholds["maximum_duplicate_sentence_ratio"] > 1
        ):
            raise KernelError(
                "QUALITY_POLICY_THRESHOLD_INVALID",
                "Duplicate sentence ratio uses 0 to 1",
            )
        if thresholds["sentence_length_unit"] not in {"CODEPOINTS", "WHITESPACE_WORDS"}:
            raise KernelError(
                "QUALITY_POLICY_UNIT_INVALID",
                "Sentence measurement unit is unsupported",
            )
    weights = {}
    if work_requirements:
        from .domain import QUALITY_DIMENSIONS

        weights = dict(facts.get("weights") or {})
        if any(
            key not in QUALITY_DIMENSIONS
            or type(value) not in {int, float}
            or not math.isfinite(value)
            or value < 0
            for key, value in weights.items()
        ):
            raise KernelError(
                "QUALITY_POLICY_WEIGHT_INVALID",
                "Dimension weights must be finite nonnegative numbers for known dimensions",
            )
        for key, value in configured.items():
            if key not in defaults and key not in QUALITY_DIMENSIONS:
                raise KernelError(
                    "QUALITY_POLICY_THRESHOLD_INVALID",
                    "Unsupported quality policy setting",
                )
            if (
                key in QUALITY_DIMENSIONS
                and value is not None
                and (
                    type(value) not in {int, float}
                    or not math.isfinite(value)
                    or not 0 <= value <= 100
                )
            ):
                raise KernelError(
                    "QUALITY_POLICY_THRESHOLD_INVALID",
                    "Configured dimension scores use 0 to 100",
                )
        for key in ("minimum_prose_characters", "minimum_sentences"):
            if type(thresholds[key]) is not int or thresholds[key] <= 0:
                raise KernelError(
                    "QUALITY_POLICY_THRESHOLD_INVALID",
                    "Prose integrity limits must be positive integers",
                )
    digest = _digest(
        {
            "source": profile_asset_version_id,
            "thresholds": thresholds,
            **({"weights": weights} if work_requirements else {}),
        }
    )
    policy_type = (
        CompiledWorkQualityPolicy if work_requirements else CompiledQualityPolicy
    )
    return policy_type(
        source_asset_version_id=profile_asset_version_id,
        thresholds=thresholds,
        deterministic_policy_thresholds=tuple(
            key for key in defaults if key not in configured
        ),
        policy_digest=digest,
        contract_version="compiled-quality-policy-v2"
        if work_requirements
        else "compiled-quality-policy-v1",
        **({"dimension_weights": weights} if work_requirements else {}),
    )


def compile_platform_policy(
    *, profile_asset_version_id: str, segment: dict[str, Any]
) -> CompiledPlatformPolicy:
    _require_profile_segment(profile_asset_version_id, segment, "platform")
    facts = _facts(segment)
    rules = dict(facts.get("platform_rules") or facts.get("rules") or {})
    chapter_length = dict(
        rules.get("chapter_length") or facts.get("chapter_length_rules") or {}
    )
    if not chapter_length:
        chapter_length = {"status": "INSUFFICIENT_EVIDENCE"}
    return CompiledPlatformPolicy(
        source_asset_version_id=profile_asset_version_id,
        chapter_length_rules=chapter_length,
        format_rules=dict(rules.get("format") or facts.get("format_rules") or {}),
        sensitive_content_rules=tuple(
            rules.get("sensitive_content") or facts.get("sensitive_content_rules") or ()
        ),
        ai_content_policy=dict(
            rules.get("ai_content") or facts.get("ai_content_policy") or {}
        ),
        opening_expectations=tuple(
            rules.get("opening") or facts.get("opening_expectations") or ()
        ),
        rhythm_expectations=tuple(
            rules.get("rhythm") or facts.get("rhythm_expectations") or ()
        ),
        publish_metadata_rules=dict(
            rules.get("publish_metadata") or facts.get("publish_metadata_rules") or {}
        ),
        policy_digest=_digest({"source": profile_asset_version_id, "facts": facts}),
    )


def build_quality_context_view(
    *,
    group: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    chapter_plan: dict[str, Any],
    chapter_plan_asset_version_id: str,
    context_bundle: dict[str, Any],
    context_bundle_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    token_budget: int = 6000,
    token_estimator: TokenEstimator | None = None,
    work_requirements: bool = False,
) -> dict[str, Any]:
    if token_budget <= 0:
        raise KernelError(
            "QUALITY_CONTEXT_BUDGET_INVALID", "quality token budget must be positive"
        )
    estimator = token_estimator or ConservativeTokenEstimator()
    if group not in {
        "structural",
        "commercial",
        "source_originality",
        "longform",
        "platform",
    }:
        raise KernelError("QUALITY_GROUP_INVALID", "quality context group is invalid")
    manifest = dict(context_bundle.get("production_input_manifest") or {})
    quality_profile_id = str(manifest.get("quality_profile_version_id") or "")
    platform_profile_id = str(manifest.get("platform_profile_version_id") or "")
    segments = list(context_bundle.get("context_segments") or [])
    quality_policy = compile_quality_policy(
        profile_asset_version_id=quality_profile_id,
        segment=_segment_by_version(segments, quality_profile_id),
        work_requirements=work_requirements,
    )
    platform_policy = compile_platform_policy(
        profile_asset_version_id=platform_profile_id,
        segment=_segment_by_version(segments, platform_profile_id),
    )
    common = {
        "project_id": str(context_bundle.get("project_id") or ""),
        "target_revision_asset_version_id": revision_asset_version_id,
        "chapter_plan_asset_version_id": chapter_plan_asset_version_id,
        "context_bundle_asset_version_id": context_bundle_asset_version_id,
        "quality_profile_version_id": quality_profile_id,
        "platform_profile_version_id": platform_profile_id,
        "compiled_quality_policy": asdict(quality_policy),
    }
    if work_requirements:
        from novel_forge.modules.chapter_authority.chapter_plan_views import (
            build_creative_baseline,
        )

        baseline = build_creative_baseline(chapter_plan, context_bundle)
        if revision.get("creative_baseline") != baseline:
            raise KernelError(
                "QUALITY_CREATIVE_BASELINE_DRIFT",
                "Quality must consume the candidate's exact frozen creative baseline",
            )
        common["creative_baseline"] = baseline
    if group == "structural":
        body = {
            "type": "StructuralQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "target_word_count": chapter_plan.get("target_word_count"),
            "paragraph_policy": quality_policy.thresholds,
            "dialogue_narration_policy": chapter_plan.get("style_constraints", {}),
            "readability_policy": quality_policy.thresholds,
            "mobile_reading_policy": quality_policy.thresholds,
            "format_policy": platform_policy.format_rules,
            "chapter_intent": chapter_plan.get("chapter_intent"),
            "scene_plan": chapter_plan.get("scene_plan", []),
        }
    elif group == "commercial":
        body = {
            "type": "CommercialQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "chapter_function": chapter_plan.get("chapter_function"),
            "chapter_objective": chapter_plan.get("chapter_objective"),
            "reader_promise_actions": chapter_plan.get("reader_promise_actions", []),
            "reward_setup": chapter_plan.get("reward_setup", []),
            "reward_payoff": chapter_plan.get("reward_payoff", []),
            "protagonist_charm_mechanism": chapter_plan.get(
                "protagonist_charm_mechanism"
            ),
            "antagonist_pressure": chapter_plan.get("antagonist_pressure"),
            "suspense_curve": chapter_plan.get("suspense_curve", []),
            "emotional_curve": chapter_plan.get("emotional_curve", []),
            "chapter_hook": chapter_plan.get("chapter_hook"),
            "serialization_function": chapter_plan.get("serialization_function"),
            "opening_state": chapter_plan.get("opening_state"),
            "next_chapter_bridge": chapter_plan.get("next_chapter_bridge"),
            "chapter_intent": chapter_plan.get("chapter_intent"),
            "arc_schedule": chapter_plan.get("arc_schedule", []),
            "setups": chapter_plan.get("setups", []),
            "payoffs": chapter_plan.get("payoffs", []),
            "reader_experience": chapter_plan.get("reader_experience", {}),
        }
    elif group == "source_originality":
        governed_segments = [
            {
                "asset_version_id": item.get("asset_version_id"),
                "asset_type": item.get("asset_type"),
                "content_digest": item.get("content_digest"),
                "allowed_use": item.get("allowed_use"),
                "source_expression_included": item.get("source_expression_included"),
                "source_policy_version": item.get("source_policy_version"),
            }
            for item in segments
        ]
        if any(item.get("source_expression_included") for item in governed_segments):
            raise KernelError(
                "QUALITY_SOURCE_CONTEXT_LEAK",
                "Source quality context may not contain source expression",
            )
        body = {
            "type": "SourceOriginalityQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "source_governance": manifest.get("source_governance", {}),
            # WHY: Quality consumes a provenance projection, not a second copy of
            # the full Context Manifest (which remains persisted on the
            # ContextBundle).  This keeps source evidence exact without
            # spending the quality budget on duplicated retrieval traces.
            "context_manifest": _source_context_manifest_view(
                dict(context_bundle.get("context_manifest") or {})
            ),
            "source_isolation_result": context_bundle.get(
                "source_isolation_result", {}
            ),
            "copyright_boundary": context_bundle.get("copyright_boundary"),
            "governed_segment_identities": governed_segments,
            "source_expression_excluded": True,
        }
    elif group == "longform":
        previous_states = _group_state_segments(segments)
        candidates = dict(canon.get("state_changes") or {})
        if (chapter_plan.get("constraint_envelope") or {}).get(
            "world_preparation", {}
        ).get("action", {}).get("contract_version") == "world-production-action.v2":
            from novel_forge.modules.narrative_state.information import (
                disclosed_fact_projection,
            )

            candidates = {
                kind: [
                    disclosed_fact_projection({"state": item})["state"]
                    for item in changes
                    if (item.get("fact_origin") or {}).get("kind")
                    not in {"GOVERNED_BACKGROUND", "GOVERNED_PREPARATION"}
                ]
                for kind, changes in candidates.items()
            }
            candidates = {
                kind: changes for kind, changes in candidates.items() if changes
            }
        current_states = _group_current_state_candidates(candidates)
        body = {
            "type": "LongformQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "canon_patch_asset_version_id": canon_asset_version_id,
            **({'identity_reference_observations':canon['deterministic_validation']['identity_reference_observations'],
                'identity_reference_check_status':canon['deterministic_validation']['identity_reference_check_status'],
                'identity_review_instruction':'Independently check the actual prose for each unresolved reference. A NOT_RUN heuristic is not evidence of either a contradiction or a pass.'}
                if canon.get('deterministic_validation',{}).get('validation_contract')=='grounded-canon-validation.v2' else {}),
            "canon_conflicts": _project_canon_conflicts(
                list(canon.get("conflicts") or [])
            ),
            "previous_state_snapshots": previous_states,
            "current_state_candidates": current_states,
            "governed_world_rules": _segments_of_type(segments, "world_bible"),
            "volume_arc": _segments_of_type(segments, "volume_arc"),
            "arc_progress": _segments_of_type(segments, "arc_progress_report"),
            "previous_recap": _segments_of_type(segments, "longform_recap_report"),
            "chapter_plan": _longform_chapter_plan_view(chapter_plan, include_governed_constraints=canon.get("deterministic_validation",{}).get("validation_contract")=="grounded-canon-validation.v2"),
            "canon_change_proposal_asset_version_id": canon.get(
                "canon_change_proposal_asset_version_id", ""
            ),
        }
    else:
        source_extensions = chapter_plan.get("source_extensions")
        summary = (
            chapter_plan.get("safe_summary")
            or (
                source_extensions.get("safe_summary")
                if isinstance(source_extensions, dict)
                else ""
            )
            or chapter_plan.get("premise")
            or ""
        )
        body = {
            "type": "PlatformQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "compiled_platform_policy": asdict(platform_policy),
            "publish_metadata_candidate": {
                "chapter": revision.get("chapter"),
                "title": str(revision.get("title") or chapter_plan.get("title") or ""),
                "summary": str(summary),
            },
        }
    body["token_budget"] = token_budget
    coverage = _fit_quality_context(
        body,
        estimator=estimator,
        token_budget=token_budget,
    )
    body["coverage_report"] = coverage
    body["contract_version"] = (
        "stage-quality-context-v7" if work_requirements and group == "longform" and canon.get("deterministic_validation",{}).get("validation_contract")=="grounded-canon-validation.v2" else "stage-quality-context-v6" if work_requirements else "stage-quality-context-v4"
    )
    if work_requirements:
        body["evaluation_semantics_version"] = "work-quality.v2"
    body["context_digest"] = _digest(body)
    final_tokens = _estimate_payload(body, estimator)
    if final_tokens > token_budget:
        raise KernelError(
            "QUALITY_CONTEXT_CRITICAL_OVERFLOW",
            "quality context identity and critical evidence exceed the frozen token budget",
        )
    body["coverage_report"]["token_estimate"] = final_tokens
    return body


def _require_profile_segment(
    version_id: str, segment: dict[str, Any], label: str
) -> None:
    if not version_id or segment.get("asset_version_id") != version_id:
        raise KernelError(
            "QUALITY_PROFILE_VERSION_MISSING",
            f"frozen {label} profile content is missing from ContextBundle",
        )


def _source_context_manifest_view(manifest: dict[str, Any]) -> dict[str, Any]:
    selected = manifest.get("selected_inputs") or ()
    return {
        "contract_version": manifest.get("contract_version"),
        "context_fingerprint": manifest.get("context_fingerprint"),
        "accepted_boundary": manifest.get("accepted_boundary", {}),
        "selected_inputs": [
            {
                "asset_version_id": item.get("asset_version_id"),
                "asset_type": item.get("asset_type"),
                "context_class": item.get("context_class"),
                "memory_layer": item.get("memory_layer"),
                "provenance": item.get("provenance", {}),
            }
            for item in selected
            if isinstance(item, dict)
        ],
    }


def _segment_by_version(
    segments: list[dict[str, Any]], version_id: str
) -> dict[str, Any]:
    return next(
        (item for item in segments if item.get("asset_version_id") == version_id), {}
    )


def _facts(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item.get("key") or item.get("kind") or ""): item.get("value")
        for item in segment.get("structured_facts", [])
        if isinstance(item, dict)
    }


def _segments_of_type(
    segments: list[dict[str, Any]], asset_type: str
) -> list[dict[str, Any]]:
    return [
        {
            "asset_version_id": item.get("asset_version_id"),
            "content_digest": item.get("content_digest"),
            "structured_facts": item.get("structured_facts", []),
        }
        for item in segments
        if item.get("asset_type") == asset_type
    ]


def _group_state_segments(
    segments: list[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        state_type: {} for state_type in STATE_ASSET_TYPES
    }
    for item in segments:
        state_type = str(item.get("asset_type") or "")
        if state_type not in grouped:
            continue
        facts = list(item.get("structured_facts") or [])
        if state_type in {"story_state_snapshot", "canon_snapshot"}:
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                identity = str(
                    fact.get("entity_key") or _state_identity(fact, state_type)
                )
                rows = grouped[state_type].setdefault(identity, [])
                if rows and rows[-1].get("asset_version_id") == item.get(
                    "asset_version_id"
                ):
                    rows[-1]["structured_facts"].append(fact)
                else:
                    rows.append(
                        {
                            "asset_version_id": item.get("asset_version_id"),
                            "entity_id": identity,
                            "relationship_pair": None,
                            "content_digest": item.get("content_digest"),
                            "chapter": item.get("chapter"),
                            "qualification": item.get("qualification", "ELIGIBLE"),
                            "structured_facts": [fact],
                            "declared_empty": False,
                            "compressed": False,
                            "omitted_fact_count": 0,
                        }
                    )
            continue
        identity = _state_identity(item, state_type)
        declared_empty = bool(
            item.get("declared_empty")
            or any(
                isinstance(fact, dict) and fact.get("declared_empty") for fact in facts
            )
        )
        # WHY: The row-level flag is the canonical empty-state fact. Keeping the
        # ContextSegment's duplicate structured marker wastes scarce judge
        # budget without adding evidence identity.
        if declared_empty:
            facts = []
        grouped[state_type].setdefault(identity, []).append(
            {
                "asset_version_id": item.get("asset_version_id"),
                "entity_id": item.get("entity_id"),
                "relationship_pair": item.get("relationship_pair"),
                "content_digest": item.get("content_digest"),
                "chapter": item.get("chapter"),
                "qualification": item.get("qualification", "ELIGIBLE"),
                "structured_facts": facts,
                "declared_empty": declared_empty,
                "compressed": False,
                "omitted_fact_count": 0,
            }
        )
    for state in grouped.values():
        for rows in state.values():
            rows.sort(
                key=lambda row: (
                    int(row.get("chapter") or 0),
                    str(row["asset_version_id"]),
                )
            )
    return grouped


def _group_current_state_candidates(
    candidates: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for state_type, raw_changes in sorted(candidates.items()):
        changes = [dict(item) for item in raw_changes if isinstance(item, dict)]
        changes_by_identity: dict[str, list[dict[str, Any]]] = {}
        for change in changes:
            changes_by_identity.setdefault(
                _state_identity(change, state_type), []
            ).append(change)
        if not changes_by_identity:
            changes_by_identity[f"{state_type}:project"] = []
        for identity, identity_changes in changes_by_identity.items():
            grouped.setdefault(state_type, {}).setdefault(identity, []).append(
                {
                    "asset_version_id": "",
                    "candidate_digest": _digest(
                        {"state_kind": state_type, "changes": changes}
                    ),
                    "entity_id": identity,
                    "chapter": next(
                        (
                            item.get("effective_from_chapter")
                            for item in identity_changes
                            if item.get("effective_from_chapter") is not None
                        ),
                        None,
                    ),
                    "qualification": "CANDIDATE",
                    "previous_asset_version_ids": [],
                    "structured_facts": [
                        _project_narrative_value(item) for item in identity_changes
                    ],
                    "declared_empty": False,
                    "compressed": False,
                    "omitted_fact_count": 0,
                }
            )
    return grouped


def _state_identity(item: dict[str, Any], state_type: str) -> str:
    pair = item.get("relationship_pair")
    if isinstance(pair, (list, tuple)) and pair:
        return "relationship:" + "|".join(sorted(str(value) for value in pair))
    for key in (
        "entity_id",
        "character_id",
        "thread_id",
        "rule_id",
        "logical_ref",
        "foreshadow_id",
        "promise_id",
        "reward_id",
    ):
        if item.get(key):
            return f"{key}:{item[key]}"
    facts = list(item.get("structured_facts") or [])
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        for key in (
            "entity_id",
            "character_id",
            "thread_id",
            "rule_id",
            "logical_ref",
            "foreshadow_id",
            "promise_id",
            "reward_id",
        ):
            if fact.get(key):
                return f"{key}:{fact[key]}"
    return f"{state_type}:project"


def _longform_chapter_plan_view(chapter_plan: dict[str, Any], *, include_governed_constraints: bool = False) -> dict[str, Any]:

    canonical_fields = (
        "chapter",
        "title",
        "prohibited_outcomes",
        "next_chapter_bridge",
        "narrative_architecture_version",
        "narrative_segment_ref",
        "chapter_intent",
        "arc_schedule",
        "setups",
        "payoffs",
        "character_participation",
        "knowledge_boundaries",
        "disclosures",
        "required_state_transitions",
        "reader_experience",
        "expected_exit_state",
    )
    view = {
        field: chapter_plan[field]
        for field in canonical_fields
        if field in chapter_plan
    }
    if include_governed_constraints:
        view['governed_plan_contract'] = {
            'source_chapter_plan_asset_version_id':chapter_plan.get('source_chapter_plan_asset_version_id',''),
            'constraint_envelope':chapter_plan.get('constraint_envelope',{}),
            'world_rule_usages':chapter_plan.get('world_rule_usages',[]),
            'power_state_changes':chapter_plan.get('power_state_changes',[]),
            'evidence_scope':'Governed design requirements and planned uses; neither accepted past events nor a substitute for missing historical state.'}
    view["scene_plan"] = [
        {
            field: scene[field]
            for field in (
                "scene_id",
                "scene_group_id",
                "goal",
                "participants",
            )
            if field in scene
        }
        for scene in chapter_plan.get("scene_plan") or []
        if isinstance(scene, dict)
    ]
    # COMPATIBILITY: Older accepted plans remain readable without duplicating their legacy
    # aliases into plans that already carry the canonical execution contract.
    if not chapter_plan.get("narrative_architecture_version"):
        for field in (
            "premise",
            "objective",
            "chapter_objective",
            "primary_function",
            "secondary_functions",
            "required_state_delta",
            "required_arc_contributions",
            "actual_arc_contributions",
            "reader_promise_actions",
            "promise_action",
            "foreshadow_action",
            "reward_setup",
            "reward_payoff",
            "reward_action",
            "chapter_hook",
            "ending_hook",
        ):
            if field in chapter_plan:
                view[field] = chapter_plan[field]
    return view


def _project_canon_conflicts(conflicts: list[Any]) -> list[dict[str, Any]]:

    projected: list[dict[str, Any]] = []
    for raw in conflicts:
        if not isinstance(raw, dict):
            continue
        candidate = raw.get("candidate_version")
        item = {
            key: raw[key]
            for key in (
                "severity",
                "conflict_code",
                "approval_requirement",
                "recommended_resolution",
            )
            if raw.get(key) not in (None, "", [], {})
        }
        existing = _project_narrative_value(raw.get("existing_version"))
        if existing not in (None, "", [], {}):
            item["expected_version"] = existing
        if candidate not in (None, "", [], {}):
            item["candidate_digest"] = _digest({"candidate": candidate})
            if isinstance(candidate, list):
                item["candidate_count"] = len(candidate)
            else:
                item["candidate_summary"] = _conflict_candidate_summary(candidate)
        item["conflict_digest"] = _digest({"conflict": raw})
        projected.append(item)
    return projected


def _conflict_candidate_summary(value: Any) -> Any:
    if not isinstance(value, dict):
        return _project_narrative_value(value)
    summary = {
        key: _project_narrative_value(value[key])
        for key in _CONFLICT_CANDIDATE_SUMMARY_KEYS
        if value.get(key) not in (None, "", [], {})
    }
    return summary or {"semantic_digest": _digest({"candidate": value})}


def _project_narrative_value(value: Any) -> Any:

    if isinstance(value, dict):
        return {
            str(key): projected
            for key, raw in value.items()
            if key not in _AUTHORITY_EVIDENCE_KEYS
            and (projected := _project_narrative_value(raw))
            not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            projected
            for raw in value
            if (projected := _project_narrative_value(raw))
            not in (None, "", [], {})
        ]
    return value


def _fit_quality_context(
    body: dict[str, Any], *, estimator: TokenEstimator, token_budget: int
) -> dict[str, Any]:
    rows = list(_state_rows(body))
    report_reserve = min(512, max(128, token_budget // 8))
    content_budget = max(1, token_budget - report_reserve)
    while _estimate_payload(body, estimator) > content_budget:
        if not _compress_one_noncritical_fact(body, rows):
            raise KernelError(
                "QUALITY_CONTEXT_CRITICAL_OVERFLOW",
                "quality context identity and critical evidence exceed the frozen token budget",
            )
        rows = list(_state_rows(body))

    # WHY: The coverage report is variable-sized because entity coverage is explicit.
    # A fixed reserve can therefore fit the evidence body yet overflow once the
    # report, contract version, and digest are serialized. Re-evaluate the actual
    # final envelope and only remove additional noncritical facts. Identity rows,
    # AssetVersion lineage, and critical facts remain fail-closed.
    while True:
        coverage = _quality_context_coverage_report(
            body,
            rows=rows,
            estimator=estimator,
            token_budget=token_budget,
        )
        if _estimate_final_quality_context(body, coverage, estimator) <= token_budget:
            return coverage
        if not _compress_one_noncritical_fact(body, rows):
            raise KernelError(
                "QUALITY_CONTEXT_CRITICAL_OVERFLOW",
                "quality context identity and critical evidence exceed the frozen token budget",
            )
        rows = list(_state_rows(body))


def _compress_one_noncritical_fact(
    body: dict[str, Any], rows: list[dict[str, Any]]
) -> bool:
    candidate = next(
        (
            row
            for row in reversed(rows)
            if any(
                not _critical_fact(fact) for fact in row.get("structured_facts") or []
            )
        ),
        None,
    )
    if candidate is None:
        return _compact_noncritical_current_candidate_rows(body)
    facts = list(candidate.get("structured_facts") or [])
    remove_index = max(
        index for index, fact in enumerate(facts) if not _critical_fact(fact)
    )
    facts.pop(remove_index)
    candidate["structured_facts"] = facts
    candidate["compressed"] = True
    candidate["omitted_fact_count"] = int(candidate.get("omitted_fact_count") or 0) + 1
    if not facts:
        _drop_redundant_empty_row_fields(candidate)
    return True


def _quality_context_coverage_report(
    body: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    estimator: TokenEstimator,
    token_budget: int,
) -> dict[str, Any]:
    # WHY: One accepted snapshot may be expanded into many entity-scoped rows. The
    # coverage report records the selected AssetVersion identity, not a second
    # copy of the row-to-version relationship, so keep it set-valued. Entity
    # coverage remains explicit in ``included_entities`` below.
    selected_versions = sorted(
        {
            str(row.get("asset_version_id") or "")
            for row in rows
            if row.get("asset_version_id")
        }
    )
    included_entities = sorted(
        identity
        for state in body.get("previous_state_snapshots", {}).values()
        for identity in state
    )
    included_fact_count = sum(len(row.get("structured_facts") or []) for row in rows)
    omitted_fact_count = sum(int(row.get("omitted_fact_count") or 0) for row in rows)
    return {
        "type": "QualityContextCoverageReport",
        "selected_asset_versions": selected_versions,
        "included_entities": included_entities,
        "omitted_entities": [],
        "included_fact_count": included_fact_count,
        "omitted_fact_count": omitted_fact_count,
        "token_estimate": _estimate_payload(body, estimator),
        "token_budget": token_budget,
        "critical_facts_preserved": True,
        "coverage_status": "COMPRESSED" if omitted_fact_count else "COMPLETE",
        "repair_actions": [],
        "contract_version": "quality-context-coverage-v1",
    }


def _estimate_final_quality_context(
    body: dict[str, Any],
    coverage: dict[str, Any],
    estimator: TokenEstimator,
) -> int:
    envelope = {
        **body,
        "coverage_report": coverage,
        "contract_version": "stage-quality-context-v4",
        # WHY: The digest value is fixed-width. Its value does not affect the token
        # estimate, so a placeholder avoids a circular digest dependency.
        "context_digest": "sha256:" + ("0" * 64),
    }
    return _estimate_payload(envelope, estimator)


def _drop_redundant_empty_row_fields(row: dict[str, Any]) -> None:

    for key in ("entity_id", "relationship_pair", "chapter"):
        if row.get(key) is None:
            row.pop(key, None)
    if row.get("declared_empty") is False:
        row.pop("declared_empty", None)


def _compact_noncritical_current_candidate_rows(body: dict[str, Any]) -> bool:

    changed = False
    for state in body.get("current_state_candidates", {}).values():
        compactable: list[tuple[str, dict[str, Any]]] = []
        retained: dict[str, list[dict[str, Any]]] = {}
        for identity, identity_rows in state.items():
            if identity == "compressed:noncritical":
                retained[identity] = identity_rows
                continue
            empty_rows = [
                row
                for row in identity_rows
                if not list(row.get("structured_facts") or [])
            ]
            nonempty_rows = [row for row in identity_rows if row not in empty_rows]
            if nonempty_rows:
                retained[identity] = nonempty_rows
            compactable.extend((identity, row) for row in empty_rows)
        if len(compactable) < 2:
            continue
        identities = list(dict.fromkeys(identity for identity, _row in compactable))
        rows = [row for _identity, row in compactable]
        previous_versions = sorted(
            {
                str(version)
                for row in rows
                for version in row.get("previous_asset_version_ids", [])
                if version
            }
        )
        candidate_digests = sorted(
            {
                str(row.get("candidate_digest") or "")
                for row in rows
                if row.get("candidate_digest")
            }
        )
        retained["compressed:noncritical"] = [
            {
                "asset_version_id": "",
                "candidate_digests": candidate_digests,
                "included_identities": identities,
                "identity_count": len(identities),
                "chapter": max(int(row.get("chapter") or 0) for row in rows),
                "qualification": "CANDIDATE",
                "previous_asset_version_ids": previous_versions,
                "structured_facts": [],
                "declared_empty": False,
                "compressed": True,
                "omitted_fact_count": sum(
                    int(row.get("omitted_fact_count") or 0) for row in rows
                ),
            }
        ]
        state.clear()
        state.update(retained)
        changed = True
    return changed


def _state_rows(body: dict[str, Any]):
    for group_key in ("previous_state_snapshots", "current_state_candidates"):
        for state in body.get(group_key, {}).values():
            for rows in state.values():
                yield from rows


def _critical_fact(fact: Any) -> bool:
    if not isinstance(fact, dict):
        return False
    return bool(
        fact.get("declared_empty")
        or fact.get("blocking")
        or fact.get("unresolved")
        or fact.get("high_risk")
        or fact.get("conflict_codes")
    )


def _estimate_payload(payload: dict[str, Any], estimator: TokenEstimator) -> int:
    return estimator.estimate(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    )


def _digest(payload: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
    )


__all__ = [
    "CompiledPlatformPolicy",
    "CompiledQualityPolicy",
    "ConservativeTokenEstimator",
    "STATE_ASSET_TYPES",
    "TokenEstimator",
    "build_quality_context_view",
    "compile_platform_policy",
    "compile_quality_policy",
]
