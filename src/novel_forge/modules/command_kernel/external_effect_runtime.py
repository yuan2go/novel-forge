from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.dispatch_control import (
    MODEL_DISPATCH_EFFECT_TYPES,
    assert_dispatch_enabled,
    require_dispatch_enabled,
)
from novel_forge.modules.command_kernel.deadline_runtime import (
    probe_external_effect_execution,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    _cas_operation,
    _transition_attempt,
)
from novel_forge.modules.command_kernel.budget_runtime import (
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
    ExternalEffectAdapterError,
    MinioObjectStoreExternalEffectAdapter,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
    ProviderControlLevel,
    capability_profile_from_dict,
)
from novel_forge.modules.production_execution.security import (
    assert_legacy_execution_allowed,
    redact_secret_text,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


_PERMANENT_PRE_SEND_AUTHORIZATION_DENIALS = frozenset(
    {
        "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
        "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED",
    }
)
_PERMANENT_BUDGET_AUTHORIZATION_DENIALS = frozenset(
    {
        "BUDGET_SCOPE_CONFLICT",
        "BUDGET_SCOPE_NOT_FOUND",
        "BOOK_OPENING_BUDGET_EFFECT_BINDING_REQUIRED",
        "BOOK_OPENING_PROVIDER_EXECUTION_NOT_AUTHORIZED",
        "BOOK_OPENING_PROVIDER_EXECUTION_NOT_LIVE",
        "ROUTING_BOOTSTRAP_EXPIRED",
        "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
        "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
        "ROUTING_BOOTSTRAP_POLICY_INTEGRITY_FAILURE",
        "ROUTING_BOOTSTRAP_DECISION_CONFLICT",
        "ROUTING_DECISION_INTEGRITY_FAILURE",
    }
)


@dataclass(frozen=True)
class EffectCommandContext:
    operation_id: str
    project_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""


class EffectRecoveryDisposition(StrEnum):
    DISPATCH_PLANNED = "DISPATCH_PLANNED"
    QUERY_EXISTING = "QUERY_EXISTING"
    RECONCILE_UNKNOWN = "RECONCILE_UNKNOWN"
    CONSUME_SUCCEEDED = "CONSUME_SUCCEEDED"
    RETRY_POLICY = "RETRY_POLICY"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    TERMINAL_CANCELLED = "TERMINAL_CANCELLED"
    OPERATOR_RECONCILIATION = "OPERATOR_RECONCILIATION"


def classify_external_effect_recovery(status: str) -> EffectRecoveryDisposition:

    normalized = status.strip().upper()
    if normalized == "READY":
        return EffectRecoveryDisposition.DISPATCH_PLANNED
    if normalized in {"DISPATCHING", "DISPATCHED"}:
        return EffectRecoveryDisposition.QUERY_EXISTING
    if normalized in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
        return EffectRecoveryDisposition.RECONCILE_UNKNOWN
    if normalized == "SUCCEEDED":
        return EffectRecoveryDisposition.CONSUME_SUCCEEDED
    if normalized == "FAILED_RETRYABLE":
        return EffectRecoveryDisposition.RETRY_POLICY
    if normalized in {"FAILED_FINAL", "DEAD_LETTER"}:
        return EffectRecoveryDisposition.TERMINAL_FAILURE
    if normalized == "CANCELLED":
        return EffectRecoveryDisposition.TERMINAL_CANCELLED
    return EffectRecoveryDisposition.OPERATOR_RECONCILIATION


def read_succeeded_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
) -> dict[str, Any] | None:
    """INVARIANT: Read one verified synchronous success without dispatching it again.

    Operation recovery may consume a Provider result that reached the durable
    receipt boundary before the owning Attempt committed its candidate.  This
    read is deliberately narrower than reconciliation: only an already
    terminal SUCCEEDED Effect with a VERIFIED receipt is eligible.
    """
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        return _read_verified_success(uow, repository, context, effect_id)


def read_failed_operation_success(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
) -> dict[str, Any] | None:
    _validate_effect_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [context.operation_id, context.project_id],
        )
        row = uow.cursor.fetchone()
        if row is None or row[0] not in {"FAILED_FINAL", "DEAD_LETTER"}:
            raise KernelError("EFFECT_RETAINED_RESULT_OWNER_INVALID", "retained result recovery requires a failed terminal owner")
        return _read_verified_success(uow, uow.repositories.external_effects, context, effect_id)


def read_checkpointed_operation_success(database_url: str, context: EffectCommandContext, *, effect_id: str) -> dict[str, Any] | None:
    _validate_effect_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
            [context.operation_id, context.project_id])
        row = uow.cursor.fetchone()
        if row is None or row[0] not in {'WAITING_EXTERNAL_RESULT', 'RECONCILIATION_REQUIRED'}:
            raise KernelError('EFFECT_RETAINED_RESULT_OWNER_INVALID', 'Completed checkpoint recovery requires a waiting owner')
        return _read_verified_success(uow, uow.repositories.external_effects, context, effect_id)


def read_completed_operation_success(database_url: str, context: EffectCommandContext, *, effect_id: str) -> dict[str, Any] | None:
    _validate_effect_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
            [context.operation_id, context.project_id])
        row = uow.cursor.fetchone()
        if row is None or row[0] != "SUCCEEDED":
            raise KernelError("EFFECT_RETAINED_RESULT_OWNER_INVALID", "Completed receipt read requires an immutable succeeded owner")
        return _read_verified_success(uow, uow.repositories.external_effects, context, effect_id)


def _read_verified_success(uow: Any, repository: Any, context: EffectCommandContext, effect_id: str) -> dict[str, Any] | None:
    effect = repository.get_for_update(effect_id)
    _require_project(effect, context.project_id)
    if effect["operation_id"] != context.operation_id:
        raise KernelError(
            "EFFECT_OPERATION_CONFLICT",
            "ExternalEffect belongs to another Operation",
        )
    if effect["status"] != "SUCCEEDED":
        return None
    frozen_capability_profile = _validated_frozen_provider_capability_profile(
        effect
    )
    uow.cursor.execute(
        """
        SELECT dispatch.generation, dispatch.evidence,
               receipt.payload_hash, receipt.payload, receipt.status
        FROM authority_external_effect_dispatch AS dispatch
        JOIN authority_external_receipt AS receipt
          ON receipt.dispatch_id=dispatch.dispatch_id
        WHERE dispatch.external_effect_id=%s
          AND dispatch.status='SUCCEEDED'
          AND receipt.status='VERIFIED'
        ORDER BY dispatch.generation DESC
        LIMIT 1
        """,
        [effect_id],
    )
    receipt = uow.cursor.fetchone()
    if receipt is None:
        raise KernelError(
            "EFFECT_SUCCESS_RECEIPT_MISSING",
            "succeeded ExternalEffect has no verified receipt",
        )
    generation, dispatch_evidence, payload_hash, payload, receipt_status = receipt
    provider_evidence = (
        payload.get("evidence") if isinstance(payload, dict) else None
    )
    if (
        receipt_status != "VERIFIED"
        or not isinstance(provider_evidence, dict)
        or not provider_evidence
        or provider_evidence != dispatch_evidence
        or _hash(provider_evidence) != payload_hash
    ):
        raise KernelError(
            "EFFECT_SUCCESS_RECEIPT_INVALID",
            "succeeded ExternalEffect receipt evidence failed integrity checks",
        )
    uow.cursor.execute(
        """
        SELECT reservation_id,status,reserved_amount,estimated_tokens,version,accounting_basis
        FROM authority_budget_reservation
        WHERE external_effect_id=%s AND project_id=%s
          AND status IN ('SETTLED','RESERVED','HELD_UNKNOWN')
        ORDER BY created_at DESC, reservation_id DESC
        LIMIT 1
        """,
        [effect_id, context.project_id],
    )
    budget = uow.cursor.fetchone()
    if budget is None:
        raise KernelError(
            "EFFECT_SUCCESS_BUDGET_MISSING",
            "succeeded Provider Effect has no recoverable budget reservation",
        )
    return {
        "external_effect_id": effect_id,
        "generation": int(generation),
        "provider_evidence": provider_evidence,
        "provider_capability_profile": frozen_capability_profile,
        "budget_reservation_id": str(budget[0]),
        "budget_reservation_status": str(budget[1]),
        "budget_reserved_amount": None if budget[5] == "ACCOUNT_ENTITLEMENT" else str(budget[2]),
        "budget_accounting_basis": str(budget[5]),
        "budget_estimated_tokens": int(budget[3]),
        "budget_reservation_version": int(budget[4]),
        "recovered": True,
    }



def read_rejected_structured_completion(database_url, context, *, effect_id):
    _validate_effect_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT status,actor_id FROM authority_operation WHERE operation_id=%s AND project_id=%s",
            [context.operation_id, context.project_id],
        )
        owner = uow.cursor.fetchone()
        if not owner or owner != ("FAILED_FINAL", context.actor_id):
            raise KernelError(
                "EFFECT_REJECTED_RESULT_OWNER_INVALID",
                "Require this actor and its failed-final owner",
            )
        effect = uow.repositories.external_effects.get_for_update(effect_id)
        _require_project(effect, context.project_id)
        if effect["operation_id"] != context.operation_id:
            raise KernelError(
                "EFFECT_OPERATION_CONFLICT",
                "Rejected result belongs to another Operation",
            )
        if (
            effect["status"] != "FAILED_FINAL"
            or effect["effect_type"] != "model.invoke"
        ):
            raise KernelError(
                "EFFECT_REJECTED_RESULT_STATUS_INVALID",
                "Only the original failed model dispatch may be revalidated",
            )
        uow.cursor.execute(
            "SELECT d.status,d.evidence,d.payload_hash,d.generation,e.last_error FROM authority_external_effect_dispatch d JOIN authority_external_effect e USING(external_effect_id) WHERE d.external_effect_id=%s ORDER BY d.generation DESC LIMIT 1",
            [effect_id],
        )
        row = uow.cursor.fetchone()
        if (
            not row
            or row[0] != "FAILED_FINAL"
            or row[1] != row[4]
            or row[2] != effect["request_hash"] or _hash(effect["request_payload"]) != effect["request_hash"]
        ):
            raise KernelError(
                "EFFECT_REJECTED_RESULT_EVIDENCE_INVALID",
                "Failed dispatch evidence must retain its exact digest",
            )
        evidence = row[1]
        process = evidence.get("production_execution", {}).get("process_evidence", {})
        result = evidence.get("production_execution", {}).get("execution_result", {})
        if (
            process.get("failure_code") != "OUTPUT_SCHEMA_FAILURE"
            or result.get("outcome") != "FINAL_FAILURE"
            or not result.get("raw_output_ref")
            or not result.get("process_receipt_ref")
            or process.get("unauthorized_tools")
            or not result.get("usage_receipt_ref")
            or not result.get("cost_receipt_ref")
        ):
            raise KernelError(
                "EFFECT_REJECTED_RESULT_FAILURE_NOT_ALLOWED",
                "Only an intact structured-output rejection may be revalidated",
            )
        uow.cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status<>'SUCCEEDED' AND external_effect_id<>%s) OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED') OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD')",
            [
                context.operation_id,
                effect_id,
                context.operation_id,
                context.operation_id,
            ],
        )
        if uow.cursor.fetchone()[0]:
            raise KernelError(
                "EFFECT_REJECTED_RESULT_RECONCILIATION_REQUIRED",
                "All original calls and usage must be resolved without an active lease",
            )
        uow.cursor.execute(
            "SELECT reservation_id,status FROM authority_budget_reservation WHERE external_effect_id=%s AND project_id=%s",
            [effect_id, context.project_id],
        )
        budgets = uow.cursor.fetchall()
        if len(budgets) != 1 or budgets[0][1] != "SETTLED":
            raise KernelError(
                "EFFECT_REJECTED_RESULT_BUDGET_INVALID",
                "Require the exact settled original usage",
            )
        return {
            "external_effect_id": effect_id,
            "provider_evidence": evidence,
            "original_outcome": "FAILED_FINAL",
            "generation": row[3],
            "budget_reservation_id": budgets[0][0],
            "budget_reservation_status": "SETTLED",
            "request_payload": effect["request_payload"],
            "request_hash": effect["request_hash"],
        }

def read_external_effect_intent(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_type: str,
    stable_idempotency_key: str,
) -> dict[str, Any] | None:
    """INVARIANT: Read an immutable Effect intent owned by the executing Operation.

    Retry preparation uses this to reuse the first Attempt's frozen Provider
    materialization without weakening the Effect request-hash conflict check.
    """
    if not effect_type or not stable_idempotency_key:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID", "external effect lookup identity is incomplete"
        )
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        uow.cursor.execute(
            """
            SELECT external_effect_id
            FROM authority_external_effect
            WHERE operation_id=%s AND project_id=%s AND effect_type=%s
              AND stable_idempotency_key=%s
            FOR UPDATE
            """,
            [
                context.operation_id,
                context.project_id,
                effect_type,
                stable_idempotency_key,
            ],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        effect = repository.get_for_update(str(row[0]))
        _require_project(effect, context.project_id)
        if effect["operation_id"] != context.operation_id:
            raise KernelError(
                "EFFECT_OPERATION_CONFLICT",
                "ExternalEffect belongs to another Operation",
            )
        return effect


def plan_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_type: str,
    provider: str,
    capability: str,
    stable_idempotency_key: str,
    request_payload: dict[str, Any],
    max_attempts: int,
    reversible: bool,
    completion_policy: str = "synchronous_final",
    compensates_effect_id: str | None = None,
    model_id: str = "",
    request_timeout_seconds: int | None = None,
    reconciliation_mode: str = "query",
    provider_capability_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if max_attempts <= 0 or not all(
        (effect_type, provider, capability, stable_idempotency_key)
    ):
        raise KernelError(
            "COMMAND_SCHEMA_INVALID", "external effect intent is incomplete"
        )
    if completion_policy not in {
        "synchronous_final",
        "async_ack",
        "callback_receipt",
        "poll_reconciliation",
    }:
        raise KernelError(
            "EFFECT_COMPLETION_POLICY_INVALID", "unknown completion policy"
        )
    if reconciliation_mode not in {"query", "callback", "unsupported"}:
        raise KernelError(
            "EFFECT_RECONCILIATION_MODE_INVALID", "unknown reconciliation mode"
        )
    if request_timeout_seconds is not None and request_timeout_seconds <= 0:
        raise KernelError(
            "EFFECT_TIMEOUT_POLICY_INVALID", "effect timeout must be positive"
        )
    request_hash = _hash(request_payload)
    capability_profile = dict(provider_capability_profile or {})
    if capability_profile:
        profile = capability_profile_from_dict(capability_profile)
        if profile.provider != provider:
            raise KernelError(
                "EFFECT_PROVIDER_CAPABILITY_CONFLICT",
                "provider capability profile belongs to another provider",
            )
        if profile.reconciliation_mode != reconciliation_mode:
            raise KernelError(
                "EFFECT_PROVIDER_CAPABILITY_CONFLICT",
                "provider reconciliation mode differs from the frozen capability profile",
            )
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        result = repository.plan(
            {
                "external_effect_id": str(uuid4()),
                "operation_id": context.operation_id,
                "project_id": context.project_id,
                "effect_type": effect_type,
                "stable_idempotency_key": stable_idempotency_key,
                "request_hash": request_hash,
                "request_payload": request_payload,
                "provider": provider,
                "capability": capability,
                "max_attempts": max_attempts,
                "reversible": reversible,
                "completion_policy": completion_policy,
                "compensates_effect_id": compensates_effect_id,
                "model_id": model_id,
                "request_timeout_seconds": request_timeout_seconds,
                "reconciliation_mode": reconciliation_mode,
                "manual_resolution_required": reconciliation_mode == "unsupported",
                "provider_capability_profile": capability_profile,
                "provider_control_level": (
                    str(capability_profile.get("control_level"))
                    if capability_profile
                    else ProviderControlLevel.LEGACY_UNCONTROLLED.value
                ),
                "provider_idempotency_mode": (
                    "provider"
                    if capability_profile.get("supports_provider_idempotency")
                    else "unsupported"
                ),
                "provider_query_mode": (
                    "query"
                    if capability_profile.get("supports_query")
                    else "unsupported"
                ),
                "provider_cancel_mode": (
                    "cancel"
                    if capability_profile.get("supports_cancel")
                    else "unsupported"
                ),
                "provider_callback_mode": (
                    "callback"
                    if capability_profile.get("supports_callback")
                    else "unsupported"
                ),
            }
        )
        if not result["replayed"]:
            _record(
                repository,
                context,
                result["external_effect_id"],
                "external_effect.planned",
                {
                    "effect_type": effect_type,
                    "provider": provider,
                    "capability": capability,
                },
            )
        # WHY: Repository.plan intentionally returns only admission identity.  The
        # caller must nevertheless settle and recover against the capability
        # profile frozen on the authoritative Effect, especially on replay
        # where the current Adapter declaration is not the source of truth.
        planned_effect = repository.get_for_update(result["external_effect_id"])
        result = {
            **result,
            "provider_capability_profile": dict(
                planned_effect.get("provider_capability_profile") or {}
            ),
        }
        uow.commit()
    return result


def require_effect_retry_ready(cursor: Any, effect_id: str) -> None:
    cursor.execute(
        """SELECT status,evidence,COALESCE(finished_at,updated_at,created_at),NOW()
           FROM authority_external_effect_dispatch WHERE external_effect_id=%s
           ORDER BY generation DESC LIMIT 1""",
        [effect_id],
    )
    row = cursor.fetchone()
    if row is None or row[0] != "FAILED_RETRYABLE":
        return
    process = (row[1] or {}).get("production_execution", {}).get("process_evidence", {})
    if process.get("failure_class") not in {"RATE_LIMIT", "PROVIDER_UNAVAILABLE"}:
        return
    delay = process.get("retry_after_seconds")
    if not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
        delay = 30
    try:
        ready_at = row[2] + timedelta(seconds=delay)
    except OverflowError:
        ready_at = datetime.max.replace(tzinfo=row[2].tzinfo)
    if row[3] < ready_at:
        raise KernelError("EFFECT_RETRY_DEFERRED", "Provider retry is deferred until " + ready_at.isoformat())


def prepare_effect_dispatch(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
) -> dict[str, Any]:
    reconciliation_required = False
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        effect = repository.get_for_update(effect_id)
        _require_project(effect, context.project_id)
        if effect["effect_type"] in MODEL_DISPATCH_EFFECT_TYPES:
            from novel_forge.modules.command_kernel.budget_runtime import require_known_cli_lineage

            require_dispatch_enabled(uow.cursor, context.project_id)
            require_known_cli_lineage(uow.cursor, project_id=context.project_id, operation_id=context.operation_id)
        require_effect_retry_ready(uow.cursor, effect_id)
        result = repository.prepare_dispatch(effect, str(uuid4()))
        reconciliation_required = bool(result.get("reconciliation_required"))
        if reconciliation_required:
            _record(
                repository,
                context,
                effect_id,
                "external_effect.reconciliation_required",
                {
                    "dispatch_id": result["dispatch_id"],
                    "generation": result["generation"],
                    "reason": "dispatch lease expired after request may have started",
                },
            )
        elif not result["replayed"]:
            _record(
                repository,
                context,
                effect_id,
                "external_effect.dispatch_prepared",
                {
                    "dispatch_id": result["dispatch_id"],
                    "generation": result["generation"],
                },
            )
        uow.commit()
    if reconciliation_required:
        raise KernelError(
            "EFFECT_RECONCILIATION_REQUIRED",
            "expired dispatch outcome must be queried before any Provider retry",
        )
    return result


def acquire_effect_dispatch(
    database_url: str,
    context: EffectCommandContext,
    *,
    dispatch_id: str,
    worker_id: str,
    lease_seconds: int,
) -> dict[str, Any]:
    try:
        with AuthorityUnitOfWork(database_url) as uow:
            repository = uow.repositories.external_effects
            _require_context(repository, context)
            dispatch = repository.dispatch_for_update(dispatch_id)
            _require_project(dispatch, context.project_id)
            lease = repository.acquire_lease(
                str(uuid4()),
                dispatch_id,
                worker_id,
                lease_seconds,
            )
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.dispatch_leased",
                {
                    "dispatch_id": dispatch_id,
                    "worker_id": worker_id,
                    "fencing_token": lease["fencing_token"],
                },
            )
            uow.commit()
            return lease
    except psycopg.errors.CheckViolation as exc:
        raise KernelError(
            "EFFECT_LEASE_NOT_AVAILABLE",
            "effect dispatch already has an active lease",
        ) from exc


def dispatch_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
    worker_id: str,
    lease_seconds: int,
    adapter: ExternalEffectAdapter,
    budget_reservation_id: str = "",
    pre_send_assertion: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if type(adapter) is not MinioObjectStoreExternalEffectAdapter:
        assert_legacy_execution_allowed(component="ExternalEffect adapter",
            gateway_backed=bool(getattr(adapter, "production_execution_gateway_backed", False)))
    effect = _read_effect(database_url, effect_id, context.project_id)
    if adapter.provider != effect["provider"]:
        raise KernelError(
            "EFFECT_PROVIDER_CONFLICT",
            "adapter provider differs from the frozen effect intent",
        )
    _validate_frozen_adapter_capability(effect, adapter)
    _admit_effect_adapter(database_url, context, effect=effect, adapter=adapter)
    dispatch = prepare_effect_dispatch(database_url, context, effect_id=effect_id)
    lease = acquire_effect_dispatch(
        database_url,
        context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    try:
        probe_external_effect_execution(
            database_url,
            external_effect_id=effect_id,
            project_id=context.project_id,
        )
    except KernelError as exc:
        submit_effect_dispatch_result(
            database_url,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
            outcome="retryable_failure",
            evidence={
                "error_type": type(exc).__name__,
                "message": redact_secret_text(exc),
                "request_sent": False,
                "timeout_phase": "before_send",
            },
        )
        raise KernelError(
            "EFFECT_REQUEST_TIMEOUT_BEFORE_SEND",
            "Provider request deadline expired before dispatch",
        ) from exc
    try:
        from novel_forge.modules.command_kernel.budget_runtime import (
            assert_provider_execution_authorized,
        )

        assert_provider_execution_authorized(
            database_url,
            operation_id=context.operation_id,
            external_effect_id=effect_id,
            project_id=context.project_id,
            budget_reservation_id=budget_reservation_id,
        )
    except Exception as exc:
        error_code = str(getattr(exc, "code", ""))
        permanent_denial = (
            isinstance(exc, KernelError)
            and error_code in _PERMANENT_BUDGET_AUTHORIZATION_DENIALS
        )
        submit_effect_dispatch_result(
            database_url,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
            outcome="final_failure" if permanent_denial else "retryable_failure",
            evidence={
                "error_type": type(exc).__name__,
                "error_code": error_code,
                "message": redact_secret_text(exc),
                "request_sent": False,
                "failure_phase": "budget_execution_assertion",
                "authorization_denial_permanent": permanent_denial,
            },
        )
        if isinstance(exc, KernelError):
            raise
        raise KernelError(
            "EFFECT_BUDGET_EXECUTION_ASSERTION_FAILED",
            "Provider budget execution assertion failed before send",
        ) from exc
    provider_send_started = False
    final_gate_started = False
    try:
        with LeaseHeartbeatGuard(
            lambda: heartbeat_effect_dispatch(
                database_url,
                context,
                dispatch_id=dispatch["dispatch_id"],
                worker_id=worker_id,
                fencing_token=lease["fencing_token"],
                lease_seconds=lease_seconds,
            ),
            lease_seconds=lease_seconds,
            label=f"effect:{dispatch['dispatch_id']}",
            probe=lambda: probe_external_effect_execution(
                database_url,
                external_effect_id=effect_id,
                project_id=context.project_id,
            ),
        ):
            # WHY: This is the last executable statement before entering the
            # adapter.  The Effect dispatch lease is already held and its
            # heartbeat guard is active; a stale outer owner cannot exploit a
            # gap between its final Authority check and Provider send.
            if pre_send_assertion is not None:
                final_gate_started = True
                pre_send_assertion()
                final_gate_started = False
            if effect["effect_type"] in MODEL_DISPATCH_EFFECT_TYPES:
                assert_dispatch_enabled(database_url, context.project_id)
            provider_send_started = True
            provider_result = adapter.execute(
                stable_idempotency_key=effect["stable_idempotency_key"],
                capability=effect["capability"],
                request_payload={
                    **effect["request_payload"],
                    "external_effect_id": effect["external_effect_id"],
                    "operation_id": effect["operation_id"],
                    "request_hash": effect["request_hash"],
                    "timeout_seconds": int(effect.get("request_timeout_seconds") or 30),
                },
            )
    except ExternalEffectAdapterError as exc:
        recorded = "unknown" if exc.request_sent else "retryable_failure"
        submit_effect_dispatch_result(
            database_url,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
            outcome=recorded,
            evidence={
                "error_type": type(exc).__name__,
                "message": redact_secret_text(exc),
                "request_sent": exc.request_sent,
                "failure_kind": exc.failure_kind,
            },
        )
        raise KernelError(
            (
                "EFFECT_EXTERNAL_STATE_UNKNOWN"
                if exc.request_sent
                else "EFFECT_RETRYABLE_FAILURE_RECORDED"
            ),
            f"adapter exception was recorded as {recorded}",
        ) from exc
    except Exception as exc:
        if not provider_send_started:
            error_code = str(getattr(exc, "code", ""))
            permanent_denial = (
                final_gate_started
                and error_code in _PERMANENT_PRE_SEND_AUTHORIZATION_DENIALS
            )
            submit_effect_dispatch_result(
                database_url,
                context,
                dispatch_id=dispatch["dispatch_id"],
                worker_id=worker_id,
                fencing_token=lease["fencing_token"],
                outcome="final_failure" if permanent_denial else "retryable_failure",
                evidence={
                    "error_type": type(exc).__name__,
                    "error_code": error_code,
                    **({"dispatch_pause_contract": "runtime-dispatch-control.v1"} if error_code == "RUNTIME_DISPATCH_PAUSED" else {}),
                    "message": redact_secret_text(exc),
                    "request_sent": False,
                    "failure_phase": (
                        "pre_send_assertion"
                        if final_gate_started
                        else "dispatch_lease_guard"
                    ),
                    "authorization_denial_permanent": permanent_denial,
                },
            )
            if isinstance(exc, KernelError):
                raise
            raise KernelError(
                "EFFECT_PRE_SEND_ASSERTION_FAILED",
                "Provider pre-send assertion failed before any request was sent",
            ) from exc
        submit_effect_dispatch_result(
            database_url,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
            outcome="unknown",
            evidence={
                "error_type": type(exc).__name__,
                "message": redact_secret_text(exc),
                "request_sent": "not_established",
            },
        )
        raise KernelError(
            "EFFECT_EXTERNAL_STATE_UNKNOWN",
            "untyped adapter exception was conservatively recorded as UNKNOWN",
        ) from exc

    outcome = submit_effect_dispatch_result(
        database_url,
        context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id=worker_id,
        fencing_token=lease["fencing_token"],
        outcome=provider_result.outcome,
        evidence=provider_result.evidence,
        provider_correlation_id=provider_result.provider_correlation_id,
        provider_request_id=provider_result.provider_request_id,
    )
    receipt: dict[str, Any] | None = None
    if outcome == "success" and effect["completion_policy"] == "synchronous_final":
        receipt_id = provider_result.provider_correlation_id or (
            f"{adapter.provider}:{dispatch['dispatch_id']}:{dispatch['generation']}"
        )
        receipt = accept_external_effect_receipt(
            database_url,
            context,
            dispatch_id=dispatch["dispatch_id"],
            provider=adapter.provider,
            receipt_id=receipt_id,
            message_id=f"sync-final:{receipt_id}:{dispatch['generation']}",
            payload_hash=_hash(provider_result.evidence),
            provider_correlation_id=provider_result.provider_correlation_id,
            generation=dispatch["generation"],
            outcome="success",
            evidence=provider_result.evidence,
        )
    return {
        "dispatch_id": dispatch["dispatch_id"],
        "outcome": outcome,
        "receipt": receipt,
        "provider_correlation_id": provider_result.provider_correlation_id,
        "provider_request_id": provider_result.provider_request_id,
        "provider_evidence": provider_result.evidence,
    }


def heartbeat_effect_dispatch(
    database_url: str,
    context: EffectCommandContext,
    *,
    dispatch_id: str,
    worker_id: str,
    fencing_token: int,
    lease_seconds: int,
) -> dict[str, Any]:
    if lease_seconds <= 0:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID", "effect lease duration must be positive"
        )
    stale = False
    expires_at = None
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        dispatch = repository.dispatch_for_update(dispatch_id)
        _require_project(dispatch, context.project_id)
        valid, current_token = repository.current_fence(
            dispatch_id,
            worker_id,
            fencing_token,
        )
        if valid:
            expires_at = repository.heartbeat_lease(
                dispatch_id,
                worker_id,
                fencing_token,
                lease_seconds,
            )
            if expires_at is None:
                stale = True
        else:
            stale = True
        if stale:
            repository.reject_stale(
                {
                    "rejection_id": str(uuid4()),
                    "external_effect_id": dispatch["external_effect_id"],
                    "dispatch_id": dispatch_id,
                    "worker_id": worker_id,
                    "presented_fencing_token": fencing_token,
                    "current_fencing_token": current_token,
                    "command_type": "heartbeat",
                    "payload": {"lease_seconds": lease_seconds},
                    "trace_id": context.trace_id,
                    "correlation_id": context.correlation_id,
                }
            )
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.command_rejected",
                {
                    "dispatch_id": dispatch_id,
                    "command_type": "heartbeat",
                    "presented_fencing_token": fencing_token,
                    "current_fencing_token": current_token,
                },
            )
        else:
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.dispatch_heartbeat",
                {
                    "dispatch_id": dispatch_id,
                    "fencing_token": fencing_token,
                    "expires_at": expires_at.isoformat(),
                },
            )
        uow.commit()
    if stale:
        raise KernelError(
            "EFFECT_FENCING_TOKEN_STALE",
            "effect heartbeat carries a stale fencing token",
        )
    return {"dispatch_id": dispatch_id, "expires_at": expires_at}


def submit_effect_dispatch_result(
    database_url: str,
    context: EffectCommandContext,
    *,
    dispatch_id: str,
    worker_id: str,
    fencing_token: int,
    outcome: str,
    evidence: dict[str, Any],
    provider_correlation_id: str = "",
    provider_request_id: str = "",
) -> str:
    if outcome not in {"success", "retryable_failure", "final_failure", "unknown"}:
        raise KernelError("EFFECT_OUTCOME_INVALID", "unknown provider outcome")
    stale = False
    accepted = ""
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        dispatch = repository.dispatch_for_update(dispatch_id)
        _require_project(dispatch, context.project_id)
        valid, current_token = repository.current_fence(
            dispatch_id,
            worker_id,
            fencing_token,
        )
        if not valid:
            repository.reject_stale(
                {
                    "rejection_id": str(uuid4()),
                    "external_effect_id": dispatch["external_effect_id"],
                    "dispatch_id": dispatch_id,
                    "worker_id": worker_id,
                    "presented_fencing_token": fencing_token,
                    "current_fencing_token": current_token,
                    "command_type": "dispatch_result",
                    "payload": {"outcome": outcome, "evidence": evidence},
                    "trace_id": context.trace_id,
                    "correlation_id": context.correlation_id,
                }
            )
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.command_rejected",
                {
                    "dispatch_id": dispatch_id,
                    "presented_fencing_token": fencing_token,
                    "current_fencing_token": current_token,
                },
            )
            stale = True
        else:
            accepted = repository.submit_result(
                dispatch,
                outcome,
                evidence,
                provider_correlation_id,
                provider_request_id,
            )
            if accepted == "unknown" and dispatch["effect_type"] == "blob.upload":
                blob_id = str(dispatch["request_payload"].get("blob_id") or "")
                if not blob_id:
                    raise KernelError(
                        "BLOB_EFFECT_PAYLOAD_INVALID",
                        "Blob upload effect does not identify its reserved Blob",
                    )
                uow.repositories.asset_blobs.mark_upload_unknown(
                    blob_id,
                    context.project_id,
                )
            repository.release_lease(
                dispatch_id,
                worker_id,
                fencing_token,
                f"result_{accepted}",
            )
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.result_recorded",
                {
                    "dispatch_id": dispatch_id,
                    "generation": dispatch["generation"],
                    "outcome": accepted,
                },
            )
        uow.commit()
    if stale:
        raise KernelError(
            "EFFECT_FENCING_TOKEN_STALE",
            "dispatch result carries a stale fencing token",
        )
    return accepted


def _validate_frozen_adapter_capability(
    effect: dict[str, Any], adapter: ExternalEffectAdapter
) -> None:
    frozen = dict(effect.get("provider_capability_profile") or {})
    if not frozen:
        return
    declared = adapter.capability_profile
    if isinstance(declared, ProviderCapabilityProfile):
        declared = declared.to_dict()
    if not isinstance(declared, dict):
        raise KernelError(
            "EFFECT_PROVIDER_CAPABILITY_MISSING",
            "adapter has no explicit Provider Adapter v2 capability profile",
        )
    if declared != frozen:
        raise KernelError(
            "EFFECT_PROVIDER_CAPABILITY_MISMATCH",
            "adapter runtime capabilities differ from the frozen ExternalEffect profile",
        )


def _validated_frozen_provider_capability_profile(
    effect: dict[str, Any],
) -> dict[str, Any]:
    frozen = effect.get("provider_capability_profile")
    if not isinstance(frozen, dict) or not frozen:
        raise KernelError(
            "EFFECT_PROVIDER_CAPABILITY_MISSING",
            "succeeded Provider Effect has no frozen capability profile",
        )
    try:
        profile = capability_profile_from_dict(dict(frozen))
    except (TypeError, ValueError) as exc:
        raise KernelError(
            "EFFECT_PROVIDER_CAPABILITY_INVALID",
            "succeeded Provider Effect capability profile is invalid",
        ) from exc
    if profile.provider != str(
        effect.get("provider") or ""
    ) or profile.reconciliation_mode != str(effect.get("reconciliation_mode") or ""):
        raise KernelError(
            "EFFECT_PROVIDER_CAPABILITY_CONFLICT",
            "succeeded Provider Effect capability profile differs from its frozen intent",
        )
    return profile.to_dict()


def accept_external_effect_receipt(
    database_url: str,
    context: EffectCommandContext,
    *,
    dispatch_id: str,
    provider: str,
    receipt_id: str,
    message_id: str,
    payload_hash: str,
    provider_correlation_id: str,
    generation: int,
    outcome: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if outcome not in {
        "success",
        "retryable_failure",
        "final_failure",
        "cancelled",
        "compensated",
    }:
        raise KernelError("RECEIPT_OUTCOME_INVALID", "receipt outcome is unsupported")
    conflict = False
    stored: dict[str, Any] = {}
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _validate_effect_context(context)
        dispatch = repository.dispatch_for_update(dispatch_id)
        _require_project(dispatch, context.project_id)
        if provider != dispatch["provider"]:
            raise KernelError(
                "RECEIPT_PROVIDER_CONFLICT", "receipt provider is unexpected"
            )
        stored_outcome = {
            "dispatch_id": dispatch_id,
            "external_effect_id": dispatch["external_effect_id"],
            "outcome": outcome,
        }
        disposition, stored = repository.record_inbox(
            "external_effect.receipt",
            message_id,
            payload_hash,
            stored_outcome,
        )
        if disposition == "REPLAY":
            return {**stored, "replayed": True}
        if disposition == "CONFLICT":
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.receipt_conflicted",
                {"message_id": message_id, "receipt_id": receipt_id},
            )
            conflict = True
        else:
            repository.accept_receipt(
                {
                    "external_effect_id": dispatch["external_effect_id"],
                    "dispatch_id": dispatch_id,
                    "provider": provider,
                    "receipt_id": receipt_id,
                    "payload_hash": payload_hash,
                    "provider_correlation_id": provider_correlation_id,
                    "generation": generation,
                    "outcome": outcome,
                    "evidence": evidence,
                    "payload": {
                        "message_id": message_id,
                        "outcome": outcome,
                        "generation": generation,
                        "evidence": evidence,
                    },
                }
            )
            if dispatch["effect_type"] == "blob.upload" and outcome == "success":
                request = dispatch["request_payload"]
                required = {
                    "object_key": evidence.get("object_key"),
                    "actual_hash": evidence.get("actual_hash"),
                    "actual_size": evidence.get("actual_size"),
                }
                if (
                    not request.get("blob_id")
                    or not required["object_key"]
                    or not required["actual_hash"]
                    or not isinstance(required["actual_size"], int)
                    or required["actual_size"] < 0
                ):
                    raise KernelError(
                        "BLOB_RECEIPT_EVIDENCE_INVALID",
                        "Blob upload receipt lacks verified object identity evidence",
                    )
                uow.repositories.asset_blobs.accept_generic_upload_receipt(
                    blob_id=str(request["blob_id"]),
                    project_id=context.project_id,
                    provider=provider,
                    object_key=str(required["object_key"]),
                    actual_hash=str(required["actual_hash"]),
                    actual_size=int(required["actual_size"]),
                )
            if (
                dispatch["effect_type"] == "external_effect.compensate"
                and outcome == "success"
                and dispatch["compensates_effect_id"]
            ):
                repository.complete_compensated_effect(
                    str(dispatch["compensates_effect_id"])
                )
                _record(
                    repository,
                    context,
                    str(dispatch["compensates_effect_id"]),
                    "external_effect.compensated",
                    {"compensation_effect_id": dispatch["external_effect_id"]},
                )
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.receipt_accepted",
                {
                    "message_id": message_id,
                    "receipt_id": receipt_id,
                    "outcome": outcome,
                },
            )
            operation = uow.repositories.attempt_runtime.operation_state(
                context.operation_id, context.project_id
            )
            current_status = str(operation["status"])
            target_status = {
                "success": "EXECUTING",
                "retryable_failure": "FAILED_RETRYABLE",
                "final_failure": "FAILED_FINAL",
                "cancelled": "CANCELLED",
                "compensated": current_status,
            }[outcome]
            if current_status == "WAITING_EXTERNAL_RESULT" and outcome == "cancelled":
                target_status = "FAILED_FINAL"
            if (
                current_status in {"WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"}
                and target_status != current_status
            ):
                _cas_operation(
                    uow,
                    operation_id=context.operation_id,
                    project_id=context.project_id,
                    expected_status=current_status,
                    expected_version=int(operation["version"]),
                    target_status=target_status,
                    actor_id=context.actor_id,
                    reason=f"external receipt accepted as {outcome}",
                    trace_id=context.trace_id,
                    correlation_id=context.correlation_id,
                    causation_id=dispatch["external_effect_id"],
                )
        uow.commit()
    if conflict:
        raise KernelError(
            "RECEIPT_PAYLOAD_CONFLICT",
            "receipt message id was reused with a different payload",
        )
    return {**stored, "replayed": False}


def reconcile_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
    adapter: ExternalEffectAdapter,
    attempt_command: WorkerLeaseCommand | None = None,
) -> dict[str, Any]:
    effect = _read_effect(database_url, effect_id, context.project_id)
    if effect["status"] not in {
        "DISPATCHING",
        "DISPATCHED",
        "UNKNOWN",
        "RECONCILIATION_REQUIRED",
    }:
        raise KernelError(
            "EFFECT_STATUS_CONFLICT", "effect does not require reconciliation"
        )
    if adapter.provider != effect["provider"]:
        raise KernelError(
            "EFFECT_PROVIDER_CONFLICT", "reconciler provider is unexpected"
        )
    if effect.get("reconciliation_mode") == "unsupported":
        raise KernelError(
            "EFFECT_RECONCILIATION_UNSUPPORTED",
            "provider cannot be queried; manual resolution is required",
        )
    _validate_frozen_adapter_capability(effect, adapter)

    fenced_gateway = bool(getattr(adapter, "production_execution_gateway_backed", False))
    if fenced_gateway:
        if effect["operation_id"] != context.operation_id:
            raise KernelError("EFFECT_OPERATION_CONFLICT", "Recovery must use the original owning Operation")
        if attempt_command is None:
            raise KernelError("ATTEMPT_RECONCILIATION_COMMAND_REQUIRED", "Gateway reconciliation requires the current recovery Attempt fence")
        with AuthorityUnitOfWork(database_url) as uow:
            runtime = uow.repositories.attempt_runtime
            attempt = runtime.get_for_update(attempt_command.attempt_id, context.project_id)
            valid, _ = runtime.current_fence(attempt_command.attempt_id, attempt_command.worker_id, attempt_command.fencing_token)
            if not valid or attempt_command.project_id != context.project_id or attempt["operation_id"] != context.operation_id:
                raise KernelError("ATTEMPT_FENCING_TOKEN_STALE", "Gateway reconciliation requires the owning active recovery lease")
            operation = runtime.operation_state(context.operation_id, context.project_id)
            if operation["status"] in {"WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"}:
                _cas_operation(uow, operation_id=context.operation_id, project_id=context.project_id,
                    expected_status=operation["status"], expected_version=int(operation["version"]), target_status="EXECUTING",
                    actor_id=attempt_command.worker_id, reason="fenced execution evidence reconciliation",
                    trace_id=context.trace_id, correlation_id=context.correlation_id, causation_id=effect_id)
            elif operation["status"] != "EXECUTING":
                raise KernelError("OPERATION_STATUS_CONFLICT", "Gateway evidence reconciliation requires recoverable durable work")
            uow.commit()
    try:
        result = adapter.query(
            stable_idempotency_key=effect["stable_idempotency_key"],
            capability=effect["capability"],
            request_payload={
                **effect["request_payload"],
                "provider_request_id": str(effect.get("provider_request_id") or ""),
                "external_effect_id": effect["external_effect_id"],
                "operation_id": effect["operation_id"],
                "trace_id": context.trace_id,
                "correlation_id": context.correlation_id,
            },
        )
    except Exception as exc:
        if fenced_gateway:
            raise KernelError("EXTERNAL_EFFECT_RECONCILIATION_REQUIRED", redact_secret_text(str(exc))) from exc
        raise

    if result.outcome not in {
        "success",
        "not_found",
        "ambiguous",
        "failed_final",
        "cancelled",
    }:
        raise KernelError(
            "RECONCILIATION_OUTCOME_INVALID", "provider query is inconclusive"
        )
    reconciliation_evidence = {
        **result.evidence,
        "provider_correlation_id": result.provider_correlation_id,
    }
    if result.outcome == "success":
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                """
                SELECT dispatch_id, generation
                FROM authority_external_effect_dispatch
                WHERE external_effect_id=%s
                ORDER BY generation DESC
                LIMIT 1
                """,
                [effect_id],
            )
            dispatch = uow.cursor.fetchone()
        if dispatch is None:
            raise KernelError(
                "EFFECT_RECONCILIATION_DISPATCH_MISSING",
                "successful reconciliation has no original Provider dispatch",
            )
        generation = int(dispatch[1])
        reconciliation_receipt_id = f"reconciliation:{effect_id}:{generation}:success"
        accept_external_effect_receipt(
            database_url,
            context,
            dispatch_id=str(dispatch[0]),
            provider=effect["provider"],
            receipt_id=reconciliation_receipt_id,
            message_id=reconciliation_receipt_id,
            payload_hash=_hash(result.evidence),
            provider_correlation_id=result.provider_correlation_id,
            generation=generation,
            outcome="success",
            evidence=result.evidence,
        )
        with AuthorityUnitOfWork(database_url) as uow:
            repository = uow.repositories.external_effects
            repository.record_reconciliation_evidence(
                {
                    "reconciliation_id": str(uuid4()),
                    "external_effect_id": effect_id,
                    "provider": effect["provider"],
                    "stable_idempotency_key": effect["stable_idempotency_key"],
                    "outcome": result.outcome,
                    "evidence": reconciliation_evidence,
                    "trace_id": context.trace_id,
                    "correlation_id": context.correlation_id,
                }
            )
            _record(
                repository,
                context,
                effect_id,
                "external_effect.reconciled",
                {
                    "outcome": result.outcome,
                    "receipt_id": reconciliation_receipt_id,
                },
            )
            operation = uow.repositories.attempt_runtime.operation_state(
                context.operation_id, context.project_id
            )
            target_status = str(operation["status"])
            if target_status == "CANCELLATION_REQUESTED":
                target_status = "COMPENSATION_REQUIRED"
                _cas_operation(
                    uow,
                    operation_id=context.operation_id,
                    project_id=context.project_id,
                    expected_status="CANCELLATION_REQUESTED",
                    expected_version=int(operation["version"]),
                    target_status=target_status,
                    actor_id=context.actor_id,
                    reason="cancelled Operation reconciled a successful external effect",
                    trace_id=context.trace_id,
                    correlation_id=context.correlation_id,
                    causation_id=effect_id,
                )
            uow.commit()
        _resolve_reconciled_budget(
            database_url,
            project_id=context.project_id,
            effect_id=effect_id,
            outcome=result.outcome,
            evidence=result.evidence,
        )
        return {
            "external_effect_id": effect_id,
            "outcome": result.outcome,
            "operation_status": target_status,
            "receipt_id": reconciliation_receipt_id,
        }
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _validate_effect_context(context)
        current = repository.get_for_update(effect_id)
        _require_project(current, context.project_id)
        repository.record_reconciliation(
            {
                "reconciliation_id": str(uuid4()),
                "external_effect_id": effect_id,
                "provider": effect["provider"],
                "stable_idempotency_key": effect["stable_idempotency_key"],
                "outcome": result.outcome,
                "evidence": reconciliation_evidence,
                "trace_id": context.trace_id,
                "correlation_id": context.correlation_id,
            }
        )
        _record(
            repository,
            context,
            effect_id,
            "external_effect.reconciled",
            {"outcome": result.outcome},
        )
        operation = uow.repositories.attempt_runtime.operation_state(
            context.operation_id, context.project_id
        )
        current_status = str(operation["status"])
        target_status = {
            "success": "EXECUTING",
            "not_found": "FAILED_RETRYABLE",
            "failed_final": "FAILED_FINAL",
            "cancelled": "CANCELLED",
            "ambiguous": "RECONCILIATION_REQUIRED",
        }[result.outcome]
        if current_status == "EXECUTING" and result.outcome == "ambiguous":
            target_status = "WAITING_EXTERNAL_RESULT"
        if current_status == "CANCELLATION_REQUESTED":
            target_status = {
                "success": "COMPENSATION_REQUIRED",
                "not_found": "CANCELLED",
                "failed_final": "CANCELLED",
                "cancelled": "CANCELLED",
                "ambiguous": "RECONCILIATION_REQUIRED",
            }[result.outcome]
        if current_status != target_status:
            if current_status not in {
                "EXECUTING",
                "WAITING_EXTERNAL_RESULT",
                "RECONCILIATION_REQUIRED",
                "CANCELLATION_REQUESTED",
            }:
                raise KernelError(
                    "OPERATION_STATUS_CONFLICT",
                    f"operation cannot resume reconciliation from {current_status}",
                )
            _cas_operation(
                uow,
                operation_id=context.operation_id,
                project_id=context.project_id,
                expected_status=current_status,
                expected_version=int(operation["version"]),
                target_status=target_status,
                actor_id=context.actor_id,
                reason=f"external effect reconciled as {result.outcome}",
                trace_id=context.trace_id,
                correlation_id=context.correlation_id,
                causation_id=effect_id,
            )
        if result.outcome in {"not_found", "failed_final", "cancelled"}:
            if attempt_command is None:
                uow.cursor.execute(
                    """
                    SELECT 1 FROM authority_attempt
                    WHERE operation_id=%s AND status='CHECKPOINTED'
                    LIMIT 1
                    """,
                    [context.operation_id],
                )
                if uow.cursor.fetchone() is not None:
                    raise KernelError(
                        "ATTEMPT_RECONCILIATION_COMMAND_REQUIRED",
                        "terminal ExternalEffect reconciliation must fence its checkpointed Attempt",
                    )
            else:
                _terminalize_reconciled_attempt(
                    uow,
                    context=context,
                    command=attempt_command,
                    outcome=result.outcome,
                    effect_id=effect_id,
                )
        uow.commit()
    _resolve_reconciled_budget(
        database_url,
        project_id=context.project_id,
        effect_id=effect_id,
        outcome=result.outcome,
        evidence=result.evidence,
    )
    return {
        "external_effect_id": effect_id,
        "outcome": result.outcome,
        "operation_status": target_status,
    }


def _terminalize_reconciled_attempt(
    uow: AuthorityUnitOfWork,
    *,
    context: EffectCommandContext,
    command: WorkerLeaseCommand,
    outcome: str,
    effect_id: str,
) -> None:
    if (
        command.project_id != context.project_id
        or command.causation_id != context.operation_id
    ):
        raise KernelError(
            "ATTEMPT_RECONCILIATION_IDENTITY_CONFLICT",
            "Attempt recovery identity differs from the reconciled ExternalEffect",
        )
    attempt = uow.repositories.attempt_runtime.get_for_update(
        command.attempt_id,
        command.project_id,
    )
    if (
        attempt["operation_id"] != context.operation_id
        or attempt["status"] != "CHECKPOINTED"
    ):
        raise KernelError(
            "ATTEMPT_RECONCILIATION_STATUS_CONFLICT",
            "ExternalEffect terminal reconciliation requires its checkpointed Attempt",
        )
    valid, current_token = uow.repositories.attempt_runtime.current_fence(
        command.attempt_id,
        command.worker_id,
        command.fencing_token,
    )
    if not valid:
        raise KernelError(
            "ATTEMPT_FENCING_TOKEN_STALE",
            "ExternalEffect reconciliation carries a stale Attempt fence "
            f"(current token {current_token})",
        )
    terminal_status = {
        "not_found": "FAILED_RETRYABLE",
        "failed_final": "FAILED_FINAL",
        "cancelled": "CANCELLED",
    }[outcome]
    result = {
        "external_effect_id": effect_id,
        "reconciliation_outcome": outcome,
    }
    if terminal_status == "CANCELLED":
        _transition_attempt(
            uow,
            attempt,
            terminal_status,
            worker_id=command.worker_id,
            fencing_token=command.fencing_token,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            result=result,
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
        _transition_attempt(
            uow,
            {**attempt, "status": "RESULT_SUBMITTED"},
            terminal_status,
            worker_id=command.worker_id,
            fencing_token=command.fencing_token,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            result=result,
        )
    uow.repositories.attempt_runtime.release(
        command.attempt_id,
        command.worker_id,
        command.fencing_token,
        f"external_effect_reconciled_{outcome}",
    )
    uow.repositories.attempt_runtime.assert_lease_consistency(command.attempt_id)


def resume_operation_from_completed_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
) -> dict[str, Any]:

    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _validate_effect_context(context)
        uow.cursor.execute("SELECT status FROM authority_operation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
            [context.operation_id, context.project_id])
        if uow.cursor.fetchone() is None:
            raise KernelError('OPERATION_NOT_FOUND', 'Completed effect recovery requires its existing owner')
        effect = repository.get_for_update(effect_id)
        _require_project(effect, context.project_id)
        if effect['operation_id'] != context.operation_id:
            raise KernelError('EFFECT_OPERATION_CONFLICT', 'Completed effect belongs to another Operation')
        if effect["status"] != "SUCCEEDED":
            raise KernelError(
                "EFFECT_STATUS_CONFLICT",
                "completed-effect recovery requires SUCCEEDED evidence",
            )
        operation = uow.repositories.attempt_runtime.operation_state(
            context.operation_id,
            context.project_id,
        )
        current_status = str(operation["status"])
        if current_status in {
            "WAITING_EXTERNAL_RESULT",
            "RECONCILIATION_REQUIRED",
        }:
            _cas_operation(
                uow,
                operation_id=context.operation_id,
                project_id=context.project_id,
                expected_status=current_status,
                expected_version=int(operation["version"]),
                target_status="EXECUTING",
                actor_id=context.actor_id,
                reason="durable successful ExternalEffect evidence recovered",
                trace_id=context.trace_id,
                correlation_id=context.correlation_id,
                causation_id=effect_id,
            )
            _record(
                repository,
                context,
                effect_id,
                "external_effect.completed_result_recovered",
                {"prior_operation_status": current_status},
            )
            current_status = "EXECUTING"
        elif current_status != "EXECUTING":
            raise KernelError(
                "OPERATION_STATUS_CONFLICT",
                f"completed effect cannot resume Operation from {current_status}",
            )
        uow.commit()
    return {
        "external_effect_id": effect_id,
        "outcome": "success",
        "operation_status": current_status,
    }


def mark_external_effect_unknown(
    database_url: str,
    context: EffectCommandContext,
    *,
    dispatch_id: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        dispatch = repository.dispatch_for_update(dispatch_id)
        _require_project(dispatch, context.project_id)
        repository.mark_unknown(dispatch, evidence)
        if dispatch["effect_type"] == "blob.upload":
            blob_id = str(dispatch["request_payload"].get("blob_id") or "")
            if not blob_id:
                raise KernelError(
                    "BLOB_EFFECT_PAYLOAD_INVALID",
                    "Blob upload effect does not identify its reserved Blob",
                )
            uow.repositories.asset_blobs.mark_upload_unknown(
                blob_id, context.project_id
            )
        _record(
            repository,
            context,
            dispatch["external_effect_id"],
            "external_effect.reconciliation_required",
            {"dispatch_id": dispatch_id, "evidence": evidence},
        )
        uow.commit()
    return {
        "external_effect_id": dispatch["external_effect_id"],
        "dispatch_id": dispatch_id,
        "status": "RECONCILIATION_REQUIRED",
    }


def cancel_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
    adapter: ExternalEffectAdapter | None = None,
) -> dict[str, Any]:
    effect_snapshot = _read_effect(database_url, effect_id, context.project_id)
    provider_result = None
    if adapter is not None:
        if adapter.provider != effect_snapshot["provider"]:
            raise KernelError(
                "EFFECT_PROVIDER_CONFLICT", "cancellation adapter is unexpected"
            )
        _validate_frozen_adapter_capability(effect_snapshot, adapter)
        provider_result = adapter.cancel(
            stable_idempotency_key=effect_snapshot["stable_idempotency_key"],
            capability=effect_snapshot["capability"],
            request_payload={
                **effect_snapshot["request_payload"],
                "cancel_reason": "authority cancellation",
                "trace_id": context.trace_id,
                "correlation_id": context.correlation_id,
            },
            provider_request_id=str(effect_snapshot.get("provider_request_id") or ""),
        )
        if provider_result.outcome not in {
            "cancelled",
            "already_completed",
            "unsupported",
            "ambiguous",
        }:
            raise KernelError(
                "EFFECT_CANCEL_OUTCOME_INVALID", "provider cancel outcome is invalid"
            )
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        effect = repository.get_for_update(effect_id)
        _require_project(effect, context.project_id)
        if provider_result is not None and provider_result.outcome == "cancelled":
            uow.cursor.execute(
                "UPDATE authority_external_effect SET status='CANCELLED' WHERE external_effect_id=%s",
                [effect_id],
            )
            uow.cursor.execute(
                """
                UPDATE authority_external_effect_dispatch
                SET status='CANCELLED', finished_at=NOW(), updated_at=NOW(),
                    evidence = evidence || %s
                WHERE external_effect_id=%s
                  AND status IN ('CREATED','DISPATCHING','ACKNOWLEDGED','UNKNOWN','CANCEL_REQUESTED')
                """,
                [Jsonb(provider_result.evidence), effect_id],
            )
            target = "CANCELLED"
        else:
            target = repository.cancel(effect)
        _record(
            repository,
            context,
            effect_id,
            "external_effect.cancelled"
            if target == "CANCELLED"
            else "external_effect.cancel_coordinated",
            {
                "status": target,
                "provider_cancel_outcome": (
                    provider_result.outcome
                    if provider_result is not None
                    else "not_dispatched"
                ),
                "provider_cancel_evidence": (
                    provider_result.evidence if provider_result is not None else {}
                ),
            },
        )
        uow.commit()
    return {
        "external_effect_id": effect_id,
        "status": target,
        "provider_cancel_outcome": (
            provider_result.outcome if provider_result is not None else "not_dispatched"
        ),
    }


def cancel_operation_external_effects(
    database_url: str,
    *,
    root_operation_id: str,
    project_id: str,
    actor_id: str,
    trace_id: str,
    correlation_id: str,
    adapters: dict[str, ExternalEffectAdapter],
) -> tuple[dict[str, Any], ...]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT effect.external_effect_id, effect.operation_id, effect.provider
            FROM authority_external_effect effect
            JOIN authority_operation operation ON operation.operation_id = effect.operation_id
            WHERE operation.root_operation_id = %s AND effect.project_id = %s
              AND effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')
            ORDER BY effect.created_at
            """,
            [root_operation_id, project_id],
        )
        rows = tuple(uow.cursor.fetchall())
    results: list[dict[str, Any]] = []
    for effect_id, operation_id, provider in rows:
        results.append(
            cancel_external_effect(
                database_url,
                EffectCommandContext(
                    operation_id=str(operation_id),
                    project_id=project_id,
                    actor_id=actor_id,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id=root_operation_id,
                ),
                effect_id=str(effect_id),
                adapter=adapters.get(str(provider)),
            )
        )
    return tuple(results)


def compensate_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    effect = _read_effect(database_url, effect_id, context.project_id)
    if not effect["reversible"]:
        raise KernelError(
            "EFFECT_NOT_REVERSIBLE", "external effect has no compensation protocol"
        )
    if effect["status"] not in {"SUCCEEDED", "COMPENSATION_REQUIRED"}:
        raise KernelError(
            "EFFECT_STATUS_CONFLICT", "external effect is not compensatable"
        )
    return plan_external_effect(
        database_url,
        context,
        effect_type="external_effect.compensate",
        provider=effect["provider"],
        capability=f"{effect['capability']}.compensate",
        stable_idempotency_key=f"compensate:{effect['stable_idempotency_key']}",
        request_payload={
            "compensates_effect_id": effect_id,
            "original_capability": effect["capability"],
            "original_request_hash": effect["request_hash"],
        },
        max_attempts=max_attempts,
        reversible=False,
        completion_policy=effect["completion_policy"],
        compensates_effect_id=effect_id,
    )


def _admit_effect_adapter(database_url: str, context: EffectCommandContext, *, effect: dict[str, Any],
                          adapter: ExternalEffectAdapter) -> None:
    if (type(adapter) is MinioObjectStoreExternalEffectAdapter
            and effect["effect_type"] == "blob.upload" and effect["capability"] == "object_store.put"):
        payload = effect["request_payload"]
        with AuthorityUnitOfWork(database_url) as uow:
            repository = uow.repositories.external_effects
            _require_context(repository, context)
            blob = uow.repositories.asset_blobs.blob_for_update(str(payload.get("blob_id") or ""))
            if (effect["operation_id"] != context.operation_id
                    or _hash(payload) != effect["request_hash"]
                    or blob["upload_effect_id"] != effect["external_effect_id"]
                    or blob["project_id"] != context.project_id
                    or any(blob[key] != payload.get(key) for key in (
                        "project_id", "provider", "object_key", "expected_hash", "expected_size", "media_type"))
                    or blob["provider"] != adapter.provider):
                raise KernelError("BLOB_EXECUTION_ADMISSION_CONFLICT", "Storage intent differs from its Authority reservation")
            _record(repository, context, effect["external_effect_id"], "external_effect.storage_admitted", {
                "policy_version": "authority-blob-execution.v1", "blob_id": blob["blob_id"],
                "request_hash": effect["request_hash"], "gateway_backed": False,
                "production_verified": False,
            })
            uow.commit()
        return
    assert_legacy_execution_allowed(component="ExternalEffect adapter",
        gateway_backed=bool(getattr(adapter, "production_execution_gateway_backed", False)))


def _read_effect(database_url: str, effect_id: str, project_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        effect = uow.repositories.external_effects.get_for_update(effect_id)
        _require_project(effect, project_id)
        return effect


def _require_context(repository: Any, context: EffectCommandContext) -> None:
    _validate_effect_context(context)
    repository.require_operation(context.operation_id, context.project_id)


def _validate_effect_context(context: EffectCommandContext) -> None:
    if any(
        not value
        for value in (
            context.operation_id,
            context.project_id,
            context.actor_id,
            context.trace_id,
            context.correlation_id,
        )
    ):
        raise KernelError(
            "COMMAND_SCHEMA_INVALID", "effect command context is incomplete"
        )


def _resolve_reconciled_budget(
    database_url: str,
    *,
    project_id: str,
    effect_id: str,
    outcome: str,
    evidence: dict[str, Any],
) -> None:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT reservation.reservation_id,reservation.reserved_amount,
                   reservation.estimated_tokens,
                   COALESCE(
                       NULLIF(to_jsonb(reservation)->>'accounting_basis',''),
                       'PRICED'
                   ), effect.effect_type,effect.provider_capability_profile
            FROM authority_budget_reservation AS reservation
            JOIN authority_external_effect AS effect USING(external_effect_id)
            WHERE reservation.external_effect_id=%s AND reservation.project_id=%s
              AND reservation.status IN ('RESERVED','HELD_UNKNOWN')
            ORDER BY reservation.created_at DESC LIMIT 1
            """,
            [effect_id, project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return
    if row[4] == "model.invoke":
        from .provider_failure_accounting import failed_provider_budget_decision, successful_provider_budget_settlement

        basis = str(row[3] or "PRICED").upper()
        reserved_amount = None if basis == "ACCOUNT_ENTITLEMENT" else str(row[1])
        if outcome == "success":
            usage = evidence.get("usage") or {}
            cost = {**(evidence.get("cost") or {}), "accounting_basis": basis}
            amount, tokens, settlement = successful_provider_budget_settlement(
                real_model_call=evidence.get("real_model_call") is not False,
                usage_tokens=int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0),
                cost_amount=str(cost.get("amount") or "0"), cost=cost,
                reserved_amount=reserved_amount, reserved_tokens=int(row[2]),
                frozen_capability_profile=dict(row[5] or {}),
            )
            settle_provider_budget(database_url, reservation_id=str(row[0]), project_id=project_id,
                                   actual_amount=amount, actual_tokens=tokens,
                                   evidence={**evidence, **settlement, "reconciled": True})
        elif outcome in {"not_found", "failed_final", "cancelled"}:
            decision = failed_provider_budget_decision(
                dispatched={"outcome": outcome, "provider_evidence": evidence,
                            **({"request_sent": False} if outcome == "not_found" else {})},
                reserved_amount=reserved_amount, reserved_tokens=int(row[2]),
                frozen_capability_profile=dict(row[5] or {}),
            )
            if decision["disposition"] == "SETTLE":
                settle_provider_budget(database_url, reservation_id=str(row[0]), project_id=project_id,
                    actual_amount=decision["actual_amount"], actual_tokens=decision["actual_tokens"],
                    evidence={**evidence, **decision, "reconciled": True})
            else:
                resolve_provider_budget_failure(database_url, reservation_id=str(row[0]), project_id=project_id,
                    external_state_unknown=decision["disposition"] == "HOLD_UNKNOWN")
        return
    if outcome == "success":
        normalized = dict(evidence)
        usage = normalized.get("usage")
        cost = normalized.get("cost")
        if isinstance(usage, dict):
            normalized.setdefault(
                "actual_tokens",
                int(usage.get("total_tokens") or 0)
                or int(usage.get("input_tokens") or 0)
                + int(usage.get("output_tokens") or 0),
            )
        accounting_basis = str(row[3] or "PRICED").upper()
        if isinstance(cost, dict) and accounting_basis != "ACCOUNT_ENTITLEMENT":
            normalized.setdefault("actual_cost", str(cost.get("amount") or "0"))
        settle_provider_budget(
            database_url,
            reservation_id=str(row[0]),
            project_id=project_id,
            actual_amount=(
                None
                if accounting_basis == "ACCOUNT_ENTITLEMENT"
                else str(normalized.get("actual_cost", row[1]))
            ),
            actual_tokens=int(normalized.get("actual_tokens", row[2])),
            evidence={
                **normalized,
                "reconciled": True,
                "cost_fallback_to_reservation": "actual_cost" not in normalized,
                "accounting_basis": accounting_basis,
                "cost_status": (
                    "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
                ),
            },
        )
    elif outcome in {"not_found", "failed_final", "cancelled"}:
        resolve_provider_budget_failure(
            database_url,
            reservation_id=str(row[0]),
            project_id=project_id,
        )


def resolve_external_effect_receipt_budget(
    database_url: str,
    *,
    project_id: str,
    effect_id: str,
    outcome: str,
    evidence: dict[str, Any],
) -> None:

    normalized = dict(evidence)
    usage = normalized.get("usage")
    cost = normalized.get("cost")
    if isinstance(usage, dict):
        normalized.setdefault(
            "actual_tokens",
            int(usage.get("total_tokens") or 0)
            or int(usage.get("input_tokens") or 0)
            + int(usage.get("output_tokens") or 0),
        )
    if isinstance(cost, dict):
        normalized.setdefault("actual_cost", str(cost.get("amount") or "0"))
    _resolve_reconciled_budget(
        database_url,
        project_id=project_id,
        effect_id=effect_id,
        outcome=("failed_final" if outcome == "final_failure" else outcome),
        evidence=normalized,
    )


def _require_project(row: dict[str, Any], project_id: str) -> None:
    if row["project_id"] != project_id:
        raise KernelError(
            "CROSS_PROJECT_REFERENCE", "external effect belongs to another project"
        )


def _record(
    repository: Any,
    context: EffectCommandContext,
    effect_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    repository.record_event(
        {
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
            "aggregate_type": "authority_external_effect",
            "aggregate_id": effect_id,
            "operation_id": context.operation_id,
            "project_id": context.project_id,
            "event_type": event_type,
            "correlation_id": context.correlation_id,
            "causation_id": context.causation_id,
            "payload": {
                **payload,
                "actor_id": context.actor_id,
                "trace_id": context.trace_id,
                "operation_id": context.operation_id,
            },
        }
    )


def _hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
