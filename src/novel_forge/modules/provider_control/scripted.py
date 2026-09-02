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
            if self.scenario in {
                "retryable_failure_before_send",
                "timeout_before_send",
            }:
                return ProviderInvocationResult(
                    "retryable_failure",
                    None,
                    {
                        "timeout": self.scenario.startswith("timeout"),
                        "request_sent": False,
                    },
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
                "cost": {
                    "amount": "999"
                    if self.scenario == "provider_cost_overrun"
                    else "0",
                    "currency": "USD",
                },
                "result": self._result_for(request),
            }
            result = ProviderInvocationResult(outcome, handle, evidence, True)
            self.requests[request.stable_idempotency_key] = result
            return result

    @staticmethod
    def _result_for(request: ProviderInvocationRequest) -> dict[str, Any]:
        if request.stage == "retrieval_query_expansion":
            inputs = request.request_payload.get("input")
            inputs = inputs if isinstance(inputs, dict) else {}
            coverage = dict(inputs.get("coverage") or {})
            boundary = int(
                dict(inputs.get("accepted_boundary") or {}).get(
                    "accepted_through_chapter"
                )
                or 0
            )
            prefixes = {
                "fact_ids": "fact",
                "historical_reference_ids": "history",
                "relationship_ids": "relationship",
                "arc_plan_version_ids": "arc",
                "obligation_ids": "obligation",
            }
            queries = [
                {
                    "query_id": f"scripted-query:{index}",
                    "text": str(identity),
                    "reason": "scripted Provider protocol exercises one governed gap",
                    "targets": [f"{prefixes[str(dimension)]}:{identity}"],
                    "selectors": {},
                    "temporal_range": {
                        "from_chapter": 0,
                        "to_chapter": boundary,
                    },
                }
                for index, (dimension, identity) in enumerate(
                    (
                        (dimension, identity)
                        for dimension, identities in dict(
                            coverage.get("missing") or {}
                        ).items()
                        for identity in identities or ()
                    ),
                    start=1,
                )
            ][:4]
            return {
                "contract_version": "retrieval-expansion-plan-v1",
                "queries": queries,
            }
        if request.stage == "draft":
            marker = str(
                request.request_payload.get("capability_pack_fixture_marker") or ""
            )
            return {
                "text": (
                    f"Scripted chapter fixture [{marker}]."
                    if marker
                    else "Scripted chapter fixture."
                )
            }
        if request.stage == "review":
            return {"score": 90, "issues": []}
        if request.stage == "canon_extraction":
            inputs = request.request_payload.get("input")
            inputs = inputs if isinstance(inputs, dict) else {}
            expectations = inputs.get("execution_expectations")
            expectations = expectations if isinstance(expectations, dict) else {}
            realization = expectations.get("narrative_realization")
            realization = realization if isinstance(realization, dict) else {}
            events = realization.get("events")
            events = events if isinstance(events, list) else []
            return {
                "canon_facts": [
                    {
                        "fact": "scripted fixture",
                        "evidence_start": 0,
                        "evidence_end": 8,
                        "confidence": 1.0,
                    }
                ],
                "character_state_changes": [],
                "relationship_changes": [],
                "timeline_events": [],
                "foreshadow_changes": [],
                "promise_changes": [],
                "reward_changes": [],
                "world_rule_usages": [],
                "power_state_changes": [],
                "plot_thread_changes": [],
                "resource_state_changes": [],
                "narrative_pattern_fingerprints": [],
                "theme_movements": [],
                "antagonist_pressure_changes": [],
                "character_knowledge_changes": [],
                "character_belief_changes": [],
                "character_arc_changes": [],
                "arc_state_changes": [],
                "disclosure_events": [],
                "arc_evidence": [],
                "realization_evidence": [
                    {
                        "planned_event_id": str(event.get("event_id") or ""),
                        "observed_event_id": f"observed:{event.get('event_id')}",
                        "observation_status": "OBSERVED",
                        "accepted_prose_evidence": [
                            {
                                "start": 0,
                                "end": 8,
                                "summary": (
                                    "scripted fixture prose realizes the frozen event"
                                ),
                            }
                        ],
                        "observed_consequence": str(
                            event.get("consequence") or "the planned consequence occurs"
                        ),
                        "observed_action": str(event.get("action") or "planned action"),
                        "observed_decision": str(
                            event.get("decision") or "planned decision"
                        ),
                        "observed_cause_event_ids": list(event.get("causes") or ()),
                        "observed_disclosures": list(event.get("disclosures") or ()),
                        "observed_state_deltas": [
                            dict(delta)
                            for delta in event.get("state_deltas") or ()
                            if isinstance(delta, dict)
                        ],
                        "observed_state_event_ids": [
                            str(delta.get("entity_id") or "")
                            for delta in event.get("state_deltas") or ()
                            if isinstance(delta, dict)
                            and str(delta.get("entity_id") or "")
                        ],
                    }
                    for event in events
                    if isinstance(event, dict) and str(event.get("event_id") or "")
                ],
            }
        if request.stage.startswith("quality_"):
            inputs = request.request_payload.get("input")
            dimensions = (
                inputs.get("dimensions", []) if isinstance(inputs, dict) else []
            )
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
        if existing is None and request.provider_request_id == (
            f"scripted-request:{request.stable_idempotency_key}"
        ):
            handle = ProviderInvocationHandle(
                provider_request_id=request.provider_request_id,
                provider_correlation_id=f"scripted-correlation:{request.correlation_id}",
                accepted_at=datetime.now(timezone.utc).isoformat(),
                completion_mode="poll",
                query_supported=True,
                cancel_supported=True,
                callback_supported=True,
                idempotency_supported=True,
            )
            existing = ProviderInvocationResult(
                "unknown",
                handle,
                {
                    "fixture_protocol_only": True,
                    "real_model_call": False,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "cost": {"amount": "0", "currency": "USD", "source": "fixture"},
                    "result": {"ok": True, "probe": "d0"},
                    "recovered_without_resend": True,
                },
                True,
            )
        if self.scenario == "query_not_found" or existing is None:
            return ProviderInvocationResult("not_found", None, {"found": False}, False)
        if self.scenario == "query_ambiguous":
            return ProviderInvocationResult(
                "ambiguous", existing.handle, {"ambiguous": True}, True
            )
        return ProviderInvocationResult(
            "success", existing.handle, {**existing.evidence, "queried": True}, True
        )

    def cancel_v2(
        self, request: ProviderCancellationRequest
    ) -> ProviderInvocationResult:
        with self._lock:
            existing = self.requests.get(request.stable_idempotency_key)
        if self.scenario == "cancel_unsupported":
            return ProviderInvocationResult(
                "ambiguous",
                existing.handle if existing else None,
                {"manual_resolution_required": True},
                bool(existing),
            )
        if self.scenario == "cancel_already_completed":
            return ProviderInvocationResult(
                "already_completed",
                existing.handle if existing else None,
                {"completed": True},
                bool(existing),
            )
        return ProviderInvocationResult(
            "cancelled",
            existing.handle if existing else None,
            {"cancelled": True},
            bool(existing),
        )

    def accept_callback(self, receipt: ProviderReceipt) -> ProviderReceipt:
        with self._lock:
            existing = self.callbacks.get(receipt.message_id)
            if existing is not None:
                if (
                    existing.payload_hash != receipt.payload_hash
                    or existing.outcome != receipt.outcome
                ):
                    raise ValueError("conflicting callback receipt")
                return existing
            self.callbacks[receipt.message_id] = receipt
            return receipt

    # COMPATIBILITY: preserve the stable provider key on the ExternalEffect
    # request identity.
    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        request = ProviderInvocationRequest(
            provider=self.provider,
            model=str(request_payload.get("model_id") or "scripted-model"),
            capability=capability,
            stage=str(request_payload.get("stage") or capability),
            stable_idempotency_key=stable_idempotency_key,
            request_payload=request_payload,
            request_hash=str(
                request_payload.get("request_hash")
                or f"scripted:{stable_idempotency_key}"
            ),
            timeout_seconds=int(request_payload.get("timeout_seconds") or 30),
            trace_id=str(request_payload.get("trace_id") or "scripted-trace"),
            correlation_id=str(
                request_payload.get("correlation_id") or "scripted-correlation"
            ),
            operation_id=str(
                request_payload.get("operation_id") or "scripted-operation"
            ),
            external_effect_id=str(
                request_payload.get("external_effect_id") or "scripted-effect"
            ),
            budget_reservation_id=str(
                request_payload.get("budget_reservation_id") or ""
            ),
        )
        result = self.invoke(request)
        handle = result.handle
        return ProviderResult(
            result.outcome,
            "" if handle is None else handle.provider_correlation_id,
            result.evidence,
            "" if handle is None else handle.provider_request_id,
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        del capability
        result = self.query_v2(
            ProviderQueryRequest(
                provider_request_id=str(
                    request_payload.get("provider_request_id") or ""
                ),
                stable_idempotency_key=stable_idempotency_key,
                trace_id=str(request_payload.get("trace_id") or "scripted-trace"),
                correlation_id=str(
                    request_payload.get("correlation_id") or "scripted-correlation"
                ),
            )
        )
        handle = result.handle
        return ProviderResult(
            result.outcome,
            "" if handle is None else handle.provider_correlation_id,
            result.evidence,
            "" if handle is None else handle.provider_request_id,
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability
        result = self.cancel_v2(
            ProviderCancellationRequest(
                provider_request_id=provider_request_id,
                stable_idempotency_key=stable_idempotency_key,
                reason=str(
                    request_payload.get("cancel_reason") or "authority cancellation"
                ),
                trace_id=str(request_payload.get("trace_id") or "scripted-trace"),
                correlation_id=str(
                    request_payload.get("correlation_id") or "scripted-correlation"
                ),
            )
        )
        handle = result.handle
        return ProviderResult(
            result.outcome,
            "" if handle is None else handle.provider_correlation_id,
            result.evidence,
            "" if handle is None else handle.provider_request_id,
        )
