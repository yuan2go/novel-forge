from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


STATE_ASSET_TYPES = (
    "canon_snapshot", "character_state_snapshot", "relationship_state_snapshot",
    "timeline_snapshot", "foreshadow_snapshot", "promise_ledger_snapshot",
    "reward_ledger_snapshot", "world_rule_snapshot", "power_state_snapshot",
)


@dataclass(frozen=True, slots=True)
class CompiledQualityPolicy:
    source_asset_version_id: str
    thresholds: dict[str, Any]
    deterministic_policy_thresholds: tuple[str, ...]
    policy_digest: str
    contract_version: str = "compiled-quality-policy-v1"


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
    *, profile_asset_version_id: str, segment: dict[str, Any]
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
    thresholds = {**defaults, **configured}
    digest = _digest({"source": profile_asset_version_id, "thresholds": thresholds})
    return CompiledQualityPolicy(
        source_asset_version_id=profile_asset_version_id,
        thresholds=thresholds,
        deterministic_policy_thresholds=tuple(
            key for key in defaults if key not in configured
        ),
        policy_digest=digest,
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
            rules.get("publish_metadata")
            or facts.get("publish_metadata_rules")
            or {}
        ),
        policy_digest=_digest(
            {"source": profile_asset_version_id, "facts": facts}
        ),
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
) -> dict[str, Any]:
    if group not in {
        "structural", "commercial", "source_originality", "longform", "platform"
    }:
        raise KernelError("QUALITY_GROUP_INVALID", "quality context group is invalid")
    manifest = dict(context_bundle.get("production_input_manifest") or {})
    quality_profile_id = str(manifest.get("quality_profile_version_id") or "")
    platform_profile_id = str(manifest.get("platform_profile_version_id") or "")
    segments = list(context_bundle.get("context_segments") or [])
    quality_policy = compile_quality_policy(
        profile_asset_version_id=quality_profile_id,
        segment=_segment_by_version(segments, quality_profile_id),
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
            "protagonist_charm_mechanism": chapter_plan.get("protagonist_charm_mechanism"),
            "antagonist_pressure": chapter_plan.get("antagonist_pressure"),
            "suspense_curve": chapter_plan.get("suspense_curve", []),
            "emotional_curve": chapter_plan.get("emotional_curve", []),
            "chapter_hook": chapter_plan.get("chapter_hook"),
            "serialization_function": chapter_plan.get("serialization_function"),
            "opening_state": chapter_plan.get("opening_state"),
            "next_chapter_bridge": chapter_plan.get("next_chapter_bridge"),
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
            "context_manifest": context_bundle.get("context_manifest", {}),
            "source_isolation_result": context_bundle.get("source_isolation_result", {}),
            "copyright_boundary": context_bundle.get("copyright_boundary"),
            "governed_segment_identities": governed_segments,
            "source_expression_excluded": True,
        }
    elif group == "longform":
        previous_states = {
            state_type: _compress_state_segments(
                [item for item in segments if item.get("asset_type") == state_type],
                token_budget=max(100, token_budget // 12),
            )
            for state_type in STATE_ASSET_TYPES
        }
        current_states = {
            str(item.get("asset_type")): item
            for item in canon.get("snapshot_candidates", [])
        }
        body = {
            "type": "LongformQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "canon_patch_asset_version_id": canon_asset_version_id,
            "canon_conflicts": canon.get("conflicts", []),
            "previous_state_snapshots": previous_states,
            "current_state_candidates": current_states,
            "volume_arc": _segments_of_type(segments, "volume_arc"),
            "arc_progress": _segments_of_type(segments, "arc_progress_report"),
            "previous_recap": _segments_of_type(segments, "longform_recap_report"),
            "chapter_plan": chapter_plan,
            "canon_change_proposal_asset_version_id": canon.get(
                "canon_change_proposal_asset_version_id", ""
            ),
        }
    else:
        body = {
            "type": "PlatformQualityContextView",
            **common,
            "revision_text": str(revision.get("text") or ""),
            "compiled_platform_policy": asdict(platform_policy),
        }
    body["token_budget"] = token_budget
    body["context_digest"] = _digest(body)
    body["contract_version"] = "stage-quality-context-v1"
    return body


def _require_profile_segment(version_id: str, segment: dict[str, Any], label: str) -> None:
    if not version_id or segment.get("asset_version_id") != version_id:
        raise KernelError(
            "QUALITY_PROFILE_VERSION_MISSING",
            f"frozen {label} profile content is missing from ContextBundle",
        )


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
        for item in segments if item.get("asset_type") == asset_type
    ]


def _compress_state_segments(
    segments: list[dict[str, Any]], *, token_budget: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    remaining = token_budget
    for item in segments:
        facts = list(item.get("structured_facts") or [])
        allowed = max(1, remaining // 12)
        kept = facts[:allowed]
        rows.append({
            "asset_version_id": item.get("asset_version_id"),
            "content_digest": item.get("content_digest"),
            "structured_facts": kept,
            "declared_empty": bool(
                kept and isinstance(kept[0], dict) and kept[0].get("declared_empty")
            ),
            "compressed": len(kept) < len(facts),
            "omitted_fact_count": max(0, len(facts) - len(kept)),
        })
        remaining = max(0, remaining - max(1, len(json.dumps(kept)) // 4))
    return rows


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


__all__ = [
    "CompiledPlatformPolicy", "CompiledQualityPolicy", "STATE_ASSET_TYPES",
    "build_quality_context_view", "compile_platform_policy", "compile_quality_policy",
]
