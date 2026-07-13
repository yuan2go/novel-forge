"""Database-fenced ExternalEffect dispatcher, receipt inbox, and reconciliation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import ExternalEffectAdapter
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class EffectCommandContext:
    operation_id: str
    project_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""


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
) -> dict[str, Any]:
    if max_attempts <= 0 or not all(
        (effect_type, provider, capability, stable_idempotency_key)
    ):
        raise KernelError("COMMAND_SCHEMA_INVALID", "external effect intent is incomplete")
    request_hash = _hash(request_payload)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        result = repository.plan(
            {
                "external_effect_id": str(uuid4()),
                "operation_id": context.operation_id,
                "effect_type": effect_type,
                "stable_idempotency_key": stable_idempotency_key,
                "request_hash": request_hash,
                "request_payload": request_payload,
                "provider": provider,
                "capability": capability,
                "max_attempts": max_attempts,
                "reversible": reversible,
            }
        )
        if not result["replayed"]:
            _record(
                repository,
                context,
                result["external_effect_id"],
                "external_effect.planned",
                {"effect_type": effect_type, "provider": provider, "capability": capability},
            )
        uow.commit()
    return result


def prepare_effect_dispatch(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        effect = repository.get_for_update(effect_id)
        _require_project(effect, context.project_id)
        result = repository.prepare_dispatch(effect, str(uuid4()))
        if not result["replayed"]:
            _record(
                repository,
                context,
                effect_id,
                "external_effect.dispatch_prepared",
                {"dispatch_id": result["dispatch_id"], "generation": result["generation"]},
            )
        uow.commit()
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
) -> dict[str, Any]:
    dispatch = prepare_effect_dispatch(database_url, context, effect_id=effect_id)
    lease = acquire_effect_dispatch(
        database_url,
        context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    effect = _read_effect(database_url, effect_id, context.project_id)
    if adapter.provider != effect["provider"]:
        raise KernelError(
            "EFFECT_PROVIDER_CONFLICT",
            "adapter provider differs from the frozen effect intent",
        )

    provider_result = adapter.execute(
        stable_idempotency_key=effect["stable_idempotency_key"],
        capability=effect["capability"],
        request_payload=effect["request_payload"],
    )

    outcome = submit_effect_dispatch_result(
        database_url,
        context,
        dispatch_id=dispatch["dispatch_id"],
        worker_id=worker_id,
        fencing_token=lease["fencing_token"],
        outcome=provider_result.outcome,
        evidence=provider_result.evidence,
        provider_correlation_id=provider_result.provider_correlation_id,
    )
    return {"dispatch_id": dispatch["dispatch_id"], "outcome": outcome}


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
        raise KernelError("COMMAND_SCHEMA_INVALID", "effect lease duration must be positive")
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
        _require_context(repository, context)
        dispatch = repository.dispatch_for_update(dispatch_id)
        _require_project(dispatch, context.project_id)
        if provider != dispatch["provider"]:
            raise KernelError("RECEIPT_PROVIDER_CONFLICT", "receipt provider is unexpected")
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
            _record(
                repository,
                context,
                dispatch["external_effect_id"],
                "external_effect.receipt_accepted",
                {"message_id": message_id, "receipt_id": receipt_id, "outcome": outcome},
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
) -> dict[str, Any]:
    effect = _read_effect(database_url, effect_id, context.project_id)
    if effect["status"] not in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
        raise KernelError("EFFECT_STATUS_CONFLICT", "effect does not require reconciliation")
    if adapter.provider != effect["provider"]:
        raise KernelError("EFFECT_PROVIDER_CONFLICT", "reconciler provider is unexpected")

    result = adapter.query(
        stable_idempotency_key=effect["stable_idempotency_key"],
        capability=effect["capability"],
        request_payload=effect["request_payload"],
    )

    if result.outcome not in {"success", "not_found", "ambiguous", "failed_final"}:
        raise KernelError("RECONCILIATION_OUTCOME_INVALID", "provider query is inconclusive")
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        current = repository.get_for_update(effect_id)
        _require_project(current, context.project_id)
        repository.record_reconciliation(
            {
                "reconciliation_id": str(uuid4()),
                "external_effect_id": effect_id,
                "provider": effect["provider"],
                "stable_idempotency_key": effect["stable_idempotency_key"],
                "outcome": result.outcome,
                "evidence": {
                    **result.evidence,
                    "provider_correlation_id": result.provider_correlation_id,
                },
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
        uow.commit()
    return {"external_effect_id": effect_id, "outcome": result.outcome}


def cancel_external_effect(
    database_url: str,
    context: EffectCommandContext,
    *,
    effect_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.external_effects
        _require_context(repository, context)
        effect = repository.get_for_update(effect_id)
        _require_project(effect, context.project_id)
        target = repository.cancel(effect)
        _record(
            repository,
            context,
            effect_id,
            "external_effect.cancelled" if target == "CANCELLED" else "external_effect.cancel_coordinated",
            {"status": target},
        )
        uow.commit()
    return {"external_effect_id": effect_id, "status": target}


def _read_effect(database_url: str, effect_id: str, project_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        effect = uow.repositories.external_effects.get_for_update(effect_id)
        _require_project(effect, project_id)
        return effect


def _require_context(repository: Any, context: EffectCommandContext) -> None:
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
        raise KernelError("COMMAND_SCHEMA_INVALID", "effect command context is incomplete")
    repository.require_operation(context.operation_id, context.project_id)


def _require_project(row: dict[str, Any], project_id: str) -> None:
    if row["project_id"] != project_id:
        raise KernelError("CROSS_PROJECT_REFERENCE", "external effect belongs to another project")


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
