"""Storage-free governed context selection and immutable bundle payloads.

The module is shared by compatibility services and PostgreSQL Authority
handlers.  It never discovers assets or persists results; callers must supply
project-scoped, versioned candidates and persist the returned payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable


ELIGIBLE_QUALIFICATIONS = {"ELIGIBLE"}
BLOCKED_QUALIFICATIONS = {"REVOKED", "STALE", "QUARANTINED", "REQUIRES_APPROVAL"}
SOURCE_MODES = {"generation", "summary_only", "structure_only", "review_only", "eval_only"}


@dataclass(frozen=True, slots=True)
class ContextProfile:
    name: str
    allowed_asset_types: frozenset[str]
    forbidden_asset_types: frozenset[str]
    required_asset_types: frozenset[str]
    maximum_raw_source_ratio: float
    maximum_token_budget: int
    source_risk_threshold: int
    generation_allowed_requirement: bool
    copyright_mode: str
    evidence_only_types: frozenset[str] = field(default_factory=frozenset)
    review_only_types: frozenset[str] = field(default_factory=frozenset)
    priority_rules: tuple[str, ...] = ()
    compression_policy: str = "rank_then_compress"


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    asset_version_id: str
    asset_type: str
    project_id: str
    estimated_tokens: int
    relevance_score: float = 0.0
    qualification: str = "ELIGIBLE"
    governance_status: str = "CLEAR"
    source_use_mode: str = "generation"
    source_risk: int = 0
    raw_source: bool = False
    content_digest: str = ""
    policy_version: str = ""
    invalidation_keys: tuple[str, ...] = ()
    narrative_function: str = ""
    safe_summary: str = ""
    structured_facts: tuple[dict[str, Any], ...] = ()
    allowed_use: str = "generation"
    compression_method: str = "safe_summary"


@dataclass(frozen=True, slots=True)
class ContextSegment:
    asset_version_id: str
    asset_type: str
    narrative_function: str
    safe_summary: str
    structured_facts: tuple[dict[str, Any], ...]
    allowed_use: str
    content_digest: str
    source_policy_version: str
    token_count: int
    compression_method: str
    source_expression_included: bool = False


@dataclass(frozen=True, slots=True)
class ContextSelection:
    selected: tuple[ContextCandidate, ...]
    rejected: tuple[dict[str, str], ...]
    estimated_tokens: int
    token_budget: int


_RAW_TYPES = frozenset({"source_document", "source_chunk", "cleaned_text", "parallel_pair"})
_COMMON = frozenset({
    "chapter_plan", "chapter_plan_version", "outline_version", "volume_arc", "world_bible",
    "character_card", "character_state", "relationship_state", "canon_snapshot",
    "timeline_snapshot", "foreshadow_state", "reader_promise", "reward_ledger",
    "character_state_snapshot", "relationship_state_snapshot", "foreshadow_snapshot",
    "promise_ledger_snapshot", "reward_ledger_snapshot", "world_rule_snapshot",
    "power_state_snapshot",
    "style_policy", "knowledge_pack", "knowledge_card", "material_asset", "material_card",
    "quality_rubric", "quality_profile", "platform_profile", "context_profile",
    "theme_arc", "theme_beat", "closure_plan", "review_issue", "review_report",
    "draft_chapter", "draft_version", "quality_report", "longform_recap_report",
    "operator_checklist", "operator_approval", "approval_decision", "source_leakage_report",
    "originality_risk_report", "anti_ai_report", "platform_rule_report",
})


def _profile(
    name: str,
    *,
    required: Iterable[str],
    maximum: int,
    allowed: Iterable[str] = (),
    evidence_only: Iterable[str] = (),
    review_only: Iterable[str] = (),
) -> ContextProfile:
    return ContextProfile(
        name=name,
        allowed_asset_types=frozenset({*_COMMON, *allowed}),
        forbidden_asset_types=_RAW_TYPES,
        required_asset_types=frozenset(required),
        maximum_raw_source_ratio=0.0,
        maximum_token_budget=maximum,
        source_risk_threshold=1,
        generation_allowed_requirement=name not in {"review", "quality"},
        copyright_mode="abstract_or_project_owned_only",
        evidence_only_types=frozenset(evidence_only),
        review_only_types=frozenset(review_only),
        priority_rules=("required_first", "stage_fit", "narrative_function", "relevance", "lower_risk"),
    )


CONTEXT_PROFILES: dict[str, ContextProfile] = {
    "creative": _profile("creative", required=(), maximum=4200, allowed={"creative_brief", "source_policy"}),
    "worldbuilding": _profile("worldbuilding", required=("creative_brief",), maximum=5000, allowed={"creative_brief", "world_rule"}),
    "character": _profile("character", required=("creative_brief", "world_bible"), maximum=4800, allowed={"creative_brief"}),
    "outline": _profile("outline", required=("world_bible", "character_card"), maximum=6000, allowed={"creative_brief"}),
    "chapter_plan": _profile("chapter_plan", required=("outline_version",), maximum=5200),
    "draft": _profile(
        "draft",
        required=("chapter_plan",),
        maximum=6000,
        review_only={"review_report", "review_issue", "quality_report"},
        evidence_only={
            "operator_checklist", "operator_approval", "approval_decision", "source_leakage_report",
            "originality_risk_report", "anti_ai_report", "platform_rule_report",
            "quality_rubric", "quality_profile", "platform_profile", "context_profile",
        },
    ),
    "review": _profile("review", required=("draft_version",), maximum=5000, evidence_only={"source_policy"}),
    "revision": _profile("revision", required=("draft_version", "review_report"), maximum=5000),
    "canon_extraction": _profile("canon_extraction", required=("draft_version",), maximum=4200),
    "quality": _profile("quality", required=("draft_version",), maximum=5200),
    "longform_recap": _profile("longform_recap", required=("longform_recap_report",), maximum=6000),
    "ending": _profile("ending", required=("closure_plan", "theme_arc"), maximum=7000),
}


def resolve_context_profile(name: str) -> ContextProfile:
    normalized = name.strip().lower().replace("-", "_")
    aliases = {"prose": "draft", "chapter_outline": "chapter_plan", "recap": "longform_recap"}
    normalized = aliases.get(normalized, normalized)
    try:
        return CONTEXT_PROFILES[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown context profile: {name}") from exc


def select_context_candidates(
    *,
    project_id: str,
    profile: ContextProfile,
    candidates: Iterable[ContextCandidate],
    token_budget: int,
) -> ContextSelection:
    if not project_id.strip():
        raise ValueError("project_id is required")
    if token_budget <= 0 or token_budget > profile.maximum_token_budget:
        raise ValueError("token_budget exceeds context profile maximum")
    accepted: list[ContextCandidate] = []
    rejected: list[dict[str, str]] = []
    for candidate in candidates:
        reason = _rejection_reason(project_id, profile, candidate)
        if reason:
            rejected.append({"asset_version_id": candidate.asset_version_id, "reason": reason})
        else:
            accepted.append(candidate)
    accepted.sort(
        key=lambda item: (
            item.asset_type not in profile.required_asset_types,
            -item.relevance_score,
            item.source_risk,
            item.asset_version_id,
        )
    )
    selected: list[ContextCandidate] = []
    used = 0
    for candidate in accepted:
        if candidate.estimated_tokens < 0:
            rejected.append({"asset_version_id": candidate.asset_version_id, "reason": "invalid_token_estimate"})
            continue
        if used + candidate.estimated_tokens > token_budget:
            rejected.append({"asset_version_id": candidate.asset_version_id, "reason": "token_budget"})
            continue
        selected.append(candidate)
        used += candidate.estimated_tokens
    present = {item.asset_type for item in selected}
    missing = sorted(profile.required_asset_types - present)
    if missing:
        raise ValueError("required context asset types missing: " + ", ".join(missing))
    raw_tokens = sum(item.estimated_tokens for item in selected if item.raw_source)
    if used and raw_tokens / used > profile.maximum_raw_source_ratio:
        raise ValueError("maximum_raw_source_ratio exceeded")
    return ContextSelection(tuple(selected), tuple(rejected), used, token_budget)


def build_authority_context_bundle(
    *,
    project_id: str,
    stage: str,
    created_by_operation_id: str,
    context_profile_version: str,
    candidates: Iterable[ContextCandidate],
    token_budget: int,
    version_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical immutable ContextBundle content payload."""
    profile = resolve_context_profile(stage)
    selection = select_context_candidates(
        project_id=project_id,
        profile=profile,
        candidates=candidates,
        token_budget=token_budget,
    )
    refs = dict(version_refs or {})
    selected = [item.asset_version_id for item in selection.selected]
    rejected = [item["asset_version_id"] for item in selection.rejected]
    segments = [_context_segment(item, profile) for item in selection.selected]
    stage_view = {
        "stage": profile.name,
        "segments": [
            {
                "asset_version_id": item.asset_version_id,
                "asset_type": item.asset_type,
                "narrative_function": item.narrative_function,
                "safe_summary": item.safe_summary,
                "structured_facts": list(item.structured_facts),
                "allowed_use": item.allowed_use,
                "content_digest": item.content_digest,
                "source_policy_version": item.source_policy_version,
                "token_count": item.token_count,
                "compression_method": item.compression_method,
                "source_expression_included": item.source_expression_included,
            }
            for item in segments
        ],
        "rendered_safe_context": "\n\n".join(
            item.safe_summary
            for item in segments
            if item.safe_summary and item.allowed_use != "evidence_only"
        ),
        "token_count": selection.estimated_tokens,
    }
    digest_payload = {
        "manifest": [
            {"asset_version_id": item.asset_version_id, "content_digest": item.content_digest}
            for item in selection.selected
        ],
        "stage_context_view": stage_view,
    }
    actual_context_digest = "sha256:" + hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    policy_versions = sorted({item.policy_version for item in selection.selected if item.policy_version})
    invalidation_keys = sorted({key for item in selection.selected for key in item.invalidation_keys})
    return {
        "project_id": project_id,
        "stage": profile.name,
        "context_profile_version": context_profile_version,
        "chapter_plan_version": refs.get("chapter_plan_version", ""),
        "outline_version": refs.get("outline_version", ""),
        "volume_arc_version": refs.get("volume_arc_version", ""),
        "world_bible_version": refs.get("world_bible_version", ""),
        "character_state_versions": list(refs.get("character_state_versions", [])),
        "canon_snapshot_version": refs.get("canon_snapshot_version", ""),
        "timeline_snapshot_version": refs.get("timeline_snapshot_version", ""),
        "foreshadow_state_versions": list(refs.get("foreshadow_state_versions", [])),
        "reader_promise_versions": list(refs.get("reader_promise_versions", [])),
        "reward_ledger_version": refs.get("reward_ledger_version", ""),
        "style_policy_version": refs.get("style_policy_version", ""),
        "operator_checklist_version": refs.get("operator_checklist_version", ""),
        "knowledge_pack_versions": [item.asset_version_id for item in selection.selected if item.asset_type == "knowledge_pack"],
        "material_asset_versions": [item.asset_version_id for item in selection.selected if item.asset_type in {"material_asset", "material_card"}],
        "source_policy_versions": policy_versions,
        "selected_asset_versions": selected,
        "selected_asset_version_ids": selected,
        "rejected_asset_versions": list(selection.rejected),
        "context_manifest": {
            "selected_asset_version_ids": selected,
            "rejected_asset_versions": list(selection.rejected),
            "policy_versions": policy_versions,
        },
        "context_segments": stage_view["segments"],
        "stage_context_view": stage_view,
        "token_budget": selection.token_budget,
        "estimated_tokens": selection.estimated_tokens,
        "actual_context_digest": actual_context_digest,
        "context_digest": actual_context_digest,
        "source_isolation_result": {"passed": True, "raw_source_ratio": 0.0},
        "copyright_boundary": profile.copyright_mode,
        "invalidation_keys": invalidation_keys,
        "created_by_operation_id": created_by_operation_id,
        "profile_contract": {
            "allowed_asset_types": sorted(profile.allowed_asset_types),
            "forbidden_asset_types": sorted(profile.forbidden_asset_types),
            "required_asset_types": sorted(profile.required_asset_types),
            "maximum_raw_source_ratio": profile.maximum_raw_source_ratio,
            "maximum_token_budget": profile.maximum_token_budget,
            "source_risk_threshold": profile.source_risk_threshold,
            "generation_allowed_requirement": profile.generation_allowed_requirement,
            "copyright_mode": profile.copyright_mode,
            "evidence_only_types": sorted(profile.evidence_only_types),
            "review_only_types": sorted(profile.review_only_types),
            "priority_rules": list(profile.priority_rules),
            "compression_policy": profile.compression_policy,
        },
        "context_contract_version": "authority-context-bundle-v3",
    }


def _context_segment(candidate: ContextCandidate, profile: ContextProfile) -> ContextSegment:
    safe_summary = candidate.safe_summary.strip()
    facts = tuple(dict(item) for item in candidate.structured_facts)
    if not safe_summary and not facts:
        # Version identity alone is not usable model context.  The caller must provide
        # safe material, while project-owned planning assets may use a concise marker.
        safe_summary = f"[{candidate.asset_type}:{candidate.asset_version_id}]"
    allowed_use = "evidence_only" if candidate.asset_type in profile.evidence_only_types else (
        "structure_only" if candidate.source_use_mode == "structure_only" else candidate.allowed_use
    )
    return ContextSegment(
        asset_version_id=candidate.asset_version_id,
        asset_type=candidate.asset_type,
        narrative_function=candidate.narrative_function,
        safe_summary=safe_summary,
        structured_facts=facts,
        allowed_use=allowed_use,
        content_digest=candidate.content_digest,
        source_policy_version=candidate.policy_version,
        token_count=candidate.estimated_tokens,
        compression_method=(
            "structural_abstraction"
            if candidate.source_use_mode == "structure_only"
            else candidate.compression_method
        ),
        source_expression_included=False,
    )


def _rejection_reason(project_id: str, profile: ContextProfile, candidate: ContextCandidate) -> str:
    if candidate.project_id != project_id:
        return "cross_project"
    if candidate.qualification in BLOCKED_QUALIFICATIONS or candidate.qualification not in ELIGIBLE_QUALIFICATIONS:
        return f"qualification:{candidate.qualification}"
    if candidate.governance_status != "CLEAR":
        return f"governance:{candidate.governance_status}"
    if candidate.asset_type in profile.forbidden_asset_types or candidate.raw_source:
        return "raw_source_forbidden"
    if candidate.asset_type not in profile.allowed_asset_types:
        return "asset_type_not_allowed"
    if candidate.asset_type in profile.review_only_types and profile.name == "draft":
        return "review_only_type"
    if candidate.source_use_mode not in SOURCE_MODES:
        return "unknown_source_use_mode"
    if profile.generation_allowed_requirement and candidate.source_use_mode not in {
        "generation",
        "structure_only",
    }:
        return f"source_mode:{candidate.source_use_mode}"
    if candidate.source_risk > profile.source_risk_threshold:
        return "source_risk"
    return ""


__all__ = [
    "CONTEXT_PROFILES",
    "ContextCandidate",
    "ContextProfile",
    "ContextSegment",
    "ContextSelection",
    "build_authority_context_bundle",
    "resolve_context_profile",
    "select_context_candidates",
]
