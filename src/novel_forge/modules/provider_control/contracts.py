from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ProviderControlLevel(StrEnum):
    V2_CONTROLLED = "V2_CONTROLLED"
    FIXTURE_CONTROLLED = "FIXTURE_CONTROLLED"
    LEGACY_UNCONTROLLED = "LEGACY_UNCONTROLLED"


@dataclass(frozen=True, slots=True)
class ProviderCapabilityProfile:
    provider: str
    control_level: ProviderControlLevel
    supports_request_timeout: bool
    supports_provider_idempotency: bool
    supports_query: bool
    supports_cancel: bool
    supports_callback: bool
    supports_usage_receipt: bool
    supports_cost_receipt: bool
    reconciliation_mode: str
    real_provider_validation_eligible: bool
    contract_version: str = "provider-capability-v2"

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provider capability profile requires provider identity")
        if self.reconciliation_mode not in {"query", "callback", "unsupported"}:
            raise ValueError("provider reconciliation mode is invalid")
        if self.supports_query != (self.reconciliation_mode == "query"):
            if self.reconciliation_mode != "callback":
                raise ValueError("query capability and reconciliation mode disagree")
        if self.real_provider_validation_eligible:
            if self.control_level is not ProviderControlLevel.V2_CONTROLLED:
                raise ValueError("only a v2-controlled adapter can validate a real provider")
            if not self.supports_request_timeout:
                raise ValueError("real provider validation requires an SDK request timeout")
            if not self.supports_provider_idempotency:
                raise ValueError("real provider validation requires provider-side idempotency")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["control_level"] = self.control_level.value
        return payload


@dataclass(frozen=True, slots=True)
class ProviderInvocationRequest:
    provider: str
    model: str
    capability: str
    stage: str
    stable_idempotency_key: str
    request_payload: dict[str, Any]
    request_hash: str
    timeout_seconds: int
    trace_id: str
    correlation_id: str
    operation_id: str
    external_effect_id: str
    budget_reservation_id: str = ""
    provider_admission: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        required = (
            self.provider, self.capability, self.stage,
            self.stable_idempotency_key, self.request_hash,
            self.trace_id, self.correlation_id,
            self.operation_id, self.external_effect_id,
        )
        if not all(required) or self.timeout_seconds <= 0:
            raise ValueError("provider invocation request is incomplete")
        if self.provider_admission is not None and not isinstance(
            self.provider_admission, dict
        ):
            raise ValueError("provider admission receipt must be an object")


@dataclass(frozen=True, slots=True)
class ProviderInvocationHandle:
    provider_request_id: str
    provider_correlation_id: str
    accepted_at: str
    completion_mode: str
    query_supported: bool
    cancel_supported: bool
    callback_supported: bool
    idempotency_supported: bool


@dataclass(frozen=True, slots=True)
class ProviderInvocationResult:
    outcome: str
    handle: ProviderInvocationHandle | None
    evidence: dict[str, Any]
    request_sent: bool

    def __post_init__(self) -> None:
        if self.outcome not in {
            "success", "retryable_failure", "final_failure", "unknown",
            "not_found", "ambiguous", "cancelled", "already_completed",
        }:
            raise ValueError("provider invocation outcome is invalid")
        if self.request_sent and self.handle is None:
            raise ValueError("a sent provider request requires a provider request handle")
        if self.handle is not None and not self.handle.provider_request_id:
            raise ValueError("provider request ID is required after submission")


@dataclass(frozen=True, slots=True)
class ProviderQueryRequest:
    provider_request_id: str
    stable_idempotency_key: str
    trace_id: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ProviderCancellationRequest:
    provider_request_id: str
    stable_idempotency_key: str
    reason: str
    trace_id: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    provider_request_id: str
    receipt_id: str
    message_id: str
    outcome: str
    payload_hash: str
    evidence: dict[str, Any]


def capability_profile_from_dict(payload: dict[str, Any]) -> ProviderCapabilityProfile:
    return ProviderCapabilityProfile(
        provider=str(payload.get("provider") or ""),
        control_level=ProviderControlLevel(str(payload.get("control_level"))),
        supports_request_timeout=bool(payload.get("supports_request_timeout")),
        supports_provider_idempotency=bool(payload.get("supports_provider_idempotency")),
        supports_query=bool(payload.get("supports_query")),
        supports_cancel=bool(payload.get("supports_cancel")),
        supports_callback=bool(payload.get("supports_callback")),
        supports_usage_receipt=bool(payload.get("supports_usage_receipt")),
        supports_cost_receipt=bool(payload.get("supports_cost_receipt")),
        reconciliation_mode=str(payload.get("reconciliation_mode") or "unsupported"),
        real_provider_validation_eligible=bool(
            payload.get("real_provider_validation_eligible")
        ),
        contract_version=str(payload.get("contract_version") or "provider-capability-v2"),
    )


__all__ = [name for name in globals() if name.startswith("Provider") or name == "capability_profile_from_dict"]
