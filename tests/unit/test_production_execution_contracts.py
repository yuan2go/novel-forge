from __future__ import annotations

import unittest

from novel_forge.modules.production_execution import (
    ArtifactPointer,
    CapabilityAvailability,
    CancellationOutcome,
    CommitManifest,
    CompletionMode,
    ExecutionBackend,
    ExecutionCancellationResult,
    ExecutionCapabilityProfile,
    ExecutionHandle,
    ExecutionManifest,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeClass,
    InputManifest,
    LocalTerminationOutcome,
    ModelProfile,
    ModelProfileStatus,
    OutputManifest,
    RoutePolicy,
    RouteSnapshot,
    TargetScope,
    UpstreamCancellationOutcome,
    ValidationCheck,
    ValidationManifest,
)


FULL_SHA = "a" * 40


def model_profile(*, effort: str = "xhigh") -> ModelProfile:
    return ModelProfile(
        profile_id=f"codex.sol.{effort}",
        profile_version=1,
        backend_id="codex_cli",
        runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        model_provider="openai",
        model_id="gpt-5.6-sol",
        reasoning_effort=effort,
        timeout_policy_ref="codex-xhigh-v1",
        workspace_policy_ref="book-staging-readonly-v1",
        output_policy_ref="structured-output-required-v1",
        fallback_policy="FAIL_CLOSED",
        status=ModelProfileStatus.ACTIVE,
        capability_probe_ref="probe:codex-cli:1",
    )


def capability_profile() -> ExecutionCapabilityProfile:
    return ExecutionCapabilityProfile(
        backend_id="codex_cli",
        backend_version="codex-cli-1.2.3",
        runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supported_completion_modes=(CompletionMode.PROCESS_EXIT,),
        supported_reasoning_efforts=("high", "xhigh"),
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=False,
        supports_structured_output=True,
        supports_process_group_control=True,
        supports_persistent_execution_directory=True,
        supports_provider_idempotency=False,
        real_provider_validation_eligible=True,
        qualification_ref="probe:codex-cli:1",
    )


def route_snapshot(*, snapshot_id: str = "route-snapshot:1", effort: str = "xhigh") -> RouteSnapshot:
    return RouteSnapshot(
        route_snapshot_id=snapshot_id,
        route_decision_id="route-decision:1",
        operation_id="operation:1",
        attempt_id="attempt:1",
        policy_id="chapter-production",
        policy_version=1,
        backend_id="codex_cli",
        backend_version="codex-cli-1.2.3",
        runtime_host_id="host:local-1",
        auth_profile_ref="auth:codex-subscription",
        model_profile_id="codex.sol.xhigh",
        model_profile_version=1,
        model_provider="openai",
        model_id="gpt-5.6-sol",
        requested_reasoning_effort="xhigh",
        reasoning_effort=effort,
        prompt_bundle_ref="prompt:chapter-draft:v1",
        skill_bundle_ref="skill:prose-generation:v1",
        context_bundle_ref="context:chapter-1:v3",
        output_schema_ref="schema:draft-candidate:v1",
        release_sha=FULL_SHA,
    )


class ProductionExecutionContractTests(unittest.TestCase):
    def test_target_scope_round_trips_every_cross_domain_identifier(self) -> None:
        scope = TargetScope(
            scope_kind="chapter",
            scope_id="chapter:9",
            project_id="project:1",
            book_id="book:1",
            volume_id="volume:2",
            arc_id="arc:3",
            chapter_group_id="chapter-group:4",
            chapter_id="chapter:9",
            chapter_number=9,
            asset_version_id="asset-version:plan:9",
            reader_segment_id="reader-segment:new",
            experiment_id="experiment:control",
        )

        payload = scope.to_dict()
        self.assertEqual(TargetScope.from_dict(payload), scope)
        self.assertEqual(dict(scope), payload)
        with self.assertRaises(TypeError):
            scope["scope_kind"] = "book"  # type: ignore[index]

    def test_execution_request_is_bound_to_authority_attempt_and_fence(self) -> None:
        request = ExecutionRequest(
            execution_id="execution:1",
            operation_id="operation:1",
            root_operation_id="operation:root",
            saga_id="saga:chapter-1",
            attempt_id="attempt:1",
            fencing_token=7,
            project_id="project:1",
            workspace_id="workspace:1",
            book_id="book:1",
            target_scope={
                "scope_kind": "chapter",
                "scope_id": "chapter:1",
                "chapter_id": "chapter:1",
            },
            domain="prose",
            task_kind="chapter.draft.generate",
            stage="draft",
            capability="prose.chapter.draft",
            importance_class="critical",
            risk_class="high",
            route_snapshot_id="route-snapshot:1",
            workspace_snapshot_ref="workspace-snapshot:1",
            input_manifest_ref="input-manifest:1",
            resource_claims=("book:1:chapter:1:write",),
            timeout_policy_ref="timeout:chapter-draft:v1",
            budget_policy_ref="budget:chapter:v1",
            permission_policy_ref="permission:chapter-worker:v1",
            validation_policy_ref="validation:chapter-draft:v1",
            commit_policy_ref="commit:chapter-draft:v1",
            stable_idempotency_key="chapter-1:draft:attempt-1",
            origin_chain=("book.production.run", "chapter.slice.run"),
            agent_hop_count=0,
        )

        self.assertEqual(request.attempt_id, "attempt:1")
        self.assertEqual(request.fencing_token, 7)
        self.assertEqual(request.to_dict()["target_scope"]["chapter_id"], "chapter:1")
        self.assertEqual(request.root_operation_id, "operation:root")
        self.assertEqual(request.capability, "prose.chapter.draft")
        self.assertEqual(
            ExecutionRequest.from_dict(request.to_dict()).contract_hash,
            request.contract_hash,
        )

    def test_execution_request_rejects_missing_attempt_or_non_positive_fence(self) -> None:
        common = dict(
            execution_id="execution:1",
            operation_id="operation:1",
            root_operation_id="operation:root",
            saga_id="saga:1",
            project_id="project:1",
            workspace_id="workspace:1",
            book_id="book:1",
            target_scope={
                "scope_kind": "chapter",
                "scope_id": "chapter:1",
                "chapter_id": "chapter:1",
            },
            domain="prose",
            task_kind="draft",
            stage="draft",
            capability="prose.chapter.draft",
            importance_class="critical",
            risk_class="high",
            route_snapshot_id="route:1",
            workspace_snapshot_ref="workspace:1",
            input_manifest_ref="input:1",
            resource_claims=(),
            timeout_policy_ref="timeout:1",
            budget_policy_ref="budget:1",
            permission_policy_ref="permission:1",
            validation_policy_ref="validation:1",
            commit_policy_ref="commit:1",
            stable_idempotency_key="stable:1",
        )
        with self.assertRaisesRegex(ValueError, "Authority Attempt"):
            ExecutionRequest(attempt_id="", fencing_token=1, **common)
        with self.assertRaisesRegex(ValueError, "fencing"):
            ExecutionRequest(attempt_id="attempt:1", fencing_token=0, **common)

    def test_local_handle_keeps_provider_request_id_null(self) -> None:
        handle = ExecutionHandle(
            execution_id="execution:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            backend_execution_id="local-exec:1",
            backend_id="codex_cli",
            transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            local_execution_receipt_id="process-receipt:1",
            local_process_id=123,
            local_process_group_id=123,
            local_process_start_time="2026-07-22T00:00:00Z",
            provider_request_id=None,
            completion_mode=CompletionMode.PROCESS_EXIT,
            query_capability=CapabilityAvailability.SUPPORTED,
            cancel_capability=CapabilityAvailability.SUPPORTED,
            callback_capability=CapabilityAvailability.UNSUPPORTED,
        )

        self.assertIsNone(handle.provider_request_id)
        self.assertEqual(handle.to_dict()["transport"], "LOCAL_CLI_REMOTE_INFERENCE")

    def test_model_profile_active_requires_capability_probe(self) -> None:
        payload = model_profile().to_dict()
        payload["capability_probe_ref"] = ""
        with self.assertRaisesRegex(ValueError, "Capability Probe"):
            ModelProfile.from_dict(payload)

    def test_capability_profile_qualifies_exact_profile(self) -> None:
        capability_profile().require_model_profile(model_profile())

        incompatible = model_profile(effort="ultra")
        with self.assertRaisesRegex(ValueError, "reasoning effort"):
            capability_profile().require_model_profile(incompatible)

        payload = model_profile().to_dict()
        payload["capability_probe_ref"] = "probe:someone-else:1"
        with self.assertRaisesRegex(ValueError, "Probe"):
            capability_profile().require_model_profile(ModelProfile.from_dict(payload))

    def test_route_snapshot_rejects_xhigh_to_high_downgrade(self) -> None:
        with self.assertRaisesRegex(ValueError, "reasoning effort"):
            route_snapshot(effort="high")

    def test_route_snapshot_validates_model_and_backend_binding(self) -> None:
        snapshot = route_snapshot()
        snapshot.require_qualified_binding(model_profile(), capability_profile())
        self.assertEqual(len(snapshot.content_hash), 64)

        payload = snapshot.to_dict()
        payload["backend_version"] = "spoofed-v999"
        with self.assertRaisesRegex(ValueError, "backend version"):
            RouteSnapshot.from_dict(payload).require_qualified_binding(
                model_profile(), capability_profile()
            )

    def test_route_change_requires_new_snapshot_identity(self) -> None:
        previous = route_snapshot(snapshot_id="route-snapshot:1")
        changed = RouteSnapshot.from_dict(
            {
                **previous.to_dict(),
                "model_id": "gpt-5.6-terra",
                "route_snapshot_id": "route-snapshot:1",
            }
        )
        with self.assertRaisesRegex(ValueError, "new RouteSnapshot"):
            changed.require_new_identity_for_change(previous)

        versioned = RouteSnapshot.from_dict(
            {**changed.to_dict(), "route_snapshot_id": "route-snapshot:2"}
        )
        with self.assertRaisesRegex(ValueError, "RouteDecision"):
            versioned.require_new_identity_for_change(previous)
        versioned = RouteSnapshot.from_dict(
            {**versioned.to_dict(), "route_decision_id": "route-decision:2"}
        )
        versioned.require_new_identity_for_change(previous)

    def test_route_policy_uses_stable_profiles_and_prohibits_reasoning_downgrade(self) -> None:
        policy = RoutePolicy(
            policy_id="chapter-draft",
            policy_version=1,
            default_model_profile_id="codex.sol.xhigh",
            allowed_model_profile_ids=("codex.sol.xhigh", "remote.openai.xhigh"),
            rule_set_ref="route-rules:chapter:v1",
            fallback_policy="FAIL_CLOSED",
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        self.assertEqual(policy.default_model_profile_id, "codex.sol.xhigh")

        with self.assertRaisesRegex(ValueError, "downgrade"):
            RoutePolicy.from_dict(
                {**policy.to_dict(), "reasoning_downgrade_policy": "ALLOW_HIGH"}
            )

    def test_backend_protocol_has_submit_reconcile_cancel(self) -> None:
        self.assertTrue(hasattr(ExecutionBackend, "submit"))
        self.assertTrue(hasattr(ExecutionBackend, "reconcile"))
        self.assertTrue(hasattr(ExecutionBackend, "cancel"))

    def test_execution_result_does_not_require_fake_provider_receipt(self) -> None:
        result = ExecutionResult(
            execution_id="execution:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            outcome=ExecutionOutcome.SUCCEEDED,
            process_receipt_ref="process-receipt:1",
            provider_receipt_ref=None,
            raw_output_ref="artifact:raw:1",
            normalized_output_ref="artifact:normalized:1",
            output_manifest_ref="output-manifest:1",
            usage_receipt_ref="usage:unavailable:1",
            cost_receipt_ref="cost:unavailable:1",
            validation_report_ref="validation-manifest:1",
            started_at="2026-07-22T00:00:00Z",
            completed_at="2026-07-22T00:01:00Z",
        )
        self.assertIsNone(result.provider_receipt_ref)

    def test_cancellation_result_distinguishes_local_and_provider_evidence(self) -> None:
        result = ExecutionCancellationResult(
            execution_id="execution:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            backend_id="codex_cli",
            outcome=CancellationOutcome.CANCELLED,
            local_execution_receipt_id="process-receipt:cancel:1",
            transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            local_termination_outcome=LocalTerminationOutcome.TERMINATED,
            upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
            provider_request_id=None,
            provider_cancellation_receipt_ref=None,
            reason="operator requested",
            requested_at="2026-07-22T00:00:30Z",
            completed_at="2026-07-22T00:00:31Z",
        )
        self.assertIsNone(result.provider_request_id)
        self.assertEqual(result.outcome, CancellationOutcome.CANCELLED)

    def test_cancellation_cannot_claim_upstream_cancel_without_provider_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "upstream"):
            ExecutionCancellationResult(
                execution_id="execution:1",
                operation_id="operation:1",
                attempt_id="attempt:1",
                fencing_token=7,
                backend_id="codex_cli",
                transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
                outcome=CancellationOutcome.CANCELLED,
                local_termination_outcome=LocalTerminationOutcome.TERMINATED,
                upstream_cancellation_outcome=UpstreamCancellationOutcome.CANCELLED,
                local_execution_receipt_id="process-receipt:cancel:1",
                provider_request_id=None,
                provider_cancellation_receipt_ref=None,
                reason="operator requested",
                requested_at="2026-07-22T00:00:30Z",
                completed_at="2026-07-22T00:00:31Z",
            )

        with self.assertRaisesRegex(ValueError, "terminal"):
            ExecutionCancellationResult(
                execution_id="execution:1",
                operation_id="operation:1",
                attempt_id="attempt:1",
                fencing_token=7,
                backend_id="codex_cli",
                transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
                outcome=CancellationOutcome.CANCELLED,
                local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
                upstream_cancellation_outcome=UpstreamCancellationOutcome.NOT_APPLICABLE,
                local_execution_receipt_id=None,
                provider_request_id=None,
                provider_cancellation_receipt_ref=None,
                reason="operator requested",
                requested_at="2026-07-22T00:00:30Z",
                completed_at="2026-07-22T00:00:31Z",
            )

        with self.assertRaisesRegex(ValueError, "ALREADY_COMPLETED"):
            ExecutionCancellationResult(
                execution_id="execution:1",
                operation_id="operation:1",
                attempt_id="attempt:1",
                fencing_token=7,
                backend_id="remote",
                transport=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                outcome=CancellationOutcome.CANCELLED,
                local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
                upstream_cancellation_outcome=UpstreamCancellationOutcome.ALREADY_COMPLETED,
                local_execution_receipt_id=None,
                provider_request_id="provider-request:1",
                provider_cancellation_receipt_ref="provider-cancel:already-completed:1",
                reason="operator requested",
                requested_at="2026-07-22T00:00:30Z",
                completed_at="2026-07-22T00:00:31Z",
            )

        with self.assertRaisesRegex(ValueError, "cancellation receipt"):
            ExecutionCancellationResult(
                execution_id="execution:1",
                operation_id="operation:1",
                attempt_id="attempt:1",
                fencing_token=7,
                backend_id="remote",
                transport=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                outcome=CancellationOutcome.CANCELLED,
                local_termination_outcome=LocalTerminationOutcome.NOT_APPLICABLE,
                upstream_cancellation_outcome=UpstreamCancellationOutcome.CANCELLED,
                local_execution_receipt_id=None,
                provider_request_id="provider-request:1",
                provider_cancellation_receipt_ref=None,
                reason="operator requested",
                requested_at="2026-07-22T00:00:30Z",
                completed_at="2026-07-22T00:00:31Z",
            )

    def test_manifests_are_attempt_bound_and_hash_stable(self) -> None:
        artifact = ArtifactPointer(
            artifact_ref="asset-version:chapter-plan:1",
            artifact_type="chapter_plan",
            content_hash="sha256:" + "b" * 64,
            schema_version="chapter-plan-v3",
            source_eligibility="ELIGIBLE",
        )
        input_manifest = InputManifest(
            manifest_id="input-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            project_id="project:1",
            book_id="book:1",
            target_scope={"scope_kind": "chapter", "chapter_id": "chapter:1"},
            context_bundle_ref="context:1",
            prompt_bundle_ref="prompt:1",
            skill_bundle_ref="skill:1",
            canon_version_refs=("canon:1",),
            arc_version_refs=("arc:1",),
            input_artifacts=(artifact,),
            read_set=("asset-version:chapter-plan:1",),
        )
        execution_manifest = ExecutionManifest(
            manifest_id="execution-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            route_snapshot_id="route-snapshot:1",
            input_manifest_ref="input-manifest:1",
            backend_id="codex_cli",
            backend_version="codex-cli-1.2.3",
            runtime_host_id="host:1",
            auth_profile_ref="auth:1",
            cli_version="codex-cli-1.2.3",
            command_summary=("codex", "exec", "--json"),
            environment_allowlist_name="codex-default-v1",
            timeout_seconds=300,
            release_sha=FULL_SHA,
        )
        output_manifest = OutputManifest(
            manifest_id="output-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            raw_output_ref="artifact:raw:1",
            normalized_output_ref="artifact:normalized:1",
            stdout_ref="artifact:stdout:1",
            stderr_ref="artifact:stderr:1",
            output_hash="c" * 64,
            schema_version="draft-candidate-v1",
            files=(artifact,),
        )
        validation_manifest = ValidationManifest(
            manifest_id="validation-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            output_manifest_ref="output-manifest:1",
            validation_policy_ref="validation-policy:chapter-draft:v1",
            required_check_kinds=("schema", "fencing"),
            checks=(
                ValidationCheck("schema", "PASSED", "schema-report:1"),
                ValidationCheck("fencing", "PASSED", "fence-report:1"),
            ),
            decision="ACCEPTED",
        )
        commit_manifest = CommitManifest(
            manifest_id="commit-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            validation_manifest_ref="validation-manifest:1",
            committed_asset_version_refs=("asset-version:draft:1",),
            authority_commit_ref="authority-commit:1",
            projection_materialization_refs=("projection:draft:1",),
            rejected_output_refs=(),
            rollback_ref="rollback:draft:1",
            decision="COMMITTED",
        )

        manifests = (
            input_manifest,
            execution_manifest,
            output_manifest,
            validation_manifest,
            commit_manifest,
        )
        self.assertTrue(all(item.attempt_id == "attempt:1" for item in manifests))
        self.assertTrue(all(len(item.content_hash) == 64 for item in manifests))
        self.assertEqual(input_manifest.content_hash, InputManifest.from_dict(input_manifest.to_dict()).content_hash)

    def test_validation_acceptance_requires_every_frozen_policy_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "required checks"):
            ValidationManifest(
                manifest_id="validation-manifest:1",
                operation_id="operation:1",
                attempt_id="attempt:1",
                fencing_token=7,
                output_manifest_ref="output-manifest:1",
                validation_policy_ref="validation-policy:chapter-draft:v1",
                required_check_kinds=("schema", "semantic", "fencing"),
                checks=(
                    ValidationCheck("schema", "PASSED", "schema-report:1"),
                    ValidationCheck("fencing", "PASSED", "fence-report:1"),
                ),
                decision="ACCEPTED",
            )

    def test_from_dict_rejects_ambiguous_boolean_and_missing_route_fields(self) -> None:
        payload = capability_profile().to_dict()
        payload["supports_query"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            ExecutionCapabilityProfile.from_dict(payload)
        with self.assertRaises(ValueError):
            RouteSnapshot.from_dict({})

    def test_execution_request_deep_freezes_target_scope(self) -> None:
        request = ExecutionRequest(
            execution_id="execution:1",
            operation_id="operation:1",
            root_operation_id="operation:1",
            saga_id="saga:1",
            attempt_id="attempt:1",
            fencing_token=1,
            project_id="project:1",
            workspace_id="workspace:1",
            book_id="book:1",
            target_scope={
                "scope_kind": "book",
                "scope_id": "book:1",
                "book_id": "book:1",
            },
            domain="planning",
            task_kind="book.plan.generate",
            stage="planning",
            capability="planning.book.generate",
            importance_class="high",
            risk_class="high",
            route_snapshot_id="route:1",
            workspace_snapshot_ref="workspace:1",
            input_manifest_ref="input:1",
            resource_claims=(),
            timeout_policy_ref="timeout:1",
            budget_policy_ref="budget:1",
            permission_policy_ref="permission:1",
            validation_policy_ref="validation:1",
            commit_policy_ref="commit:1",
            stable_idempotency_key="stable:1",
        )
        with self.assertRaises(TypeError):
            request.target_scope["scope_kind"] = "chapter"  # type: ignore[index]
        self.assertEqual(request.target_scope["book_id"], "book:1")

    def test_commit_manifest_rejects_commit_without_asset_or_authority_receipt(self) -> None:
        common = dict(
            manifest_id="commit-manifest:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            fencing_token=7,
            validation_manifest_ref="validation-manifest:1",
            projection_materialization_refs=(),
            rejected_output_refs=(),
            rollback_ref="rollback:1",
            decision="COMMITTED",
        )
        with self.assertRaisesRegex(ValueError, "committed AssetVersion"):
            CommitManifest(
                committed_asset_version_refs=(),
                authority_commit_ref="authority-commit:1",
                **common,
            )
        with self.assertRaisesRegex(ValueError, "Authority commit"):
            CommitManifest(
                committed_asset_version_refs=("asset-version:1",),
                authority_commit_ref="",
                **common,
            )


if __name__ == "__main__":
    unittest.main()
