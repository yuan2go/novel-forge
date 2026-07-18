"""Synchronous worker facade for one Content Authority Operation.

The facade coordinates existing Command Kernel primitives; it is not a second runtime.
Schedulers may call the lower-level admission/attempt/runtime functions directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import AuthorityExecutionResult
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.definitions import (
    CONTENT_DEFINITION_VERSION,
    content_operation_definitions,
)
from novel_forge.modules.content_authority.registry import ContentHandlerRegistry
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ContentOperationRequest:
    definition_name: str
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    payload: dict[str, Any]
    input_assets: tuple[dict[str, str], ...] = ()
    approval: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ContentOperationAdmission:
    operation_id: str
    project_id: str
    replayed: bool


class ContentAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        integration_proven: Collection[str],
        registry: ContentHandlerRegistry | None = None,
        trusted_only: bool = False,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.integration_proven = frozenset(integration_proven)
        self.registry = registry or ContentHandlerRegistry()
        self.trusted_only = trusted_only

    def execute(
        self,
        request: ContentOperationRequest,
        *,
        principal: Principal | None = None,
    ) -> AuthorityExecutionResult:
        admission = self.admit(request, principal=principal)
        return ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=admission.project_id,
        ).output

    def admit(
        self,
        request: ContentOperationRequest,
        *,
        principal: Principal | None = None,
    ) -> ContentOperationAdmission:
        definitions = content_operation_definitions(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            integration_proven=self.integration_proven,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()
        if self.trusted_only and principal is None:
            raise PermissionError("trusted Principal is required for Content admission")
        actor_id = request.actor_id
        permissions = frozenset(self.registry.definition_names)
        if principal is not None:
            principal.require("content.authority.execute", request.project_id)
            actor_id = principal.principal_id
            permissions = (
                frozenset(self.registry.definition_names)
                if principal.allows("content.authority.execute", request.project_id)
                else frozenset()
            )
        admission = AdmissionContext(
            actor_id=actor_id,
            permissions=permissions,
            available_handlers=self.registry.available_handler_keys,
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": request.definition_name,
                "definition_version": CONTENT_DEFINITION_VERSION,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:content-domain",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": request.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in request.input_assets
                    ],
                    "payload": request.payload,
                },
                "input_assets": list(request.input_assets),
                "approval": request.approval,
            },
            context=admission,
        )
        operation_id = str(admitted["operation_id"])
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
                    expected_version=state["version"],
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="content operation ready",
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                    causation_id="",
                ),
            )
        return ContentOperationAdmission(
            operation_id=operation_id,
            project_id=request.project_id,
            replayed=bool(admitted["replayed"]),
        )


__all__ = [
    "ContentAuthorityApplication",
    "ContentOperationAdmission",
    "ContentOperationRequest",
]
