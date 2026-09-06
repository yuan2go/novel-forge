from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Iterable, TypeVar

from novel_forge.modules.command_kernel.errors import KernelError


class WorkerFailureClass(StrEnum):
    RETRYABLE = "retryable"
    FINAL_FAILURE = "final_failure"
    UNKNOWN_EXTERNAL_STATE = "unknown_external_state"
    LEASE_CONFLICT = "lease_conflict"
    FENCING_CONFLICT = "fencing_conflict"
    CANCELLATION = "cancellation"
    DEAD_LETTER = "dead_letter"
    MANUAL_INTERVENTION = "manual_intervention"
    PROGRAMMING_BUG = "programming_bug"


_LEASE_CODES = frozenset(
    {"LEASE_NOT_AVAILABLE", "ATTEMPT_LEASE_ACTIVE", "CONTENT_RECOVERY_LEASE_ACTIVE"}
)
_FENCING_CODES = frozenset(
    {"ATTEMPT_FENCING_TOKEN_STALE", "OPERATION_COMPARE_AND_SET_CONFLICT"}
)
_CANCELLATION_CODES = frozenset(
    {"OPERATION_CANCELLATION_REQUESTED", "OPERATION_CANCELLED", "ATTEMPT_CANCELLED"}
)
_DEAD_LETTER_CODES = frozenset(
    {
        "ATTEMPT_RETRY_EXHAUSTED",
        "CHAPTER_ATTEMPT_EXHAUSTED",
        "CONTENT_RECOVERY_RETRY_EXHAUSTED",
        "CONTENT_RECOVERY_TERMINAL",
    }
)
_MANUAL_INTERVENTION_CODES = frozenset({"CHAPTER_QUALITY_GATE_BLOCKED"})
_FINAL_FAILURE_CODES = frozenset(
    {
        "CHAPTER_QUALITY_GATE_FAILED",
        "CHAPTER_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
        # WHY: Once a semantic Provider attempt has reached the final send gate,
        # loss/abort of its exact outer Opening fence is permanent for that
        # Operation generation.  Retrying the same generation can never
        # acquire a different owner and would only create a retry poison loop.
        "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
        "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED",
        # WHY: These denials are evaluated at the final Provider authorization
        # boundary.  They are immutable identity/lifecycle failures for the
        # frozen Effect generation, so retrying the same Operation cannot
        # make it executable and would split a terminal ExternalEffect from a
        # retryable parent Operation.
        "BUDGET_SCOPE_CONFLICT",
        "BUDGET_SCOPE_NOT_FOUND",
        "BOOK_OPENING_BUDGET_EFFECT_BINDING_REQUIRED",
        "BOOK_OPENING_PROVIDER_EXECUTION_NOT_AUTHORIZED",
        "BOOK_OPENING_PROVIDER_EXECUTION_NOT_LIVE",
    }
)


class WorkerProgrammingError(RuntimeError):
    """INVARIANT: Raised after the rest of the current batch has been isolated and attempted."""


class WorkerHealthStatus(StrEnum):
    STARTING = "starting"
    HEALTHY = "healthy"
    IDLE = "idle"
    DEGRADED = "degraded"
    DRAINING = "draining"
    FATAL = "fatal"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class WorkerHealthSnapshot:
    worker_kind: str
    worker_id: str
    status: WorkerHealthStatus
    last_poll_at: str
    last_successful_poll_at: str
    last_fatal_error: str
    exit_code: int | None
    restart_policy_expectation: str
    completed_batches: int
    failed_tasks: int
    active_operation_id: str
    completed_operations: int
    failed_operations: int
    last_heartbeat_at: str


class WorkerSupervisor:

    FATAL_EXIT_CODE = 70

    def __init__(
        self,
        *,
        worker_kind: str,
        worker_id: str,
        observer: Callable[[WorkerHealthSnapshot], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not worker_kind or not worker_id:
            raise ValueError("worker kind and configured identity are required")
        self.worker_kind = worker_kind
        self.worker_id = worker_id
        self._observer = observer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._status = WorkerHealthStatus.STARTING
        self._last_poll_at = ""
        self._last_successful_poll_at = ""
        self._last_fatal_error = ""
        self._exit_code: int | None = None
        self._completed_batches = 0
        self._failed_tasks = 0
        self._active_operation_id = ""
        self._completed_operations = 0
        self._failed_operations = 0
        self._last_heartbeat_at = ""
        self._publish()

    def polled(self, *, idle: bool) -> WorkerHealthSnapshot:
        now = self._timestamp()
        self._last_poll_at = now
        self._last_successful_poll_at = now
        self._last_heartbeat_at = now
        self._status = WorkerHealthStatus.IDLE if idle else WorkerHealthStatus.HEALTHY
        return self._publish()

    def operation_started(self, operation_id: str) -> WorkerHealthSnapshot:
        if not operation_id:
            raise ValueError("active operation identity is required")
        self._active_operation_id = operation_id
        self._last_heartbeat_at = self._timestamp()
        self._status = WorkerHealthStatus.HEALTHY
        return self._publish()

    def operation_finished(
        self, operation_id: str, *, succeeded: bool
    ) -> WorkerHealthSnapshot:
        if operation_id != self._active_operation_id:
            raise ValueError("finished operation does not match active operation")
        if succeeded:
            self._completed_operations += 1
        else:
            self._failed_operations += 1
        self._active_operation_id = ""
        self._last_heartbeat_at = self._timestamp()
        return self._publish()

    def batch_completed(
        self, failures: Iterable[WorkerTaskFailure]
    ) -> WorkerHealthSnapshot:
        failures = tuple(failures)
        self._completed_batches += 1
        self._failed_tasks += len(failures)
        self._last_successful_poll_at = self._timestamp()
        self._last_heartbeat_at = self._last_successful_poll_at
        self._status = (
            WorkerHealthStatus.DEGRADED if failures else WorkerHealthStatus.HEALTHY
        )
        return self._publish()

    def fatal(self, error: BaseException) -> WorkerHealthSnapshot:
        self._status = WorkerHealthStatus.FATAL
        self._last_fatal_error = f"{type(error).__name__}: {error}"
        self._exit_code = self.FATAL_EXIT_CODE
        return self._publish()

    def draining(self) -> WorkerHealthSnapshot:
        if self._status is not WorkerHealthStatus.FATAL:
            self._status = WorkerHealthStatus.DRAINING
        return self._publish()

    def stopped(self) -> WorkerHealthSnapshot:
        if self._status is not WorkerHealthStatus.FATAL:
            self._status = WorkerHealthStatus.STOPPED
            self._exit_code = 0
        return self._publish()

    def snapshot(self) -> WorkerHealthSnapshot:
        return WorkerHealthSnapshot(
            worker_kind=self.worker_kind,
            worker_id=self.worker_id,
            status=self._status,
            last_poll_at=self._last_poll_at,
            last_successful_poll_at=self._last_successful_poll_at,
            last_fatal_error=self._last_fatal_error,
            exit_code=self._exit_code,
            restart_policy_expectation="restart_on_nonzero_exit_with_backoff",
            completed_batches=self._completed_batches,
            failed_tasks=self._failed_tasks,
            active_operation_id=self._active_operation_id,
            completed_operations=self._completed_operations,
            failed_operations=self._failed_operations,
            last_heartbeat_at=self._last_heartbeat_at,
        )

    def _timestamp(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat()

    def _publish(self) -> WorkerHealthSnapshot:
        snapshot = self.snapshot()
        if self._observer is not None:
            self._observer(snapshot)
        return snapshot


class WorkerFailureClassifier:
    @staticmethod
    def classify(error: BaseException) -> WorkerFailureClass:
        if not isinstance(error, KernelError):
            return WorkerFailureClass.PROGRAMMING_BUG
        code = error.code.upper()
        if code in _LEASE_CODES:
            return WorkerFailureClass.LEASE_CONFLICT
        if code in _FENCING_CODES or "FENC" in code:
            return WorkerFailureClass.FENCING_CONFLICT
        if code in _CANCELLATION_CODES or "CANCEL" in code:
            return WorkerFailureClass.CANCELLATION
        if code in _DEAD_LETTER_CODES or "DEAD_LETTER" in code or "EXHAUST" in code:
            return WorkerFailureClass.DEAD_LETTER
        if "UNKNOWN" in code or "RECONCILIATION" in code:
            return WorkerFailureClass.UNKNOWN_EXTERNAL_STATE
        if (
            code in _MANUAL_INTERVENTION_CODES
            or "MANUAL" in code
            or "WAITING_GATE" in code
            or "APPROVAL" in code
        ):
            return WorkerFailureClass.MANUAL_INTERVENTION
        if code == "MODEL_EFFECT_TIMEOUT" or code.startswith("MODEL_EFFECT_RETRYABLE_"):
            return WorkerFailureClass.RETRYABLE
        if code.startswith("MODEL_EFFECT_FINAL_"):
            return WorkerFailureClass.FINAL_FAILURE
        if code in _FINAL_FAILURE_CODES:
            return WorkerFailureClass.FINAL_FAILURE
        if any(
            marker in code
            for marker in (
                "INVALID",
                "MISSING",
                "NOT_FOUND",
                "CROSS_PROJECT",
                "NOT_ELIGIBLE",
                "PERMISSION",
                "FORBIDDEN",
                "FAILED_FINAL",
            )
        ):
            return WorkerFailureClass.FINAL_FAILURE
        return WorkerFailureClass.RETRYABLE


@dataclass(frozen=True, slots=True)
class WorkerTaskFailure:
    task_id: str
    project_id: str
    classification: WorkerFailureClass
    error_type: str
    error_code: str
    message: str


T = TypeVar("T")


class AuthorityWorkerExecutionBoundary:

    def __init__(
        self, *, worker_kind: str, logger: logging.Logger | None = None
    ) -> None:
        self.worker_kind = worker_kind
        self.logger = logger or logging.getLogger(
            f"novel_forge.authority.{worker_kind}"
        )

    def execute_batch(
        self,
        tasks: Iterable[T],
        *,
        identity: Callable[[T], tuple[str, str]],
        execute: Callable[[T], object],
        on_task_start: Callable[[str], object] | None = None,
        on_task_finish: Callable[[str, bool], object] | None = None,
    ) -> tuple[WorkerTaskFailure, ...]:
        failures: list[WorkerTaskFailure] = []
        programming_failures: list[WorkerTaskFailure] = []
        for task in tasks:
            project_id, task_id = identity(task)
            if on_task_start is not None:
                on_task_start(task_id)
            try:
                execute(task)
            except (
                Exception
            ) as exc:  # INVARIANT: signals and explicit process exits must propagate
                classification = WorkerFailureClassifier.classify(exc)
                failure = WorkerTaskFailure(
                    task_id=task_id,
                    project_id=project_id,
                    classification=classification,
                    error_type=type(exc).__name__,
                    error_code=exc.code
                    if isinstance(exc, KernelError)
                    else "PROGRAMMING_BUG",
                    message=str(exc),
                )
                failures.append(failure)
                if classification is WorkerFailureClass.PROGRAMMING_BUG:
                    programming_failures.append(failure)
                self.logger.error(
                    json.dumps(
                        {
                            "event": "authority.worker.task_failed",
                            "worker_kind": self.worker_kind,
                            "project_id": project_id,
                            "task_id": task_id,
                            "classification": classification.value,
                            "error_type": failure.error_type,
                            "error_code": failure.error_code,
                            "message": failure.message,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                if on_task_finish is not None:
                    on_task_finish(task_id, False)
            else:
                if on_task_finish is not None:
                    on_task_finish(task_id, True)
        if programming_failures:
            raise WorkerProgrammingError(
                f"{len(programming_failures)} programming error(s) were isolated in "
                f"the {self.worker_kind} batch"
            )
        return tuple(failures)


__all__ = [
    "AuthorityWorkerExecutionBoundary",
    "WorkerFailureClass",
    "WorkerFailureClassifier",
    "WorkerHealthSnapshot",
    "WorkerHealthStatus",
    "WorkerProgrammingError",
    "WorkerSupervisor",
    "WorkerTaskFailure",
]
