"""Recovery-aware Content Authority worker over Command Kernel Attempt primitives."""
from __future__ import annotations

from dataclasses import dataclass

from novel_forge.modules.authority_handler_runtime import AuthorityExecutionResult
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
    heartbeat_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)
from novel_forge.modules.content_authority.registry import ContentHandlerRegistry
from novel_forge.modules.content_authority.runtime import execute_content_handler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ContentScheduledExecution:
    output: AuthorityExecutionResult
    attempt_id: str
    attempt_number: int
    recovery_mode: str


class ContentAuthorityScheduler:
    """Runs or recovers one admitted Operation without creating a parallel scheduler."""

    def __init__(
        self,
        database_url: str,
        *,
        registry: ContentHandlerRegistry,
        worker_id: str = "content-authority-worker",
        lease_seconds: int = 30,
    ) -> None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_id and positive lease_seconds are required")
        self.database_url = database_url
        self.registry = registry
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def pending_operations(self, *, limit: int = 50) -> tuple[tuple[str, str], ...]:
        """Return recoverable work; lease arbitration remains authoritative."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.operation_id, operation.project_id
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT lease.expires_at
                    FROM authority_attempt AS attempt
                    JOIN authority_lease_acquisition AS lease
                      ON lease.attempt_id = attempt.attempt_id
                    WHERE attempt.operation_id = operation.operation_id
                      AND lease.status = 'HELD'
                    ORDER BY attempt.attempt_number DESC, lease.fencing_token DESC
                    LIMIT 1
                ) AS active_lease ON TRUE
                WHERE operation.definition_name = ANY(%s)
                  AND operation.status IN ('READY', 'FAILED_RETRYABLE', 'EXECUTING')
                  AND (active_lease.expires_at IS NULL OR active_lease.expires_at <= NOW())
                ORDER BY operation.created_at, operation.operation_id
                LIMIT %s
                """,
                [list(self.registry.definition_names), limit],
            )
            rows = uow.cursor.fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def run_or_recover(
        self,
        *,
        operation_id: str,
        project_id: str,
    ) -> ContentScheduledExecution:
        state = self._state(operation_id, project_id)
        if state["operation_status"] == "SUCCEEDED":
            output = self._existing_result(operation_id, project_id)
            if output is None:
                raise KernelError(
                    "CONTENT_RECOVERY_OUTPUT_MISSING",
                    "succeeded Content Operation has no primary output",
                )
            return ContentScheduledExecution(
                output=output,
                attempt_id=str(state.get("attempt_id") or ""),
                attempt_number=int(state.get("attempt_number") or 0),
                recovery_mode="operation_replay",
            )
        if state["operation_status"] in {
            "FAILED_FINAL",
            "DEAD_LETTER",
            "CANCELLED",
        }:
            raise KernelError(
                "CONTENT_RECOVERY_TERMINAL",
                f"Content Operation is terminal: {state['operation_status']}",
            )

        recovery_mode = "fresh_attempt"
        if state["operation_status"] in {"READY", "FAILED_RETRYABLE"}:
            retrying = state["operation_status"] == "FAILED_RETRYABLE"
            attempt = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=int(state["max_attempts"]),
                trace_id=state["trace_id"],
                correlation_id=state["correlation_id"],
            )
            if attempt["dead_letter"] or attempt["attempt_id"] is None:
                raise KernelError(
                    "CONTENT_RECOVERY_RETRY_EXHAUSTED",
                    "Content Operation retry policy is exhausted",
                )
            attempt_id = str(attempt["attempt_id"])
            attempt_number = int(attempt["attempt_number"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=state["trace_id"],
                correlation_id=state["correlation_id"],
            )
            attempt_status = "QUEUED"
            recovery_mode = "retry_attempt" if retrying else recovery_mode
        elif state["operation_status"] == "EXECUTING" and state.get("attempt_id"):
            attempt_id = str(state["attempt_id"])
            attempt_number = int(state["attempt_number"])
            attempt_status = str(state["attempt_status"])
            recovery_mode = (
                "output_replay_takeover"
                if self._existing_result(operation_id, project_id, require_succeeded=False)
                else "lease_takeover"
            )
        else:
            raise KernelError(
                "CONTENT_RECOVERY_STATE_INVALID",
                "Content Operation has no recoverable Attempt",
            )

        try:
            lease = acquire_attempt_lease(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                trace_id=state["trace_id"],
                correlation_id=state["correlation_id"],
            )
        except KernelError as exc:
            if exc.code == "LEASE_NOT_AVAILABLE":
                raise KernelError(
                    "CONTENT_RECOVERY_LEASE_ACTIVE",
                    "another worker still owns the Content Attempt lease",
                ) from exc
            raise
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=state["trace_id"],
            correlation_id=state["correlation_id"],
            causation_id=operation_id,
        )
        if attempt_status in {"QUEUED", "LEASED"}:
            start_attempt(self.database_url, worker)
        elif attempt_status not in {"RUNNING", "CHECKPOINTED"}:
            raise KernelError(
                "CONTENT_RECOVERY_ATTEMPT_INVALID",
                f"Content Attempt cannot resume from {attempt_status}",
            )
        try:
            with LeaseHeartbeatGuard(
                lambda: heartbeat_attempt(self.database_url, worker, self.lease_seconds),
                lease_seconds=self.lease_seconds,
                label=f"attempt:{attempt_id}",
            ):
                output = execute_content_handler(
                    self.database_url,
                    command=worker,
                    definition_name=state["definition_name"],
                    definition_version=state["definition_version"],
                    registry=self.registry,
                )
            with AuthorityUnitOfWork(self.database_url) as uow:
                operation = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_status=operation["status"],
                    expected_operation_version=operation["version"],
                ),
                outcome="success",
                result={
                    "asset_version_id": output.asset_version_id,
                    "content_hash": output.content_hash,
                    "recovery_mode": recovery_mode,
                },
            )
        except BaseException as exc:
            classification = WorkerFailureClassifier.classify(exc)
            if classification not in {
                WorkerFailureClass.LEASE_CONFLICT,
                WorkerFailureClass.FENCING_CONFLICT,
                WorkerFailureClass.CANCELLATION,
                WorkerFailureClass.UNKNOWN_EXTERNAL_STATE,
            }:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=classification is WorkerFailureClass.RETRYABLE,
                    error_code=exc.code if isinstance(exc, KernelError) else "PROGRAMMING_BUG",
                    error_message=str(exc),
                    failure_class=classification.value,
                )
            raise
        return ContentScheduledExecution(
            output=output,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            recovery_mode=recovery_mode,
        )

    def _state(self, operation_id: str, project_id: str) -> dict[str, object]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, operation.definition_name,
                       operation.definition_version, operation.trace_id,
                       operation.correlation_id,
                       COALESCE((operation.definition_snapshot->'retry_policy'->>'max_attempts')::int, 1),
                       attempt.attempt_id, attempt.attempt_number, attempt.status
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT attempt_id, attempt_number, status
                    FROM authority_attempt
                    WHERE operation_id = operation.operation_id
                      AND status IN (
                          'CREATED', 'QUEUED', 'LEASED', 'RUNNING',
                          'CHECKPOINTED', 'RESULT_SUBMITTED'
                      )
                    ORDER BY attempt_number DESC
                    LIMIT 1
                ) AS attempt ON TRUE
                WHERE operation.operation_id = %s AND operation.project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "Content Operation does not exist")
        return dict(
            zip(
                (
                    "operation_status", "definition_name", "definition_version",
                    "trace_id", "correlation_id",
                    "max_attempts", "attempt_id", "attempt_number", "attempt_status",
                ),
                row,
                strict=True,
            )
        )

    def _existing_result(
        self,
        operation_id: str,
        project_id: str,
        *,
        require_succeeded: bool = True,
    ) -> AuthorityExecutionResult | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_id, binding.asset_version_id, binding.content_hash,
                       binding.output_key, operation.status
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                WHERE binding.operation_id = %s AND operation.project_id = %s
                  AND binding.role = 'primary'
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None or (require_succeeded and row[4] != "SUCCEEDED"):
            return None
        return AuthorityExecutionResult(
            operation_id=operation_id,
            asset_id=row[0],
            asset_version_id=row[1],
            content_hash=row[2],
            output_key=row[3],
            replayed=True,
        )


__all__ = ["ContentAuthorityScheduler", "ContentScheduledExecution"]
