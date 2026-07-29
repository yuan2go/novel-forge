"""Command application over the existing Command Kernel and Attempt scheduler."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import BOOK_FOLLOWUP_DEFINITION_VERSION, ReaderOutcomeModelPort
from .definitions import book_followup_operation_definitions
from .registry import BookFollowupHandlerRegistry


@dataclass(frozen=True, slots=True)
class BookFollowupCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    payload: dict[str, Any]
    input_assets: tuple[dict[str, str], ...] = ()
    root_operation_id: str | None = None
    parent_operation_id: str | None = None
    causation_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BookFollowupAdmission:
    operation_id: str
    project_id: str
    replayed: bool


class BookFollowupAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        model_port: ReaderOutcomeModelPort | None = None,
        worker_id: str = "book-followup-authority-worker",
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("PostgreSQL, build id, and full commit SHA are required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.registry = BookFollowupHandlerRegistry(model_port)
        self.worker_id = worker_id

    def admit(
        self, request: BookFollowupCommand, *, principal: Principal
    ) -> BookFollowupAdmission:
        permission = f"book.followup:{request.definition_name}"
        principal.require("book.authority.execute", request.project_id)
        principal.require(permission, request.project_id)
        if request.actor_id != principal.principal_id:
            raise PermissionError("Book follow-up actor must be the trusted Principal")
        definitions = book_followup_operation_definitions(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": request.definition_name,
                "definition_version": BOOK_FOLLOWUP_DEFINITION_VERSION,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "actor_id": request.actor_id,
                "idempotency_scope": "project:book-followup",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": request.causation_operation_id or "",
                "input": {
                    "project_id": request.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in request.input_assets
                    ],
                    "payload": request.payload,
                },
                "input_assets": list(request.input_assets),
                "root_operation_id": request.root_operation_id,
                "parent_operation_id": request.parent_operation_id,
                "causation_operation_id": request.causation_operation_id,
            },
            context=AdmissionContext(
                actor_id=request.actor_id,
                permissions=frozenset({permission}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
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
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=request.actor_id,
                    reason="book follow-up operation ready",
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                    causation_id="",
                ),
            )
        if request.root_operation_id is None:
            # Standalone development/test operations need a graph context because
            # the production execution binder requires an Authority Saga. Real
            # Book production supplies and owns its coordinating root Saga.
            start_saga(
                self.database_url,
                GraphCommandContext(
                    request.project_id,
                    request.actor_id,
                    request.trace_id,
                    request.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        return BookFollowupAdmission(
            operation_id=operation_id,
            project_id=request.project_id,
            replayed=bool(admitted["replayed"]),
        )

    def run_or_recover(self, admission: BookFollowupAdmission):
        return ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,  # shared scheduler protocol; no new Attempt runtime
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=admission.project_id,
        )


__all__ = [
    "BookFollowupAdmission",
    "BookFollowupAuthorityApplication",
    "BookFollowupCommand",
]
