from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from novel_forge.modules.production_execution import (
    AgentWorkspaceExecutionBackend,
    AgentWorkspaceExecutionContract,
    ArtifactPointer,
    BackendConformanceScenario,
    BackendConformanceSuite,
    CapabilityId,
    CodexCliExecutionBackend,
    CodexProcessSupervisor,
    CompletionMode,
    ExecutionCapabilityProfile,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
    ExternalActionCallbackReceipt,
    FailureInjectionPoint,
    FailureInjector,
    InMemoryExecutionRecordStore,
    InputManifest,
    InjectedExecutionFailure,
    LocalProcessExecutionPolicy,
    ModelProfile,
    ModelProfileStatus,
    PersistentExecutionDirectory,
    RemoteProviderExecutionBackend,
    RemoteExternalActionBackend,
    ResolvedExecutionPayload,
    RoutePolicy,
    RouteSnapshot,
    ScriptedFixtureExecutionBackend,
    ScriptedAgentWorkspaceRunner,
    ScriptedExternalActionAdapter,
    StaticAgentWorkspaceContractSource,
    StaticExecutionPayloadResolver,
    default_capability_registry,
)
from novel_forge.modules.production_execution.gateway import (
    AdmissionController,
    StaticAttemptFenceVerifier,
    StaticExecutionContractSource,
)
from tests.unit.test_production_execution_gateway import (
    _remote_adapter,
    contracts as model_contracts,
)


SHA = "b" * 40
HASH = "sha256:" + hashlib.sha256(b"execution-input").hexdigest()


def _profile(
    *,
    backend_id: str,
    runtime: ExecutionRuntimeClass,
    qualification_ref: str,
    query: bool = True,
    cancel: bool = True,
    callback: bool = False,
    idempotency: bool = False,
) -> ExecutionCapabilityProfile:
    return ExecutionCapabilityProfile(
        backend_id=backend_id,
        backend_version="1.0.0",
        runtime_class=runtime,
        supported_completion_modes=(
            CompletionMode.SYNCHRONOUS,
            CompletionMode.POLL,
            CompletionMode.CALLBACK,
        ),
        supported_reasoning_efforts=("none",),
        supports_query=query,
        supports_cancel=cancel,
        supports_callback=callback,
        supports_usage_receipt=False,
        supports_cost_receipt=False,
        supports_structured_output=True,
        supports_process_group_control=False,
        supports_persistent_execution_directory=False,
        supports_provider_idempotency=idempotency,
        real_provider_validation_eligible=False,
        qualification_ref=qualification_ref,
    )


def _contracts(
    capability_id: CapabilityId,
    profile_contract: ExecutionCapabilityProfile,
    *,
    environment: str = "test",
) -> tuple[AdmissionController, ExecutionRequest]:
    definition = default_capability_registry().resolve(capability_id)
    model_profile = ModelProfile(
        profile_id=f"{profile_contract.backend_id}.default",
        profile_version=1,
        backend_id=profile_contract.backend_id,
        runtime_class=profile_contract.runtime_class,
        model_provider="external-runtime",
        model_id=f"{profile_contract.backend_id}.v1",
        reasoning_effort="none",
        timeout_policy_ref=definition.timeout_policy_ref,
        workspace_policy_ref="workspace:governed:v1",
        output_policy_ref="output:structured:v1",
        fallback_policy="FAIL_CLOSED",
        status=ModelProfileStatus.ACTIVE,
        capability_probe_ref=profile_contract.qualification_ref,
    )
    policy = RoutePolicy(
        policy_id=f"{definition.domain.value}.production",
        policy_version=1,
        default_model_profile_id=model_profile.profile_id,
        allowed_model_profile_ids=(model_profile.profile_id,),
        rule_set_ref=f"route-rules:{definition.domain.value}:1",
        fallback_policy="FAIL_CLOSED",
        reasoning_downgrade_policy="PROHIBITED",
        status="ACTIVE",
    )
    route = RouteSnapshot(
        route_snapshot_id=f"route:{profile_contract.backend_id}:1",
        route_decision_id=f"decision:{profile_contract.backend_id}:1",
        operation_id="operation:conformance",
        attempt_id="attempt:conformance",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        backend_id=profile_contract.backend_id,
        backend_version=profile_contract.backend_version,
        runtime_host_id="host:fixture",
        auth_profile_ref="auth-profile:fixture",
        model_profile_id=model_profile.profile_id,
        model_profile_version=model_profile.profile_version,
        model_provider=model_profile.model_provider,
        model_id=model_profile.model_id,
        requested_reasoning_effort="none",
        reasoning_effort="none",
        prompt_bundle_ref=f"prompt:{definition.capability_id.value}:1",
        skill_bundle_ref=f"skill:{definition.capability_id.value}:1",
        context_bundle_ref=f"context:{definition.capability_id.value}:1",
        output_schema_ref=definition.output_schema_ref,
        release_sha=SHA,
    )
    artifact = ArtifactPointer(
        artifact_ref="asset-version:conformance-input:1",
        artifact_type="execution_input",
        content_hash=HASH,
        schema_version="execution-input.v1",
        source_eligibility="PRODUCTION_ELIGIBLE",
    )
    manifest = InputManifest(
        manifest_id=f"input-manifest:{profile_contract.backend_id}:1",
        operation_id=route.operation_id,
        attempt_id=route.attempt_id,
        fencing_token=17,
        project_id="project:conformance",
        book_id="book:conformance",
        target_scope={
            "scope_kind": "book",
            "scope_id": "book:conformance",
            "project_id": "project:conformance",
            "book_id": "book:conformance",
        },
        context_bundle_ref=route.context_bundle_ref,
        prompt_bundle_ref=route.prompt_bundle_ref,
        skill_bundle_ref=route.skill_bundle_ref,
        context_bundle_version=route.context_bundle_ref,
        prompt_bundle_version=route.prompt_bundle_ref,
        skill_bundle_version=route.skill_bundle_ref,
        canon_snapshot_version="canon:conformance:1",
        story_state_version="story-state:conformance:1",
        planning_version=artifact.asset_version_id,
        quality_profile_version="quality:conformance:1",
        source_policy_ref=definition.source_policy_ref,
        source_eligibility="PRODUCTION_ELIGIBLE",
        canon_version_refs=("canon:conformance:1",),
        arc_version_refs=("arc:conformance:1",),
        input_artifacts=(artifact,),
        read_set=(artifact.artifact_ref,),
    )
    request = ExecutionRequest(
        execution_id=f"execution:{profile_contract.backend_id}:1",
        operation_id=route.operation_id,
        root_operation_id=route.operation_id,
        saga_id="saga:conformance",
        attempt_id=route.attempt_id,
        fencing_token=17,
        project_id=manifest.project_id,
        workspace_id="workspace:conformance",
        book_id=manifest.book_id,
        target_scope=manifest.target_scope,
        domain=definition.domain.value,
        task_kind=f"{definition.domain.value}.conformance",
        stage="execute",
        capability=definition.capability_id.value,
        importance_class="HIGH",
        risk_class=definition.risk_class.value,
        route_snapshot_id=route.route_snapshot_id,
        workspace_snapshot_ref="workspace-snapshot:conformance:1",
        input_manifest_ref=manifest.manifest_id,
        resource_claims=("external-effect",),
        timeout_policy_ref=definition.timeout_policy_ref,
        budget_policy_ref=definition.budget_policy_ref,
        permission_policy_ref=definition.permission_policy_ref,
        validation_policy_ref=definition.validation_policy_ref,
        commit_policy_ref=definition.commit_policy_ref,
        stable_idempotency_key=f"{definition.capability_id.value}:conformance:1",
        trace_id="trace:conformance",
        correlation_id="correlation:conformance",
        external_effect_id="external-effect:conformance",
        budget_reservation_id="budget-reservation:conformance",
    )
    source = StaticExecutionContractSource(
        route_snapshots=(route,),
        model_profiles=(model_profile,),
        route_policies=(policy,),
        input_manifests=(manifest,),
    )
    admission = AdmissionController(
        source,
        StaticAttemptFenceVerifier(
            {(request.operation_id, request.attempt_id): request.fencing_token}
        ),
        environment=environment,
    )
    return admission, request


class QualifiedBackendConformanceTests(unittest.TestCase):
    def test_local_process_policy_fixes_workspace_and_command_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = LocalProcessExecutionPolicy(
                fixed_working_directory=tmp,
                allowed_command_prefixes=(("codex", "exec"),),
            )
            policy.assert_payload(
                ResolvedExecutionPayload(
                    request_payload={"input": "bounded"},
                    input_text="",
                    working_directory=tmp,
                    timeout_seconds=10,
                    output_schema_version="result.v1",
                    command=("codex", "exec", "--json"),
                )
            )
            with self.assertRaisesRegex(ValueError, "working directory"):
                policy.assert_payload(
                    ResolvedExecutionPayload(
                        request_payload={"input": "bounded"},
                        input_text="",
                        working_directory=str(Path(tmp) / "other"),
                        timeout_seconds=10,
                        output_schema_version="result.v1",
                        command=("codex", "exec"),
                    )
                )
            with self.assertRaisesRegex(ValueError, "not allowlisted"):
                policy.assert_payload(
                    ResolvedExecutionPayload(
                        request_payload={"input": "bounded"},
                        input_text="",
                        working_directory=tmp,
                        timeout_seconds=10,
                        output_schema_version="result.v1",
                        command=("python", "-c", "unsafe"),
                    )
                )

    def test_failure_injector_catalog_is_complete_and_one_shot(self) -> None:
        expected = {
            "before_send_failure",
            "after_send_before_receipt_failure",
            "provider_unknown",
            "provider_timeout",
            "callback_duplicate",
            "callback_conflict",
            "callback_after_cancel",
            "database_disconnect",
            "object_store_failure",
            "worker_crash",
            "process_exit_nonzero",
            "process_timeout",
            "process_result_corrupt",
            "stale_fence",
            "budget_exceeded",
            "schema_mismatch",
            "semantic_validation_failure",
            "commit_failure",
        }
        self.assertEqual(
            {item.value for item in FailureInjectionPoint},
            expected,
        )
        injector = FailureInjector(
            (FailureInjectionPoint.AFTER_SEND_BEFORE_RECEIPT_FAILURE,)
        )
        with self.assertRaises(InjectedExecutionFailure) as raised:
            injector.trip(
                FailureInjectionPoint.AFTER_SEND_BEFORE_RECEIPT_FAILURE,
                request_sent=True,
            )
        self.assertTrue(raised.exception.request_sent)
        injector.trip(
            FailureInjectionPoint.AFTER_SEND_BEFORE_RECEIPT_FAILURE,
            request_sent=True,
        )

    @staticmethod
    def _model_admission(contract_set):
        capability, model_profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,),
            model_profiles=(model_profile,),
            route_policies=(policy,),
            input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier(
                {(request.operation_id, request.attempt_id): request.fencing_token}
            ),
        )
        return capability, admission, request

    def _assert_common_backend_contract(
        self,
        backend,
        request: ExecutionRequest,
    ) -> None:
        report = BackendConformanceSuite.exercise_common(
            backend,
            request,
            replace(
                request,
                stable_idempotency_key=(
                    request.stable_idempotency_key + ":contract-drift"
                ),
            ),
        )
        self.assertTrue(report.duplicate_submit_stable)
        self.assertTrue(report.contract_conflict_rejected)
        self.assertTrue(report.attempt_binding_preserved)
        self.assertTrue(report.query_completed)
        self.assertTrue(report.usage_receipt_recorded)
        self.assertTrue(report.cost_receipt_recorded)
        self.assertTrue(report.cancellation_contract_returned)

    def _external_backend(
        self,
        scenario: str = "success",
        *,
        environment: str = "test",
    ):
        adapter = ScriptedExternalActionAdapter(scenario)
        profile_contract = _profile(
            backend_id="remote-external-action",
            runtime=ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
            qualification_ref=adapter.capability_profile.qualification_ref,
            callback=True,
            idempotency=True,
        )
        admission, request = _contracts(
            CapabilityId.PUBLISHING_RELEASE_SUBMIT,
            profile_contract,
            environment=environment,
        )
        store = InMemoryExecutionRecordStore()
        backend = RemoteExternalActionBackend(
            adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={
                            "release_package_ref": "asset-version:release:1"
                        },
                        input_text="",
                        working_directory=".",
                        timeout_seconds=30,
                        output_schema_version="external-action-receipt.v1",
                    )
                }
            ),
            record_store=store,
        )
        return backend, adapter, store, request

    def _agent_backend(self):
        runner = ScriptedAgentWorkspaceRunner()
        profile_contract = _profile(
            backend_id="agent-workspace",
            runtime=ExecutionRuntimeClass.AGENT_WORKSPACE_TRANSACTION,
            qualification_ref=runner.capability_profile.qualification_ref,
        )
        admission, request = _contracts(
            CapabilityId.AGENT_WORKSPACE_EXECUTE,
            profile_contract,
        )
        workspace_contract = AgentWorkspaceExecutionContract(
            workspace_snapshot_ref=request.workspace_snapshot_ref,
            read_set=("src", "tests"),
            write_set=("src", "tests"),
            allowed_tools=("rg", "apply_patch"),
            allowed_commands=(("rg", "--files"),),
            network_policy="DENY",
            git_base_sha=SHA,
            expected_output_contract="workspace-manifest.v1",
            maximum_agent_hops=1,
            maximum_files_changed=4,
            maximum_cost="0",
            approval_policy="AUTHORITY_REVIEW_REQUIRED",
        )
        store = InMemoryExecutionRecordStore()
        backend = AgentWorkspaceExecutionBackend(
            runner=runner,
            workspace_contracts=StaticAgentWorkspaceContractSource(
                (workspace_contract,)
            ),
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"task": "produce a bounded patch candidate"},
                        input_text="",
                        working_directory=".",
                        timeout_seconds=30,
                        output_schema_version="workspace-manifest.v1",
                    )
                }
            ),
            record_store=store,
        )
        return backend, store, request

    def test_external_action_duplicate_submit_contract_conflict_and_receipts(self) -> None:
        backend, adapter, store, request = self._external_backend()

        first = backend.submit(request)
        duplicate = backend.submit(request)
        with self.assertRaisesRegex(ValueError, "different request"):
            backend.submit(
                replace(request, stable_idempotency_key="external:contract-drift")
            )
        result = backend.reconcile(first)

        self.assertEqual(first, duplicate)
        self.assertEqual(adapter.submit_calls, 1)
        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertIsNone(first.provider_request_id)
        self.assertIsNotNone(first.external_request_id)
        self.assertIsNotNone(result.external_receipt_ref)
        self.assertEqual(
            store.read_evidence(result.usage_receipt_ref)["availability"],
            "UNAVAILABLE",
        )
        raw = store.read_evidence(result.raw_output_ref)
        self.assertTrue(raw["fixture_protocol_only"])
        self.assertFalse(raw["real_model_call"])
        self.assertFalse(raw["production_verified"])

    def test_external_action_unknown_is_queried_and_callbacks_are_deduplicated(self) -> None:
        backend, _adapter, _store, request = self._external_backend("unknown")
        handle = backend.submit(request)
        callback = ExternalActionCallbackReceipt(
            message_id="callback:external:1",
            external_request_id=handle.external_request_id,
            payload_hash="sha256:" + "c" * 64,
            outcome="success",
            evidence={
                "result": {"callback": "accepted"},
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            },
            verified=True,
        )

        first = backend.accept_callback(handle, callback)
        duplicate = backend.accept_callback(handle, callback)

        self.assertEqual(first.contract_hash, duplicate.contract_hash)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            backend.accept_callback(
                handle,
                replace(callback, payload_hash="sha256:" + "d" * 64),
            )

    def test_external_action_cancel_rejects_late_callback(self) -> None:
        backend, _adapter, _store, request = self._external_backend("unknown")
        handle = backend.submit(request)

        cancellation = backend.cancel(handle, "release was superseded")

        self.assertEqual(cancellation.outcome, "CANCELLED")
        self.assertIsNone(cancellation.provider_request_id)
        self.assertEqual(
            cancellation.external_request_id, handle.external_request_id
        )
        self.assertIsNotNone(cancellation.external_cancellation_receipt_ref)
        with self.assertRaisesRegex(ValueError, "late external callback"):
            backend.accept_callback(
                handle,
                ExternalActionCallbackReceipt(
                    message_id="callback:late:1",
                    external_request_id=handle.external_request_id,
                    payload_hash="sha256:" + "e" * 64,
                    outcome="success",
                    evidence={"result": {"late": True}},
                    verified=True,
                ),
            )

    def test_controlled_environment_rejects_external_action_fixture_adapter(self) -> None:
        with self.assertRaisesRegex(ValueError, "prohibited"):
            self._external_backend(environment="production")

    def test_agent_workspace_contract_blocks_escape_and_shell_operators(self) -> None:
        with self.assertRaisesRegex(ValueError, "bounded relative"):
            AgentWorkspaceExecutionContract(
                workspace_snapshot_ref="workspace:1",
                read_set=("../secret",),
                write_set=("src",),
                allowed_tools=("rg",),
                allowed_commands=(("rg", "--files"),),
                network_policy="DENY",
                git_base_sha=SHA,
                expected_output_contract="workspace-manifest.v1",
                maximum_agent_hops=1,
                maximum_files_changed=1,
                maximum_cost="0",
                approval_policy="AUTHORITY_REVIEW_REQUIRED",
            )
        with self.assertRaisesRegex(ValueError, "shell operators"):
            AgentWorkspaceExecutionContract(
                workspace_snapshot_ref="workspace:1",
                read_set=("src",),
                write_set=("src",),
                allowed_tools=("rg",),
                allowed_commands=(("rg", "--files", "|", "head"),),
                network_policy="DENY",
                git_base_sha=SHA,
                expected_output_contract="workspace-manifest.v1",
                maximum_agent_hops=1,
                maximum_files_changed=1,
                maximum_cost="0",
                approval_policy="AUTHORITY_REVIEW_REQUIRED",
            )

    def test_agent_workspace_backend_returns_candidate_and_never_commits(self) -> None:
        backend, store, request = self._agent_backend()

        first = backend.submit(request)
        duplicate = backend.submit(request)
        with self.assertRaisesRegex(ValueError, "different request"):
            backend.submit(replace(request, task_kind="agent.contract-drift"))
        result = backend.reconcile(first)
        cancellation = backend.cancel(first, "already materialized")

        self.assertEqual(first, duplicate)
        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        raw = store.read_evidence(result.raw_output_ref)
        self.assertEqual(raw["result"]["result_kind"], "workspace_manifest")
        self.assertTrue(raw["result"]["workspace_manifest"]["proposed_only"])
        self.assertTrue(raw["fixture_protocol_only"])
        self.assertFalse(raw["production_verified"])
        self.assertEqual(cancellation.outcome, "ALREADY_COMPLETED")
        self.assertIsNotNone(cancellation.backend_completion_receipt_ref)
        self.assertIsNone(cancellation.local_execution_receipt_id)

    def test_submit_reconcile_cancel_contract_is_shared_by_every_backend(self) -> None:
        self.assertEqual(
            {item.value for item in BackendConformanceSuite.scenarios},
            {item.value for item in BackendConformanceScenario},
        )
        scripted_contracts = model_contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        _capability, scripted_admission, scripted_request = (
            self._model_admission(scripted_contracts)
        )
        scripted_store = InMemoryExecutionRecordStore()
        scripted = ScriptedFixtureExecutionBackend(
            admission=scripted_admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    scripted_request.execution_id: ResolvedExecutionPayload(
                        request_payload={
                            "result": {"text": "scripted"},
                            "fixture_protocol_only": False,
                            "real_model_call": True,
                            "production_verified": True,
                        },
                        input_text="",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="structured-output.v1",
                    )
                }
            ),
            record_store=scripted_store,
        )

        remote_contracts = model_contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        remote_capability, remote_admission, remote_request = (
            self._model_admission(remote_contracts)
        )
        remote_adapter, _transport = _remote_adapter("success")
        remote = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=remote_capability,
            provider_adapter=remote_adapter,
            admission=remote_admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    remote_request.execution_id: ResolvedExecutionPayload(
                        request_payload={"input": {"chapter": 1}},
                        input_text="",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="structured-output.v1",
                    )
                }
            ),
            record_store=InMemoryExecutionRecordStore(),
        )

        external, _external_adapter, _external_store, external_request = (
            self._external_backend()
        )
        agent, _agent_store, agent_request = self._agent_backend()

        with tempfile.TemporaryDirectory() as tmp:
            codex_contracts = model_contracts(
                backend_id="codex-cli",
                runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            )
            _codex_capability, codex_admission, codex_request = (
                self._model_admission(codex_contracts)
            )
            execution_directory = PersistentExecutionDirectory(
                Path(tmp) / "executions"
            )
            result_path = execution_directory.prepare(
                codex_request.execution_id
            ).result_path("result.json")
            codex = CodexCliExecutionBackend(
                admission=codex_admission,
                payload_resolver=StaticExecutionPayloadResolver(
                    {
                        codex_request.execution_id: ResolvedExecutionPayload(
                            request_payload={"input": {"chapter": 1}},
                            input_text="",
                            working_directory=tmp,
                            timeout_seconds=5,
                            output_schema_version="structured-output.v1",
                            command=(
                                sys.executable,
                                "-c",
                                (
                                    "import json,sys; "
                                    "json.dump({'text':'codex'}, "
                                    "open(sys.argv[1], 'w'))"
                                ),
                                str(result_path),
                            ),
                        )
                    }
                ),
                record_store=InMemoryExecutionRecordStore(),
                supervisor=CodexProcessSupervisor(execution_directory),
                execution_policy=LocalProcessExecutionPolicy(
                    fixed_working_directory=tmp,
                    allowed_command_prefixes=((sys.executable,),),
                ),
            )

            cases = (
                ("scripted-fixture", scripted, scripted_request),
                ("remote-provider", remote, remote_request),
                ("codex-cli", codex, codex_request),
                ("remote-external-action", external, external_request),
                ("agent-workspace", agent, agent_request),
            )
            for backend_id, backend, request in cases:
                with self.subTest(backend_id=backend_id):
                    self._assert_common_backend_contract(backend, request)
            scripted_evidence = scripted_store.get_record(
                scripted_request.execution_id
            ).raw_evidence
            self.assertTrue(scripted_evidence["fixture_protocol_only"])
            self.assertFalse(scripted_evidence["real_model_call"])
            self.assertFalse(scripted_evidence["production_verified"])


if __name__ == "__main__":
    unittest.main()
