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
    CapabilityPackExecutionSnapshot,
    CapabilityPackScope,
    DeploymentStatus,
    RolloutStatus,
    ScopeType,
)


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
        _validate_deployment(repository, deployment, request, active=True)
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
            elif rollout_status == RolloutStatus.COMPLETED.value:
                selected_id = str(rollout["candidate_deployment_id"])
                assignment_ref = f"rollout:{rollout_id}:completed-candidate"
            else:
                assignment = repository.assign_rollout_subject(
                    rollout, subject_key
                )
                assignment_ref = str(assignment["assignment_id"])
                selected_id = str(assignment["selected_deployment_id"])
            if selected_id != deployment["deployment_id"]:
                deployment = repository.require_deployment(selected_id)
                _validate_deployment(repository, deployment, request, active=False)

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
    deprecation = repository.latest_deprecation(
        str(deployment["pack_id"]), str(deployment["pack_version"])
    )
    if deprecation and deprecation["retired"]:
        raise KernelError(
            "CAPABILITY_PACK_VERSION_RETIRED",
            "retired Pack Version cannot admit new runtime work",
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
    active = uow.repositories.agent_runtime.resolve_active_definition(agent_id)
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
]
