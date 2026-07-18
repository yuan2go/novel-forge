from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult

from .contracts import (
    ProviderCancellationRequest,
    ProviderCapabilityProfile,
    ProviderControlLevel,
    ProviderInvocationHandle,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderQueryRequest,
    ProviderReceipt,
)


class ScriptedProviderAdapterV2:
    """Protocol-only provider used for deterministic control-plane proofs."""

    provider = "scripted_provider_v2"
    reconciliation_mode = "query"
    capability_profile = ProviderCapabilityProfile(
        provider=provider,
        control_level=ProviderControlLevel.FIXTURE_CONTROLLED,
        supports_request_timeout=True,
        supports_provider_idempotency=True,
        supports_query=True,
        supports_cancel=True,
        supports_callback=True,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        reconciliation_mode="query",
        real_provider_validation_eligible=False,
    )

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.requests: dict[str, ProviderInvocationResult] = {}
        self.callbacks: dict[str, ProviderReceipt] = {}
        self.last_request: ProviderInvocationRequest | None = None
        self._lock = Lock()

    def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResult:
        self.last_request = request
        with self._lock:
            existing = self.requests.get(request.stable_idempotency_key)
            if existing is not None:
                return ProviderInvocationResult(
                    existing.outcome,
                    existing.handle,
                    {**existing.evidence, "replayed": True},
                    existing.request_sent,
                )
            if self.scenario in {"retryable_failure_before_send", "timeout_before_send"}:
                return ProviderInvocationResult(
                    "retryable_failure", None,
                    {"timeout": self.scenario.startswith("timeout"), "request_sent": False},
                    False,
                )
            handle = ProviderInvocationHandle(
                provider_request_id=f"scripted-request:{request.stable_idempotency_key}",
                provider_correlation_id=f"scripted-correlation:{request.correlation_id}",
                accepted_at=datetime.now(timezone.utc).isoformat(),
                completion_mode="synchronous" if self.scenario == "success" else "poll",
                query_supported=True,
                cancel_supported=True,
                callback_supported=True,
                idempotency_supported=True,
            )
            outcome = {
                "success": "success",
                "unknown_after_send": "unknown",
                "timeout_after_send": "unknown",
                "provider_cost_overrun": "success",
                "provider_token_mismatch": "success",
            }.get(self.scenario, "unknown")
            evidence = {
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
                "request_hash": request.request_hash,
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "cost": {"amount": "999" if self.scenario == "provider_cost_overrun" else "0", "currency": "USD"},
                "result": self._result_for(request),
            }
            result = ProviderInvocationResult(outcome, handle, evidence, True)
            self.requests[request.stable_idempotency_key] = result
            return result

    @staticmethod
    def _result_for(request: ProviderInvocationRequest) -> dict[str, Any]:
        if request.stage == "draft":
            return {"text": "Scripted chapter fixture."}
        if request.stage == "review":
            return {"score": 90, "issues": []}
        if request.stage == "canon_extraction":
            return {
                "canon_facts": [{"fact": "scripted fixture", "evidence_start": 0, "evidence_end": 8, "confidence": 1.0}],
                "character_state_changes": [], "relationship_changes": [],
                "timeline_events": [], "foreshadow_changes": [],
                "promise_changes": [], "reward_changes": [],
                "world_rule_usages": [], "power_state_changes": [],
                "narrative_pattern_fingerprints": [], "theme_movements": [],
                "antagonist_pressure_changes": [],
            }
        if request.stage.startswith("quality_"):
            inputs = request.request_payload.get("input")
            dimensions = inputs.get("dimensions", []) if isinstance(inputs, dict) else []
            return {
                "dimensions": [
                    {
                        "dimension": str(dimension),
                        "gate_status": "INSUFFICIENT_EVIDENCE",
                        "score": None,
                        "confidence": 0.0,
                        "evidence_locations": [],
                        "issue_codes": ["FIXTURE_PROTOCOL_ONLY"],
                        "revision_strategies": [],
                    }
                    for dimension in dimensions
                ]
            }
        return {"text": "Scripted revision fixture.", "resolved_issue_codes": []}

    def query_v2(self, request: ProviderQueryRequest) -> ProviderInvocationResult:
        with self._lock:
            existing = self.requests.get(request.stable_idempotency_key)
        if self.scenario == "query_not_found" or existing is None:
            return ProviderInvocationResult("not_found", None, {"found": False}, False)
        if self.scenario == "query_ambiguous":
            return ProviderInvocationResult("ambiguous", existing.handle, {"ambiguous": True}, True)
        return ProviderInvocationResult("success", existing.handle, {**existing.evidence, "queried": True}, True)

    def cancel_v2(self, request: ProviderCancellationRequest) -> ProviderInvocationResult:
        with self._lock:
            existing = self.requests.get(request.stable_idempotency_key)
        if self.scenario == "cancel_unsupported":
            return ProviderInvocationResult("ambiguous", existing.handle if existing else None, {"manual_resolution_required": True}, bool(existing))
        if self.scenario == "cancel_already_completed":
            return ProviderInvocationResult("already_completed", existing.handle if existing else None, {"completed": True}, bool(existing))
        return ProviderInvocationResult("cancelled", existing.handle if existing else None, {"cancelled": True}, bool(existing))

    def accept_callback(self, receipt: ProviderReceipt) -> ProviderReceipt:
        with self._lock:
            existing = self.callbacks.get(receipt.message_id)
            if existing is not None:
                if existing.payload_hash != receipt.payload_hash or existing.outcome != receipt.outcome:
                    raise ValueError("conflicting callback receipt")
                return existing
            self.callbacks[receipt.message_id] = receipt
            return receipt

    # Generic ExternalEffect compatibility surface.  It preserves the v2
    # request identity instead of dropping the stable provider key.
    def execute(self, *, stable_idempotency_key: str, capability: str, request_payload: dict[str, Any]) -> ProviderResult:
        request = ProviderInvocationRequest(
            provider=self.provider,
            model=str(request_payload.get("model_id") or "scripted-model"),
            capability=capability,
            stage=str(request_payload.get("stage") or capability),
            stable_idempotency_key=stable_idempotency_key,
            request_payload=request_payload,
            request_hash=str(request_payload.get("request_hash") or f"scripted:{stable_idempotency_key}"),
            timeout_seconds=int(request_payload.get("timeout_seconds") or 30),
            trace_id=str(request_payload.get("trace_id") or "scripted-trace"),
            correlation_id=str(request_payload.get("correlation_id") or "scripted-correlation"),
            operation_id=str(request_payload.get("operation_id") or "scripted-operation"),
            external_effect_id=str(request_payload.get("external_effect_id") or "scripted-effect"),
            budget_reservation_id=str(request_payload.get("budget_reservation_id") or ""),
        )
        result = self.invoke(request)
        handle = result.handle
        return ProviderResult(
            result.outcome,
            "" if handle is None else handle.provider_correlation_id,
            result.evidence,
            "" if handle is None else handle.provider_request_id,
        )

    def query(self, *, stable_idempotency_key: str, capability: str, request_payload: dict[str, Any]) -> ProviderResult:
        del capability
        result = self.query_v2(ProviderQueryRequest(
            provider_request_id=str(request_payload.get("provider_request_id") or ""),
            stable_idempotency_key=stable_idempotency_key,
            trace_id=str(request_payload.get("trace_id") or "scripted-trace"),
            correlation_id=str(request_payload.get("correlation_id") or "scripted-correlation"),
        ))
        handle = result.handle
        return ProviderResult(result.outcome, "" if handle is None else handle.provider_correlation_id, result.evidence, "" if handle is None else handle.provider_request_id)

    def cancel(self, *, stable_idempotency_key: str, capability: str, request_payload: dict[str, Any], provider_request_id: str) -> ProviderResult:
        del capability
        result = self.cancel_v2(ProviderCancellationRequest(
            provider_request_id=provider_request_id,
            stable_idempotency_key=stable_idempotency_key,
            reason=str(request_payload.get("cancel_reason") or "authority cancellation"),
            trace_id=str(request_payload.get("trace_id") or "scripted-trace"),
            correlation_id=str(request_payload.get("correlation_id") or "scripted-correlation"),
        ))
        handle = result.handle
        return ProviderResult(result.outcome, "" if handle is None else handle.provider_correlation_id, result.evidence, "" if handle is None else handle.provider_request_id)
