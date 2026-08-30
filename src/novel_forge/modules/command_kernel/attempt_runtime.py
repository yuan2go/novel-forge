from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lifecycle import require_attempt_transition
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class WorkerLeaseCommand:
    attempt_id: str
    project_id: str
    worker_id: str
    fencing_token: int
    trace_id: str
    correlation_id: str
    causation_id: str = ""


@dataclass(frozen=True)
class WorkerResultCommand(WorkerLeaseCommand):
    expected_operation_version: int = 0
    expected_operation_status: str = "EXECUTING"


def create_attempt(
    database_url: str,
    *,
    operation_id: str,
    project_id: str,
    max_attempts: int,
    trace_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    if max_attempts <= 0:
        raise KernelError("ATTEMPT_POLICY_INVALID", "max_attempts must be positive")
    with AuthorityUnitOfWork(database_url) as uow:
        operation = uow.repositories.attempt_runtime.operation_state(
            operation_id,
            project_id,
        )
        if operation["status"] not in {"READY", "FAILED_RETRYABLE"}:
            raise KernelError(
                "OPERATION_STATUS_CONFLICT",
                "operation is not ready for a new attempt",
            )
        attempt_number = uow.repositories.attempt_runtime.next_attempt_number(operation_id)
        if attempt_number > max_attempts:
            _cas_operation(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                expected_status=operation["status"],
                expected_version=operation["version"],
                target_status="DEAD_LETTER",
                actor_id="kernel.scheduler",
                reason="attempt retry policy exhausted",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
            uow.commit()
            return {"attempt_id": None, "dead_letter": True}
        if operation["status"] == "FAILED_RETRYABLE":
            _cas_operation(
                uow,
                operation_id=operation_id,
                project_id=project_id,
                expected_status="FAILED_RETRYABLE",
                expected_version=operation["version"],
                target_status="READY",
                actor_id="kernel.scheduler",
                reason="retry attempt admitted",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        attempt_id = str(uuid4())
        uow.repositories.attempt_runtime.create(
            {
                "attempt_id": attempt_id,
                "operation_id": operation_id,
                "attempt_number": attempt_number,
                "max_attempts": max_attempts,
            }
        )
        _record_attempt_transition(
            uow,
            attempt_id=attempt_id,
            operation_id=operation_id,
            project_id=project_id,
            expected_status="NONE",
            target_status="CREATED",
            worker_id="",
            fencing_token=None,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        uow.commit()
    return {
        "attempt_id": attempt_id,
        "attempt_number": attempt_number,
        "dead_letter": False,
    }


def queue_attempt(
    database_url: str,
    *,
    attempt_id: str,
    project_id: str,
    trace_id: str,
    correlation_id: str,
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(attempt_id, project_id)
        _transition_attempt(
            uow,
            attempt,
            "QUEUED",
            worker_id="",
            fencing_token=None,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        if attempt["operation_status"] == "READY":
            _cas_operation(
                uow,
                operation_id=attempt["operation_id"],
                project_id=project_id,
                expected_status="READY",
                expected_version=attempt["operation_version"],
                target_status="EXECUTING",
                actor_id="kernel.scheduler",
                reason="attempt queued for worker execution",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        uow.commit()


def acquire_attempt_lease(
    database_url: str,
    *,
    attempt_id: str,
    project_id: str,
    worker_id: str,
    lease_seconds: int,
    trace_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    try:
        with AuthorityUnitOfWork(database_url) as uow:
            attempt = uow.repositories.attempt_runtime.get_for_update(
                attempt_id,
                project_id,
            )
            lease = uow.repositories.attempt_runtime.acquire_lease(
                str(uuid4()),
                attempt_id,
                worker_id,
                lease_seconds,
            )
            if attempt["status"] == "QUEUED":
                _transition_attempt(
                    uow,
                    attempt,
                    "LEASED",
                    worker_id=worker_id,
                    fencing_token=lease["fencing_token"],
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                )
            else:
                uow.repositories.attempt_runtime.assign_worker(
                    attempt_id,
                    attempt["status"],
                    worker_id,
                )
                _record_attempt_runtime_event(
                    uow,
                    attempt=attempt,
                    event_type="authority.attempt.lease_taken_over",
                    worker_id=worker_id,
                    fencing_token=lease["fencing_token"],
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    payload={"previous_worker_id": attempt.get("worker_id", "")},
                )
            uow.repositories.attempt_runtime.assert_lease_consistency(attempt_id)
            uow.commit()
            return lease
    except psycopg.errors.CheckViolation as exc:
        raise KernelError("LEASE_NOT_AVAILABLE", "attempt already has an active lease") from exc


def start_attempt(database_url: str, command: WorkerLeaseCommand) -> None:
    _run_fenced_transition(database_url, command, "start", "RUNNING")


def checkpoint_attempt(
    database_url: str,
    command: WorkerLeaseCommand,
    checkpoint: dict[str, Any],
) -> None:
    _run_fenced_transition(
        database_url,
        command,
        "checkpoint",
        "CHECKPOINTED",
        checkpoint=checkpoint,
    )


def checkpoint_attempt_for_external_reconciliation(
    database_url: str,
    command: WorkerLeaseCommand,
    checkpoint: dict[str, Any],
) -> None:
    stale_error: KernelError | None = None
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(
            command.attempt_id, command.project_id
        )
        valid, current_token = uow.repositories.attempt_runtime.current_fence(
            command.attempt_id, command.worker_id, command.fencing_token
        )
        if not valid:
            _reject_stale(uow, command, attempt, current_token, "external_checkpoint", checkpoint)
            stale_error = KernelError(
                "ATTEMPT_FENCING_TOKEN_STALE",
                "external checkpoint carries a stale fencing token",
            )
        else:
            if attempt["status"] == "RUNNING":
                _transition_attempt(
                    uow,
                    attempt,
                    "CHECKPOINTED",
                    worker_id=command.worker_id,
                    fencing_token=command.fencing_token,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    checkpoint=checkpoint,
                )
            operation = uow.repositories.attempt_runtime.operation_state(
                attempt["operation_id"], command.project_id
            )
            if operation["status"] == "EXECUTING":
                _cas_operation(
                    uow,
                    operation_id=attempt["operation_id"],
                    project_id=command.project_id,
                    expected_status="EXECUTING",
                    expected_version=int(operation["version"]),
                    target_status="WAITING_EXTERNAL_RESULT",
                    actor_id=command.worker_id,
                    reason="external effect outcome requires reconciliation",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.causation_id,
                )
            uow.repositories.attempt_runtime.release(
                command.attempt_id,
                command.worker_id,
                command.fencing_token,
                "waiting_external_reconciliation",
            )
        uow.commit()
    if stale_error is not None:
        raise stale_error


def submit_attempt_result(
    database_url: str,
    command: WorkerResultCommand,
    *,
    outcome: str,
    result: dict[str, Any],
) -> None:
    operation_target = {
        "success": "SUCCEEDED",
        "retryable_failure": "FAILED_RETRYABLE",
        "final_failure": "FAILED_FINAL",
    }.get(outcome)
    attempt_target = {
        "success": "SUCCEEDED",
        "retryable_failure": "FAILED_RETRYABLE",
        "final_failure": "FAILED_FINAL",
    }.get(outcome)
    if operation_target is None or attempt_target is None:
        raise KernelError("RESULT_OUTCOME_INVALID", f"unknown result outcome: {outcome}")

    stale_error: KernelError | None = None
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(
            command.attempt_id,
            command.project_id,
        )
        valid, current_token = uow.repositories.attempt_runtime.current_fence(
            command.attempt_id,
            command.worker_id,
            command.fencing_token,
        )
        if not valid:
            _reject_stale(uow, command, attempt, current_token, "result", result)
            stale_error = KernelError(
                "ATTEMPT_FENCING_TOKEN_STALE",
                "worker result does not carry the current fencing token",
            )
        else:
            _transition_attempt(
                uow,
                attempt,
                "RESULT_SUBMITTED",
                worker_id=command.worker_id,
                fencing_token=command.fencing_token,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                result=result,
            )
            submitted = {**attempt, "status": "RESULT_SUBMITTED"}
            if outcome == "success":
                from novel_forge.modules.command_kernel.completion import (
                    evaluate_completion_in_uow,
                )

                operation = uow.repositories.completion_contracts.operation(
                    attempt["operation_id"],
                    command.project_id,
                    lock=True,
                )
                completion = evaluate_completion_in_uow(uow, operation)
                operation_target = completion["target_status"]
                if operation_target in {"SUCCEEDED", "FAILED_FINAL"}:
                    attempt_target = operation_target
                    _transition_attempt(
                        uow,
                        submitted,
                        attempt_target,
                        worker_id=command.worker_id,
                        fencing_token=command.fencing_token,
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                        result=result,
                    )
            else:
                _transition_attempt(
                    uow,
                    submitted,
                    attempt_target,
                    worker_id=command.worker_id,
                    fencing_token=command.fencing_token,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    result=result,
                )
            _cas_operation(
                uow,
                operation_id=attempt["operation_id"],
                project_id=command.project_id,
                expected_status=command.expected_operation_status,
                expected_version=command.expected_operation_version,
                target_status=operation_target,
                actor_id=command.worker_id,
                reason=f"worker result accepted: {outcome}",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )
            uow.repositories.attempt_runtime.release(
                command.attempt_id,
                command.worker_id,
                command.fencing_token,
                f"result_{outcome}",
            )
            uow.repositories.attempt_runtime.assert_lease_consistency(
                command.attempt_id,
            )
        uow.commit()
    if stale_error is not None:
        raise stale_error


def submit_attempt_failure(
    database_url: str,
    command: WorkerLeaseCommand,
    *,
    retryable: bool,
    error_code: str,
    error_message: str,
    failure_class: str,
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        operation = uow.repositories.attempt_runtime.operation_state(
            command.causation_id, command.project_id
        )
    submit_attempt_result(
        database_url,
        WorkerResultCommand(
            **command.__dict__,
            expected_operation_status=str(operation["status"]),
            expected_operation_version=int(operation["version"]),
        ),
        outcome="retryable_failure" if retryable else "final_failure",
        result={
            "error_code": error_code,
            "error_message": error_message,
            "failure_class": failure_class,
        },
    )


def heartbeat_attempt(
    database_url: str,
    command: WorkerLeaseCommand,
    lease_seconds: int,
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.attempt_runtime.get_for_update(command.attempt_id, command.project_id)
        uow.repositories.attempt_runtime.heartbeat(
            command.attempt_id,
            command.worker_id,
            command.fencing_token,
            lease_seconds,
        )
        uow.commit()


def expire_attempt_lease(
    database_url: str,
    command: WorkerLeaseCommand,
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(
            command.attempt_id,
            command.project_id,
        )
        valid, _ = uow.repositories.attempt_runtime.current_fence(
            command.attempt_id,
            command.worker_id,
            command.fencing_token,
        )
        if valid:
            raise KernelError("ATTEMPT_LEASE_ACTIVE", "attempt lease has not expired")
        _transition_attempt(
            uow,
            attempt,
            "LEASE_LOST",
            worker_id=command.worker_id,
            fencing_token=command.fencing_token,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        uow.commit()


def timeout_attempt(
    database_url: str,
    *,
    attempt_id: str,
    project_id: str,
    trace_id: str,
    correlation_id: str,
) -> None:
    _kernel_attempt_transition(
        database_url,
        attempt_id=attempt_id,
        project_id=project_id,
        target_status="TIMED_OUT",
        trace_id=trace_id,
        correlation_id=correlation_id,
    )


def cancel_attempt(
    database_url: str,
    *,
    attempt_id: str,
    project_id: str,
    trace_id: str,
    correlation_id: str,
) -> None:
    _kernel_attempt_transition(
        database_url,
        attempt_id=attempt_id,
        project_id=project_id,
        target_status="CANCELLED",
        trace_id=trace_id,
        correlation_id=correlation_id,
    )


def supersede_attempt(
    database_url: str,
    *,
    attempt_id: str,
    project_id: str,
    trace_id: str,
    correlation_id: str,
) -> None:
    _kernel_attempt_transition(
        database_url,
        attempt_id=attempt_id,
        project_id=project_id,
        target_status="SUPERSEDED",
        trace_id=trace_id,
        correlation_id=correlation_id,
    )


def _kernel_attempt_transition(
    database_url: str,
    *,
    attempt_id: str,
    project_id: str,
    target_status: str,
    trace_id: str,
    correlation_id: str,
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(attempt_id, project_id)
        _transition_attempt(
            uow,
            attempt,
            target_status,
            worker_id="kernel.scheduler",
            fencing_token=None,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        uow.commit()


def _run_fenced_transition(
    database_url: str,
    command: WorkerLeaseCommand,
    command_type: str,
    target_status: str,
    *,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    stale_error: KernelError | None = None
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = uow.repositories.attempt_runtime.get_for_update(
            command.attempt_id,
            command.project_id,
        )
        valid, current_token = uow.repositories.attempt_runtime.current_fence(
            command.attempt_id,
            command.worker_id,
            command.fencing_token,
        )
        if not valid:
            _reject_stale(
                uow,
                command,
                attempt,
                current_token,
                command_type,
                checkpoint or {},
            )
            stale_error = KernelError(
                "ATTEMPT_FENCING_TOKEN_STALE",
                f"worker {command_type} does not carry the current fencing token",
            )
        elif command_type == "start" and attempt["status"] == "RUNNING":
            _record_attempt_runtime_event(
                uow,
                attempt=attempt,
                event_type="authority.attempt.resumed",
                worker_id=command.worker_id,
                fencing_token=command.fencing_token,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                payload={},
            )
        else:
            _transition_attempt(
                uow,
                attempt,
                target_status,
                worker_id=command.worker_id,
                fencing_token=command.fencing_token,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                checkpoint=checkpoint,
            )
        uow.repositories.attempt_runtime.assert_lease_consistency(command.attempt_id)
        uow.commit()
    if stale_error is not None:
        raise stale_error


def _transition_attempt(
    uow: AuthorityUnitOfWork,
    attempt: dict[str, Any],
    target_status: str,
    *,
    worker_id: str,
    fencing_token: int | None,
    trace_id: str,
    correlation_id: str,
    checkpoint: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    require_attempt_transition(attempt["status"], target_status)
    uow.repositories.attempt_runtime.transition(
        attempt["attempt_id"],
        attempt["status"],
        target_status,
        worker_id=worker_id,
        checkpoint=checkpoint,
        result=result,
    )
    _record_attempt_transition(
        uow,
        attempt_id=attempt["attempt_id"],
        operation_id=attempt["operation_id"],
        project_id=attempt["project_id"],
        expected_status=attempt["status"],
        target_status=target_status,
        worker_id=worker_id,
        fencing_token=fencing_token,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )


def _reject_stale(
    uow: AuthorityUnitOfWork,
    command: WorkerLeaseCommand,
    attempt: dict[str, Any],
    current_token: int | None,
    command_type: str,
    payload: dict[str, Any],
) -> None:
    current_lease = uow.repositories.attempt_runtime.current_lease(command.attempt_id)
    uow.repositories.attempt_runtime.reject_stale(
        {
            "evidence_id": str(uuid4()),
            "attempt_id": command.attempt_id,
            "operation_id": attempt["operation_id"],
            "project_id": command.project_id,
            "command_type": command_type,
            "worker_id": command.worker_id,
            "presented_fencing_token": command.fencing_token,
            "current_fencing_token": current_token,
            "payload": payload,
            "authoritative_attempt_status": attempt["status"],
            "current_worker_id": (current_lease or {}).get("worker_id", ""),
            "current_lease_id": (current_lease or {}).get("lease_id", ""),
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
            "causation_id": command.causation_id,
        }
    )
    _record_attempt_runtime_event(
        uow,
        attempt=attempt,
        event_type="authority.attempt.command_rejected",
        worker_id=command.worker_id,
        fencing_token=command.fencing_token,
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
        payload={
            "command_type": command_type,
            "presented_fencing_token": command.fencing_token,
            "current_fencing_token": current_token,
            "authoritative_attempt_status": attempt["status"],
        },
    )
    uow.repositories.attempt_runtime.assert_lease_consistency(command.attempt_id)


def _record_attempt_runtime_event(
    uow: AuthorityUnitOfWork,
    *,
    attempt: dict[str, Any],
    event_type: str,
    worker_id: str,
    fencing_token: int,
    trace_id: str,
    correlation_id: str,
    payload: dict[str, Any],
) -> None:
    uow.repositories.runtime_evidence.record_attempt_runtime_event(
        {
            "attempt_id": attempt["attempt_id"],
            "operation_id": attempt["operation_id"],
            "project_id": attempt["project_id"],
            "event_type": event_type,
            "correlation_id": correlation_id,
            "causation_id": "",
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
            "payload": {
                **payload,
                "worker_id": worker_id,
                "fencing_token": fencing_token,
                "attempt_status": attempt["status"],
                "trace_id": trace_id,
            },
        }
    )


def _cas_operation(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
    expected_status: str,
    expected_version: int,
    target_status: str,
    actor_id: str,
    reason: str,
    trace_id: str,
    correlation_id: str,
    causation_id: str = "",
) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.lifecycle import require_operation_transition

    require_operation_transition(expected_status, target_status)
    row = {
        "operation_id": operation_id,
        "project_id": project_id,
        "expected_status": expected_status,
        "expected_version": expected_version,
        "target_status": target_status,
        "actor_id": actor_id,
        "reason": reason,
        "trace_id": trace_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
    }
    result = uow.repositories.operation_lifecycle.compare_and_set(row)
    uow.repositories.runtime_evidence.record_operation_transition(
        {
            **row,
            "version": result["version"],
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
        }
    )
    return result


def _record_attempt_transition(
    uow: AuthorityUnitOfWork,
    *,
    attempt_id: str,
    operation_id: str,
    project_id: str,
    expected_status: str,
    target_status: str,
    worker_id: str,
    fencing_token: int | None,
    trace_id: str,
    correlation_id: str,
) -> None:
    uow.repositories.runtime_evidence.record_attempt_transition(
        {
            "attempt_id": attempt_id,
            "operation_id": operation_id,
            "project_id": project_id,
            "expected_status": expected_status,
            "target_status": target_status,
            "worker_id": worker_id,
            "fencing_token": fencing_token,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "causation_id": "",
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
        }
    )
