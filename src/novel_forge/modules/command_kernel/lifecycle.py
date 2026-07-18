from __future__ import annotations

from enum import StrEnum

from novel_forge.modules.command_kernel.errors import KernelError


class OperationStatus(StrEnum):
    ADMITTED = "ADMITTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    READY = "READY"
    EXECUTING = "EXECUTING"
    WAITING_CHILDREN = "WAITING_CHILDREN"
    WAITING_EXTERNAL_RESULT = "WAITING_EXTERNAL_RESULT"
    WAITING_GATE = "WAITING_GATE"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    SUCCEEDED = "SUCCEEDED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"


class AttemptStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    TIMED_OUT = "TIMED_OUT"
    LEASE_LOST = "LEASE_LOST"
    SUPERSEDED = "SUPERSEDED"
    LATE_RESULT_REJECTED = "LATE_RESULT_REJECTED"
    CANCELLED = "CANCELLED"


OPERATION_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.ADMITTED: frozenset(
        {
            OperationStatus.WAITING_APPROVAL,
            OperationStatus.READY,
            OperationStatus.CANCELLATION_REQUESTED,
            OperationStatus.FAILED_FINAL,
        }
    ),
    OperationStatus.WAITING_APPROVAL: frozenset(
        {
            OperationStatus.READY,
            OperationStatus.EXECUTING,
            OperationStatus.WAITING_CHILDREN,
            OperationStatus.WAITING_EXTERNAL_RESULT,
            OperationStatus.WAITING_GATE,
            OperationStatus.SUCCEEDED,
            OperationStatus.CANCELLED,
            OperationStatus.FAILED_FINAL,
        }
    ),
    OperationStatus.READY: frozenset(
        {
            OperationStatus.EXECUTING,
            OperationStatus.WAITING_CHILDREN,
            OperationStatus.WAITING_APPROVAL,
            OperationStatus.CANCELLATION_REQUESTED,
        }
    ),
    OperationStatus.EXECUTING: frozenset(
        {
            OperationStatus.WAITING_EXTERNAL_RESULT,
            OperationStatus.WAITING_GATE,
            OperationStatus.WAITING_APPROVAL,
            OperationStatus.WAITING_CHILDREN,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED_RETRYABLE,
            OperationStatus.FAILED_FINAL,
            OperationStatus.CANCELLATION_REQUESTED,
        }
    ),
    OperationStatus.WAITING_CHILDREN: frozenset(
        {
            OperationStatus.EXECUTING,
            OperationStatus.WAITING_GATE,
            OperationStatus.WAITING_APPROVAL,
            OperationStatus.WAITING_EXTERNAL_RESULT,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED_FINAL,
            OperationStatus.CANCELLATION_REQUESTED,
            OperationStatus.COMPENSATING,
        }
    ),
    OperationStatus.WAITING_EXTERNAL_RESULT: frozenset(
        {
            OperationStatus.EXECUTING,
            OperationStatus.WAITING_CHILDREN,
            OperationStatus.WAITING_GATE,
            OperationStatus.WAITING_APPROVAL,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED_RETRYABLE,
            OperationStatus.RECONCILIATION_REQUIRED,
            OperationStatus.CANCELLATION_REQUESTED,
        }
    ),
    OperationStatus.WAITING_GATE: frozenset(
        {
            OperationStatus.EXECUTING,
            OperationStatus.WAITING_CHILDREN,
            OperationStatus.WAITING_EXTERNAL_RESULT,
            OperationStatus.WAITING_APPROVAL,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED_FINAL,
            OperationStatus.CANCELLATION_REQUESTED,
        }
    ),
    OperationStatus.FAILED_RETRYABLE: frozenset(
        {
            OperationStatus.READY,
            OperationStatus.FAILED_FINAL,
            OperationStatus.DEAD_LETTER,
            OperationStatus.CANCELLATION_REQUESTED,
        }
    ),
    OperationStatus.CANCELLATION_REQUESTED: frozenset(
        {
            OperationStatus.CANCELLED,
            OperationStatus.RECONCILIATION_REQUIRED,
            OperationStatus.COMPENSATION_REQUIRED,
        }
    ),
    OperationStatus.RECONCILIATION_REQUIRED: frozenset(
        {
            OperationStatus.EXECUTING,
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED_FINAL,
            OperationStatus.COMPENSATION_REQUIRED,
            OperationStatus.CANCELLED,
        }
    ),
    OperationStatus.COMPENSATION_REQUIRED: frozenset(
        {
            OperationStatus.COMPENSATING,
            OperationStatus.FAILED_FINAL,
            OperationStatus.RECONCILIATION_REQUIRED,
        }
    ),
    OperationStatus.COMPENSATING: frozenset(
        {
            OperationStatus.COMPENSATED,
            OperationStatus.COMPENSATION_FAILED,
            OperationStatus.RECONCILIATION_REQUIRED,
        }
    ),
}


ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.CREATED: frozenset(
        {AttemptStatus.QUEUED, AttemptStatus.CANCELLED, AttemptStatus.SUPERSEDED}
    ),
    AttemptStatus.QUEUED: frozenset(
        {
            AttemptStatus.LEASED,
            AttemptStatus.CANCELLED,
            AttemptStatus.SUPERSEDED,
            AttemptStatus.TIMED_OUT,
        }
    ),
    AttemptStatus.LEASED: frozenset(
        {
            AttemptStatus.RUNNING,
            AttemptStatus.LEASE_LOST,
            AttemptStatus.CANCELLED,
            AttemptStatus.TIMED_OUT,
        }
    ),
    AttemptStatus.RUNNING: frozenset(
        {
            AttemptStatus.CHECKPOINTED,
            AttemptStatus.RESULT_SUBMITTED,
            AttemptStatus.FAILED_RETRYABLE,
            AttemptStatus.FAILED_FINAL,
            AttemptStatus.TIMED_OUT,
            AttemptStatus.LEASE_LOST,
            AttemptStatus.CANCELLED,
        }
    ),
    AttemptStatus.CHECKPOINTED: frozenset(
        {
            AttemptStatus.RUNNING,
            AttemptStatus.RESULT_SUBMITTED,
            AttemptStatus.LEASE_LOST,
            AttemptStatus.TIMED_OUT,
            AttemptStatus.CANCELLED,
        }
    ),
    AttemptStatus.RESULT_SUBMITTED: frozenset(
        {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED_RETRYABLE,
            AttemptStatus.FAILED_FINAL,
        }
    ),
}


def require_operation_transition(current: str, target: str) -> None:
    try:
        current_status = OperationStatus(current)
        target_status = OperationStatus(target)
    except ValueError as exc:
        raise KernelError(
            "OPERATION_TRANSITION_INVALID",
            f"unknown operation status in transition: {current} -> {target}",
        ) from exc
    if target_status not in OPERATION_TRANSITIONS.get(current_status, frozenset()):
        raise KernelError(
            "OPERATION_TRANSITION_INVALID",
            f"invalid operation transition: {current} -> {target}",
        )


def require_attempt_transition(current: str, target: str) -> None:
    try:
        current_status = AttemptStatus(current)
        target_status = AttemptStatus(target)
    except ValueError as exc:
        raise KernelError(
            "ATTEMPT_TRANSITION_INVALID",
            f"unknown attempt status in transition: {current} -> {target}",
        ) from exc
    if target_status not in ATTEMPT_TRANSITIONS.get(current_status, frozenset()):
        raise KernelError(
            "ATTEMPT_TRANSITION_INVALID",
            f"invalid attempt transition: {current} -> {target}",
        )


def require_transition(current: str, target: str) -> None:
    require_operation_transition(current, target)
