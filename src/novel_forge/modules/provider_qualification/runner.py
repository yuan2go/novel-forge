from __future__ import annotations

from dataclasses import asdict
import json
import os
from typing import Mapping

from novel_forge.modules.provider_control import (
    ProviderCancellationRequest,
    ProviderInvocationRequest,
    ProviderQueryRequest,
    ProviderReceipt,
    ScriptedProviderAdapterV2,
)

from .domain import D0_GATE_NAMES, D0ProbeConfig, D0ProbeReport, request_hash


def _request(
    *, provider: str, model: str, timeout_seconds: int, stable_key: str
) -> ProviderInvocationRequest:
    payload = {
        "schema_version": "d0-structured-echo.v1",
        "instruction": "Return one JSON object with ok=true and probe='d0'.",
    }
    return ProviderInvocationRequest(
        provider=provider,
        model=model,
        capability="structured.echo",
        stage="d0_qualification",
        stable_idempotency_key=stable_key,
        request_payload=payload,
        request_hash=request_hash(payload),
        timeout_seconds=timeout_seconds,
        trace_id="trace:d0-provider-qualification",
        correlation_id="correlation:d0-provider-qualification",
        operation_id="operation:d0-provider-qualification",
        external_effect_id="external-effect:d0-provider-qualification",
        budget_reservation_id="budget:d0-provider-qualification",
    )


def run_fixture_protocol_probe(config: D0ProbeConfig) -> D0ProbeReport:
    stable_key = "d0-fixture-stable-key"
    unknown_adapter = ScriptedProviderAdapterV2("unknown_after_send")
    initial = unknown_adapter.invoke(
        _request(
            provider=unknown_adapter.provider,
            model="fixture-model",
            timeout_seconds=config.timeout_seconds,
            stable_key=stable_key,
        )
    )
    assert initial.handle is not None
    queried = unknown_adapter.query_v2(
        ProviderQueryRequest(
            provider_request_id=initial.handle.provider_request_id,
            stable_idempotency_key=stable_key,
            trace_id="trace:d0-provider-qualification",
            correlation_id="correlation:d0-provider-qualification",
        )
    )
    cancelled = unknown_adapter.cancel_v2(
        ProviderCancellationRequest(
            provider_request_id=initial.handle.provider_request_id,
            stable_idempotency_key=stable_key,
            reason="D0 cancel behavior probe",
            trace_id="trace:d0-provider-qualification",
            correlation_id="correlation:d0-provider-qualification",
        )
    )
    receipt = ProviderReceipt(
        provider_request_id=initial.handle.provider_request_id,
        receipt_id="fixture-receipt:d0",
        message_id="fixture-message:d0",
        outcome="success",
        payload_hash="sha256:" + "f" * 64,
        evidence={"late_result": True, "fixture_protocol_only": True},
    )
    first_receipt = unknown_adapter.accept_callback(receipt)
    duplicate_receipt = unknown_adapter.accept_callback(receipt)
    timeout_before = ScriptedProviderAdapterV2("timeout_before_send").invoke(
        _request(
            provider="scripted_provider_v2",
            model="fixture-model",
            timeout_seconds=1,
            stable_key="d0-timeout-before",
        )
    )
    timeout_after = ScriptedProviderAdapterV2("timeout_after_send").invoke(
        _request(
            provider="scripted_provider_v2",
            model="fixture-model",
            timeout_seconds=1,
            stable_key="d0-timeout-after",
        )
    )
    restart_snapshot = json.loads(
        json.dumps(
            {
                "provider_request_id": initial.handle.provider_request_id,
                "stable_idempotency_key": stable_key,
                "outcome": initial.outcome,
            },
            sort_keys=True,
        )
    )
    raw_usage = dict(initial.evidence["usage"])
    normalized_usage = {
        **raw_usage,
        "total_tokens": int(raw_usage["input_tokens"]) + int(raw_usage["output_tokens"]),
    }
    checks = {
        "authentication_contract": config.auth_secret_ref.startswith("env://"),
        "request_id": bool(initial.handle.provider_request_id),
        "timeout_before_send_retryable": timeout_before.outcome == "retryable_failure" and not timeout_before.request_sent,
        "timeout_after_send_unknown": timeout_after.outcome == "unknown" and timeout_after.request_sent,
        "query_reconciles_unknown": initial.outcome == "unknown" and queried.outcome == "success",
        "cancel_behavior": cancelled.outcome == "cancelled",
        "usage_normalization": normalized_usage["total_tokens"] == 15,
        "cost_contract": initial.evidence["cost"]["currency"] == "USD",
        "duplicate_receipt_idempotent": first_receipt is duplicate_receipt,
        "late_result_recorded": bool(first_receipt.evidence["late_result"]),
        "restart_state_serializable": restart_snapshot["provider_request_id"] == initial.handle.provider_request_id,
    }
    return D0ProbeReport(
        status="BLOCKED_MISSING_CREDENTIALS",
        blocker="Fixture contract passed; no real Provider credential/model/SDK evidence was used.",
        provider=config.provider,
        backend_id=config.backend_id,
        model="fixture-model",
        model_version="fixture",
        route_policy_version=config.route_policy_version,
        timeout_seconds=config.timeout_seconds,
        cancel_capability="fixture_verified",
        query_capability="fixture_verified",
        provider_request_id=initial.handle.provider_request_id,
        raw_usage=raw_usage,
        normalized_usage=normalized_usage,
        provider_cost=dict(initial.evidence["cost"]),
        calculated_cost={"amount": "0", "currency": "USD", "source": "fixture"},
        receipt=asdict(first_receipt),
        request_object_ref="fixture://d0/request",
        response_object_ref="fixture://d0/response",
        contract_checks=checks,
        gates={name: False for name in D0_GATE_NAMES},
        fixture_protocol_only=True,
        external_execution_proven=False,
    )


def run_d0_probe(
    config: D0ProbeConfig, *, env: Mapping[str, str] | None = None
) -> D0ProbeReport:
    values = os.environ if env is None else env
    api_key = str(values.get(config.auth_environment_name) or "").strip()
    model = str(values.get(config.model_env) or "").strip()
    model_version = str(values.get(config.model_version_env) or "").strip()
    if not api_key:
        return run_fixture_protocol_probe(config)
    fixture = run_fixture_protocol_probe(config)
    return D0ProbeReport(
        **{
            **fixture.to_dict(),
            "status": "BLOCKED_CONFIGURATION",
            "blocker": (
                "Credentialed execution is forbidden in the contract probe; use "
                "the PostgreSQL Provider Qualification Authority runner."
            ),
            "model": model or "configured-model-not-called",
            "model_version": model_version or "provider-not-called",
        }
    )


__all__ = ["run_d0_probe", "run_fixture_protocol_probe"]
