"""Application services for PostgreSQL Agent Definition and run admission."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping
from uuid import uuid4

from novel_forge.modules.agent_collaboration.domain import (
    AgentCapability,
    AgentDefinition,
    AgentMessageType,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    admit_command_in_uow,
    execute_transaction_command,
)
from novel_forge.modules.capability_packs.runtime_binding import (
    bind_compiled_pack_for_admission,
    compiled_capability_pack_from_payload,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
    chapter_node_binding_from_snapshot,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import (
    AgentCapabilityExecutionMapping,
    AgentDefinitionActivationStatus,
    AgentDefinitionRuntimeContract,
    ChapterNodeExecutionBinding,
)
from .definitions import (
    AGENT_RUNTIME_ADMIN_HANDLER_KEY,
    AGENT_RUNTIME_ADMIN_OPERATIONS,
    AGENT_RUNTIME_DEFINITION_VERSION,
    AGENT_RUNTIME_EXECUTION_HANDLER_KEY,
    agent_runtime_operation_definitions,
)


@dataclass(frozen=True, slots=True)
class AgentRuntimeAdminCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    agent_id: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    payload: Mapping[str, Any]
    expected_activation_version: int = 0

    def __post_init__(self) -> None:
        if self.definition_name not in AGENT_RUNTIME_ADMIN_OPERATIONS:
            raise ValueError("unsupported Agent Runtime administration command")
        if self.expected_activation_version < 0:
            raise ValueError("expected activation version cannot be negative")
        required = (
            self.project_id,
            self.workspace_id,
            self.agent_id,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Agent Runtime administration command is incomplete")


@dataclass(frozen=True, slots=True)
class AgentRunAdmissionRequest:
    project_id: str
    workspace_id: str
    book_id: str
    chapter_number: int
    actor_id: str
    agent_id: str
    agent_definition_version: int
    agent_definition_hash: str
    capability_id: str
    capability_version: int
    capability_hash: str
    execution_capability_id: str
    execution_capability_hash: str
    capability_pack_ref: str
    capability_pack_compilation_hash: str
    workflow_definition_ref: str
    workflow_node_id: str
    operation_definition_ref: str
    operation_definition_hash: str
    chapter_node_binding_ref: str
    collaboration_session_id: str
    scope_snapshot_ref: str
    participant_snapshot_ref: str
    context_bundle_asset_version_id: str
    context_bundle_hash: str
    input_assets: tuple[tuple[str, str], ...]
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_policy_ref: str
    tool_policy_hash: str
    context_policy_ref: str
    context_policy_hash: str
    evaluation_policy_ref: str
    evaluation_policy_hash: str
    route_policy_ref: str
    model_profile_ref: str
    budget_policy_ref: str
    timeout_policy_ref: str
    approval_policy_ref: str
    validation_policy_ref: str
    commit_policy_ref: str
    commit_authority: str
    message_type: AgentMessageType
    business_goal: str
    current_issue: str
    candidate_version_ref: str
    evidence_refs: tuple[str, ...]
    must_preserve: tuple[str, ...]
    must_change: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    risk_level: str
    failure_policy: str
    continuation_policy: str
    release_sha: str
    capability_pack_deployment_id: str
    capability_pack_activation_version: int
    capability_pack_binding_set_id: str
    capability_pack_binding_set_hash: str
    capability_pack_scope_type: str
    capability_pack_assignment_ref: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message_type", AgentMessageType(self.message_type))
        if self.agent_definition_version <= 0 or self.capability_version <= 0:
            raise ValueError("Agent and capability versions must be positive")
        if self.capability_pack_activation_version <= 0:
            raise ValueError("Capability Pack activation version must be positive")
        if self.chapter_number <= 0:
            raise ValueError("Chapter Agent run requires a positive chapter number")
        if not self.input_assets:
            raise ValueError("Agent run must bind immutable input AssetVersions")
        identities = {asset_version_id for asset_version_id, _ in self.input_assets}
        if self.context_bundle_asset_version_id not in identities:
            raise ValueError("Context Bundle must be part of frozen input assets")
        required = (
            value
            for name, value in asdict(self).items()
            if name not in {
                "agent_definition_version",
                "capability_version",
                "chapter_number",
            }
            and not name.endswith("_refs")
            and name
            not in {
                "input_assets",
                "must_preserve",
                "must_change",
                "forbidden_changes",
                "acceptance_criteria",
                "evidence_refs",
                "candidate_version_ref",
            }
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("Agent run admission is incomplete")
        if not self.commit_authority.endswith("_AUTHORITY"):
            raise ValueError("Agent output commit requires a Domain Authority")

    def command_input(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("actor_id")
        payload.pop("idempotency_key")
        payload.pop("trace_id")
        payload.pop("correlation_id")
        payload["message_type"] = self.message_type.value
        payload["input_asset_versions"] = [item[0] for item in self.input_assets]
        payload.pop("input_assets")
        return payload


class AgentRuntimeAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        runtime_environment: str = "development",
        release_channel: str = "VALIDATION",
        fault_injector: TransactionCheckpoint | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("Agent Runtime Authority requires PostgreSQL")
        if not application_build_id or len(commit_sha) != 40:
            raise ValueError("Agent Runtime Authority requires exact release identity")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.runtime_environment = runtime_environment.strip().lower()
        self.release_channel = release_channel.strip().upper()
        self.pack_resolver = CapabilityPackRuntimeResolver(database_url)
        self.fault_injector = fault_injector

    def execute_admin(
        self,
        command: AgentRuntimeAdminCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("agent.authority.admin", command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError("Agent Runtime actor must be the trusted Principal")
        self._register_definitions()
        context = AdmissionContext(
            actor_id=principal.principal_id,
            permissions=principal.permissions,
            available_handlers=frozenset({AGENT_RUNTIME_ADMIN_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": AGENT_RUNTIME_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "agent_id": command.agent_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "system:agent-definition",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "agent_id": command.agent_id,
                    "payload": dict(command.payload),
                    "expected_activation_version": (
                        command.expected_activation_version
                    ),
                },
                "input_assets": [],
            },
            context=context,
            handler=self._execute_admin_transaction,
            fault_injector=self.fault_injector,
        )

    def admit_run(
        self,
        request: AgentRunAdmissionRequest,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        principal.require("agent.authority.execute", request.project_id)
        if principal.principal_id != request.actor_id:
            raise PermissionError("Agent run actor must be the trusted Principal")
        self._register_definitions()
        context = AdmissionContext(
            actor_id=principal.principal_id,
            permissions=principal.permissions,
            available_handlers=frozenset({AGENT_RUNTIME_EXECUTION_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            snapshot = None
            if self.runtime_environment in {
                "validation",
                "provider-validation",
                "production",
            }:
                pack_id, separator, _ = request.capability_pack_ref.rpartition("@")
                if not separator:
                    raise KernelError(
                        "CAPABILITY_PACK_REFERENCE_INVALID",
                        "Agent run requires an exact Capability Pack ref",
                    )
                snapshot = self.pack_resolver.resolve_in_uow(
                    uow,
                    CapabilityPackResolutionRequest(
                        project_id=request.project_id,
                        workspace_id=request.workspace_id,
                        book_id=request.book_id,
                        workflow_definition_ref=request.workflow_definition_ref,
                        workflow_node_id=request.workflow_node_id,
                        environment=self.runtime_environment,
                        runtime_profile=self.runtime_environment,
                        release_channel=self.release_channel,
                        release_sha=request.release_sha,
                        operation_definition_ref=request.operation_definition_ref,
                        pack_id=pack_id,
                    ),
                )
                self.pack_resolver.validate_runtime_admission(
                    snapshot, request.command_input()
                )
                pack_drift = [
                    key
                    for key, expected in {
                        "capability_pack_deployment_id": snapshot.deployment_id,
                        "capability_pack_activation_version": (
                            snapshot.activation_version
                        ),
                        "capability_pack_binding_set_id": snapshot.binding_set_id,
                        "capability_pack_binding_set_hash": snapshot.binding_set_hash,
                        "capability_pack_scope_type": (
                            snapshot.selected_scope_type.value
                        ),
                        "capability_pack_assignment_ref": snapshot.assignment_ref,
                    }.items()
                    if str(getattr(request, key)) != str(expected)
                ]
                if pack_drift:
                    raise KernelError(
                        "CAPABILITY_PACK_RUNTIME_SNAPSHOT_DRIFT",
                        "Agent run Pack snapshot differs from resolver: "
                        + ", ".join(pack_drift),
                    )
            active_definition = uow.repositories.agent_runtime.lock_active_definition(
                request.agent_id
            )
            active_binding = (
                chapter_node_binding_from_snapshot(snapshot)
                if snapshot is not None
                else uow.repositories.agent_runtime.resolve_active_chapter_node_binding(
                    workflow_definition_ref=request.workflow_definition_ref,
                    workflow_node_id=request.workflow_node_id,
                )
            )
            self._validate_run_admission(
                request,
                active_definition=active_definition,
                active_binding=active_binding,
            )
            self._validate_collaboration_scope(uow, request)
            admitted = admit_command_in_uow(
                uow,
                {
                    "definition_name": "agent.candidate.execute",
                    "definition_version": AGENT_RUNTIME_DEFINITION_VERSION,
                    "project_id": request.project_id,
                    "workspace_id": request.workspace_id,
                    "book_id": request.book_id,
                    "agent_id": request.agent_id,
                    "actor_id": principal.principal_id,
                    "idempotency_scope": "project:agent-runtime",
                    "idempotency_key": request.idempotency_key,
                    "trace_id": request.trace_id,
                    "span_id": str(uuid4()),
                    "correlation_id": request.correlation_id,
                    "causation_id": "",
                    "input": request.command_input(),
                    "input_assets": [
                        {
                            "asset_version_id": asset_version_id,
                            "content_hash": content_hash,
                        }
                        for asset_version_id, content_hash in request.input_assets
                    ],
                },
                context=context,
            )
            uow.commit()
        operation_id = str(admitted["operation_id"])
        start_saga(
            self.database_url,
            GraphCommandContext(
                project_id=request.project_id,
                actor_id=principal.principal_id,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            ),
            root_operation_id=operation_id,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, request.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=request.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="frozen Agent run admitted for worker execution",
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                ),
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            current = uow.repositories.attempt_runtime.operation_state(
                operation_id, request.project_id
            )
        return {
            "agent_run_id": operation_id,
            "operation_id": operation_id,
            "status": str(current["status"]),
            "replayed": bool(admitted["replayed"]),
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in agent_runtime_operation_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _execute_admin_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT definition_name, project_id, command_payload,
                   actor_id, trace_id, correlation_id
            FROM authority_operation
            WHERE operation_id=%s
            """,
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "Agent admin Operation disappeared")
        action, project_id, command_payload, actor_id, trace_id, correlation_id = row
        command = dict(command_payload or {})
        agent_id = str(command["agent_id"])
        payload = dict(command["payload"])
        expected_activation_version = int(
            command.get("expected_activation_version") or 0
        )
        checkpoint("after_admission")
        if action == "agent.definition.register":
            result = self._register_agent_definition(
                uow, payload=payload, operation_id=operation_id
            )
        elif action in {"agent.definition.activate", "agent.definition.disable"}:
            status = (
                AgentDefinitionActivationStatus.ACTIVE
                if action == "agent.definition.activate"
                else AgentDefinitionActivationStatus.DISABLED
            )
            activation = uow.repositories.agent_runtime.activate_definition(
                agent_id=agent_id,
                definition_version=int(payload["definition_version"]),
                status=status,
                expected_activation_version=expected_activation_version,
                reason=str(payload["reason"]),
                activated_by=str(actor_id),
                activated_by_operation_id=operation_id,
            )
            result = {
                "agent_id": activation.agent_id,
                "definition_version": activation.definition_version,
                "activation_status": activation.status.value,
                "activation_version": activation.activation_version,
            }
        elif action == "agent.chapter_binding.register":
            binding_payload = dict(payload)
            self._require_legacy_binding_mode(binding_payload)
            binding_payload.pop("authority_mode", None)
            compiled_payload = binding_payload.pop("compiled_capability_pack", None)
            if not isinstance(compiled_payload, Mapping):
                raise KernelError(
                    "CAPABILITY_PACK_COMPILED_PAYLOAD_REQUIRED",
                    "Chapter Agent Binding registration requires a compiled Pack",
                )
            binding_payload["created_by_operation_id"] = operation_id
            binding = ChapterNodeExecutionBinding(**binding_payload)
            compiled = compiled_capability_pack_from_payload(compiled_payload)
            operation_name, separator, operation_version = (
                binding.operation_definition_ref.rpartition("@")
            )
            if not separator:
                raise KernelError(
                    "CHAPTER_AGENT_OPERATION_DEFINITION_INVALID",
                    "Chapter Agent Binding requires an exact OperationDefinition ref",
                )
            authority_definition = uow.repositories.definitions.get(
                operation_name, operation_version
            )
            if authority_definition is None:
                raise KernelError(
                    "OPERATION_DEFINITION_NOT_FOUND",
                    "Chapter Agent Binding OperationDefinition is not registered",
                )
            bind_compiled_pack_for_admission(
                compiled=compiled,
                workflow_node_id=binding.workflow_node_id,
                chapter_binding=binding,
                authority_operation_definition=authority_definition,
            )
            uow.repositories.agent_runtime.register_chapter_node_binding(binding)
            result = {
                "binding_id": binding.binding_id,
                "binding_version": binding.binding_version,
                "binding_hash": binding.binding_hash,
            }
        elif action == "agent.chapter_binding.activate":
            self._require_legacy_binding_mode(payload)
            result = uow.repositories.agent_runtime.activate_chapter_node_binding(
                workflow_definition_ref=str(payload["workflow_definition_ref"]),
                workflow_node_id=str(payload["workflow_node_id"]),
                binding_id=str(payload["binding_id"]),
                binding_version=int(payload["binding_version"]),
                status=AgentDefinitionActivationStatus(
                    str(payload.get("status") or "ACTIVE")
                ),
                expected_activation_version=expected_activation_version,
                reason=str(payload["reason"]),
                activated_by=str(actor_id),
                activated_by_operation_id=operation_id,
            )
        else:
            raise KernelError(
                "AGENT_RUNTIME_ADMIN_COMMAND_INVALID",
                f"unsupported Agent Runtime action: {action}",
            )
        checkpoint("after_authority_write")
        event_type = f"authority.{action}.committed"
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_agent_definition",
                "aggregate_id": agent_id,
                "operation_id": operation_id,
                "project_id": str(project_id),
                "event_type": event_type,
                "correlation_id": str(correlation_id),
                "causation_id": operation_id,
                "payload": {
                    **result,
                    "operation_id": operation_id,
                    "project_id": str(project_id),
                    "trace_id": str(trace_id),
                    "execution_classification": "transaction_command",
                },
            }
        )
        checkpoint("after_outbox_insert")
        return result

    def _require_legacy_binding_mode(self, payload: Mapping[str, Any]) -> None:
        if self.runtime_environment in {
            "validation",
            "provider-validation",
            "production",
        }:
            raise KernelError(
                "CAPABILITY_PACK_DEPLOYMENT_REQUIRED",
                "controlled runtime forbids direct Chapter binding administration",
            )
        if str(payload.get("authority_mode") or "") not in {
            "DEVELOPMENT_FIXTURE",
            "LEGACY_MIGRATION",
            "BOOTSTRAP_ADAPTER",
        }:
            raise KernelError(
                "CAPABILITY_PACK_LEGACY_MODE_REQUIRED",
                "direct Chapter binding requires an explicit non-production legacy mode",
            )

    @staticmethod
    def _register_agent_definition(
        uow: AuthorityUnitOfWork,
        *,
        payload: Mapping[str, Any],
        operation_id: str,
    ) -> dict[str, Any]:
        capability_payload = dict(payload["capability"])
        capability_payload["supported_message_types"] = tuple(
            AgentMessageType(value)
            for value in capability_payload["supported_message_types"]
        )
        capability_payload["supported_scope_types"] = tuple(
            capability_payload["supported_scope_types"]
        )
        capability = AgentCapability(**capability_payload)
        definition_payload = dict(payload["definition"])
        for field in (
            "capability_refs",
            "allowed_tools",
            "allowed_context_types",
        ):
            definition_payload[field] = tuple(definition_payload[field])
        definition = AgentDefinition(**definition_payload)
        if definition.agent_id != str(payload["runtime_contract"]["agent_id"]):
            raise KernelError(
                "AGENT_DEFINITION_IDENTITY_CONFLICT",
                "Agent Definition and runtime contract identities differ",
            )
        uow.repositories.agent_collaboration.register_capability(capability)
        uow.repositories.agent_collaboration.register_definition(definition)
        mapping_payload = dict(payload["execution_mapping"])
        mapping_payload["created_by_operation_id"] = operation_id
        mapping = AgentCapabilityExecutionMapping(**mapping_payload)
        if (
            mapping.capability_id != capability.capability_id
            or mapping.capability_version != capability.version
        ):
            raise KernelError(
                "AGENT_CAPABILITY_MAPPING_IDENTITY_CONFLICT",
                "PEP Capability mapping does not match Agent Capability",
            )
        contract_payload = dict(payload["runtime_contract"])
        contract_payload["created_by_operation_id"] = operation_id
        contract = AgentDefinitionRuntimeContract(**contract_payload)
        if (
            contract.agent_id != definition.agent_id
            or contract.definition_version != definition.version
        ):
            raise KernelError(
                "AGENT_RUNTIME_CONTRACT_IDENTITY_CONFLICT",
                "runtime contract does not match Agent Definition version",
            )
        uow.repositories.agent_runtime.register_capability_execution_mapping(mapping)
        uow.repositories.agent_runtime.register_definition_runtime_contract(contract)
        return {
            "agent_id": definition.agent_id,
            "definition_version": definition.version,
            "definition_hash": definition.definition_hash,
            "runtime_contract_hash": contract.runtime_contract_hash,
            "capability_id": capability.capability_id,
            "capability_version": capability.version,
            "capability_hash": capability.capability_hash,
            "execution_capability_id": mapping.execution_capability_id,
        }

    @staticmethod
    def _validate_run_admission(
        request: AgentRunAdmissionRequest,
        *,
        active_definition: Mapping[str, Any],
        active_binding: Mapping[str, Any],
    ) -> None:
        expected_definition = {
            "definition_version": request.agent_definition_version,
            "definition_hash": request.agent_definition_hash,
            "capability_pack_ref": request.capability_pack_ref,
            "prompt_bundle_ref": request.prompt_bundle_ref,
            "prompt_bundle_hash": request.prompt_bundle_hash,
            "skill_bundle_ref": request.skill_bundle_ref,
            "skill_bundle_hash": request.skill_bundle_hash,
            "tool_policy_ref": request.tool_policy_ref,
            "tool_policy_hash": request.tool_policy_hash,
            "context_policy_ref": request.context_policy_ref,
            "context_policy_hash": request.context_policy_hash,
        }
        definition_drift = [
            key
            for key, value in expected_definition.items()
            if str(active_definition.get(key)) != str(value)
        ]
        if definition_drift:
            raise KernelError(
                "AGENT_DEFINITION_SNAPSHOT_DRIFT",
                "Agent run differs from active definition: "
                + ", ".join(definition_drift),
            )
        capability = next(
            (
                item
                for item in active_definition["capabilities"]
                if item["capability_id"] == request.capability_id
                and int(item["capability_version"]) == request.capability_version
            ),
            None,
        )
        if capability is None:
            raise KernelError(
                "AGENT_CAPABILITY_NOT_BOUND",
                "requested Agent Capability is not mapped by the active definition",
            )
        if capability["qualification_status"] != "QUALIFIED_REAL_RUNTIME":
            raise KernelError(
                "AGENT_CAPABILITY_NOT_PRODUCTION_QUALIFIED",
                "production Agent execution requires a REAL_RUNTIME-qualified Capability",
            )
        if (
            capability["capability_hash"] != request.capability_hash
            or capability["execution_capability_id"]
            != request.execution_capability_id
            or capability["execution_capability_hash"]
            != request.execution_capability_hash
        ):
            raise KernelError(
                "AGENT_CAPABILITY_SNAPSHOT_DRIFT",
                "Agent Capability or PEP mapping differs from frozen request",
            )
        expected_binding = {
            "chapter_node_binding_ref": request.chapter_node_binding_ref,
            "agent_id": request.agent_id,
            "agent_definition_version": request.agent_definition_version,
            "capability_id": request.capability_id,
            "capability_version": request.capability_version,
            "capability_pack_compilation_hash": (
                request.capability_pack_compilation_hash
            ),
            "release_sha": request.release_sha,
            "commit_authority": request.commit_authority,
            "capability_pack_deployment_id": request.capability_pack_deployment_id,
            "capability_pack_binding_set_id": request.capability_pack_binding_set_id,
            "capability_pack_binding_set_hash": (
                request.capability_pack_binding_set_hash
            ),
        }
        binding_drift = [
            key
            for key, value in expected_binding.items()
            if str(
                active_binding.get(key)
                if key != "chapter_node_binding_ref"
                else active_binding.get(key)
                or (
                    f"{active_binding.get('binding_id')}@"
                    f"{active_binding.get('binding_version')}"
                )
            )
            != str(value)
        ]
        if binding_drift:
            raise KernelError(
                "CHAPTER_AGENT_BINDING_SNAPSHOT_DRIFT",
                "Agent run differs from active Chapter binding: "
                + ", ".join(binding_drift),
            )

    @staticmethod
    def _validate_collaboration_scope(
        uow: AuthorityUnitOfWork, request: AgentRunAdmissionRequest
    ) -> None:
        session = uow.repositories.agent_collaboration.get_session(
            request.collaboration_session_id
        )
        if (
            session.project_id != request.project_id
            or session.scope_snapshot_ref != request.scope_snapshot_ref
            or session.participant_snapshot_ref != request.participant_snapshot_ref
        ):
            raise KernelError(
                "AGENT_COLLABORATION_SCOPE_DRIFT",
                "Agent run differs from its frozen collaboration session",
            )
        scope = uow.repositories.agent_collaboration.get_scope_snapshot(
            request.scope_snapshot_ref
        )
        if scope.contract.narrative.book_id != request.book_id:
            raise KernelError(
                "AGENT_COLLABORATION_BOOK_SCOPE_DRIFT",
                "Agent run book differs from its frozen ScopeSnapshot",
            )
        participants = uow.repositories.agent_collaboration.get_participant_snapshot(
            request.participant_snapshot_ref
        )
        participant = next(
            (item for item in participants.participants if item.agent_id == request.agent_id),
            None,
        )
        if (
            participant is None
            or participant.agent_definition_version
            != request.agent_definition_version
        ):
            raise KernelError(
                "AGENT_COLLABORATION_PARTICIPANT_DRIFT",
                "Agent run is not bound to the frozen participant version",
            )
        frozen_inputs = {item[0]: item[1] for item in request.input_assets}
        for asset_version_id, content_hash in frozen_inputs.items():
            uow.cursor.execute(
                """
                SELECT content_hash FROM authority_asset_version
                WHERE asset_version_id=%s AND project_id=%s
                """,
                [asset_version_id, request.project_id],
            )
            row = uow.cursor.fetchone()
            if row is None or str(row[0]) != content_hash:
                raise KernelError(
                    "AGENT_INPUT_ASSET_DRIFT",
                    "Agent run input AssetVersion is absent or changed",
                )
            if not scope.contract.asset_read.allows_version(asset_version_id):
                raise KernelError(
                    "AGENT_INPUT_OUTSIDE_SCOPE",
                    "Agent run input escaped the frozen Asset Read Scope",
                )
        expected_operation_ref = (
            f"agent.candidate.execute@{AGENT_RUNTIME_DEFINITION_VERSION}"
        )
        if request.operation_definition_ref != expected_operation_ref:
            raise KernelError(
                "AGENT_OPERATION_DEFINITION_DRIFT",
                "Agent run must use the shared Agent candidate OperationDefinition",
            )
        definition = uow.repositories.definitions.get(
            "agent.candidate.execute", AGENT_RUNTIME_DEFINITION_VERSION
        )
        if (
            definition is None
            or str(definition["definition_hash"])
            != request.operation_definition_hash
        ):
            raise KernelError(
                "AGENT_OPERATION_DEFINITION_DRIFT",
                "Agent run OperationDefinition content hash differs from Authority",
            )


def _ref_identity(value: str) -> str:
    identity, separator, _version = value.rpartition("@")
    if not separator or not identity:
        raise ValueError(f"version ref must be exact: {value}")
    return identity


def _ref_integer_version(value: str) -> int:
    _identity, separator, version = value.rpartition("@")
    if not separator:
        raise ValueError(f"version ref must be exact: {value}")
    parsed = int(version)
    if parsed <= 0:
        raise ValueError(f"version ref must be positive: {value}")
    return parsed


__all__ = [
    "AgentRunAdmissionRequest",
    "AgentRuntimeAdminCommand",
    "AgentRuntimeAuthorityApplication",
]
