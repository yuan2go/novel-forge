from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from novel_forge.modules.authority_handler_runtime import (
    AuthorityExecutionResult,
    AuthorityHandlerRegistry,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    checkpoint_attempt_for_external_reconciliation,
    submit_attempt_result,
    heartbeat_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.deadline_runtime import (
    probe_operation_execution,
)
from novel_forge.modules.command_kernel.cancellation import (
    acknowledge_worker_cancellation,
)
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)
from novel_forge.modules.content_authority.runtime import execute_content_handler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ContentScheduledExecution:
    output: AuthorityExecutionResult
    attempt_id: str
    attempt_number: int
    recovery_mode: str


class ContentAuthorityScheduler:

    def __init__(
        self,
        database_url: str,
        *,
        registry: AuthorityHandlerRegistry,
        worker_id: str = "content-authority-worker",
        lease_seconds: int = 30,
    ) -> None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("worker_id and positive lease_seconds are required")
        self.database_url = database_url
        self.registry = registry
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def pending_operations(
        self,
        *,
        limit: int = 50,
        project_ids: Iterable[str] = (),
        excluded_operation_ids: Iterable[str] = (),
    ) -> tuple[tuple[str, str], ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        projects = tuple(
            dict.fromkeys(str(item) for item in project_ids if str(item))
        )
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
                  AND (%s::text[]='{}'::text[] OR operation.project_id=ANY(%s))
                  AND NOT (operation.operation_id=ANY(%s))
                  AND operation.status IN ('READY', 'FAILED_RETRYABLE', 'EXECUTING')
                  AND (active_lease.expires_at IS NULL OR active_lease.expires_at <= NOW())
                ORDER BY operation.created_at, operation.operation_id
                LIMIT %s
                """,
                [
                    list(self.registry.definition_names),
                    list(projects),
                    list(projects),
                    list(excluded_operation_ids),
                    limit,
                ],
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

        if state["operation_status"] in {"WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"}:
            from novel_forge.modules.command_kernel.recovery import RecoverOperationCommand, recover_operation
            with AuthorityUnitOfWork(self.database_url) as uow:
                operation = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
            recovered = recover_operation(self.database_url, RecoverOperationCommand(operation_id=operation_id,
                project_id=project_id, actor_id=self.worker_id, expected_version=int(operation["version"]),
                idempotency_key=f"{operation_id}:content-reconcile:{operation['version']}",
                reason="Reconcile original checkpoint before resuming frozen Content input",
                trace_id=str(state["trace_id"]), correlation_id=str(state["correlation_id"])))
            if recovered["action"] != "PRE_SEND_CHECKPOINT_RECONCILED":
                raise KernelError("CONTENT_EXTERNAL_RECONCILIATION_REQUIRED", "Original external receipt must settle before Content resumes")
            state = self._state(operation_id, project_id)

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
                if self._existing_result(
                    operation_id, project_id, require_succeeded=False
                )
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
                lambda: heartbeat_attempt(
                    self.database_url, worker, self.lease_seconds
                ),
                lease_seconds=self.lease_seconds,
                label=f"attempt:{attempt_id}",
                probe=lambda: probe_operation_execution(
                    self.database_url,
                    operation_id=operation_id,
                    project_id=project_id,
                ),
            ):
                output = execute_content_handler(
                    self.database_url,
                    command=worker,
                    definition_name=state["definition_name"],
                    definition_version=state["definition_version"],
                    registry=self.registry,
                    execution_probe=lambda: probe_operation_execution(
                        self.database_url,
                        operation_id=operation_id,
                        project_id=project_id,
                    ),
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
        except Exception as exc:
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
            elif classification is WorkerFailureClass.DISPATCH_PAUSED:
                from novel_forge.modules.command_kernel.attempt_runtime import checkpoint_attempt_for_dispatch_pause
                checkpoint_attempt_for_dispatch_pause(self.database_url, worker)
            elif classification is WorkerFailureClass.UNKNOWN_EXTERNAL_STATE:
                checkpoint_attempt_for_external_reconciliation(
                    self.database_url,
                    worker,
                    {
                        "reason": "external_state_unknown",
                        "error_code": exc.code
                        if isinstance(exc, KernelError)
                        else "UNKNOWN",
                        "error_message": str(exc),
                    },
                )
            elif classification not in {
                WorkerFailureClass.LEASE_CONFLICT,
                WorkerFailureClass.FENCING_CONFLICT,
            }:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=classification is WorkerFailureClass.RETRYABLE,
                    error_code=exc.code
                    if isinstance(exc, KernelError)
                    else "PROGRAMMING_BUG",
                    error_message=str(exc),
                    failure_details=getattr(exc, "details", {}),
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
                    "operation_status",
                    "definition_name",
                    "definition_version",
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
                       binding.output_key, operation.status,
                       operation.definition_name, operation.definition_version,
                       binding.role
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                WHERE binding.operation_id = %s AND operation.project_id = %s
                """,
                [operation_id, project_id],
            )
            rows = uow.cursor.fetchall()
        matching = []
        for row in rows:
            registration = self.registry.registration(str(row[5]), str(row[6]))
            if row[3] == registration.output_key and row[7] == registration.role:
                matching.append(row)
        if len(matching) > 1:
            raise KernelError(
                "CONTENT_RECOVERY_OUTPUT_AMBIGUOUS",
                "Content Operation has multiple outputs matching its handler contract",
            )
        row = matching[0] if matching else None
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
