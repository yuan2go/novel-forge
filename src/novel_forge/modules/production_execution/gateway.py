"""Attempt-bound admission and backend routing for production model execution.

The gateway owns no Attempt state.  It verifies the caller's existing Authority
Attempt and fencing token, resolves immutable routing/input contracts, and then
delegates to an explicitly registered execution backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .capabilities import CapabilityDefinition
from .capability_registry import CapabilityRegistry, default_capability_registry
from .contracts import (
    ExecutionBackend,
    ExecutionCancellationResult,
    ExecutionCapabilityProfile,
    ExecutionHandle,
    ExecutionRecoveryAction,
    ExecutionRecoveryAuthorization,
    ExecutionRequest,
    ExecutionResult,
    InputManifest,
    ModelProfile,
    ModelProfileStatus,
    RoutePolicy,
    RouteSnapshot,
)
from novel_forge.modules.provider_control.contracts import ProviderReceipt


class AttemptFenceVerifier(Protocol):
    def assert_current(
        self, operation_id: str, attempt_id: str, fencing_token: int
    ) -> None: ...

    def assert_recovery_current(
        self,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
    ) -> None: ...


class ExecutionContractSource(Protocol):
    def route_snapshot(self, route_snapshot_id: str) -> RouteSnapshot: ...

    def model_profile(self, profile_id: str, version: int) -> ModelProfile: ...

    def route_policy(self, policy_id: str, version: int) -> RoutePolicy: ...

    def input_manifest(self, manifest_ref: str) -> InputManifest: ...


@dataclass(frozen=True, slots=True)
class ExecutionAdmission:
    request: ExecutionRequest
    route_snapshot: RouteSnapshot
    model_profile: ModelProfile
    route_policy: RoutePolicy
    input_manifest: InputManifest
    capability_profile: ExecutionCapabilityProfile
    capability_definition: CapabilityDefinition


class StaticAttemptFenceVerifier:
    """Explicit test/composition fixture; production injects the Authority query."""

    def __init__(
        self,
        tokens: dict[tuple[str, str], int],
        *,
        owners: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._tokens = dict(tokens)
        self._owners = dict(owners or {})

    def assert_current(
        self, operation_id: str, attempt_id: str, fencing_token: int
    ) -> None:
        current = self._tokens.get((operation_id, attempt_id))
        if current != fencing_token:
            raise ValueError("stale Authority fencing token")

    def assert_recovery_current(
        self,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
    ) -> None:
        self.assert_current(operation_id, attempt_id, fencing_token)
        expected_owner = self._owners.get((operation_id, attempt_id))
        if expected_owner is not None and expected_owner != worker_id:
            raise ValueError("recovery worker does not own the current lease")


class StaticExecutionContractSource:
    """Read-only contract source for tests and explicit bootstrap fixtures."""

    def __init__(
        self,
        *,
        route_snapshots: Iterable[RouteSnapshot],
        model_profiles: Iterable[ModelProfile],
        route_policies: Iterable[RoutePolicy],
        input_manifests: Iterable[InputManifest],
    ) -> None:
        self._routes = self._index(route_snapshots, lambda item: item.route_snapshot_id)
        self._profiles = self._index(
            model_profiles, lambda item: (item.profile_id, item.profile_version)
        )
        self._policies = self._index(
            route_policies, lambda item: (item.policy_id, item.policy_version)
        )
        self._inputs = self._index(input_manifests, lambda item: item.manifest_id)

    @staticmethod
    def _index(items: Iterable[object], key):
        result = {}
        for item in items:
            identity = key(item)
            if identity in result:
                raise ValueError(f"duplicate immutable execution contract: {identity}")
            result[identity] = item
        return result

    def route_snapshot(self, route_snapshot_id: str) -> RouteSnapshot:
        try:
            return self._routes[route_snapshot_id]
        except KeyError as exc:
            raise ValueError(f"RouteSnapshot is not available: {route_snapshot_id}") from exc

    def model_profile(self, profile_id: str, version: int) -> ModelProfile:
        try:
            return self._profiles[(profile_id, version)]
        except KeyError as exc:
            raise ValueError(f"ModelProfile is not available: {profile_id}@{version}") from exc

    def route_policy(self, policy_id: str, version: int) -> RoutePolicy:
        try:
            return self._policies[(policy_id, version)]
        except KeyError as exc:
            raise ValueError(f"RoutePolicy is not available: {policy_id}@{version}") from exc

    def input_manifest(self, manifest_ref: str) -> InputManifest:
        try:
            return self._inputs[manifest_ref]
        except KeyError as exc:
            raise ValueError(f"InputManifest is not available: {manifest_ref}") from exc


class CapabilityProbe:
    """Fail-closed comparison of a frozen route with a backend declaration."""

    @staticmethod
    def verify(
        route: RouteSnapshot,
        profile: ModelProfile,
        capability: ExecutionCapabilityProfile,
    ) -> None:
        route.require_qualified_binding(profile, capability)
        if route.backend_id != capability.backend_id:
            raise ValueError("RouteSnapshot was routed to a different backend")
        if route.backend_version != capability.backend_version:
            raise ValueError("backend version changed after RouteSnapshot creation")


class AdmissionController:
    def __init__(
        self,
        contracts: ExecutionContractSource,
        attempt_fence: AttemptFenceVerifier,
        *,
        require_external_effect: bool = True,
        capability_registry: CapabilityRegistry | None = None,
        environment: str = "test",
    ) -> None:
        self.contracts = contracts
        self.attempt_fence = attempt_fence
        self.require_external_effect = require_external_effect
        self.capability_registry = (
            capability_registry or default_capability_registry()
        )
        self.environment = environment.strip().lower()

    def resolve_route(self, request: ExecutionRequest) -> RouteSnapshot:
        route = self.contracts.route_snapshot(request.route_snapshot_id)
        if (route.operation_id, route.attempt_id) != (
            request.operation_id,
            request.attempt_id,
        ):
            raise ValueError("RouteSnapshot does not bind the requested Authority Attempt")
        return route

    def admit(
        self,
        request: ExecutionRequest,
        capability: ExecutionCapabilityProfile,
    ) -> ExecutionAdmission:
        self.attempt_fence.assert_current(
            request.operation_id, request.attempt_id, request.fencing_token
        )
        return self._admit_frozen_contracts(request, capability)

    def admit_recovery(
        self,
        request: ExecutionRequest,
        capability: ExecutionCapabilityProfile,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionAdmission:
        expected_identity = (
            request.execution_id,
            request.external_effect_id,
            request.operation_id,
            request.attempt_id,
            request.fencing_token,
        )
        authorized_identity = (
            authorization.execution_id,
            authorization.external_effect_id,
            authorization.operation_id,
            authorization.attempt_id,
            authorization.execution_fencing_token,
        )
        if expected_identity != authorized_identity:
            raise ValueError(
                "Recovery Authorization differs from frozen execution identity"
            )
        self.attempt_fence.assert_recovery_current(
            request.operation_id,
            request.attempt_id,
            authorization.recovery_fencing_token,
            authorization.recovery_worker_id,
        )
        return self._admit_frozen_contracts(request, capability)

    def _admit_frozen_contracts(
        self,
        request: ExecutionRequest,
        capability: ExecutionCapabilityProfile,
    ) -> ExecutionAdmission:
        if self.require_external_effect and not all(
            (request.trace_id, request.correlation_id, request.external_effect_id)
        ):
            raise ValueError("production execution requires trace and ExternalEffect binding")
        definition = self.capability_registry.require_backend(
            request.capability,
            capability,
            environment=self.environment,
        )
        if request.domain != definition.domain.value:
            raise ValueError("ExecutionRequest domain differs from governed capability")
        if request.risk_class.lower() != definition.risk_class.value:
            raise ValueError(
                "ExecutionRequest risk class differs from governed capability"
            )
        policy_bindings = (
            (
                request.timeout_policy_ref,
                definition.timeout_policy_ref,
                "timeout",
            ),
            (
                request.budget_policy_ref,
                definition.budget_policy_ref,
                "budget",
            ),
            (
                request.permission_policy_ref,
                definition.permission_policy_ref,
                "permission",
            ),
            (
                request.validation_policy_ref,
                definition.validation_policy_ref,
                "validation",
            ),
            (
                request.commit_policy_ref,
                definition.commit_policy_ref,
                "commit",
            ),
        )
        mismatched_policies = [
            label
            for actual, expected, label in policy_bindings
            if actual != expected
        ]
        if mismatched_policies:
            raise ValueError(
                "ExecutionRequest differs from governed "
                + ", ".join(mismatched_policies)
                + " policy"
            )
        route = self.resolve_route(request)
        profile = self.contracts.model_profile(
            route.model_profile_id, route.model_profile_version
        )
        policy = self.contracts.route_policy(route.policy_id, route.policy_version)
        manifest = self.contracts.input_manifest(request.input_manifest_ref)
        if profile.status is not ModelProfileStatus.ACTIVE or policy.status != "ACTIVE":
            raise ValueError("execution route is not ACTIVE")
        if profile.profile_id not in policy.allowed_model_profile_ids:
            raise ValueError("ModelProfile is not allowed by RoutePolicy")
        if route.policy_id != policy.policy_id:
            raise ValueError("RouteSnapshot policy binding is invalid")
        if (
            route.fallback_policy_ref != policy.fallback_policy_ref
            or route.fallback_policy_version
            != policy.fallback_policy_version
        ):
            raise ValueError(
                "RouteSnapshot fallback policy binding is invalid"
            )
        CapabilityProbe.verify(route, profile, capability)
        expected_identity = (
            request.operation_id,
            request.attempt_id,
            request.fencing_token,
            request.project_id,
            request.book_id,
        )
        manifest_identity = (
            manifest.operation_id,
            manifest.attempt_id,
            manifest.fencing_token,
            manifest.project_id,
            manifest.book_id,
        )
        if manifest_identity != expected_identity:
            raise ValueError("InputManifest does not bind the requested Authority Attempt")
        if manifest.source_policy_ref != definition.source_policy_ref:
            raise ValueError(
                "InputManifest source policy differs from governed capability"
            )
        if dict(manifest.target_scope) != dict(request.target_scope):
            raise ValueError("InputManifest target scope changed after admission")
        route_refs = (
            route.context_bundle_ref,
            route.prompt_bundle_ref,
            route.skill_bundle_ref,
        )
        manifest_refs = (
            manifest.context_bundle_ref,
            manifest.prompt_bundle_ref,
            manifest.skill_bundle_ref,
        )
        if route_refs != manifest_refs:
            raise ValueError("InputManifest does not match the frozen RouteSnapshot")
        if request.timeout_policy_ref != profile.timeout_policy_ref:
            raise ValueError("ExecutionRequest timeout policy differs from ModelProfile")
        return ExecutionAdmission(
            request,
            route,
            profile,
            policy,
            manifest,
            capability,
            definition,
        )

    def assert_handle_current(self, handle: ExecutionHandle) -> None:
        self.attempt_fence.assert_current(
            handle.operation_id, handle.attempt_id, handle.fencing_token
        )


class ExecutionBackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, ExecutionBackend] = {}

    def register(self, backend: ExecutionBackend) -> None:
        backend_id = backend.backend_id.strip().lower()
        if not backend_id or backend_id in self._backends:
            raise ValueError(f"execution backend is missing or already registered: {backend_id}")
        if backend.capability_profile.backend_id != backend.backend_id:
            raise ValueError("backend identity and capability profile disagree")
        self._backends[backend_id] = backend

    def resolve(self, backend_id: str) -> ExecutionBackend:
        try:
            return self._backends[backend_id.strip().lower()]
        except KeyError as exc:
            raise ValueError(f"execution backend is not registered: {backend_id}") from exc


class ProductionExecutionGateway:
    def __init__(
        self,
        backends: ExecutionBackendRegistry,
        admission: AdmissionController,
    ) -> None:
        self.backends = backends
        self.admission = admission

    def submit(self, request: ExecutionRequest) -> ExecutionHandle:
        route = self.admission.resolve_route(request)
        backend = self.backends.resolve(route.backend_id)
        self.admission.admit(request, backend.capability_profile)
        handle = backend.submit(request)
        self._validate_handle(
            request, route, handle, backend.capability_profile.runtime_class
        )
        return handle

    def resume_planned_execution(
        self,
        request: ExecutionRequest,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionHandle:
        if authorization.action is not ExecutionRecoveryAction.DISPATCH_PLANNED:
            raise ValueError(
                "planned execution recovery requires DISPATCH_PLANNED authorization"
            )
        route = self.admission.resolve_route(request)
        backend = self.backends.resolve(route.backend_id)
        self.admission.admit_recovery(
            request,
            backend.capability_profile,
            authorization,
        )
        handle = backend.submit_recovered(request, authorization)
        self._validate_handle(
            request,
            route,
            handle,
            backend.capability_profile.runtime_class,
        )
        return handle

    def recover_existing_execution(
        self,
        request: ExecutionRequest,
        handle: ExecutionHandle,
        authorization: ExecutionRecoveryAuthorization,
    ) -> ExecutionResult:
        if authorization.action not in {
            ExecutionRecoveryAction.QUERY,
            ExecutionRecoveryAction.CONSUME_RESULT,
        }:
            raise ValueError(
                "existing execution recovery requires QUERY or CONSUME_RESULT authorization"
            )
        route = self.admission.resolve_route(request)
        backend = self.backends.resolve(route.backend_id)
        self.admission.admit_recovery(
            request,
            backend.capability_profile,
            authorization,
        )
        self._validate_handle(
            request,
            route,
            handle,
            backend.capability_profile.runtime_class,
        )
        result = backend.reconcile(handle)
        self._validate_result(handle, result)
        return result

    def cancel_existing_execution(
        self,
        request: ExecutionRequest,
        handle: ExecutionHandle,
        authorization: ExecutionRecoveryAuthorization,
        reason: str,
    ) -> ExecutionCancellationResult:
        if authorization.action is not ExecutionRecoveryAction.CANCEL:
            raise ValueError(
                "existing execution cancellation requires CANCEL authorization"
            )
        if not reason.strip():
            raise ValueError("execution cancellation reason is required")
        route = self.admission.resolve_route(request)
        backend = self.backends.resolve(route.backend_id)
        self.admission.admit_recovery(
            request,
            backend.capability_profile,
            authorization,
        )
        self._validate_handle(
            request,
            route,
            handle,
            backend.capability_profile.runtime_class,
        )
        result = backend.cancel(handle, reason)
        self._validate_cancellation(handle, result)
        return result

    def reconcile(self, handle: ExecutionHandle) -> ExecutionResult:
        self.admission.assert_handle_current(handle)
        backend = self.backends.resolve(handle.backend_id)
        result = backend.reconcile(handle)
        self._validate_result(handle, result)
        return result

    def cancel(
        self, handle: ExecutionHandle, reason: str
    ) -> ExecutionCancellationResult:
        self.admission.assert_handle_current(handle)
        if not reason.strip():
            raise ValueError("execution cancellation reason is required")
        backend = self.backends.resolve(handle.backend_id)
        result = backend.cancel(handle, reason)
        self._validate_cancellation(handle, result)
        return result

    @staticmethod
    def _validate_cancellation(
        handle: ExecutionHandle,
        result: ExecutionCancellationResult,
    ) -> None:
        if (
            result.execution_id,
            result.operation_id,
            result.attempt_id,
            result.fencing_token,
            result.backend_id,
        ) != (
            handle.execution_id,
            handle.operation_id,
            handle.attempt_id,
            handle.fencing_token,
            handle.backend_id,
        ):
            raise ValueError("backend cancellation result changed execution identity")

    def accept_callback(
        self, handle: ExecutionHandle, receipt: ProviderReceipt
    ) -> ExecutionResult:
        self.admission.assert_handle_current(handle)
        backend = self.backends.resolve(handle.backend_id)
        accept = getattr(backend, "accept_callback", None)
        if not callable(accept):
            raise ValueError("execution backend does not support callbacks")
        result = accept(handle, receipt)
        self._validate_result(handle, result)
        return result

    @staticmethod
    def _validate_handle(
        request: ExecutionRequest,
        route: RouteSnapshot,
        handle: ExecutionHandle,
        expected_runtime,
    ) -> None:
        if (
            handle.execution_id,
            handle.operation_id,
            handle.attempt_id,
            handle.fencing_token,
            handle.backend_id,
        ) != (
            request.execution_id,
            request.operation_id,
            request.attempt_id,
            request.fencing_token,
            route.backend_id,
        ):
            raise ValueError("execution backend returned a handle for a different Attempt")
        if handle.transport is not expected_runtime:
            raise ValueError("execution backend transport differs from capability profile")

    @staticmethod
    def _validate_result(handle: ExecutionHandle, result: ExecutionResult) -> None:
        if (
            result.execution_id,
            result.operation_id,
            result.attempt_id,
            result.fencing_token,
        ) != (
            handle.execution_id,
            handle.operation_id,
            handle.attempt_id,
            handle.fencing_token,
        ):
            raise ValueError("execution backend returned a result for a different Attempt")
__all__ = [
    "AdmissionController",
    "AttemptFenceVerifier",
    "CapabilityProbe",
    "ExecutionAdmission",
    "ExecutionBackendRegistry",
    "ExecutionContractSource",
    "ProductionExecutionGateway",
    "StaticAttemptFenceVerifier",
    "StaticExecutionContractSource",
]
