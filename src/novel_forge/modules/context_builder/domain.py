from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any, Iterable

from novel_forge.modules.context_contracts import ContextCandidate, ContextClass
from novel_forge.modules.context_builder.governance import (
    ContextBudgetLimits,
    ContextPolicyCompilation,
    ContextPolicySnapshot,
    EffectiveContextPolicy,
    PolicyIdentity,
    compile_effective_context_policy,
)


ELIGIBLE_QUALIFICATIONS = {"ELIGIBLE"}
BLOCKED_QUALIFICATIONS = {"REVOKED", "STALE", "QUARANTINED", "REQUIRES_APPROVAL"}
SOURCE_MODES = {
    "generation",
    "summary_only",
    "structure_only",
    "review_only",
    "eval_only",
}


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
    context_class: ContextClass
    source_expression_included: bool = False
    physical_asset_type: str = ""


@dataclass(frozen=True, slots=True)
class ContextSelection:
    selected: tuple[ContextCandidate, ...]
    rejected: tuple[dict[str, str], ...]
    estimated_tokens: int
    token_budget: int
    decisions: tuple[dict[str, Any], ...] = ()
    deduplications: tuple[dict[str, Any], ...] = ()
    truncations: tuple[dict[str, Any], ...] = ()
    token_accounting: dict[str, Any] = field(default_factory=dict)
    policy_compilation: dict[str, Any] = field(default_factory=dict)


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
_COMMON = frozenset(
    {
        "chapter_plan",
        "chapter_plan_version",
        "outline_version",
        "volume_arc",
        "world_bible",
        "character_cast",
        "character_card",
        "canon_snapshot",
        "story_state_snapshot",
        "style_policy",
        "knowledge_pack",
        "knowledge_card",
        "material_asset",
        "material_card",
        "reader_promise",
        "quality_rubric",
        "quality_profile",
        "platform_profile",
        "context_profile",
        "theme_arc",
        "theme_beat",
        "closure_plan",
        "review_issue",
        "review_report",
        "draft_chapter",
        "draft_version",
        "quality_report",
        "longform_recap_report",
        "operator_checklist",
        "operator_approval",
        "approval_decision",
        "source_leakage_report",
        "originality_risk_report",
        "anti_ai_report",
        "platform_rule_report",
        "structural_quality_report",
        "commercial_quality_report",
        "source_originality_quality_report",
        "longform_quality_report",
        "platform_quality_report",
        "chapter_execution_intent",
        "chapter_memo",
        "arc_plan",
        "arc_actual_state",
        "retrieval_result",
        "arc_checkpoint",
        "narrative_obligation_state",
        "character_timeline",
        "relationship_timeline",
        "chapter_episodic_summary",
        "scene_episodic_summary",
        "narrative_retrieval_document",
        "external_knowledge",
    }
)

_ALWAYS_PROTECTED_TYPES = frozenset(
    {
        "chapter_plan",
        "chapter_execution_intent",
        "chapter_memo",
        "retrieval_result",
        "canon_snapshot",
        "story_state_snapshot",
        "character_cast",
        "character_card",
        "reader_promise",
        "arc_actual_state",
        "narrative_obligation_state",
    }
)


def context_candidate_class(candidate: ContextCandidate) -> ContextClass:
    explicit = ContextClass(str(candidate.context_class or "").upper())
    if (
        candidate.asset_type in _ALWAYS_PROTECTED_TYPES
        or candidate.narrative_function
        in {"hard_world_rules", "critical_character_state", "critical_arc_state"}
    ):
        return ContextClass.PROTECTED
    return explicit


_NON_LOSSY_COMPRESSION_METHODS = frozenset(
    {"", "none", "full", "full_asset", "raw", "authority_projection"}
)


def _validate_context_class_invariants(candidate: ContextCandidate) -> None:
    context_class = context_candidate_class(candidate)
    method = candidate.compression_method.strip().lower()
    if context_class is ContextClass.PROTECTED:
        if candidate.compression_trace or method not in {
            *_NON_LOSSY_COMPRESSION_METHODS,
            # COMPATIBILITY: ``safe_summary`` is metadata on a versioned projection,
            # not permission to compress during Context assembly.
            "safe_summary",
        }:
            raise ValueError(
                "PROTECTED_CONTEXT_COMPRESSION_FORBIDDEN: protected context "
                "cannot be compressed during Context assembly"
            )
        return
    if context_class is ContextClass.EPHEMERAL:
        if candidate.memory_layer or candidate.retrieval_reasons:
            raise ValueError(
                "EPHEMERAL_CONTEXT_SEARCH_FORBIDDEN: ephemeral context cannot "
                "enter long-term Memory or Search"
            )
        return
    if (
        context_class is ContextClass.COMPRESSIBLE
        and method not in _NON_LOSSY_COMPRESSION_METHODS
    ):
        if candidate.truncation_strategy == "structured_elements-v1":
            return
        if not candidate.compression_trace or not candidate.provenance:
            raise ValueError(
                "COMPRESSIBLE_CONTEXT_PROVENANCE_REQUIRED: compressed context "
                "requires source provenance and a compression trace"
            )
        for entry in candidate.compression_trace:
            if (
                not str(entry.get("source_asset_version_id") or "")
                or not str(entry.get("method") or "")
                or not any(
                    str(entry.get(key) or "")
                    for key in (
                        "source_content_hash",
                        "source_projection_hash",
                        "content_fingerprint",
                    )
                )
            ):
                raise ValueError(
                    "COMPRESSIBLE_CONTEXT_PROVENANCE_REQUIRED: compression "
                    "trace must identify source AssetVersion, method, and digest"
                )


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
        priority_rules=(
            "required_first",
            "stage_fit",
            "narrative_function",
            "relevance",
            "lower_risk",
        ),
    )


CONTEXT_PROFILES: dict[str, ContextProfile] = {
    "creative": _profile(
        "creative",
        required=(),
        maximum=4200,
        allowed={"creative_brief", "source_policy"},
    ),
    "worldbuilding": _profile(
        "worldbuilding",
        required=("creative_brief",),
        maximum=5000,
        allowed={"creative_brief", "world_rule"},
    ),
    "character": _profile(
        "character",
        required=("creative_brief", "world_bible"),
        maximum=4800,
        allowed={"creative_brief"},
    ),
    "outline": _profile(
        "outline",
        required=("world_bible", "character_card"),
        maximum=6000,
        allowed={"creative_brief"},
    ),
    "chapter_plan": _profile(
        "chapter_plan", required=("outline_version",), maximum=5200
    ),
    "draft": _profile(
        "draft",
        required=("chapter_plan",),
        maximum=16000,
        review_only={"review_report", "review_issue", "quality_report"},
        evidence_only={
            "operator_checklist",
            "operator_approval",
            "approval_decision",
            "source_leakage_report",
            "originality_risk_report",
            "anti_ai_report",
            "platform_rule_report",
            "quality_rubric",
            "quality_profile",
            "platform_profile",
            "context_profile",
            "structural_quality_report",
            "commercial_quality_report",
            "source_originality_quality_report",
            "longform_quality_report",
            "platform_quality_report",
        },
    ),
    "review": _profile(
        "review",
        required=("draft_version",),
        maximum=5000,
        evidence_only={"source_policy"},
    ),
    "revision": _profile(
        "revision", required=("draft_version", "review_report"), maximum=5000
    ),
    "canon_extraction": _profile(
        "canon_extraction", required=("draft_version",), maximum=4200
    ),
    "quality": _profile("quality", required=("draft_version",), maximum=5200),
    "longform_recap": _profile(
        "longform_recap", required=("longform_recap_report",), maximum=6000
    ),
    "ending": _profile("ending", required=("closure_plan", "theme_arc"), maximum=7000),
}


def resolve_context_profile(name: str) -> ContextProfile:
    normalized = name.strip().lower().replace("-", "_")
    aliases = {
        "prose": "draft",
        "chapter_outline": "chapter_plan",
        "recap": "longform_recap",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return CONTEXT_PROFILES[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown context profile: {name}") from exc


def _policy_hash(payload: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _compile_profile_policy(
    profile: ContextProfile,
    *,
    token_budget: int,
    required_asset_types: Iterable[str] = (),
    stage: str = "",
) -> ContextPolicyCompilation:
    profile_payload = {
        "name": profile.name,
        "allowed_asset_types": sorted(profile.allowed_asset_types),
        "forbidden_asset_types": sorted(profile.forbidden_asset_types),
        "required_asset_types": sorted(profile.required_asset_types),
        "maximum_token_budget": profile.maximum_token_budget,
        "maximum_raw_source_ratio": profile.maximum_raw_source_ratio,
        "source_risk_threshold": profile.source_risk_threshold,
        "compression_policy": profile.compression_policy,
    }
    caller_required = frozenset(
        str(value).strip() for value in required_asset_types if str(value).strip()
    )
    snapshots: list[ContextPolicySnapshot] = [
        ContextPolicySnapshot(
            identity=PolicyIdentity(
                policy_id=f"context-profile:{profile.name}",
                version="context-profile-v1",
                content_hash=_policy_hash(profile_payload),
                snapshot_ref=f"context-profile:{profile.name}",
            ),
            allowed_logical_kinds=tuple(profile.allowed_asset_types),
            denied_logical_kinds=tuple(profile.forbidden_asset_types),
            required_logical_kinds=tuple(profile.required_asset_types),
            limits=ContextBudgetLimits(total=profile.maximum_token_budget),
            permitted_source_modes=(
                ("generation", "structure_only")
                if profile.generation_allowed_requirement
                else tuple(SOURCE_MODES)
            ),
            source_risk_threshold=profile.source_risk_threshold,
            maximum_raw_source_ratio=profile.maximum_raw_source_ratio,
        ),
        ContextPolicySnapshot(
            identity=PolicyIdentity(
                policy_id=f"caller-context-limit:{profile.name}",
                version="caller-context-limit-v1",
                content_hash=_policy_hash(
                    {
                        "token_budget": token_budget,
                        "required_asset_types": sorted(caller_required),
                    }
                ),
                snapshot_ref="command:context_token_budget",
            ),
            allowed_logical_kinds=tuple(profile.allowed_asset_types),
            required_logical_kinds=tuple(caller_required),
            limits=ContextBudgetLimits(total=token_budget),
            permitted_source_modes=(
                ("generation", "structure_only")
                if profile.generation_allowed_requirement
                else tuple(SOURCE_MODES)
            ),
            source_risk_threshold=profile.source_risk_threshold,
            maximum_raw_source_ratio=profile.maximum_raw_source_ratio,
        ),
    ]
    if stage:
        from novel_forge.modules.production_preparation.policies import STAGE_PROFILES

        normalized_stage = "recap" if stage == "longform_recap" else stage
        try:
            stage_profile = STAGE_PROFILES[normalized_stage]
        except KeyError as exc:
            raise ValueError(
                "CONTEXT_POLICY_UNRESOLVED: unknown ProductionStageProfile " + stage
            ) from exc
        stage_payload = {
            "stage": stage_profile.stage,
            "allowed_asset_types": list(stage_profile.allowed_asset_types),
            "forbidden_asset_types": list(stage_profile.forbidden_asset_types),
            "declared_required_asset_types": list(stage_profile.required_asset_types),
            "maximum_raw_source_ratio": stage_profile.maximum_raw_source_ratio,
            "compression_policy": stage_profile.compression_policy,
            "source_expression_policy": stage_profile.source_expression_policy,
        }
        runtime_context_types = (
            (
                "chapter_execution_intent",
                "chapter_memo",
                "retrieval_result",
            )
            if normalized_stage == "draft"
            else ()
        )
        snapshots.append(
            ContextPolicySnapshot(
                identity=PolicyIdentity(
                    policy_id=f"production-stage-profile:{stage_profile.stage}",
                    version="production-stage-profile-v1",
                    content_hash=_policy_hash(stage_payload),
                    snapshot_ref=f"production-stage-profile:{stage_profile.stage}",
                ),
                allowed_logical_kinds=(
                    *stage_profile.allowed_asset_types,
                    *runtime_context_types,
                ),
                denied_logical_kinds=stage_profile.forbidden_asset_types,
                required_logical_kinds=tuple(caller_required),
                limits=ContextBudgetLimits(total=profile.maximum_token_budget),
                permitted_source_modes=("generation", "structure_only"),
                source_risk_threshold=profile.source_risk_threshold,
                maximum_raw_source_ratio=stage_profile.maximum_raw_source_ratio,
            )
        )
    return compile_effective_context_policy(snapshots)


_DIAGNOSTIC_CONTEXT_TYPES = frozenset(
    {
        "build_log",
        "ci_output",
        "stack_trace",
        "raw_exception",
        "provider_debug_payload",
        "provider_diagnostic",
        "retry_chatter",
        "tool_debug_output",
        "sql_debug_log",
        "runtime_debug",
        "rejected_generation",
    }
)


def _eligibility_reason(
    project_id: str,
    profile: ContextProfile,
    policy: EffectiveContextPolicy,
    candidate: ContextCandidate,
    *,
    authority_state_boundary: dict[str, Any],
) -> str:
    logical_kind = candidate.logical_context_kind
    physical_type = candidate.physical_asset_type or candidate.asset_type
    if candidate.project_id != project_id:
        return "WRONG_PROJECT"
    if (
        logical_kind in _DIAGNOSTIC_CONTEXT_TYPES
        or physical_type in _DIAGNOSTIC_CONTEXT_TYPES
    ):
        return "DIAGNOSTIC_CONTEXT_FORBIDDEN"
    if (
        candidate.qualification in BLOCKED_QUALIFICATIONS
        or candidate.qualification not in ELIGIBLE_QUALIFICATIONS
    ):
        return f"QUALIFICATION_{candidate.qualification}"
    if candidate.governance_status != "CLEAR":
        return f"GOVERNANCE_{candidate.governance_status}"
    if candidate.authority_freshness == "INVALIDATED":
        return "INVALIDATED_REPRESENTATION"
    if candidate.authority_freshness not in {"CURRENT", "VALID_AS_OF"}:
        return "STALE_REPRESENTATION"
    if candidate.representation_status == "INVALIDATED":
        return "INVALIDATED_REPRESENTATION"
    if candidate.representation_status not in {"ACTIVE", "CURRENT", "VALID_AS_OF"}:
        return "SUPERSEDED_REPRESENTATION"
    if (
        candidate.active_read_generation_id
        and candidate.read_generation_id != candidate.active_read_generation_id
    ):
        return "WRONG_READ_GENERATION"
    if candidate.raw_source or logical_kind in profile.forbidden_asset_types:
        return "RAW_SOURCE_FORBIDDEN"
    if logical_kind in policy.denied_logical_kinds:
        return "LOGICAL_CONTEXT_KIND_DENIED"
    if physical_type in policy.denied_physical_types:
        return "PHYSICAL_ASSET_TYPE_DENIED"
    if logical_kind not in policy.allowed_logical_kinds:
        return "LOGICAL_CONTEXT_KIND_NOT_ALLOWED"
    if (
        policy.allowed_physical_types
        and physical_type not in policy.allowed_physical_types
    ):
        return "PHYSICAL_ASSET_TYPE_NOT_ALLOWED"
    if candidate.asset_type in profile.review_only_types and profile.name == "draft":
        return "REVIEW_ONLY_TYPE"
    if candidate.source_use_mode not in SOURCE_MODES:
        return "UNKNOWN_SOURCE_USE_MODE"
    if candidate.source_use_mode not in policy.permitted_source_modes:
        return f"SOURCE_MODE_{candidate.source_use_mode}"
    if candidate.source_risk > policy.source_risk_threshold:
        return "SOURCE_RISK"
    if not candidate.provenance:
        return "MISSING_PROVENANCE"
    if candidate.accepted_boundary and authority_state_boundary:
        if dict(candidate.accepted_boundary) != authority_state_boundary:
            return "WRONG_ACCEPTED_BOUNDARY"
    return ""


def select_context_candidates(
    *,
    project_id: str,
    profile: ContextProfile,
    candidates: Iterable[ContextCandidate],
    token_budget: int,
    effective_policy: EffectiveContextPolicy | None = None,
    authority_state_boundary: dict[str, Any] | None = None,
) -> ContextSelection:
    if not project_id.strip():
        raise ValueError("project_id is required")
    if token_budget <= 0 or token_budget > profile.maximum_token_budget:
        raise ValueError("token_budget exceeds context profile maximum")
    compilation = (
        None
        if effective_policy is not None
        else _compile_profile_policy(profile, token_budget=token_budget)
    )
    policy = effective_policy or compilation.effective_policy
    if token_budget > policy.limits.total:
        raise ValueError("token_budget exceeds effective Context policy")
    accepted: list[ContextCandidate] = []
    rejected: list[dict[str, str]] = []
    decisions: list[dict[str, Any]] = []
    for candidate in candidates:
        _validate_context_class_invariants(candidate)
        reason = _eligibility_reason(
            project_id,
            profile,
            policy,
            candidate,
            authority_state_boundary=authority_state_boundary or {},
        )
        if reason:
            if context_candidate_class(candidate) is ContextClass.PROTECTED:
                raise ValueError(
                    f"protected context is unavailable: {candidate.asset_version_id}:{reason}"
                )
            rejected.append(
                {"asset_version_id": candidate.asset_version_id, "reason": reason}
            )
            decisions.append(
                {
                    "asset_version_id": candidate.asset_version_id,
                    "decision": "DROPPED",
                    "reason": reason,
                }
            )
        else:
            accepted.append(candidate)
    class_priority = {
        ContextClass.PROTECTED: 0,
        ContextClass.COMPRESSIBLE: 1,
        ContextClass.RETRIEVABLE: 2,
        ContextClass.EPHEMERAL: 3,
    }
    required_kinds = set(policy.required_logical_kinds)

    def ordering(item: ContextCandidate) -> tuple[Any, ...]:
        required = item.required or item.logical_context_kind in required_kinds
        return (
            not required,
            context_candidate_class(item) is not ContextClass.PROTECTED,
            class_priority[context_candidate_class(item)],
            -item.relevance_score,
            item.source_risk,
            item.source_revision,
            item.asset_version_id,
        )

    accepted.sort(key=ordering)
    deduplicated: list[ContextCandidate] = []
    dedupe_winners: dict[tuple[str, str], ContextCandidate] = {}
    deduplications: list[dict[str, Any]] = []
    for candidate in accepted:
        basis = _dedupe_basis(candidate)
        if basis is None:
            deduplicated.append(candidate)
            continue
        previous = dedupe_winners.get(basis)
        if previous is None:
            dedupe_winners[basis] = candidate
            deduplicated.append(candidate)
            continue
        winner = min((previous, candidate), key=ordering)
        loser = candidate if winner is previous else previous
        if winner is candidate:
            deduplicated.remove(previous)
            deduplicated.append(candidate)
            dedupe_winners[basis] = candidate
        receipt = {
            "asset_version_id": loser.asset_version_id,
            "decision": "DROPPED",
            "reason": "DUPLICATE_REPRESENTATION",
            "winner_asset_version_id": winner.asset_version_id,
            "equivalence_basis": basis[0],
            "equivalence_identity": basis[1],
        }
        decisions.append(receipt)
        deduplications.append(receipt)
        rejected.append(
            {
                "asset_version_id": loser.asset_version_id,
                "reason": "DUPLICATE_REPRESENTATION",
            }
        )
    accepted = sorted(deduplicated, key=ordering)
    selected: list[ContextCandidate] = []
    usage: dict[str, dict[str, int]] = {
        "sections": {},
        "buckets": {},
        "classes": {},
    }
    used = 0
    truncations: list[dict[str, Any]] = []
    for candidate in accepted:
        if candidate.estimated_tokens <= 0:
            if context_candidate_class(candidate) is ContextClass.PROTECTED:
                raise ValueError(
                    "PROTECTED_CONTEXT_TOKEN_ESTIMATE_INVALID: protected context "
                    "cannot be omitted because its token estimate is invalid"
                )
            rejected.append(
                {
                    "asset_version_id": candidate.asset_version_id,
                    "reason": "INVALID_TOKEN_ESTIMATE",
                }
            )
            decisions.append(
                {
                    "asset_version_id": candidate.asset_version_id,
                    "decision": "DROPPED",
                    "reason": "INVALID_TOKEN_ESTIMATE",
                }
            )
            continue
        required = (
            candidate.required or candidate.logical_context_kind in required_kinds
        )
        available, budget_reason = _available_budget(
            candidate,
            policy=policy,
            total_limit=token_budget,
            used=used,
            usage=usage,
        )
        selected_candidate = candidate
        decision = "SELECTED"
        if candidate.estimated_tokens > available:
            if required or context_candidate_class(candidate) is ContextClass.PROTECTED:
                code = (
                    "PROTECTED_CONTEXT_BUDGET_EXCEEDED"
                    if context_candidate_class(candidate) is ContextClass.PROTECTED
                    else "CONTEXT_REQUIRED_BUDGET_UNSATISFIABLE"
                )
                raise ValueError(
                    f"{code}: {candidate.asset_version_id} exceeds {budget_reason}"
                )
            selected_candidate, receipt = _truncate_candidate(
                candidate,
                maximum_tokens=available,
                policy=policy,
            )
            if selected_candidate is not None and receipt is not None:
                truncations.append(receipt)
                decision = "TRUNCATED_THEN_SELECTED"
            else:
                rejected.append(
                    {
                        "asset_version_id": candidate.asset_version_id,
                        "reason": budget_reason,
                    }
                )
                decisions.append(
                    {
                        "asset_version_id": candidate.asset_version_id,
                        "decision": "DROPPED",
                        "reason": budget_reason,
                    }
                )
                continue
        if selected_candidate is None:
            raise AssertionError("selected Context candidate is unexpectedly absent")
        selected.append(selected_candidate)
        _consume_budget(selected_candidate, usage)
        used += selected_candidate.estimated_tokens
        decisions.append(
            {
                "asset_version_id": selected_candidate.asset_version_id,
                "decision": decision,
                "reason": (
                    "STRUCTURED_TRUNCATION"
                    if decision == "TRUNCATED_THEN_SELECTED"
                    else "ELIGIBLE_AND_BUDGETED"
                ),
            }
        )
    present = {item.logical_context_kind for item in selected}
    missing = sorted(required_kinds - present)
    if missing:
        raise ValueError("required context asset types missing: " + ", ".join(missing))
    raw_tokens = sum(item.estimated_tokens for item in selected if item.raw_source)
    if used and raw_tokens / used > policy.maximum_raw_source_ratio:
        raise ValueError("maximum_raw_source_ratio exceeded")
    required_tokens = sum(
        item.estimated_tokens
        for item in selected
        if item.required or item.logical_context_kind in required_kinds
    )
    accounting = {
        "accounting_method": "declared-candidate-estimate-v1",
        "precision": "ESTIMATE_ONLY",
        "total_candidate_tokens": sum(
            max(0, item.estimated_tokens) for item in accepted
        ),
        "accepted_tokens": used,
        "tokens_by_section": dict(sorted(usage["sections"].items())),
        "tokens_by_bucket": dict(sorted(usage["buckets"].items())),
        "tokens_by_class": dict(sorted(usage["classes"].items())),
        "required_tokens": required_tokens,
        "required_reservation": max(
            required_tokens, policy.limits.required_reservation
        ),
        "total_limit": token_budget,
    }
    return ContextSelection(
        tuple(selected),
        tuple(rejected),
        used,
        token_budget,
        tuple(sorted(decisions, key=lambda item: str(item["asset_version_id"]))),
        tuple(deduplications),
        tuple(truncations),
        accounting,
        dict(compilation.receipt) if compilation is not None else {},
    )


def _dedupe_basis(candidate: ContextCandidate) -> tuple[str, str] | None:
    if candidate.semantic_representation_identity:
        return ("SEMANTIC_REPRESENTATION", candidate.semantic_representation_identity)
    if candidate.logical_narrative_identity:
        return ("LOGICAL_NARRATIVE", candidate.logical_narrative_identity)
    if candidate.source_identity != candidate.asset_version_id:
        return ("SOURCE_IDENTITY", candidate.source_identity)
    return ("PHYSICAL_IDENTITY", candidate.asset_version_id)


def _dimension_limit(limits: dict[str, int] | Any, key: str, total_limit: int) -> int:
    return int(limits.get(key, total_limit))


def _available_budget(
    candidate: ContextCandidate,
    *,
    policy: EffectiveContextPolicy,
    total_limit: int,
    used: int,
    usage: dict[str, dict[str, int]],
) -> tuple[int, str]:
    context_class = context_candidate_class(candidate).value
    remaining = {
        "TOTAL_CONTEXT_LIMIT": total_limit - used,
        "SECTION_LIMIT": _dimension_limit(
            dict(policy.limits.sections), candidate.section, total_limit
        )
        - usage["sections"].get(candidate.section, 0),
        "BUCKET_LIMIT": _dimension_limit(
            dict(policy.limits.buckets), candidate.bucket, total_limit
        )
        - usage["buckets"].get(candidate.bucket, 0),
        "CLASS_LIMIT": _dimension_limit(
            dict(policy.limits.classes), context_class, total_limit
        )
        - usage["classes"].get(context_class, 0),
    }
    reason, amount = min(remaining.items(), key=lambda item: item[1])
    return max(0, amount), reason


def _consume_budget(
    candidate: ContextCandidate, usage: dict[str, dict[str, int]]
) -> None:
    dimensions = {
        "sections": candidate.section,
        "buckets": candidate.bucket,
        "classes": context_candidate_class(candidate).value,
    }
    for dimension, key in dimensions.items():
        usage[dimension][key] = (
            usage[dimension].get(key, 0) + candidate.estimated_tokens
        )


def _truncate_candidate(
    candidate: ContextCandidate,
    *,
    maximum_tokens: int,
    policy: EffectiveContextPolicy,
) -> tuple[ContextCandidate | None, dict[str, Any] | None]:
    strategy = candidate.truncation_strategy
    if (
        maximum_tokens <= 0
        or strategy != "structured_elements-v1"
        or strategy not in policy.permitted_truncation_strategies
        or context_candidate_class(candidate) is ContextClass.PROTECTED
        or candidate.required
        or not candidate.structured_facts
    ):
        return None, None
    facts = tuple(dict(item) for item in candidate.structured_facts)
    keep = min(
        len(facts),
        max(1, (len(facts) * maximum_tokens) // candidate.estimated_tokens),
    )
    if keep >= len(facts):
        return None, None
    kept = facts[:keep]
    after_tokens = max(
        1, min(maximum_tokens, (candidate.estimated_tokens * keep) // len(facts))
    )
    before_payload = {
        "safe_summary": candidate.safe_summary,
        "structured_facts": list(facts),
    }
    after_payload = {"safe_summary": "", "structured_facts": list(kept)}
    before_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(before_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    after_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(after_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    updated = replace(
        candidate,
        estimated_tokens=after_tokens,
        safe_summary="",
        structured_facts=kept,
        content_digest=after_hash,
        compression_method=strategy,
        compression_trace=(
            *candidate.compression_trace,
            {
                "source_asset_version_id": candidate.asset_version_id,
                "source_content_hash": candidate.content_digest,
                "method": strategy,
                "result_content_hash": after_hash,
            },
        ),
    )
    return updated, {
        "asset_version_id": candidate.asset_version_id,
        "source_identity": candidate.source_identity,
        "source_revision": candidate.source_revision,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "strategy": strategy,
        "strategy_version": candidate.truncation_version or "v1",
        "before_token_count": candidate.estimated_tokens,
        "after_token_count": after_tokens,
        "removed_element_count": len(facts) - keep,
        "decision_reason": "HIERARCHICAL_BUDGET",
        "provenance": dict(candidate.provenance or {}),
    }


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
    accessible_knowledge_fact_ids: Iterable[str] = (),
    required_long_distance_fact_ids: Iterable[str] = (),
) -> dict[str, Any]:
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
    compilation = _compile_profile_policy(
        profile,
        token_budget=token_budget,
        required_asset_types=required,
        stage=profile.name,
    )
    selection = select_context_candidates(
        project_id=project_id,
        profile=profile,
        candidates=candidates,
        token_budget=token_budget,
        effective_policy=compilation.effective_policy,
        authority_state_boundary=dict(authority_state_boundary or {}),
    )
    selection = replace(selection, policy_compilation=dict(compilation.receipt))
    refs = dict(version_refs or {})
    selected = [item.asset_version_id for item in selection.selected]
    segments = [_context_segment(item, profile) for item in selection.selected]
    correctness = _context_correctness_receipt(
        profile=profile,
        selection=selection,
        segments=segments,
        narrative_position=_normalize_narrative_position(narrative_position),
        accessible_knowledge_fact_ids=accessible_knowledge_fact_ids,
        required_long_distance_fact_ids=required_long_distance_fact_ids,
    )
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
                "context_class": item.context_class.value,
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
            {
                "asset_version_id": item.asset_version_id,
                "content_digest": item.content_digest,
            }
            for item in selection.selected
        ],
        "stage_context_view": stage_view,
        "context_correctness": correctness,
    }
    actual_context_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    policy_versions = sorted(
        {item.policy_version for item in selection.selected if item.policy_version}
    )
    invalidation_keys = sorted(
        {key for item in selection.selected for key in item.invalidation_keys}
    )
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
            "context_class": context_candidate_class(item).value,
            "memory_layer": item.memory_layer,
            "retrieval_reasons": list(item.retrieval_reasons),
            "retrieval_scores": dict(item.retrieval_scores or {}),
            "provenance": dict(item.provenance or {}),
            "compression_trace": [dict(entry) for entry in item.compression_trace],
            "logical_context_kind": item.logical_context_kind,
            "source_identity": item.source_identity,
            "source_revision": item.source_revision,
            "logical_narrative_identity": item.logical_narrative_identity,
            "semantic_representation_identity": (item.semantic_representation_identity),
            "accepted_boundary": dict(item.accepted_boundary or {}),
            "section": item.section,
            "bucket": item.bucket,
            "required": (
                item.required
                or item.logical_context_kind
                in compilation.effective_policy.required_logical_kinds
            ),
            "representation_status": item.representation_status,
            "read_generation_id": item.read_generation_id,
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
    replay_input_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(replay_inputs, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    context_manifest = {
        "type": "NarrativeContextManifest",
        "contract_version": "narrative-context-manifest-v4",
        "task": {
            "stage": profile.name,
            "target_capability_id": target_capability_id,
            "created_by_operation_id": created_by_operation_id,
        },
        "scope": {"project_id": project_id, "book_id": book_id},
        "narrative_position": normalized_position,
        "authority_state_boundary": normalized_boundary,
        "accepted_boundary": normalized_boundary,
        "selected_inputs": selected_inputs,
        "selected_asset_version_ids": selected,
        "rejected_inputs": list(selection.rejected),
        "rejected_asset_versions": list(selection.rejected),
        "candidate_decisions": [dict(item) for item in selection.decisions],
        "deduplication_decisions": [dict(item) for item in selection.deduplications],
        "truncation_decisions": [dict(item) for item in selection.truncations],
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
        "protected_context": [
            item for item in selected_inputs if item["context_class"] == "PROTECTED"
        ],
        "compressible_context": [
            item for item in selected_inputs if item["context_class"] == "COMPRESSIBLE"
        ],
        "retrievable_context": [
            item for item in selected_inputs if item["context_class"] == "RETRIEVABLE"
        ],
        "ephemeral_context": [
            {
                **item,
                "attempt_evidence_policy": "FROZEN_IF_SENT_NOT_SEARCH_INDEXED",
            }
            for item in selected_inputs
            if item["context_class"] == "EPHEMERAL"
        ],
        "retrieval_trace": [
            {
                "asset_version_id": item["asset_version_id"],
                "memory_layer": item["memory_layer"],
                "reasons": item["retrieval_reasons"],
                "scores": item["retrieval_scores"],
                "provenance": item["provenance"],
            }
            for item in selected_inputs
            if item["context_class"] in {"RETRIEVABLE", "COMPRESSIBLE"}
        ],
        "compression_trace": [
            {
                "asset_version_id": item["asset_version_id"],
                "trace": item["compression_trace"],
            }
            for item in selected_inputs
            if item["compression_trace"]
        ],
        "token_budget": {
            "maximum": selection.token_budget,
            "estimated_used": selection.estimated_tokens,
            "remaining": selection.token_budget - selection.estimated_tokens,
            "protected": sum(
                candidate.estimated_tokens
                for candidate in selection.selected
                if context_candidate_class(candidate) is ContextClass.PROTECTED
            ),
            "compressible": sum(
                candidate.estimated_tokens
                for candidate in selection.selected
                if context_candidate_class(candidate) is ContextClass.COMPRESSIBLE
            ),
            "retrievable": sum(
                candidate.estimated_tokens
                for candidate in selection.selected
                if context_candidate_class(candidate) is ContextClass.RETRIEVABLE
            ),
            "ephemeral": sum(
                candidate.estimated_tokens
                for candidate in selection.selected
                if context_candidate_class(candidate) is ContextClass.EPHEMERAL
            ),
            "sections": dict(selection.token_accounting.get("tokens_by_section") or {}),
            "buckets": dict(selection.token_accounting.get("tokens_by_bucket") or {}),
            "classes": dict(selection.token_accounting.get("tokens_by_class") or {}),
            "required_reservation": int(
                selection.token_accounting.get("required_reservation") or 0
            ),
        },
        "effective_policy": {
            **compilation.effective_policy.to_dict(),
            "input_policy_identities": [
                dict(item["identity"]) for item in compilation.receipt["input_policies"]
            ],
            "compiler_receipt_hash": compilation.receipt["receipt_hash"],
        },
        "token_accounting_contract": {
            "method": "declared-candidate-estimate-v1",
            "version": "v1",
            "precision": "ESTIMATE_ONLY",
            "provider_admission_eligible": False,
        },
        "metrics": {
            **selection.token_accounting,
            "candidate_count": len(selection.decisions),
            "accepted_count": len(selection.selected),
            "dropped_count": sum(
                item["decision"] == "DROPPED" for item in selection.decisions
            ),
            "truncated_count": len(selection.truncations),
            "decision_count_by_reason": {
                reason: sum(item["reason"] == reason for item in selection.decisions)
                for reason in sorted(
                    {str(item["reason"]) for item in selection.decisions}
                )
            },
        },
        "replay": {
            "algorithm": "authority-context-selection-v3-governed",
            "input_digest": replay_input_digest,
            "output_context_digest": actual_context_digest,
        },
        "policy_versions": policy_versions,
        "context_correctness": correctness,
    }
    context_manifest["context_fingerprint"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(context_manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
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
        "knowledge_pack_versions": [
            item.asset_version_id
            for item in selection.selected
            if item.asset_type == "knowledge_pack"
        ],
        "material_asset_versions": [
            item.asset_version_id
            for item in selection.selected
            if item.asset_type in {"material_asset", "material_card"}
        ],
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
        "context_correctness": correctness,
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
        "context_contract_version": "authority-context-bundle-v8",
    }


_CONTEXT_CORRECTNESS_CHECKS = (
    "NO_FUTURE_FACT",
    "NO_HIDDEN_KNOWLEDGE_LEAK",
    "NO_STALE_VERSION",
    "NO_DUPLICATE_SEMANTIC_REPRESENTATION",
    "NO_IRRELEVANT_FULL_ASSET",
    "REQUIRED_LONG_DISTANCE_FACT_PRESENT",
)


def _context_correctness_receipt(
    *,
    profile: ContextProfile,
    selection: ContextSelection,
    segments: list[ContextSegment],
    narrative_position: dict[str, Any],
    accessible_knowledge_fact_ids: Iterable[str],
    required_long_distance_fact_ids: Iterable[str],
) -> dict[str, Any]:
    chapter = int(narrative_position.get("chapter") or 0)
    accessible = {
        str(item) for item in accessible_knowledge_fact_ids if str(item).strip()
    }
    required_long_distance = {
        str(item) for item in required_long_distance_fact_ids if str(item).strip()
    }
    facts = [
        (segment, dict(fact))
        for segment in segments
        for fact in segment.structured_facts
        if isinstance(fact, dict)
    ]
    future = [
        _fact_identity(fact)
        for _, fact in facts
        if chapter > 0 and int(fact.get("effective_from_chapter") or 0) > chapter
    ]
    hidden: list[str] = []
    for _, fact in facts:
        state = dict(fact.get("state") or {})
        state_kind = str(fact.get("state_kind") or "")
        visibility = str(
            fact.get("visibility")
            or fact.get("knowledge_access")
            or state.get("visibility")
            or state.get("knowledge_access")
            or ""
        ).upper()
        epistemic = state_kind in {
            "character_knowledge",
            "character_belief",
        }
        hidden_truth = state_kind in {
            "canon_fact",
            "story_truth",
            "",
        } and visibility in {"HIDDEN", "RESTRICTED", "NOT_ACCESSIBLE"}
        identity = _epistemic_fact_identity(fact)
        if (epistemic or hidden_truth) and identity and identity not in accessible:
            hidden.append(_fact_identity(fact))
    stale = [
        item.asset_version_id
        for item in selection.selected
        if item.authority_freshness != "CURRENT"
        or item.qualification != "ELIGIBLE"
        or item.governance_status != "CLEAR"
    ]
    semantic_sources: dict[str, set[str]] = {}
    for segment, fact in facts:
        semantic_identity = str(
            fact.get("semantic_identity")
            or fact.get("entity_key")
            or _epistemic_fact_identity(fact)
            or ""
        )
        if not semantic_identity:
            # INVARIANT: profile and policy metadata are structured facts but do not
            # represent Authority state and therefore cannot be semantic
            # duplicates of one another.
            continue
        key = json.dumps(
            {
                "semantic_identity": semantic_identity,
                "state_kind": fact.get("state_kind"),
                "effective_from_chapter": fact.get("effective_from_chapter"),
                "effective_to_chapter": fact.get("effective_to_chapter"),
                "state": fact.get("state"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        semantic_sources.setdefault(key, set()).add(segment.asset_version_id)
    duplicates = [
        sorted(sources) for sources in semantic_sources.values() if len(sources) > 1
    ]
    irrelevant_full = [
        item.asset_version_id
        for item in selection.selected
        if (
            not item.semantic_projection
            or item.compression_method in {"full", "full_asset", "raw"}
        )
        and item.asset_type not in profile.required_asset_types
    ]
    observed_long_distance = {
        _epistemic_fact_identity(fact) or _fact_identity(fact)
        for _, fact in facts
        if chapter > 0
        and int(fact.get("source_chapter") or chapter) > 0
        and chapter - int(fact.get("source_chapter") or chapter) >= 20
    }
    missing_long_distance = sorted(required_long_distance - observed_long_distance)
    evidence = {
        "NO_FUTURE_FACT": sorted(set(future)),
        "NO_HIDDEN_KNOWLEDGE_LEAK": sorted(set(hidden)),
        "NO_STALE_VERSION": sorted(set(stale)),
        "NO_DUPLICATE_SEMANTIC_REPRESENTATION": duplicates,
        "NO_IRRELEVANT_FULL_ASSET": sorted(set(irrelevant_full)),
        "REQUIRED_LONG_DISTANCE_FACT_PRESENT": missing_long_distance,
    }
    checks = {
        name: {
            "status": (
                "NOT_APPLICABLE"
                if name == "REQUIRED_LONG_DISTANCE_FACT_PRESENT"
                and not required_long_distance
                else "PASS"
                if not evidence[name]
                else "FAIL"
            ),
            "violations": evidence[name],
        }
        for name in _CONTEXT_CORRECTNESS_CHECKS
    }
    failed = [name for name, result in checks.items() if result["status"] == "FAIL"]
    if failed:
        raise ValueError("CONTEXT_CORRECTNESS_BLOCKED: " + ", ".join(failed))
    body = {
        "type": "ContextCorrectnessReceipt",
        "contract_version": "context-correctness-receipt-v1",
        "overall_status": "PASS",
        "checks": checks,
        "selected_asset_version_ids": [
            item.asset_version_id for item in selection.selected
        ],
        "narrative_position": narrative_position,
    }
    return {
        **body,
        "receipt_hash": "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _epistemic_fact_identity(fact: dict[str, Any]) -> str:
    state = dict(fact.get("state") or {})
    direct = str(
        fact.get("fact_id")
        or fact.get("proposition_id")
        or state.get("fact_id")
        or state.get("proposition_id")
        or ""
    )
    if direct:
        return direct
    components = {
        key: value
        for component in str(fact.get("entity_key") or "").split("|")
        if "=" in component
        for key, value in (component.split("=", 1),)
    }
    return str(components.get("fact_id") or components.get("proposition_id") or "")


def _fact_identity(fact: dict[str, Any]) -> str:
    return str(
        fact.get("entity_key")
        or _epistemic_fact_identity(fact)
        or fact.get("fact_id")
        or "UNIDENTIFIED_FACT"
    )


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
    reader_knowledge: list[dict[str, Any]] = []
    disclosures: list[dict[str, Any]] = []
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
                "effective_from_chapter": int(fact.get("effective_from_chapter") or 0),
                "effective_to_chapter": int(fact.get("effective_to_chapter") or 0),
            }
            if kind in {"character_knowledge", "character_belief"}:
                knowledge.append({**base, "state": state})
            elif kind == "reader_knowledge":
                reader_knowledge.append({**base, "state": state})
            elif kind == "disclosure_event":
                disclosures.append({**base, "state": state})
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
        "reader_knowledge": sorted(reader_knowledge, key=order),
        "disclosure_events": sorted(disclosures, key=order),
        "unresolved_obligations": sorted(obligations, key=order),
        "current_state_constraints": sorted(state_constraints, key=order),
    }


def _context_segment(
    candidate: ContextCandidate, profile: ContextProfile
) -> ContextSegment:
    safe_summary = candidate.safe_summary.strip()
    facts = tuple(dict(item) for item in candidate.structured_facts)
    if not safe_summary and not facts:
        # INVARIANT: version identity alone is not usable model context. The caller provides
        # safe material, while project-owned planning assets may use a concise marker.
        safe_summary = f"[{candidate.asset_type}:{candidate.asset_version_id}]"
    allowed_use = (
        "evidence_only"
        if candidate.asset_type in profile.evidence_only_types
        else (
            "structure_only"
            if candidate.source_use_mode == "structure_only"
            else candidate.allowed_use
        )
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
        context_class=context_candidate_class(candidate),
        source_expression_included=False,
        physical_asset_type=candidate.physical_asset_type or candidate.asset_type,
    )


def _rejection_reason(
    project_id: str, profile: ContextProfile, candidate: ContextCandidate
) -> str:
    if candidate.project_id != project_id:
        return "cross_project"
    if (
        candidate.qualification in BLOCKED_QUALIFICATIONS
        or candidate.qualification not in ELIGIBLE_QUALIFICATIONS
    ):
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


def replay_context_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    contract_version = str(bundle.get("context_contract_version") or "")
    manifest = bundle.get("context_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("CONTEXT_REPLAY_INVALID: Context Manifest is absent")
    expected = str(manifest.get("context_fingerprint") or "")
    body = dict(manifest)
    body.pop("context_fingerprint", None)
    actual = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    output_digest = str(
        dict(manifest.get("replay") or {}).get("output_context_digest") or ""
    )
    bundle_digest = str(bundle.get("actual_context_digest") or "")
    if expected != actual or output_digest != bundle_digest:
        raise ValueError("CONTEXT_REPLAY_MISMATCH: frozen Context evidence changed")
    versions = {
        "authority-context-bundle-v7": (
            "narrative-context-manifest-v3",
            "authority-context-selection-v2-four-class",
            "FROZEN_V7",
        ),
        "authority-context-bundle-v8": (
            "narrative-context-manifest-v4",
            "authority-context-selection-v3-governed",
            "FROZEN_V8",
        ),
    }
    try:
        manifest_version, algorithm, semantics = versions[contract_version]
    except KeyError as exc:
        raise ValueError(
            "CONTEXT_REPLAY_VERSION_UNSUPPORTED: " + contract_version
        ) from exc
    if (
        manifest.get("contract_version") != manifest_version
        or dict(manifest.get("replay") or {}).get("algorithm") != algorithm
    ):
        raise ValueError("CONTEXT_REPLAY_VERSION_MISMATCH: frozen semantics changed")
    return {
        "status": "MATCH",
        "context_contract_version": contract_version,
        "manifest_contract_version": manifest_version,
        "algorithm": algorithm,
        "semantics": semantics,
        "current_policy_compiler_invoked": False,
        "context_fingerprint": expected,
        "output_context_digest": output_digest,
    }


__all__ = [
    "CONTEXT_PROFILES",
    "ContextCandidate",
    "ContextProfile",
    "ContextSegment",
    "ContextSelection",
    "build_authority_context_bundle",
    "resolve_context_profile",
    "replay_context_bundle",
    "select_context_candidates",
]
