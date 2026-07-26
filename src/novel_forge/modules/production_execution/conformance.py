"""Reusable lifecycle conformance and deterministic failure-injection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import ExecutionBackend, ExecutionRequest


class BackendConformanceScenario(StrEnum):
    DUPLICATE_SUBMIT = "duplicate_submit"
    SAME_ID_DIFFERENT_CONTRACT = "same_id_different_contract"
    STABLE_IDEMPOTENCY = "stable_idempotency"
    STALE_FENCE = "stale_fence"
    QUERY = "query"
    CANCEL = "cancel"
    CALLBACK = "callback"
    CALLBACK_DUPLICATE = "callback_duplicate"
    CALLBACK_CONFLICT = "callback_conflict"
    LATE_CALLBACK = "late_callback"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    MALFORMED_OUTPUT = "malformed_output"
    USAGE_RECEIPT = "usage_receipt"
    COST_RECEIPT = "cost_receipt"
    RESTART_RECOVERY = "restart_recovery"


class FailureInjectionPoint(StrEnum):
    BEFORE_SEND_FAILURE = "before_send_failure"
    AFTER_SEND_BEFORE_RECEIPT_FAILURE = "after_send_before_receipt_failure"
    PROVIDER_UNKNOWN = "provider_unknown"
    PROVIDER_TIMEOUT = "provider_timeout"
    CALLBACK_DUPLICATE = "callback_duplicate"
    CALLBACK_CONFLICT = "callback_conflict"
    CALLBACK_AFTER_CANCEL = "callback_after_cancel"
    DATABASE_DISCONNECT = "database_disconnect"
    OBJECT_STORE_FAILURE = "object_store_failure"
    WORKER_CRASH = "worker_crash"
    PROCESS_EXIT_NONZERO = "process_exit_nonzero"
    PROCESS_TIMEOUT = "process_timeout"
    PROCESS_RESULT_CORRUPT = "process_result_corrupt"
    STALE_FENCE = "stale_fence"
    BUDGET_EXCEEDED = "budget_exceeded"
    SCHEMA_MISMATCH = "schema_mismatch"
    SEMANTIC_VALIDATION_FAILURE = "semantic_validation_failure"
    COMMIT_FAILURE = "commit_failure"


class InjectedExecutionFailure(RuntimeError):
    def __init__(
        self,
        point: FailureInjectionPoint,
        *,
        request_sent: bool = False,
    ) -> None:
        super().__init__(f"injected production execution failure: {point.value}")
        self.point = point
        self.request_sent = request_sent


class FailureInjector:
    """One-shot deterministic injector for fixture and integration tests."""

    def __init__(
        self, armed: tuple[FailureInjectionPoint | str, ...] = ()
    ) -> None:
        self._armed = {
            item if isinstance(item, FailureInjectionPoint) else FailureInjectionPoint(item)
            for item in armed
        }

    def trip(
        self,
        point: FailureInjectionPoint | str,
        *,
        request_sent: bool = False,
    ) -> None:
        normalized = (
            point
            if isinstance(point, FailureInjectionPoint)
            else FailureInjectionPoint(point)
        )
        if normalized in self._armed:
            self._armed.remove(normalized)
            raise InjectedExecutionFailure(
                normalized, request_sent=request_sent
            )


@dataclass(frozen=True, slots=True)
class BackendConformanceReport:
    backend_id: str
    duplicate_submit_stable: bool
    contract_conflict_rejected: bool
    attempt_binding_preserved: bool
    query_completed: bool
    usage_receipt_recorded: bool
    cost_receipt_recorded: bool
    cancellation_contract_returned: bool


class BackendConformanceSuite:
    """Protocol-level checks shared by every qualified backend.

    Callback, timeout, malformed output, UNKNOWN, and restart scenarios remain
    backend-specific because transports expose different lifecycle controls.
    The complete required scenario catalog is exposed for coverage checks.
    """

    scenarios = tuple(BackendConformanceScenario)

    @staticmethod
    def exercise_common(
        backend: ExecutionBackend,
        request: ExecutionRequest,
        conflicting_request: ExecutionRequest,
    ) -> BackendConformanceReport:
        first = backend.submit(request)
        duplicate = backend.submit(request)
        duplicate_stable = first.contract_hash == duplicate.contract_hash
        conflict_rejected = False
        try:
            backend.submit(conflicting_request)
        except ValueError as exc:
            conflict_rejected = "different request" in str(exc)
        result = backend.reconcile(first)
        binding_preserved = (
            result.operation_id,
            result.attempt_id,
            result.fencing_token,
        ) == (
            request.operation_id,
            request.attempt_id,
            request.fencing_token,
        )
        cancellation = backend.cancel(first, "backend conformance cancellation")
        cancellation_bound = (
            cancellation.execution_id == request.execution_id
            and cancellation.attempt_id == request.attempt_id
            and cancellation.fencing_token == request.fencing_token
        )
        return BackendConformanceReport(
            backend_id=backend.backend_id,
            duplicate_submit_stable=duplicate_stable,
            contract_conflict_rejected=conflict_rejected,
            attempt_binding_preserved=binding_preserved,
            query_completed=result.outcome.value == "SUCCEEDED",
            usage_receipt_recorded=result.usage_receipt_ref is not None,
            cost_receipt_recorded=result.cost_receipt_ref is not None,
            cancellation_contract_returned=cancellation_bound,
        )


__all__ = [
    "BackendConformanceReport",
    "BackendConformanceScenario",
    "BackendConformanceSuite",
    "FailureInjectionPoint",
    "FailureInjector",
    "InjectedExecutionFailure",
]
