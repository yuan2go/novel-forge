"""Universal PostgreSQL Capability Pack runtime resolver foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .domain import (
    ApprovalDecision,
    CapabilityPackArtifactMaterialization,
    CapabilityPackAttemptSnapshot,
    CapabilityPackExecutionSnapshot,
    CapabilityPackScope,
    DeploymentStatus,
    RolloutStatus,
    ScopeType,
    MaterializedCapabilityArtifact,
    canonical_hash,
)
from .policy import CapabilityPackApprovalScope


@dataclass(frozen=True, slots=True)
class CapabilityPackResolutionRequest:
    project_id: str
    workspace_id: str
    book_id: str
    workflow_definition_ref: str
    workflow_node_id: str
    environment: str
    runtime_profile: str
    release_channel: str
    release_sha: str
    operation_definition_ref: str
    pack_id: str

    def __post_init__(self) -> None:
        values = asdict(self)
        required = tuple(
            values[key]
            for key in (
                "project_id",
                "workflow_definition_ref",
                "workflow_node_id",
                "environment",
                "runtime_profile",
                "release_channel",
                "release_sha",
                "operation_definition_ref",
                "pack_id",
            )
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("Capability Pack resolution request is incomplete")
        if self.book_id and not self.workspace_id:
            raise ValueError("Book-scoped Pack resolution requires workspace_id")


class CapabilityPackRuntimeResolver:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("Capability Pack Runtime Resolver requires PostgreSQL")
        self.database_url = database_url

    def resolve_active_deployment(
        self, request: CapabilityPackResolutionRequest
    ) -> CapabilityPackExecutionSnapshot:
        with AuthorityUnitOfWork(self.database_url) as uow:
            snapshot = self.resolve_in_uow(uow, request)
            uow.commit()  # a first-time canary assignment is an immutable fact
            return snapshot

    def resolve_binding_set(
        self, request: CapabilityPackResolutionRequest
    ) -> CapabilityPackExecutionSnapshot:
        return self.resolve_active_deployment(request)

    def resolve_workflow_node(
        self, request: CapabilityPackResolutionRequest
    ) -> CapabilityPackExecutionSnapshot:
        return self.resolve_active_deployment(request)

    def resolve_agent_binding(
        self, request: CapabilityPackResolutionRequest
    ) -> CapabilityPackExecutionSnapshot:
        return self.resolve_active_deployment(request)

    def freeze_execution_snapshot(
        self, request: CapabilityPackResolutionRequest
    ) -> CapabilityPackExecutionSnapshot:
        return self.resolve_active_deployment(request)

    def freeze_attempt_snapshot(
        self,
        request: CapabilityPackResolutionRequest,
        *,
        operation_id: str,
        attempt_id: str,
        execution_fencing_token: int,
        worker_id: str,
        snapshot_creation_fencing_token: int | None = None,
        snapshot_creation_worker_id: str = "",
    ) -> CapabilityPackAttemptSnapshot:
        """Resolve at most once and bind the result to the current Attempt fence."""

        creation_fence = (
            execution_fencing_token
            if snapshot_creation_fencing_token is None
            else snapshot_creation_fencing_token
        )
        creation_worker = snapshot_creation_worker_id or worker_id
        if (
            not operation_id
            or not attempt_id
            or not worker_id
            or execution_fencing_token <= 0
            or creation_fence <= 0
            or not creation_worker
        ):
            raise ValueError("Attempt Pack Snapshot admission identity is incomplete")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT attempt.operation_id
                FROM authority_attempt AS attempt
                WHERE attempt.attempt_id=%s
                FOR UPDATE OF attempt
                """,
                [attempt_id],
            )
            attempt = uow.cursor.fetchone()
            if attempt != (operation_id,):
                raise KernelError(
                    "CAPABILITY_PACK_ATTEMPT_OPERATION_INVALID",
                    "Pack Snapshot Attempt belongs to another operation",
                )
            existing = uow.repositories.capability_packs.find_attempt_snapshot(
                attempt_id
            )
            if existing is None:
                uow.cursor.execute(
                    """
                    SELECT owner FROM authority_lease_acquisition
                    WHERE attempt_id=%s AND fencing_token=%s
                      AND status='HELD' AND expires_at>NOW()
                    """,
                    [attempt_id, creation_fence],
                )
                lease = uow.cursor.fetchone()
                if lease != (creation_worker,):
                    raise KernelError(
                        "CAPABILITY_PACK_ATTEMPT_FENCE_INVALID",
                        "Pack Snapshot creation requires the current Attempt fence and worker",
                    )
                execution_snapshot = self.resolve_in_uow(uow, request)
                existing = uow.repositories.capability_packs.store_attempt_snapshot(
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    execution_fencing_token=execution_fencing_token,
                    snapshot_creation_fencing_token=creation_fence,
                    worker_id=creation_worker,
                    snapshot=execution_snapshot,
                )
            uow.commit()
        return CapabilityPackAttemptSnapshot(
            snapshot_id=str(existing["snapshot_id"]),
            operation_id=str(existing["operation_id"]),
            attempt_id=str(existing["attempt_id"]),
            execution_fencing_token=int(existing["execution_fencing_token"]),
            snapshot_creation_fencing_token=int(
                existing["snapshot_creation_fencing_token"]
            ),
            snapshot_hash=str(existing["snapshot_hash"]),
            trace_id=str(existing["trace_id"]),
            span_id=str(existing["span_id"]),
            execution_snapshot=existing["snapshot"],
        )

    def materialize_attempt_artifacts(
        self,
        snapshot: CapabilityPackAttemptSnapshot,
    ) -> CapabilityPackArtifactMaterialization:
        """Read exact registered content for an existing Attempt Snapshot only."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            stored = uow.repositories.capability_packs.find_attempt_snapshot(
                snapshot.attempt_id
            )
            if (
                stored is None
                or str(stored["snapshot_id"]) != snapshot.snapshot_id
                or str(stored["snapshot_hash"]) != snapshot.snapshot_hash
                or stored["snapshot"] != snapshot.execution_snapshot
            ):
                raise KernelError(
                    "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                    "Attempt Pack Snapshot differs from PostgreSQL Authority",
                )
            version = uow.repositories.capability_packs.require_version(
                snapshot.execution_snapshot.pack_id,
                snapshot.execution_snapshot.pack_version,
            )
        return materialize_registered_pack_version(
            snapshot.execution_snapshot,
            version,
        )

    def require_attempt_snapshot(
        self,
        *,
        attempt_id: str,
        snapshot_id: str,
        snapshot_hash: str,
    ) -> CapabilityPackAttemptSnapshot:
        """Load a previously frozen Snapshot without resolving current activation."""

        with AuthorityUnitOfWork(self.database_url) as uow:
            stored = uow.repositories.capability_packs.find_attempt_snapshot(attempt_id)
        if (
            stored is None
            or str(stored["snapshot_id"]) != snapshot_id
            or str(stored["snapshot_hash"]) != snapshot_hash
        ):
            raise KernelError(
                "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                "ExternalEffect Capability binding differs from Attempt Snapshot",
            )
        return CapabilityPackAttemptSnapshot(
            snapshot_id=str(stored["snapshot_id"]),
            operation_id=str(stored["operation_id"]),
            attempt_id=str(stored["attempt_id"]),
            execution_fencing_token=int(stored["execution_fencing_token"]),
            snapshot_creation_fencing_token=int(
                stored["snapshot_creation_fencing_token"]
            ),
            snapshot_hash=str(stored["snapshot_hash"]),
            trace_id=str(stored["trace_id"]),
            span_id=str(stored["span_id"]),
            execution_snapshot=stored["snapshot"],
        )

    @staticmethod
    def validate_runtime_admission(
        snapshot: CapabilityPackExecutionSnapshot,
        runtime_contract: Mapping[str, Any],
    ) -> None:
        checks = {
            "operation_definition_ref": snapshot.operation_definition_ref,
            "operation_definition_hash": snapshot.operation_definition_hash,
            "agent_definition_ref": snapshot.agent_definition_ref,
            "agent_definition_hash": snapshot.agent_definition_hash,
            "capability_ref": snapshot.capability_ref,
            "capability_hash": snapshot.capability_hash,
            "execution_capability_id": snapshot.execution_capability_id,
            "execution_capability_hash": snapshot.execution_capability_hash,
            "tool_policy_ref": snapshot.tool_policy_ref,
            "tool_policy_hash": snapshot.tool_policy_hash,
            "context_policy_ref": snapshot.context_policy_ref,
            "context_policy_hash": snapshot.context_policy_hash,
            "evaluation_policy_ref": snapshot.evaluation_policy_ref,
            "evaluation_policy_hash": snapshot.evaluation_policy_hash,
            "release_sha": snapshot.release_sha,
        }
        if not bool(runtime_contract.get("derived_execution_contract")):
            checks.update(
                {
                    "prompt_bundle_ref": snapshot.prompt_bundle_ref,
                    "prompt_bundle_hash": snapshot.prompt_bundle_hash,
                    "skill_bundle_ref": snapshot.skill_bundle_ref,
                    "skill_bundle_hash": snapshot.skill_bundle_hash,
                }
            )
        drift = [
            name
            for name, expected in checks.items()
            if str(runtime_contract.get(name) or "") != str(expected)
        ]
        if drift:
            raise KernelError(
                "CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT",
                "runtime contract differs from Pack execution snapshot: "
                + ", ".join(drift),
            )
        if bool(runtime_contract.get("derived_execution_contract")):
            semantic_checks: dict[str, Any] = {
                "prompt_system_instruction_hash": (
                    snapshot.prompt_system_instruction_hash
                ),
                "prompt_template_hash": snapshot.prompt_template_hash,
                "prompt_compiler_version": snapshot.prompt_compiler_version,
                "skill_ref": snapshot.skill_version,
                "skill_content_hash": snapshot.skill_content_hash,
                "governing_tool_policy_ref": snapshot.tool_policy_ref,
                "governing_tool_policy_hash": snapshot.tool_policy_hash,
                "governing_context_policy_ref": snapshot.context_policy_ref,
                "governing_context_policy_hash": snapshot.context_policy_hash,
                "governing_evaluation_policy_ref": (
                    snapshot.evaluation_policy_ref
                ),
                "governing_evaluation_policy_hash": (
                    snapshot.evaluation_policy_hash
                ),
            }
            semantic_drift = [
                name
                for name, expected in semantic_checks.items()
                if not expected
                or str(runtime_contract.get(name) or "") != str(expected)
            ]
            if semantic_drift:
                raise KernelError(
                    "CAPABILITY_PACK_DERIVED_CONTRACT_DRIFT",
                    "derived PEP contract differs from Pack source binding: "
                    + ", ".join(semantic_drift),
                )

    @staticmethod
    def resolve_in_uow(
        uow: AuthorityUnitOfWork, request: CapabilityPackResolutionRequest
    ) -> CapabilityPackExecutionSnapshot:
        uow.repositories.capability_packs.validate_resolution_scope(
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            book_id=request.book_id,
        )
        scopes = _scope_precedence(request)
        candidates = uow.repositories.capability_packs.resolve_activation_candidates(
            scope_keys=[scope.scope_key for scope in scopes],
            environment=request.environment,
            workflow_definition_ref=request.workflow_definition_ref,
            pack_id=request.pack_id,
        )
        by_scope: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            by_scope.setdefault(str(candidate["scope_key"]), []).append(candidate)
        selected_activation: Mapping[str, Any] | None = None
        selected_scope: CapabilityPackScope | None = None
        for scope in scopes:
            matching = by_scope.get(scope.scope_key, [])
            if len(matching) > 1:
                raise KernelError(
                    "CAPABILITY_PACK_DEPLOYMENT_AMBIGUOUS",
                    f"multiple Pack activations exist at {scope.scope_type.value} scope",
                )
            if matching:
                selected_activation = matching[0]
                selected_scope = scope
                break
        if selected_activation is None or selected_scope is None:
            raise KernelError(
                "CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED",
                "no active Pack Deployment exists for the requested scope hierarchy",
            )

        repository = uow.repositories.capability_packs
        deployment = repository.require_deployment(
            str(selected_activation["active_deployment_id"])
        )
        _validate_deployment(
            repository,
            deployment,
            request,
            scope=selected_scope,
            active=True,
        )
        rollout = repository.active_rollout_for_baseline(
            str(deployment["deployment_id"])
        )
        rollout_id = ""
        assignment_ref = (
            "activation:"
            f"{selected_activation.get('activation_key') or selected_scope.scope_key}"
            f"@{selected_activation['activation_version']}"
        )
        if rollout is not None:
            assignment_key_policy = str(rollout["assignment_key_policy"])
            if assignment_key_policy == "BOOK":
                if not request.book_id:
                    raise KernelError(
                        "CAPABILITY_PACK_ROLLOUT_SUBJECT_REQUIRED",
                        "BOOK rollout requires an exact Book subject",
                    )
                subject_key = request.book_id
            elif assignment_key_policy == "PROJECT_WORKSPACE":
                if not request.workspace_id:
                    raise KernelError(
                        "CAPABILITY_PACK_ROLLOUT_SUBJECT_REQUIRED",
                        "PROJECT_WORKSPACE rollout requires an exact Workspace subject",
                    )
                subject_key = f"{request.project_id}:{request.workspace_id}"
            else:
                raise KernelError(
                    "CAPABILITY_PACK_ROLLOUT_ASSIGNMENT_POLICY_INVALID",
                    "rollout assignment policy is unsupported",
                )
            rollout_id = str(rollout["rollout_id"])
            rollout_status = str(rollout["status"])
            if rollout_status == RolloutStatus.PAUSED.value:
                selected_id = str(rollout["baseline_deployment_id"])
                assignment_ref = f"rollout:{rollout_id}:paused-baseline"
            else:
                assignment = repository.assign_rollout_subject(
                    rollout, subject_key
                )
                assignment_ref = str(assignment["assignment_id"])
                selected_id = str(assignment["selected_deployment_id"])
            if selected_id != deployment["deployment_id"]:
                deployment = repository.require_deployment(selected_id)
                _validate_deployment(
                    repository,
                    deployment,
                    request,
                    scope=selected_scope,
                    active=False,
                )

        nodes = [
            dict(item)
            for item in deployment["node_bindings"]
            if str(item.get("workflow_node_id")) == request.workflow_node_id
        ]
        if len(nodes) != 1:
            raise KernelError(
                "CAPABILITY_PACK_WORKFLOW_NODE_AMBIGUOUS",
                "Binding Set must contain exactly one requested Workflow Node",
            )
        node = nodes[0]
        if node["operation_definition_ref"] != request.operation_definition_ref:
            raise KernelError(
                "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
                "requested OperationDefinition differs from Binding Set",
            )
        name, separator, version = request.operation_definition_ref.rpartition("@")
        definition = (
            uow.repositories.definitions.get(name, version) if separator else None
        )
        if (
            definition is None
            or not bool(definition.get("enabled"))
            or str(definition.get("definition_hash"))
            != str(node["operation_definition_hash"])
        ):
            raise KernelError(
                "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
                "Binding Set OperationDefinition is unavailable or changed",
            )
        _validate_active_agent(uow, deployment, node)
        return CapabilityPackExecutionSnapshot(
            deployment_id=str(deployment["deployment_id"]),
            activation_version=int(selected_activation["activation_version"]),
            selected_scope_type=selected_scope.scope_type,
            selection_reason=(
                f"{selected_scope.scope_type.value} deployment selected"
            ),
            pack_id=str(deployment["pack_id"]),
            pack_version=str(deployment["pack_version"]),
            manifest_hash=str(deployment["manifest_hash"]),
            compilation_id=str(deployment["compilation_id"]),
            compilation_hash=str(deployment["compilation_hash"]),
            catalog_snapshot_hash=str(deployment["catalog_snapshot_hash"]),
            binding_set_id=str(deployment["binding_set_id"]),
            binding_set_hash=str(deployment["binding_set_hash"]),
            workflow_definition_ref=request.workflow_definition_ref,
            workflow_node_id=request.workflow_node_id,
            operation_definition_ref=str(node["operation_definition_ref"]),
            operation_definition_hash=str(node["operation_definition_hash"]),
            agent_definition_ref=str(node["agent_definition_ref"]),
            agent_definition_hash=str(node["agent_definition_hash"]),
            capability_ref=str(node["capability_ref"]),
            capability_hash=str(node["capability_hash"]),
            execution_capability_id=str(node["execution_capability_id"]),
            execution_capability_hash=str(node["execution_capability_hash"]),
            prompt_bundle_ref=str(node["prompt_bundle_ref"]),
            prompt_bundle_hash=str(node["prompt_bundle_hash"]),
            skill_bundle_ref=str(node["skill_bundle_ref"]),
            skill_bundle_hash=str(node["skill_bundle_hash"]),
            tool_policy_ref=str(node["tool_policy_ref"]),
            tool_policy_hash=str(node["tool_policy_hash"]),
            context_policy_ref=str(node["context_policy_ref"]),
            context_policy_hash=str(node["context_policy_hash"]),
            evaluation_policy_ref=str(node["evaluation_policy_ref"]),
            evaluation_policy_hash=str(node["evaluation_policy_hash"]),
            route_policy_ref=str(node["route_policy_ref"]),
            route_policy_hash=str(node["route_policy_hash"]),
            approval_policy_ref=str(node["approval_policy_ref"]),
            approval_policy_hash=str(node["approval_policy_hash"]),
            budget_policy_ref=str(node["budget_policy_ref"]),
            budget_policy_hash=str(node["budget_policy_hash"]),
            input_contract_ref=str(node["input_contract_ref"]),
            output_contract_ref=str(node["output_contract_ref"]),
            domain_acceptance_policy_ref=str(
                node["domain_acceptance_policy_ref"]
            ),
            commit_authority=str(node["commit_authority"]),
            release_sha=str(deployment["release_sha"]),
            rollout_id=rollout_id,
            assignment_ref=assignment_ref,
            prompt_system_instruction_ref=str(
                node.get("prompt_system_instruction_ref") or ""
            ),
            prompt_system_instruction_hash=str(
                node.get("prompt_system_instruction_hash") or ""
            ),
            prompt_template_ref=str(node.get("prompt_template_ref") or ""),
            prompt_template_hash=str(node.get("prompt_template_hash") or ""),
            prompt_compiler_version=str(
                node.get("prompt_compiler_version") or ""
            ),
            skill_ref=str(node.get("skill_ref") or ""),
            skill_version=str(node.get("skill_version") or ""),
            skill_content_hash=str(node.get("skill_content_hash") or ""),
            context_policy_payload_json=json.dumps(
                node.get("context_policy_payload") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            tool_policy_payload_json=json.dumps(
                node.get("tool_policy_payload") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            evaluation_policy_payload_json=json.dumps(
                node.get("evaluation_policy_payload") or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


def chapter_node_binding_from_snapshot(
    snapshot: CapabilityPackExecutionSnapshot,
) -> dict[str, Any]:
    """Expose the immutable Pack node as a runtime binding, never a global pointer."""

    operation_name, separator, operation_version = (
        snapshot.operation_definition_ref.rpartition("@")
    )
    if not separator:
        raise KernelError(
            "CAPABILITY_PACK_OPERATION_DEFINITION_INVALID",
            "Pack snapshot requires an exact OperationDefinition ref",
        )
    agent_id, separator, agent_version = snapshot.agent_definition_ref.rpartition("@")
    if not separator or not agent_version.isdigit():
        raise KernelError(
            "CAPABILITY_PACK_AGENT_DEFINITION_INVALID",
            "Pack snapshot requires an exact AgentDefinition ref",
        )
    capability_id, separator, capability_version = snapshot.capability_ref.rpartition(
        "@"
    )
    if not separator or not capability_version.isdigit():
        raise KernelError(
            "CAPABILITY_PACK_AGENT_CAPABILITY_INVALID",
            "Pack snapshot requires an exact Agent Capability ref",
        )
    binding_id = (
        f"pack-binding-set:{snapshot.binding_set_id}:{snapshot.workflow_node_id}"
    )
    return {
        "binding_id": binding_id,
        "binding_version": snapshot.activation_version,
        "chapter_node_binding_ref": f"{binding_id}@{snapshot.activation_version}",
        "workflow_definition_ref": snapshot.workflow_definition_ref,
        "workflow_node_id": snapshot.workflow_node_id,
        "operation_definition_name": operation_name,
        "operation_definition_version": operation_version,
        "operation_definition_hash": snapshot.operation_definition_hash,
        "agent_id": agent_id,
        "agent_definition_version": int(agent_version),
        "agent_definition_hash": snapshot.agent_definition_hash,
        "capability_id": capability_id,
        "capability_version": int(capability_version),
        "capability_hash": snapshot.capability_hash,
        "execution_capability_id": snapshot.execution_capability_id,
        "execution_capability_hash": snapshot.execution_capability_hash,
        "capability_pack_ref": f"{snapshot.pack_id}@{snapshot.pack_version}",
        "capability_pack_compilation_hash": snapshot.compilation_hash,
        "input_contract_ref": snapshot.input_contract_ref,
        "output_contract_ref": snapshot.output_contract_ref,
        "domain_acceptance_policy_ref": snapshot.domain_acceptance_policy_ref,
        "commit_authority": snapshot.commit_authority,
        "binding_status": "ACTIVE",
        "release_sha": snapshot.release_sha,
        "capability_pack_deployment_id": snapshot.deployment_id,
        "capability_pack_activation_version": snapshot.activation_version,
        "capability_pack_binding_set_id": snapshot.binding_set_id,
        "capability_pack_binding_set_hash": snapshot.binding_set_hash,
        "capability_pack_scope_type": snapshot.selected_scope_type.value,
        "capability_pack_assignment_ref": snapshot.assignment_ref,
    }


def materialize_registered_pack_version(
    snapshot: CapabilityPackExecutionSnapshot,
    registered_version: Mapping[str, Any],
) -> CapabilityPackArtifactMaterialization:
    """Materialize exact provider inputs without consulting active deployment state."""

    from novel_forge.modules.capability_packs.artifacts import (
        ArtifactKind,
        exact_ref_version,
    )
    from novel_forge.modules.capability_packs.loader import (
        load_capability_pack_payload,
    )

    manifest_payload = registered_version.get("manifest")
    catalog_payload = registered_version.get("artifact_catalog")
    if not isinstance(manifest_payload, Mapping) or not isinstance(
        catalog_payload, Mapping
    ):
        raise KernelError(
            "CAPABILITY_PACK_ASSET_CONTENT_MISSING",
            "registered Pack Version has no Manifest or Artifact Catalog content",
        )
    manifest = load_capability_pack_payload(manifest_payload)
    version_checks = {
        "pack_id": (registered_version.get("pack_id"), snapshot.pack_id),
        "pack_version": (
            registered_version.get("pack_version"),
            snapshot.pack_version,
        ),
        "manifest_identity_pack_id": (manifest.identity.pack_id, snapshot.pack_id),
        "manifest_identity_version": (
            manifest.identity.version,
            snapshot.pack_version,
        ),
        "manifest_hash": (
            registered_version.get("manifest_hash"),
            snapshot.manifest_hash,
        ),
        "recomputed_manifest_hash": (manifest.manifest_hash, snapshot.manifest_hash),
    }
    drift = [
        name
        for name, (actual, expected) in version_checks.items()
        if str(actual or "") != str(expected)
    ]
    if drift:
        raise KernelError(
            "CAPABILITY_PACK_VERSION_MISMATCH",
            "registered Pack Version differs from frozen Snapshot: "
            + ", ".join(drift),
        )
    catalog_hash = canonical_hash(catalog_payload)
    if str(registered_version.get("artifact_catalog_hash") or "") != catalog_hash:
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_HASH_DRIFT",
            "registered Artifact Catalog content differs from Authority hash",
        )
    resolver = _registered_artifact_resolver(catalog_payload)
    prompt = manifest.prompt_binding
    system = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
        str(prompt.system_instruction_ref),
        str(prompt.system_instruction_version),
    )
    template = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.PROMPT_TEMPLATE,
        str(prompt.template_ref),
        str(prompt.template_version),
    )
    selected_skills = [
        item
        for item in manifest.skill_binding.skills
        if str(item.skill_ref) == snapshot.skill_ref
        and str(item.version) == snapshot.skill_version
    ]
    if len(selected_skills) != 1:
        raise KernelError(
            "CAPABILITY_PACK_REQUIRED_SKILL_MISSING",
            "frozen Agent Skill is not present exactly once in the Pack Manifest",
        )
    skill_binding = selected_skills[0]
    skill = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.SKILL,
        str(skill_binding.skill_ref),
        str(skill_binding.version),
    )
    context_policy = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.CONTEXT_POLICY,
        str(manifest.context_sources.policy_id),
        exact_ref_version(str(manifest.context_sources.policy_id)),
    )
    tool_policy = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.TOOL_POLICY,
        str(manifest.tool_permissions.policy_id),
        exact_ref_version(str(manifest.tool_permissions.policy_id)),
    )
    input_schema = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.SCHEMA,
        snapshot.input_contract_ref,
        exact_ref_version(snapshot.input_contract_ref),
    )
    output_schema = _resolve_materialized_artifact(
        resolver,
        ArtifactKind.SCHEMA,
        snapshot.output_contract_ref,
        exact_ref_version(snapshot.output_contract_ref),
    )
    knowledge = tuple(
        _resolve_materialized_artifact(
            resolver,
            ArtifactKind.KNOWLEDGE,
            str(ref),
            exact_ref_version(str(ref)),
        )
        for ref in manifest.assets.knowledge.get("required_packs") or ()
    )
    context_payload = json.loads(snapshot.context_policy_payload_json)
    tool_payload = json.loads(snapshot.tool_policy_payload_json)
    manifest_payload = manifest.to_dict()
    if (
        context_payload != manifest_payload["context_sources"]
        or tool_payload != manifest_payload["tool_permissions"]
        or canonical_hash(context_payload) != snapshot.context_policy_hash
        or canonical_hash(tool_payload) != snapshot.tool_policy_hash
        or str(context_policy.content.get("policy_id") or "")
        != snapshot.context_policy_ref
        or str(tool_policy.content.get("policy_id") or "")
        != snapshot.tool_policy_ref
    ):
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_HASH_DRIFT",
            "frozen Capability policy differs from Manifest or exact policy content",
        )
    expected_hashes = {
        "prompt_system_instruction": (
            system.content_hash,
            snapshot.prompt_system_instruction_hash,
        ),
        "prompt_template": (
            template.content_hash,
            snapshot.prompt_template_hash,
        ),
        "skill": (skill.content_hash, snapshot.skill_content_hash),
    }
    hash_drift = [
        name
        for name, (actual, expected) in expected_hashes.items()
        if actual != expected
    ]
    ref_drift = [
        name
        for name, actual, expected in (
            (
                "prompt_system_instruction",
                f"{system.ref}@{system.version}",
                snapshot.prompt_system_instruction_ref,
            ),
            (
                "prompt_template",
                f"{template.ref}@{template.version}",
                snapshot.prompt_template_ref,
            ),
            ("skill", skill.ref, snapshot.skill_ref),
            ("context_policy", context_policy.ref, snapshot.context_policy_ref),
            ("tool_policy", tool_policy.ref, snapshot.tool_policy_ref),
        )
        if actual != expected
    ]
    if hash_drift or ref_drift:
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_HASH_DRIFT",
            "frozen Capability binding differs from exact registered content: "
            + ", ".join(hash_drift + ref_drift),
        )
    return CapabilityPackArtifactMaterialization(
        pack_id=snapshot.pack_id,
        pack_version=snapshot.pack_version,
        manifest_hash=snapshot.manifest_hash,
        artifact_catalog_hash=catalog_hash,
        system_instruction=system,
        prompt_template=template,
        skill=skill,
        context_policy=context_policy,
        tool_policy=tool_policy,
        input_schema=input_schema,
        output_schema=output_schema,
        required_knowledge=knowledge,
    )


def _registered_artifact_resolver(
    catalog: Mapping[str, Any],
) -> Any:
    from novel_forge.modules.capability_packs.artifacts import (
        ArtifactKind,
        ExplicitArtifactResolver,
        ResolvedArtifact,
        canonical_artifact_json,
    )

    if catalog.get("schema_version") != "novelos.capability_pack.artifact_catalog.v1":
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_CATALOG_INVALID",
            "registered Artifact Catalog protocol is unsupported",
        )
    entries = catalog.get("artifacts")
    if not isinstance(entries, list):
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_CATALOG_INVALID",
            "registered Artifact Catalog requires an artifacts array",
        )
    artifacts: list[ResolvedArtifact] = []
    try:
        for raw in entries:
            if (
                not isinstance(raw, Mapping)
                or "content" not in raw
                or "source_path" in raw
            ):
                raise ValueError("registered Artifact content must be inline")
            artifacts.append(
                ResolvedArtifact(
                    kind=ArtifactKind(str(raw.get("kind") or "")),
                    ref=str(raw.get("ref") or ""),
                    version=str(raw.get("version") or ""),
                    content_hash=str(raw.get("content_hash") or ""),
                    content_json=canonical_artifact_json(raw["content"]),
                    source_identity=str(raw.get("source_identity") or ""),
                )
            )
        return ExplicitArtifactResolver(artifacts)
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_CATALOG_INVALID",
            str(exc),
        ) from exc


def _resolve_materialized_artifact(
    resolver: Any,
    kind: Any,
    ref: str,
    version: str,
) -> MaterializedCapabilityArtifact:
    try:
        artifact = resolver.resolve(kind, ref, version)
    except (KeyError, LookupError, TypeError, ValueError) as exc:
        raise KernelError(
            "CAPABILITY_PACK_REQUIRED_ASSET_MISSING",
            f"required {kind.value} Artifact cannot be resolved: {ref}@{version}: {exc}",
        ) from exc
    return MaterializedCapabilityArtifact(
        kind=artifact.kind.value,
        ref=artifact.ref,
        version=artifact.version,
        content_hash=artifact.content_hash,
        content_json=artifact.content_json,
        source_identity=artifact.source_identity,
    )


def _scope_precedence(
    request: CapabilityPackResolutionRequest,
) -> tuple[CapabilityPackScope, ...]:
    scopes: list[CapabilityPackScope] = []
    if request.book_id:
        scopes.append(
            CapabilityPackScope(
                ScopeType.BOOK,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=request.book_id,
            )
        )
    if request.workspace_id:
        scopes.append(
            CapabilityPackScope(
                ScopeType.WORKSPACE,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
            )
        )
    scopes.extend(
        (
            CapabilityPackScope(
                ScopeType.PROJECT, project_id=request.project_id
            ),
            CapabilityPackScope(ScopeType.SYSTEM),
        )
    )
    return tuple(scopes)


def _validate_deployment(
    repository: Any,
    deployment: Mapping[str, Any],
    request: CapabilityPackResolutionRequest,
    scope: CapabilityPackScope,
    *,
    active: bool,
) -> None:
    allowed = {DeploymentStatus.ACTIVE.value} if active else {
        DeploymentStatus.ACTIVE.value,
        DeploymentStatus.CANDIDATE.value,
    }
    if str(deployment["deployment_status"]) not in allowed:
        raise KernelError(
            "CAPABILITY_PACK_DEPLOYMENT_BLOCKED",
            "Pack Deployment is not eligible for new runtime admission",
        )
    mismatches = [
        name
        for name, expected in {
            "workflow_definition_ref": request.workflow_definition_ref,
            "release_sha": request.release_sha,
            "runtime_profile": request.runtime_profile,
            "release_channel": request.release_channel,
            "pack_id": request.pack_id,
        }.items()
        if str(deployment.get(name)) != str(expected)
    ]
    if mismatches:
        raise KernelError(
            "CAPABILITY_PACK_DEPLOYMENT_COMPATIBILITY_DRIFT",
            "Pack Deployment is incompatible with runtime: " + ", ".join(mismatches),
        )
    approval = repository.latest_approval(str(deployment["compilation_id"]))
    if (
        approval is None
        or approval["decision"] != ApprovalDecision.APPROVED.value
        or approval["compilation_hash"] != deployment["compilation_hash"]
        or (
            approval["expires_at"] is not None
            and approval["expires_at"] <= datetime.now(timezone.utc)
        )
    ):
        raise KernelError(
            "CAPABILITY_PACK_APPROVAL_INVALID",
            "Pack Deployment no longer has a current exact approval",
        )
    CapabilityPackApprovalScope.from_payload(
        dict(approval["approval_scope"])
    ).require_admission(
        scope=scope,
        environment=request.environment,
        runtime_profile=request.runtime_profile,
        release_channel=request.release_channel,
        workflow_definition_ref=request.workflow_definition_ref,
        limitations=tuple(approval.get("structured_limitations") or ()),
    )
    deprecation = repository.latest_deprecation(
        str(deployment["pack_id"]), str(deployment["pack_version"])
    )
    if deprecation and deprecation["retired"]:
        raise KernelError(
            "CAPABILITY_PACK_VERSION_RETIRED",
            "retired Pack Version cannot admit new runtime work",
        )
    blocked_dependencies = repository.blocked_dependencies(
        str(deployment["pack_id"]), str(deployment["pack_version"])
    )
    if blocked_dependencies:
        raise KernelError(
            "CAPABILITY_PACK_DEPENDENCY_ADMISSION_BLOCKED",
            "Pack dependency is revoked, retired, or drifted: "
            + ", ".join(blocked_dependencies),
        )


def _validate_active_agent(
    uow: AuthorityUnitOfWork,
    deployment: Mapping[str, Any],
    node: Mapping[str, Any],
) -> None:
    agent_ref = str(node.get("agent_definition_ref") or "")
    agent_id, separator, raw_version = agent_ref.rpartition("@")
    if not separator or not raw_version.isdigit():
        raise KernelError(
            "CAPABILITY_PACK_AGENT_DEFINITION_INVALID",
            "runtime Node must bind an exact Agent Definition",
        )
    active = uow.repositories.agent_runtime.lock_definition_version(
        agent_id, int(raw_version)
    )
    checks = {
        "definition_version": int(raw_version),
        "definition_hash": node["agent_definition_hash"],
        "capability_pack_ref": (
            f"{deployment['pack_id']}@{deployment['pack_version']}"
        ),
        "prompt_bundle_ref": node["prompt_bundle_ref"],
        "prompt_bundle_hash": node["prompt_bundle_hash"],
        "skill_bundle_ref": node["skill_bundle_ref"],
        "skill_bundle_hash": node["skill_bundle_hash"],
        "tool_policy_ref": node["tool_policy_ref"],
        "tool_policy_hash": node["tool_policy_hash"],
        "context_policy_ref": node["context_policy_ref"],
        "context_policy_hash": node["context_policy_hash"],
    }
    drift = [
        key for key, expected in checks.items() if str(active.get(key)) != str(expected)
    ]
    capability_id, _, capability_version = str(node["capability_ref"]).rpartition("@")
    capability = next(
        (
            item
            for item in active.get("capabilities") or ()
            if str(item.get("capability_id")) == capability_id
            and str(item.get("capability_version")) == capability_version
        ),
        None,
    )
    if (
        capability is None
        or str(capability.get("capability_hash")) != str(node["capability_hash"])
        or str(capability.get("execution_capability_id"))
        != str(node["execution_capability_id"])
        or str(capability.get("execution_capability_hash"))
        != str(node["execution_capability_hash"])
    ):
        drift.append("capability")
    if drift:
        raise KernelError(
            "CAPABILITY_PACK_AGENT_DEFINITION_DRIFT",
            "active Agent Definition differs from Binding Set: " + ", ".join(drift),
        )


__all__ = [
    "CapabilityPackResolutionRequest",
    "CapabilityPackRuntimeResolver",
    "chapter_node_binding_from_snapshot",
    "materialize_registered_pack_version",
]
