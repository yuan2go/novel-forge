from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)

from .contracts import (
    ProviderCancellationRequest,
    ProviderCapabilityProfile,
    ProviderControlLevel,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderQueryRequest,
)


class ProviderAdapterV2(Protocol):
    provider: str
    capability_profile: ProviderCapabilityProfile

    def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResult: ...
    def query_v2(self, request: ProviderQueryRequest) -> ProviderInvocationResult: ...
    def cancel_v2(
        self, request: ProviderCancellationRequest
    ) -> ProviderInvocationResult: ...


@dataclass(frozen=True, slots=True)
class ProviderRouteDefinition:
    stage: str
    provider_id: str
    model_id: str
    adapter_contract_version: str
    prompt_version: str
    skill_version: str
    timeout_seconds: int
    environment: str
    idempotency_policy: str
    query_policy: str
    cancel_policy: str
    callback_policy: str
    usage_receipt_policy: str
    cost_receipt_policy: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.stage,
                self.provider_id,
                self.model_id,
                self.adapter_contract_version,
                self.prompt_version,
                self.skill_version,
                self.environment,
            )
        ) or self.timeout_seconds <= 0:
            raise ValueError("provider route definition is incomplete")


@dataclass(frozen=True, slots=True)
class ProviderRouteQualification:
    qualified: bool
    environment: str
    provider_id: str
    model_id: str
    control_level: str
    real_provider_validation_eligible: bool
    reasons: tuple[str, ...]
    capability_profile: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderCapabilityConformanceReport:
    provider_id: str
    contract_version: str
    passed: bool
    checks: Mapping[str, bool]
    failures: tuple[str, ...]
    fixture_protocol_only: bool
    real_model_call: bool = False
    production_verified: bool = False


class ProviderAdapterRegistry:
    """Explicit provider-control registry; never discovers adapters implicitly."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapterV2] = {}

    def register(self, adapter: ProviderAdapterV2) -> None:
        provider_id = adapter.provider.strip().lower()
        if not provider_id or provider_id in self._adapters:
            raise ValueError(f"provider adapter is missing or already registered: {provider_id}")
        if adapter.capability_profile.provider != adapter.provider:
            raise ValueError("provider adapter identity and capability profile disagree")
        self._adapters[provider_id] = adapter

    def resolve(self, provider_id: str) -> ProviderAdapterV2:
        normalized = provider_id.strip().lower()
        try:
            return self._adapters[normalized]
        except KeyError as exc:
            raise ValueError(f"provider v2 adapter is not registered: {normalized}") from exc

    def qualify(
        self,
        provider_id: str,
        model_id: str,
        *,
        environment: str,
    ) -> ProviderRouteQualification:
        adapter = self.resolve(provider_id)
        profile = adapter.capability_profile
        reasons: list[str] = []
        controlled_environment = environment in {"validation", "provider-validation", "production"}
        if controlled_environment and profile.control_level is not ProviderControlLevel.V2_CONTROLLED:
            reasons.append("controlled environments require V2_CONTROLLED")
        if controlled_environment and not profile.real_provider_validation_eligible:
            reasons.append("route is not eligible for real provider validation")
        if environment in {"validation", "provider-validation", "production"} and profile.control_level is ProviderControlLevel.FIXTURE_CONTROLLED:
            reasons.append("fixture providers are forbidden in controlled environments")
        return ProviderRouteQualification(
            qualified=not reasons,
            environment=environment,
            provider_id=provider_id,
            model_id=model_id,
            control_level=profile.control_level.value,
            real_provider_validation_eligible=profile.real_provider_validation_eligible,
            reasons=tuple(reasons),
            capability_profile=profile.to_dict(),
        )


class ProviderAdapterFactory:
    """Constructs only explicitly registered adapter families."""

    def __init__(self) -> None:
        self._builders: dict[str, Callable[[], ProviderAdapterV2]] = {}

    def register(self, provider_id: str, builder: Callable[[], ProviderAdapterV2]) -> None:
        normalized = provider_id.strip().lower()
        if not normalized or normalized in self._builders:
            raise ValueError(f"provider adapter factory is missing or duplicated: {normalized}")
        self._builders[normalized] = builder

    def build_registry(self, provider_ids: set[str]) -> ProviderAdapterRegistry:
        registry = ProviderAdapterRegistry()
        for provider_id in sorted(provider_ids):
            try:
                builder = self._builders[provider_id]
            except KeyError as exc:
                raise ValueError(f"provider adapter factory is not configured: {provider_id}") from exc
            registry.register(builder())
        return registry


@dataclass(frozen=True, slots=True)
class ChapterProviderV2Route:
    definition: ProviderRouteDefinition
    adapter: ProviderAdapterV2


class ChapterProviderV2Gateway:
    """ExternalEffect adapter that preserves v2 provider controls per chapter stage."""

    def __init__(self, routes: Mapping[str, ChapterProviderV2Route]) -> None:
        if not routes:
            raise ValueError("chapter provider v2 gateway requires routes")
        self.routes = dict(routes)
        providers = {route.adapter.provider for route in self.routes.values()}
        if len(providers) != 1:
            raise ValueError(
                "one chapter gateway must use one provider identity; split mixed providers"
            )
        self.provider = providers.pop()
        profiles = [route.adapter.capability_profile for route in self.routes.values()]
        self.reconciliation_mode = (
            "query" if all(profile.supports_query for profile in profiles)
            else "callback" if all(profile.supports_callback for profile in profiles)
            else "unsupported"
        )
        self.capability_profile = ProviderCapabilityProfile(
            provider=self.provider,
            control_level=(
                ProviderControlLevel.V2_CONTROLLED
                if all(profile.control_level is ProviderControlLevel.V2_CONTROLLED for profile in profiles)
                else ProviderControlLevel.FIXTURE_CONTROLLED
            ),
            supports_request_timeout=all(profile.supports_request_timeout for profile in profiles),
            supports_provider_idempotency=all(profile.supports_provider_idempotency for profile in profiles),
            supports_query=all(profile.supports_query for profile in profiles),
            supports_cancel=all(profile.supports_cancel for profile in profiles),
            supports_callback=all(profile.supports_callback for profile in profiles),
            supports_usage_receipt=all(profile.supports_usage_receipt for profile in profiles),
            supports_cost_receipt=all(profile.supports_cost_receipt for profile in profiles),
            reconciliation_mode=self.reconciliation_mode,
            real_provider_validation_eligible=all(
                profile.real_provider_validation_eligible for profile in profiles
            ),
        )

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        route = self._route(capability, request_payload)
        definition = route.definition
        request = ProviderInvocationRequest(
            provider=definition.provider_id,
            model=definition.model_id,
            capability=capability,
            stage=definition.stage,
            stable_idempotency_key=stable_idempotency_key,
            request_payload=dict(request_payload),
            request_hash=str(request_payload.get("request_hash") or ""),
            timeout_seconds=min(
                int(request_payload.get("timeout_seconds") or definition.timeout_seconds),
                definition.timeout_seconds,
            ),
            trace_id=str(request_payload.get("trace_id") or ""),
            correlation_id=str(request_payload.get("correlation_id") or ""),
            operation_id=str(request_payload.get("operation_id") or ""),
            external_effect_id=str(request_payload.get("external_effect_id") or ""),
            budget_reservation_id=str(request_payload.get("budget_reservation_id") or ""),
        )
        result = route.adapter.invoke(request)
        self._validate_result(route, result)
        evidence = dict(result.evidence)
        if result.outcome == "success":
            from novel_forge.modules.chapter_authority.model_effects import (
                normalize_model_output,
            )

            raw_output = evidence.get("result")
            normalized_output = normalize_model_output(
                definition.stage,
                raw_output if isinstance(raw_output, dict) else {},
            )
            if definition.stage.startswith("quality_"):
                requested_dimensions = request_payload.get("input", {}).get("dimensions")
                returned_dimensions = [
                    str(item.get("dimension") or "")
                    for item in normalized_output["dimensions"]
                ]
                if (
                    not isinstance(requested_dimensions, list)
                    or len(returned_dimensions) != len(set(returned_dimensions))
                    or set(returned_dimensions)
                    != {str(item) for item in requested_dimensions}
                ):
                    raise ExternalEffectAdapterError(
                        "quality response dimensions do not match the frozen contract",
                        request_sent=True,
                    )
            evidence["result"] = normalized_output
        evidence.update(
            {
                "provider_id": definition.provider_id,
                "model_id": definition.model_id,
                "prompt_version": definition.prompt_version,
                "skill_version": definition.skill_version,
                "provider_capability_profile": route.adapter.capability_profile.to_dict(),
                "fixture_protocol_only": route.adapter.capability_profile.control_level
                is ProviderControlLevel.FIXTURE_CONTROLLED,
                "real_model_call": route.adapter.capability_profile.control_level
                is ProviderControlLevel.V2_CONTROLLED,
                "production_verified": False,
            }
        )
        handle = result.handle
        return ProviderResult(
            result.outcome,
            "" if handle is None else handle.provider_correlation_id,
            evidence,
            "" if handle is None else handle.provider_request_id,
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        route = self._route(capability, request_payload)
        if not route.adapter.capability_profile.supports_query:
            return ProviderResult("ambiguous", "", {"manual_resolution_required": True})
        result = route.adapter.query_v2(
            ProviderQueryRequest(
                provider_request_id=str(request_payload.get("provider_request_id") or ""),
                stable_idempotency_key=stable_idempotency_key,
                trace_id=str(request_payload.get("trace_id") or ""),
                correlation_id=str(request_payload.get("correlation_id") or ""),
            )
        )
        self._validate_result(route, result)
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
        route = self._route(capability, request_payload)
        if not route.adapter.capability_profile.supports_cancel:
            return ProviderResult("ambiguous", provider_request_id, {"manual_resolution_required": True})
        result = route.adapter.cancel_v2(
            ProviderCancellationRequest(
                provider_request_id=provider_request_id,
                stable_idempotency_key=stable_idempotency_key,
                reason=str(request_payload.get("cancel_reason") or "authority cancellation"),
                trace_id=str(request_payload.get("trace_id") or ""),
                correlation_id=str(request_payload.get("correlation_id") or ""),
            )
        )
        self._validate_result(route, result)
        handle = result.handle
        return ProviderResult(
            result.outcome,
            "" if handle is None else handle.provider_correlation_id,
            result.evidence,
            provider_request_id if handle is None else handle.provider_request_id,
        )

    def model_id_for_stage(self, stage: str) -> str:
        route = self.routes.get(stage)
        return "" if route is None else route.definition.model_id

    def _route(
        self, capability: str, request_payload: Mapping[str, Any]
    ) -> ChapterProviderV2Route:
        stage = str(request_payload.get("stage") or "")
        route = self.routes.get(stage)
        if route is None or capability != f"model.{stage}":
            raise ExternalEffectAdapterError(
                "chapter provider v2 capability or route is unsupported",
                request_sent=False,
            )
        return route

    @staticmethod
    def _validate_result(
        route: ChapterProviderV2Route, result: ProviderInvocationResult
    ) -> None:
        profile = route.adapter.capability_profile
        handle = result.handle
        if result.request_sent and handle is None:
            raise ExternalEffectAdapterError(
                "provider reported submission without a request handle", request_sent=True
            )
        if handle is None:
            return
        mismatches = (
            handle.query_supported != profile.supports_query,
            handle.cancel_supported != profile.supports_cancel,
            handle.callback_supported != profile.supports_callback,
            handle.idempotency_supported != profile.supports_provider_idempotency,
        )
        if any(mismatches):
            raise ExternalEffectAdapterError(
                "provider handle contradicts the frozen capability profile",
                request_sent=True,
            )


__all__ = [
    "ChapterProviderV2Gateway",
    "ChapterProviderV2Route",
    "ProviderAdapterFactory",
    "ProviderAdapterRegistry",
    "ProviderAdapterV2",
    "ProviderCapabilityConformanceReport",
    "ProviderRouteDefinition",
    "ProviderRouteQualification",
]
