"""Database-fenced ExternalEffect dispatcher, receipt inbox, and reconciliation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.deadline_runtime import probe_external_effect_execution
from novel_forge.modules.command_kernel.attempt_runtime import _cas_operation
from novel_forge.modules.command_kernel.budget_runtime import (
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
    ExternalEffectAdapterError,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
    ProviderControlLevel,
    capability_profile_from_dict,
)
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
        raise KernelError("COMMAND_SCHEMA_INVALID", "external effect intent is incomplete")
    if completion_policy not in {
        "synchronous_final",
        "async_ack",
        "callback_receipt",
        "poll_reconciliation",
    }:
        raise KernelError("EFFECT_COMPLETION_POLICY_INVALID", "unknown completion policy")
    if reconciliation_mode not in {"query", "callback", "unsupported"}:
        raise KernelError("EFFECT_RECONCILIATION_MODE_INVALID", "unknown reconciliation mode")
    if request_timeout_seconds is not None and request_timeout_seconds <= 0:
        raise KernelError("EFFECT_TIMEOUT_POLICY_INVALID", "effect timeout must be positive")
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
                    if capability_profile else ProviderControlLevel.LEGACY_UNCONTROLLED.value
                ),
                "provider_idempotency_mode": (
                    "provider" if capability_profile.get("supports_provider_idempotency") else "unsupported"
                ),
                "provider_query_mode": (
                    "query" if capability_profile.get("supports_query") else "unsupported"
                ),
                "provider_cancel_mode": (
                    "cancel" if capability_profile.get("supports_cancel") else "unsupported"
                ),
                "provider_callback_mode": (
                    "callback" if capability_profile.get("supports_callback") else "unsupported"
                ),
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
    effect = _read_effect(database_url, effect_id, context.project_id)
    if adapter.provider != effect["provider"]:
        raise KernelError(
            "EFFECT_PROVIDER_CONFLICT",
            "adapter provider differs from the frozen effect intent",
        )
    _validate_frozen_adapter_capability(effect, adapter)
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
                "message": str(exc),
                "request_sent": False,
                "timeout_phase": "before_send",
            },
        )
        raise KernelError(
            "EFFECT_REQUEST_TIMEOUT_BEFORE_SEND",
            "Provider request deadline expired before dispatch",
        ) from exc
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
            provider_result = adapter.execute(
                stable_idempotency_key=effect["stable_idempotency_key"],
                capability=effect["capability"],
                request_payload={
                    **effect["request_payload"],
                    "external_effect_id": effect["external_effect_id"],
                    "operation_id": effect["operation_id"],
                    "request_hash": effect["request_hash"],
                    "timeout_seconds": int(
                        effect.get("request_timeout_seconds") or 30
                    ),
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
                "message": str(exc),
                "request_sent": exc.request_sent,
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
        submit_effect_dispatch_result(
            database_url,
            context,
            dispatch_id=dispatch["dispatch_id"],
            worker_id=worker_id,
            fencing_token=lease["fencing_token"],
            outcome="unknown",
            evidence={
                "error_type": type(exc).__name__,
                "message": str(exc),
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
                {"message_id": message_id, "receipt_id": receipt_id, "outcome": outcome},
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
) -> dict[str, Any]:
    effect = _read_effect(database_url, effect_id, context.project_id)
    if effect["status"] not in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
        raise KernelError("EFFECT_STATUS_CONFLICT", "effect does not require reconciliation")
    if adapter.provider != effect["provider"]:
        raise KernelError("EFFECT_PROVIDER_CONFLICT", "reconciler provider is unexpected")
    if effect.get("reconciliation_mode") == "unsupported":
        raise KernelError(
            "EFFECT_RECONCILIATION_UNSUPPORTED",
            "provider cannot be queried; manual resolution is required",
        )
    _validate_frozen_adapter_capability(effect, adapter)

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

    if result.outcome not in {"success", "not_found", "ambiguous", "failed_final", "cancelled"}:
        raise KernelError("RECONCILIATION_OUTCOME_INVALID", "provider query is inconclusive")
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
            uow.repositories.asset_blobs.mark_upload_unknown(blob_id, context.project_id)
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
            raise KernelError("EFFECT_PROVIDER_CONFLICT", "cancellation adapter is unexpected")
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
            "cancelled", "already_completed", "unsupported", "ambiguous"
        }:
            raise KernelError("EFFECT_CANCEL_OUTCOME_INVALID", "provider cancel outcome is invalid")
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
            "external_effect.cancelled" if target == "CANCELLED" else "external_effect.cancel_coordinated",
            {
                "status": target,
                "provider_cancel_outcome": (
                    provider_result.outcome if provider_result is not None else "not_dispatched"
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
    """Propagate a root cancel to every non-terminal effect using its real adapter."""
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
                    operation_id=str(operation_id), project_id=project_id,
                    actor_id=actor_id, trace_id=trace_id,
                    correlation_id=correlation_id, causation_id=root_operation_id,
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
        raise KernelError("EFFECT_NOT_REVERSIBLE", "external effect has no compensation protocol")
    if effect["status"] not in {"SUCCEEDED", "COMPENSATION_REQUIRED"}:
        raise KernelError("EFFECT_STATUS_CONFLICT", "external effect is not compensatable")
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
        raise KernelError("COMMAND_SCHEMA_INVALID", "effect command context is incomplete")


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
            SELECT reservation_id, reserved_amount, estimated_tokens
            FROM authority_budget_reservation
            WHERE external_effect_id=%s AND project_id=%s
              AND status IN ('RESERVED','HELD_UNKNOWN')
            ORDER BY created_at DESC LIMIT 1
            """,
            [effect_id, project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return
    if outcome == "success":
        settle_provider_budget(
            database_url,
            reservation_id=str(row[0]),
            project_id=project_id,
            actual_amount=str(evidence.get("actual_cost") or row[1]),
            actual_tokens=int(evidence.get("actual_tokens") or row[2]),
            evidence={
                **evidence,
                "reconciled": True,
                "cost_fallback_to_reservation": "actual_cost" not in evidence,
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
    """Public idempotent settlement seam for verified callback receipts."""

    normalized = dict(evidence)
    usage = normalized.get("usage")
    cost = normalized.get("cost")
    if isinstance(usage, dict):
        normalized.setdefault(
            "actual_tokens",
            int(usage.get("total_tokens") or 0)
            or int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0),
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
