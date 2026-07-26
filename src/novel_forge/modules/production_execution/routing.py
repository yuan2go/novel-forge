"""Stable ModelProfile registry and immutable RouteSnapshot resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .contracts import (
    ExecutionCapabilityProfile,
    FallbackMode,
    FallbackPolicy,
    ModelProfile,
    ModelProfileStatus,
    RoutePolicy,
    RouteSnapshot,
)
from .gateway import CapabilityProbe


class FallbackPolicyRegistry:
    def __init__(self, policies: Iterable[FallbackPolicy] = ()) -> None:
        self._policies: dict[tuple[str, int], FallbackPolicy] = {}
        self._active: dict[str, int] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: FallbackPolicy) -> None:
        key = (policy.policy_id, policy.policy_version)
        existing = self._policies.get(key)
        if existing is not None:
            if existing.contract_hash != policy.contract_hash:
                raise ValueError(
                    f"FallbackPolicy has a different contract: {key}"
                )
            return
        self._policies[key] = policy
        if policy.status == "ACTIVE":
            if policy.policy_id in self._active:
                raise ValueError(
                    f"FallbackPolicy already has an ACTIVE version: {policy.policy_id}"
                )
            self._active[policy.policy_id] = policy.policy_version

    def resolve(
        self, policy_id: str, version: int | None = None
    ) -> FallbackPolicy:
        resolved_version = (
            version if version is not None else self._active.get(policy_id)
        )
        if resolved_version is None:
            raise ValueError(
                f"ACTIVE FallbackPolicy is not registered: {policy_id}"
            )
        try:
            return self._policies[(policy_id, resolved_version)]
        except KeyError as exc:
            raise ValueError(
                f"FallbackPolicy is not registered: {policy_id}@{resolved_version}"
            ) from exc


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
    def __init__(
        self,
        policies: Iterable[RoutePolicy] = (),
        *,
        fallback_policies: FallbackPolicyRegistry,
    ) -> None:
        self._policies: dict[tuple[str, int], RoutePolicy] = {}
        self._active: dict[str, int] = {}
        self.fallback_policies = fallback_policies
        for policy in policies:
            self.register(policy)

    def register(self, policy: RoutePolicy) -> None:
        fallback = self.fallback_policies.resolve(
            policy.fallback_policy_ref,
            policy.fallback_policy_version,
        )
        if fallback.mode.value != policy.fallback_policy:
            raise ValueError(
                "RoutePolicy fallback mode differs from FallbackPolicy"
            )
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

    def fallback_for(self, policy: RoutePolicy) -> FallbackPolicy:
        return self.fallback_policies.resolve(
            policy.fallback_policy_ref,
            policy.fallback_policy_version,
        )


class RouteSnapshotRegistry:
    """Attempt-scoped immutable RouteSnapshot materializer."""

    def __init__(self, snapshots: Iterable[RouteSnapshot] = ()) -> None:
        self._by_id: dict[str, RouteSnapshot] = {}
        self._by_attempt: dict[tuple[str, str], RouteSnapshot] = {}
        for snapshot in snapshots:
            self.materialize(snapshot)

    def materialize(self, snapshot: RouteSnapshot) -> RouteSnapshot:
        existing = self._by_id.get(snapshot.route_snapshot_id)
        if existing is not None:
            if existing.contract_hash != snapshot.contract_hash:
                raise ValueError(
                    "RouteSnapshot ID has a different contract"
                )
            return existing
        attempt_key = (snapshot.operation_id, snapshot.attempt_id)
        attempt_snapshot = self._by_attempt.get(attempt_key)
        if attempt_snapshot is not None:
            if attempt_snapshot.contract_hash != snapshot.contract_hash:
                raise ValueError(
                    "Authority Attempt already has a RouteSnapshot"
                )
            return attempt_snapshot
        self._by_id[snapshot.route_snapshot_id] = snapshot
        self._by_attempt[attempt_key] = snapshot
        return snapshot

    def require_for_attempt(
        self, operation_id: str, attempt_id: str
    ) -> RouteSnapshot:
        try:
            return self._by_attempt[(operation_id, attempt_id)]
        except KeyError as exc:
            raise ValueError(
                "Authority Attempt has no materialized RouteSnapshot"
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
        credential_scope: str = "",
        secret_version_ref: str = "",
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
        fallback = self.policies.fallback_for(policy)
        if profile.reasoning_effort != requested_reasoning_effort.strip().lower():
            raise ValueError("requested reasoning effort cannot be silently downgraded")
        try:
            capability = self.capabilities[profile.backend_id]
        except KeyError as exc:
            raise ValueError(
                f"backend capability is not registered: {profile.backend_id}"
            ) from exc
        snapshot = RouteSnapshot(
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
            credential_scope=credential_scope,
            secret_version_ref=secret_version_ref,
            fallback_policy_ref=fallback.policy_id,
            fallback_policy_version=fallback.policy_version,
        )
        CapabilityProbe.verify(snapshot, profile, capability)
        return snapshot

    def reroute(
        self,
        previous: RouteSnapshot,
        *,
        route_snapshot_id: str,
        route_decision_id: str,
        attempt_id: str,
        fallback_route_id: str,
        trigger: str,
        approval_ref: str,
        quality_revalidation_ref: str,
        runtime_host_id: str,
        auth_profile_ref: str,
        credential_scope: str | None = None,
        secret_version_ref: str | None = None,
    ) -> RouteSnapshot:
        policy = self.policies.resolve(
            previous.policy_id, previous.policy_version
        )
        fallback = self.policies.fallback_for(policy)
        if fallback.mode is FallbackMode.FAIL_CLOSED:
            raise ValueError("FallbackPolicy is FAIL_CLOSED")
        if attempt_id == previous.attempt_id:
            raise ValueError("reroute requires a new Authority Attempt")
        if route_snapshot_id == previous.route_snapshot_id:
            raise ValueError("reroute requires a new RouteSnapshot identity")
        if route_decision_id == previous.route_decision_id:
            raise ValueError("reroute requires a new RouteDecision identity")
        if fallback_route_id not in fallback.allowed_route_ids:
            raise ValueError("fallback route is outside the explicit allowlist")
        if fallback_route_id not in policy.allowed_model_profile_ids:
            raise ValueError("fallback route is outside RoutePolicy")
        if trigger not in fallback.triggers:
            raise ValueError("fallback trigger is not governed")
        route_change_index = previous.route_change_index + 1
        if route_change_index > fallback.maximum_route_changes:
            raise ValueError("maximum fallback route changes exceeded")
        if fallback.approval_required and not approval_ref:
            raise ValueError("fallback route requires approval evidence")
        if (
            fallback.quality_revalidation_required
            and not quality_revalidation_ref
        ):
            raise ValueError("fallback route requires quality revalidation")
        profile = self.profiles.resolve(fallback_route_id)
        if profile.reasoning_effort != previous.requested_reasoning_effort:
            raise ValueError(
                "fallback cannot silently change reasoning effort"
            )
        try:
            capability = self.capabilities[profile.backend_id]
        except KeyError as exc:
            raise ValueError(
                f"backend capability is not registered: {profile.backend_id}"
            ) from exc
        snapshot = RouteSnapshot(
            route_snapshot_id=route_snapshot_id,
            route_decision_id=route_decision_id,
            operation_id=previous.operation_id,
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
            requested_reasoning_effort=previous.requested_reasoning_effort,
            reasoning_effort=profile.reasoning_effort,
            prompt_bundle_ref=previous.prompt_bundle_ref,
            skill_bundle_ref=previous.skill_bundle_ref,
            context_bundle_ref=previous.context_bundle_ref,
            output_schema_ref=previous.output_schema_ref,
            release_sha=previous.release_sha,
            credential_scope=(
                previous.credential_scope
                if credential_scope is None
                else credential_scope
            ),
            secret_version_ref=(
                previous.secret_version_ref
                if secret_version_ref is None
                else secret_version_ref
            ),
            route_generation=previous.route_generation + 1,
            parent_route_snapshot_id=previous.route_snapshot_id,
            fallback_policy_ref=fallback.policy_id,
            fallback_policy_version=fallback.policy_version,
            fallback_trigger=trigger,
            route_change_index=route_change_index,
            approval_ref=approval_ref,
            quality_revalidation_ref=quality_revalidation_ref,
        )
        CapabilityProbe.verify(snapshot, profile, capability)
        snapshot.require_new_identity_for_change(previous)
        return snapshot


__all__ = [
    "FallbackPolicyRegistry",
    "ModelProfileRegistry",
    "RoutePolicyRegistry",
    "RouteRecommendation",
    "RouteRecommendationReadModel",
    "RouteResolver",
    "RouteSnapshotRegistry",
]
