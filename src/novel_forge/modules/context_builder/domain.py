"""Storage-free governed context selection and immutable bundle payloads.

The module is shared by compatibility services and PostgreSQL Authority
handlers.  It never discovers assets or persists results; callers must supply
project-scoped, versioned candidates and persist the returned payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any, Iterable

from novel_forge.modules.context_contracts import ContextCandidate


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
    physical_asset_type: str = ""


@dataclass(frozen=True, slots=True)
class ContextSelection:
    selected: tuple[ContextCandidate, ...]
    rejected: tuple[dict[str, str], ...]
    estimated_tokens: int
    token_budget: int


_RAW_TYPES = frozenset(
    {
        "source_document",
        "source_chunk",
        "source_deconstruction_observation",
        "source_reprocessing_plan",
        "cleaned_text",
        "parallel_pair",
    }
)
_COMMON = frozenset({
    "chapter_plan", "chapter_plan_version", "outline_version", "volume_arc", "world_bible",
    "character_card", "canon_snapshot", "story_state_snapshot",
    "style_policy", "knowledge_pack", "knowledge_card", "material_asset", "material_card",
    "quality_rubric", "quality_profile", "platform_profile", "context_profile",
    "theme_arc", "theme_beat", "closure_plan", "review_issue", "review_report",
    "draft_chapter", "draft_version", "quality_report", "longform_recap_report",
    "operator_checklist", "operator_approval", "approval_decision", "source_leakage_report",
    "originality_risk_report", "anti_ai_report", "platform_rule_report",
    "structural_quality_report", "commercial_quality_report",
    "source_originality_quality_report", "longform_quality_report",
    "platform_quality_report",
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
        maximum=16000,
        review_only={"review_report", "review_issue", "quality_report"},
        evidence_only={
            "operator_checklist", "operator_approval", "approval_decision", "source_leakage_report",
            "originality_risk_report", "anti_ai_report", "platform_rule_report",
            "quality_rubric", "quality_profile", "platform_profile", "context_profile",
            "structural_quality_report", "commercial_quality_report",
            "source_originality_quality_report", "longform_quality_report",
            "platform_quality_report",
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
    required_asset_types: Iterable[str] = (),
    book_id: str = "",
    narrative_position: dict[str, Any] | None = None,
    target_capability_id: str = "",
    capability_pack_snapshot_ref: str = "",
    authority_state_boundary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical immutable ContextBundle content payload."""
    profile = resolve_context_profile(stage)
    required = frozenset(str(item) for item in required_asset_types if str(item))
    unsupported = required - profile.allowed_asset_types
    if unsupported:
        raise ValueError(
            "required context asset types are not allowed: "
            + ", ".join(sorted(unsupported))
        )
    if required:
        profile = replace(
            profile,
            required_asset_types=profile.required_asset_types | required,
        )
    selection = select_context_candidates(
        project_id=project_id,
        profile=profile,
        candidates=candidates,
        token_budget=token_budget,
    )
    refs = dict(version_refs or {})
    selected = [item.asset_version_id for item in selection.selected]
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
                "physical_asset_type": item.physical_asset_type or item.asset_type,
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
    normalized_position = _normalize_narrative_position(narrative_position)
    selected_inputs = [
        {
            "asset_version_id": item.asset_version_id,
            "asset_type": item.asset_type,
            "physical_asset_type": item.physical_asset_type or item.asset_type,
            "content_digest": item.content_digest,
            "inclusion_reason": _inclusion_reason(item, profile),
            "narrative_function": item.narrative_function,
            "relevance_score": item.relevance_score,
            "allowed_use": (
                "evidence_only"
                if item.asset_type in profile.evidence_only_types
                else item.allowed_use
            ),
        }
        for item in selection.selected
    ]
    normalized_boundary = {
        str(key): value
        for key, value in sorted(dict(authority_state_boundary or {}).items())
        if value not in (None, "", [], {})
    }
    replay_inputs = {
        "project_id": project_id,
        "book_id": book_id,
        "stage": profile.name,
        "context_profile_version": context_profile_version,
        "target_capability_id": target_capability_id,
        "capability_pack_snapshot_ref": capability_pack_snapshot_ref,
        "narrative_position": normalized_position,
        "authority_state_boundary": normalized_boundary,
        "selected_inputs": selected_inputs,
        "rejected_inputs": list(selection.rejected),
        "token_budget": selection.token_budget,
        "selection_policy": {
            "priority_rules": list(profile.priority_rules),
            "compression_policy": profile.compression_policy,
            "copyright_mode": profile.copyright_mode,
        },
    }
    replay_input_digest = "sha256:" + hashlib.sha256(
        json.dumps(replay_inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    context_manifest = {
        "type": "NarrativeContextManifest",
        "contract_version": "narrative-context-manifest-v1",
        "task": {
            "stage": profile.name,
            "target_capability_id": target_capability_id,
            "created_by_operation_id": created_by_operation_id,
        },
        "scope": {"project_id": project_id, "book_id": book_id},
        "narrative_position": normalized_position,
        "authority_state_boundary": normalized_boundary,
        "selected_inputs": selected_inputs,
        "selected_asset_version_ids": selected,
        "rejected_inputs": list(selection.rejected),
        "rejected_asset_versions": list(selection.rejected),
        "knowledge_usage": [
            {
                "asset_version_id": item.asset_version_id,
                "asset_type": item.asset_type,
                "narrative_function": item.narrative_function,
                "target_capability_id": target_capability_id,
                "capability_pack_snapshot_ref": capability_pack_snapshot_ref,
            }
            for item in selection.selected
            if item.asset_type in {"knowledge_pack", "knowledge_card"}
        ],
        "narrative_boundaries": _narrative_boundaries(segments),
        "token_budget": {
            "maximum": selection.token_budget,
            "estimated_used": selection.estimated_tokens,
            "remaining": selection.token_budget - selection.estimated_tokens,
        },
        "replay": {
            "algorithm": "authority-context-selection-v1",
            "input_digest": replay_input_digest,
            "output_context_digest": actual_context_digest,
        },
        "policy_versions": policy_versions,
    }
    return {
        "project_id": project_id,
        "book_id": book_id,
        "stage": profile.name,
        "context_profile_version": context_profile_version,
        "chapter_plan_version": refs.get("chapter_plan_version", ""),
        "outline_version": refs.get("outline_version", ""),
        "volume_arc_version": refs.get("volume_arc_version", ""),
        "world_bible_version": refs.get("world_bible_version", ""),
        "story_state_snapshot_version": refs.get(
            "story_state_snapshot_version",
            refs.get("story_state_snapshot_versions", ""),
        ),
        "canon_snapshot_version": refs.get("canon_snapshot_version", ""),
        "style_policy_version": refs.get("style_policy_version", ""),
        "operator_checklist_version": refs.get("operator_checklist_version", ""),
        "knowledge_pack_versions": [item.asset_version_id for item in selection.selected if item.asset_type == "knowledge_pack"],
        "material_asset_versions": [item.asset_version_id for item in selection.selected if item.asset_type in {"material_asset", "material_card"}],
        "source_policy_versions": policy_versions,
        "selected_asset_versions": selected,
        "selected_asset_version_ids": selected,
        "rejected_asset_versions": list(selection.rejected),
        "context_manifest": context_manifest,
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
        "context_contract_version": "authority-context-bundle-v5",
    }


def _normalize_narrative_position(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(value or {})
    normalized: dict[str, Any] = {}
    for key in ("book_id", "volume_id", "arc_id", "sequence_id"):
        text = str(raw.get(key) or "").strip()
        if text:
            normalized[key] = text
    for key in ("chapter", "sequence_ordinal"):
        item = raw.get(key)
        if item not in (None, ""):
            number = int(item)
            if number < 0 or (key == "chapter" and number == 0):
                raise ValueError(f"narrative position {key} is invalid")
            normalized[key] = number
    return normalized


def _inclusion_reason(candidate: ContextCandidate, profile: ContextProfile) -> str:
    if candidate.asset_type in profile.required_asset_types:
        return "REQUIRED_BY_CONTEXT_PROFILE"
    if candidate.narrative_function:
        return "NARRATIVE_FUNCTION_MATCH"
    if candidate.asset_type in {"knowledge_pack", "knowledge_card"}:
        return "CAPABILITY_KNOWLEDGE_SELECTION"
    return "TASK_RELEVANCE_RANK"


def _narrative_boundaries(
    segments: Iterable[ContextSegment],
) -> dict[str, list[dict[str, Any]]]:
    knowledge: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    state_constraints: list[dict[str, Any]] = []
    for segment in segments:
        for fact in segment.structured_facts:
            kind = str(fact.get("state_kind") or "")
            state = dict(fact.get("state") or {})
            base = {
                "source_asset_version_id": segment.asset_version_id,
                "state_kind": kind,
                "entity_key": str(fact.get("entity_key") or ""),
                "entity_version": int(fact.get("entity_version") or 0),
                "effective_from_chapter": int(
                    fact.get("effective_from_chapter") or 0
                ),
                "effective_to_chapter": int(
                    fact.get("effective_to_chapter") or 0
                ),
            }
            if kind in {"character_knowledge", "character_belief"}:
                knowledge.append({**base, "state": state})
            elif kind == "narrative_obligation":
                if str(state.get("status") or "").upper() not in {
                    "FULFILLED",
                    "CANCELLED",
                }:
                    obligations.append({**base, "state": state})
            elif kind in {
                "character_state",
                "character_arc",
                "relationship_state",
                "world_state",
                "faction_state",
                "location_state",
                "world_rule",
                "consequence_state",
                "conflict_state",
            }:
                state_constraints.append({**base, "state": state})
    def order(item: dict[str, Any]) -> tuple[str, str]:
        return (str(item["state_kind"]), str(item["entity_key"]))

    return {
        "character_knowledge_and_belief": sorted(knowledge, key=order),
        "unresolved_obligations": sorted(obligations, key=order),
        "current_state_constraints": sorted(state_constraints, key=order),
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
        physical_asset_type=candidate.physical_asset_type or candidate.asset_type,
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
