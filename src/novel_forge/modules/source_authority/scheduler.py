"""Recovery-aware Source Authority worker over the shared Command Kernel."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    heartbeat_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.cancellation import (
    acknowledge_worker_cancellation,
)
from novel_forge.modules.command_kernel.deadline_runtime import (
    probe_operation_execution,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)
from novel_forge.modules.source_authority.application import SourceAuthorityApplication
from novel_forge.modules.source_authority.definitions import SOURCE_AUTHORITY_OPERATIONS
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class SourceAuthorityScheduler:
    """Claims Source Operations from PostgreSQL; no process-local task state exists."""

    def __init__(
        self,
        application: SourceAuthorityApplication,
        *,
        worker_id: str = "source-authority-worker",
        lease_seconds: int = 30,
    ) -> None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_id and positive lease_seconds are required")
        self.application = application
        self.database_url = application.database_url
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.operation_names = SOURCE_AUTHORITY_OPERATIONS
        self.output_keys = frozenset(
            {"source.document", "source.transform.manifest"}
        )

    def pending_operations(self, *, limit: int = 50) -> tuple[tuple[str, str], ...]:
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
                    ORDER BY attempt.attempt_number DESC,
                             lease.fencing_token DESC
                    LIMIT 1
                ) AS active_lease ON TRUE
                WHERE operation.definition_name = ANY(%s)
                  AND operation.status IN ('READY', 'FAILED_RETRYABLE', 'EXECUTING')
                  AND (
                      active_lease.expires_at IS NULL
                      OR active_lease.expires_at <= NOW()
                  )
                ORDER BY operation.created_at, operation.operation_id
                LIMIT %s
                """,
                [list(self.operation_names), limit],
            )
            rows = uow.cursor.fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def run_or_recover(
        self, *, operation_id: str, project_id: str
    ) -> dict[str, Any]:
        state = self._state(operation_id, project_id)
        operation_status = str(state["operation_status"])
        if operation_status == "SUCCEEDED":
            return {
                **self.application.result(operation_id, project_id, replayed=True),
                "recovery_mode": "operation_replay",
            }
        if operation_status in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
            raise KernelError(
                "SOURCE_RECOVERY_TERMINAL",
                f"Source Operation is terminal: {operation_status}",
            )

        recovery_mode = "fresh_attempt"
        if operation_status in {"READY", "FAILED_RETRYABLE"}:
            retrying = operation_status == "FAILED_RETRYABLE"
            attempt = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=int(state["max_attempts"]),
                trace_id=str(state["trace_id"]),
                correlation_id=str(state["correlation_id"]),
            )
            if attempt["dead_letter"] or not attempt["attempt_id"]:
                raise KernelError(
                    "SOURCE_OPERATION_DEAD_LETTER", "retry policy exhausted"
                )
            attempt_id = str(attempt["attempt_id"])
            attempt_number = int(attempt["attempt_number"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=str(state["trace_id"]),
                correlation_id=str(state["correlation_id"]),
            )
            attempt_status = "QUEUED"
            if retrying:
                recovery_mode = "retry_attempt"
        elif operation_status == "EXECUTING" and state.get("attempt_id"):
            attempt_id = str(state["attempt_id"])
            attempt_number = int(state["attempt_number"])
            attempt_status = str(state["attempt_status"])
            recovery_mode = (
                "output_replay_takeover"
                if self._has_output(operation_id, project_id)
                else "lease_takeover"
            )
        else:
            raise KernelError(
                "SOURCE_RECOVERY_STATE_INVALID",
                "Source Operation has no recoverable Attempt",
            )

        try:
            lease = acquire_attempt_lease(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                trace_id=str(state["trace_id"]),
                correlation_id=str(state["correlation_id"]),
            )
        except KernelError as exc:
            if exc.code == "LEASE_NOT_AVAILABLE":
                raise KernelError(
                    "SOURCE_RECOVERY_LEASE_ACTIVE",
                    "another worker still owns the Source Attempt lease",
                ) from exc
            raise
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
            causation_id=operation_id,
        )
        if attempt_status in {"QUEUED", "LEASED"}:
            start_attempt(self.database_url, worker)
        elif attempt_status not in {"RUNNING", "CHECKPOINTED"}:
            raise KernelError(
                "SOURCE_RECOVERY_ATTEMPT_INVALID",
                f"Source Attempt cannot resume from {attempt_status}",
            )
        try:
            with LeaseHeartbeatGuard(
                lambda: heartbeat_attempt(
                    self.database_url, worker, self.lease_seconds
                ),
                lease_seconds=self.lease_seconds,
                label=f"source-attempt:{attempt_id}",
                probe=lambda: probe_operation_execution(
                    self.database_url,
                    operation_id=operation_id,
                    project_id=project_id,
                ),
            ):
                result = self.application.execute_fenced(worker)
            with AuthorityUnitOfWork(self.database_url) as uow:
                operation = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_version=int(operation["version"]),
                    expected_operation_status=str(operation["status"]),
                ),
                outcome="success",
                result=result,
            )
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            classification = WorkerFailureClassifier.classify(exc)
            if classification is WorkerFailureClass.CANCELLATION:
                with AuthorityUnitOfWork(self.database_url) as uow:
                    current = uow.repositories.attempt_runtime.operation_state(
                        operation_id, project_id
                    )
                acknowledge_worker_cancellation(
                    self.database_url,
                    worker,
                    expected_operation_version=int(current["version"]),
                )
            elif classification not in {
                WorkerFailureClass.LEASE_CONFLICT,
                WorkerFailureClass.FENCING_CONFLICT,
            }:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=classification is WorkerFailureClass.RETRYABLE,
                    error_code=(
                        exc.code if isinstance(exc, KernelError) else "PROGRAMMING_BUG"
                    ),
                    error_message=str(exc),
                    failure_class=classification.value,
                )
            raise
        return {
            **self.application.result(operation_id, project_id, replayed=False),
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "recovery_mode": recovery_mode,
        }

    def _state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, operation.trace_id,
                       operation.correlation_id,
                       COALESCE(
                           (operation.definition_snapshot->'retry_policy'->>'max_attempts')::int,
                           1
                       ),
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
                WHERE operation.operation_id = %s
                  AND operation.project_id = %s
                  AND operation.definition_name = ANY(%s)
                """,
                [operation_id, project_id, list(self.operation_names)],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND", "Source Operation does not exist"
            )
        return dict(
            zip(
                (
                    "operation_status",
                    "trace_id",
                    "correlation_id",
                    "max_attempts",
                    "attempt_id",
                    "attempt_number",
                    "attempt_status",
                ),
                row,
                strict=True,
            )
        )

    def _has_output(self, operation_id: str, project_id: str) -> bool:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT 1
                FROM authority_operation_output_asset AS output
                JOIN authority_operation AS operation
                  ON operation.operation_id = output.operation_id
                WHERE output.operation_id = %s
                  AND operation.project_id = %s
                  AND output.output_key = ANY(%s)
                """,
                [operation_id, project_id, list(self.output_keys)],
            )
            return uow.cursor.fetchone() is not None


__all__ = ["SourceAuthorityScheduler"]
