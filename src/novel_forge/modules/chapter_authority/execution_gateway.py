from __future__ import annotations
from novel_forge.modules.production_execution.cost_routing import producer_contract_identity
from novel_forge.modules.production_execution.contracts import local_cli_remote_outcome_unknown
from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping, Protocol
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.capability_pack_authority.domain import (
    CapabilityPackArtifactMaterialization,
    CapabilityPackAttemptSnapshot,
    canonical_hash,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.production_execution import (
    ArtifactPointer,
    CancellationOutcome,
    CapabilityId,
    CommitPolicy,
    ContextPolicy,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRecoveryAction,
    ExecutionRecoveryAuthorization,
    ExecutionRequest,
    FallbackPolicy,
    InputManifest,
    ModelProfile,
    ProductionExecutionGateway,
    PromptBundle,
    ResolvedExecutionPayload,
    RoutePolicy,
    RouteSnapshot,
    SkillBundle,
    SourcePolicy,
    TargetScope,
    ValidationPolicy,
    default_capability_registry,
)
from novel_forge.storage.database_runtime import get_database_runtime
from novel_forge.modules.production_execution.postgres import (
    PostgresExecutionRecoveryAuthorizationStore,
)
from novel_forge.modules.production_execution.evidence import (
    ExecutionRecord,
    ExecutionRecordStore,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
    ProviderControlLevel,
)
from novel_forge.modules.production_execution.provider_admission import (
    ProviderAdmissionReceipt,
    ProviderRequestEnvelope,
    TokenAccountingContract,
    build_route_token_accounting_contract,
    prepare_provider_admission,
    provider_request_protocol,
    verify_provider_admission,
)
from novel_forge.modules.context_builder.domain import replay_context_bundle
from novel_forge.modules.context_builder.governance import (
    ContextBudgetLimits,
    ContextPolicySnapshot,
    PolicyIdentity,
    compile_effective_context_policy,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.modules.chapter_authority.context_compression_provider import (
    CONTEXT_MODEL_STAGES,
    require_task_output_reserve,
    require_task_reasoning,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    chapter_provider_output_schema_ref,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_knowledge_view,
    build_provider_task_view,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_MODEL_WORKFLOW_DEFINITION_REF,
)

_STAGES = frozenset(
    {
        "memo",
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "canon_support",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "reader_outcome",
        "longform_prose_review",
        "screenplay_generate",
        "screenplay_review",
        "screenplay_revision",
        "narrative_semantic_evaluation",
    }
)
_OPTIONAL_DOMAIN_STAGES = frozenset(
    {"agent_session", "retrieval", "retrieval_query_expansion", *CONTEXT_MODEL_STAGES,
     "model_reference_evaluate", "model_reference_adjudicate"}
)

_PLANNING_STAGES = frozenset(
    {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
        "world_candidates.generate",
        "world_candidates.evaluate",
    }
)

_STAGE_CAPABILITIES = {
    "memo": CapabilityId.PLANNING_CHAPTER_MEMO,
    "draft": CapabilityId.PROSE_CHAPTER_DRAFT,
    "review": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "revision": CapabilityId.REVISION_CHAPTER_REVISE,
    "rereview": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "canon_extraction": CapabilityId.CANON_EXTRACT,
    "canon_support": CapabilityId.CANON_EXTRACT,
    "quality_structural": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "quality_commercial": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "quality_source_originality": CapabilityId.QUALITY_ORIGINALITY_JUDGE,
    "quality_longform": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "quality_platform": CapabilityId.QUALITY_PLATFORM_JUDGE,
    "reader_outcome": CapabilityId.QUALITY_READER_OUTCOME_JUDGE,
    "longform_prose_review": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "screenplay_generate": CapabilityId.PROSE_CHAPTER_DRAFT,
    "screenplay_review": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "screenplay_revision": CapabilityId.REVISION_CHAPTER_REVISE,
    "narrative_semantic_evaluation": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "model_reference_evaluate": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "model_reference_adjudicate": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "agent_session": CapabilityId.AGENT_WORKSPACE_EXECUTE,
    "retrieval": CapabilityId.RETRIEVAL_EMBED,
    "retrieval_query_expansion": CapabilityId.RETRIEVAL_QUERY_EXPAND,
    "context_compress": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "context_fidelity": CapabilityId.REVIEW_CHAPTER_EVALUATE,
}


def chapter_stage_capability(stage: str) -> CapabilityId:
    try:
        return _STAGE_CAPABILITIES[stage]
    except KeyError as exc:
        raise ValueError(f"unsupported Chapter execution stage: {stage}") from exc


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _identity_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _retrieval_embedding_output_contract(
    route: "ChapterExecutionRoute",
) -> dict[str, Any]:
    if route.stage != "retrieval" or route.embedding_dimensions <= 0:
        raise KernelError(
            "RETRIEVAL_EMBEDDING_OUTPUT_CONTRACT_MISSING",
            "controlled retrieval execution requires a frozen model and dimensions",
        )
    return {
        "contract_version": "retrieval-embedding-output-v1",
        "embedding_model": route.model_profile.model_id,
        "embedding_dimensions": route.embedding_dimensions,
        "vector_normalization": "L2_UNIT",
        "placeholder_vectors_allowed": False,
    }


def _provider_context_selection(
    stage: str,
    selected_inputs: list[dict[str, Any]],
    *,
    retrieval_projection: bool,
) -> list[dict[str, Any]]:
    if retrieval_projection:
        context = selected_inputs
    elif stage == "memo":
        context = [
            item
            for item in selected_inputs
            if item["artifact_type"] == "chapter_execution_intent"
        ]
    elif stage in {"retrieval", "retrieval_query_expansion", *CONTEXT_MODEL_STAGES}:
        context = [
            item for item in selected_inputs if item["artifact_type"] == "chapter_memo"
        ]
    else:
        context = [
            item
            for item in selected_inputs
            if item["artifact_type"] == "context_bundle"
        ]
    if stage in CONTEXT_MODEL_STAGES and len(context) == 1:
        from .execution_artifacts import validate_chapter_memo

        intents = [item for item in selected_inputs if item["artifact_type"] == "chapter_execution_intent"]
        if len(intents) != 1:
            raise KernelError("CONTEXT_COMPRESSION_INTENT_REQUIRED", "compression requires the exact frozen Intent and Memo")
        validate_chapter_memo(
            context[0]["content"], intent=intents[0]["content"],
            intent_asset_version_id=intents[0]["asset_version_id"],
        )
    if len(context) != 1:
        raise KernelError(
            "CHAPTER_CAPABILITY_CONTEXT_INVALID",
            "controlled execution requires exactly one frozen Provider context",
        )
    return context


def _provider_route_context_types(
    stage: str, *, retrieval_projection: bool
) -> tuple[str, ...]:
    if retrieval_projection:
        return ("best_draft_candidate",)
    if stage == "memo":
        return ("chapter_execution_intent",)
    if stage in {"retrieval", "retrieval_query_expansion", *CONTEXT_MODEL_STAGES}:
        return ("chapter_memo",)
    return ("context_bundle",)


def chapter_producer_contract_identity(
    prompt_evidence: Mapping[str, Any], materialization: Mapping[str, Any],
) -> dict[str, Any]:
    identity = producer_contract_identity(prompt_evidence, materialization)
    artifact = materialization["pack_artifacts"]["context_policy"]
    policy = dict(artifact["content"])
    reachable = set(_provider_route_context_types(str(materialization["stage"]), retrieval_projection=False))
    policy["allowed_asset_types"] = sorted(reachable.intersection(policy["allowed_asset_types"]))
    identity["schema_version"] = "routing-chapter-producer-contract.v2"
    identity["context_policy"] = {
        "ref": artifact["ref"], "version": artifact["version"],
        "projection": "chapter-stage-physical-context.v1", "content_hash": canonical_hash(policy),
    }
    tools = materialization["tool_permissions"]
    if tools["default"] != "DENY":
        raise KernelError("CHAPTER_CAPABILITY_TOOL_POLICY_INVALID", "evidence requires default-deny stage tools")
    tool_artifact = materialization["pack_artifacts"]["tool_policy"]
    tool_policy = dict(tool_artifact["content"])
    tool_policy["explicit_tool_refs"] = sorted(set(tool_policy["explicit_tool_refs"]).intersection(tools["allowed"]))
    identity["tool_policy"] = {
        "ref": tool_artifact["ref"], "version": tool_artifact["version"],
        "projection": "chapter-stage-tools.v1", "content_hash": canonical_hash(tool_policy),
    }
    identity["effective_tool_permissions"] = {
        "default": "DENY", "allowed": sorted(tools["allowed"]), "invoked": sorted(tools.get("invoked", [])),
    }
    return identity


def _provider_token_contract(
    route: "ChapterExecutionRoute",
    *,
    route_identity: str,
    output_reserve: int,
    execution_token_limit: int,
) -> TokenAccountingContract:
    applicable_execution_limit = (
        route.model_context_limit
        if route.model_profile.model_provider == "scripted_provider_v2"
        else execution_token_limit
    )
    return build_route_token_accounting_contract(
        provider=route.model_profile.model_provider,
        model=route.model_profile.model_id,
        route_identity=route_identity,
        accounting_method=route.token_accounting_method,
        accounting_evidence_ref=route.token_accounting_evidence_ref,
        model_context_limit=route.model_context_limit,
        execution_token_limit=applicable_execution_limit,
        output_reserve=output_reserve,
        safety_margin=route.token_safety_margin,
        framing_overhead=route.token_framing_overhead,
    )


def _provider_effective_context_policy(
    *,
    context_selection: list[dict[str, Any]],
    context_policy_payload: Mapping[str, Any],
    context_policy_hash: str,
    context_policy_ref: str,
    route_identity: str,
    route_allowed_physical_types: tuple[str, ...],
) -> dict[str, Any]:
    physical_allowed = tuple(
        str(value) for value in context_policy_payload.get("allowed_asset_types") or ()
    )
    physical_denied = tuple(
        str(value)
        for value in context_policy_payload.get("forbidden_asset_types") or ()
    )
    selected_physical = tuple(
        str(item.get("artifact_type") or "") for item in context_selection
    )
    if not route_allowed_physical_types or any(
        not value for value in route_allowed_physical_types
    ):
        raise KernelError(
            "CONTEXT_POLICY_UNRESOLVED",
            "Provider route has no immutable physical Context capability",
        )
    if set(selected_physical) - set(route_allowed_physical_types):
        raise KernelError(
            "CONTEXT_POLICY_CONFLICT",
            "Provider route does not admit the frozen physical Context selection",
        )
    if (
        not physical_allowed
        or any(not value for value in selected_physical)
        or set(selected_physical) - set(physical_allowed)
        or set(selected_physical) & set(physical_denied)
    ):
        raise KernelError(
            "CONTEXT_POLICY_CONFLICT",
            "Capability Pack does not admit the frozen physical Context selection",
        )
    content = context_selection[0].get("content")
    if not isinstance(content, Mapping):
        raise KernelError(
            "CONTEXT_POLICY_UNRESOLVED",
            "frozen Context selection has no contract content",
        )
    if selected_physical == ("chapter_execution_intent",):
        from .execution_artifacts import validate_chapter_execution_intent

        validate_chapter_execution_intent(content)
        snapshot = ContextPolicySnapshot(
            identity=PolicyIdentity(
                policy_id=context_policy_ref,
                version="capability-pack-context-policy-v1",
                content_hash=context_policy_hash,
                snapshot_ref=context_policy_ref,
            ),
            allowed_physical_types=("chapter_execution_intent",),
            denied_physical_types=physical_denied,
            limits=ContextBudgetLimits(
                total=int(context_policy_payload.get("max_tokens") or 0)
            ),
            maximum_raw_source_ratio=0.0,
        )
        compilation = compile_effective_context_policy((snapshot,))
        return {
            "compiler_version": "effective-context-policy-compiler-v1",
            "policy_compilation": dict(compilation.receipt),
            "effective_policy": compilation.effective_policy.to_dict(),
            "selected_physical_types": list(selected_physical),
            "intent_fingerprint": content["intent_fingerprint"],
        }
    if selected_physical == ("chapter_memo",):
        from .execution_artifacts import _hash, MEMO_INPUT_QUALIFICATIONS

        memo_body = dict(content)
        fingerprint = str(memo_body.pop("memo_fingerprint", ""))
        if content.get("qualification") not in MEMO_INPUT_QUALIFICATIONS or not fingerprint or fingerprint != _hash(memo_body):
            raise KernelError("CHAPTER_MEMO_FINGERPRINT_INVALID", "Provider context requires an exact qualified Memo")
        return {
            "compiler_version": "frozen-memo-context-physical-admission-v1",
            "memo_fingerprint": content["memo_fingerprint"],
            "physical_allowed_types": sorted(physical_allowed),
            "physical_denied_types": sorted(physical_denied),
            "selected_physical_types": list(selected_physical),
            "current_policy_compiler_invoked": False,
        }
    bundle_version = str(content.get("context_contract_version") or "")
    if bundle_version == "authority-context-bundle-v7":
        replay = replay_context_bundle(dict(content))
        return {
            "compiler_version": "frozen-context-v7-physical-admission-v1",
            "historical_replay": replay,
            "physical_allowed_types": sorted(physical_allowed),
            "physical_denied_types": sorted(physical_denied),
            "selected_physical_types": list(selected_physical),
            "current_policy_compiler_invoked": False,
        }
    manifest = content.get("context_manifest")
    if str(
        content.get("schema_version") or ""
    ) == "novelos.planning_context_bundle.v1" and not isinstance(manifest, Mapping):
        if (
            int(content.get("token_budget") or 0) != 16_000
            or content.get("source_isolation") != "ABSTRACT_ASSETS_ONLY"
            or not isinstance(content.get("input_versions"), list)
        ):
            raise KernelError(
                "CONTEXT_POLICY_UNRESOLVED",
                "historical Planning Context v1 violates its frozen contract",
            )
        return {
            "compiler_version": "frozen-planning-context-v1-physical-admission-v1",
            "context_contract_version": "novelos.planning_context_bundle.v1",
            "physical_allowed_types": sorted(physical_allowed),
            "physical_denied_types": sorted(physical_denied),
            "selected_physical_types": list(selected_physical),
            "current_policy_compiler_invoked": False,
            "historical_compatibility": "FROZEN_TYPED_PLANNING_V1",
        }
    typed_schema = str(content.get("schema_version") or "")
    if typed_schema == "novelos.model_reference_context_bundle.v1" and not isinstance(manifest, Mapping):
        provider_view = content.get("provider_context_view")
        frozen = content.get("model_reference")
        if (content.get("source_isolation") != "FROZEN_MODEL_REFERENCE_ONLY"
            or not isinstance(provider_view, Mapping)
            or provider_view.get("source_isolation") != "FROZEN_MODEL_REFERENCE_ONLY"
            or provider_view.get("source_bindings") != content.get("source_bindings")
            or provider_view.get("scope") != (frozen or {}).get("scope")):
            raise KernelError("CONTEXT_POLICY_UNRESOLVED", "model reference Context source isolation differs")
        return {"compiler_version": "frozen-model-reference-context-v1",
            "context_contract_version": typed_schema,
            "provider_view_hash": canonical_hash(provider_view),
            "physical_allowed_types": sorted(physical_allowed),
            "physical_denied_types": sorted(physical_denied),
            "selected_physical_types": list(selected_physical),
            "current_policy_compiler_invoked": False,
            "diagnostic_context_contract": "VERSIONED_MODEL_REFERENCE_V1"}
    typed_stage = {
        "novelos.narrative_evaluation_context_bundle.v1": (
            "narrative_semantic_evaluation"
        ),
        "novelos.reader_outcome_context_bundle.v1": "reader_outcome",
        "novelos.reader_outcome_context_bundle.v2": "reader_outcome",
        "novelos.longform_prose_review_context_bundle.v2": "longform_prose_review",
        "novelos.screenplay_generate_context_bundle.v1": "screenplay_generate",
        "novelos.screenplay_review_context_bundle.v1": "screenplay_review",
        "novelos.screenplay_revision_context_bundle.v1": "screenplay_revision",
    }.get(typed_schema)
    if typed_stage and not isinstance(manifest, Mapping):
        provider_view = build_provider_context_view(typed_stage, content, {})
        return {
            "compiler_version": "frozen-typed-context-physical-admission-v1",
            "context_contract_version": typed_schema,
            "provider_view_hash": canonical_hash(provider_view),
            "physical_allowed_types": sorted(physical_allowed),
            "physical_denied_types": sorted(physical_denied),
            "selected_physical_types": list(selected_physical),
            "current_policy_compiler_invoked": False,
            "historical_compatibility": "FROZEN_TYPED_CONTEXT",
        }
    if bundle_version != "authority-context-bundle-v8" and not isinstance(
        manifest, Mapping
    ):
        raise KernelError(
            "CONTEXT_POLICY_UNRESOLVED",
            "typed narrative Context has no canonical compiler receipt",
        )
    effective = (
        manifest.get("effective_policy") if isinstance(manifest, Mapping) else None
    )
    frozen_compilation = (
        manifest.get("policy_compilation") if isinstance(manifest, Mapping) else None
    )
    frozen_inputs = (
        frozen_compilation.get("input_policies")
        if isinstance(frozen_compilation, Mapping)
        else None
    )
    if (
        not isinstance(manifest, Mapping)
        or not isinstance(effective, Mapping)
        or not isinstance(frozen_inputs, list)
        or not frozen_inputs
    ):
        raise KernelError(
            "CONTEXT_POLICY_UNRESOLVED",
            "Context does not carry its frozen policy compiler inputs",
        )
    limits = effective.get("limits")
    if not isinstance(limits, Mapping):
        raise KernelError("CONTEXT_POLICY_UNRESOLVED", "Context limits are absent")
    try:
        context_snapshots = tuple(
            ContextPolicySnapshot.from_dict(item)
            for item in frozen_inputs
            if isinstance(item, Mapping)
        )
    except ValueError as exc:
        raise KernelError("CONTEXT_POLICY_UNRESOLVED", str(exc)) from exc
    if len(context_snapshots) != len(frozen_inputs):
        raise KernelError(
            "CONTEXT_POLICY_UNRESOLVED", "Context compiler input is not an object"
        )
    try:
        reconstructed = compile_effective_context_policy(context_snapshots)
    except ValueError as exc:
        raise KernelError("CONTEXT_POLICY_UNRESOLVED", str(exc)) from exc
    if dict(reconstructed.receipt) != dict(frozen_compilation) or any(
        effective.get(key) != value
        for key, value in reconstructed.effective_policy.to_dict().items()
    ):
        raise KernelError(
            "CONTEXT_POLICY_IDENTITY_CONFLICT",
            "frozen Context compiler receipt does not reconstruct exactly",
        )
    context_total = int(limits.get("total") or 0)
    pack_snapshot = ContextPolicySnapshot(
        identity=PolicyIdentity(
            policy_id=str(
                context_policy_payload.get("policy_id") or context_policy_ref
            ),
            version="capability-pack-context-policy-v1",
            content_hash=context_policy_hash,
            snapshot_ref=context_policy_ref,
        ),
        allowed_physical_types=physical_allowed,
        denied_physical_types=physical_denied,
        limits=ContextBudgetLimits(
            total=int(context_policy_payload.get("max_tokens") or 0)
        ),
        permitted_truncation_strategies=tuple(
            effective.get("permitted_truncation_strategies") or ()
        ),
        permitted_source_modes=tuple(effective.get("permitted_source_modes") or ()),
        source_risk_threshold=int(effective.get("source_risk_threshold") or 0),
        maximum_raw_source_ratio=float(effective.get("maximum_raw_source_ratio") or 0),
    )
    route_payload = {
        "route_identity": route_identity,
        "physical_context_types": sorted(set(route_allowed_physical_types)),
        "context_limit": context_total,
    }
    route_snapshot = ContextPolicySnapshot(
        identity=PolicyIdentity(
            policy_id="provider-route-context:" + route_identity,
            version="provider-route-context-capability-v1",
            content_hash=canonical_hash(route_payload),
            snapshot_ref="provider-route:" + route_identity,
        ),
        allowed_physical_types=tuple(sorted(set(route_allowed_physical_types))),
        limits=ContextBudgetLimits(total=context_total),
        permitted_truncation_strategies=tuple(
            effective.get("permitted_truncation_strategies") or ()
        ),
        permitted_source_modes=tuple(effective.get("permitted_source_modes") or ()),
        source_risk_threshold=int(effective.get("source_risk_threshold") or 0),
        maximum_raw_source_ratio=float(effective.get("maximum_raw_source_ratio") or 0),
    )
    compilation = compile_effective_context_policy(
        (*context_snapshots, pack_snapshot, route_snapshot)
    )
    admitted_physical = set(compilation.effective_policy.allowed_physical_types)
    if set(selected_physical) - admitted_physical:
        raise KernelError(
            "CONTEXT_POLICY_CONFLICT",
            "Provider route does not admit the frozen physical Context selection",
        )
    return dict(compilation.receipt)


def _stage_tool_permissions(
    policy: Mapping[str, Any], stage: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if str(policy.get("default") or "").upper() != "DENY":
        raise KernelError(
            "CHAPTER_CAPABILITY_TOOL_POLICY_INVALID",
            "controlled Capability Tool policy must default deny",
        )
    tools = policy.get("tools")
    if not isinstance(tools, list):
        raise KernelError(
            "CHAPTER_CAPABILITY_TOOL_POLICY_INVALID",
            "Capability Tool policy requires explicit tool entries",
        )
    allowed: set[str] = set()
    denied: set[str] = set()
    for item in tools:
        if not isinstance(item, Mapping):
            raise KernelError(
                "CHAPTER_CAPABILITY_TOOL_POLICY_INVALID",
                "Capability Tool entry must be an object",
            )
        tool_ref = str(item.get("tool_ref") or "")
        operations = {str(value) for value in item.get("allowed_operations") or ()}
        if (
            tool_ref
            and str(item.get("permission") or "").upper() in {"EXECUTE", "QUERY"}
            and (
                "canon_proposal" if stage == "canon_support" else
                "context" if stage in CONTEXT_MODEL_STAGES and stage in set(
                    dict(policy.get("external_models") or {}).get("context_substages") or ()
                ) else stage
            ) in operations
        ):
            allowed.add(tool_ref)
        elif tool_ref:
            denied.add(tool_ref)
    return tuple(sorted(allowed)), tuple(sorted(denied - allowed))


@dataclass(frozen=True, slots=True)
class ChapterExecutionRoute:
    stage: str
    model_profile: ModelProfile
    route_policy: RoutePolicy
    fallback_policy: FallbackPolicy
    backend_version: str
    runtime_host_id: str
    auth_profile_ref: str
    prompt_version: str
    skill_version: str
    system_instruction_hash: str
    template_hash: str
    skill_content_hash: str
    prompt_compiler_version: str
    output_schema_ref: str
    release_sha: str
    real_provider_validation_eligible: bool
    embedding_dimensions: int = 0
    model_context_limit: int = 0
    model_output_limit: int = 0
    token_accounting_method: str = ""
    token_accounting_evidence_ref: str = ""
    token_safety_margin: int = 256
    token_framing_overhead: int = 16
    task_reasoning_authorization: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.stage not in _STAGES | _OPTIONAL_DOMAIN_STAGES:
            raise ValueError(f"unsupported Chapter execution stage: {self.stage}")
        if (
            self.model_profile.profile_id
            not in self.route_policy.allowed_model_profile_ids
        ):
            raise ValueError("Chapter route policy does not allow its ModelProfile")
        if (
            self.route_policy.fallback_policy_ref != self.fallback_policy.policy_id
            or self.route_policy.fallback_policy_version
            != self.fallback_policy.policy_version
            or self.route_policy.fallback_policy != self.fallback_policy.mode.value
        ):
            raise ValueError("Chapter route policy does not bind its FallbackPolicy")
        if not all(
            (
                self.backend_version,
                self.runtime_host_id,
                self.auth_profile_ref,
                self.prompt_version,
                self.skill_version,
                self.system_instruction_hash,
                self.template_hash,
                self.skill_content_hash,
                self.prompt_compiler_version,
                self.output_schema_ref,
            )
        ):
            raise ValueError("Chapter execution route is incomplete")
        if len(self.release_sha) != 40:
            raise ValueError("Chapter execution route requires a full release SHA")
        if self.stage == "retrieval" and not 1 <= self.embedding_dimensions <= 8192:
            raise ValueError(
                "retrieval execution route requires 1..8192 embedding dimensions"
            )
        if self.stage != "retrieval" and self.embedding_dimensions != 0:
            raise ValueError(
                "embedding dimensions may only be bound to the retrieval route"
            )
        if (
            min(
                self.model_context_limit,
                self.model_output_limit,
                self.token_safety_margin,
                self.token_framing_overhead,
            )
            < 0
        ):
            raise ValueError("Chapter route Token Accounting limits are invalid")
        definition = default_capability_registry().resolve(
            chapter_stage_capability(self.stage)
        )
        if self.model_profile.timeout_policy_ref != definition.timeout_policy_ref:
            raise ValueError(
                "Chapter ModelProfile timeout differs from its governed capability"
            )
        for label, value in (
            ("system instruction", self.system_instruction_hash),
            ("template", self.template_hash),
            ("skill content", self.skill_content_hash),
        ):
            normalized = value.removeprefix("sha256:")
            if len(normalized) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in normalized
            ):
                raise ValueError(f"Chapter route {label} hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class ChapterExecutionBinding:
    request: ExecutionRequest
    route_snapshot: RouteSnapshot
    input_manifest: InputManifest
    capability_pack_attempt_snapshot: CapabilityPackAttemptSnapshot | None = None


@dataclass(frozen=True, slots=True)
class ChapterCapabilityPreflight:
    attempt_snapshot: CapabilityPackAttemptSnapshot | None
    materialization: CapabilityPackArtifactMaterialization | None
    materialization_artifact: ArtifactPointer
    effect_binding: Mapping[str, Any]
    provider_admission_artifact: ArtifactPointer | None = None


class PostgresChapterExecutionContractBinder:
    def __init__(
        self,
        database_url: str,
        routes: Mapping[str, ChapterExecutionRoute],
        *,
        capability_pack_id: str = "",
        pack_environment: str = "development",
        pack_runtime_profile: str = "development",
        pack_release_channel: str = "VALIDATION",
        pack_required: bool = False,
        workflow_definition_ref: str = CHAPTER_MODEL_WORKFLOW_DEFINITION_REF,
    ) -> None:
        route_names = set(routes)
        if (
            not database_url
            or not _STAGES.issubset(route_names)
            or not route_names.issubset(_STAGES | _OPTIONAL_DOMAIN_STAGES)
        ):
            raise ValueError(
                "PostgreSQL and all governed execution routes are required"
            )
        self.database_url = database_url
        self.routes = dict(routes)
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)
        self.capability_pack_id = capability_pack_id
        self.pack_environment = pack_environment
        self.pack_runtime_profile = pack_runtime_profile
        self.pack_release_channel = pack_release_channel
        self.pack_required = pack_required
        self.workflow_definition_ref = workflow_definition_ref
        self.pack_resolver = CapabilityPackRuntimeResolver(database_url)
        self.provider_router: Any = None

    def freeze_before_external_effect(
        self,
        *,
        capability: str,
        request_payload: Mapping[str, Any],
        snapshot_fencing_token: int,
        snapshot_worker_id: str,
    ) -> ChapterCapabilityPreflight | None:

        stage = str(request_payload.get("stage") or "")
        metadata = request_payload.get("_production_execution")
        if capability != f"model.{stage}" or stage not in self.routes:
            raise KernelError(
                "CHAPTER_CAPABILITY_REQUIREMENT_INVALID",
                "Chapter Capability requirement does not match the model stage",
            )
        if not isinstance(metadata, Mapping):
            raise KernelError(
                "CHAPTER_CAPABILITY_METADATA_MISSING",
                "Capability preflight requires Attempt metadata",
            )
        operation_id = str(metadata.get("operation_id") or "")
        attempt_id = str(metadata.get("attempt_id") or "")
        project_id = str(metadata.get("project_id") or "")
        workspace_id = str(metadata.get("workspace_id") or "")
        book_id = str(metadata.get("book_id") or "")
        worker_id = str(metadata.get("worker_id") or "")
        try:
            execution_fencing_token = int(metadata.get("fencing_token") or 0)
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "CHAPTER_CAPABILITY_METADATA_INVALID",
                "Capability preflight fencing identity is invalid",
            ) from exc
        if (
            not all(
                (
                    operation_id,
                    attempt_id,
                    project_id,
                    workspace_id,
                    book_id,
                    worker_id,
                    snapshot_worker_id,
                )
            )
            or min(execution_fencing_token, snapshot_fencing_token) <= 0
        ):
            raise KernelError(
                "CHAPTER_CAPABILITY_METADATA_INCOMPLETE",
                "Capability preflight Attempt identity is incomplete",
            )
        if not self.capability_pack_id:
            raise KernelError(
                "CHAPTER_CAPABILITY_PACK_REQUIRED",
                "Capability preflight requires a governed Capability Pack",
            )
        graph = self._operation_graph(operation_id, project_id)
        if graph["definition_name"].startswith("chapter.provider.sample.") and self.provider_router is None:
            raise KernelError("CHAPTER_SAMPLE_ROUTER_REQUIRED", "sampling must resolve its authorized candidate through the native Router")
        route = self.routes[stage]
        routing_decision = None
        attempt_snapshot = self._resolve_pack_snapshot(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            execution_fencing_token=execution_fencing_token,
            worker_id=worker_id,
            snapshot_creation_fencing_token=snapshot_fencing_token,
            snapshot_creation_worker_id=snapshot_worker_id,
            stage=stage,
            graph=graph,
            route=route,
        )
        if attempt_snapshot is None:
            if self.pack_required:
                raise KernelError(
                    "CHAPTER_CAPABILITY_PACK_REQUIRED",
                    "Capability Pack resolution did not produce an Attempt Snapshot",
                )
            return None
        materialization = self.pack_resolver.materialize_attempt_artifacts(
            attempt_snapshot
        )
        supported_templates = {
            "prompt-template:chapter-generation-pack": {
                "v2",
                "v3",
                "v4",
                "v5",
                "v6",
                "v7",
                "v8",
        "v9", "v10", "v11", "v12", "v13", "v15",
            },
            "prompt-template:agent-session-pack": {"v1"},
            "prompt-template:story-planning-pack": {"v1", "v2", "v3"},
            "prompt-template:reader-outcome-pack": {"v2"},
            "prompt-template:longform-prose-review-pack": {"v2"},
            "prompt-template:narrative-semantic-evaluation-pack": {"v1"},
            "prompt-template:model-reference-creation": {"v1"},
            "prompt-template:scene-screenplay-pack": {"v1"},
        }
        if materialization.prompt_template.version not in supported_templates.get(
            materialization.prompt_template.ref, set()
        ):
            raise KernelError(
                "CHAPTER_PROMPT_CONTRACT_UNSUPPORTED",
                "frozen Prompt Template identity has no output contract adapter",
            )
        artifacts = self._artifacts(metadata)
        selected_inputs = self._materialize_selected_inputs(
            project_id=project_id,
            artifacts=artifacts,
            reference_operation_id=operation_id, reference_stage=stage,
        )
        if stage in CONTEXT_MODEL_STAGES:
            chunk = dict(dict(request_payload.get("input") or {}).get("context_compression_task") or {})
            source = dict(chunk.get("source_binding") or {})
            matches = [item for item in selected_inputs
                       if item["asset_version_id"] == source.get("asset_version_id")
                       and item["content_hash"] == source.get("content_hash")]
            if len(matches) != 1:
                raise KernelError("CONTEXT_COMPRESSION_SOURCE_DRIFT", "compression source must match one exact frozen input version and hash")
        retrieval_projection = (
            str(metadata.get("execution_binding_domain") or "")
            == "retrieval_projection"
        )
        context_selection = _provider_context_selection(
            stage,
            selected_inputs,
            retrieval_projection=retrieval_projection,
        )
        frozen_context_policy_payload = json.loads(
            attempt_snapshot.execution_snapshot.context_policy_payload_json
        )
        route_identity = ":".join(
            (
                route.stage,
                route.model_profile.model_provider,
                route.model_profile.model_id,
                route.release_sha,
                attempt_snapshot.snapshot_hash,
            )
        )
        effective_context_policy = _provider_effective_context_policy(
            context_selection=context_selection,
            context_policy_payload=frozen_context_policy_payload,
            context_policy_hash=(
                attempt_snapshot.execution_snapshot.context_policy_hash
            ),
            context_policy_ref=attempt_snapshot.execution_snapshot.context_policy_ref,
            route_identity=route_identity,
            route_allowed_physical_types=_provider_route_context_types(
                stage, retrieval_projection=retrieval_projection
            ),
        )
        tool_payload = json.loads(
            attempt_snapshot.execution_snapshot.tool_policy_payload_json
        )
        allowed_tools, denied_tools = _stage_tool_permissions(tool_payload, stage)
        if "model.provider.invoke" not in allowed_tools:
            raise KernelError(
                "CHAPTER_CAPABILITY_TOOL_UNAUTHORIZED",
                "Capability Pack does not authorize model.provider.invoke for this stage",
            )
        if stage == "canon_extraction" and graph["definition_version"] in {"3.9.5", "3.9.6", "3.9.7"} and materialization.prompt_template.version != ("v11" if graph["definition_version"]=="3.9.7" else "v10"):
            raise KernelError("CHAPTER_CANON_SCHEMA_PROJECTION_REQUIRED", "Canon requires its exact versioned Schema and transport Prompt binding")
        if graph["definition_version"] == "3.10.0" and materialization.prompt_template.version not in {"v12", "v13", "v15"}:
            raise KernelError("CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED", "Coordinated Chapter requires its exact new current prompt contract")
        provider_schema, provider_schema_ref = self._provider_output_contract(
            stage=stage,
            request_payload=request_payload,
            legacy_contract=materialization.prompt_template.version == "v2",
            prompt_contract_version=materialization.prompt_template.version,
        )
        if stage == "canon_support" and graph["definition_version"]=="3.9.8" and provider_schema_ref!="schema:chapter-provider-output:canon_support:v2":
            raise KernelError("CHAPTER_CANON_SUPPORT_CONTRACT_REQUIRED", "Support requires its exact finite taxonomy Schema binding")
        if stage.startswith("quality_") and graph["definition_version"] in {"3.9.9", "3.9.12"} and provider_schema_ref!=f"schema:chapter-provider-output:{stage}:v5":
            raise KernelError("CHAPTER_QUALITY_APPLICABILITY_CONTRACT_REQUIRED", "Quality requires its exact frozen applicability Schema")
        schema_hash = canonical_hash(provider_schema)
        embedding_output_contract = (
            _retrieval_embedding_output_contract(route)
            if stage == "retrieval"
            else None
        )
        contract_without_hash: dict[str, Any] = {
            "schema_version": "novelos.chapter_capability_materialization.v1",
            "stage": stage,
            "capability_requirement": capability,
            "attempt_snapshot": {
                "snapshot_id": attempt_snapshot.snapshot_id,
                "snapshot_hash": attempt_snapshot.snapshot_hash,
                "operation_id": attempt_snapshot.operation_id,
                "attempt_id": attempt_snapshot.attempt_id,
                "execution_fencing_token": (attempt_snapshot.execution_fencing_token),
                "snapshot_creation_fencing_token": (
                    attempt_snapshot.snapshot_creation_fencing_token
                ),
            },
            "pack_identity": {
                "pack_id": attempt_snapshot.execution_snapshot.pack_id,
                "pack_version": attempt_snapshot.execution_snapshot.pack_version,
                "manifest_hash": attempt_snapshot.execution_snapshot.manifest_hash,
                "compilation_hash": (
                    attempt_snapshot.execution_snapshot.compilation_hash
                ),
                "catalog_snapshot_hash": (
                    attempt_snapshot.execution_snapshot.catalog_snapshot_hash
                ),
                "binding_set_id": (attempt_snapshot.execution_snapshot.binding_set_id),
                "binding_set_hash": (
                    attempt_snapshot.execution_snapshot.binding_set_hash
                ),
            },
            "pack_artifacts": materialization.to_dict(include_content=True),
            "pack_artifact_materialization_hash": (
                materialization.materialization_hash
            ),
            "context_selection": context_selection,
            "effective_context_policy": effective_context_policy,
            "knowledge_selection": [
                item.to_dict(include_content=True)
                for item in materialization.required_knowledge
            ]
            + [
                item
                for item in selected_inputs
                if item["artifact_type"] == "knowledge_pack"
            ],
            "tool_permissions": {
                "default": str(tool_payload.get("default") or ""),
                "allowed": list(allowed_tools),
                "denied": list(denied_tools),
                "invoked": ["model.provider.invoke"],
                "governing_policy_ref": (
                    attempt_snapshot.execution_snapshot.tool_policy_ref
                ),
                "governing_policy_hash": (
                    attempt_snapshot.execution_snapshot.tool_policy_hash
                ),
            },
            "output_schema": {
                "ref": provider_schema_ref,
                "content_hash": schema_hash,
                "content": provider_schema,
            },
        }
        if embedding_output_contract is not None:
            contract_without_hash["embedding_output_contract"] = (
                embedding_output_contract
            )
        materialization_hash = canonical_hash(contract_without_hash)
        contract = {
            **contract_without_hash,
            "materialization_hash": materialization_hash,
        }
        contract_stage_identity = (
            str(request_payload.get("stable_idempotency_key") or "")
            if stage in CONTEXT_MODEL_STAGES else stage
        )
        token = _identity_token(
            f"{project_id}:{operation_id}:{attempt_id}:{contract_stage_identity}:capability"
        )
        logical_ref = f"production_execution/capability_materializations/{token}"
        document = self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=logical_ref,
            asset_type="capability_materialization_manifest",
            contract=contract,
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        pointer = ArtifactPointer(
            artifact_ref=f"asset-version:{document.asset_version_id}",
            asset_version_id=document.asset_version_id,
            artifact_type=document.asset_type,
            content_hash=document.content_hash,
            schema_version="novelos.chapter_capability_materialization.v1",
            source_eligibility="NOT_SOURCE_DERIVED",
        )
        provider_inputs = request_payload.get("input")
        if not isinstance(provider_inputs, Mapping):
            raise KernelError(
                "CHAPTER_PROVIDER_INPUT_INVALID",
                "Provider admission requires frozen stage inputs",
            )
        target_scope = self._target_scope(
            metadata=metadata,
            project_id=project_id,
            book_id=book_id,
            chapter=int(metadata.get("chapter") or 0),
        )
        prompt, prompt_evidence = _materialize_production_codex_prompt(
            target_scope=target_scope,
            stage=stage,
            inputs=provider_inputs,
            materialization=contract,
        )
        stable_idempotency_key = str(
            request_payload.get("stable_idempotency_key") or ""
        )
        timeout_seconds = int(metadata.get("provider_request_timeout_seconds") or 0)
        output_reserve = int(request_payload.get("max_output_tokens") or 0)
        if not stable_idempotency_key or timeout_seconds <= 0 or output_reserve <= 0:
            raise KernelError(
                "PROVIDER_ADMISSION_INPUT_INCOMPLETE",
                "Provider admission requires stable identity, timeout, and output reserve",
            )
        if self.provider_router is not None and embedding_output_contract is None:
            route, routing_decision = self.provider_router.select(route, task_type=stage,
                project_id=project_id, work_id=book_id, operation_id=operation_id,
                attempt_id=attempt_id, stable_key=stable_idempotency_key,
                input_tokens=len(prompt.encode()) + route.token_safety_margin + route.token_framing_overhead,
                output_tokens=output_reserve, trace_id=str(request_payload["trace_id"]),
                correlation_id=str(request_payload["correlation_id"]), cache_prefix=prompt.encode()[:prompt_evidence["reusable_prefix_bytes"]],
                producer_contract=chapter_producer_contract_identity(prompt_evidence, contract),
                request_input=provider_inputs, input_hash="sha256:" + hashlib.sha256(prompt.encode()).hexdigest(), chapter=int(metadata.get("chapter") or 0))
            route_identity = routing_decision["decision_id"]
        task_scoped = stage in CONTEXT_MODEL_STAGES or any(
            str(item.get("content", {}).get("profile_version") or "") == "draft-context-profile-v4"
            for item in selected_inputs
        ) or str(metadata.get("task_context_profile") or "") == "draft-context-profile-v4"
        require_task_reasoning(route, task_scoped=task_scoped and stage != "retrieval")
        if task_scoped and stage != "retrieval":
            require_task_output_reserve(
                stage, route, output_reserve, capacity_error_code="TASK_CONTEXT_MODEL_OUTPUT_LIMIT_EXCEEDED",
            )
        envelope = ProviderRequestEnvelope(
            provider=route.model_profile.model_provider,
            reasoning_effort=route.model_profile.reasoning_effort if route.model_profile.model_provider in {"deepseek", "openai"} else "",
            pricing_policy_json=json.dumps(routing_decision["selected"]["candidate"]["pricing"], sort_keys=True) if routing_decision else "",
            model=route.model_profile.model_id,
            protocol=provider_request_protocol(route.model_profile.model_provider),
            input_text=prompt,
            max_output_tokens=output_reserve,
            timeout_seconds=_provider_process_timeout_seconds(
                timeout_seconds, max_attempts=1 if stage == "longform_prose_review" else 2
            ),
            stable_idempotency_key=stable_idempotency_key,
        )
        token_contract = _provider_token_contract(
            route,
            route_identity=route_identity,
            output_reserve=output_reserve,
            execution_token_limit=int(
                metadata.get("provider_token_limit") or route.model_context_limit
            ),
        )
        context_content = context_selection[0].get("content")
        context_bundle_tokens = (
            int(context_content.get("estimated_tokens") or 0)
            if isinstance(context_content, Mapping)
            else 0
        )
        admission = prepare_provider_admission(
            envelope,
            token_contract,
            context_bundle_tokens=context_bundle_tokens,
            input_component_hashes=dict(
                dict(prompt_evidence.get("provider_view") or {}).get("component_hashes")
                or {}
            ),
            complete_request_coverage=(
                "system_runtime_instructions",
                "prompt_template",
                "skill_instructions",
                "tool_policy_and_schemas",
                "structured_output_schema",
                "context_bundle",
                "knowledge_inputs",
                "request_envelope_and_framing",
                "output_reserve",
                "safety_margin",
            ),
        )
        if admission.status != "ADMITTED":
            raise KernelError(
                "PROVIDER_TOKEN_ADMISSION_REJECTED",
                admission.reason,
            )
        admission_contract = {
            "schema_version": "novelos.provider_request_admission.v1",
            "provider_request_identity": envelope.to_identity_dict(),
            "provider_admission": admission.to_dict(),
            "effective_context_policy": effective_context_policy,
            "prompt_materialization": prompt_evidence,
            "capability_materialization_asset_version_id": document.asset_version_id,
            "capability_materialization_content_hash": document.content_hash,
        }
        admission_ref = f"production_execution/provider_admissions/{token}"
        admission_document = self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=admission_ref,
            asset_type="provider_request_admission_manifest",
            contract=admission_contract,
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        admission_pointer = ArtifactPointer(
            artifact_ref=f"asset-version:{admission_document.asset_version_id}",
            asset_version_id=admission_document.asset_version_id,
            artifact_type=admission_document.asset_type,
            content_hash=admission_document.content_hash,
            schema_version="novelos.provider_request_admission.v1",
            source_eligibility="NOT_SOURCE_DERIVED",
        )
        effect_binding = {
            "snapshot_id": attempt_snapshot.snapshot_id,
            "snapshot_hash": attempt_snapshot.snapshot_hash,
            "pack_ref": (
                f"{attempt_snapshot.execution_snapshot.pack_id}@"
                f"{attempt_snapshot.execution_snapshot.pack_version}"
            ),
            "manifest_hash": attempt_snapshot.execution_snapshot.manifest_hash,
            "compilation_hash": (attempt_snapshot.execution_snapshot.compilation_hash),
            "binding_set_hash": (attempt_snapshot.execution_snapshot.binding_set_hash),
            "materialization_asset_version_id": document.asset_version_id,
            "materialization_content_hash": document.content_hash,
            "materialization_hash": materialization_hash,
            "prompt_system_instruction_hash": (
                materialization.system_instruction.content_hash
            ),
            "prompt_template_hash": materialization.prompt_template.content_hash,
            "skill_content_hash": materialization.skill.content_hash,
            "context_asset_version_ids": [
                item["asset_version_id"] for item in context_selection
            ],
            "knowledge_content_hashes": [
                item.content_hash for item in materialization.required_knowledge
            ],
            "allowed_tools": list(allowed_tools),
            "output_schema_ref": provider_schema_ref,
            "output_schema_hash": schema_hash,
            "provider_admission_asset_version_id": admission_document.asset_version_id,
            "provider_admission_content_hash": admission_document.content_hash,
            "provider_request_envelope_hash": envelope.envelope_hash,
            "token_accounting_contract": token_contract.to_dict(),
            "provider_admission": admission.to_dict(),
        }
        if routing_decision is not None:
            effect_binding["routing_decision"] = routing_decision
        if embedding_output_contract is not None:
            effect_binding["embedding_output_contract"] = embedding_output_contract
        return ChapterCapabilityPreflight(
            attempt_snapshot=attempt_snapshot,
            materialization=materialization,
            materialization_artifact=pointer,
            provider_admission_artifact=admission_pointer,
            effect_binding=effect_binding,
        )

    @staticmethod
    def _provider_output_contract(
        *,
        stage: str,
        request_payload: Mapping[str, Any],
        legacy_contract: bool = False,
        prompt_contract_version: str = "v3",
    ) -> tuple[dict[str, Any], str]:
        inputs = request_payload.get("input") or {}
        from novel_forge.modules.review.diagnostics import structural_repair_scope, prose_repair_diagnoses
        structural_revision = stage == "revision" and (bool(inputs.get("chapter_length_repair_scope")) or structural_repair_scope(
            prose_repair_diagnoses(dict(inputs["review"]), work_requirements="creative_baseline" in (inputs.get("draft") or {})) if inputs.get("review") else [],
            review=inputs.get("review")) == "CHAPTER_REVISION")
        causal_batch = bool(
            (inputs.get("execution_expectations") or {}).get("world_preparation")
        )
        targeted_revision = bool(
            stage == "revision"
            and not structural_revision
            and prompt_contract_version in {"v4", "v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13", "v15"}
            and (
                inputs.get("quality_edit_contract")
                or (prompt_contract_version in {"v9", "v10", "v11", "v12", "v13", "v15"} and (
                    inputs.get("cross_chapter_window")
                    or (inputs.get("review") or {}).get("cross_chapter_window")
                    or (inputs.get("review") or {}).get("craft_targets")
                ))
                or (
                    (
                        (inputs.get("review") or {}).get("issues")
                        or (inputs.get("review") or {}).get("unresolved_issues")
                    )
                    and (
                        inputs.get("cross_chapter_window")
                        or (inputs.get("review") or {}).get("cross_chapter_window")
                        or (inputs.get("review") or {}).get("craft_targets")
                    )
                )
            )
        )
        schema = chapter_provider_output_schema(
            stage,
            character_references=(inputs.get("execution_intent") or {}).get("character_reference_contract") if stage == "memo" else None,
            causal_batch=causal_batch,
            legacy_contract=legacy_contract,
            targeted_revision=targeted_revision,
            work_requirements=prompt_contract_version in {"v8", "v9", "v10", "v11", "v12", "v13", "v15"},
            allow_noop_revision=prompt_contract_version in {"v9", "v10", "v11", "v12", "v13", "v15"} and not bool(inputs.get("quality_edit_contract")),
        )
        schema_ref = chapter_provider_output_schema_ref(
            stage,
            character_references=(inputs.get("execution_intent") or {}).get("character_reference_contract") if stage == "memo" else None,
            causal_batch=causal_batch,
            legacy_contract=legacy_contract,
            targeted_revision=targeted_revision,
            work_requirements=prompt_contract_version in {"v8", "v9", "v10", "v11", "v12", "v13", "v15"},
            allow_noop_revision=prompt_contract_version in {"v9", "v10", "v11", "v12", "v13", "v15"} and not bool(inputs.get("quality_edit_contract")),
        )
        if stage == "longform_prose_review" and inputs.get("prose_diagnosis_contract") == "prose-root-cause.v1":
            from novel_forge.modules.book_followup_authority.prose_review import prose_review_output_schema
            schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **prose_review_output_schema(root_cause=True)}
            schema_ref = "schema:chapter-provider-output:longform_prose_review:v2"
        if stage in {"screenplay_generate", "screenplay_review", "screenplay_revision"}:
            from novel_forge.modules.book_followup_authority.screenplay import screenplay_output_schema
            contract = inputs.get("screenplay_source_contract", "screenplay-source.v1")
            if contract not in {"screenplay-source.v1", "screenplay-source.v2"}:
                raise KernelError("SCREENPLAY_SOURCE_CONTRACT_UNSUPPORTED", "Provider schema requires the exact frozen source contract")
            schema = screenplay_output_schema(stage, craft=contract == "screenplay-source.v2")
            schema_ref = "schema:chapter-provider-output:" + stage + (":v2" if contract == "screenplay-source.v2" else ":v1")
        current_review = stage in {"review", "rereview"} and prompt_contract_version in {"v9", "v10", "v11", "v12", "v13", "v15"}
        if current_review:
            schema_ref = f"schema:chapter-provider-output:{stage}:v6"
        if inputs.get("cross_chapter_window") or (stage == "revision" and inputs.get("required_actions") is None and (inputs.get("review") or {}).get("cross_chapter_window")):
            from novel_forge.modules.review.cross_chapter import extend_provider_schema
            cross_version = (
                "v2" if legacy_contract else "v6" if current_review
                else "v5" if targeted_revision and prompt_contract_version in {"v9", "v10", "v11", "v12", "v13", "v15"} and not inputs.get("quality_edit_contract")
                else "v4" if targeted_revision else "v3"
            )
            schema = extend_provider_schema(schema, stage, legacy_contract=legacy_contract)
            schema_ref = f"schema:chapter-provider-output:{stage}:cross-chapter-{cross_version}"
        if stage == "revision" and inputs.get("quality_edit_contract"):
            from novel_forge.modules.review.cross_chapter import extend_provider_schema
            schema = extend_provider_schema(schema, stage, legacy_contract=legacy_contract)
            schema_ref += ":quality-targeted-v2" if targeted_revision else ":quality-targeted-v1"
        if stage == "rereview" and (inputs.get("revision") or {}).get("quality_edit_contract"):
            from novel_forge.modules.revision.domain import extend_quality_rereview_schema
            schema = extend_quality_rereview_schema(schema, legacy_contract=legacy_contract)
            schema_ref += ":quality-resolution-v1"
        if stage in {"review", "revision", "rereview"}:
            from novel_forge.modules.review.craft import craft_review_targets, extend_craft_provider_schema
            candidate = inputs.get("revision") or inputs.get("draft") or {}
            if craft_review_targets(candidate) and not (stage == "revision" and inputs.get("required_actions") is not None):
                phase_transitions = any(target.get("usage", {}).get("type_policy", {}).get("transition_policy") for target in craft_review_targets(candidate))
                schema = extend_craft_provider_schema(schema, stage, phase_transitions=phase_transitions, legacy_contract=legacy_contract)
                schema_ref += (":narrative-craft-v2" if phase_transitions else ":narrative-craft-v1") if legacy_contract else (":narrative-craft-v3" if phase_transitions else ":narrative-craft-v2")
        if stage in {"review", "rereview"} and inputs.get("review_knowledge_scope_contract") == "delivered-card-scope.v1":
            from .provider_output_contracts import bind_delivered_knowledge_scope
            schema = bind_delivered_knowledge_scope(schema, inputs.get("knowledge_review_targets") or [])
            schema_ref += ":delivered-card-scope-v1"
        if stage == "canon_extraction" and prompt_contract_version in {"v10", "v11", "v12", "v13", "v15"}:
            from .provider_output_contracts import shared_canon_schema
            schema = shared_canon_schema(schema)
            schema_ref = "schema:chapter-provider-output:canon_extraction:v25" if prompt_contract_version=="v11" else "schema:chapter-provider-output:canon_extraction:v24"
        if stage == "draft" and (inputs.get("realization_contract") or {}).get("contract_version") == "scene-realization-composition.v3":
            from .realization_composition import scoped_realization_schema
            schema = scoped_realization_schema(schema, inputs["realization_contract"])
            schema_ref = "schema:chapter-provider-output:draft:v4"
        working = inputs.get("working_manuscript") or (inputs.get("frozen_intent") or {}).get("working_manuscript") or (inputs.get("execution_intent") or {}).get("working_manuscript") or {}
        if stage == "draft" and (working.get("projection_policy") or {}).get("version") == "working-prose-projection.v3":
            schema["properties"]["working_memory_json"] = {"type": "string", "maxLength": 100000}
            schema_ref += ":working-memory-v1"
        if stage == "revision" and not targeted_revision and (inputs.get("draft", {}).get("realization_contract") or {}).get("contract_version") == "scene-realization-composition.v3":
            from .realization_composition import scoped_realization_schema
            schema = scoped_realization_schema(schema, inputs["draft"]["realization_contract"])
            schema_ref = "schema:chapter-provider-output:revision:v6"
        if structural_revision:
            schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                      "properties": {"text": {"type": "string", "minLength": 1},
                          "resolved_issue_codes": {"type": "array", "items": {"type": "string"}}},
                      "required": ["text", "resolved_issue_codes"], "additionalProperties": False}
            schema_ref = "schema:chapter-provider-output:revision:v7"
        if stage == "canon_support" and inputs.get("support_kind_contract")=="canon-support-kinds.v2":
            from novel_forge.modules.canon_graph.grounding import SUPPORT_CLAIM_KINDS
            schema['properties']['claims']['items']['properties']['observed_kind']={'type':'string','enum':list(SUPPORT_CLAIM_KINDS)}
            schema_ref="schema:chapter-provider-output:canon_support:v2"
            if inputs.get("realization_comparison") is not None:
                from novel_forge.modules.canon_graph.realization_comparison import comparison_schema
                schema = comparison_schema(schema, inputs["realization_comparison"])
                schema_ref = "schema:chapter-provider-output:canon_support:v3"
        if stage.startswith("quality_") and inputs.get("quality_applicability_contract")=="quality-host-applicability.v1":
            from novel_forge.modules.chapter_quality_authority.applicability_contract import bind_quality_applicability_schema
            schema=bind_quality_applicability_schema(schema,inputs["quality_context"]["creative_baseline"],stage.removeprefix("quality_"))
            schema_ref=f"schema:chapter-provider-output:{stage}:v5"
        if stage.startswith("quality_") and prompt_contract_version in {"v12", "v13", "v15"}:
            from novel_forge.modules.canon_graph.source_spans import bind_quality_applicability_spans
            table = inputs.get("source_span_table") or {}
            if table.get("contract_version") != "literal-source-spans.v1":
                raise KernelError("QUALITY_SOURCE_SPAN_INVALID", "Current Quality requires its exact host candidate spans")
            schema = bind_quality_applicability_spans(schema, table)
            schema_ref = f"schema:chapter-provider-output:{stage}:v6"
        if stage == "canon_extraction" and prompt_contract_version in {"v12", "v13", "v15"}:
            from novel_forge.modules.canon_graph.source_spans import (
                span_output_schema, constrain_transition_preconditions, constrain_planned_character_results,
            )
            table = inputs.get("source_span_table") or {}
            if table.get("contract_version") != "literal-source-spans.v1":
                raise KernelError("CANON_SOURCE_TEXT_REQUIRED", "Current Canon requires its exact host span table")
            schema = chapter_provider_output_schema(stage, causal_batch=causal_batch, work_requirements=True)
            schema = constrain_transition_preconditions(schema, inputs["accepted_transition_baselines"])
            schema = span_output_schema(schema, table, compact=True, span_pattern=True)
            schema = constrain_planned_character_results(schema, inputs["canonical_transition_results"])
            schema = {"$schema": schema["$schema"], "type": "object", "additionalProperties": False,
                "properties": {"payload_json": {"type": "string", "minLength": 2}}, "required": ["payload_json"],
                "x-host-payload-schema": schema}
            schema_ref = "schema:chapter-provider-output:canon_extraction:v30"
        if current_review:
            from novel_forge.modules.review.repair_scope import repair_schema
            def bind_repair(value):
                if isinstance(value, dict):
                    properties = value.get("properties", {})
                    if {"judgment_kind", "revision_goal", "evidence"}.issubset(properties):
                        properties["repair"] = {"anyOf": [repair_schema(), {"type": "null"}]}
                        value["required"] = [*value["required"], "repair"]
                    for item in list(value.values()):
                        bind_repair(item)
                elif isinstance(value, list):
                    for item in value:
                        bind_repair(item)
            bind_repair(schema)
            schema_ref += ":repair-scope-v1"
        return schema, schema_ref

    def bind(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: Mapping[str, Any],
        external_effect_id: str,
    ) -> ChapterExecutionBinding:
        stage = str(request_payload.get("stage") or "")
        if capability != f"model.{stage}" or stage not in self.routes:
            raise ExternalEffectAdapterError(
                "Chapter gateway capability or stage is unsupported", request_sent=False
            )
        metadata = request_payload.get("_production_execution")
        if not isinstance(metadata, Mapping):
            raise ExternalEffectAdapterError(
                "Chapter gateway execution metadata is missing", request_sent=False
            )
        operation_id = str(
            metadata.get("operation_id") or request_payload.get("operation_id") or ""
        )
        attempt_id = str(metadata.get("attempt_id") or "")
        project_id = str(metadata.get("project_id") or "")
        workspace_id = str(metadata.get("workspace_id") or "")
        book_id = str(metadata.get("book_id") or "")
        worker_id = str(metadata.get("worker_id") or "")
        try:
            fencing_token = int(metadata.get("fencing_token") or 0)
            chapter = int(metadata.get("chapter") or 0)
        except (TypeError, ValueError) as exc:
            raise ExternalEffectAdapterError(
                "Chapter gateway Attempt metadata is invalid", request_sent=False
            ) from exc
        if not all(
            (operation_id, attempt_id, project_id, workspace_id, book_id, worker_id)
        ):
            raise ExternalEffectAdapterError(
                "Chapter gateway Attempt metadata is incomplete", request_sent=False
            )
        graph = self._operation_graph(operation_id, project_id)
        route = self.routes[stage]
        if self.provider_router is not None and route.embedding_dimensions == 0:
            route, _routing_decision = self.provider_router.select_for_payload(route, request_payload)
        require_task_reasoning(
            route, task_scoped=stage in CONTEXT_MODEL_STAGES or (
                stage != "retrieval" and str(metadata.get("task_context_profile") or "") == "draft-context-profile-v4"
            ),
        )
        definition = default_capability_registry().resolve(
            chapter_stage_capability(stage)
        )
        target_scope = self._target_scope(
            metadata=metadata,
            project_id=project_id,
            book_id=book_id,
            chapter=chapter,
        )
        artifacts = self._artifacts(metadata)
        capability_runtime = metadata.get("capability_runtime")
        attempt_pack_snapshot: CapabilityPackAttemptSnapshot | None = None
        materialization_contract: Mapping[str, Any] | None = None
        if isinstance(capability_runtime, Mapping):
            runtime_kind = str(capability_runtime.get("runtime_kind") or "")
            snapshot_id = str(capability_runtime.get("snapshot_id") or "")
            snapshot_hash = str(capability_runtime.get("snapshot_hash") or "")
            if runtime_kind != "FROZEN_RETRIEVAL_PROJECTION_CONTRACT":
                attempt_pack_snapshot = self.pack_resolver.require_attempt_snapshot(
                    attempt_id=attempt_id,
                    snapshot_id=snapshot_id,
                    snapshot_hash=snapshot_hash,
                )
                if attempt_pack_snapshot.operation_id != operation_id:
                    raise KernelError(
                        "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                        "frozen Capability Snapshot belongs to another Operation",
                    )
            materialization_version_id = str(
                capability_runtime.get("materialization_asset_version_id") or ""
            )
            document = self.query.require(
                project_id=project_id,
                asset_version_id=materialization_version_id,
            )
            if (
                document.asset_type != "capability_materialization_manifest"
                or document.content_hash
                != str(capability_runtime.get("materialization_content_hash") or "")
            ):
                raise KernelError(
                    "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                    "ExternalEffect Capability materialization identity drifted",
                )
            frozen = document.content.get("contract", document.content)
            pack_identity_valid = (
                str(
                    (frozen.get("attempt_snapshot") or {}).get("snapshot_id")
                    if isinstance(frozen, Mapping)
                    and isinstance(frozen.get("attempt_snapshot"), Mapping)
                    else ""
                )
                == snapshot_id
            )
            domain_identity_valid = (
                runtime_kind == "FROZEN_RETRIEVAL_PROJECTION_CONTRACT"
                and isinstance(frozen, Mapping)
                and frozen.get("runtime_kind") == runtime_kind
                and str(frozen.get("operation_id") or "") == operation_id
                and str(frozen.get("attempt_id") or "") == attempt_id
            )
            materialization_identity_valid = (
                domain_identity_valid
                if runtime_kind == "FROZEN_RETRIEVAL_PROJECTION_CONTRACT"
                else pack_identity_valid
            )
            if (
                not isinstance(frozen, Mapping)
                or str(frozen.get("materialization_hash") or "")
                != str(capability_runtime.get("materialization_hash") or "")
                or not materialization_identity_valid
            ):
                raise KernelError(
                    "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                    "Capability materialization content differs from ExternalEffect",
                )
            materialization_contract = frozen
            materialization_pointer = ArtifactPointer(
                artifact_ref=f"asset-version:{document.asset_version_id}",
                asset_version_id=document.asset_version_id,
                artifact_type=document.asset_type,
                content_hash=document.content_hash,
                schema_version=str(
                    frozen.get("schema_version")
                    or "novelos.chapter_capability_materialization.v1"
                ),
                source_eligibility="NOT_SOURCE_DERIVED",
            )
            if all(
                item.asset_version_id != materialization_pointer.asset_version_id
                for item in artifacts
            ):
                artifacts = (*artifacts, materialization_pointer)
        elif self.pack_required:
            raise KernelError(
                "CHAPTER_CAPABILITY_PREFLIGHT_MISSING",
                "controlled Chapter execution cannot bypass Capability preflight",
            )
        pack_snapshot = (
            attempt_pack_snapshot.execution_snapshot
            if attempt_pack_snapshot is not None
            else None
        )
        domain_materialization = (
            materialization_contract is not None
            and materialization_contract.get("runtime_kind")
            == "FROZEN_RETRIEVAL_PROJECTION_CONTRACT"
        )
        context_ref = next(
            (
                item.artifact_ref
                for item in artifacts
                if item.artifact_type == "context_bundle"
                or (stage in CONTEXT_MODEL_STAGES and item.artifact_type == "chapter_memo")
                or (
                    domain_materialization
                    and item.artifact_type != "capability_materialization_manifest"
                )
            ),
            f"context:none:{operation_id}",
        )
        contract_instance = external_effect_id if stage == "agent_session" or stage in CONTEXT_MODEL_STAGES else stage
        token = _identity_token(
            f"{project_id}:{operation_id}:{attempt_id}:{contract_instance}"
        )
        route_ref = f"production_execution/routes/{token}"
        input_ref = f"production_execution/inputs/{token}"
        prompt_ref = f"production_execution/prompt_bundles/{token}"
        skill_ref = f"production_execution/skill_bundles/{token}"
        tool_ref = f"production_execution/tool_permissions/{token}"
        if pack_snapshot is None:
            context_policy_ref = (
                "context-policy:"
                + definition.capability_id.value.replace(".", "-")
                + ":v1"
            )
            context_policy_payload: dict[str, Any] = {}
            tool_policy_payload: dict[str, Any] = {}
            allowed_tools = ("model.provider.invoke",)
            denied_tools: tuple[str, ...] = ()
            prompt_version = route.prompt_version
            skill_version = route.skill_version
            system_instruction_hash = route.system_instruction_hash
            template_hash = route.template_hash
            skill_content_hash = route.skill_content_hash
            prompt_compiler_version = route.prompt_compiler_version
            context_maximum_tokens = 16000
            context_allowed_asset_types = (
                "book_plan",
                "volume_plan",
                "arc_plan",
                "chapter_group_plan",
                "chapter_plan",
                "context_bundle",
                "canon_snapshot",
                "canon_patch",
                "story_state_snapshot",
                "quality_profile",
                "reader_contract",
                "reader_state",
                "draft_chapter",
                "review_report",
                "revision_patch",
                "book_design",
                "planning_generation_candidate",
            )
            if domain_materialization:
                context_allowed_asset_types = tuple(
                    str(item.get("artifact_type") or "")
                    for item in materialization_contract.get("context_selection") or ()
                    if isinstance(item, Mapping)
                    and str(item.get("artifact_type") or "")
                )
        else:
            context_policy_ref = pack_snapshot.context_policy_ref
            context_policy_payload = json.loads(
                pack_snapshot.context_policy_payload_json
            )
            tool_policy_payload = json.loads(pack_snapshot.tool_policy_payload_json)
            allowed_tools, denied_tools = _stage_tool_permissions(
                tool_policy_payload, stage
            )
            prompt_version = pack_snapshot.prompt_bundle_ref
            skill_version = pack_snapshot.skill_version
            system_instruction_hash = pack_snapshot.prompt_system_instruction_hash
            template_hash = pack_snapshot.prompt_template_hash
            skill_content_hash = pack_snapshot.skill_content_hash
            prompt_compiler_version = pack_snapshot.prompt_compiler_version
            context_maximum_tokens = int(context_policy_payload.get("max_tokens") or 0)
            context_allowed_asset_types = tuple(
                str(value)
                for value in context_policy_payload.get("allowed_asset_types") or ()
            )
        context_policy_snapshot_ref = f"production_execution/context_policies/{token}"
        validation_policy_snapshot_ref = (
            f"production_execution/validation_policies/{token}"
        )
        commit_policy_snapshot_ref = f"production_execution/commit_policies/{token}"
        context_policy = ContextPolicy(
            policy_id=context_policy_snapshot_ref,
            policy_version="v1",
            maximum_tokens=context_maximum_tokens,
            allowed_asset_types=context_allowed_asset_types,
            compression_policy_ref="compression:chapter-authority:v1",
            source_policy_ref=definition.source_policy_ref,
        )
        source_policy = SourcePolicy(
            policy_id=definition.source_policy_ref,
            policy_version="v1",
            allowed_eligibility=(
                "PRODUCTION_ELIGIBLE",
                "NOT_SOURCE_DERIVED",
            ),
            allow_raw_reference_sources=False,
            requires_lineage=True,
            isolation_mode="ABSTRACT_ASSETS_ONLY",
        )
        provider_output_schema_ref = (
            str(
                (materialization_contract.get("output_schema") or {}).get("ref")
                if materialization_contract is not None
                and isinstance(materialization_contract.get("output_schema"), Mapping)
                else ""
            )
            or definition.output_schema_ref
        )
        validation_policy = ValidationPolicy(
            policy_id=definition.validation_policy_ref,
            policy_version="v1",
            structural_schema_ref=provider_output_schema_ref,
            semantic_validator_refs=(
                "validator:" + definition.capability_id.value.replace(".", "-") + ":v1",
            ),
            maximum_repair_attempts=2,
            requires_domain_validation=True,
        )
        commit_policy = CommitPolicy(
            policy_id=definition.commit_policy_ref,
            policy_version="v1",
            candidate_asset_type=(
                "screenplay_review_candidate"
                if stage == "screenplay_review"
                else "screenplay_candidate"
                if stage in {"screenplay_generate", "screenplay_revision"}
                else "generation_candidate"
                if stage == "draft"
                else "revision_candidate"
                if stage == "revision"
                else "canon_candidate"
                if stage == "canon_extraction"
                else "quality_judge_candidate"
                if stage.startswith("quality_")
                else "reader_outcome_candidate"
                if stage == "reader_outcome"
                else "narrative_semantic_evaluation_candidate"
                if stage == "narrative_semantic_evaluation"
                else "retrieval_embedding_candidate"
                if stage == "retrieval"
                else "review_candidate"
            ),
            requires_validation_manifest=True,
            requires_approval=True,
            activation_mode="DOMAIN_AUTHORITY_ONLY",
        )
        skill_bundle = SkillBundle(
            skill_bundle_id=skill_ref,
            skill_version=skill_version,
            domain=definition.domain.value,
            capability=definition.capability_id.value,
            skill_refs=(skill_version,),
            skill_content_hashes=(skill_content_hash,),
            tool_policy_ref=tool_ref,
            created_by_operation_id=operation_id,
        )
        prompt_bundle = PromptBundle(
            prompt_bundle_id=prompt_ref,
            prompt_version=prompt_version,
            domain=definition.domain.value,
            capability=definition.capability_id.value,
            system_instruction_hash=system_instruction_hash,
            template_hash=template_hash,
            input_schema_ref=definition.input_schema_ref,
            output_schema_ref=provider_output_schema_ref,
            skill_bundle_ref=skill_ref,
            context_policy_ref=context_policy_snapshot_ref,
            source_policy_ref=definition.source_policy_ref,
            compiler_version=prompt_compiler_version,
            created_by_operation_id=operation_id,
        )
        manifest = InputManifest(
            manifest_id=input_ref,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=project_id,
            book_id=book_id,
            target_scope=target_scope,
            context_bundle_ref=context_ref,
            prompt_bundle_ref=prompt_ref,
            skill_bundle_ref=skill_ref,
            context_bundle_version=next(
                (
                    item.asset_version_id
                    for item in artifacts
                    if item.artifact_type == "context_bundle"
                    or (stage in CONTEXT_MODEL_STAGES and item.artifact_type == "chapter_memo")
                ),
                f"context:none:{operation_id}",
            ),
            prompt_bundle_version=prompt_version,
            skill_bundle_version=skill_version,
            canon_snapshot_version=next(
                (
                    item.asset_version_id
                    for item in artifacts
                    if "canon" in item.artifact_type
                ),
                f"canon:none:{operation_id}",
            ),
            story_state_version=next(
                (
                    item.asset_version_id
                    for item in artifacts
                    if "story_state" in item.artifact_type
                ),
                f"story-state:none:{operation_id}",
            ),
            planning_version=next(
                (
                    item.asset_version_id
                    for item in artifacts
                    if item.artifact_type
                    in {
                        "chapter_plan",
                        "chapter_group_plan",
                        "arc_plan",
                        "volume_plan",
                        "book_plan",
                    }
                ),
                f"planning:none:{operation_id}",
            ),
            quality_profile_version=next(
                (
                    item.asset_version_id
                    for item in artifacts
                    if "quality_profile" in item.artifact_type
                ),
                f"quality-profile:none:{operation_id}",
            ),
            source_policy_ref=definition.source_policy_ref,
            source_eligibility="PRODUCTION_ELIGIBLE",
            canon_version_refs=tuple(
                item.artifact_ref for item in artifacts if "canon" in item.artifact_type
            ),
            arc_version_refs=tuple(
                item.artifact_ref for item in artifacts if "arc" in item.artifact_type
            ),
            input_artifacts=artifacts,
            read_set=tuple(item.artifact_ref for item in artifacts),
        )
        snapshot = RouteSnapshot(
            route_snapshot_id=route_ref,
            route_decision_id=str((capability_runtime or {}).get("routing_decision", {}).get("decision_id") or f"route-decision:{token}"),
            operation_id=operation_id,
            attempt_id=attempt_id,
            policy_id=route.route_policy.policy_id,
            policy_version=route.route_policy.policy_version,
            backend_id=route.model_profile.backend_id,
            backend_version=route.backend_version,
            runtime_host_id=route.runtime_host_id,
            auth_profile_ref=route.auth_profile_ref,
            model_profile_id=route.model_profile.profile_id,
            model_profile_version=route.model_profile.profile_version,
            model_profile_hash=route.model_profile.contract_hash,
            route_policy_hash=route.route_policy.contract_hash,
            model_provider=route.model_profile.model_provider,
            model_id=route.model_profile.model_id,
            requested_reasoning_effort=route.model_profile.reasoning_effort,
            reasoning_effort=route.model_profile.reasoning_effort,
            prompt_bundle_ref=prompt_ref,
            skill_bundle_ref=skill_ref,
            context_bundle_ref=context_ref,
            output_schema_ref=provider_output_schema_ref,
            release_sha=route.release_sha,
            fallback_policy_ref=route.route_policy.fallback_policy_ref,
            fallback_policy_version=(route.route_policy.fallback_policy_version),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=context_policy.policy_id,
            asset_type="execution_context_policy",
            contract={
                **context_policy.to_dict(),
                "governing_capability_pack_policy_ref": (
                    pack_snapshot.context_policy_ref
                    if pack_snapshot
                    else context_policy_ref
                ),
                "governing_capability_pack_policy_hash": (
                    pack_snapshot.context_policy_hash if pack_snapshot else ""
                ),
            },
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=source_policy.policy_id,
            asset_type="execution_source_policy",
            contract=source_policy.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=validation_policy_snapshot_ref,
            asset_type="execution_validation_policy",
            contract={
                **validation_policy.to_dict(),
                "runtime_snapshot_ref": validation_policy_snapshot_ref,
                "governing_capability_pack_policy_ref": (
                    pack_snapshot.evaluation_policy_ref if pack_snapshot else ""
                ),
                "governing_capability_pack_policy_hash": (
                    pack_snapshot.evaluation_policy_hash if pack_snapshot else ""
                ),
            },
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=commit_policy_snapshot_ref,
            asset_type="execution_commit_policy",
            contract={
                **commit_policy.to_dict(),
                "runtime_snapshot_ref": commit_policy_snapshot_ref,
                "governing_capability_policy_ref": definition.commit_policy_ref,
            },
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=tool_ref,
            asset_type="tool_permission_snapshot",
            contract={
                "tool_policy_id": tool_ref,
                "tool_policy_version": "v1",
                "allowed_tools": list(allowed_tools),
                "denied_tools": list(denied_tools),
                "direct_http": "FORBIDDEN",
                "direct_file": "FORBIDDEN",
                "direct_command": "FORBIDDEN",
                "direct_database": "FORBIDDEN",
                "direct_mcp": "FORBIDDEN",
                "gateway_required": True,
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "fencing_token": fencing_token,
                "governing_capability_pack_policy_ref": (
                    pack_snapshot.tool_policy_ref if pack_snapshot else ""
                ),
                "governing_capability_pack_policy_hash": (
                    pack_snapshot.tool_policy_hash if pack_snapshot else ""
                ),
            },
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=skill_ref,
            asset_type="skill_bundle",
            contract=skill_bundle.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=prompt_ref,
            asset_type="prompt_bundle",
            contract=prompt_bundle.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=(
                f"production_execution/model_profiles/"
                f"{route.model_profile.profile_id}/v{route.model_profile.profile_version}"
            ),
            asset_type="model_profile",
            contract=route.model_profile.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=(
                f"production_execution/fallback_policies/"
                f"{route.fallback_policy.policy_id}/"
                f"v{route.fallback_policy.policy_version}"
            ),
            asset_type="fallback_policy",
            contract=route.fallback_policy.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=(
                f"production_execution/route_policies/"
                f"{route.route_policy.policy_id}/v{route.route_policy.policy_version}"
            ),
            asset_type="route_policy",
            contract=route.route_policy.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=input_ref,
            asset_type="input_manifest",
            contract=manifest.to_dict(),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=route_ref,
            asset_type="route_snapshot",
            contract={
                **snapshot.to_dict(),
                "capability_pack_attempt_snapshot_id": (
                    attempt_pack_snapshot.snapshot_id if attempt_pack_snapshot else ""
                ),
                "capability_pack_attempt_snapshot_hash": (
                    attempt_pack_snapshot.snapshot_hash if attempt_pack_snapshot else ""
                ),
            },
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        budget_reservation_id = self._budget_reservation(external_effect_id, project_id)
        request = ExecutionRequest(
            execution_id=f"chapter-execution:{external_effect_id}",
            operation_id=operation_id,
            root_operation_id=graph["root_operation_id"],
            saga_id=graph["saga_id"],
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            target_scope=target_scope,
            domain=definition.domain.value,
            task_kind=graph["definition_name"],
            stage=stage,
            capability=definition.capability_id.value,
            importance_class="HIGH",
            risk_class=definition.risk_class.value,
            route_snapshot_id=route_ref,
            workspace_snapshot_ref=workspace_id,
            input_manifest_ref=input_ref,
            resource_claims=self._resource_claims(
                metadata=metadata,
                chapter=chapter,
                stage=stage,
            ),
            timeout_policy_ref=definition.timeout_policy_ref,
            budget_policy_ref=definition.budget_policy_ref,
            permission_policy_ref=definition.permission_policy_ref,
            validation_policy_ref=definition.validation_policy_ref,
            commit_policy_ref=definition.commit_policy_ref,
            stable_idempotency_key=stable_idempotency_key,
            origin_chain=self._origin_chain(graph=graph, stage=stage),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
            external_effect_id=external_effect_id,
            budget_reservation_id=budget_reservation_id,
        )
        return ChapterExecutionBinding(
            request,
            snapshot,
            manifest,
            attempt_pack_snapshot,
        )

    def _target_scope(
        self,
        *,
        metadata: Mapping[str, Any],
        project_id: str,
        book_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        if str(metadata.get("execution_binding_domain") or "") == (
            "retrieval_projection"
        ):
            source_asset_version_id = str(
                metadata.get("source_asset_version_id")
                or metadata.get("target_asset_version_id")
                or ""
            )
            if not source_asset_version_id:
                raise KernelError(
                    "RETRIEVAL_PROJECTION_SCOPE_MISSING",
                    "Retrieval projection requires a frozen source AssetVersion",
                )
            return {
                "scope_kind": "asset_version",
                "scope_id": source_asset_version_id,
                "project_id": project_id,
                "book_id": book_id,
                "asset_version_id": source_asset_version_id,
            }
        return {
            "scope_kind": "chapter",
            "scope_id": f"{book_id}:chapter:{chapter}",
            "project_id": project_id,
            "book_id": book_id,
            "chapter_number": chapter,
        }

    def _resource_claims(
        self,
        *,
        metadata: Mapping[str, Any],
        chapter: int,
        stage: str,
    ) -> tuple[str, ...]:
        if str(metadata.get("execution_binding_domain") or "") == (
            "retrieval_projection"
        ):
            source_asset_version_id = str(
                metadata.get("source_asset_version_id")
                or metadata.get("target_asset_version_id")
                or ""
            )
            if not source_asset_version_id:
                raise KernelError(
                    "RETRIEVAL_PROJECTION_SCOPE_MISSING",
                    "Retrieval projection requires a frozen source AssetVersion",
                )
            return (
                source_asset_version_id,
                f"stage:{stage}",
            )
        return (f"chapter:{chapter}", f"stage:{stage}")

    @staticmethod
    def _origin_chain(*, graph: Mapping[str, str], stage: str) -> tuple[str, ...]:
        del stage
        if graph["definition_name"].startswith("chapter.provider.sample."):
            return (graph["definition_name"],)
        return ("chapter.slice.run", graph["definition_name"])

    @staticmethod
    def _artifacts(metadata: Mapping[str, Any]) -> tuple[ArtifactPointer, ...]:
        values = metadata.get("input_artifacts")
        if not isinstance(values, list) or not values:
            raise ExternalEffectAdapterError(
                "Chapter gateway requires frozen input artifacts", request_sent=False
            )
        try:
            return tuple(ArtifactPointer.from_dict(dict(item)) for item in values)
        except (TypeError, ValueError) as exc:
            raise ExternalEffectAdapterError(
                "Chapter gateway input artifact identity is invalid", request_sent=False
            ) from exc

    def _operation_graph(self, operation_id: str, project_id: str) -> dict[str, str]:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT operation.definition_name, operation.definition_version,
                           operation.root_operation_id, saga.saga_id
                    FROM authority_operation AS operation
                    LEFT JOIN authority_saga AS saga
                      ON saga.root_operation_id = operation.root_operation_id
                     AND saga.project_id = operation.project_id
                    WHERE operation.operation_id = %s AND operation.project_id = %s
                    """,
                    [operation_id, project_id],
                )
                row = cursor.fetchone()
        if row is None or not row[3]:
            raise ExternalEffectAdapterError(
                "Chapter gateway operation has no Authority Saga", request_sent=False
            )
        from novel_forge.modules.command_kernel.routing_bootstrap import (
            chapter_sample_definition_supported,
        )

        from .definitions import (
            CHAPTER_DRAFT_DEFINITION_VERSION,
            CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
            CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS,
            CHAPTER_SLICE_DEFINITION_VERSION,
        )

        compatible = str(row[0]) in {
            node.definition_name for node in ChapterNode
        } and str(row[1]) in {
            CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
            *CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS,
            CHAPTER_SLICE_DEFINITION_VERSION,
        }
        compatible = compatible or (str(row[1]) == "3.10.0" and str(row[0]) in {node.definition_name for node in ChapterNode if node is not ChapterNode.PLAN})
        compatible = compatible or (
            str(row[0]) == ChapterNode.DRAFT.definition_name
            and str(row[1]) in {CHAPTER_DRAFT_DEFINITION_VERSION, "3.9.1"}
        )
        compatible = compatible or (str(row[0]) in {ChapterNode.REVIEW.definition_name, ChapterNode.REREVIEW.definition_name} and str(row[1]) == "3.9.3")
        compatible = compatible or (str(row[0]) in {n.definition_name for n in (ChapterNode.QUALITY_STRUCTURAL,ChapterNode.QUALITY_COMMERCIAL,ChapterNode.QUALITY_SOURCE_ORIGINALITY,ChapterNode.QUALITY_LONGFORM,ChapterNode.QUALITY_PLATFORM)} and str(row[1]) in {"3.9.9", "3.9.12"})
        compatible = compatible or (str(row[0]) == ChapterNode.CANON_PROPOSAL.definition_name and str(row[1])=="3.9.8")
        compatible = compatible or (str(row[0]) == ChapterNode.CANON_EXTRACTION.definition_name and str(row[1]) in {"3.9.5", "3.9.6", "3.9.7"})
        compatible = compatible or (str(row[0]) == ChapterNode.REVISION.definition_name and str(row[1]) == "3.9.4")
        if str(row[0]).startswith("chapter.") and not compatible and not chapter_sample_definition_supported(str(row[0]), str(row[1])):
            raise KernelError(
                "CHAPTER_EXECUTION_CONTRACT_REBUILD_REQUIRED",
                "unfinished legacy Chapter execution requires current prepared input; accepted history and confirmed receipts remain unchanged",
            )
        return {
            "definition_name": str(row[0]),
            "definition_version": str(row[1]),
            "root_operation_id": str(row[2]),
            "saga_id": str(row[3]),
        }

    def _resolve_pack_snapshot(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        operation_id: str,
        attempt_id: str,
        execution_fencing_token: int,
        worker_id: str,
        snapshot_creation_fencing_token: int,
        snapshot_creation_worker_id: str,
        stage: str,
        graph: Mapping[str, str],
        route: ChapterExecutionRoute,
    ) -> CapabilityPackAttemptSnapshot | None:
        sampling = graph["definition_name"].startswith("chapter.provider.sample.")
        if sampling and (not self.capability_pack_id or self.pack_environment != "validation"):
            raise KernelError("CHAPTER_SAMPLE_PACK_REQUIRED", "Chapter sampling requires its approved validation pack")
        if not self.capability_pack_id:
            return None
        from novel_forge.modules.command_kernel.routing_bootstrap import CHAPTER_REFERENCE_TASKS

        reference = sampling and stage in CHAPTER_REFERENCE_TASKS.values()
        from novel_forge.modules.command_kernel.routing_bootstrap import CHAPTER_REFERENCE_SAMPLE_VERSIONS

        reference_samples = reference and graph["definition_version"] in CHAPTER_REFERENCE_SAMPLE_VERSIONS
        workflow_ref = ("chapter_reference_sampling" if reference else "chapter_provider_sampling") + "@" + graph["definition_version"] if sampling else self.workflow_definition_ref
        from .definitions import (
            CHAPTER_COORDINATED_DEFINITION_VERSION,
            CHAPTER_MODEL_WORKFLOW_DEFINITION_ID,
            CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS,
        )

        if (
            not sampling
            and graph["definition_name"]
            in {node.definition_name for node in ChapterNode}
            and graph["definition_version"]
            in CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS | {CHAPTER_COORDINATED_DEFINITION_VERSION}
        ):
            workflow_ref = (
                f"{CHAPTER_MODEL_WORKFLOW_DEFINITION_ID}@{graph['definition_version']}"
            )
        pack_id = self.capability_pack_id + (".reference_samples" if reference_samples else ".reference_sampling" if reference else ".provider_sampling") if sampling else self.capability_pack_id
        try:
            return self.pack_resolver.freeze_attempt_snapshot(
                CapabilityPackResolutionRequest(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_id=book_id,
                    workflow_definition_ref=workflow_ref,
                    workflow_node_id="canon_proposal"
                    if stage == "canon_support"
                    else "context" if stage in CONTEXT_MODEL_STAGES else stage,
                    environment=self.pack_environment,
                    runtime_profile=self.pack_runtime_profile,
                    release_channel=self.pack_release_channel,
                    release_sha=route.release_sha,
                    operation_definition_ref=(
                        f"{graph['definition_name']}@{graph['definition_version']}"
                    ),
                    pack_id=pack_id,
                ),
                operation_id=operation_id,
                attempt_id=attempt_id,
                execution_fencing_token=execution_fencing_token,
                worker_id=worker_id,
                snapshot_creation_fencing_token=(snapshot_creation_fencing_token),
                snapshot_creation_worker_id=snapshot_creation_worker_id,
            )
        except KernelError as exc:
            if (
                exc.code
                in {
                    "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED",
                    "CAPABILITY_PACK_SCOPE_NOT_FOUND",
                }
                and not self.pack_required
                and not sampling
            ):
                return None
            raise

    def _materialize_selected_inputs(
        self,
        *,
        project_id: str,
        artifacts: tuple[ArtifactPointer, ...],
        reference_operation_id: str = "", reference_stage: str = "",
    ) -> list[dict[str, Any]]:
        reference_target = None
        if any(item.artifact_type == "chapter_provider_sample" for item in artifacts):
            from novel_forge.modules.chapter_quality_authority.reference_subject import require_chapter_sample_target
            from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork

            with AuthorityUnitOfWork(self.database_url) as uow:
                snapshot = load_bootstrap_authorization(uow.cursor, project_id=project_id, operation_id=reference_operation_id, check_expiry=False)
                uow.cursor.execute("SELECT command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s",
                                   [project_id, reference_operation_id])
                row = uow.cursor.fetchone()
                if snapshot is None or snapshot["authorization"]["purpose"] != "REFERENCE_EVALUATION" or not row or row[0].get("generator_operation_name") != reference_stage:
                    raise KernelError("CHAPTER_CAPABILITY_CONTEXT_INVALID", "sample inputs require the exact native reference evaluation grant")
                reference_target = require_chapter_sample_target(uow.cursor, project_id=project_id, payload=row[0])
        if any(item.artifact_type == "screenplay_provider_sample" for item in artifacts):
            from novel_forge.modules.book_followup_authority.screenplay_sampling import validate_screenplay_sample_origin
            from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork
            with AuthorityUnitOfWork(self.database_url) as uow:
                snapshot = load_bootstrap_authorization(uow.cursor, project_id=project_id, operation_id=reference_operation_id, check_expiry=False)
                uow.cursor.execute("SELECT command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, reference_operation_id])
                row = uow.cursor.fetchone()
                if not snapshot or not row or row[0].get("generator_operation_name") != reference_stage:
                    raise KernelError("SCREENPLAY_SAMPLE_INVALID", "Only the exact authorized native sample stage may consume a sample")
                reference_target = validate_screenplay_sample_origin(uow.cursor, project_id=project_id, payload=row[0])["upstream"]
        selected: list[dict[str, Any]] = []
        for pointer in artifacts:
            document = self.query.require(
                project_id=project_id,
                asset_version_id=pointer.asset_version_id,
            )
            reference_sample = (reference_target is not None and pointer.asset_version_id == reference_target["asset_version_id"]
                and pointer.content_hash == reference_target["content_hash"] and document.lifecycle == "ACTIVE" and document.eligibility == "INELIGIBLE")
            if (
                document.asset_type != pointer.artifact_type
                or document.content_hash != pointer.content_hash
                or (document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE", "NOT_SOURCE_DERIVED"} and not reference_sample)
                or document.governance != "CLEAR"
            ):
                raise KernelError(
                    "CHAPTER_CAPABILITY_CONTEXT_INVALID",
                    "frozen input Artifact differs from PostgreSQL Authority",
                )
            selected.append(
                {
                    **pointer.to_dict(),
                    "content": document.content,
                    "eligibility": document.eligibility,
                    "governance": document.governance,
                }
            )
        return selected

    def _budget_reservation(self, external_effect_id: str, project_id: str) -> str:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT reservation_id
                    FROM authority_budget_reservation
                    WHERE external_effect_id = %s AND project_id = %s
                      AND status IN ('RESERVED', 'HELD_UNKNOWN', 'SETTLED')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    [external_effect_id, project_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise ExternalEffectAdapterError(
                "Chapter gateway requires an approved budget reservation",
                request_sent=False,
            )
        return str(row[0])

    def _ensure_contract(
        self,
        *,
        operation_id: str,
        project_id: str,
        logical_ref: str,
        asset_type: str,
        contract: dict[str, Any],
        trace_id: str,
        correlation_id: str,
    ) -> AuthorityAssetDocument:
        try:
            existing = self.query.require(
                project_id=project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            frozen = existing.content.get("contract", existing.content)
            if frozen != contract or existing.asset_type != asset_type:
                raise KernelError(
                    "EXECUTION_CONTRACT_FROZEN_CONFLICT",
                    "an immutable execution contract changed inside one identity",
                )
            return existing
        token = _identity_token(f"{project_id}:{logical_ref}")
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"production-execution-contract:{token}",
                asset_type=asset_type,
                schema_version="production-execution-contract.v1",
                logical_ref=logical_ref,
                category="production_execution_contracts",
                output_key=f"production_execution.contract.{asset_type}.{token}",
                role="execution_contract",
                content={"contract": contract},
                qualification_policy="production-execution-contract-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )


class PostgresRetrievalProjectionExecutionContractBinder(
    PostgresChapterExecutionContractBinder
):
    """INVARIANT: retrieval is not a Chapter Saga node and must not borrow its Capability Pack."""

    def __init__(
        self,
        database_url: str,
        routes: Mapping[str, ChapterExecutionRoute],
        *,
        frozen_artifacts: Mapping[str, Any],
    ) -> None:
        super().__init__(
            database_url,
            routes,
            capability_pack_id="",
            pack_required=False,
        )
        required = {"system_instruction", "prompt_template", "skill"}
        if set(frozen_artifacts) != required:
            raise ValueError("retrieval projection artifacts are incomplete")
        self.frozen_artifacts = dict(frozen_artifacts)

    def freeze_before_external_effect(
        self,
        *,
        capability: str,
        request_payload: Mapping[str, Any],
        snapshot_fencing_token: int,
        snapshot_worker_id: str,
    ) -> ChapterCapabilityPreflight | None:
        stage = str(request_payload.get("stage") or "")
        metadata = request_payload.get("_production_execution")
        if capability != "model.retrieval" or stage != "retrieval":
            raise KernelError(
                "RETRIEVAL_PROJECTION_CAPABILITY_INVALID",
                "projection binder only accepts model.retrieval",
            )
        if not isinstance(metadata, Mapping):
            raise KernelError(
                "RETRIEVAL_PROJECTION_CONTRACT_MISSING",
                "projection Provider metadata is missing",
            )
        operation_id = str(metadata.get("operation_id") or "")
        attempt_id = str(metadata.get("attempt_id") or "")
        project_id = str(metadata.get("project_id") or "")
        execution_fencing_token = int(metadata.get("fencing_token") or 0)
        if (
            not all(
                (
                    operation_id,
                    attempt_id,
                    project_id,
                    snapshot_worker_id,
                )
            )
            or execution_fencing_token <= 0
            or snapshot_fencing_token <= 0
        ):
            raise KernelError(
                "RETRIEVAL_PROJECTION_CONTRACT_MISSING",
                "projection Attempt/Fence identity is incomplete",
            )
        pointers = self._artifacts(metadata)
        selected_inputs = self._materialize_selected_inputs(
            project_id=project_id,
            artifacts=pointers,
        )
        source_asset_version_id = str(metadata.get("source_asset_version_id") or "")
        source_content_hash = str(metadata.get("source_content_hash") or "")
        if (
            len(selected_inputs) != 1
            or not source_asset_version_id
            or not source_content_hash
            or selected_inputs[0]["asset_version_id"] != source_asset_version_id
            or selected_inputs[0]["content_hash"] != source_content_hash
        ):
            raise KernelError(
                "RETRIEVAL_PROJECTION_SCOPE_MISSING",
                "projection contract requires its exact frozen source AssetVersion",
            )
        system = self.frozen_artifacts["system_instruction"]
        template = self.frozen_artifacts["prompt_template"]
        skill = self.frozen_artifacts["skill"]
        route = self.routes[stage]
        if (
            system.content_hash != route.system_instruction_hash
            or template.content_hash != route.template_hash
            or skill.content_hash != route.skill_content_hash
        ):
            raise KernelError(
                "RETRIEVAL_PROJECTION_ROUTE_ARTIFACT_DRIFT",
                "projection Provider artifacts differ from the frozen route",
            )
        output_schema = chapter_provider_output_schema(stage)
        output_schema_ref = chapter_provider_output_schema_ref(stage)
        embedding_output_contract = _retrieval_embedding_output_contract(route)
        contract_without_hash: dict[str, Any] = {
            "schema_version": "novelos.provider_capability_materialization.v1",
            "runtime_kind": "FROZEN_RETRIEVAL_PROJECTION_CONTRACT",
            "stage": stage,
            "capability_requirement": capability,
            "operation_id": operation_id,
            "attempt_id": attempt_id,
            "execution_fencing_token": execution_fencing_token,
            # INVARIANT: A recovery worker's newer fence authorizes takeover but must not
            # alter the original Provider execution semantics.
            "snapshot_creation_fencing_token": execution_fencing_token,
            "source_asset_version_id": source_asset_version_id,
            "source_content_hash": source_content_hash,
            "route_identity": {
                "release_sha": route.release_sha,
                "embedding_model": route.model_profile.model_id,
                "embedding_dimensions": route.embedding_dimensions,
                "model_profile_hash": route.model_profile.contract_hash,
                "route_policy_hash": route.route_policy.contract_hash,
                "system_instruction_hash": system.content_hash,
                "template_hash": template.content_hash,
                "skill_content_hash": skill.content_hash,
            },
            "pack_artifacts": {
                "system_instruction": system.to_dict(),
                "prompt_template": template.to_dict(),
                "skill": skill.to_dict(),
            },
            "context_selection": selected_inputs,
            "knowledge_selection": [],
            "tool_permissions": {
                "default": "DENY",
                "allowed": ["model.provider.invoke"],
                "denied": [],
                "invoked": ["model.provider.invoke"],
                "governing_policy_ref": "permission:retrieval-embed:v1",
                "governing_policy_hash": canonical_hash(
                    {
                        "default": "DENY",
                        "allowed": ["model.provider.invoke"],
                        "stage": stage,
                    }
                ),
            },
            "output_schema": {
                "ref": output_schema_ref,
                "content_hash": canonical_hash(output_schema),
                "content": output_schema,
            },
            "embedding_output_contract": embedding_output_contract,
        }
        materialization_hash = canonical_hash(contract_without_hash)
        contract = {
            **contract_without_hash,
            "materialization_hash": materialization_hash,
        }
        token = _identity_token(
            f"{project_id}:{operation_id}:{attempt_id}:{stage}:projection-capability"
        )
        document = self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=f"production_execution/capability_materializations/{token}",
            asset_type="capability_materialization_manifest",
            contract=contract,
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        pointer = ArtifactPointer(
            artifact_ref=f"asset-version:{document.asset_version_id}",
            asset_version_id=document.asset_version_id,
            artifact_type=document.asset_type,
            content_hash=document.content_hash,
            schema_version="novelos.provider_capability_materialization.v1",
            source_eligibility="NOT_SOURCE_DERIVED",
        )
        provider_inputs = request_payload.get("input")
        if not isinstance(provider_inputs, Mapping):
            raise KernelError(
                "RETRIEVAL_PROJECTION_INPUT_INVALID",
                "projection Provider admission requires frozen inputs",
            )
        prompt, prompt_evidence = _materialize_production_codex_prompt(
            target_scope={
                "scope_kind": "asset_version",
                "scope_id": source_asset_version_id,
                "project_id": project_id,
                "asset_version_id": source_asset_version_id,
            },
            stage=stage,
            inputs=provider_inputs,
            materialization=contract,
        )
        stable_idempotency_key = str(
            request_payload.get("stable_idempotency_key") or ""
        )
        timeout_seconds = int(metadata.get("provider_request_timeout_seconds") or 0)
        output_reserve = int(request_payload.get("max_output_tokens") or 0)
        if not stable_idempotency_key or timeout_seconds <= 0 or output_reserve <= 0:
            raise KernelError(
                "PROVIDER_ADMISSION_INPUT_INCOMPLETE",
                "projection admission identity or limits are incomplete",
            )
        route_identity = ":".join(
            (
                stage,
                route.model_profile.model_provider,
                route.model_profile.model_id,
                route.release_sha,
                source_content_hash,
            )
        )
        envelope = ProviderRequestEnvelope(
            provider=route.model_profile.model_provider,
            model=route.model_profile.model_id,
            protocol=provider_request_protocol(route.model_profile.model_provider),
            input_text=prompt,
            max_output_tokens=output_reserve,
            timeout_seconds=_provider_process_timeout_seconds(
                timeout_seconds, max_attempts=1 if stage == "longform_prose_review" else 2
            ),
            stable_idempotency_key=stable_idempotency_key,
        )
        token_contract = _provider_token_contract(
            route,
            route_identity=route_identity,
            output_reserve=output_reserve,
            execution_token_limit=int(
                metadata.get("provider_token_limit") or route.model_context_limit
            ),
        )
        admission = prepare_provider_admission(
            envelope,
            token_contract,
            input_component_hashes=dict(
                dict(prompt_evidence.get("provider_view") or {}).get("component_hashes")
                or {}
            ),
            complete_request_coverage=(
                "system_runtime_instructions",
                "prompt_template",
                "skill_instructions",
                "tool_policy_and_schemas",
                "structured_output_schema",
                "context_bundle",
                "request_envelope_and_framing",
                "output_reserve",
                "safety_margin",
            ),
        )
        if admission.status != "ADMITTED":
            raise KernelError("PROVIDER_TOKEN_ADMISSION_REJECTED", admission.reason)
        admission_contract = {
            "schema_version": "novelos.provider_request_admission.v1",
            "provider_request_identity": envelope.to_identity_dict(),
            "provider_admission": admission.to_dict(),
            "prompt_materialization": prompt_evidence,
            "capability_materialization_asset_version_id": document.asset_version_id,
            "capability_materialization_content_hash": document.content_hash,
        }
        admission_document = self._ensure_contract(
            operation_id=operation_id,
            project_id=project_id,
            logical_ref=f"production_execution/provider_admissions/{token}",
            asset_type="provider_request_admission_manifest",
            contract=admission_contract,
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
        )
        admission_pointer = ArtifactPointer(
            artifact_ref=f"asset-version:{admission_document.asset_version_id}",
            asset_version_id=admission_document.asset_version_id,
            artifact_type=admission_document.asset_type,
            content_hash=admission_document.content_hash,
            schema_version="novelos.provider_request_admission.v1",
            source_eligibility="NOT_SOURCE_DERIVED",
        )
        return ChapterCapabilityPreflight(
            attempt_snapshot=None,
            materialization=None,
            materialization_artifact=pointer,
            provider_admission_artifact=admission_pointer,
            effect_binding={
                "runtime_kind": "FROZEN_RETRIEVAL_PROJECTION_CONTRACT",
                "materialization_asset_version_id": document.asset_version_id,
                "materialization_content_hash": document.content_hash,
                "materialization_hash": materialization_hash,
                "source_asset_version_id": source_asset_version_id,
                "source_content_hash": source_content_hash,
                "prompt_system_instruction_hash": system.content_hash,
                "prompt_template_hash": template.content_hash,
                "skill_content_hash": skill.content_hash,
                "allowed_tools": ["model.provider.invoke"],
                "output_schema_ref": output_schema_ref,
                "output_schema_hash": canonical_hash(output_schema),
                "embedding_output_contract": embedding_output_contract,
                "provider_admission_asset_version_id": (
                    admission_document.asset_version_id
                ),
                "provider_admission_content_hash": admission_document.content_hash,
                "provider_request_envelope_hash": envelope.envelope_hash,
                "token_accounting_contract": token_contract.to_dict(),
                "provider_admission": admission.to_dict(),
            },
        )


class ChapterFixtureResponseFactory(Protocol):
    def __call__(self, stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]: ...


class ExternalEffectExecutionSessionStore:
    """INVARIANT: Transient gateway cache; PostgreSQL ExternalEffect remains recovery authority.

    Every referenced manifest is copied into the ExternalEffect receipt before the
    adapter returns.  A new worker deliberately starts with an empty cache and
    reconstructs the same request from PostgreSQL using the Provider idempotency key
    or persistent local execution directory.
    """

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}
        self._evidence: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def put_record(self, record: ExecutionRecord) -> None:
        with self._lock:
            existing = self._records.get(record.request.execution_id)
            if existing is not None:
                if existing.request.contract_hash != record.request.contract_hash:
                    raise ValueError("duplicate execution ID has a different request")
                return
            self._records[record.request.execution_id] = record

    def save_record(self, record: ExecutionRecord) -> None:
        with self._lock:
            existing = self._records.get(record.request.execution_id)
            if (
                existing is not None
                and existing.request.contract_hash != record.request.contract_hash
            ):
                raise ValueError("duplicate execution ID has a different request")
            self._records[record.request.execution_id] = record

    def get_record(self, execution_id: str) -> ExecutionRecord:
        try:
            return self._records[execution_id]
        except KeyError as exc:
            raise ValueError(
                f"execution session is not available: {execution_id}"
            ) from exc

    def find_record(self, execution_id: str) -> ExecutionRecord | None:
        return self._records.get(execution_id)

    def put_evidence(
        self, kind: str, execution_id: str, payload: Mapping[str, Any]
    ) -> str:
        frozen = json.loads(_canonical(payload))
        digest = hashlib.sha256(_canonical(frozen).encode("utf-8")).hexdigest()
        ref = f"external-effect-session:{kind}:{execution_id}:{digest}"
        with self._lock:
            prior = self._evidence.get(ref)
            if prior is not None and prior != frozen:
                raise ValueError("execution session evidence hash collision")
            self._evidence[ref] = frozen
        return ref

    def read_evidence(self, ref: str) -> dict[str, Any]:
        try:
            return dict(self._evidence[ref])
        except KeyError as exc:
            raise ValueError(
                f"execution session evidence is not available: {ref}"
            ) from exc


def _fixture_knowledge_checks(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "knowledge_card_asset_version_id": item["knowledge_card_asset_version_id"],
            "status": "NOT_USED", "evidence": None,
            "reason": "Scripted transport does not demonstrate semantic knowledge use.",
            "conditions_checked": [], "exceptions_checked": [], "issue_codes": [],
        }
        for item in inputs.get("knowledge_review_targets", [])
    ]


def default_chapter_fixture_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:

    if stage == "longform_prose_review":
        from novel_forge.modules.book_followup_authority.prose_review import PROSE_DIMENSIONS
        return {"schema_version": "longform-prose-review.v1", "manifest_digest": inputs["manifest_digest"], "window_id": inputs["window_id"], "reviewed_dimensions": list(PROSE_DIMENSIONS), "findings": []}
    if stage == "memo":
        intent = inputs["execution_intent"]
        scenes = intent.get("scene_plans") or []
        mission = intent.get("chapter_mission") or {}
        participants = sorted(
            {str(value) for scene in scenes for value in scene.get("participants", [])}
        )
        return {
            "execution_strategy": "Make the locked goal demand an observable costly choice: "
            + str(intent.get("chapter_objective")),
            "tension_strategy": "Let resistance make the safe option progressively unavailable.",
            "composition_strategy": "Carry each scene consequence into the next scene's obstacle.",
            "creative_guidance": {
                "chapter_goal": str(
                    intent.get("chapter_objective") or "Advance the frozen mission"
                ),
                "pov": "Follow the focal participant's available perception; do not disclose hidden causes.",
                "voice": "Concrete language shaped by the frozen character and narrator voice constraints.",
                "emotional_turn": "Move from guarded certainty to the cost of committing in public.",
                "reader_promise": "Show what the choice costs, while preserving unresolved questions.",
                "ending_change": "The choice removes a safe option and changes the next scene's pressure.",
                "character_choices": [
                    {
                        "character_id": who,
                        "choice": "Act despite the loss of a safe exit",
                        "motivation": "Pursue the locked scene goal under pressure",
                        "cost": "Lose the option to retreat unnoticed",
                    }
                    for who in participants
                ],
                "constraints": [
                    "No new Canon; no knowledge beyond the frozen Scene boundaries."
                ],
            },
            "scene_directives": [
                {
                    "scene_id": scene["scene_id"],
                    "directive": "Dramatize the goal through resistance: "
                    + str(scene.get("goal") or "advance the mission"),
                    "conflict_progression": "An attempted solution creates a visible cost.",
                    "information_release": "Reveal only the information assigned to this Scene's audience.",
                    "emotional_change": "Confidence narrows into a committed choice.",
                    "transition": "Carry the consequence into the following Scene, without recap.",
                }
                for scene in scenes
            ],
            "retrieval_queries": ["accepted consequences relevant to the locked goal"],
            "obligation_actions": [],
            "arc_actions": [
                {"arc_plan_version_id": arc["arc_plan_version_id"], "action": "ADVANCE"}
                for arc in mission.get("arc_contributions", [])
            ],
            "stop_conditions": [
                "Stop on a frozen constraint conflict; do not invent a fact to resolve it."
            ],
        }
    if stage in CONTEXT_MODEL_STAGES:
        task = dict(inputs.get("context_compression_task") or {})
        if stage == "context_compress":
            return {"selected_unit_ids": list(task.get("required_unit_ids") or ())}
        selected = set(task.get("selected_unit_ids") or ())
        missing = sorted(set(task.get("required_unit_ids") or ()) - selected)
        return {
            "supported": True, "coverage_complete": not missing,
            "missing_unit_ids": missing, "distorted_unit_ids": [],
            "reason": "Scripted fixture checks required extract identities only; semantic fidelity is not proven.",
        }
    if stage == "retrieval_query_expansion":
        coverage = dict(inputs.get("coverage") or {})
        contract = dict(inputs.get("coverage_contract") or {})
        selectors = dict(contract.get("selectors") or {})
        boundary = int(
            dict(inputs.get("accepted_boundary") or {}).get("accepted_through_chapter")
            or 0
        )
        prefixes = {
            "fact_ids": "fact",
            "historical_reference_ids": "history",
            "relationship_ids": "relationship",
            "arc_plan_version_ids": "arc",
            "obligation_ids": "obligation",
        }
        selector_for = {
            "fact_ids": "entity_ids",
            "historical_reference_ids": "entity_ids",
            "relationship_ids": "relationship_ids",
            "arc_plan_version_ids": "arc_plan_version_ids",
            "obligation_ids": "obligation_ids",
        }
        queries = []
        for dimension, identities in dict(coverage.get("missing") or {}).items():
            for identity in identities or ():
                selector_dimension = selector_for.get(str(dimension), "entity_ids")
                allowed = [
                    str(item)
                    for item in selectors.get(selector_dimension) or ()
                    if str(item)
                ]
                queries.append(
                    {
                        "query_id": f"fixture-query:{len(queries) + 1}",
                        "text": str(identity),
                        "reason": "fixture exercises the governed missing-evidence protocol",
                        "targets": [f"{prefixes[str(dimension)]}:{identity}"],
                        "selectors": (
                            {selector_dimension: allowed[:1]} if allowed else {}
                        ),
                        "temporal_range": {
                            "from_chapter": 0,
                            "to_chapter": boundary,
                        },
                    }
                )
                if len(queries) == 4:
                    break
            if len(queries) == 4:
                break
        if not queries:
            raise ValueError("fixture query expansion requires a deterministic gap")
        return {
            "contract_version": "retrieval-expansion-plan-v1",
            "queries": queries,
        }
    if stage == "retrieval":
        texts = inputs.get("texts")
        if not isinstance(texts, list) or not texts:
            raise ValueError("fixture retrieval embedding requires texts")
        dimensions = 8
        vectors = []
        for text_value in texts:
            digest = hashlib.sha256(str(text_value).encode()).digest()
            vectors.append(
                [round((digest[index] / 127.5) - 1.0, 8) for index in range(dimensions)]
            )
        return {
            "vectors": vectors,
            "embedding_model": "deterministic-fixture-embedding-v1",
            "embedding_dimensions": dimensions,
        }
    if stage == "agent_session":
        observations = inputs.get("observations")
        tools = inputs.get("tools")
        if not observations and isinstance(tools, list) and tools:
            first = tools[0] if isinstance(tools[0], Mapping) else {}
            return {
                "message": "Inspect the frozen accepted boundary.",
                "action": "TOOL_CALL",
                "tool_call": {
                    "tool_name": str(first.get("tool_name") or ""),
                    "arguments": {"payload_json": '{"scope":"accepted_boundary"}'},
                    "reason": "ground the proposal in accepted facts",
                },
                "final_response": None,
            }
        return {
            "message": "Return an authority-bounded proposal.",
            "action": "FINAL",
            "tool_call": None,
            "final_response": {
                "payload_json": _canonical(
                    {
                        "candidate_only": True,
                        "instruction": str(inputs.get("instruction") or ""),
                    }
                )
            },
        }
    if stage == "draft":
        plan = inputs.get("plan") if isinstance(inputs.get("plan"), Mapping) else {}
        text = f"{plan.get('premise') or 'The chapter objective advances.'} The choice is public, and the irreversible cost is witnessed."
        contract = inputs.get("realization_contract") or {}
        artifacts = [
            {
                "slot_id": slot["slot_id"],
                "text": text
                if index == 0
                else f"The scene carries its {slot['capability'].lower()} contribution forward.",
                "used_fact_ids": [],
                **({"character_source_uses": []} if contract.get("contract_version") == "scene-realization-composition.v3" else {}),
            }
            for index, slot in enumerate(contract.get("slots", []))
        ]
        return {
            "text": "\n\n".join(item["text"] for item in artifacts)
            if artifacts
            else text,
            "scene_artifacts": artifacts,
        }
    if stage == "review":
        from novel_forge.modules.review.craft import fixture_craft_checks
        text = str(
            (inputs.get("draft") or {}).get("text") or "The choice has no visible cost."
        )
        return {
            "score": 72,
            "resolution_checks": [],
            "knowledge_checks": _fixture_knowledge_checks(inputs),
            **({"craft_checks": fixture_craft_checks(inputs)} if fixture_craft_checks(inputs) else {}),
            "issues": [
                {
                    "code": "COST_NOT_CONCRETE",
                    "severity": "blocking",
                    "message": "Make the irreversible cost concrete in the scene.",
                    "category": "CAUSALITY",
                    "judgment_kind": "SEMANTIC_CONFLICT",
                    "evidence": {"start": 0, "end": len(text), "quote": text},
                    "violated_constraint": "A decisive choice must have a visible cost.",
                    "revision_goal": "Show the protagonist giving up a concrete safe option.",
                    "preserve": ["The frozen choice and all unrelated Scene actions."],
                    "acceptance_criteria": [
                        "The text identifies the lost option and the consequence."
                    ],
                }
            ],
        }
    if stage == "revision":
        draft = inputs.get("draft") if isinstance(inputs.get("draft"), Mapping) else {}
        suffix = "The protagonist gives up the only safe route home before the witnesses leave."
        artifacts = json.loads(json.dumps(draft.get("scene_artifacts", [])))
        if artifacts:
            artifacts[-1]["text"] += " " + suffix
        from .realization_composition import serialize_realization
        text = (
            serialize_realization(artifacts, draft.get("scene_separators"))
            if artifacts
            else f"{draft.get('text') or 'The choice is made.'} {suffix}"
        )
        return {
            "text": text,
            "scene_artifacts": artifacts,
            "resolved_issue_codes": ["COST_NOT_CONCRETE"],
            **({"edits": [{"start": 0, "end": len(str(draft.get("text") or "")), "quote": str(draft.get("text") or ""), "replacement": text, "issue_codes": ["COST_NOT_CONCRETE"]}]} if (inputs.get("review") or {}).get("craft_targets") else {}),
        }
    if stage == "rereview":
        from novel_forge.modules.review.craft import fixture_craft_checks, craft_review_targets, PRESERVATION_DIMENSIONS
        text = str(
            (inputs.get("revision") or {}).get("text")
            or "The choice costs a safe route home."
        )
        return {
            "score": 90,
            "issues": [],
            **({"craft_preservation_checks": [{"dimension": dimension, "status": "UNCERTAIN", "evidence": {"start": 0, "end": len(text), "quote": text}, "reason": "Fixture cannot establish semantic preservation."} for dimension in PRESERVATION_DIMENSIONS]} if craft_review_targets(inputs.get("revision") or {}) else {}),
            "knowledge_checks": _fixture_knowledge_checks(inputs),
            **({"craft_checks": fixture_craft_checks(inputs)} if fixture_craft_checks(inputs) else {}),
            "resolution_checks": [
                {
                    "code": issue["code"],
                    "status": "SATISFIED",
                    "preservation": "PRESERVED",
                    "evidence": {"start": 0, "end": len(text), "quote": text},
                    "reason": "Scripted transport verifies the explicit cost sentence; not model quality evidence.",
                }
                for issue in (inputs.get("review") or {}).get("issues", [])
            ],
        }
    if stage == "canon_support":
        return {
            "coverage": "COMPLETE",
            "no_change_supported": not inputs.get("claims"),
            **({"realization_comparisons": [{"planned_event_id": item["planned_event_id"],
                "causality": "EQUIVALENT", "required_state": "EQUIVALENT", "knowledge_boundary": "EQUIVALENT",
                "reason": "Scripted contract evidence only; no literary or semantic proof.",
                "evidence_quotes": [inputs["realization_comparison"]["evidence_quotes"][0]]}
                for item in inputs["realization_comparison"]["events"]]} if inputs.get("realization_comparison") is not None else {}),
            "claims": [
                {
                    "claim_id": item["claim"]["grounded_claim_id"],
                    "assessment": "SUPPORTED",
                    "observed_kind": item["claim"]["claim_kind"],
                    "reason": "Scripted transport evidence only; no model entailment proof.",
                }
                for item in inputs.get("claims", [])
            ],
        }
    if stage == "canon_extraction":
        revision = (
            inputs.get("revision")
            if isinstance(inputs.get("revision"), Mapping)
            else {}
        )
        text = str(
            revision.get("text") or "The protagonist gives up the safe route home."
        )
        evidence_end = max(1, min(len(text), 40))
        expectations = (
            inputs.get("execution_expectations")
            if isinstance(inputs.get("execution_expectations"), Mapping)
            else {}
        )
        character_arc_changes = []
        for transition in expectations.get("required_state_transitions") or ():
            if (
                not isinstance(transition, Mapping)
                or str(transition.get("state_kind") or "") != "character_arc"
            ):
                continue
            character_id, _, arc_suffix = str(
                transition.get("entity_key") or ""
            ).partition(":")
            change = {
                "summary": "The planned character trajectory advances.",
                "effective_from_chapter": int(revision.get("chapter") or 1),
                "character_id": character_id,
                "arc_id": f"character-arc:{arc_suffix}",
                "state": str(transition.get("to_state") or ""),
                "evidence_start": 0,
                "evidence_end": evidence_end,
                "confidence": 0.99,
                "impact_type": "character_arc_progression",
            }
            if int(revision.get("chapter") or 1) > 1:
                change["from_state"] = str(transition.get("from_state") or "")
            character_arc_changes.append(change)
        disclosure_events = [
            {
                "summary": "The planned reader-facing disclosure is presented.",
                "effective_from_chapter": int(revision.get("chapter") or 1),
                "disclosure_id": str(item.get("disclosure_id") or ""),
                "fact_id": str(item.get("fact_id") or ""),
                "audience": str(item.get("audience") or ""),
                "disclosure_mode": str(item.get("mode") or ""),
                "presentation_channel": str(item.get("presentation_channel") or ""),
                "evidence_start": 0,
                "evidence_end": evidence_end,
                "confidence": 0.99,
                "impact_type": "reader_disclosure",
            }
            for item in expectations.get("disclosures") or ()
            if isinstance(item, Mapping)
            and str(item.get("mode") or "").upper() != "WITHHOLD"
        ]
        empty_fields = {
            "character_state_changes": [],
            "relationship_changes": [],
            "timeline_events": [],
            "foreshadow_changes": [],
            "promise_changes": [],
            "obligation_changes": [],
            "reward_changes": [],
            "world_rule_usages": [],
            "world_state_changes": [],
            "faction_state_changes": [],
            "location_state_changes": [],
            "consequence_changes": [],
            "conflict_state_changes": [],
            "power_state_changes": [],
            "plot_thread_changes": [],
            "resource_state_changes": [],
            "narrative_pattern_fingerprints": [],
            "theme_movements": [],
            "antagonist_pressure_changes": [],
            "character_knowledge_changes": [],
            "character_belief_changes": [],
            "character_arc_changes": character_arc_changes,
            "arc_state_changes": [],
            "disclosure_events": disclosure_events,
            "arc_evidence": [],
            "realization_evidence": [
                {
                    "planned_event_id": str(event.get("event_id") or ""),
                    "observed_event_id": (f"observed:{event.get('event_id')}"),
                    "observation_status": "OBSERVED",
                    "accepted_prose_evidence": [
                        {
                            "start": 0,
                            "end": evidence_end,
                            "summary": "scripted fixture prose realizes the frozen event",
                        }
                    ],
                    "observed_consequence": str(
                        event.get("consequence") or "the planned consequence occurs"
                    ),
                    "observed_action": str(event.get("action") or "planned action"),
                    "observed_decision": (None if event.get("feature_status") and event.get("decision") is None else str(event.get("decision") or "planned decision")),
                    "observed_cause_event_ids": list(event.get("causes") or ()),
                    "observed_disclosures": list(event.get("disclosures") or ()),
                    "observed_state_deltas": [
                        dict(delta)
                        for delta in event.get("state_deltas") or ()
                        if isinstance(delta, Mapping)
                    ],
                    "observed_state_event_ids": [
                        str(delta.get("entity_id") or "")
                        for delta in event.get("state_deltas") or ()
                        if isinstance(delta, Mapping)
                        and str(delta.get("entity_id") or "")
                    ],
                }
                for event in (expectations.get("narrative_realization") or {}).get(
                    "events"
                )
                or ()
                if isinstance(event, Mapping)
            ],
        }
        result = {
            "canon_facts": [
                {
                    "subject": "protagonist",
                    "predicate": "gave_up",
                    "object": "safe_route_home",
                    "evidence_start": 0,
                    "evidence_end": evidence_end,
                    "confidence": 0.99,
                }
            ],
            **empty_fields,
        }
        result.update({"extraction_status": "EXTRACTED", "no_change_reason": ""})
        for field, values in result.items():
            if not isinstance(values, list):
                continue
            for claim in values:
                if field in {"arc_evidence", "realization_evidence"}:
                    if claim.get("observation_status") != "OBSERVED":
                        continue
                    claim.update({"evidence_start": 0, "evidence_end": evidence_end})
                claim["evidence_quote"] = text[
                    int(claim["evidence_start"]) : int(claim["evidence_end"])
                ]
                claim["claim_kind"] = {
                    "arc_evidence": "NARRATIVE_OBSERVATION",
                    "realization_evidence": "NARRATIVE_OBSERVATION",
                    "disclosure_events": "READER_DISCLOSURE",
                    "character_knowledge_changes": "KNOWLEDGE_ACQUISITION",
                    "character_belief_changes": "BELIEF",
                }.get(field, "OBJECTIVE_EVENT")
        return result
    if stage.startswith("quality_"):
        dimensions = inputs.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise ValueError("fixture quality route requires dimensions")
        return {
            "dimensions": [
                {
                    "dimension": str(dimension),
                    "gate_status": "PASSED",
                    "score": 90,
                    "evidence_locations": [{"start": 0, "end": 24}],
                    "confidence": 0.9,
                    "issue_codes": [],
                    "revision_strategies": [],
                }
                for dimension in dimensions
            ]
        }
    if stage == "reader_outcome":
        assets = (
            inputs.get("assets") if isinstance(inputs.get("assets"), Mapping) else {}
        )
        source = next(iter(assets), "final_draft")
        return {
            "reader_state": {
                "continue_intent": 0.88,
                "curiosity": 0.86,
                "satisfaction": 0.81,
                "confusion": 0.18,
                "trust": 0.84,
                "character_attachment": 0.82,
                "antagonist_pressure": 0.76,
                "promise_expectation": 0.79,
                "payoff_satisfaction": 0.77,
                "drop_risk": 0.12,
                "repetition_fatigue": 0.14,
            },
            "evidence": [
                {
                    "asset_version_id": source,
                    "location": "chapter",
                    "claim": "fixture reader outcome evidence",
                }
            ],
        }
    raise ValueError(f"unsupported fixture stage: {stage}")


def _provider_process_timeout_seconds(
    external_effect_timeout_seconds: int, *, max_attempts: int = 1
) -> int:
    """COMPATIBILITY: Preserve the declared timeout in frozen request evidence."""
    if external_effect_timeout_seconds <= 0 or max_attempts <= 0:
        raise ValueError("declared Effect timeout and attempts must be positive")
    return external_effect_timeout_seconds



class PostgresProductionExecutionPayloadResolver:
    def __init__(
        self,
        database_url: str,
        *,
        fixture_response_factory: ChapterFixtureResponseFactory | None = None,
        source_object_reader: Any | None = None,
        working_directory: str | Path = ".",
        command: tuple[str, ...] = (),
    ) -> None:
        self.database_url = database_url
        self.fixture_response_factory = fixture_response_factory
        self.source_object_reader = source_object_reader
        self.working_directory = str(working_directory)
        self.command = tuple(command)

    def resolve(
        self, request: ExecutionRequest, admission: Any
    ) -> ResolvedExecutionPayload:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT request_payload, request_timeout_seconds, request_hash,
                           max_attempts
                    FROM authority_external_effect
                    WHERE external_effect_id = %s AND operation_id = %s AND project_id = %s
                    """,
                    [
                        request.external_effect_id,
                        request.operation_id,
                        request.project_id,
                    ],
                )
                row = cursor.fetchone()
        if row is None:
            raise ValueError("ExecutionRequest has no frozen PostgreSQL ExternalEffect")
        payload = dict(row[0] or {})
        stage = str(payload.get("stage") or "")
        stored_inputs = payload.get("input")
        if stage != request.stage or not isinstance(stored_inputs, Mapping):
            raise ValueError("frozen Production ExternalEffect payload changed")
        source_metadata = payload.get("_source_intelligence")
        source_execution = isinstance(source_metadata, Mapping)
        from novel_forge.modules.source_authority.corpus_consumption import (
            require_corpus_consumption,
        )

        require_corpus_consumption(
            self.database_url,
            request.project_id,
            stored_inputs,
            source_analysis=source_execution,
            operation_id=request.operation_id,
        )
        inputs = (
            self.resolve_source_intelligence_inputs(
                project_id=request.project_id,
                stored_inputs=stored_inputs,
                metadata=source_metadata,
            )
            if source_execution
            else stored_inputs
        )
        actual_manifest = (
            source_metadata.get("actual_input_manifest") if source_execution else None
        )
        if actual_manifest and actual_manifest["materialized_input_hash"] != (
            "sha256:" + hashlib.sha256(_canonical(inputs).encode("utf-8")).hexdigest()
        ):
            raise KernelError(
                "SOURCE_ACTUAL_INPUT_DRIFT",
                "final source input differs from durable prepared evidence",
            )
        if self.fixture_response_factory is None:
            metadata = payload.get("_production_execution")
            capability_runtime = (
                metadata.get("capability_runtime")
                if isinstance(metadata, Mapping)
                else None
            )
            if not isinstance(capability_runtime, Mapping):
                raise KernelError(
                    "CHAPTER_CAPABILITY_PREFLIGHT_MISSING",
                    "Provider payload cannot bypass frozen Capability materialization",
                )
            materialization_version_id = str(
                capability_runtime.get("materialization_asset_version_id") or ""
            )
            materialization_document = AuthorityAssetQuery(self.database_url).require(
                project_id=request.project_id,
                asset_version_id=materialization_version_id,
            )
            if (
                materialization_document.asset_type
                != "capability_materialization_manifest"
                or materialization_document.content_hash
                != str(capability_runtime.get("materialization_content_hash") or "")
            ):
                raise KernelError(
                    "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                    "Provider materialization differs from frozen ExternalEffect",
                )
            materialization = materialization_document.content.get(
                "contract", materialization_document.content
            )
            if not isinstance(materialization, Mapping) or str(
                materialization.get("materialization_hash") or ""
            ) != str(capability_runtime.get("materialization_hash") or ""):
                raise KernelError(
                    "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                    "Provider materialization hash differs from frozen ExternalEffect",
                )
            if source_execution:
                input_text, prompt_evidence = _materialize_source_intelligence_prompt(
                    request=request,
                    stage=stage,
                    inputs=inputs,
                    materialization=materialization,
                )
            else:
                input_text, prompt_evidence = _materialize_production_codex_prompt(
                    request=request,
                    stage=stage,
                    inputs=inputs,
                    materialization=materialization,
                )
            output_schema = materialization.get("output_schema")
            if not isinstance(output_schema, Mapping) or not isinstance(
                output_schema.get("content"), Mapping
            ):
                raise KernelError(
                    "CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID",
                    "frozen Capability materialization has no output schema content",
                )
            tool_permissions = materialization.get("tool_permissions")
            if not isinstance(tool_permissions, Mapping):
                raise KernelError(
                    "CHAPTER_CAPABILITY_TOOL_POLICY_INVALID",
                    "frozen Capability materialization has no Tool policy",
                )
            admission_version_id = str(
                capability_runtime.get("provider_admission_asset_version_id") or ""
            )
            admission_document = AuthorityAssetQuery(self.database_url).require(
                project_id=request.project_id,
                asset_version_id=admission_version_id,
            )
            if (
                admission_document.asset_type != "provider_request_admission_manifest"
                or admission_document.content_hash
                != str(capability_runtime.get("provider_admission_content_hash") or "")
            ):
                raise KernelError(
                    "PROVIDER_ADMISSION_IDENTITY_DRIFT",
                    "Provider admission differs from frozen ExternalEffect",
                )
            frozen_admission = admission_document.content.get(
                "contract", admission_document.content
            )
            if not isinstance(frozen_admission, Mapping):
                raise KernelError(
                    "PROVIDER_ADMISSION_IDENTITY_DRIFT",
                    "Provider admission contract is malformed",
                )
            try:
                envelope = ProviderRequestEnvelope.from_identity_dict(
                    dict(frozen_admission.get("provider_request_identity") or {}),
                    input_text=input_text,
                )
            except ValueError as exc:
                raise KernelError("PROVIDER_REQUEST_IDENTITY_DRIFT", str(exc)) from exc
            admission_receipt = ProviderAdmissionReceipt.from_dict(
                dict(frozen_admission.get("provider_admission") or {})
            )
            try:
                verify_provider_admission(envelope, admission_receipt)
            except ValueError as exc:
                raise KernelError(
                    "PROVIDER_ADMISSION_IDENTITY_DRIFT", str(exc)
                ) from exc
            if (
                envelope.input_text != input_text
                or envelope.envelope_hash
                != str(capability_runtime.get("provider_request_envelope_hash") or "")
                or envelope.provider != admission.route_snapshot.model_provider
                or envelope.model != admission.route_snapshot.model_id
            ):
                raise KernelError(
                    "PROVIDER_REQUEST_IDENTITY_DRIFT",
                    "materialized Provider request differs from admitted envelope",
                )
            resolved_payload = envelope.to_dict()
            prompt_evidence = {
                **dict(prompt_evidence),
                "provider_admission_asset_version_id": admission_version_id,
                "provider_admission": admission_receipt.to_dict(),
                "provider_request_envelope_hash": envelope.envelope_hash,
            }
        else:
            input_text = _canonical({"stage": stage, "input": inputs})
            output_schema = None
            fixture_schema_ref = (
                chapter_provider_output_schema_ref(
                    stage, legacy_contract=not ((payload.get("_production_execution") or {}).get("creative_requirements_contract") == "work-requirements.v1"),
                    work_requirements=(payload.get("_production_execution") or {}).get("creative_requirements_contract") == "work-requirements.v1",
                )
                if stage == "canon_extraction" else admission.route_snapshot.output_schema_ref
            )
            tool_permissions = {}
            prompt_evidence = None
            resolved_payload = {
                "result": self.fixture_response_factory(stage, inputs),
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "cost": {"amount": "0", "currency": "USD"},
                "capability_pack_fixture_marker": (
                    admission.route_snapshot.prompt_bundle_ref
                ),
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            }
        external_effect_timeout_seconds = int(row[1] or 30)
        return ResolvedExecutionPayload(
            request_payload=resolved_payload,
            input_text=input_text,
            working_directory=self.working_directory,
            timeout_seconds=_provider_process_timeout_seconds(
                external_effect_timeout_seconds,
                max_attempts=int(row[3] or 1),
            ),
            output_schema_version=(
                str(output_schema.get("ref") or "")
                if isinstance(output_schema, Mapping)
                else fixture_schema_ref
            ),
            command=self.command,
            output_schema=(
                dict(output_schema["content"])
                if isinstance(output_schema, Mapping)
                and isinstance(output_schema.get("content"), Mapping)
                else None
            ),
            capability_evidence=prompt_evidence,
            allowed_tools=tuple(
                str(item) for item in tool_permissions.get("allowed") or ()
            ),
            denied_tools=tuple(
                str(item) for item in tool_permissions.get("denied") or ()
            ),
        )

    def resolve_source_intelligence_inputs(
        self,
        *,
        project_id: str,
        stored_inputs: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        kind = str(metadata.get("kind") or "")
        reading_context = stored_inputs.get("reading_context") or {}
        failed_output = reading_context.get("failed_output")
        if failed_output:
            runtime = get_database_runtime(self.database_url)
            with runtime.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT CASE WHEN e.reconciliation<>'{}'::jsonb THEN e.reconciliation ELSE d.evidence END
                    FROM authority_external_effect e
                    JOIN LATERAL (SELECT evidence FROM authority_external_effect_dispatch
                      WHERE external_effect_id=e.external_effect_id AND status='SUCCEEDED'
                      ORDER BY generation DESC LIMIT 1) d ON true
                    WHERE e.project_id=%s AND e.external_effect_id=%s AND e.status='SUCCEEDED'
                      AND e.request_payload->'input'->'reading_context'->>'reading_identity'=%s""",
                    [
                        project_id,
                        failed_output["effect_id"],
                        failed_output["reading_identity"],
                    ],
                )
                row = cursor.fetchone()
            if not row or "result" not in row[0]:
                raise KernelError(
                    "SOURCE_DIAGNOSTIC_RECEIPT_UNAVAILABLE",
                    "directed repair requires the exact returned output",
                )
            raw_result = row[0]["result"]
            if diagnostic_ref := raw_result.get("_rejected_provider_output"):
                from novel_forge.modules.production_execution.recovery import (
                    AuthorityExecutionRecoveryStore,
                )

                diagnostic = AuthorityExecutionRecoveryStore(
                    self.database_url, project_id=project_id
                ).read_evidence(diagnostic_ref)
                path = Path(diagnostic["result_path"])
                if diagnostic["byte_size"] > 262144:
                    raise KernelError(
                        "SOURCE_DIAGNOSTIC_INPUT_BOUND",
                        "rejected result exceeds the directed repair input bound",
                    )
                with path.open("rb") as source:
                    content = source.read(262145)
                if (
                    len(content) != diagnostic["byte_size"]
                    or "sha256:" + hashlib.sha256(content).hexdigest()
                    != diagnostic["result_sha256"]
                ):
                    raise KernelError(
                        "SOURCE_DIAGNOSTIC_INPUT_DRIFT",
                        "rejected result differs from its durable receipt",
                    )
                raw_result = content.decode("utf-8", errors="strict")
            stored_inputs = {
                **stored_inputs,
                "reading_context": {
                    **reading_context,
                    "failed_output": {**failed_output, "raw_result": raw_result},
                },
            }
        if kind == "classification":
            if self.source_object_reader is None:
                raise KernelError(
                    "SOURCE_CLASSIFICATION_OBJECT_READER_REQUIRED",
                    "Source classification requires a governed object-store reader",
                )
            evidence = stored_inputs.get("classification_evidence")
            if not isinstance(evidence, Mapping):
                raise ValueError("Source classification Evidence is missing")
            samples = evidence.get("samples")
            if not isinstance(samples, list) or not samples:
                raise ValueError("Source classification sample manifest is missing")
            identities = [
                str(item.get("source_chunk_asset_version_id") or "")
                for item in samples
                if isinstance(item, Mapping)
            ]
            runtime = get_database_runtime(self.database_url)
            with runtime.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT chunk.asset_version_id, chunk.content_hash,
                               chunk.byte_size, blob.actual_object_key,
                               blob.actual_hash, blob.actual_size, blob.status
                        FROM authority_source_chunk AS chunk
                        JOIN authority_blob AS blob ON blob.blob_id=chunk.blob_id
                        WHERE chunk.project_id=%s
                          AND chunk.asset_version_id=ANY(%s)
                        """,
                        [project_id, identities],
                    )
                    rows = cursor.fetchall()
            by_id = {str(row[0]): row for row in rows}
            if len(by_id) != len(set(identities)):
                raise ValueError("Source classification sample is outside the project")
            resolved_samples: list[dict[str, Any]] = []
            for sample in samples:
                if not isinstance(sample, Mapping):
                    raise ValueError("Source classification sample pointer is invalid")
                identity = str(sample.get("source_chunk_asset_version_id") or "")
                row = by_id[identity]
                if str(row[6]) != "AVAILABLE":
                    raise ValueError("Source classification Blob is unavailable")
                content = self.source_object_reader.read(
                    object_key=str(row[3]),
                    expected_hash=str(row[4]),
                    expected_size=int(row[5]),
                )
                if str(row[1]) != str(row[4]) or int(row[2]) != len(content):
                    raise ValueError("Source classification chunk identity drifted")
                start = int(sample.get("byte_start") or 0)
                end = int(sample.get("byte_end") or 0)
                bounded = content[start:end]
                digest = "sha256:" + hashlib.sha256(bounded).hexdigest()
                if (
                    start < 0
                    or end <= start
                    or end > len(content)
                    or digest != str(sample.get("sample_hash") or "")
                ):
                    raise ValueError("Source classification sample hash drifted")
                resolved_samples.append(
                    {
                        "sample_id": str(sample.get("sample_id") or ""),
                        "source_chunk_asset_version_id": identity,
                        "position": str(sample.get("position") or ""),
                        "sample_hash": digest,
                        "content": bounded.decode("utf-8", errors="strict"),
                    }
                )
            return {
                **dict(stored_inputs),
                "classification_samples": resolved_samples,
            }
        if kind in {"deconstruction", "deconstruction_compound"}:
            if self.source_object_reader is None:
                raise KernelError(
                    "SOURCE_ANALYSIS_OBJECT_READER_REQUIRED",
                    "Source analysis requires a governed object-store reader",
                )
            raw_segments = stored_inputs.get("source_segments")
            if not isinstance(raw_segments, list) or not raw_segments:
                raise ValueError("Source analysis segment manifest is missing")
            identities = [
                str(item.get("source_chunk_asset_version_id") or "")
                for item in raw_segments
                if isinstance(item, Mapping)
            ]
            runtime = get_database_runtime(self.database_url)
            with runtime.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT chunk.asset_version_id, chunk.content_hash,
                               chunk.byte_size, blob.actual_object_key,
                               blob.actual_hash, blob.actual_size, blob.status
                        FROM authority_source_chunk AS chunk
                        JOIN authority_blob AS blob ON blob.blob_id=chunk.blob_id
                        WHERE chunk.project_id=%s
                          AND chunk.asset_version_id=ANY(%s)
                        """,
                        [project_id, identities],
                    )
                    rows = cursor.fetchall()
            by_id = {str(row[0]): row for row in rows}
            if len(by_id) != len(set(identities)):
                raise ValueError("Source analysis segment is outside the project")
            resolved_segments: list[dict[str, Any]] = []
            for item in raw_segments:
                if not isinstance(item, Mapping):
                    raise ValueError("Source analysis segment pointer is invalid")
                identity = str(item.get("source_chunk_asset_version_id") or "")
                row = by_id[identity]
                if (
                    str(row[6]) != "AVAILABLE"
                    or str(item.get("content_hash") or "") != str(row[1])
                    or int(item.get("byte_size") or -1) != int(row[2])
                ):
                    raise ValueError("Source analysis segment identity drifted")
                content = self.source_object_reader.read(
                    object_key=str(row[3]),
                    expected_hash=str(row[4]),
                    expected_size=int(row[5]),
                )
                if stored_inputs.get("observation_boundary"):
                    from novel_forge.modules.source_authority.observation import observation_boundary
                    boundary = observation_boundary(stored_inputs["observation_boundary"])
                    spans = [span for span in boundary.spans if span.chunk_asset_version_id == identity]
                    if not spans:
                        raise KernelError("SOURCE_OBSERVATION_SCOPE", "chunk has no allowed source slice")
                    for span in spans:
                        sliced = content[span.byte_start:span.byte_end]
                        if "sha256:" + hashlib.sha256(sliced).hexdigest() != span.content_hash:
                            raise KernelError("SOURCE_OBSERVATION_HASH", "observation slice drifted")
                        resolved_segments.append({"source_chunk_asset_version_id": identity, "content_hash": span.content_hash, "byte_size": len(sliced), "content": sliced.decode("utf-8", errors="strict")})
                else:
                    resolved_segments.append({"source_chunk_asset_version_id": identity, "content_hash": str(row[1]), "byte_size": int(row[2]), "content": content.decode("utf-8", errors="strict")})
            if stored_inputs.get("reference_semantic_task"):
                from .context_compression_provider import context_compression_task_view
                frozen = stored_inputs["reference_semantic_task"]
                view = context_compression_task_view(frozen["stage"], {"context_compression_task": frozen["task"]})
                allowed_text = "\n\n".join(segment["content"] for segment in resolved_segments)
                if any(unit["text"] not in allowed_text for unit in view["units"]):
                    raise KernelError("SOURCE_OBSERVATION_COMPRESSOR_SCOPE", "semantic source unit exceeds observed text")
                return {**dict(stored_inputs), "source_segments": [{key: value for key, value in segment.items() if key != "content"} for segment in resolved_segments], "reference_semantic_task": view}
            extract = stored_inputs.get("reference_context_extract")
            if extract is not None:
                if not isinstance(extract, list) or not extract:
                    raise KernelError("SOURCE_OBSERVATION_EXTRACT", "reference Context extract must be nonempty")
                allowed = "\n\n".join(segment["content"] for segment in resolved_segments)
                if any(not isinstance(value, str) or value not in allowed for value in extract):
                    raise KernelError("SOURCE_OBSERVATION_EXTRACT", "extract differs from authorized source units")
                return {**dict(stored_inputs), "source_segments": [{key: value for key, value in segment.items() if key != "content"} for segment in resolved_segments]}
            return {**dict(stored_inputs), "source_segments": resolved_segments}
        if kind == "deconstruction_aggregate":
            manifest = stored_inputs.get("input_observations")
            if not isinstance(manifest, list) or not manifest:
                raise ValueError("Source aggregate Observation manifest is missing")
            identities = [
                str(item.get("asset_version_id") or "")
                for item in manifest
                if isinstance(item, Mapping)
            ]
            documents = {
                identity: AuthorityAssetQuery(self.database_url).require(
                    project_id=project_id,
                    asset_version_id=identity,
                )
                for identity in identities
            }
            resolved_observations: list[dict[str, Any]] = []
            for item in manifest:
                if not isinstance(item, Mapping):
                    raise ValueError("Source aggregate Observation pointer is invalid")
                identity = str(item.get("asset_version_id") or "")
                document = documents.get(identity)
                observation = (
                    document.content.get("observation")
                    if document is not None
                    and document.asset_type == "source_deconstruction_observation"
                    else None
                )
                if (
                    document is None
                    or document.content_hash != str(item.get("content_hash") or "")
                    or not isinstance(observation, Mapping)
                    or "sha256:"
                    + hashlib.sha256(
                        _canonical(observation).encode("utf-8")
                    ).hexdigest()
                    != str(item.get("observation_hash") or "")
                ):
                    raise ValueError("Source aggregate Observation identity drifted")
                resolved_observations.append(
                    {
                        "asset_version_id": identity,
                        "content_hash": document.content_hash,
                        "observation": dict(observation),
                    }
                )
            return {
                **dict(stored_inputs),
                "input_observations": resolved_observations,
            }
        if kind == "mkaos":
            observation_id = str(
                stored_inputs.get("observation_asset_version_id") or ""
            )
            document = AuthorityAssetQuery(self.database_url).require(
                project_id=project_id,
                asset_version_id=observation_id,
            )
            if document.asset_type != "source_deconstruction_observation":
                raise ValueError("MKAOS execution input is not an Observation")
            observation = document.content.get("observation")
            if not isinstance(observation, Mapping):
                raise ValueError("MKAOS Observation payload is unavailable")
            return {**dict(stored_inputs), "observation": dict(observation)}
        raise ValueError("unsupported Source intelligence execution kind")


def _required_language_from_context(value: Any) -> str | None:

    languages: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            contract = item.get("language_contract")
            if isinstance(contract, Mapping):
                required = str(contract.get("required_language") or "").strip()
                if required:
                    languages.add(required)
            if item.get("key") == "language_contract":
                nested = item.get("value")
                if isinstance(nested, Mapping):
                    required = str(nested.get("required_language") or "").strip()
                    if required:
                        languages.add(required)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    if len(languages) > 1:
        raise KernelError(
            "CHAPTER_LANGUAGE_CONTRACT_CONFLICT",
            "governed Context contains conflicting reader-facing languages",
        )
    return next(iter(languages), None)


def _language_semantic_contract(required_language: str | None) -> str:
    if not required_language:
        return ""
    if required_language != "zh-CN":
        raise KernelError(
            "CHAPTER_LANGUAGE_CONTRACT_UNSUPPORTED",
            f"unsupported governed reader-facing language: {required_language}",
        )
    return (
        "The governed reader-facing language is zh-CN. Write reader-facing titles, "
        "synopses, chapter prose, revision prose, and explanatory review evidence "
        "primarily in Simplified Chinese. Keep schema keys and stable identifiers "
        "unchanged, and do not translate identifiers."
    )


def _stage_semantic_contract_v3(
    stage: str, *, required_language: str | None = None,
    embedding_output_contract: Mapping[str, Any] | None = None,
) -> str:
    if stage in {"model_reference_evaluate", "model_reference_adjudicate"}:
        return (
            "Evaluate only the frozen subject against the author baseline and named dimension. "
            "State uncertainty when evidence is insufficient. Return the exact declared JSON schema. "
            "Do not claim human judgment, author approval, production eligibility, or literary proof. "
            + ("Do not infer or access peer judgments. " if stage == "model_reference_evaluate" else
               "Use only the two frozen blind reports supplied in source_evaluations; resolve their disagreements independently. ")
        )
    if stage == "memo":
        return (
            "Suggest concrete creative guidance for the frozen Chapter mission and Scene roles. "
            "A choice, cost, emotional turn, reward, reversal, or hook is applicable only when "
            "the chapter function, author intent, Arc or due obligation calls for it. Use null "
            "for an inapplicable optional guidance field and [] when no character choice is needed. "
            "Provide at least one task-relevant retrieval query for accepted history. "
            "Accepted facts and explicit author constraints remain binding. Do not claim an "
            "outcome occurred or that the Memo changed the active Plan."
        )
    if stage in {"draft", "revision"}:
        instruction = (
            "Return one JSON result with scene_artifacts in exact frozen Slot order. "
            "Each Slot has one reader-facing prose text and only the in-scope used_fact_ids. "
            "Do not return a second chapter text, Markdown, self-check, change log, or "
            "approval claim. The host joins Slot text and binds identities and receipts. "
            "Respect actor, POV, source and knowledge boundaries, accepted facts, explicit "
            "author constraints, and due obligations. Use optional craft techniques only "
            "where relevant to this Chapter."
        )
        if stage == "revision":
            instruction += (
                " Preserve every unaffected Slot and the chapter's narrative scale. "
                "Address evidenced blocking issues; report a resolved code only when "
                "the revised prose actually addresses it. For targeted edits, quote the "
                "exact old passage; the host locates it and enforces frozen ranges."
            )
        return _bind_language_contract(instruction, required_language)
    if stage in {"review", "rereview"}:
        instruction = (
            "Judge this exact candidate against applicable author, accepted-state, "
            "knowledge, Scene and due-obligation constraints. For evidence return a "
            "literal quote only; the host locates Unicode spans against the frozen "
            "candidate and rejects missing or ambiguous quotes. A quote alone is not "
            "semantic support. Separate conflicts, uncertainty, and taste; do not "
            "penalize omitted cost, growth, reversal, reward or hook techniques when "
            "they are not required by this Chapter. Never claim human approval."
        )
        if stage == "rereview":
            instruction += " Check every prior diagnosis against revised prose and preserve successful content."
        return _bind_language_contract(instruction, required_language)
    if stage.startswith("quality_"):
        return _stage_semantic_contract(stage, required_language=required_language).replace(
            "Every returned dimension must include at least one concrete evidence location, including policy-compliance dimensions.",
            "PASSED and FAILED dimensions require literal candidate-prose quotes. "
            "For other statuses return [] when no prose supports a location. Explain "
            "policy and context support in claim. The host binds Unicode positions "
            "and candidate identity; a literal match alone is not semantic support."
        )
    if stage == "canon_extraction":
        contract = _stage_semantic_contract(stage, required_language=required_language)
        contract = contract.replace(
            "FULFILLED requires a typed payoff_evidence object.",
            "FULFILLED requires a supported payoff: null for a prose payoff that the host binds, or a typed accepted prerequisite for CAUSAL_DEBT.",
        )
        contract = contract.replace("accepted revision visibly executes", "selected candidate visibly executes")
        contract = contract.replace(
            "For a prose payoff use the literal "
            "asset_version_id=$FINAL_CANDIDATE and event_id=$CURRENT_CLAIM; the Authority "
            "binds these to this final candidate and grounded claim. Never invent an "
            "AssetVersion or accepted event identity.",
            "For a non-CAUSAL_DEBT prose payoff set payoff_evidence to null; the host "
            "binds this candidate and grounded claim. For CAUSAL_DEBT select only an "
            "exact accepted prerequisite source and event from governed context."
        )
        contract = contract.replace(
            "An OBSERVED Arc item must include at least one resolution_evidence string "
            "encoded as chars:<start>-<end>:<summary>, where start and end are valid "
            "Unicode code-point offsets into final_candidate; otherwise return zero ",
            "An OBSERVED Arc item must include at least one unique literal final-candidate "
            "prose quote in resolution_evidence; the host binds its location. Otherwise return zero ",
        )
        return contract.replace(
            "accepted_prose_evidence list with valid final_candidate Unicode code-point "
            "offsets plus the observed event identity",
            "accepted_prose_evidence list with unique literal final-candidate quotes "
            "plus the observed event identity",
        )
    return _stage_semantic_contract(
        stage, required_language=required_language,
        embedding_output_contract=embedding_output_contract,
    )


def _stage_semantic_contract(
    stage: str,
    *,
    required_language: str | None = None,
    embedding_output_contract: Mapping[str, Any] | None = None,
) -> str:
    if stage in {"model_reference_evaluate", "model_reference_adjudicate"}:
        return _stage_semantic_contract_v3(stage, required_language=required_language)
    if stage == "retrieval":
        if embedding_output_contract is None:
            return (
                "Return exactly one numeric embedding vector for each frozen input "
                "text, in the same order. Return the actual embedding model identity "
                "and vector dimensions. Do not add facts, summarize, retrieve, or "
                "mutate Authority state."
            )
        expected_model = str(embedding_output_contract.get("embedding_model") or "")
        try:
            expected_dimensions = int(
                embedding_output_contract.get("embedding_dimensions") or 0
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "RETRIEVAL_EMBEDDING_OUTPUT_CONTRACT_INVALID",
                "frozen retrieval embedding dimensions are invalid",
            ) from exc
        if (
            not expected_model
            or not 1 <= expected_dimensions <= 8192
            or embedding_output_contract.get("vector_normalization") != "L2_UNIT"
            or embedding_output_contract.get("placeholder_vectors_allowed") is not False
        ):
            raise KernelError(
                "RETRIEVAL_EMBEDDING_OUTPUT_CONTRACT_INVALID",
                "frozen retrieval embedding model, dimensions, or vector policy is invalid",
            )
        return (
            "Return exactly one numeric embedding vector for each frozen input text, "
            "in the same order. The frozen output identity is exact: set embedding_model "
            f"to {_canonical(expected_model)} and embedding_dimensions to "
            f"{expected_dimensions}. Every vector must have exactly "
            f"{expected_dimensions} finite numeric entries and non-zero L2 norm; normalize "
            "each vector to unit length. Produce a genuine dense semantic representation "
            "whose latent axes remain consistent across calls under this exact contract, "
            "so meaningfully similar passages remain close without lexical, entity, Arc, "
            "or obligation overlap. Never emit a placeholder, sentinel, all-zero vector, "
            "provider-unavailable identity, summary, or invented fact. Do not retrieve or "
            "mutate Authority state."
        )
    if stage == "context_compress":
        return (
            "Select exact unit_id values from this bounded chunk that retain the task relevant "
            "causal meaning. Preserve every required unit and the subject, time, negation, "
            "condition, exception, uncertainty, and distinction between fact, belief, suspicion "
            "and plan. Keep task important voice, humor, relationship subtext and promise wording. "
            "Return unit IDs only; do not rewrite text, invent units, emit source hashes or "
            "positions, or decide fidelity. This is a derived extract proposal, never Canon. "
            "If required information cannot fit, preserve it and let the host block. "
        )
    if stage == "context_fidelity":
        return (
            "Independently inspect the proposed extract against this original source chunk "
            "and frozen task. Check forward source support and reverse required meaning coverage. "
            "Check subject, time, negation, conditions, exceptions, uncertainty, epistemic "
            "status, causal prerequisites, voice, relationship subtext and promises. A legal ID "
            "alone is not fidelity proof. Report unsupported or distorted selected IDs and "
            "missing original IDs. Fail closed on uncertainty and give a concrete reason. "
            "Do not rewrite extracts, mutate story state or rely on a compressor verdict. "
        )
    if stage == "retrieval_query_expansion":
        return (
            "Return only a bounded retrieval query proposal matching the strict schema. "
            "Every query must target one supplied deterministic evidence gap and stay "
            "within the frozen accepted chapter boundary and allowed selector dimensions. "
            "Never emit SQL, database identifiers, arbitrary AssetVersion identifiers, "
            "future-state selectors, retrieved records, sufficiency decisions, or Authority "
            "mutations. Deterministic policy validates the proposal and alone decides whether "
            "another governed retrieval round executes."
        )
    if stage == "agent_session":
        return (
            "Reason only over the frozen accepted boundary, committed transcript, "
            "observations, and server Tool snapshot. Choose exactly one action: "
            "request one Tool by copying its exact tool_name, or return one final "
            "candidate/proposal response. Encode Tool arguments and final response as one JSON "
            "object string in the required payload_json envelope. The outer response "
            "must still match the strict schema exactly. A Skill supplies method only and never "
            "adds permission. Never claim to mutate Canon, Accepted Narrative State, "
            "Arc Actual, Narrative Obligation lifecycle, active Plan pointers, or "
            "Chapter acceptance. Authority Commands submit proposals only; the owning "
            "Authority decides them."
        )
    realization_instruction = (
        (
            "Produce candidate prose within the frozen Scene realization contract. "
            "Each selected specialist slot must appear exactly once in contract order. "
            "Use only its accessible fact references; report used_fact_ids explicitly. "
            "Do not give a character reader-only knowledge. Keep every factual commitment "
            "inside the approved Scene scope and declared voice contracts. The text field "
            "must equal slot texts joined with two newlines, or the exact frozen scene_separators "
            "when supplied for an author candidate. Preserve those separators. For Revision, preserve unaffected "
            "slots and amend only slots needed by the frozen review issues; Quality and Actual "
            "reconciliation will run again. If no Scene slots exist, return scene_artifacts=[]. "
            "Candidate generation never changes Canon or accepted Narrative Reality."
        )
        if stage in {"draft", "revision"}
        else ""
    )
    if stage == "narrative_semantic_evaluation":
        return (
            "Independently evaluate the immutable candidate against every frozen "
            "qualification profile and criterion. The frozen Provider Context is the "
            "complete evidence boundary. For EXACT_CANDIDATE_ONLY, use only the first "
            "selected input. For EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES, keep the "
            "first selected input as the sole candidate under evaluation and consume "
            "each remaining exact qualified dependency's semantic_payload as evidence "
            "for that "
            "candidate's cross-layer claims. A reference-only BookDesign field is not "
            "missing evidence when its exact referenced dependency supplies the "
            "semantics. Do not consume prior qualification verdicts, demand downstream "
            "plans that cannot legally exist at the candidate's stage, or infer anything "
            "outside the frozen candidate-and-dependency envelope. Copy layer, profile_id, "
            "profile_version, profile_hash, capability_id, skill_ref, criterion, and "
            "candidate evidence identities exactly. Return one verdict per criterion. "
            "A non-PASS verdict must include a concrete repair_directive; PASS must "
            "leave repair_directive empty. Do not activate, revise, or replace the "
            "candidate, and do not infer evidence outside the frozen candidate."
        )
    if stage == "world_candidates.generate":
        return (
            "Generate only bounded candidate world transitions from the supplied frozen Foundation, Intent and accepted Reality. "
            "Copy all Authority references exactly. Propose hard preconditions, optional preparation paths, costs, "
            "consequences, information scope and soft assumptions separately. Never omit a hard predicate to make "
            "an event eligible. Preparation steps are proposals, not completed facts. Use explicit local: names "
            "for intra-batch dependencies; never invent accepted event IDs. Honor all frozen search and planning "
            "bounds. Return an evidence-based NO_OP or DEFER when advancement is unnecessary. "
            "OFF_CAMERA and UNDERCURRENT proposals must not grant Reader or character knowledge."
        )
    if stage == "world_candidates.evaluate":
        return (
            "Evaluate every supplied candidate exactly once against the frozen Director dimensions. "
            "Give reasons grounded in the supplied Foundation, Intent and Reality; compare the supplied preparation "
            "paths without inventing new paths, scores from third parties, facts or Authority identifiers. "
            "A high narrative score never overrides hard preconditions. This result recommends plans only."
        )
    if stage in _PLANNING_STAGES:
        contract = (
            "Return only the planning candidate defined by the frozen output schema. "
            "Every field ending in _version_id, _version_ids, _ref, or _refs is an "
            "immutable Authority reference: copy the exact supplied identifier "
            "verbatim and never replace it with a logical label, ordinal, title, or "
            "newly invented identifier. Keep Timeline containers and cross-cutting "
            "Narrative Arcs orthogonal. "
        )
        if stage == "book_plan.generate":
            contract += (
                "For world_realization and character_realization, every CURRENT "
                "entity's realization_level must be at least the top-level "
                "realization_level using ANCHOR < DEFINED < DETAILED < ACTIVE. "
                "Every knowledge_disclosure_obligations.obligation_windows[]."
                "obligation_id must copy one exact identity declared in story_truth_ids, "
                "mystery_ids, promise_ids, or foreshadow_ids, and each window must "
                "satisfy setup_chapter <= payoff_not_before <= payoff_due_by inside "
                "the bounded Book. "
            )
        elif stage == "arc_plan.generate":
            contract += (
                "Set cross_volume_scope to exactly the ordered VolumePlan Authority "
                "version identifiers supplied by planning_command.input_versions."
                "volume_plan followed by planning_command."
                "arc_scope_volume_plan_version_ids. Each arc_segments[]."
                "volume_plan_version_id must copy one identifier from that exact "
                "scope, and each narrative_segment_id must copy a Narrative Segment "
                "identifier from the corresponding supplied VolumePlan. Never use a "
                "logical label such as volume:1 in cross_volume_scope or a "
                "volume_plan_version_id. Thread -> Arc -> Arc Segment is the "
                "cross-volume graph; Volume -> Narrative Segment remains the "
                "Timeline plan."
            )
        elif stage == "chapter_group_plan.generate":
            contract += (
                "Copy planning_command.narrative_search_planning_horizon."
                "chapter_range exactly into chapter_range. Produce one ordered "
                "chapter_function_matrix row for every Chapter in that frozen range, "
                "and make narrative_event_chain cover every Chapter without placing "
                "an event outside the range. The frozen desired transformation, hard "
                "constraints, and branch strategy directive are simultaneous; the "
                "branch cannot relax the exact range or accepted boundary. Every "
                "narrative_event_chain[].disclosures value must exactly copy a value "
                "from the same event's knowledge_boundary.reader_may_learn and must "
                "not occur in forbidden_disclosures."
            )
        elif stage == "chapter_plan.generate":
            contract += (
                "Produce an executable Chapter plan: bind its exact Timeline and Arc "
                "references, declare Primary/Secondary/Touch/Hold Arc work, knowledge "
                "boundaries, disclosures, causal character and state transitions, "
                "scene or scene-group execution units, reader experience, and the "
                "expected exit state. Every required_state_transitions[].state_kind "
                "must use the schema's canonical Narrative State vocabulary. Use exact "
                "stable identities in entity_key: character_id for character_state; "
                "source_id:target_id for relationship_state; character_id:arc_id for "
                "character_arc; character_id:fact_id for character_knowledge; and "
                "the state kind's stable Authority identifier. Do not put Reader "
                "Knowledge or Disclosure in required_state_transitions: Reader "
                "Knowledge is fulfilled only by a planned Disclosure whose mode "
                "deterministically yields the knowledge boundary status: HINT -> "
                "HINTED, PARTIAL -> SUSPECTED, MISDIRECT -> MISDIRECTED, CONFIRM -> "
                "KNOWN, WITHHOLD -> WITHHELD. WITHHOLD does not advance accepted "
                "Reader Knowledge. Use audience "
                "READER or ALL for reader-facing disclosure; represent a mixed audience "
                "as separate Disclosure events with stable identities. Commit only "
                "state transitions that this chapter can visibly execute and Canon "
                "extraction can type. Use resource_state only for a quantifiable "
                "balance with a stable entity/resource identity; object custody, "
                "location, ownership, or protection belongs in Canon facts or another "
                "typed state."
            )
        return _bind_language_contract(contract, required_language)
    if stage == "revision":
        revision_language = (
            "Revise the reader-facing prose into the governed language even when the "
            "input draft uses another language. Do not preserve a conflicting input "
            "language. "
            if required_language
            else (
                "Preserve the reader-facing language of the input chapter and do not "
                "introduce unexplained code-switching. "
            )
        )
        return _bind_language_contract(
            realization_instruction
            + "Return text as final reader-facing revised chapter prose only. "
            "Resolve every supplied review issue in the prose, prioritizing blocking and "
            "major issues; list a code in resolved_issue_codes only after the edit is "
            "actually present. For a governed Quality revision task, make the smallest "
            "bounded edit that resolves the supplied task, preserve all unrelated scenes, "
            "causal links, established facts, and already-passing quality dimensions, and "
            "retain the complete reader-facing chapter at its original narrative scale "
            "unless chapter_length is itself the supplied task. Never replace the full "
            "chapter with a summary or excerpt. "
            f"{revision_language}Do not put a serialized "
            "JSON object inside text. Do not include analysis, self-checks, change logs, "
            "revision evidence, or operator-facing appendices in text.",
            required_language,
        )
    if stage == "review":
        return _bind_language_contract(
            "Diagnose the actual candidate against frozen constraints and creative guidance. "
            "Every issue requires category, judgment_kind, literal evidence with Unicode code-point "
            "start/end offsets, violated_constraint, revision_goal, preserve and acceptance_criteria. "
            "Separate semantic conflicts, uncertain judgments and aesthetic suggestions. Provider opinions "
            "are not deterministic proof; taste preferences alone are minor. Do not invent defects from "
            "a plan target that prose deliberately leaves unfulfilled. Return resolution_checks=[] on "
            "initial review. Evidence must identify a concrete defect and an observable repair condition. "
            "For every knowledge_review_target return a knowledge_check using its exact card version. "
            "Check mechanism, prerequisites, exceptions, cost and consequences in actual prose, including "
            "knowledge/disclosure boundaries, future leakage and false payoff. VERIFIED_IN_PROSE needs "
            "literal evidence and explicit conditions_checked/ exceptions_checked; terminology or Writer "
            "used_fact_ids is insufficient. Unused inspiration is NOT_USED, uncertainty is UNKNOWN. "
            "MISAPPLIED requires linked actionable issue_codes; unresolved CONSTRAINT requires a blocking issue. "
            "Return knowledge_checks=[] if no targets. Never call this formal proof or human approval.",
            required_language,
        )
    if stage == "rereview":
        return _bind_language_contract(
            "Independently verify the revised chapter against the supplied review. "
            "Report in issues only defects that remain acceptance-blocking: an unresolved "
            "blocking or major issue, or a material regression that prevents acceptance. "
            "Do not report optional minor polish or taste preferences in issues. If no "
            "acceptance-blocking defect remains, return issues=[] and an evidence-based "
            "score. Never suppress an actual blocking or major defect. "
            "For EVERY prior diagnosis return a resolution_check tied to its acceptance criteria, with "
            "a literal revised-prose evidence location and preservation assessment. SATISFIED requires "
            "the repair to be present and required content preserved. A claimed fix, issue omission, "
            "or a higher score never establishes resolution; report UNRESOLVED/UNCERTAIN when needed. "
            "Recheck every knowledge_review_target against this revised prose in knowledge_checks. "
            "Use its exact card version and literal evidence; check mechanisms, prerequisites, exceptions "
            "and narrative consequences. MISAPPLIED requires linked actionable issue_codes; unresolved "
            "CONSTRAINT requires a blocking issue. Prior verification never transfers to changed prose. "
            "Unused inspiration may be NOT_USED; report UNKNOWN for uncertainty; no targets means [].",
            required_language,
        )
    if stage == "memo":
        return (
            "Turn the frozen Chapter mission into specific creative guidance rather than paraphrasing it. "
            "Explain each character choice through motivation and cost, scene conflict, emotional movement, "
            "information release and continuity, reader promise and ending change. Respect POV and voice. "
            "Use exact Scene/Arc/character identities. Accepted boundary is fact provenance; scene targets "
            "are author plans; your choices are suggestions. Never introduce Canon or undisclosed secrets. "
            "Keep the plan and accepted boundary unchanged; propose craft decisions within their constraints."
        )
    if stage == "canon_support":
        return (
            "Independently check each candidate claim against final prose and exact accepted references. "
            "A matching quote is necessary, never sufficient. Distinguish objective events from dialogue, "
            "belief, hearsay, plans and intentions. Knowledge belongs only to the evidenced recipient. "
            "GROUNDED_FINAL_CANDIDATE_CLAIM payoff citations identify this candidate's claim, "
            "not a historical event; check the actual fulfillment against the final prose. "
            "Return UNSUPPORTED or UNCERTAIN when entailment is missing. Do not repair claims or supply "
            "events from plans. Review NARRATIVE_OBSERVATION claims against prose as well; a plan is only the comparison target. Check extraction coverage; approve NO_CHANGE only when prose supports no "
            "new canonical change. You provide evidence only; Book acceptance remains Authority."
        )
    if stage == "canon_extraction":
        return _bind_language_contract(
            "Extract only facts and state changes supported by the revised chapter. "
            "Treat from_status, from_state, from_stance, and from_tier only as compare-and-set "
            "preconditions against the exact accepted Story State supplied in the "
            "governed context. For a first occurrence with no accepted entity baseline, "
            "leave from_status, from_state, from_stance, and from_tier null; never infer them from prose, "
            "Story Design assets, plans, or ordinary background conditions. "
            "For canon_facts, compare each (subject, predicate) slot with the accepted "
            "Canon facts supplied in the governed context. If the chapter does not "
            "materially change an accepted fact, omit the redundant fact or reuse its "
            "object exactly. If the chapter changes, refines, or replaces that fact, "
            "copy the accepted fact's exact source_event_id into supersedes_event_id. "
            "Never paraphrase an unchanged accepted fact into a different object, and "
            "never invent a supersession identity. "
            "Treat requires_fact_ids as character-specific epistemic preconditions. "
            "Every required fact must already appear in that character's accepted "
            "known facts in the governed context, or the chapter must first establish "
            "it through an atomic character_knowledge_changes item with fact_id and "
            "chapter evidence. World-rule "
            "availability is not automatically character knowledge. If the prose and "
            "governed context do not establish the knowledge, omit the unsupported "
            "action or requirement; never add unsupported knowledge merely to satisfy "
            "validation. Keep Story Truth, Character Knowledge, Character Belief, "
            "Reader Knowledge, and presentation separate: a Canon fact does not by "
            "itself make any character or the reader aware of it; a belief may be "
            "false. In character_knowledge_changes, emit one item per "
            "character_id plus fact_id or proposition_id; never bundle multiple newly "
            "learned facts into one Character Knowledge event. Use only the status "
            "field with UNKNOWN, SUSPECTED, KNOWN, or FORGOTTEN; leave the generic "
            "state field null. "
            "In character_belief_changes, use only stance with BELIEVES, DOUBTS, "
            "DISBELIEVES, or UNCERTAIN plus belief_confidence from zero to one; use "
            "from_stance only for an exact accepted baseline and leave generic state, "
            "status, from_state, and from_status null. "
            "In relationship_changes, always copy both directed graph endpoints into "
            "source_id and target_id; entity_id cannot replace an endpoint, and the "
            "generic character_id field must remain null. "
            "Use obligation_changes for the unified accepted Narrative Obligation "
            "lifecycle. Copy obligation_id, obligation_type, priority, target_window, "
            "and linked Arc identities from governed context. FULFILLED requires a "
            "typed payoff_evidence object. For a prose payoff use the literal "
            "asset_version_id=$FINAL_CANDIDATE and event_id=$CURRENT_CLAIM; the Authority "
            "binds these to this final candidate and grounded claim. Never invent an "
            "AssetVersion or accepted event identity. Arc evidence alone never silently closes an "
            "obligation. "
            "For CAUSAL_DEBT, preserve causal_plan_asset_version_id and the exact "
            "causal_requirement.payload_json predicate from its planning origin. "
            "A plan cannot repay debt: FULFILLED requires a satisfied condition and "
            "its accepted source event as payoff_evidence.event_id. Other obligation "
            "types use null for these two causal fields. "
            "World, faction, location, consequence and conflict state changes require "
            "world_transition.payload_json: transition_id, actor_id, camera (ON_CAMERA, "
            "OFF_CAMERA or UNDERCURRENT), native StoryTime, action, state_kind, exact "
            "entity_key, changes, requirements, cause_refs and epistemic_basis. "
            "Causes must resolve to accepted source events. Observe only events "
            "supported by the final prose, including explicitly narrated off-camera "
            "events; a proposed future is not an occurrence. "
            "Every typed change must copy its exact stable Authority identity: "
            "character_id for character and power state, event_id for timeline, "
            "thread_id for foreshadow and plot thread, promise_id, reward_id, rule_id, "
            "entity_id plus resource_id for resource balances, fingerprint_id, "
            "antagonist_id, character_id plus arc_id for character trajectory, arc_id "
            "for narrative Arc state, and disclosure_id for presentation. A generic "
            "entity_id never substitutes for another domain's identity. If no stable "
            "identity is available in governed context, omit the unsupported change. "
            "Emit every supported "
            "planned non-WITHHOLD presentation as a "
            "disclosure_event, including character-facing events; accepted "
            "reader-facing Disclosure alone is deterministically projected into "
            "Reader Knowledge. Record how the "
            "information was presented "
            "through disclosure_mode, audience, and presentation_channel rather than "
            "copying Truth into every epistemic layer. "
            "Reconcile the frozen execution_expectations exactly. For every required "
            "state transition supported by the chapter, emit one change in the "
            "corresponding typed array with the exact planned identity and to_state; "
            "do not paraphrase either. Omit from_* only when the governed context has "
            "no accepted baseline. For every planned disclosure, copy disclosure_id, "
            "fact_id, audience, and mode exactly; do not expand the audience. Reader "
            "Knowledge will be derived after the Disclosure is accepted. "
            "Arc and Narrative Realization evidence describes final candidate prose, "
            "never Plan or Future Intent. Return exactly one arc_evidence item for "
            "each frozen expected Arc contribution. Use observation_status OBSERVED "
            "only when the accepted revision visibly executes that contribution. An "
            "OBSERVED Arc item must include at least one resolution_evidence string "
            "encoded as chars:<start>-<end>:<summary>, where start and end are valid "
            "Unicode code-point offsets into final_candidate; otherwise return zero "
            "progress_units and an empty resolution_evidence list. Return one "
            "realization_evidence item for every frozen Narrative Realization event. "
            "OBSERVED realization evidence requires a non-empty "
            "accepted_prose_evidence list with valid final_candidate Unicode code-point "
            "offsets plus the observed event identity, action, decision, consequence, "
            "and state deltas. Planning context alone never proves observation. "
            "Within canon_facts, each (subject, predicate, impact_type) tuple may occur "
            "at most once. When one subject has multiple objects for a broad relation, "
            "either combine them into one object when they are one bundled fact, or use "
            "precise relation-specific predicates. For example, encode separate consent "
            "facts as authorizes_testimony and authorizes_public_identification instead "
            "of repeating authorizes with two objects. Never emit two different objects "
            "for the same semantic tuple. "
            "Use resource_state_changes only for quantifiable resource balances. An "
            "initial resource baseline must set balance_after; a later transition must "
            "set balance_before, delta, and balance_after with exact arithmetic. Do not "
            "encode custody, location, protection, ownership, or other qualitative "
            "object status as a Resource State merely because the object is a story "
            "resource; represent supported qualitative changes as precise canon_facts "
            "or timeline_events instead. If the prose supplies no numeric balance, "
            "leave resource_state_changes empty.",
            required_language,
        )
    if stage.startswith("quality_"):
        contract = (
            "Evaluate only the requested dimensions. Every returned dimension must "
            "include at least one concrete evidence location, including policy-"
            "compliance dimensions. Use PASSED only when the supplied chapter or "
            "governed context directly supports the claim; otherwise use "
            "INSUFFICIENT_EVIDENCE, REQUIRES_HUMAN_REVIEW, or FAILED as appropriate."
        )
        if stage == "quality_source_originality":
            contract += (
                " Judge originality as differentiated execution within the supplied "
                "project-owned task and the governed source boundary. Universal "
                "comparison against every published work is not required and its "
                "absence alone is not a reason for REQUIRES_HUMAN_REVIEW. When source "
                "isolation is clear, no reference expression or suspicious overlap is "
                "present, and the prose contains concrete project-specific causal "
                "choices, originality may PASS with provider-uncalibrated evidence. "
                "Use REQUIRES_HUMAN_REVIEW only for an identified similarity, lineage, "
                "or attribution ambiguity that cannot be resolved from the governed "
                "inputs; name that specific risk in the evidence."
            )
        if stage == "quality_longform":
            contract += (
                " For world_rule_conflict and power_state_conflict, distinguish a "
                "proven no-op from missing comparison state: when the chapter directly "
                "shows no state-changing use or claim and current state candidates "
                "contain no transition, return PASSED with concrete no-op evidence; "
                "do not require the chapter to exercise the rule or power. When the "
                "chapter claims a state or transition but the governed comparison "
                "baseline is unavailable, return INSUFFICIENT_EVIDENCE."
            )
            contract += (
                " Treat canon_conflicts as the authoritative deterministic continuity "
                "result: when it is empty, do not invent a Canon conflict. Compare "
                "world-rule usages against governed_world_rules in the Quality Context; "
                "when the exact rule and its limits are present and the chapter stays "
                "within them, return PASSED with concrete rule-and-prose evidence."
            )
        if stage == "quality_platform":
            contract += (
                " Evaluate ai_content_policy only against the exact "
                "compiled_platform_policy and its release_scope. When governed assisted "
                "content is allowed for internal Provider validation and the chapter "
                "meets the listed content requirements, return PASSED with concrete "
                "policy and prose evidence. Do not duplicate source-lineage, copyright, "
                "or originality review in ai_content_policy; those are independently "
                "governed dimensions. A separate human approval required for external "
                "publication is not a defect in an internal validation release."
            )
        if required_language:
            contract += (
                " For a requested language, platform, or format dimension, treat prose "
                "that is not primarily Simplified Chinese as FAILED; Authority "
                "acceptance alone is not evidence of language compliance."
            )
        return _bind_language_contract(contract, required_language)
    return _bind_language_contract(
        realization_instruction
        + "Return only the stage result defined by the frozen output schema.",
        required_language,
    )


def _bind_language_contract(contract: str, required_language: str | None) -> str:
    language_contract = _language_semantic_contract(required_language)
    return f"{language_contract} {contract}" if language_contract else contract


def _project_prose_skill(text: str, *, stage: str, targeted: bool) -> str:
    sections = {}
    for part in text.split("\n## ")[1:]:
        heading, separator, body = part.partition("\n")
        if not separator or heading in sections:
            raise KernelError("PROSE_SKILL_PROJECTION_INVALID", "The frozen method sections must be distinct")
        sections[heading] = body.strip()
    selected = "Targeted revision" if targeted else "Draft and full revision"
    if stage not in {"draft", "revision"} or "Shared rules" not in sections or selected not in sections:
        raise KernelError("PROSE_SKILL_PROJECTION_INVALID", "Prose method requires the declared Draft or Revision task")
    return "# Prose Generation\n\n" + sections["Shared rules"] + "\n\n" + sections[selected]


def _materialize_production_codex_prompt(
    *,
    request: ExecutionRequest | None = None,
    target_scope: Mapping[str, Any] | None = None,
    stage: str,
    inputs: Mapping[str, Any],
    materialization: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    if request is not None:
        resolved_target_scope = request.target_scope.to_dict()
    elif target_scope is not None:
        resolved_target_scope = TargetScope.from_dict(target_scope).to_dict()
    else:
        raise KernelError(
            "CHAPTER_PROVIDER_TARGET_SCOPE_MISSING",
            "Provider prompt requires a frozen target scope",
        )
    pack_artifacts = materialization.get("pack_artifacts")
    if not isinstance(pack_artifacts, Mapping):
        raise KernelError(
            "CAPABILITY_PACK_ASSET_CONTENT_MISSING",
            "Capability materialization has no Pack Artifact content",
        )

    def required_text(key: str) -> tuple[str, Mapping[str, Any]]:
        artifact = pack_artifacts.get(key)
        content = artifact.get("content") if isinstance(artifact, Mapping) else None
        text = content.get("text") if isinstance(content, Mapping) else None
        if not isinstance(text, str) or not text.strip():
            raise KernelError(
                "CAPABILITY_PACK_ASSET_CONTENT_MISSING",
                f"Capability {key} has no exact text content",
            )
        return text, artifact

    from novel_forge.modules.worldbuilding.actor_isolation import ACTOR_STAGES, validate_actor_task

    if stage in ACTOR_STAGES:
        validate_actor_task(inputs.get("world_preparation") or {})

    system_text, system = required_text("system_instruction")
    template_text, template = required_text("prompt_template")
    skill_text, skill = required_text("skill")
    if (template.get("ref"), template.get("version")) == ("prompt-template:chapter-generation-pack", "v15"):
        from .prompt_methods import project_chapter_template
        template_text = project_chapter_template(template_text, stage=stage)
    intent_boundary = (template.get("ref"), template.get("version")) == ("prompt-template:story-planning-pack", "v3")
    if intent_boundary and (system.get("ref"), system.get("version")) != ("prompt-system:story-planning-pack", "v12"):
        raise KernelError("PLANNING_NARRATIVE_INTENT_BINDING_INVALID", "Narrative intent projection requires its frozen System binding")
    compact_contract = str(template.get("version") or "") in {
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9", "v10", "v11", "v12", "v13", "v15",
    }
    context = materialization.get("context_selection")
    knowledge = materialization.get("knowledge_selection")
    tools = materialization.get("tool_permissions")
    schema = materialization.get("output_schema")
    if (
        not isinstance(context, list)
        or len(context) != 1
        or not isinstance(context[0], Mapping)
        or not isinstance(knowledge, list)
        or (
            not knowledge
            and stage not in {"agent_session", "retrieval", "retrieval_query_expansion", "model_reference_evaluate", "model_reference_adjudicate", *CONTEXT_MODEL_STAGES, *ACTOR_STAGES}
        )
        or not isinstance(tools, Mapping)
        or not isinstance(schema, Mapping)
        or not isinstance(schema.get("content"), Mapping)
    ):
        raise KernelError(
            "CHAPTER_CAPABILITY_MATERIALIZATION_INVALID",
            "Capability Context, Knowledge, Tool, or Schema selection is incomplete",
        )
    context_content = context[0].get("content")
    if not isinstance(context_content, Mapping):
        raise KernelError(
            "CHAPTER_CAPABILITY_MATERIALIZATION_INVALID",
            "Capability Context selection has no ContextBundle content",
        )
    from .provider_output_contracts import is_targeted_revision_schema_ref

    targeted_edits_only = stage == "revision" and is_targeted_revision_schema_ref(
        str(schema.get("ref") or "")
    )
    project_methods = str(template.get("version") or "") in {"v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13", "v15"}
    if skill.get("ref") == "prose-generation" and skill.get("version") == "prose-generation-v3":
        skill_text = _project_prose_skill(skill_text, stage=stage, targeted=targeted_edits_only)
    from .prompt_methods import project_planning_system, project_skill_method

    method_source_text = skill_text
    skill_text = project_skill_method(skill_text, ref=str(skill.get("ref") or ""), version=str(skill.get("version") or ""), stage=stage, targeted=targeted_edits_only)
    calibrated_methods = skill_text != method_source_text
    if system.get("ref") == "prompt-system:story-planning-pack" and system.get("version") in {"v8", "v12"}:
        system_text = project_planning_system(system_text, stage=stage, narrative_intent_boundary=intent_boundary)
        calibrated_methods = True
    task_view = build_provider_task_view(
        stage,
        inputs,
        compact_contract=compact_contract,
        targeted_edits_only=targeted_edits_only,
        project_methods=project_methods,
        instruction_cleanup=template.get("ref")
        == "prompt-template:chapter-generation-pack"
        and template.get("version") in {"v7", "v8", "v9", "v10", "v11", "v12", "v13", "v15"},
        work_requirements=template.get("ref")
        == "prompt-template:chapter-generation-pack"
        and template.get("version") in {"v8", "v9", "v10", "v11", "v12", "v13", "v15"},
    )
    if stage == "revision" and schema.get("ref") == "schema:chapter-provider-output:revision:v7":
        source = dict(inputs.get("draft") or {})
        prior_window = (inputs.get("review") or {}).get("cross_chapter_window")
        if prior_window:
            task_view["source_window"] = deepcopy(prior_window)
        task_view["chapter"] = {key: source[key] for key in ("chapter", "title", "text") if key in source}
        task_view.pop("scene_artifacts", None)
        task_view.pop("scene_separators", None)
        task_view.pop("realization_contract", None)
        task_view.pop("targeted_repair", None)
        task_view.pop("targeted_editing", None)
        task_view["revision_scope"] = "WHOLE_CHAPTER_TEXT_WITH_FROZEN_CORE_REQUIREMENTS"
    context_view = build_provider_context_view(
        stage,
        context_content,
        task_view,
        clean_writer_context=template.get("ref")
        == "prompt-template:chapter-generation-pack"
        and template.get("version") == "v6",
        writer_projection_version="accepted-writer-history.v2"
        if template.get("ref") == "prompt-template:chapter-generation-pack"
        and template.get("version") in {"v7", "v8", "v9", "v10", "v11", "v12", "v13", "v15"}
        else "",
    )
    context_manifest = context_content.get("context_manifest")
    if isinstance(context_manifest, Mapping):
        frozen_provider_view = context_manifest.get("provider_context_view")
        if isinstance(frozen_provider_view, Mapping):
            expected_view_hash = str(frozen_provider_view.get("content_hash") or "")
            if (
                not expected_view_hash
                or canonical_hash(context_view) != expected_view_hash
            ):
                raise KernelError(
                    "PROVIDER_CONTEXT_VIEW_IDENTITY_MISMATCH",
                    "materialized Provider Context differs from its frozen Manifest",
                )
    knowledge_view = build_provider_knowledge_view(
        item for item in knowledge if isinstance(item, Mapping)
    )
    if not knowledge_view and stage not in {
        "agent_session", "retrieval", "retrieval_query_expansion", "model_reference_evaluate", "model_reference_adjudicate", *CONTEXT_MODEL_STAGES, *ACTOR_STAGES,
    }:
        raise KernelError(
            "CHAPTER_CAPABILITY_MATERIALIZATION_INVALID",
            "Provider Knowledge projection is empty",
        )
    intent_projection = None
    selection_explanation = context_view.get("selection_explanation")
    if intent_boundary:
        from .provider_views import project_planning_narrative_intent
        task_view, context_view, intent_projection = project_planning_narrative_intent(task_view, context_view)
    exact_reference_proof = None
    reference_version = context_content.get("planning_exact_reference_projection_version")
    if reference_version not in (None, "planning-exact-value-reference.v1"):
        raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "Exact reference compilation requires its frozen Planning contract")
    if (template.get("ref"), template.get("version")) in {
        ("prompt-template:chapter-generation-pack", "v13"),
        ("prompt-template:chapter-generation-pack", "v15"),
        ("prompt-template:story-planning-pack", "v2"),
        ("prompt-template:story-planning-pack", "v3"),
    }:
        from .provider_views import compile_exact_context_references
        envelope, exact_reference_proof = compile_exact_context_references({"input_manifest": task_view, "context_bundle": context_view}, structured_transport=stage in {"draft", "revision"} and template.get("ref") == "prompt-template:chapter-generation-pack" and template.get("version") in {"v13", "v15"} and (context_content.get("working_manuscript") or {}).get("projection_policy", {}).get("version") in {"working-prose-projection.v2", "working-prose-projection.v3"})
        task_view, context_view = envelope["input_manifest"], envelope["context_bundle"]
        exact_reference_proof["source_scope"] = "provider_data_envelope"
        exact_reference_proof["contract_version"] = "provider-context-exact-value-reference.v1"
    elif reference_version is not None and stage in {
            "book_plan.generate", "volume_plan.generate", "arc_plan.generate", "chapter_group_plan.generate", "chapter_plan.generate",
        }:
        from .provider_views import compile_exact_context_references
        context_view, exact_reference_proof = compile_exact_context_references(context_view)
    replacements = {
        "{{stage}}": stage,
        "{{provider_data_envelope}}": _canonical({"input_manifest": task_view, "context_bundle": context_view}),
        "{{target_scope}}": _canonical(resolved_target_scope),
        "{{input_manifest}}": _canonical(task_view),
        "{{context_bundle}}": _canonical(context_view),
        "{{output_schema_ref}}": str(schema.get("ref") or ""),
    }
    rendered_template = template_text
    for marker, value in replacements.items():
        rendered_template = rendered_template.replace(marker, value)
    if re.search(r"\{\{[a-zA-Z0-9_]+\}\}", rendered_template):
        raise KernelError(
            "CHAPTER_CAPABILITY_TEMPLATE_INVALID",
            "frozen Prompt Template contains unresolved placeholders",
        )
    allowed = tuple(str(item) for item in tools.get("allowed") or ())
    agent_tool_names = {
        str(item.get("tool_name") or "")
        for item in inputs.get("tools") or ()
        if isinstance(item, Mapping)
    }
    required_allowed = (
        {"model.provider.invoke", *agent_tool_names}
        if stage == "agent_session"
        else {"model.provider.invoke"}
    )
    if set(allowed) != required_allowed:
        raise KernelError(
            "CHAPTER_CAPABILITY_TOOL_UNAUTHORIZED",
            "Codex execution differs from the governed Provider/Agent Tool set",
        )
    required_language = _required_language_from_context(context_content)
    embedding_output_contract = materialization.get("embedding_output_contract")
    if stage == "retrieval" and not isinstance(embedding_output_contract, Mapping):
        raise KernelError(
            "RETRIEVAL_EMBEDDING_OUTPUT_CONTRACT_MISSING",
            "controlled retrieval prompt requires a frozen embedding output contract",
        )
    stage_semantic_contract = (_stage_semantic_contract_v3 if compact_contract else _stage_semantic_contract)(
        stage,
        required_language=required_language,
        embedding_output_contract=(
            embedding_output_contract
            if isinstance(embedding_output_contract, Mapping)
            else None
        ),
    )
    if stage == "revision" and schema.get("ref") == "schema:chapter-provider-output:revision:v7":
        stage_semantic_contract = _bind_language_contract(
            "Return the complete revised chapter in the single text field, with resolved_issue_codes only for repairs claimed. "
            "The frozen whole-chapter repair or measured length scope permits merging repeated scenes, transitions and noncritical order. "
            "Preserve author commitments, selected story facts, character knowledge, causal consequences and due promises. "
            "Do not change upper plot; propose Plan Change for that. Do not return scene_artifacts or an edits protocol. "
            "Keep unresolved diagnoses open. This candidate is not accepted Canon and its scene mapping requires separate validation.",
            required_language,
        )
    if targeted_edits_only:
        stage_semantic_contract = _bind_language_contract(
            "Return only ordered non-overlapping edits with exact old quotes, replacement prose and linked issue codes. "
            "Do not return Scene Slot texts or a second complete chapter. The host locates each quote against the frozen "
            "candidate, enforces diagnosed ranges and Slot boundaries, and derives unchanged prose byte-for-byte. "
            "Preserve actor, POV, knowledge, accepted facts and due obligations; read adjacent passages for continuity. "
            "A Slot boundary only locates prose and does not prove narrative coherence.",
            required_language,
        )
    grounding_observations = [
        item
        for item in inputs.get("observations") or ()
        if isinstance(item, Mapping)
        and str(item.get("tool_name") or "") != "skill.activate"
    ]
    if (
        stage == "agent_session"
        and int(inputs.get("turn_number") or 0) == 1
        and not grounding_observations
        and "narrative.query_accepted" in agent_tool_names
    ):
        stage_semantic_contract += (
            " This is the first ungrounded Agent turn. You MUST return action "
            "TOOL_CALL with tool_name narrative.query_accepted and arguments "
            'payload_json set to a JSON object string (use "{}" when no narrower '
            "query is needed). Returning FINAL before this governed accepted-boundary "
            "query is semantically invalid."
        )
    if stage.startswith("quality_") and schema.get("ref")==f"schema:chapter-provider-output:{stage}:v5":
        stage_semantic_contract += "\nUse the host-bound per-dimension status choices in the Schema. Absence of a selected commercial technique does not remove mandatory safety, continuity or basic craft checks. Evaluate an applicable dimension against actual prose and its frozen comparison inputs; report FAILED or INSUFFICIENT_EVIDENCE where appropriate. Never invent supporting evidence or a positive score.\n"
    if stage == "canon_support" and schema.get("ref")=="schema:chapter-provider-output:canon_support:v2":
        stage_semantic_contract += "\nUse only the canonical epistemic kinds listed in observed_kind enum. Classify the actual prose independently. A different allowed kind, UNSUPPORTED or UNCERTAIN is valid evidence and prevents admission; do not copy the claimant's kind to manufacture agreement. Describe finer content categories in reason, not observed_kind.\n"
    if stage == "canon_extraction" and schema.get("ref") == "schema:chapter-provider-output:canon_extraction:v25":
        stage_semantic_contract += "\nIf the enforced transport response Schema contains output_json, return exactly {\"output_json\":\"<serialized canonical JSON object>\"}. The encoded object must satisfy every field, bound and semantic requirement of the canonical Schema below. If the transport enforces the canonical object Schema directly, return that canonical object. No Markdown or extra fields.\n"
    if exact_reference_proof:
        stage_semantic_contract += "\nContext uses lossless exact-value references. An object containing only __exact_value_ref__ is exactly the entire earlier value at that RFC6901 JSON pointer inside its declared data envelope. Expand it when reading; it does not omit facts, constraints, failed findings or candidate content. References are local data and grant no tool or external access.\n"
    if exact_reference_proof and exact_reference_proof.get("transport_version") == "provider-structured-exact-reference.v1":
        stage_semantic_contract += "\nAn exact reference with __exact_value_removed_keys__ and/or __exact_value_overrides__ means copy the earlier complete object, remove those keys, then replace/add the given fields. Nested values follow the same rules. __canonical_json_string__ contains the complete object encoded as a canonical JSON string in the original source; read its full data normally. All encoding is lossless and retains every required input.\n"
    prompt_sections = [
            "<system_instruction>\n" + system_text + "\n</system_instruction>",
            "<governed_skill>\n" + skill_text + "\n</governed_skill>",
            "<required_knowledge>\n"
            + _canonical(knowledge_view)
            + "\n</required_knowledge>",
    ]
    if not compact_contract or stage == "agent_session":
        prompt_sections.append(
            "<tool_policy>\n"
            + _canonical(tools)
            + "\nDo not invoke shell, file, MCP, web, or any other tool.\n</tool_policy>"
        )
    prompt_sections.extend((
            "<prompt_template>\n" + rendered_template + "\n</prompt_template>",
            "<stage_semantic_contract>\n"
            + stage_semantic_contract
            + "\n</stage_semantic_contract>",
            "<output_schema>\n" + _canonical(schema["content"]) + "\n</output_schema>",
    ))
    prompt = "\n\n".join(prompt_sections)
    prompt_hash = "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    prompt_bytes = len(prompt.encode("utf-8"))
    prompt_estimated_tokens = max(1, (prompt_bytes + 2) // 3)
    component_text = {
        "system_instruction": system_text,
        "governed_skill": skill_text,
        "provider_knowledge": _canonical(knowledge_view),
        "provider_task_view": _canonical(task_view),
        "provider_context_view": _canonical(context_view),
        "tool_policy": _canonical(tools) if not compact_contract or stage == "agent_session" else "",
        "stage_semantic_contract": stage_semantic_contract,
        "output_schema": _canonical(schema["content"]),
        "fully_rendered_prompt": prompt,
    }
    component_characters = {key: len(value) for key, value in component_text.items()}
    component_bytes = {
        key: len(value.encode("utf-8")) for key, value in component_text.items()
    }
    component_hashes = {
        key: "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
        for key, value in component_text.items()
    }
    from novel_forge.modules.chapter_quality_authority.context_views import ConservativeTokenEstimator

    component_estimator = ConservativeTokenEstimator()
    component_tokens = {
        key: component_estimator.estimate(value) for key, value in component_text.items()
    }
    authority_context_tokens = int(context_content.get("estimated_tokens") or 0)
    provider_context_tokens = component_tokens["provider_context_view"]
    semantic_input_tokens = max(
        1,
        provider_context_tokens
        + component_tokens["provider_task_view"]
        + component_tokens["provider_knowledge"],
    )
    evidence = {
        "materialization_hash": str(materialization.get("materialization_hash") or ""),
        "reusable_prefix_bytes": len(prompt.split("</governed_skill>", 1)[0].encode())
        + len("</governed_skill>".encode()),
        "fully_rendered_prompt_hash": prompt_hash,
        "required_reader_facing_language": required_language,
        **({"narrative_intent_projection": intent_projection} if intent_projection else {}),
        "provider_prompt_projection_version": "planning-narrative-intent-projection.v1" if intent_boundary else "authority-projection-work-requirements.v1"
        if template.get("ref") == "prompt-template:chapter-generation-pack"
        and template.get("version") in {"v8", "v9", "v10", "v11", "v12", "v13", "v15"}
        else "authority-projection-task-provider-v5"
        if template.get("ref") == "prompt-template:chapter-generation-pack"
        and template.get("version") == "v7"
        else "authority-projection-task-provider-v4"
        if template.get("ref") == "prompt-template:chapter-generation-pack"
        and template.get("version") == "v6"
        else "authority-projection-stage-method-provider-v1"
        if calibrated_methods
        else "authority-projection-task-provider-v3"
        if project_methods
        else "authority-projection-task-provider-v2"
        if compact_contract
        else "authority-projection-task-provider-v1",
        **(
            {
                "method_selection": {
                    "contract_version": "production-stage-methods.v1",
                    "skill_sections": [
                        part.partition("\n")[0]
                        for part in ("\n" + skill_text).split("\n## ")[1:]
                    ],
                    "system_sections": [
                        part.partition("\n")[0]
                        for part in ("\n" + system_text).split("\n## ")[1:]
                    ],
                }
            }
            if calibrated_methods
            else {}
        ),
        "rendered_prompt_bytes": prompt_bytes,
        "rendered_prompt_estimated_tokens": prompt_estimated_tokens,
        "system_instruction": {
            key: system.get(key) for key in ("ref", "version", "content_hash")
        },
        "prompt_template": {
            key: template.get(key) for key in ("ref", "version", "content_hash")
        },
        "skill": {key: skill.get(key) for key in ("ref", "version", "content_hash")},
        "context_asset_version_ids": [
            str(item.get("asset_version_id") or "") for item in context
        ],
        "knowledge_content_hashes": [
            str(item.get("content_hash") or "")
            for item in knowledge
            if isinstance(item, Mapping)
        ],
        "allowed_tools": list(allowed),
        "output_schema_ref": str(schema.get("ref") or ""),
        "output_schema_hash": str(schema.get("content_hash") or ""),
        "embedding_output_contract": (
            dict(embedding_output_contract)
            if isinstance(embedding_output_contract, Mapping)
            else None
        ),
        "provider_view": {
            **({"exact_context_references": exact_reference_proof} if exact_reference_proof else {}),
            "task_contract_version": task_view["contract_version"],
            "context_contract_version": context_view["contract_version"],
            "selection_explanation": selection_explanation or context_view.get(
                "selection_explanation",
                {
                    "policy": "accepted-boundary-only",
                    "selected_count": 1,
                    "omitted_count": 0,
                },
            ),
            "component_characters": component_characters,
            "component_estimated_tokens": component_tokens,
            "component_utf8_byte_upper_bounds": component_bytes,
            "component_hashes": component_hashes,
            "component_accounting_precision": "OBSERVABILITY_ONLY_ESTIMATE",
            "component_estimator": "ConservativeTokenEstimator:utf8-third-ceiling.v1",
            "provider_admission_uses_component_estimates": False,
            "authority_context_estimated_tokens": authority_context_tokens,
            "provider_context_estimated_tokens": provider_context_tokens,
            "context_projection_ratio": round(
                provider_context_tokens / max(1, authority_context_tokens), 6
            ),
            "rendered_prompt_to_semantic_input_ratio": round(
                component_tokens["fully_rendered_prompt"] / semantic_input_tokens,
                6,
            ),
            "representation_policy": "authority-projection-task-provider-v2"
            if compact_contract
            else "authority-projection-task-provider-v1",
        },
    }
    return prompt, evidence


def _materialize_source_intelligence_prompt(
    *,
    request: ExecutionRequest | None = None,
    target_scope: Mapping[str, Any] | None = None,
    stage: str,
    inputs: Mapping[str, Any],
    materialization: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """SECURITY: Render Source analysis bytes only in Provider memory, never in PostgreSQL."""
    if request is not None:
        resolved_target_scope = request.target_scope.to_dict()
    elif target_scope is not None:
        resolved_target_scope = TargetScope.from_dict(target_scope).to_dict()
    else:
        raise KernelError(
            "SOURCE_PROVIDER_TARGET_SCOPE_MISSING",
            "Source Provider prompt requires a frozen target scope",
        )
    system = materialization.get("system_instruction")
    skill = materialization.get("skill")
    template = materialization.get("prompt_template")
    output_schema = materialization.get("output_schema")
    tool_permissions = materialization.get("tool_permissions")
    if not all(
        isinstance(item, Mapping)
        for item in (system, skill, template, output_schema, tool_permissions)
    ):
        raise KernelError(
            "SOURCE_CAPABILITY_MATERIALIZATION_INVALID",
            "Source execution materialization is incomplete",
        )
    assert isinstance(system, Mapping)
    assert isinstance(skill, Mapping)
    assert isinstance(template, Mapping)
    assert isinstance(output_schema, Mapping)
    assert isinstance(tool_permissions, Mapping)
    texts = tuple(
        str(item.get("text") or "").strip() for item in (system, skill, template)
    )
    schema_content = output_schema.get("content")
    if (
        any(not text for text in texts)
        or not isinstance(schema_content, Mapping)
        or tuple(tool_permissions.get("allowed") or ()) != ("model.provider.invoke",)
    ):
        raise KernelError(
            "SOURCE_CAPABILITY_MATERIALIZATION_INVALID",
            "Source prompt, schema, or Tool policy is incomplete",
        )
    provider_inputs = dict(inputs)
    if inputs.get("observation_boundary"):
        boundary = inputs["observation_boundary"]
        provider_inputs = {key: value for key, value in inputs.items() if key in {
            "task_id", "mode", "evaluation_case_id", "synthetic_candidate",
            "source_segments", "evidence_span_ids", "reference_context_extract",
            "reference_semantic_task",
        }}
        provider_inputs["chapter_bindings"] = [{key: binding[key] for key in ("evidence_span_id", "chapter")} for binding in inputs.get("chapter_bindings", [])]
        provider_inputs["observation_limit"] = {"mode": boundary["mode"], "visible_chapters": sorted({span["chapter"] for span in boundary["spans"]})}
    from novel_forge.modules.source_import.execution_contracts import source_analysis_output_instruction

    prompt = "\n\n".join(
        (
            "<system_instruction>\n" + texts[0] + "\n</system_instruction>",
            "<governed_skill>\n" + texts[1] + "\n</governed_skill>",
            "<prompt_template>\n" + texts[2] + "\n</prompt_template>",
            "<target_scope>\n"
            + _canonical(resolved_target_scope)
            + "\n</target_scope>",
            "<source_analysis_input>\n"
            + _canonical(provider_inputs)
            + "\n</source_analysis_input>",
            "<output_schema>\n" + _canonical(schema_content) + "\n</output_schema>",
            source_analysis_output_instruction(stage, provider_inputs),
        )
    )
    prompt_hash = "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    source_components = {
        "system_instruction": texts[0],
        "governed_skill": texts[1],
        "prompt_template": texts[2],
        "target_scope": _canonical(resolved_target_scope),
        "source_analysis_input": _canonical(provider_inputs),
        "tool_policy": _canonical(tool_permissions),
        "output_schema": _canonical(schema_content),
        "fully_rendered_prompt": prompt,
    }
    return prompt, {
        "materialization_hash": str(materialization.get("materialization_hash") or ""),
        "reusable_prefix_bytes": len(prompt.split("</prompt_template>", 1)[0].encode())
        + len("</prompt_template>".encode()),
        "fully_rendered_prompt_hash": prompt_hash,
        "stage": stage,
        "source_bytes_transient_only": True,
        "source_bytes_persisted_in_external_effect": False,
        "component_hashes": {
            key: "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
            for key, value in source_components.items()
        },
        "component_utf8_byte_upper_bounds": {
            key: len(value.encode("utf-8")) for key, value in source_components.items()
        },
        "component_accounting_precision": "OBSERVABILITY_ONLY_UPPER_BOUND",
        "provider_admission_uses_component_estimates": False,
        "system_instruction": {
            key: system.get(key) for key in ("ref", "version", "content_hash")
        },
        "prompt_template": {
            key: template.get(key) for key in ("ref", "version", "content_hash")
        },
        "skill": {key: skill.get(key) for key in ("ref", "version", "content_hash")},
        "output_schema_ref": str(output_schema.get("ref") or ""),
        "output_schema_hash": str(output_schema.get("content_hash") or ""),
        "allowed_tools": ["model.provider.invoke"],
    }


# COMPATIBILITY: Chapter callers retain these aliases; cross-domain composition
# uses the production-semantic name.
PostgresChapterExecutionPayloadResolver = PostgresProductionExecutionPayloadResolver
_materialize_chapter_codex_prompt = _materialize_production_codex_prompt


@dataclass(frozen=True, slots=True)
class ChapterExecutionGatewaySession:
    gateway: ProductionExecutionGateway
    evidence_store: ExecutionRecordStore


@dataclass(frozen=True, slots=True)
class _RecoveryAuthorizedGatewayAdapter:
    adapter: "ProductionExecutionGatewayExternalEffectAdapter"
    authorization: ExecutionRecoveryAuthorization

    @property
    def provider(self) -> str:
        return self.adapter.provider

    @property
    def reconciliation_mode(self) -> str:
        return self.adapter.reconciliation_mode

    @property
    def production_execution_gateway_backed(self) -> bool:
        return self.adapter.production_execution_gateway_backed

    @property
    def capability_profile(self) -> ProviderCapabilityProfile:
        return self.adapter.capability_profile

    @property
    def cost_accounting_basis(self) -> str:
        return self.adapter.cost_accounting_basis

    @property
    def account_authorization_ref(self) -> str:
        return self.adapter.account_authorization_ref

    @property
    def provider_call_caps(self) -> dict[str, int]:
        return dict(self.adapter.provider_call_caps)

    @property
    def provider_token_caps(self) -> dict[str, int]:
        return dict(self.adapter.provider_token_caps)

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        return self.adapter._invoke(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            reconciliation=False,
            recovery_authorization=self.authorization,
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        return self.adapter._invoke(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            reconciliation=True,
            recovery_authorization=self.authorization,
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        return self.adapter._cancel(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            provider_request_id=provider_request_id,
            recovery_authorization=self.authorization,
        )

    def record_authorization(self) -> None:
        self.adapter._record_recovery_authorization(self.authorization)


class ProductionExecutionGatewayExternalEffectAdapter:
    provider = "production_execution_gateway"
    reconciliation_mode = "query"
    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        database_url: str,
        routes: Mapping[str, ChapterExecutionRoute],
        session_factory: Callable[[str], ChapterExecutionGatewaySession],
        provider_adapters: Mapping[str, Any] | None = None,
        cost_accounting_basis: str = "PRICED",
        account_authorization_ref: str = "",
        provider_call_caps: Mapping[str, int] | None = None,
        provider_token_caps: Mapping[str, int] | None = None,
        resource_control_version: str = "",
    ) -> None:
        route_names = set(routes)
        if not _STAGES.issubset(route_names) or not route_names.issubset(
            _STAGES | _OPTIONAL_DOMAIN_STAGES
        ):
            raise ValueError("all governed execution stages must use the gateway")
        self.database_url = database_url
        self.routes = dict(routes)
        self.recovery_authorizations = PostgresExecutionRecoveryAuthorizationStore(
            database_url
        )
        self.session_factory = session_factory
        self.provider_adapters = dict(provider_adapters or {})
        self.cost_accounting_basis = cost_accounting_basis.strip().upper()
        self.account_authorization_ref = account_authorization_ref.strip()
        self.provider_call_caps = {
            str(key): int(value) for key, value in (provider_call_caps or {}).items()
        }
        self.provider_token_caps = {
            str(key): int(value) for key, value in (provider_token_caps or {}).items()
        }
        if self.cost_accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}:
            raise ValueError("unsupported Production Gateway cost accounting basis")
        if (
            self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
            and not self.account_authorization_ref
        ):
            raise ValueError("account entitlement requires an authorization reference")
        if resource_control_version not in {"", "billing-channel-resources.v1"}:
            raise ValueError("unsupported billing channel resource contract")
        self.resource_control_version = resource_control_version
        if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT" and not resource_control_version and (
            not self.provider_call_caps or not self.provider_token_caps
        ):
            raise ValueError(
                "account entitlement requires aggregate Provider call and token caps"
            )
        self.execution_binders: dict[str, Any] = {}
        self.provider_router: Any = None
        self._sessions: dict[str, ChapterExecutionGatewaySession] = {}
        self._lock = Lock()
        all_real = all(
            item.real_provider_validation_eligible for item in routes.values()
        )
        # WHY: This is the ExternalEffect-facing composite adapter capability.  Its
        # stable execution id plus persistent local receipt prevents duplicate
        # submission even though Codex itself exposes no remote idempotency key.
        gateway_submission_idempotent = True
        self.capability_profile = ProviderCapabilityProfile(
            provider=self.provider,
            control_level=(
                ProviderControlLevel.V2_CONTROLLED
                if all_real
                else ProviderControlLevel.FIXTURE_CONTROLLED
            ),
            supports_request_timeout=True,
            supports_provider_idempotency=gateway_submission_idempotent,
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=True,
            supports_cost_receipt=True,
            reconciliation_mode=self.reconciliation_mode,
            real_provider_validation_eligible=all_real,
            supports_usage_pricing=bool(self.provider_adapters) and all(
                getattr(adapter.capability_profile, "supports_usage_pricing", False)
                or adapter.capability_profile.supports_cost_receipt
                for adapter in self.provider_adapters.values()
            ),
        )

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        return self._invoke(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            reconciliation=False,
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        return self._invoke(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            reconciliation=True,
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        return self._cancel(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            provider_request_id=provider_request_id,
            recovery_authorization=None,
        )

    def _cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
        recovery_authorization: ExecutionRecoveryAuthorization | None,
    ) -> ProviderResult:
        binding, session = self._binding_and_session(
            stable_idempotency_key, capability, request_payload
        )
        try:
            if recovery_authorization is None:
                handle = session.gateway.submit(binding.request)
            else:
                record = session.evidence_store.find_record(
                    binding.request.execution_id
                )
                if record is None:
                    raise ValueError(
                        "cannot cancel an execution without persisted Provider identity"
                    )
                self._record_recovery_authorization(recovery_authorization)
                handle = record.handle
            if (
                provider_request_id
                and handle.provider_request_id != provider_request_id
            ):
                raise ValueError(
                    "Provider request identity changed during cancellation"
                )
            result = (
                session.gateway.cancel(handle, "authority cancellation")
                if recovery_authorization is None
                else session.gateway.cancel_existing_execution(
                    binding.request,
                    handle,
                    recovery_authorization,
                    "authority cancellation",
                )
            )
        except ExternalEffectAdapterError:
            raise
        except Exception as exc:
            raise ExternalEffectAdapterError(
                f"gateway cancellation failed: {type(exc).__name__}: {exc}",
                request_sent=bool(provider_request_id),
            ) from exc
        outcome = {
            CancellationOutcome.CANCELLED: "cancelled",
            CancellationOutcome.ALREADY_COMPLETED: "already_completed",
            CancellationOutcome.UNSUPPORTED: "unsupported",
        }.get(result.outcome, "ambiguous")
        return ProviderResult(
            outcome,
            handle.backend_execution_id,
            {
                "production_execution_cancellation": result.to_dict(),
                "route_snapshot_id": binding.route_snapshot.route_snapshot_id,
                "transport": handle.transport.value,
            },
            handle.provider_request_id or "",
        )

    def model_id_for_stage(self, stage: str) -> str:
        route = self.routes.get(stage)
        return "" if route is None else route.model_profile.model_id

    def saved_result_evidence(self, request: ExecutionRequest, handle: ExecutionHandle, result: Any) -> dict[str, Any]:
        session = self._session(request.project_id)
        route = session.gateway.admission.resolve_route(request)
        manifest = session.gateway.admission.contracts.input_manifest(request.input_manifest_ref)
        return self._evidence(binding=ChapterExecutionBinding(request, route, manifest),
            session=session, handle=handle, result=result)

    def session_for_project(self, project_id: str) -> ChapterExecutionGatewaySession:

        return self._session(project_id)

    def register_execution_binder(self, domain: str, binder: Any) -> None:
        if self.provider_router is not None:
            binder.provider_router = self.provider_router

        normalized = domain.strip().lower()
        if not normalized or normalized in self.execution_binders:
            raise ValueError("execution binder domain is missing or already registered")
        if not callable(getattr(binder, "bind", None)):
            raise ValueError("execution binder must materialize a frozen request")
        self.execution_binders[normalized] = binder

    def provider_id_for_stage(self, stage: str) -> str:
        route = self.routes.get(stage)
        return "" if route is None else route.model_profile.model_provider

    def for_recovery(
        self,
        *,
        execution_id: str,
        external_effect_id: str,
        operation_id: str,
        attempt_id: str,
        execution_fencing_token: int,
        recovery_fencing_token: int,
        recovery_worker_id: str,
        action: ExecutionRecoveryAction,
        trace_id: str,
        correlation_id: str,
    ) -> _RecoveryAuthorizedGatewayAdapter:
        token = _identity_token(
            ":".join(
                (
                    execution_id,
                    str(recovery_fencing_token),
                    action.value,
                )
            )
        )
        return _RecoveryAuthorizedGatewayAdapter(
            self,
            ExecutionRecoveryAuthorization(
                authorization_id=f"execution-recovery:{token}",
                execution_id=execution_id,
                external_effect_id=external_effect_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                execution_fencing_token=execution_fencing_token,
                recovery_fencing_token=recovery_fencing_token,
                recovery_worker_id=recovery_worker_id,
                action=action,
                trace_id=trace_id,
                correlation_id=correlation_id,
            ),
        )

    def _invoke(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        reconciliation: bool,
        recovery_authorization: ExecutionRecoveryAuthorization | None = None,
    ) -> ProviderResult:
        if recovery_authorization is not None:
            metadata = request_payload.get("_production_execution")
            if not isinstance(metadata, Mapping):
                raise ExternalEffectAdapterError(
                    "recovery payload has no execution metadata",
                    request_sent=False,
                )
            request_payload = {
                **request_payload,
                "_production_execution": {
                    **metadata,
                    "snapshot_fencing_token": (
                        recovery_authorization.recovery_fencing_token
                    ),
                    "snapshot_worker_id": (recovery_authorization.recovery_worker_id),
                },
            }
        binding, session = self._binding_and_session(
            stable_idempotency_key, capability, request_payload
        )
        request_sent = False
        try:
            if recovery_authorization is None:
                handle = session.gateway.submit(binding.request)
                request_sent = True
                result = session.gateway.reconcile(handle)
            else:
                record = session.evidence_store.find_record(
                    binding.request.execution_id
                )
                authorization = recovery_authorization
                if record is None:
                    if (
                        authorization.action
                        is not ExecutionRecoveryAction.DISPATCH_PLANNED
                    ):
                        raise ValueError(
                            "Provider identity is absent; query must remain unresolved"
                        )
                    self._record_recovery_authorization(authorization)
                    handle = session.gateway.resume_planned_execution(
                        binding.request,
                        authorization,
                    )
                    request_sent = True
                    authorization = replace(
                        authorization,
                        authorization_id=(authorization.authorization_id + ":consume"),
                        action=ExecutionRecoveryAction.CONSUME_RESULT,
                    )
                else:
                    handle = record.handle
                    request_sent = bool(
                        handle.provider_request_id
                        or handle.external_request_id
                        or record.raw_evidence.get("submission_phase")
                    )
                    if authorization.action is ExecutionRecoveryAction.DISPATCH_PLANNED:
                        authorization = replace(
                            authorization,
                            authorization_id=(
                                authorization.authorization_id + ":consume"
                            ),
                            action=ExecutionRecoveryAction.CONSUME_RESULT,
                        )
                self._record_recovery_authorization(authorization)
                result = session.gateway.recover_existing_execution(
                    binding.request,
                    handle,
                    authorization,
                )
        except ExternalEffectAdapterError:
            raise
        except Exception as exc:
            recovered = session.evidence_store.find_record(binding.request.execution_id)
            submission_phase = (
                str(recovered.raw_evidence.get("submission_phase") or "")
                if recovered is not None
                else ""
            )
            request_sent = request_sent or submission_phase in {
                "PROVIDER_INVOKING",
                "PROVIDER_OUTCOME_UNKNOWN",
                "PROVIDER_RESULT_OBSERVED",
                "PROVIDER_RESULT_RECORDED",
                "PROCESS_STARTING",
                "PROCESS_OUTCOME_UNKNOWN",
                "PROCESS_RESULT_RECORDED",
            }
            raise ExternalEffectAdapterError(
                f"gateway execution failed: {type(exc).__name__}: {exc}",
                request_sent=request_sent,
            ) from exc
        outcome = self._external_outcome(result.outcome, reconciliation=reconciliation)
        evidence = self._evidence(
            binding=binding,
            session=session,
            handle=handle,
            result=result,
        )
        if local_cli_remote_outcome_unknown(
            transport=handle.transport, outcome=result.outcome,
            started_at=result.started_at, usage_receipt_ref=result.usage_receipt_ref,
            failure_code=evidence["production_execution"]["process_evidence"].get("failure_code"),
        ):
            evidence["external_state_unknown"] = True
            evidence["recovery_instruction"] = "Reconcile the original receipt; local termination does not confirm remote cancellation"
            outcome = "ambiguous" if reconciliation else "unknown"
        return ProviderResult(
            outcome,
            handle.backend_execution_id,
            evidence,
            handle.provider_request_id or "",
        )

    def _record_recovery_authorization(
        self,
        authorization: ExecutionRecoveryAuthorization,
    ) -> None:
        self.recovery_authorizations.record(authorization)

    def _binding_and_session(
        self,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> tuple[ChapterExecutionBinding, ChapterExecutionGatewaySession]:
        metadata = request_payload.get("_production_execution")
        project_id = (
            str(metadata.get("project_id") or "")
            if isinstance(metadata, Mapping)
            else ""
        )
        operation_id = (
            str(metadata.get("operation_id") or "")
            if isinstance(metadata, Mapping)
            else ""
        )
        external_effect_id = str(request_payload.get("external_effect_id") or "")
        if not external_effect_id and project_id and operation_id:
            external_effect_id = self._effect_id(
                project_id, operation_id, stable_idempotency_key
            )
        if not project_id or not external_effect_id:
            raise ExternalEffectAdapterError(
                "gateway ExternalEffect identity is incomplete", request_sent=False
            )
        binding_domain = (
            str(metadata.get("execution_binding_domain") or "chapter").strip().lower()
            if isinstance(metadata, Mapping)
            else "chapter"
        )
        binder = self.execution_binders.get(binding_domain)
        if binder is None:
            raise ExternalEffectAdapterError(
                f"no execution binder is registered for {binding_domain}",
                request_sent=False,
            )
        binding = binder.bind(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
            external_effect_id=external_effect_id,
        )
        return binding, self._session(project_id)

    def _session(self, project_id: str) -> ChapterExecutionGatewaySession:
        with self._lock:
            session = self._sessions.get(project_id)
            if session is None:
                session = self.session_factory(project_id)
                self._sessions[project_id] = session
            return session

    def close_sessions(self) -> None:

        with self._lock:
            self._sessions.clear()

    def _effect_id(self, project_id: str, operation_id: str, stable_key: str) -> str:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT external_effect_id FROM authority_external_effect
                    WHERE project_id = %s AND operation_id = %s
                      AND stable_idempotency_key = %s
                    """,
                    [project_id, operation_id, stable_key],
                )
                row = cursor.fetchone()
        if row is None:
            raise ExternalEffectAdapterError(
                "gateway ExternalEffect does not exist", request_sent=False
            )
        return str(row[0])

    def _evidence(
        self,
        *,
        binding: ChapterExecutionBinding,
        session: ChapterExecutionGatewaySession,
        handle: ExecutionHandle,
        result: Any,
    ) -> dict[str, Any]:
        execution_record = session.evidence_store.get_record(
            binding.request.execution_id
        )
        raw_evidence = execution_record.raw_evidence
        fixture_only = (
            handle.transport.value == "SCRIPTED_FIXTURE"
            or raw_evidence.get("fixture_protocol_only") is True
        )
        remote_receipt = execution_record.provider_result
        process_receipt = execution_record.process_receipt
        receipt_proves_call = bool(
            not fixture_only
            and raw_evidence.get("real_model_call") is not False
            and (
                (
                    handle.transport.value == "REMOTE_PROVIDER_API"
                    and remote_receipt is not None
                    and remote_receipt.request_sent
                    and remote_receipt.handle is not None
                    and handle.provider_request_id
                    == remote_receipt.handle.provider_request_id
                    and bool(handle.provider_request_id)
                    and remote_receipt.evidence.get("fixture_protocol_only") is not True
                    and remote_receipt.evidence.get("real_model_call") is not False
                )
                or (
                    handle.transport.value == "LOCAL_CLI_REMOTE_INFERENCE"
                    and process_receipt is not None
                    and process_receipt.receipt_id == handle.local_execution_receipt_id
                    and process_receipt.execution_id == binding.request.execution_id
                    and raw_evidence.get("terminal_event_observed") is True
                    and (raw_evidence.get("usage") or {}).get("measurement") == "MEASURED"
                )
            )
        )
        frozen_eligible = False
        if receipt_proves_call:
            runtime = get_database_runtime(self.database_url)
            with runtime.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """SELECT provider_capability_profile,request_payload,model_id
                           FROM authority_external_effect
                           WHERE external_effect_id=%s AND project_id=%s AND operation_id=%s""",
                        [binding.request.external_effect_id, binding.request.project_id,
                         binding.request.operation_id],
                    )
                    frozen = cursor.fetchone()
            if frozen is not None:
                capability, request_payload, model_id = frozen
                identity = (request_payload.get("_production_execution") or {}).get(
                    "capability_runtime", {}).get("provider_request_identity") or {}
                frozen_eligible = bool(
                    (capability or {}).get("real_provider_validation_eligible") is True
                    and request_payload.get("stage") == binding.request.stage
                    and model_id == binding.route_snapshot.model_id
                    and (not identity or (
                        identity.get("provider") == binding.route_snapshot.model_provider
                        and identity.get("model") == binding.route_snapshot.model_id
                    ))
                )
        evidence: dict[str, Any] = {
            "provider_id": binding.route_snapshot.model_provider,
            "model_id": binding.route_snapshot.model_id,
            "prompt_version": binding.input_manifest.prompt_bundle_version,
            "skill_version": binding.input_manifest.skill_bundle_version,
            "real_model_call": receipt_proves_call and frozen_eligible,
            "fixture_protocol_only": fixture_only,
            "production_verified": False,
            "production_execution": {
                "execution_request": binding.request.to_dict(),
                "execution_handle": handle.to_dict(),
                "execution_result": result.to_dict(),
                "route_snapshot": binding.route_snapshot.to_dict(),
                "input_manifest": binding.input_manifest.to_dict(),
                "validation_manifest_ref": result.validation_report_ref or "",
                "commit_manifest_required": True,
                "process_evidence": dict(execution_record.raw_evidence),
            },
        }
        capability_evidence = execution_record.raw_evidence.get("capability_evidence")
        if isinstance(capability_evidence, Mapping):
            evidence["capability_runtime"] = dict(capability_evidence)
        tool_evidence = execution_record.raw_evidence.get("tools")
        if isinstance(tool_evidence, Mapping):
            evidence["tools"] = dict(tool_evidence)
        if result.normalized_output_ref:
            raw = session.evidence_store.read_evidence(result.normalized_output_ref)
            evidence["result"] = normalize_model_output(
                binding.request.stage, raw,
                output_schema_ref=str(
                    execution_record.frozen_output_contract.get("output_schema_version")
                    or execution_record.raw_evidence.get("output_schema_version")
                    or binding.route_snapshot.output_schema_ref
                ),
            )
        if result.output_manifest_ref:
            evidence["production_execution"]["output_manifest"] = (
                session.evidence_store.read_evidence(result.output_manifest_ref)
            )
        if result.validation_report_ref:
            evidence["production_execution"]["validation_manifest"] = (
                session.evidence_store.read_evidence(result.validation_report_ref)
            )
        if result.usage_receipt_ref:
            evidence["usage"] = session.evidence_store.read_evidence(
                result.usage_receipt_ref
            )
        else:
            evidence["usage"] = {
                "availability": "UNAVAILABLE",
                "reason": "execution_result_has_no_usage_receipt",
            }
        if result.cost_receipt_ref:
            evidence["cost"] = session.evidence_store.read_evidence(
                result.cost_receipt_ref
            )
        else:
            evidence["cost"] = {
                "availability": "UNAVAILABLE",
                "reason": "execution_result_has_no_cost_receipt",
            }
        return evidence

    @staticmethod
    def _external_outcome(outcome: ExecutionOutcome, *, reconciliation: bool) -> str:
        if outcome is ExecutionOutcome.SUCCEEDED:
            return "success"
        if outcome in {
            ExecutionOutcome.RETRYABLE_FAILURE,
            ExecutionOutcome.TIMED_OUT,
            ExecutionOutcome.CORRUPT_RESULT,
        }:
            return "not_found" if reconciliation else "retryable_failure"
        if outcome is ExecutionOutcome.FINAL_FAILURE:
            return "failed_final" if reconciliation else "final_failure"
        if outcome is ExecutionOutcome.CANCELLED:
            return "cancelled"
        if outcome in {
            ExecutionOutcome.ACCEPTED,
            ExecutionOutcome.RUNNING,
            ExecutionOutcome.UNKNOWN,
            ExecutionOutcome.ORPHANED,
        }:
            return "ambiguous" if reconciliation else "unknown"
        return "failed_final" if reconciliation else "final_failure"


__all__ = [
    "ChapterExecutionBinding",
    "ChapterExecutionGatewaySession",
    "ChapterExecutionRoute",
    "ExternalEffectExecutionSessionStore",
    "PostgresChapterExecutionContractBinder",
    "PostgresChapterExecutionPayloadResolver",
    "PostgresProductionExecutionPayloadResolver",
    "PostgresRetrievalProjectionExecutionContractBinder",
    "ProductionExecutionGatewayExternalEffectAdapter",
    "chapter_stage_capability",
    "default_chapter_fixture_response",
]
