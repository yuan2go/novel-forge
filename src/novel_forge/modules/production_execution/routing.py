"""Stable ModelProfile registry and immutable RouteSnapshot resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .contracts import (
    ExecutionCapabilityProfile,
    ModelProfile,
    ModelProfileStatus,
    RoutePolicy,
    RouteSnapshot,
)
from .gateway import CapabilityProbe


class ModelProfileRegistry:
    """Registry of versioned stable aliases; it performs no model call."""

    def __init__(self, profiles: Iterable[ModelProfile] = ()) -> None:
        self._profiles: dict[tuple[str, int], ModelProfile] = {}
        self._active: dict[str, int] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ModelProfile) -> None:
        key = (profile.profile_id, profile.profile_version)
        if key in self._profiles:
            raise ValueError(f"ModelProfile is already registered: {key}")
        self._profiles[key] = profile
        if profile.status is ModelProfileStatus.ACTIVE:
            current = self._active.get(profile.profile_id)
            if current is not None:
                raise ValueError(
                    f"ModelProfile alias already has an ACTIVE version: {profile.profile_id}"
                )
            self._active[profile.profile_id] = profile.profile_version

    def resolve(self, profile_id: str, version: int | None = None) -> ModelProfile:
        resolved_version = version if version is not None else self._active.get(profile_id)
        if resolved_version is None:
            raise ValueError(f"ACTIVE ModelProfile is not registered: {profile_id}")
        try:
            return self._profiles[(profile_id, resolved_version)]
        except KeyError as exc:
            raise ValueError(
                f"ModelProfile is not registered: {profile_id}@{resolved_version}"
            ) from exc


class RoutePolicyRegistry:
    def __init__(self, policies: Iterable[RoutePolicy] = ()) -> None:
        self._policies: dict[tuple[str, int], RoutePolicy] = {}
        self._active: dict[str, int] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: RoutePolicy) -> None:
        key = (policy.policy_id, policy.policy_version)
        if key in self._policies:
            raise ValueError(f"RoutePolicy is already registered: {key}")
        self._policies[key] = policy
        if policy.status == "ACTIVE":
            if policy.policy_id in self._active:
                raise ValueError(
                    f"RoutePolicy already has an ACTIVE version: {policy.policy_id}"
                )
            self._active[policy.policy_id] = policy.policy_version

    def resolve(self, policy_id: str, version: int | None = None) -> RoutePolicy:
        resolved_version = version if version is not None else self._active.get(policy_id)
        if resolved_version is None:
            raise ValueError(f"ACTIVE RoutePolicy is not registered: {policy_id}")
        try:
            return self._policies[(policy_id, resolved_version)]
        except KeyError as exc:
            raise ValueError(
                f"RoutePolicy is not registered: {policy_id}@{resolved_version}"
            ) from exc


@dataclass(frozen=True, slots=True)
class RouteRecommendation:
    task_kind: str
    risk_class: str
    model_profile_id: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not all(
            (self.task_kind, self.risk_class, self.model_profile_id, self.evidence_ref)
        ):
            raise ValueError("route recommendation is incomplete")


class RouteRecommendationReadModel:
    """Advisory projection only; RoutePolicy remains admission authority."""

    def __init__(self, recommendations: Iterable[RouteRecommendation] = ()) -> None:
        self._rows = {
            (item.task_kind, item.risk_class): item for item in recommendations
        }

    def get(self, task_kind: str, risk_class: str) -> RouteRecommendation | None:
        return self._rows.get((task_kind, risk_class))


class RouteResolver:
    def __init__(
        self,
        profiles: ModelProfileRegistry,
        policies: RoutePolicyRegistry,
        capabilities: Mapping[str, ExecutionCapabilityProfile],
        recommendations: RouteRecommendationReadModel | None = None,
    ) -> None:
        self.profiles = profiles
        self.policies = policies
        self.capabilities = dict(capabilities)
        self.recommendations = recommendations or RouteRecommendationReadModel()

    def freeze(
        self,
        *,
        route_snapshot_id: str,
        route_decision_id: str,
        operation_id: str,
        attempt_id: str,
        policy_id: str,
        task_kind: str,
        risk_class: str,
        requested_reasoning_effort: str,
        runtime_host_id: str,
        auth_profile_ref: str,
        prompt_bundle_ref: str,
        skill_bundle_ref: str,
        context_bundle_ref: str,
        output_schema_ref: str,
        release_sha: str,
    ) -> RouteSnapshot:
        policy = self.policies.resolve(policy_id)
        if policy.status != "ACTIVE":
            raise ValueError("RoutePolicy is not ACTIVE")
        recommendation = self.recommendations.get(task_kind, risk_class)
        profile_id = (
            recommendation.model_profile_id
            if recommendation is not None
            else policy.default_model_profile_id
        )
        if profile_id not in policy.allowed_model_profile_ids:
            raise ValueError("route recommendation is outside RoutePolicy allowlist")
        profile = self.profiles.resolve(profile_id)
        if profile.reasoning_effort != requested_reasoning_effort.strip().lower():
            raise ValueError("requested reasoning effort cannot be silently downgraded")
        try:
            capability = self.capabilities[profile.backend_id]
        except KeyError as exc:
            raise ValueError(
                f"backend capability is not registered: {profile.backend_id}"
            ) from exc
        CapabilityProbe.verify(
            RouteSnapshot(
                route_snapshot_id=route_snapshot_id,
                route_decision_id=route_decision_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                backend_id=profile.backend_id,
                backend_version=capability.backend_version,
                runtime_host_id=runtime_host_id,
                auth_profile_ref=auth_profile_ref,
                model_profile_id=profile.profile_id,
                model_profile_version=profile.profile_version,
                model_provider=profile.model_provider,
                model_id=profile.model_id,
                requested_reasoning_effort=requested_reasoning_effort,
                reasoning_effort=profile.reasoning_effort,
                prompt_bundle_ref=prompt_bundle_ref,
                skill_bundle_ref=skill_bundle_ref,
                context_bundle_ref=context_bundle_ref,
                output_schema_ref=output_schema_ref,
                release_sha=release_sha,
            ),
            profile,
            capability,
        )
        return RouteSnapshot(
            route_snapshot_id=route_snapshot_id,
            route_decision_id=route_decision_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            backend_id=profile.backend_id,
            backend_version=capability.backend_version,
            runtime_host_id=runtime_host_id,
            auth_profile_ref=auth_profile_ref,
            model_profile_id=profile.profile_id,
            model_profile_version=profile.profile_version,
            model_provider=profile.model_provider,
            model_id=profile.model_id,
            requested_reasoning_effort=requested_reasoning_effort,
            reasoning_effort=profile.reasoning_effort,
            prompt_bundle_ref=prompt_bundle_ref,
            skill_bundle_ref=skill_bundle_ref,
            context_bundle_ref=context_bundle_ref,
            output_schema_ref=output_schema_ref,
            release_sha=release_sha,
        )


__all__ = [
    "ModelProfileRegistry",
    "RoutePolicyRegistry",
    "RouteRecommendation",
    "RouteRecommendationReadModel",
    "RouteResolver",
]
