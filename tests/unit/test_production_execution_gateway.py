from __future__ import annotations

import hashlib
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from novel_forge.modules.production_execution import (
    ArtifactPointer,
    CapabilityId,
    CompletionMode,
    CancellationOutcome,
    ExecutionCapabilityProfile,
    ExecutionOutcome,
    ExecutionRecoveryAction,
    ExecutionRecoveryAuthorization,
    ExecutionRequest,
    ExecutionRuntimeClass,
    FallbackPolicy,
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
    FallbackPolicyRegistry,
    ModelProfileRegistry,
    RoutePolicyRegistry,
    RouteRecommendation,
    RouteRecommendationReadModel,
    RouteResolver,
)
from novel_forge.modules.production_execution.backends import (
    CodexCliExecutionBackend,
    InMemoryExecutionRecordStore,
    LocalProcessExecutionPolicy,
    RemoteProviderExecutionBackend,
    ResolvedExecutionPayload,
    ScriptedFixtureExecutionBackend,
    StaticExecutionPayloadResolver,
)
from novel_forge.modules.production_execution.process_supervisor import (
    CodexProcessSupervisor,
    PersistentExecutionDirectory,
    ProcessReceiptStatus,
)
from novel_forge.modules.provider_control.contracts import ProviderReceipt
from novel_forge.modules.provider_control.openai_v2 import OpenAIProviderAdapterV2
from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    TokenAccountingContract,
    prepare_provider_admission,
)


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
        if self.scenario == "raise_after_send":
            raise ConnectionError("connection lost after request submission")
        return {
            "outcome": "success" if self.scenario == "success" else "unknown",
            "request_sent": True,
            "provider_request_id": f"provider-request:{request.stable_idempotency_key}",
            "provider_correlation_id": f"provider-correlation:{request.correlation_id}",
            "completion_mode": "synchronous"
            if self.scenario == "success"
            else "background",
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


def _admitted_remote_payload(request: ExecutionRequest, text: str) -> ResolvedExecutionPayload:
    envelope = ProviderRequestEnvelope(
        provider="openai",
        model="gpt-test",
        protocol="openai-responses-text-envelope-v1",
        input_text=text,
        max_output_tokens=64,
        timeout_seconds=30,
        stable_idempotency_key=request.stable_idempotency_key,
    )
    contract = TokenAccountingContract(
        provider="openai",
        model="gpt-test",
        route_identity="route:unit-test",
        meter_identity="openai-byte-token-upper-bound",
        meter_version="v1",
        accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1",
        precision="PROVEN_UPPER_BOUND",
        evidence_ref="token-proof:openai-byte-fallback:v1",
        serialization_contract=envelope.protocol,
        model_context_limit=4096,
        execution_token_limit=4096,
        output_reserve=64,
        safety_margin=32,
        framing_overhead=16,
    )
    receipt = prepare_provider_admission(
        envelope,
        contract,
        complete_request_coverage=(
            "system_runtime_instructions",
            "prompt_template",
            "skill_instructions",
            "tool_policy_and_schemas",
            "structured_output_schema",
            "context_bundle",
            "request_envelope_and_framing",
            "output_reserve",
            "safety_margin",
        ),
    )
    return ResolvedExecutionPayload(
        request_payload=envelope.to_dict(),
        input_text=text,
        working_directory=".",
        timeout_seconds=30,
        output_schema_version="chapter-draft.v1",
        capability_evidence={"provider_admission": receipt.to_dict()},
    )


def contracts(*, backend_id: str, runtime: ExecutionRuntimeClass):
    definition = default_capability_registry().resolve(CapabilityId.PROSE_CHAPTER_DRAFT)
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
        supports_usage_receipt=runtime
        is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_cost_receipt=runtime
        is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_structured_output=True,
        supports_process_group_control=runtime
        is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_persistent_execution_directory=runtime
        is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        supports_provider_idempotency=runtime
        is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        real_provider_validation_eligible=False,
        qualification_ref=f"capability-probe:{backend_id}:1",
    )
    profile = ModelProfile(
        profile_id=f"{backend_id}.default",
        profile_version=1,
        backend_id=backend_id,
        runtime_class=runtime,
        model_provider=(
            "openai"
            if runtime is ExecutionRuntimeClass.REMOTE_PROVIDER_API
            else "codex"
            if runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            else "fixture"
        ),
        model_id=(
            "gpt-test"
            if runtime is ExecutionRuntimeClass.REMOTE_PROVIDER_API
            else "codex-test"
            if runtime is ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
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
        fallback_policy_ref="chapter.production.fail-closed",
        fallback_policy_version=1,
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
        model_profile_hash=profile.contract_hash,
        route_policy_hash=policy.contract_hash,
        model_provider=profile.model_provider,
        model_id=profile.model_id,
        requested_reasoning_effort="xhigh",
        reasoning_effort="xhigh",
        prompt_bundle_ref="prompt:chapter:1",
        skill_bundle_ref="skill:chapter:1",
        context_bundle_ref="context:chapter:1",
        output_schema_ref="schema:chapter:1",
        release_sha=SHA,
        fallback_policy_ref=policy.fallback_policy_ref,
        fallback_policy_version=policy.fallback_policy_version,
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
        context_bundle_version=route.context_bundle_ref,
        prompt_bundle_version=route.prompt_bundle_ref,
        skill_bundle_version=route.skill_bundle_ref,
        canon_snapshot_version="canon:1",
        story_state_version="story-state:none",
        planning_version=artifact.asset_version_id,
        quality_profile_version="quality:1",
        source_policy_ref=definition.source_policy_ref,
        source_eligibility="PRODUCTION_ELIGIBLE",
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
    def _model_call_evidence(self, contract_set, gateway, store, handle, result,
                             *, eligible=True, frozen_model=None):
        from novel_forge.modules.chapter_authority.execution_gateway import (
            ChapterExecutionBinding, ChapterExecutionGatewaySession,
            ProductionExecutionGatewayExternalEffectAdapter,
        )

        _, _, _, route, manifest, request = contract_set
        adapter = object.__new__(ProductionExecutionGatewayExternalEffectAdapter)
        adapter.database_url = "postgresql://fixture/not-accessed"
        runtime = MagicMock()
        cursor = runtime.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            {"real_provider_validation_eligible": eligible},
            {"stage": request.stage, "_production_execution": {"capability_runtime": {
                "provider_request_identity": {"provider": route.model_provider,
                    "model": frozen_model or route.model_id},
            }}}, route.model_id,
        )
        with patch("novel_forge.modules.chapter_authority.execution_gateway.get_database_runtime", return_value=runtime):
            return adapter._evidence(
                binding=ChapterExecutionBinding(request, route, manifest),
                session=ChapterExecutionGatewaySession(gateway, store),
                handle=handle, result=result,
            )

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

    def test_scripted_fixture_is_attempt_bound_and_never_claims_provider_request(
        self,
    ) -> None:
        contract_set = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        capability, profile, policy, route, manifest, request = contract_set
        resolver = StaticExecutionPayloadResolver(
            {
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": {"text": "fixture"}},
                    input_text="fixture input",
                    working_directory=".",
                    timeout_seconds=5,
                    output_schema_version="chapter-draft.v1",
                )
            }
        )
        source = StaticExecutionContractSource(
            route_snapshots=(route,),
            model_profiles=(profile,),
            route_policies=(policy,),
            input_manifests=(manifest,),
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
        self.assertEqual(
            (result.operation_id, result.attempt_id, result.fencing_token),
            ("operation:1", "attempt:1", 7),
        )
        self.assertIsNotNone(result.output_manifest_ref)
        self.assertIsNotNone(result.validation_report_ref)

    def test_stale_fencing_token_is_rejected_before_backend_submission(self) -> None:
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
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 8}),
        )
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"result": {"text": "must not run"}},
                        input_text="fixture",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="chapter-draft.v1",
                    )
                }
            ),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        with self.assertRaisesRegex(ValueError, "stale Authority fencing token"):
            gateway.submit(request)

    def test_recovery_authorization_keeps_original_execution_fence_immutable(
        self,
    ) -> None:
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
        initial_admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
        )
        store = InMemoryExecutionRecordStore()
        backend = ScriptedFixtureExecutionBackend(
            admission=initial_admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"result": {"text": "fixture"}},
                        input_text="fixture",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="chapter-draft.v1",
                    )
                }
            ),
            record_store=store,
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        initial_gateway = ProductionExecutionGateway(registry, initial_admission)
        handle = initial_gateway.submit(request)

        recovery_admission = AdmissionController(
            source,
            StaticAttemptFenceVerifier(
                {("operation:1", "attempt:1"): 8},
                owners={("operation:1", "attempt:1"): "worker:new"},
            ),
        )
        backend.admission = recovery_admission
        recovery_gateway = ProductionExecutionGateway(registry, recovery_admission)
        authorization = ExecutionRecoveryAuthorization(
            authorization_id="recovery:execution:1:fence:8:consume",
            execution_id=request.execution_id,
            external_effect_id=request.external_effect_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            execution_fencing_token=7,
            recovery_fencing_token=8,
            recovery_worker_id="worker:new",
            action=ExecutionRecoveryAction.CONSUME_RESULT,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )

        with self.assertRaisesRegex(ValueError, "stale Authority fencing token"):
            recovery_gateway.submit(request)
        result = recovery_gateway.recover_existing_execution(
            request,
            handle,
            authorization,
        )

        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual(result.fencing_token, 7)
        self.assertEqual(
            store.get_record(request.execution_id).request.fencing_token, 7
        )

    def test_planned_recovery_dispatches_once_under_current_recovery_fence(
        self,
    ) -> None:
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
            StaticAttemptFenceVerifier(
                {("operation:1", "attempt:1"): 8},
                owners={("operation:1", "attempt:1"): "worker:new"},
            ),
        )
        store = InMemoryExecutionRecordStore()
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"result": {"text": "fixture"}},
                        input_text="fixture",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="chapter-draft.v1",
                    )
                }
            ),
            record_store=store,
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)
        authorization = ExecutionRecoveryAuthorization(
            authorization_id="recovery:execution:1:fence:8:dispatch",
            execution_id=request.execution_id,
            external_effect_id=request.external_effect_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            execution_fencing_token=7,
            recovery_fencing_token=8,
            recovery_worker_id="worker:new",
            action=ExecutionRecoveryAction.DISPATCH_PLANNED,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )

        first = gateway.resume_planned_execution(request, authorization)
        second = gateway.resume_planned_execution(request, authorization)

        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(
            store.get_record(request.execution_id).request.fencing_token, 7
        )

    def test_structurally_corrupt_fixture_result_is_not_materialized_as_success(
        self,
    ) -> None:
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
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"result": {}},
                        input_text="fixture",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="chapter-draft.v1",
                    )
                }
            ),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        with self.assertRaisesRegex(ValueError, "non-empty structured result"):
            gateway.reconcile(gateway.submit(request))

    def test_remote_schema_rejection_preserves_result_diagnostic_and_settlement(self):
        capability, profile, policy, route, manifest, request = contracts(
            backend_id="remote-provider", runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API)
        source = StaticExecutionContractSource(
            route_snapshots=(route,), model_profiles=(profile,),
            route_policies=(policy,), input_manifests=(manifest,))
        admission = AdmissionController(
            source, StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}))
        adapter, transport = _remote_adapter("success")

        def validate(stage, schema, value):
            from novel_forge.modules.chapter_authority.provider_output_contracts import (
                validate_chapter_provider_output_against_schema,
            )
            return validate_chapter_provider_output_against_schema(stage, schema, value)

        payload = replace(_admitted_remote_payload(request, "provider payload"),
            output_schema={"$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object", "properties": {}, "additionalProperties": False})
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider", capability_profile=capability,
            provider_adapter=adapter, admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({request.execution_id: payload}),
            record_store=InMemoryExecutionRecordStore(), structured_result_validator=validate)
        handle = backend.submit(request)
        first = backend.reconcile(handle)
        self.assertEqual(backend.reconcile(handle), first)
        record = backend.record_store.get_record(request.execution_id)
        self.assertEqual(record.provider_result.outcome, "final_failure")
        evidence = record.raw_evidence
        self.assertEqual(evidence["result"], {"text": "remote result"})
        self.assertEqual(evidence["failure_class"], "SCHEMA_REJECTION")
        self.assertIn("text is not allowed", evidence["output_validation_error"]["detail"])
        self.assertEqual(evidence["usage"]["output_tokens"], 3)
        self.assertEqual(evidence["cost"]["amount"], "0.01")
        self.assertEqual(transport.execute_calls, 1)

    def test_remote_backend_adapts_provider_v2_without_losing_provider_handle(
        self,
    ) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
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
        adapter, transport = _remote_adapter("success")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: _admitted_remote_payload(
                        request, "provider payload"
                    )
                }
            ),
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
        self.assertEqual(
            transport.last_request.external_effect_id, request.external_effect_id
        )
        self.assertEqual(
            transport.last_request.budget_reservation_id, request.budget_reservation_id
        )
        for eligible, frozen_model, expected in (
            (False, None, False), (True, None, True), (True, "drifted-model", False),
        ):
            with self.subTest(eligible=eligible, frozen_model=frozen_model):
                evidence = self._model_call_evidence(contract_set, gateway,
                    backend.record_store, handle, result,
                    eligible=eligible, frozen_model=frozen_model)
                self.assertEqual(evidence["real_model_call"], expected)
        record = backend.record_store.get_record(request.execution_id)
        for flags in ({"fixture_protocol_only": True}, {"real_model_call": False}):
            with self.subTest(receipt_flags=flags):
                record.raw_evidence.update(flags)
                evidence = self._model_call_evidence(contract_set, gateway,
                    backend.record_store, handle, result)
                self.assertFalse(evidence["real_model_call"])
                for key in flags:
                    record.raw_evidence.pop(key)
        receipt = record.provider_result
        record.provider_result = None
        self.assertFalse(self._model_call_evidence(contract_set, gateway,
            backend.record_store, handle, result)["real_model_call"])
        record.provider_result = receipt

        duplicate = gateway.submit(request)
        self.assertEqual(duplicate.contract_hash, handle.contract_hash)
        self.assertEqual(transport.execute_calls, 1)
        with self.assertRaisesRegex(ValueError, "different request"):
            gateway.submit(
                replace(request, stable_idempotency_key="chapter:1:draft:conflict")
            )

    def test_remote_unknown_submission_checkpoint_prevents_blind_resubmit(self) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
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
        adapter, transport = _remote_adapter("raise_after_send")
        store = InMemoryExecutionRecordStore()
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: _admitted_remote_payload(
                        request, "provider payload"
                    )
                }
            ),
            record_store=store,
        )

        with self.assertRaises(ConnectionError):
            backend.submit(request)
        restarted_handle = backend.submit(request)

        self.assertEqual(transport.execute_calls, 1)
        self.assertIsNone(restarted_handle.provider_request_id)
        self.assertEqual(
            store.get_record(request.execution_id).raw_evidence["submission_phase"],
            "PROVIDER_OUTCOME_UNKNOWN",
        )
        with self.assertRaisesRegex(ValueError, "no Provider v2 result"):
            backend.reconcile(restarted_handle)

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
        drifted_manifest = replace(
            manifest,
            source_policy_ref="source:unqualified:v9",
        )
        drifted_source = StaticExecutionContractSource(
            route_snapshots=(route,),
            model_profiles=(profile,),
            route_policies=(policy,),
            input_manifests=(drifted_manifest,),
        )
        with self.assertRaisesRegex(ValueError, "source policy"):
            AdmissionController(
                drifted_source,
                StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}),
            ).admit(request, capability)

    def test_registry_rejects_duplicate_backend_identity(self) -> None:
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
            source, StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7})
        )
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: ResolvedExecutionPayload(
                        request_payload={"result": {"text": "fixture"}},
                        input_text="fixture",
                        working_directory=".",
                        timeout_seconds=5,
                        output_schema_version="v1",
                    )
                }
            ),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(backend)

    def test_admission_rejects_version_alias_content_drift_by_frozen_hash(self) -> None:
        capability, profile, policy, route, manifest, request = contracts(
            backend_id="scripted-fixture",
            runtime=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        )
        fence = StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7})
        drifted_profile = replace(profile, model_id="same-version-drifted-model")
        with self.assertRaisesRegex(ValueError, "ModelProfile hash"):
            AdmissionController(
                StaticExecutionContractSource(
                    route_snapshots=(route,),
                    model_profiles=(drifted_profile,),
                    route_policies=(policy,),
                    input_manifests=(manifest,),
                ),
                fence,
            ).admit(request, capability)

        drifted_policy = replace(policy, rule_set_ref="route-rules:drifted:v9")
        with self.assertRaisesRegex(ValueError, "RoutePolicy hash"):
            AdmissionController(
                StaticExecutionContractSource(
                    route_snapshots=(route,),
                    model_profiles=(profile,),
                    route_policies=(drifted_policy,),
                    input_manifests=(manifest,),
                ),
                fence,
            ).admit(request, capability)

    def test_codex_cli_backend_uses_persistent_process_receipt_without_provider_id(
        self,
    ) -> None:
        contract_set = contracts(
            backend_id="codex-cli",
            runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
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
        with tempfile.TemporaryDirectory() as tmp:
            directory = PersistentExecutionDirectory(Path(tmp) / "executions")
            record_store = InMemoryExecutionRecordStore()
            result_path = directory.prepare(request.execution_id).result_path(
                "result.json"
            )
            command = (
                sys.executable,
                "-c",
                "import json,sys; json.dump({'text':'codex fixture process'}, open(sys.argv[1], 'w'))",
                str(result_path),
            )
            backend = CodexCliExecutionBackend(
                admission=admission,
                payload_resolver=StaticExecutionPayloadResolver(
                    {
                        request.execution_id: ResolvedExecutionPayload(
                            request_payload={"input": {"chapter": 1}},
                            input_text="bounded prompt",
                            working_directory=tmp,
                            timeout_seconds=5,
                            output_schema_version="chapter-draft.v1",
                            command=command,
                        )
                    }
                ),
                record_store=record_store,
                supervisor=CodexProcessSupervisor(directory),
                execution_policy=LocalProcessExecutionPolicy(
                    fixed_working_directory=tmp,
                    allowed_command_prefixes=((sys.executable,),),
                    maximum_result_bytes=1_000_000,
                ),
            )
            registry = ExecutionBackendRegistry()
            registry.register(backend)
            gateway = ProductionExecutionGateway(registry, admission)

            handle = gateway.submit(request)
            result = gateway.reconcile(handle)

            self.assertIsNotNone(handle.local_execution_receipt_id)
            self.assertIsNone(handle.provider_request_id)
            self.assertEqual(
                handle.transport, ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            )
            self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
            self.assertEqual(
                record_store.read_evidence(result.usage_receipt_ref)["availability"],
                "UNAVAILABLE",
            )
            self.assertEqual(
                record_store.read_evidence(result.cost_receipt_ref)["availability"],
                "UNAVAILABLE",
            )
            receipt = directory.read_receipt(request.execution_id)
            self.assertTrue(receipt.authority_bound)
            self.assertIsNone(receipt.provider_request_id)
            self.assertFalse(self._model_call_evidence(contract_set, gateway,
                record_store, handle, result)["real_model_call"])
            record = record_store.get_record(request.execution_id)
            record.raw_evidence.update({"terminal_event_observed": True,
                "usage": {"measurement": "MEASURED", "total_tokens": 5}})
            self.assertTrue(self._model_call_evidence(contract_set, gateway,
                record_store, handle, result)["real_model_call"])
            self.assertFalse(self._model_call_evidence(contract_set, gateway,
                record_store, handle, result, eligible=False)["real_model_call"])

    def test_codex_cli_backend_cancels_running_verified_process_only(self) -> None:
        contract_set = contracts(
            backend_id="codex-cli",
            runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
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
        with tempfile.TemporaryDirectory() as tmp:
            directory = PersistentExecutionDirectory(Path(tmp) / "executions")
            record_store = InMemoryExecutionRecordStore()
            result_path = directory.prepare(request.execution_id).result_path(
                "result.json"
            )
            ready_path = Path(tmp) / "codex-cancel-ready"
            backend = CodexCliExecutionBackend(
                admission=admission,
                payload_resolver=StaticExecutionPayloadResolver(
                    {
                        request.execution_id: ResolvedExecutionPayload(
                            request_payload={"input": {"chapter": 1}},
                            input_text="bounded prompt",
                            working_directory=tmp,
                            timeout_seconds=10,
                            output_schema_version="chapter-draft.v1",
                            command=(
                                sys.executable,
                                "-c",
                                (
                                    "import json,pathlib,signal,sys,time; "
                                    "result_path=sys.argv[1]; ready=pathlib.Path(sys.argv[2]); "
                                    "signal.signal(signal.SIGTERM, lambda *_: "
                                    "(json.dump({'late': True}, open(result_path, 'w')), "
                                    "sys.exit(0))); "
                                    "ready.write_text('ready'); time.sleep(30)"
                                ),
                                str(result_path),
                                str(ready_path),
                            ),
                        )
                    }
                ),
                record_store=record_store,
                supervisor=CodexProcessSupervisor(directory),
                execution_policy=LocalProcessExecutionPolicy(
                    fixed_working_directory=tmp,
                    allowed_command_prefixes=((sys.executable,),),
                    maximum_result_bytes=1_000_000,
                ),
            )

            with ThreadPoolExecutor(max_workers=1) as pool:
                submitted = pool.submit(backend.submit, request)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    receipt = directory.read_receipt(request.execution_id)
                    if (
                        receipt is not None
                        and receipt.status is ProcessReceiptStatus.RUNNING
                        and ready_path.exists()
                    ):
                        break
                    time.sleep(0.01)
                else:
                    self.fail("Codex process never reached RUNNING")
                provisional = record_store.get_record(request.execution_id).handle
                cancellation = backend.cancel(
                    provisional, "bounded operation cancelled"
                )
                handle = submitted.result(timeout=3)

            self.assertEqual(cancellation.outcome, CancellationOutcome.CANCELLED)
            self.assertEqual(cancellation.local_termination_outcome, "TERMINATED")
            self.assertEqual(
                cancellation.upstream_cancellation_outcome, "NOT_APPLICABLE"
            )
            self.assertIsNone(cancellation.provider_request_id)
            self.assertIsNotNone(cancellation.local_execution_receipt_id)
            persisted_record = record_store.get_record(request.execution_id)
            self.assertTrue(persisted_record.raw_evidence["late_result_quarantined"])
            self.assertNotIn("result", persisted_record.raw_evidence)
            self.assertEqual(
                backend.reconcile(handle).outcome, ExecutionOutcome.CANCELLED
            )

    def test_remote_unknown_is_reconciled_by_provider_query(self) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
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
        adapter, _transport = _remote_adapter("unknown_after_send")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: _admitted_remote_payload(request, "provider")
                }
            ),
            record_store=InMemoryExecutionRecordStore(),
        )
        registry = ExecutionBackendRegistry()
        registry.register(backend)
        gateway = ProductionExecutionGateway(registry, admission)

        handle = gateway.submit(request)
        result = gateway.reconcile(handle)

        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertIsNotNone(result.provider_receipt_ref)

    def test_remote_callback_is_deduplicated_and_materialized_as_execution_result(
        self,
    ) -> None:
        contract_set = contracts(
            backend_id="remote-provider",
            runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
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
        adapter, _transport = _remote_adapter("unknown_after_send")
        backend = RemoteProviderExecutionBackend(
            backend_id="remote-provider",
            capability_profile=capability,
            provider_adapter=adapter,
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: _admitted_remote_payload(request, "provider")
                }
            ),
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
            route_snapshots=(route,),
            model_profiles=(profile,),
            route_policies=(policy,),
            input_manifests=(manifest,),
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
            payload_resolver=StaticExecutionPayloadResolver(
                {
                    request.execution_id: _admitted_remote_payload(request, "provider")
                }
            ),
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
            RoutePolicyRegistry(
                (policy,),
                fallback_policies=FallbackPolicyRegistry(
                    (
                        FallbackPolicy.fail_closed(
                            policy.fallback_policy_ref,
                            policy.fallback_policy_version,
                        ),
                    )
                ),
            ),
            {capability.backend_id: capability},
            RouteRecommendationReadModel(
                (
                    RouteRecommendation(
                        task_kind="chapter.slice.run",
                        risk_class="NORMAL",
                        model_profile_id=profile.profile_id,
                        evidence_ref="route-recommendation:1",
                    ),
                )
            ),
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
            RoutePolicyRegistry(
                (policy,),
                fallback_policies=FallbackPolicyRegistry(
                    (
                        FallbackPolicy.fail_closed(
                            policy.fallback_policy_ref,
                            policy.fallback_policy_version,
                        ),
                    )
                ),
            ),
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

if __name__ == "__main__":
    unittest.main()
