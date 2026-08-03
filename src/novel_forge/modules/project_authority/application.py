"""Project/Workspace commands over the shared Command Kernel runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.project_authority.definitions import (
    PROJECT_AUTHORITY_DEFINITION_VERSION,
    PROJECT_AUTHORITY_HANDLER_KEY,
    PROJECT_AUTHORITY_OPERATIONS,
    project_authority_definitions,
)
from novel_forge.modules.project_authority.domain import (
    build_project_snapshot,
    build_workspace_snapshot,
    transition_project_snapshot,
    update_project_snapshot,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.project_authority_repositories import (
    ProjectAuthorityRepository,
    _binding_logical_ref,
)


@dataclass(frozen=True, slots=True)
class ProjectAuthorityCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    payload: dict[str, Any]
    expected_version: int = 0
    expected_current_asset_version_id: str = ""

    def __post_init__(self) -> None:
        if self.definition_name not in PROJECT_AUTHORITY_OPERATIONS:
            raise ValueError(
                f"unsupported Project Authority operation: {self.definition_name}"
            )
        for name in (
            "project_id",
            "workspace_id",
            "actor_id",
            "idempotency_key",
            "trace_id",
            "correlation_id",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.expected_version < 0:
            raise ValueError("expected_version cannot be negative")


class ProjectAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

    def execute(
        self, command: ProjectAuthorityCommand, *, principal: Principal | None = None
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("project.authority.execute", command.project_id)
            actor_id = principal.principal_id
        self._register_definitions()
        command_input = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "expected_version": command.expected_version,
            "payload": dict(command.payload),
        }
        input_assets: list[dict[str, str]] = []
        input_version_ids = [command.expected_current_asset_version_id]
        if command.definition_name.startswith("project_binding."):
            input_version_ids.extend(
                [
                    str(command.payload.get("target_asset_version_id") or ""),
                    str(command.payload.get("expected_binding_asset_version_id") or ""),
                ]
            )
        if command.expected_current_asset_version_id:
            command_input["expected_current_asset_version_id"] = (
                command.expected_current_asset_version_id
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            for asset_version_id in dict.fromkeys(
                value for value in input_version_ids if value
            ):
                document = uow.repositories.asset_documents.require(
                    project_id=command.project_id,
                    asset_version_id=asset_version_id,
                )
                input_assets.append(
                    {
                        "asset_version_id": document.asset_version_id,
                        "content_hash": document.content_hash,
                    }
                )
        context = AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"project.authority.execute"}),
            available_handlers=frozenset({PROJECT_AUTHORITY_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": PROJECT_AUTHORITY_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:lifecycle",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": command_input,
                "input_assets": input_assets,
            },
            context=context,
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in project_authority_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        project_id = self._project_for_operation(uow, operation_id)
        operation = uow.repositories.chapter_authority.operation_execution(
            operation_id, project_id
        )
        payload = dict(operation["command_payload"])
        action = str(operation["definition_name"])
        project_id = str(payload["project_id"])
        workspace_id = str(payload["workspace_id"])
        expected_version = int(payload["expected_version"])
        expected_asset_version = str(
            payload.get("expected_current_asset_version_id") or ""
        )
        repository = ProjectAuthorityRepository(uow.cursor)
        binding_document = None
        binding_type = ""
        binding_target_version_id = ""
        if action == "project_lifecycle.create":
            project = build_project_snapshot(
                project_id=project_id,
                workspace_id=workspace_id,
                payload=dict(payload["payload"]),
            )
            workspace = build_workspace_snapshot(
                project_id=project_id,
                workspace_id=workspace_id,
                payload=dict(payload["payload"]),
            )
            checkpoint("after_domain_validation")
        else:
            current = repository.lock_project(project_id)
            if current["workspace_id"] != workspace_id:
                raise KernelError(
                    "WORKSPACE_SCOPE_CONFLICT",
                    "command workspace is not the project's primary workspace",
                )
            if (
                expected_version != current["version"]
                or expected_asset_version != current["asset_version_id"]
            ):
                raise KernelError(
                    "PROJECT_VERSION_CONFLICT",
                    "expected Project version does not match PostgreSQL Authority",
                )
            if action == "project_lifecycle.update":
                project = update_project_snapshot(
                    dict(current["content"]), dict(payload["payload"])
                )
                checkpoint("after_domain_validation")
            elif action == "project_lifecycle.transition":
                project = transition_project_snapshot(
                    dict(current["content"]),
                    target_status=str(payload["payload"].get("target_status") or ""),
                )
                checkpoint("after_domain_validation")
            else:
                binding_payload = dict(payload["payload"])
                binding_type = (
                    str(binding_payload.get("binding_type") or "").strip().upper()
                )
                if not binding_type:
                    raise KernelError(
                        "PROJECT_BINDING_TYPE_INVALID", "binding_type is required"
                    )
                current_decision = repository.current_binding_decision_version(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    binding_type=binding_type,
                )
                expected_binding = str(
                    binding_payload.get("expected_binding_asset_version_id") or ""
                )
                if expected_binding != current_decision:
                    raise KernelError(
                        "PROJECT_BINDING_VERSION_CONFLICT",
                        "expected binding decision does not match PostgreSQL Authority",
                    )
                active_binding = repository.current_binding_for_update(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    binding_type=binding_type,
                )
                target_asset_id = ""
                if action == "project_binding.assign":
                    binding_target_version_id = str(
                        binding_payload.get("target_asset_version_id") or ""
                    )
                    target = repository.require_binding_target(
                        project_id=project_id,
                        asset_version_id=binding_target_version_id,
                        binding_type=binding_type,
                    )
                    target_asset_id = target["asset_id"]
                    binding_status = "BOUND"
                elif action == "project_binding.remove":
                    if active_binding is None:
                        raise KernelError(
                            "PROJECT_BINDING_NOT_FOUND",
                            "active Project binding does not exist",
                        )
                    binding_target_version_id = str(
                        active_binding["target_asset_version_id"]
                    )
                    binding_status = "REMOVED"
                else:
                    raise KernelError(
                        "PROJECT_COMMAND_INVALID",
                        f"unsupported Project Authority action: {action}",
                    )
                checkpoint("after_domain_validation")
                binding_snapshot = {
                    "schema_version": "project-binding-authority.v1",
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "binding_type": binding_type,
                    "target_asset_version_id": binding_target_version_id,
                    "status": binding_status,
                    "previous_binding_asset_version_id": current_decision,
                }
                binding_document = uow.repositories.asset_documents.materialize_output(
                    AuthorityAssetWriteCommand(
                        operation_id=operation_id,
                        project_id=project_id,
                        asset_id=(
                            f"project-binding:{project_id}:{workspace_id}:"
                            f"{binding_type.lower()}"
                        ),
                            asset_type="project_binding_record",
                            schema_version="project-binding-authority.v1",
                        logical_ref=_binding_logical_ref(workspace_id, binding_type),
                        category="project-bindings",
                        output_key="project.binding",
                        role="primary_binding",
                        content=binding_snapshot,
                        qualification_policy="project-binding-authority-v1",
                        trace_id=str(operation["trace_id"]),
                        correlation_id=str(operation["correlation_id"]),
                        causation_id=operation_id,
                        expected_current_asset_version_id=(current_decision or None),
                        reference_asset_ids=(
                            (target_asset_id,) if target_asset_id else ()
                        ),
                    )
                )
                checkpoint("after_asset_version_insert")
                project = dict(current["content"])
                bindings = dict(project.get("bindings") or {})
                decisions = dict(project.get("binding_decisions") or {})
                if action == "project_binding.assign":
                    bindings[binding_type] = {
                        "target_asset_version_id": binding_target_version_id,
                        "binding_asset_version_id": (binding_document.asset_version_id),
                    }
                else:
                    bindings.pop(binding_type, None)
                decisions[binding_type] = binding_document.asset_version_id
                project["bindings"] = bindings
                project["binding_decisions"] = decisions
            workspace = {}
        project_document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"project:{project_id}",
                    asset_type="project_record",
                    schema_version="project-authority.v1",
                logical_ref=f"projects/{project_id}",
                category="projects",
                output_key="project.record",
                role="primary",
                content=project,
                qualification_policy="project-authority-v1",
                trace_id=str(operation["trace_id"]),
                correlation_id=str(operation["correlation_id"]),
                causation_id=operation_id,
                expected_current_asset_version_id=expected_asset_version or None,
            )
        )
        checkpoint("after_asset_version_insert")
        if action == "project_lifecycle.create":
            workspace_document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id=f"workspace:{workspace_id}",
                        asset_type="workspace_record",
                        schema_version="workspace-authority.v1",
                    logical_ref=f"workspaces/{workspace_id}",
                    category="workspaces",
                    output_key="workspace.record",
                    role="primary_workspace",
                    content=workspace,
                    qualification_policy="workspace-authority-v1",
                    trace_id=str(operation["trace_id"]),
                    correlation_id=str(operation["correlation_id"]),
                    causation_id=operation_id,
                )
            )
            checkpoint("after_asset_version_insert")
            repository.create(
                project=project,
                project_asset_version_id=project_document.asset_version_id,
                workspace=workspace,
                workspace_asset_version_id=workspace_document.asset_version_id,
                operation_id=operation_id,
            )
        else:
            repository.update(
                project=project,
                project_asset_version_id=project_document.asset_version_id,
                operation_id=operation_id,
                expected_version=expected_version,
                expected_current_asset_version_id=expected_asset_version,
            )
            if binding_document is not None:
                if action == "project_binding.assign":
                    repository.assign_binding(
                        binding_id=f"binding:{binding_document.asset_version_id}",
                        binding_asset_version_id=(binding_document.asset_version_id),
                        project_id=project_id,
                        workspace_id=workspace_id,
                        binding_type=binding_type,
                        target_asset_version_id=binding_target_version_id,
                        operation_id=operation_id,
                    )
                else:
                    repository.remove_binding(
                        project_id=project_id,
                        workspace_id=workspace_id,
                        binding_type=binding_type,
                        operation_id=operation_id,
                    )
        checkpoint("after_business_projection_update")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_project",
                "aggregate_id": project_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": f"authority.{action}.committed",
                "correlation_id": str(operation["correlation_id"]),
                "causation_id": operation_id,
                "payload": {
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "asset_version_id": project_document.asset_version_id,
                    "content_hash": project_document.content_hash,
                    "trace_id": str(operation["trace_id"]),
                    "execution_classification": "transaction_command",
                    "binding_type": binding_type,
                    "binding_asset_version_id": (
                        binding_document.asset_version_id
                        if binding_document is not None
                        else ""
                    ),
                    "target_asset_version_id": binding_target_version_id,
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "version": 1
            if action == "project_lifecycle.create"
            else expected_version + 1,
            "asset_version_id": project_document.asset_version_id,
            "content_hash": project_document.content_hash,
        }

    @staticmethod
    def _project_for_operation(uow: AuthorityUnitOfWork, operation_id: str) -> str:
        uow.cursor.execute(
            "SELECT project_id FROM authority_operation WHERE operation_id = %s",
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "Project Operation disappeared")
        return str(row[0])


__all__ = ["ProjectAuthorityApplication", "ProjectAuthorityCommand"]
