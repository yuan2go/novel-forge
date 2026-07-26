from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from novel_forge.modules.production_execution import (
    ArtifactPointer,
    CapabilityId,
    CompletionMode,
    CancellationOutcome,
    ExecutionCapabilityProfile,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
    InputManifest,
    ModelProfile,
    ModelProfileStatus,
    RoutePolicy,
    RouteSnapshot,
    default_capability_registry,
)
from novel_forge.modules.production_execution.gateway import (
    AdmissionController,
    ExecutionBackendRegistry,
    ProductionExecutionGateway,
    StaticAttemptFenceVerifier,
    StaticExecutionContractSource,
)
from novel_forge.modules.production_execution.routing import (
    ModelProfileRegistry,
    RoutePolicyRegistry,
    RouteRecommendation,
    RouteRecommendationReadModel,
    RouteResolver,
)
from novel_forge.modules.production_execution.legacy import (
    LegacyGatewayModelAdapter,
    LegacyRequestMapper,
    LegacyResultMapper,
    execute_legacy_model_operation,
)
from novel_forge.modules.production_execution.backends import (
    CodexCliExecutionBackend,
    InMemoryExecutionRecordStore,
    RemoteProviderExecutionBackend,
    ResolvedExecutionPayload,
    ScriptedFixtureExecutionBackend,
    StaticExecutionPayloadResolver,
)
from novel_forge.modules.production_execution.process_supervisor import (
    CodexProcessSupervisor,
    PersistentExecutionDirectory,
)
from novel_forge.modules.provider_control.contracts import ProviderReceipt
from novel_forge.modules.provider_control.openai_v2 import OpenAIProviderAdapterV2


SHA = "a" * 40
HASH = "sha256:" + hashlib.sha256(b"input").hexdigest()


class _RemoteTransport:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.last_request = None
        self.execute_calls = 0

    def execute(self, request):
        self.last_request = request
        self.execute_calls += 1
        return {
            "outcome": "success" if self.scenario == "success" else "unknown",
            "request_sent": True,
            "provider_request_id": f"provider-request:{request.stable_idempotency_key}",
            "provider_correlation_id": f"provider-correlation:{request.correlation_id}",
            "completion_mode": "synchronous" if self.scenario == "success" else "background",
            "evidence": {
                "result": {"text": "remote result"},
                "usage": {"input_tokens": 2, "output_tokens": 3},
                "cost": {"amount": "0.01", "currency": "USD"},
            },
        }

    def query(self, request):
        return {
            "outcome": "success",
            "request_sent": True,
            "provider_request_id": request.provider_request_id,
            "provider_correlation_id": request.provider_request_id,
            "completion_mode": "synchronous",
            "evidence": {
                "result": {"text": "queried remote result"},
                "usage": {"input_tokens": 2, "output_tokens": 3},
                "cost": {"amount": "0.01", "currency": "USD"},
            },
        }

    def cancel(self, request):
        return {
            "outcome": "cancelled",
            "request_sent": True,
            "provider_request_id": request.provider_request_id,
            "provider_correlation_id": request.provider_request_id,
            "completion_mode": "background",
            "evidence": {"cancelled": True},
        }

    def verify_callback(self, body, headers, *, secret):  # pragma: no cover
        raise NotImplementedError


def _remote_adapter(scenario: str):
    transport = _RemoteTransport(scenario)
    adapter = OpenAIProviderAdapterV2(
        transport,
        supports_query=True,
        supports_cancel=True,
        supports_callback=True,
        supports_cost_receipt=True,
        provider_idempotency_supported=True,
        real_provider_validation_eligible=False,
    )
    return adapter, transport


def contracts(*, backend_id: str, runtime: ExecutionRuntimeClass):
    definition = default_capability_registry().resolve(
        CapabilityId.PROSE_CHAPTER_DRAFT
    )
    completion_modes = (
        (CompletionMode.PROCESS_EXIT,)
        if runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
        else (CompletionMode.SYNCHRONOUS, CompletionMode.POLL)
    )
    capability = ExecutionCapabilityProfile(
        backend_id=backend_id,
        backend_version="1.0.0",
        runtime_class=runtime,
        supported_completion_modes=completion_modes,
        supported_reasoning_efforts=(
            ("low", "medium", "high", "xhigh", "max")
            if runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            else ("high", "xhigh")
        ),
        supports_query=True,
        supports_cancel=True,
        supports_callback=runtime is ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        supports_usage_receipt=runtime is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_cost_receipt=runtime is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_structured_output=True,
        supports_process_group_control=runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_persistent_execution_directory=runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_provider_idempotency=runtime is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        real_provider_validation_eligible=False,
        qualification_ref=f"capability-probe:{backend_id}:1",
    )
    profile = ModelProfile(
        profile_id=f"{backend_id}.default",
        profile_version=1,
        backend_id=backend_id,
        runtime_class=runtime,
        model_provider=(
            "openai" if runtime is ExecutionRuntimeClass.REMOTE_PROVIDER_API
            else "codex" if runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            else "fixture"
        ),
        model_id=(
            "gpt-test" if runtime is ExecutionRuntimeClass.REMOTE_PROVIDER_API
            else "codex-test" if runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            else "scripted-model"
        ),
        reasoning_effort="xhigh",
        timeout_policy_ref=definition.timeout_policy_ref,
        workspace_policy_ref="workspace:default",
        output_policy_ref="output:json",
        fallback_policy="FAIL_CLOSED",
        status=ModelProfileStatus.ACTIVE,
        capability_probe_ref=capability.qualification_ref,
    )
    policy = RoutePolicy(
        policy_id="chapter.production",
        policy_version=1,
        default_model_profile_id=profile.profile_id,
        allowed_model_profile_ids=(profile.profile_id,),
        rule_set_ref="route-rules:chapter:1",
        fallback_policy="FAIL_CLOSED",
        reasoning_downgrade_policy="PROHIBITED",
        status="ACTIVE",
    )
    route = RouteSnapshot(
        route_snapshot_id=f"route:{backend_id}:1",
        route_decision_id=f"decision:{backend_id}:1",
        operation_id="operation:1",
        attempt_id="attempt:1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        backend_id=backend_id,
        backend_version=capability.backend_version,
        runtime_host_id="host:test",
        auth_profile_ref="auth:test",
        model_profile_id=profile.profile_id,
        model_profile_version=profile.profile_version,
        model_provider=profile.model_provider,
        model_id=profile.model_id,
        requested_reasoning_effort="xhigh",
        reasoning_effort="xhigh",
        prompt_bundle_ref="prompt:chapter:1",
        skill_bundle_ref="skill:chapter:1",
        context_bundle_ref="context:chapter:1",
        output_schema_ref="schema:chapter:1",
        release_sha=SHA,
    )
    artifact = ArtifactPointer(
        artifact_ref="asset-version:plan:1",
        artifact_type="chapter_plan",
        content_hash=HASH,
        schema_version="chapter-plan.v3",
        source_eligibility="PRODUCTION_ELIGIBLE",
    )
    manifest = InputManifest(
        manifest_id="input-manifest:1",
        operation_id="operation:1",
        attempt_id="attempt:1",
        fencing_token=7,
        project_id="project:1",
        book_id="book:1",
        target_scope={"scope_kind": "chapter", "chapter": 1},
        context_bundle_ref=route.context_bundle_ref,
        prompt_bundle_ref=route.prompt_bundle_ref,
        skill_bundle_ref=route.skill_bundle_ref,
        canon_version_refs=("canon:1",),
        arc_version_refs=("arc:1",),
        input_artifacts=(artifact,),
        read_set=(artifact.artifact_ref,),
    )
    request = ExecutionRequest(
        execution_id="execution:1",
        operation_id="operation:1",
        root_operation_id="operation:1",
        saga_id="saga:1",
        attempt_id="attempt:1",
        fencing_token=7,
        project_id="project:1",
        workspace_id="workspace:1",
        book_id="book:1",
        target_scope={
            "scope_kind": "chapter",
            "scope_id": "chapter-number:1",
            "chapter_number": 1,
        },
        domain=definition.domain.value,
        task_kind="chapter.slice.run",
        stage="draft",
        capability=definition.capability_id.value,
        importance_class="HIGH",
        risk_class=definition.risk_class.value,
        route_snapshot_id=route.route_snapshot_id,
        workspace_snapshot_ref="workspace:1",
        input_manifest_ref=manifest.manifest_id,
        resource_claims=("provider:request",),
        timeout_policy_ref=definition.timeout_policy_ref,
        budget_policy_ref=definition.budget_policy_ref,
        permission_policy_ref=definition.permission_policy_ref,
        validation_policy_ref=definition.validation_policy_ref,
        commit_policy_ref=definition.commit_policy_ref,
        stable_idempotency_key="chapter:1:draft:attempt:1",
        trace_id="trace:1",
        correlation_id="correlation:1",
        external_effect_id="external-effect:1",
        budget_reservation_id="budget-reservation:1",
    )
    return capability, profile, policy, route, manifest, request


class ProductionExecutionGatewayTests(unittest.TestCase):
    def _gateway(self, backend, contract_set):
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,),
            model_profiles=(profile,),
            route_policies=(policy,),
            input_manifests=(manifest,),
        )
        verifier = StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7})
        admission = AdmissionController(source, verifier)
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        return ProductionExecutionGateway(registry, admission), request

    def test_scripted_fixture_is_attempt_bound_and_never_claims_provider_request(self) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        resolver = StaticExecutionPayloadResolver({
            request.execution_id: ResolvedExecutionPayload(
                request_payload={"result": {"text": "fixture"}},
                input_text="fixture input",
                working_directory=".",
                timeout_seconds=5,
                output_schema_version="chapter-draft.v1",
            )
        })
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        verifier = StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7})
        admission = AdmissionController(source, verifier)
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=resolver,
            record_store=InMemoryExecutionRecordStore(),
        )
        gateway, request = self._gateway(backend, contract_set)

        handle = gateway.submit(request)
        result = gateway.reconcile(handle)

        self.assertEqual(handle.transport, ExecutionRuntimeClass.SCRIPTED_FIXTURE)
        self.assertIsNone(handle.provider_request_id)
        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual((result.operation_id, result.attempt_id, result.fencing_token), ("operation:1", "attempt:1", 7))
        self.assertIsNotNone(result.output_manifest_ref)
        self.assertIsNotNone(result.validation_report_ref)

    def test_stale_fencing_token_is_rejected_before_backend_submission(self) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 8}),
        )
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": {"text": "must not run"}},
                    input_text="fixture", working_directory=".", timeout_seconds=5,
                    output_schema_version="chapter-draft.v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        with self.assertRaisesRegex(ValueError, "stale Authority fencing token"):
            gateway.submit(request)

    def test_structurally_corrupt_fixture_result_is_not_materialized_as_success(self) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": {}}, input_text="fixture",
                    working_directory=".", timeout_seconds=5,
                    output_schema_version="chapter-draft.v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        with self.assertRaisesRegex(ValueError, "non-empty structured result"):
            gateway.reconcile(gateway.submit(request))

    def test_remote_backend_adapts_provider_v2_without_losing_provider_handle(self) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        adapter, transport = _remote_adapter("success")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"input": {"chapter": 1}},
                    input_text="provider payload", working_directory=".", timeout_seconds=30,
                    output_schema_version="chapter-draft.v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        handle = gateway.submit(request)
        result = gateway.reconcile(handle)

        self.assertTrue(handle.provider_request_id.startswith("provider-request:"))
        self.assertEqual(handle.transport, ExecutionRuntimeClass.REMOTE_PROVIDER_API)
        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual(transport.last_request.operation_id, request.operation_id)
        self.assertEqual(transport.last_request.external_effect_id, request.external_effect_id)
        self.assertEqual(transport.last_request.budget_reservation_id, request.budget_reservation_id)

        duplicate = gateway.submit(request)
        self.assertEqual(duplicate.contract_hash, handle.contract_hash)
        self.assertEqual(transport.execute_calls, 1)
        with self.assertRaisesRegex(ValueError, "different request"):
            gateway.submit(
                replace(request, stable_idempotency_key="chapter:1:draft:conflict")
            )

    def test_admission_rejects_capability_domain_or_policy_drift(self) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,),
            model_profiles=(profile,),
            route_policies=(policy,),
            input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )

        with self.assertRaisesRegex(ValueError, "domain"):
            admission.admit(
                replace(
                    request,
                    capability=CapabilityId.REVISION_CHAPTER_REVISE.value,
                ),
                capability,
            )
        with self.assertRaisesRegex(ValueError, "validation policy"):
            admission.admit(
                replace(request, validation_policy_ref="validation:drift:v9"),
                capability,
            )
        with self.assertRaisesRegex(ValueError, "risk class"):
            admission.admit(
                replace(request, risk_class="CRITICAL"),
                capability,
            )

    def test_registry_rejects_duplicate_backend_identity(self) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(source, StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}))
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": {"text": "fixture"}}, input_text="fixture",
                    working_directory=".", timeout_seconds=5, output_schema_version="v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(backend)

    def test_codex_cli_backend_uses_persistent_process_receipt_without_provider_id(self) -> None:
        contract_set = contracts(
            backend_id="codex-cli",
            runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = PersistentExecutionDirectory(Path(tmp) / "executions")
            result_path = directory.prepare(request.execution_id).result_path("result.json")
            command = (
                sys.executable,
                "-c",
                "import json,sys; json.dump({'text':'codex fixture process'}, open(sys.argv[1], 'w'))",
                str(result_path),
            )
            backend = CodexCliExecutionBackend(
                admission=admission,
                payload_resolver=StaticExecutionPayloadResolver({
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"input": {"chapter": 1}},
                        input_text="bounded prompt",
                        working_directory=tmp,
                        timeout_seconds=5,
                        output_schema_version="chapter-draft.v1",
                        command=command,
                    )
                }),
                record_store=InMemoryExecutionRecordStore(),
                supervisor=CodexProcessSupervisor(directory),
            )
            registry = ExecutionBackendRegistry()
            registry.register(backend)
            gateway = ProductionExecutionGateway(registry, admission)

            handle = gateway.submit(request)
            result = gateway.reconcile(handle)

            self.assertIsNotNone(handle.local_execution_receipt_id)
            self.assertIsNone(handle.provider_request_id)
            self.assertEqual(handle.transport, ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
            self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
            receipt = directory.read_receipt(request.execution_id)
            self.assertTrue(receipt.authority_bound)
            self.assertIsNone(receipt.provider_request_id)

    def test_remote_unknown_is_reconciled_by_provider_query(self) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        adapter, _transport = _remote_adapter("unknown_after_send")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"input": {"chapter": 1}}, input_text="provider",
                    working_directory=".", timeout_seconds=30,
                    output_schema_version="chapter-draft.v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        handle = gateway.submit(request)
        result = gateway.reconcile(handle)

        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertIsNotNone(result.provider_receipt_ref)

    def test_remote_callback_is_deduplicated_and_materialized_as_execution_result(self) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        adapter, _transport = _remote_adapter("unknown_after_send")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"input": {"chapter": 1}}, input_text="provider",
                    working_directory=".", timeout_seconds=30,
                    output_schema_version="chapter-draft.v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)
        handle = gateway.submit(request)
        receipt = ProviderReceipt(
            provider_request_id=handle.provider_request_id,
            receipt_id="provider-receipt:1",
            message_id="provider-message:1",
            outcome="success",
            payload_hash="sha256:" + "b" * 64,
            evidence={
                "result": {"text": "callback result"},
                "usage": {"input_tokens": 2, "output_tokens": 3},
                "cost": {"amount": "0.01", "currency": "USD"},
            },
        )

        first = gateway.accept_callback(handle, receipt)
        duplicate = gateway.accept_callback(handle, receipt)

        self.assertEqual(first.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual(first.contract_hash, duplicate.contract_hash)

        conflicting = ProviderReceipt(
            provider_request_id=handle.provider_request_id,
            receipt_id="provider-receipt:conflict",
            message_id=receipt.message_id,
            outcome="final_failure",
            payload_hash="sha256:" + "c" * 64,
            evidence={"error": "conflict"},
        )
        with self.assertRaisesRegex(ValueError, "conflicting callback"):
            gateway.accept_callback(handle, conflicting)

    def test_remote_cancel_preserves_upstream_provider_receipt(self) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        capability, profile, policy, route, manifest, request = contract_set
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        adapter, _transport = _remote_adapter("unknown_after_send")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"input": {"chapter": 1}}, input_text="provider",
                    working_directory=".", timeout_seconds=30,
                    output_schema_version="chapter-draft.v1",
                )
            }),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        handle = gateway.submit(request)
        cancellation = gateway.cancel(handle, "operator requested")

        self.assertEqual(cancellation.outcome, CancellationOutcome.CANCELLED)
        self.assertIsNotNone(cancellation.provider_request_id)
        self.assertIsNotNone(cancellation.provider_cancellation_receipt_ref)
        self.assertEqual(gateway.reconcile(handle).outcome, ExecutionOutcome.CANCELLED)
        with self.assertRaisesRegex(ValueError, "late provider callback"):
            gateway.accept_callback(
                handle,
                ProviderReceipt(
                    provider_request_id=handle.provider_request_id,
                    receipt_id="late-receipt:1",
                    message_id="late-message:1",
                    outcome="success",
                    payload_hash="sha256:" + "d" * 64,
                    evidence={
                        "result": {"text": "late"},
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                        "cost": {"amount": "0", "currency": "USD"},
                    },
                ),
            )

    def test_route_resolver_uses_stable_profile_alias_and_freezes_release(self) -> None:
        capability, profile, policy, _route, _manifest, _request = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        resolver = RouteResolver(
            ModelProfileRegistry((profile,)),
            RoutePolicyRegistry((policy,)),
            {capability.backend_id: capability},
            RouteRecommendationReadModel((
                RouteRecommendation(
                    task_kind="chapter.slice.run",
                    risk_class="NORMAL",
                    model_profile_id=profile.profile_id,
                    evidence_ref="route-recommendation:1",
                ),
            )),
        )

        route = resolver.freeze(
            route_snapshot_id="route:frozen:1",
            route_decision_id="decision:frozen:1",
            operation_id="operation:1",
            attempt_id="attempt:1",
            policy_id=policy.policy_id,
            task_kind="chapter.slice.run",
            risk_class="NORMAL",
            requested_reasoning_effort="xhigh",
            runtime_host_id="host:1",
            auth_profile_ref="auth:1",
            prompt_bundle_ref="prompt:1",
            skill_bundle_ref="skill:1",
            context_bundle_ref="context:1",
            output_schema_ref="schema:1",
            release_sha=SHA,
        )

        self.assertEqual(route.model_profile_id, profile.profile_id)
        self.assertEqual(route.model_id, profile.model_id)
        self.assertEqual(route.release_sha, SHA)

    def test_route_resolver_rejects_xhigh_to_high_downgrade(self) -> None:
        capability, profile, policy, _route, _manifest, _request = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        )
        resolver = RouteResolver(
            ModelProfileRegistry((profile,)),
            RoutePolicyRegistry((policy,)),
            {capability.backend_id: capability},
        )
        with self.assertRaisesRegex(ValueError, "silently downgraded"):
            resolver.freeze(
                route_snapshot_id="route:frozen:1",
                route_decision_id="decision:frozen:1",
                operation_id="operation:1",
                attempt_id="attempt:1",
                policy_id=policy.policy_id,
                task_kind="chapter.slice.run",
                risk_class="NORMAL",
                requested_reasoning_effort="high",
                runtime_host_id="host:1",
                auth_profile_ref="auth:1",
                prompt_bundle_ref="prompt:1",
                skill_bundle_ref="skill:1",
                context_bundle_ref="context:1",
                output_schema_ref="schema:1",
                release_sha=SHA,
            )

    def test_legacy_adapter_maps_only_frozen_attempt_bound_request_to_gateway(self) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        request = replace(request, stage="generate")
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,),
        )
        admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        store = InMemoryExecutionRecordStore()
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": {"text": "through gateway"}},
                    input_text="frozen prompt", working_directory=".",
                    timeout_seconds=5, output_schema_version="draft.v1",
                )
            }),
            record_store=store,
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        adapter = LegacyGatewayModelAdapter(
            name="legacy-gateway",
            gateway=ProductionExecutionGateway(registry, admission),
            result_mapper=LegacyResultMapper(store),
        )
        prompt = "frozen prompt"
        result = adapter.generate(
            prompt,
            {
                "execution_request": request,
                "legacy_input_digest": LegacyRequestMapper.input_digest(
                    "generate", prompt
                ),
            },
        )

        self.assertEqual(result["text"], "through gateway")
        self.assertEqual(
            result["production_execution"]["attempt_id"], request.attempt_id
        )
        with self.assertRaisesRegex(ValueError, "frozen attempt-bound"):
            adapter.generate(prompt, {})

    def test_production_environment_rejects_non_gateway_legacy_adapter(self) -> None:
        class DirectAdapter:
            legacy_independent_execution = True

            def generate(self, prompt, context=None):  # pragma: no cover
                return {"text": prompt}

        with self.assertRaisesRegex(RuntimeError, "legacy direct model adapters"):
            execute_legacy_model_operation(
                DirectAdapter(),
                "generate",
                "must not execute",
                {"runtime_environment": "production"},
            )


if __name__ == "__main__":
    unittest.main()
