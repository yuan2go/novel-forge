from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)

from .contracts import ProviderCapabilityProfile, ProviderControlLevel


class LegacyProviderCompatibilityAdapter:
    """Explicitly quarantines v1 adapters from production provider validation."""

    reconciliation_mode = "unsupported"

    def __init__(self, delegate: Any, *, provider: str, environment: str) -> None:
        self.delegate = delegate
        self.provider = provider
        self.environment = environment
        self.capability_profile = ProviderCapabilityProfile(
            provider=provider,
            control_level=ProviderControlLevel.LEGACY_UNCONTROLLED,
            supports_request_timeout=False,
            supports_provider_idempotency=False,
            supports_query=False,
            supports_cancel=False,
            supports_callback=False,
            supports_usage_receipt=False,
            supports_cost_receipt=False,
            reconciliation_mode="unsupported",
            real_provider_validation_eligible=False,
        )

    def execute(self, *, stable_idempotency_key: str, capability: str, request_payload: dict[str, Any]) -> ProviderResult:
        if self.environment == "production":
            raise ExternalEffectAdapterError(
                "legacy uncontrolled provider adapter is disabled in production",
                request_sent=False,
            )
        return self.delegate.execute(
            stable_idempotency_key=stable_idempotency_key,
            capability=capability,
            request_payload=request_payload,
        )

    def query(self, **_: Any) -> ProviderResult:
        return ProviderResult("ambiguous", "", {"manual_resolution_required": True})

    def cancel(self, **_: Any) -> ProviderResult:
        return ProviderResult("ambiguous", "", {"manual_resolution_required": True})


__all__ = ["LegacyProviderCompatibilityAdapter"]
