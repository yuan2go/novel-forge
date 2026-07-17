"""Synchronous worker facade for one Content Authority Operation.

The facade coordinates existing Command Kernel primitives; it is not a second runtime.
Schedulers may call the lower-level admission/attempt/runtime functions directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import AuthorityExecutionResult
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.definitions import (
    CONTENT_DEFINITION_VERSION,
    content_operation_definitions,
)
from novel_forge.modules.content_authority.registry import ContentHandlerRegistry
from novel_forge.modules.content_authority.runtime import execute_content_handler
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


class ContentAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        integration_proven: Collection[str],
        registry: ContentHandlerRegistry | None = None,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.integration_proven = frozenset(integration_proven)
        self.registry = registry or ContentHandlerRegistry()

    def execute(self, request: ContentOperationRequest) -> AuthorityExecutionResult:
        definitions = content_operation_definitions(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            integration_proven=self.integration_proven,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()
        admission = AdmissionContext(
            actor_id=request.actor_id,
            permissions=frozenset(self.registry.definition_names),
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
                "actor_id": request.actor_id,
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
        operation_id = admitted["operation_id"]
        if admitted["replayed"]:
            existing = self._existing_result(operation_id, request.project_id)
            if existing is not None:
                return existing
        transition_operation(
            self.database_url,
            OperationTransitionCommand(
                operation_id=operation_id,
                project_id=request.project_id,
                expected_version=0,
                expected_status="ADMITTED",
                target_status="READY",
                actor_id=request.actor_id,
                reason="content operation ready",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                causation_id="",
            ),
        )
        attempt_id = create_attempt(
            self.database_url,
            operation_id=operation_id,
            project_id=request.project_id,
            max_attempts=2,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )["attempt_id"]
        queue_attempt(
            self.database_url,
            attempt_id=attempt_id,
            project_id=request.project_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=request.project_id,
            worker_id="content-authority-worker",
            lease_seconds=30,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=request.project_id,
            worker_id="content-authority-worker",
            fencing_token=lease["fencing_token"],
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            causation_id=operation_id,
        )
        start_attempt(self.database_url, worker)
        output = execute_content_handler(
            self.database_url,
            command=worker,
            definition_name=request.definition_name,
            definition_version=CONTENT_DEFINITION_VERSION,
            registry=self.registry,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(operation_id, request.project_id)
        submit_attempt_result(
            self.database_url,
            WorkerResultCommand(
                attempt_id=worker.attempt_id,
                project_id=worker.project_id,
                worker_id=worker.worker_id,
                fencing_token=worker.fencing_token,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=worker.causation_id,
                expected_operation_status=state["status"],
                expected_operation_version=state["version"],
            ),
            outcome="success",
            result={"asset_version_id": output.asset_version_id, "content_hash": output.content_hash},
        )
        return output

    def _existing_result(self, operation_id: str, project_id: str) -> AuthorityExecutionResult | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_id, binding.asset_version_id, binding.content_hash,
                       binding.output_key, operation.status
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation ON operation.operation_id = binding.operation_id
                WHERE binding.operation_id = %s AND operation.project_id = %s
                  AND binding.role = 'primary'
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        if row[4] != "SUCCEEDED":
            raise KernelError(
                "CONTENT_OPERATION_RECOVERY_REQUIRED",
                "an output exists but Completion is not terminal; resume the fenced Attempt",
            )
        return AuthorityExecutionResult(
            operation_id=operation_id,
            asset_id=row[0],
            asset_version_id=row[1],
            content_hash=row[2],
            output_key=row[3],
            replayed=True,
        )


__all__ = ["ContentAuthorityApplication", "ContentOperationRequest"]
