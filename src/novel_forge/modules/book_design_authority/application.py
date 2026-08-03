"""Book + BookDesign commands through the shared Command Kernel."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority.definitions import (
    BOOK_DESIGN_DEFINITION_VERSION,
    BOOK_DESIGN_HANDLER_KEY,
    BOOK_DESIGN_OPERATIONS,
    book_design_definitions,
)
from novel_forge.modules.book_design_authority.domain import BookDesignPayload, BookScope
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import OperationTransitionCommand, transition_operation
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_design_authority_repositories import BookDesignAuthorityRepository


@dataclass(frozen=True, slots=True)
class BookDesignAuthorityCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    service_identity: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    payload: dict[str, Any]
    expected_book_version: int = 0
    expected_current_design_asset_version_id: str = ""
    target_asset_version_id: str = ""

    def __post_init__(self) -> None:
        if self.definition_name not in BOOK_DESIGN_OPERATIONS:
            raise ValueError(f"unsupported BookDesign Authority operation: {self.definition_name}")
        for field in (
            "project_id", "workspace_id", "book_id", "actor_id", "service_identity",
            "idempotency_key", "trace_id", "correlation_id",
        ):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"{field} is required")
        if self.expected_book_version < 0:
            raise ValueError("expected_book_version cannot be negative")


class BookDesignAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "authority-worker:book-design",
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id

    def execute(
        self, command: BookDesignAuthorityCommand, *, principal: Principal | None = None
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("book_design.authority.execute", command.project_id)
            actor_id = principal.principal_id
        self._register_definitions()
        command_input = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "service_identity": command.service_identity,
            "expected_book_version": command.expected_book_version,
            "expected_current_design_asset_version_id": command.expected_current_design_asset_version_id,
            "target_asset_version_id": command.target_asset_version_id,
            "payload": dict(command.payload),
        }
        input_assets: list[dict[str, str]] = []
        if command.target_asset_version_id:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT version.content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                    WHERE version.asset_version_id = %s AND asset.project_id = %s
                    """,
                    [command.target_asset_version_id, command.project_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    raise KernelError("BOOK_DESIGN_CANDIDATE_NOT_FOUND", "target AssetVersion is outside project scope")
                input_assets.append({"asset_version_id": command.target_asset_version_id, "content_hash": row[0]})
        context = AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"book_design.authority.execute"}),
            available_handlers=frozenset({BOOK_DESIGN_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": BOOK_DESIGN_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "book:design",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": command_input,
                "input_assets": input_assets,
            },
            context=context,
        )
        operation_id = str(admitted["operation_id"])
        state = self._operation_state(operation_id, command.project_id)
        if state["status"] == "SUCCEEDED":
            return self._result(operation_id, command.project_id, replayed=True)
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="BookDesign transaction command ready",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id="",
                ),
            )
        return self._run(operation_id, command.project_id)

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in book_design_definitions(
                application_build_id=self.application_build_id, commit_sha=self.commit_sha
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _run(self, operation_id: str, project_id: str) -> dict[str, Any]:
        state = self._operation_state(operation_id, project_id)
        if state["status"] not in {"READY", "FAILED_RETRYABLE"}:
            raise KernelError("BOOK_DESIGN_OPERATION_NOT_RUNNABLE", f"operation is not runnable from {state['status']}")
        attempt = create_attempt(
            self.database_url,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        if attempt["dead_letter"] or not attempt["attempt_id"]:
            raise KernelError("BOOK_DESIGN_OPERATION_DEAD_LETTER", "retry policy exhausted")
        attempt_id = str(attempt["attempt_id"])
        queue_attempt(
            self.database_url, attempt_id=attempt_id, project_id=project_id,
            trace_id=str(state["trace_id"]), correlation_id=str(state["correlation_id"]),
        )
        lease = acquire_attempt_lease(
            self.database_url, attempt_id=attempt_id, project_id=project_id,
            worker_id=self.worker_id, lease_seconds=30,
            trace_id=str(state["trace_id"]), correlation_id=str(state["correlation_id"]),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
            causation_id=operation_id,
        )
        start_attempt(self.database_url, worker)
        try:
            result = self._execute_fenced(worker)
            current = self._operation_state(operation_id, project_id)
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_version=int(current["version"]),
                    expected_operation_status=str(current["status"]),
                ),
                outcome="success",
                result=result,
            )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            try:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=False,
                    error_code=exc.code if isinstance(exc, KernelError) else "BOOK_DESIGN_HANDLER_FAILED",
                    error_message=str(exc),
                    failure_class="DOMAIN_OR_CONCURRENCY_FAILURE",
                )
            except KernelError:
                pass
            raise
        return self._result(operation_id, project_id, replayed=False)

    def _execute_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            payload = dict(operation["command_payload"])
            action = str(operation["definition_name"])
            project_id = str(payload["project_id"])
            workspace_id = str(payload["workspace_id"])
            book_id = str(payload["book_id"])
            actor_id = str(operation["actor_id"])
            repository = BookDesignAuthorityRepository(uow.cursor)
            result: dict[str, Any] = {"book_id": book_id}
            if action == "book.create":
                scope = BookScope.from_mapping(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    book_id=book_id,
                    principal=actor_id,
                    service_identity=str(payload["service_identity"]),
                    payload=dict(payload["payload"]),
                )
                content = scope.content(title=str(payload["payload"].get("title") or ""))
                document = uow.repositories.asset_documents.materialize_output(
                    AuthorityAssetWriteCommand(
                        operation_id=worker.causation_id,
                        project_id=project_id,
                        asset_id=f"book:{book_id}",
                        asset_type="book_record",
                        logical_ref=f"books/{book_id}",
                        category="books",
                        output_key="book.record",
                        role="primary",
                        content=content,
                        qualification_policy="book-authority-v1",
                        trace_id=worker.trace_id,
                        correlation_id=worker.correlation_id,
                        causation_id=worker.causation_id,
                    )
                )
                repository.create_book(
                    scope=scope,
                    book_asset_version_id=document.asset_version_id,
                    operation_id=worker.causation_id,
                )
                result["asset_version_id"] = document.asset_version_id
                result["content_hash"] = document.content_hash
            else:
                book = repository.book_for_update(
                    project_id=project_id, workspace_id=workspace_id, book_id=book_id
                )
                expected_version = int(payload["expected_book_version"])
                expected_design = str(payload.get("expected_current_design_asset_version_id") or "")
                if expected_version != book["version"] or expected_design != book["current_design_asset_version_id"]:
                    raise KernelError("BOOK_VERSION_CONFLICT", "expected Book/design version is stale")
                if action == "book_design.propose":
                    design = BookDesignPayload.from_mapping(dict(payload["payload"]))
                    result.update(
                        repository.propose(
                            book=book, design=design, operation_id=worker.causation_id,
                            trace_id=worker.trace_id,
                        )
                    )
                elif action == "book_design.decide":
                    target = str(payload.get("target_asset_version_id") or "")
                    result["asset_version_id"] = target
                    result["decision_id"] = repository.decide(
                        book=book,
                        asset_version_id=target,
                        decision=str(payload["payload"].get("decision") or ""),
                        reason=str(payload["payload"].get("reason") or ""),
                        decided_by=actor_id,
                        operation_id=worker.causation_id,
                    )
                elif action == "book_design.activate":
                    target = str(payload.get("target_asset_version_id") or "")
                    result["asset_version_id"] = target
                    result.update(
                        repository.activate(
                            book=book,
                            asset_version_id=target,
                            reason=str(payload["payload"].get("reason") or ""),
                            operation_id=worker.causation_id,
                        )
                    )
                else:
                    raise KernelError("BOOK_DESIGN_COMMAND_INVALID", f"unsupported action: {action}")
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_book",
                    "aggregate_id": book_id,
                    "operation_id": worker.causation_id,
                    "project_id": project_id,
                    "event_type": f"authority.{action}.committed",
                    "correlation_id": worker.correlation_id,
                    "causation_id": worker.causation_id,
                    "payload": {
                        **result,
                        "operation_id": worker.causation_id,
                        "project_id": project_id,
                        "workspace_id": workspace_id,
                        "trace_id": worker.trace_id,
                        "attempt_id": worker.attempt_id,
                        "fencing_token": worker.fencing_token,
                    },
                }
            )
            uow.commit()
            return result

    def _operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
            uow.cursor.execute(
                "SELECT trace_id, correlation_id FROM authority_operation WHERE operation_id = %s",
                [operation_id],
            )
            trace_id, correlation_id = uow.cursor.fetchone()
        return {**state, "trace_id": trace_id, "correlation_id": correlation_id}

    def _result(self, operation_id: str, project_id: str, *, replayed: bool) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, COALESCE(attempt.result, '{}'::jsonb)
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT result FROM authority_attempt
                    WHERE operation_id = operation.operation_id
                    ORDER BY attempt_number DESC LIMIT 1
                ) AS attempt ON TRUE
                WHERE operation.operation_id = %s AND operation.project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_DESIGN_OPERATION_NOT_FOUND", "operation result is missing")
        return {
            "operation_id": operation_id,
            "status": row[0],
            **dict(row[1] or {}),
            "replayed": replayed,
        }


__all__ = ["BookDesignAuthorityApplication", "BookDesignAuthorityCommand"]
