"""Chapter ExternalEffect bridge to the unified ProductionExecutionGateway.

The bridge owns no Attempt, retry, budget, or receipt state.  It freezes execution
contracts as ordinary Authority AssetVersions and reconstructs gateway submissions
from the PostgreSQL ExternalEffect after a worker restart.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping, Protocol

from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.capability_pack_authority.domain import (
    CapabilityPackAttemptSnapshot,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.production_execution import (
    ArtifactPointer,
    CapabilityId,
    CancellationOutcome,
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
    PromptBundle,
    ProductionExecutionGateway,
    ResolvedExecutionPayload,
    RoutePolicy,
    RouteSnapshot,
    SkillBundle,
    SourcePolicy,
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
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)


_STAGES = frozenset(
    {
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
        "reader_outcome",
    }
)

_STAGE_CAPABILITIES = {
    "draft": CapabilityId.PROSE_CHAPTER_DRAFT,
    "review": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "revision": CapabilityId.REVISION_CHAPTER_REVISE,
    "rereview": CapabilityId.REVIEW_CHAPTER_EVALUATE,
    "canon_extraction": CapabilityId.CANON_EXTRACT,
    "quality_structural": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "quality_commercial": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "quality_source_originality": CapabilityId.QUALITY_ORIGINALITY_JUDGE,
    "quality_longform": CapabilityId.QUALITY_INTRINSIC_JUDGE,
    "quality_platform": CapabilityId.QUALITY_PLATFORM_JUDGE,
    "reader_outcome": CapabilityId.QUALITY_READER_OUTCOME_JUDGE,
}


def chapter_stage_capability(stage: str) -> CapabilityId:
    try:
        return _STAGE_CAPABILITIES[stage]
    except KeyError as exc:
        raise ValueError(f"unsupported Chapter execution stage: {stage}") from exc


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _identity_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


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

    def __post_init__(self) -> None:
        if self.stage not in _STAGES:
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


class PostgresChapterExecutionContractBinder:
    """Materialize immutable per-Attempt contracts through Authority AssetVersion."""

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
    ) -> None:
        if not database_url or set(routes) != _STAGES:
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
        self.pack_resolver = CapabilityPackRuntimeResolver(database_url)

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
            snapshot_fencing_token = int(
                metadata.get("snapshot_fencing_token") or fencing_token
            )
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
        definition = default_capability_registry().resolve(
            chapter_stage_capability(stage)
        )
        target_scope = {
            "scope_kind": "chapter",
            "scope_id": f"{book_id}:chapter:{chapter}",
            "project_id": project_id,
            "book_id": book_id,
            "chapter_number": chapter,
        }
        artifacts = self._artifacts(metadata)
        attempt_pack_snapshot = self._resolve_pack_snapshot(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            execution_fencing_token=fencing_token,
            worker_id=worker_id,
            snapshot_creation_fencing_token=snapshot_fencing_token,
            snapshot_creation_worker_id=str(
                metadata.get("snapshot_worker_id") or worker_id
            ),
            stage=stage,
            graph=graph,
            route=route,
        )
        pack_snapshot = (
            attempt_pack_snapshot.execution_snapshot
            if attempt_pack_snapshot is not None
            else None
        )
        context_ref = next(
            (
                item.artifact_ref
                for item in artifacts
                if item.artifact_type == "context_bundle"
            ),
            f"context:none:{operation_id}",
        )
        token = _identity_token(f"{project_id}:{operation_id}:{attempt_id}:{stage}")
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
            )
        else:
            context_policy_ref = pack_snapshot.context_policy_ref
            context_policy_payload = json.loads(
                pack_snapshot.context_policy_payload_json
            )
            tool_policy_payload = json.loads(pack_snapshot.tool_policy_payload_json)
            prompt_version = pack_snapshot.prompt_bundle_ref
            skill_version = pack_snapshot.skill_version
            system_instruction_hash = (
                pack_snapshot.prompt_system_instruction_hash
            )
            template_hash = pack_snapshot.prompt_template_hash
            skill_content_hash = pack_snapshot.skill_content_hash
            prompt_compiler_version = pack_snapshot.prompt_compiler_version
            context_maximum_tokens = int(
                context_policy_payload.get("max_tokens") or 0
            )
            context_allowed_asset_types = tuple(
                str(value)
                for value in context_policy_payload.get("allowed_asset_types") or ()
            )
        context_policy = ContextPolicy(
            policy_id=context_policy_ref,
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
        validation_policy = ValidationPolicy(
            policy_id=definition.validation_policy_ref,
            policy_version="v1",
            structural_schema_ref=definition.output_schema_ref,
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
                "generation_candidate"
                if stage == "draft"
                else "revision_candidate"
                if stage == "revision"
                else "canon_candidate"
                if stage == "canon_extraction"
                else "quality_judge_candidate"
                if stage.startswith("quality_")
                else "reader_outcome_candidate"
                if stage == "reader_outcome"
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
            output_schema_ref=definition.output_schema_ref,
            skill_bundle_ref=skill_ref,
            context_policy_ref=context_policy_ref,
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
            route_decision_id=f"route-decision:{token}",
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
            model_provider=route.model_profile.model_provider,
            model_id=route.model_profile.model_id,
            requested_reasoning_effort=route.model_profile.reasoning_effort,
            reasoning_effort=route.model_profile.reasoning_effort,
            prompt_bundle_ref=prompt_ref,
            skill_bundle_ref=skill_ref,
            context_bundle_ref=context_ref,
            output_schema_ref=route.output_schema_ref,
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
                    pack_snapshot.context_policy_ref if pack_snapshot else ""
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
            logical_ref=validation_policy.policy_id,
            asset_type="execution_validation_policy",
            contract={
                **validation_policy.to_dict(),
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
            logical_ref=commit_policy.policy_id,
            asset_type="execution_commit_policy",
            contract=commit_policy.to_dict(),
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
                "allowed_tools": list(
                    tool_policy_payload.get("explicit_tool_refs") or ()
                ),
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
                    attempt_pack_snapshot.snapshot_id
                    if attempt_pack_snapshot
                    else ""
                ),
                "capability_pack_attempt_snapshot_hash": (
                    attempt_pack_snapshot.snapshot_hash
                    if attempt_pack_snapshot
                    else ""
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
            resource_claims=(f"chapter:{chapter}", f"stage:{stage}"),
            timeout_policy_ref=definition.timeout_policy_ref,
            budget_policy_ref=definition.budget_policy_ref,
            permission_policy_ref=definition.permission_policy_ref,
            validation_policy_ref=definition.validation_policy_ref,
            commit_policy_ref=definition.commit_policy_ref,
            stable_idempotency_key=stable_idempotency_key,
            origin_chain=("chapter.slice.run", graph["definition_name"]),
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
        if not self.capability_pack_id:
            return None
        try:
            return self.pack_resolver.freeze_attempt_snapshot(
                CapabilityPackResolutionRequest(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_id=book_id,
                    workflow_definition_ref="chapter_authority_slice@2.2.0",
                    workflow_node_id=stage,
                    environment=self.pack_environment,
                    runtime_profile=self.pack_runtime_profile,
                    release_channel=self.pack_release_channel,
                    release_sha=route.release_sha,
                    operation_definition_ref=(
                        f"{graph['definition_name']}@{graph['definition_version']}"
                    ),
                    pack_id=self.capability_pack_id,
                ),
                operation_id=operation_id,
                attempt_id=attempt_id,
                execution_fencing_token=execution_fencing_token,
                worker_id=worker_id,
                snapshot_creation_fencing_token=(
                    snapshot_creation_fencing_token
                ),
                snapshot_creation_worker_id=snapshot_creation_worker_id,
            )
        except KernelError as exc:
            if exc.code in {
                "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED",
                "CAPABILITY_PACK_SCOPE_NOT_FOUND",
            } and not self.pack_required:
                return None
            raise

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
    ) -> None:
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
            return
        token = _identity_token(f"{project_id}:{logical_ref}")
        self.writer.materialize_output(
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


class ChapterFixtureResponseFactory(Protocol):
    def __call__(self, stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]: ...


class ExternalEffectExecutionSessionStore:
    """Transient gateway cache; PostgreSQL ExternalEffect remains recovery authority.

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


def default_chapter_fixture_response(
    stage: str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Deterministic chapter fixture used only by SCRIPTED_FIXTURE routes."""

    if stage == "draft":
        plan = inputs.get("plan") if isinstance(inputs.get("plan"), Mapping) else {}
        return {
            "text": (
                f"{plan.get('premise') or 'The chapter objective advances.'} "
                "The choice is public, and the irreversible cost is witnessed."
            )
        }
    if stage == "review":
        return {
            "score": 72,
            "issues": [
                {
                    "code": "COST_NOT_CONCRETE",
                    "severity": "blocking",
                    "message": "Make the irreversible cost concrete in the scene.",
                }
            ],
        }
    if stage == "revision":
        draft = inputs.get("draft") if isinstance(inputs.get("draft"), Mapping) else {}
        return {
            "text": (
                f"{draft.get('text') or 'The choice is made.'} "
                "The protagonist gives up the only safe route home before the witnesses leave."
            ),
            "resolved_issue_codes": ["COST_NOT_CONCRETE"],
        }
    if stage == "rereview":
        return {"score": 90, "issues": []}
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
        empty_fields = {
            "character_state_changes": [],
            "relationship_changes": [],
            "timeline_events": [],
            "foreshadow_changes": [],
            "promise_changes": [],
            "reward_changes": [],
            "world_rule_usages": [],
            "power_state_changes": [],
            "narrative_pattern_fingerprints": [],
            "theme_movements": [],
            "antagonist_pressure_changes": [],
        }
        return {
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


class PostgresChapterExecutionPayloadResolver:
    """Resolve the frozen ExternalEffect payload; optionally materialize a fixture reply."""

    def __init__(
        self,
        database_url: str,
        *,
        fixture_response_factory: ChapterFixtureResponseFactory | None = None,
        working_directory: str | Path = ".",
        command: tuple[str, ...] = (),
    ) -> None:
        self.database_url = database_url
        self.fixture_response_factory = fixture_response_factory
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
                    SELECT request_payload, request_timeout_seconds, request_hash
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
        inputs = payload.get("input")
        if stage != request.stage or not isinstance(inputs, Mapping):
            raise ValueError("frozen Chapter ExternalEffect payload changed")
        if self.fixture_response_factory is None:
            resolved_payload: dict[str, Any] = {
                "stage": stage,
                "input": dict(inputs),
                "prompt_bundle_ref": admission.route_snapshot.prompt_bundle_ref,
                "skill_bundle_ref": admission.route_snapshot.skill_bundle_ref,
                "output_schema_ref": admission.route_snapshot.output_schema_ref,
            }
        else:
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
        return ResolvedExecutionPayload(
            request_payload=resolved_payload,
            input_text=_canonical({"stage": stage, "input": inputs}),
            working_directory=self.working_directory,
            timeout_seconds=int(row[1] or 30),
            output_schema_version=admission.route_snapshot.output_schema_ref,
            command=self.command,
        )


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
    """Map the existing ExternalEffect protocol to one Attempt-bound gateway call."""

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
        capability_pack_id: str = "",
        pack_environment: str = "development",
        pack_runtime_profile: str = "development",
        pack_release_channel: str = "VALIDATION",
        pack_required: bool = False,
    ) -> None:
        if set(routes) != _STAGES:
            raise ValueError("all governed execution stages must use the gateway")
        self.database_url = database_url
        self.routes = dict(routes)
        self.binder = PostgresChapterExecutionContractBinder(
            database_url,
            routes,
            capability_pack_id=capability_pack_id,
            pack_environment=pack_environment,
            pack_runtime_profile=pack_runtime_profile,
            pack_release_channel=pack_release_channel,
            pack_required=pack_required,
        )
        self.recovery_authorizations = PostgresExecutionRecoveryAuthorizationStore(
            database_url
        )
        self.session_factory = session_factory
        self.provider_adapters = dict(provider_adapters or {})
        self._sessions: dict[str, ChapterExecutionGatewaySession] = {}
        self._lock = Lock()
        all_real = all(
            item.real_provider_validation_eligible for item in routes.values()
        )
        all_idempotent = all(
            item.model_profile.runtime_class.value != "LOCAL_CLI_REMOTE_INFERENCE"
            for item in routes.values()
        )
        self.capability_profile = ProviderCapabilityProfile(
            provider=self.provider,
            control_level=(
                ProviderControlLevel.V2_CONTROLLED
                if all_real
                else ProviderControlLevel.FIXTURE_CONTROLLED
            ),
            supports_request_timeout=True,
            supports_provider_idempotency=all_idempotent,
            supports_query=True,
            supports_cancel=True,
            supports_callback=False,
            supports_usage_receipt=True,
            supports_cost_receipt=True,
            reconciliation_mode=self.reconciliation_mode,
            real_provider_validation_eligible=all_real,
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
                    "snapshot_worker_id": (
                        recovery_authorization.recovery_worker_id
                    ),
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
                "PROVIDER_RESULT_RECORDED",
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
        binding = self.binder.bind(
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
        """Drop all process-local gateway sessions before worker recovery."""

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
        route = self.routes[binding.request.stage]
        evidence: dict[str, Any] = {
            "provider_id": route.model_profile.model_provider,
            "model_id": route.model_profile.model_id,
            "prompt_version": route.prompt_version,
            "skill_version": route.skill_version,
            "real_model_call": (
                route.real_provider_validation_eligible
                and handle.transport.value != "SCRIPTED_FIXTURE"
            ),
            "fixture_protocol_only": handle.transport.value == "SCRIPTED_FIXTURE",
            "production_verified": False,
            "production_execution": {
                "execution_request": binding.request.to_dict(),
                "execution_handle": handle.to_dict(),
                "execution_result": result.to_dict(),
                "route_snapshot": binding.route_snapshot.to_dict(),
                "input_manifest": binding.input_manifest.to_dict(),
                "validation_manifest_ref": result.validation_report_ref or "",
                "commit_manifest_required": True,
            },
        }
        if result.normalized_output_ref:
            raw = session.evidence_store.read_evidence(result.normalized_output_ref)
            evidence["result"] = normalize_model_output(binding.request.stage, raw)
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
        if outcome is ExecutionOutcome.RETRYABLE_FAILURE:
            return "not_found" if reconciliation else "retryable_failure"
        if outcome is ExecutionOutcome.FINAL_FAILURE:
            return "failed_final" if reconciliation else "final_failure"
        if outcome is ExecutionOutcome.CANCELLED:
            return "cancelled"
        if outcome in {
            ExecutionOutcome.ACCEPTED,
            ExecutionOutcome.RUNNING,
            ExecutionOutcome.UNKNOWN,
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
    "ProductionExecutionGatewayExternalEffectAdapter",
    "chapter_stage_capability",
    "default_chapter_fixture_response",
]
