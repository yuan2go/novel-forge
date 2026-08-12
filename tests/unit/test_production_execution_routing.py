from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.production_execution import (
    CompletionMode,
    ExecutionCapabilityProfile,
    ExecutionRuntimeClass,
    FallbackMode,
    FallbackPolicy,
    FallbackPolicyRegistry,
    ModelProfile,
    ModelProfileRegistry,
    ModelProfileStatus,
    RoutePolicy,
    RoutePolicyRegistry,
    RouteResolver,
    RouteSnapshotRegistry,
)


SHA = "f" * 40


def _capability(
    backend_id: str, runtime: ExecutionRuntimeClass
) -> ExecutionCapabilityProfile:
    return ExecutionCapabilityProfile(
        backend_id=backend_id,
        backend_version="1.0.0",
        runtime_class=runtime,
        supported_completion_modes=(CompletionMode.SYNCHRONOUS,),
        supported_reasoning_efforts=("xhigh",),
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        supports_structured_output=True,
        supports_process_group_control=False,
        supports_persistent_execution_directory=False,
        supports_provider_idempotency=True,
        real_provider_validation_eligible=False,
        qualification_ref=f"capability-probe:{backend_id}:1",
    )


def _model_profile(
    profile_id: str,
    backend_id: str,
    provider: str,
    model: str,
) -> ModelProfile:
    return ModelProfile(
        profile_id=profile_id,
        profile_version=1,
        backend_id=backend_id,
        runtime_class=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        model_provider=provider,
        model_id=model,
        reasoning_effort="xhigh",
        timeout_policy_ref="timeout:chapter:v1",
        workspace_policy_ref="workspace:chapter:v1",
        output_policy_ref="output:structured:v1",
        fallback_policy="FAIL_CLOSED",
        status=ModelProfileStatus.ACTIVE,
        capability_probe_ref=f"capability-probe:{backend_id}:1",
    )


class ProductionExecutionRoutingTests(unittest.TestCase):
    def _resolver(self, fallback: FallbackPolicy) -> RouteResolver:
        primary = _model_profile(
            "chapter.primary", "remote-provider-a", "openai", "gpt-primary"
        )
        secondary = _model_profile(
            "chapter.secondary", "remote-provider-b", "anthropic", "claude-secondary"
        )
        policy = RoutePolicy(
            policy_id="chapter.production",
            policy_version=1,
            default_model_profile_id=primary.profile_id,
            allowed_model_profile_ids=(primary.profile_id, secondary.profile_id),
            rule_set_ref="route-rules:chapter:v1",
            fallback_policy=fallback.mode.value,
            fallback_policy_ref=fallback.policy_id,
            fallback_policy_version=fallback.policy_version,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        return RouteResolver(
            ModelProfileRegistry((primary, secondary)),
            RoutePolicyRegistry(
                (policy,),
                fallback_policies=FallbackPolicyRegistry((fallback,)),
            ),
            {
                "remote-provider-a": _capability(
                    "remote-provider-a",
                    ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                ),
                "remote-provider-b": _capability(
                    "remote-provider-b",
                    ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                ),
            },
        )

    @staticmethod
    def _freeze(resolver: RouteResolver):
        return resolver.freeze(
            route_snapshot_id="route-snapshot:primary:1",
            route_decision_id="route-decision:primary:1",
            operation_id="operation:chapter:1",
            attempt_id="attempt:chapter:1",
            policy_id="chapter.production",
            task_kind="chapter.draft",
            risk_class="high",
            requested_reasoning_effort="xhigh",
            runtime_host_id="worker:1",
            auth_profile_ref="auth-profile:primary",
            prompt_bundle_ref="prompt-bundle:chapter:1",
            skill_bundle_ref="skill-bundle:chapter:1",
            context_bundle_ref="context-bundle:chapter:1",
            output_schema_ref="schema:chapter-draft:v1",
            release_sha=SHA,
        )

    def test_fallback_policy_is_versioned_and_fail_closed_by_default(self) -> None:
        fallback = FallbackPolicy(
            policy_id="chapter.fail-closed",
            policy_version=1,
            mode=FallbackMode.FAIL_CLOSED,
            allowed_route_ids=(),
            triggers=(),
            maximum_route_changes=0,
            approval_required=True,
            quality_revalidation_required=True,
            status="ACTIVE",
        )

        self.assertEqual(
            FallbackPolicy.from_dict(fallback.to_dict()).contract_hash,
            fallback.contract_hash,
        )
        with self.assertRaisesRegex(ValueError, "route changes"):
            replace(fallback, maximum_route_changes=1)
        with self.assertRaisesRegex(ValueError, "allowlist"):
            FallbackPolicy(
                policy_id="chapter.allow-listed",
                policy_version=1,
                mode=FallbackMode.ALLOW_LISTED_ROUTE,
                allowed_route_ids=(),
                triggers=("provider_timeout",),
                maximum_route_changes=1,
                approval_required=False,
                quality_revalidation_required=True,
                status="ACTIVE",
            )

    def test_freeze_uses_stable_profile_and_snapshot_registry_rejects_drift(self) -> None:
        fallback = FallbackPolicy.fail_closed("chapter.fail-closed", 1)
        resolver = self._resolver(fallback)

        snapshot = self._freeze(resolver)
        registry = RouteSnapshotRegistry()
        first = registry.materialize(snapshot)
        replay = registry.materialize(snapshot)

        self.assertEqual(first.contract_hash, replay.contract_hash)
        self.assertEqual(snapshot.model_profile_id, "chapter.primary")
        self.assertEqual(snapshot.model_provider, "openai")
        self.assertEqual(snapshot.model_id, "gpt-primary")
        self.assertEqual(snapshot.route_generation, 1)
        with self.assertRaisesRegex(ValueError, "different contract"):
            registry.materialize(replace(snapshot, model_id="drifted-model"))
        with self.assertRaisesRegex(ValueError, "already has a RouteSnapshot"):
            registry.materialize(
                replace(
                    snapshot,
                    route_snapshot_id="route-snapshot:other:1",
                    route_decision_id="route-decision:other:1",
                )
            )

    def test_explicit_reroute_requires_new_attempt_approval_and_revalidation(self) -> None:
        fallback = FallbackPolicy(
            policy_id="chapter.approved-fallback",
            policy_version=1,
            mode=FallbackMode.APPROVAL_REQUIRED,
            allowed_route_ids=("chapter.secondary",),
            triggers=("provider_timeout",),
            maximum_route_changes=1,
            approval_required=True,
            quality_revalidation_required=True,
            status="ACTIVE",
        )
        resolver = self._resolver(fallback)
        primary = self._freeze(resolver)

        with self.assertRaisesRegex(ValueError, "new Authority Attempt"):
            resolver.reroute(
                primary,
                route_snapshot_id="route-snapshot:fallback:1",
                route_decision_id="route-decision:fallback:1",
                attempt_id=primary.attempt_id,
                fallback_route_id="chapter.secondary",
                trigger="provider_timeout",
                approval_ref="approval:route-change:1",
                quality_revalidation_ref="quality-revalidation:route-change:1",
                runtime_host_id="worker:2",
                auth_profile_ref="auth-profile:secondary",
            )
        with self.assertRaisesRegex(ValueError, "approval"):
            resolver.reroute(
                primary,
                route_snapshot_id="route-snapshot:fallback:1",
                route_decision_id="route-decision:fallback:1",
                attempt_id="attempt:chapter:2",
                fallback_route_id="chapter.secondary",
                trigger="provider_timeout",
                approval_ref="",
                quality_revalidation_ref="quality-revalidation:route-change:1",
                runtime_host_id="worker:2",
                auth_profile_ref="auth-profile:secondary",
            )

        fallback_snapshot = resolver.reroute(
            primary,
            route_snapshot_id="route-snapshot:fallback:1",
            route_decision_id="route-decision:fallback:1",
            attempt_id="attempt:chapter:2",
            fallback_route_id="chapter.secondary",
            trigger="provider_timeout",
            approval_ref="approval:route-change:1",
            quality_revalidation_ref="quality-revalidation:route-change:1",
            runtime_host_id="worker:2",
            auth_profile_ref="auth-profile:secondary",
        )

        self.assertEqual(fallback_snapshot.route_generation, 2)
        self.assertEqual(
            fallback_snapshot.parent_route_snapshot_id,
            primary.route_snapshot_id,
        )
        self.assertEqual(fallback_snapshot.model_provider, "anthropic")
        self.assertEqual(fallback_snapshot.model_id, "claude-secondary")
        self.assertEqual(
            fallback_snapshot.prompt_bundle_ref, primary.prompt_bundle_ref
        )
        self.assertEqual(
            fallback_snapshot.skill_bundle_ref, primary.skill_bundle_ref
        )
        self.assertEqual(
            fallback_snapshot.output_schema_ref, primary.output_schema_ref
        )
        self.assertEqual(
            fallback_snapshot.fallback_policy_ref, fallback.policy_id
        )

    def test_fail_closed_policy_prohibits_provider_substitution(self) -> None:
        resolver = self._resolver(
            FallbackPolicy.fail_closed("chapter.fail-closed", 1)
        )
        primary = self._freeze(resolver)

        with self.assertRaisesRegex(ValueError, "FAIL_CLOSED"):
            resolver.reroute(
                primary,
                route_snapshot_id="route-snapshot:fallback:1",
                route_decision_id="route-decision:fallback:1",
                attempt_id="attempt:chapter:2",
                fallback_route_id="chapter.secondary",
                trigger="provider_timeout",
                approval_ref="approval:route-change:1",
                quality_revalidation_ref="quality-revalidation:route-change:1",
                runtime_host_id="worker:2",
                auth_profile_ref="auth-profile:secondary",
            )

if __name__ == "__main__":
    unittest.main()
