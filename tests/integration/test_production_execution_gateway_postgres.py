from __future__ import annotations

import hashlib
import unittest

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.production_execution import (
    AdmissionController,
    ArtifactPointer,
    CapabilityId,
    CompletionMode,
    ExecutionBackendRegistry,
    ExecutionCapabilityProfile,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
    InMemoryExecutionRecordStore,
    InputManifest,
    ModelProfile,
    ModelProfileStatus,
    PostgresAttemptFenceVerifier,
    PostgresExecutionContractSource,
    ProductionExecutionGateway,
    ResolvedExecutionPayload,
    RoutePolicy,
    RouteSnapshot,
    ScriptedFixtureExecutionBackend,
    StaticExecutionPayloadResolver,
    default_capability_registry,
)
from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class ProductionExecutionGatewayPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_postgres_contracts_and_authority_fence_admit_fixture_backend(self) -> None:
        definition = default_capability_registry().resolve(
            CapabilityId.PROSE_CHAPTER_DRAFT
        )
        project_id = identifier("execution-project")
        operation_id = identifier("execution-operation")
        attempt_id = identifier("execution-attempt")
        external_effect_id = identifier("external-effect")
        route_ref = f"production_execution/routes/{identifier('route')}"
        input_ref = f"production_execution/inputs/{identifier('input')}"
        profile_id = f"scripted.{identifier('profile')}"
        policy_id = f"chapter.{identifier('policy')}"
        capability = ExecutionCapabilityProfile(
            backend_id="scripted-fixture",
            backend_version="1.0.0",
            runtime_class=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
            supported_completion_modes=(CompletionMode.SYNCHRONOUS, CompletionMode.POLL),
            supported_reasoning_efforts=("high", "xhigh"),
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
            qualification_ref="capability-probe:scripted-fixture:1",
        )
        profile = ModelProfile(
            profile_id=profile_id,
            profile_version=1,
            backend_id=capability.backend_id,
            runtime_class=capability.runtime_class,
            model_provider="fixture",
            model_id="scripted-model",
            reasoning_effort="xhigh",
            timeout_policy_ref=definition.timeout_policy_ref,
            workspace_policy_ref="workspace:default",
            output_policy_ref="output:json",
            fallback_policy="FAIL_CLOSED",
            status=ModelProfileStatus.ACTIVE,
            capability_probe_ref=capability.qualification_ref,
        )
        policy = RoutePolicy(
            policy_id=policy_id,
            policy_version=1,
            default_model_profile_id=profile_id,
            allowed_model_profile_ids=(profile_id,),
            rule_set_ref="route-rules:chapter:1",
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=f"{policy_id}.fail-closed",
            fallback_policy_version=1,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        route = RouteSnapshot(
            route_snapshot_id=route_ref,
            route_decision_id=identifier("route-decision"),
            operation_id=operation_id,
            attempt_id=attempt_id,
            policy_id=policy_id,
            policy_version=1,
            backend_id=capability.backend_id,
            backend_version=capability.backend_version,
            runtime_host_id="host:integration",
            auth_profile_ref="auth:fixture",
            model_profile_id=profile_id,
            model_profile_version=1,
            model_provider=profile.model_provider,
            model_id=profile.model_id,
            requested_reasoning_effort="xhigh",
            reasoning_effort="xhigh",
            prompt_bundle_ref="prompt:chapter:1",
            skill_bundle_ref="skill:chapter:1",
            context_bundle_ref="context:chapter:1",
            output_schema_ref="schema:chapter:1",
            release_sha="a" * 40,
            fallback_policy_ref=policy.fallback_policy_ref,
            fallback_policy_version=policy.fallback_policy_version,
        )
        artifact = ArtifactPointer(
            artifact_ref="asset-version:plan:1",
            artifact_type="chapter_plan",
            content_hash="sha256:" + hashlib.sha256(b"plan").hexdigest(),
            schema_version="chapter-plan.v3",
            source_eligibility="PRODUCTION_ELIGIBLE",
        )
        manifest = InputManifest(
            manifest_id=input_ref,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=1,
            project_id=project_id,
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
        definition_name = identifier("execution-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
            cursor.execute(
                """
                INSERT INTO authority_attempt (
                    attempt_id, operation_id, attempt_number, max_attempts,
                    status, worker_id, started_at
                ) VALUES (%s, %s, 1, 1, 'RUNNING', 'worker:integration', NOW())
                """,
                [attempt_id, operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_lease_acquisition (
                    lease_id, attempt_id, owner, fencing_token, expires_at, status
                ) VALUES (%s, %s, 'worker:integration', 1,
                          NOW() + INTERVAL '10 minutes', 'HELD')
                """,
                [identifier("lease"), attempt_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_external_effect (
                    external_effect_id, operation_id, project_id, effect_type,
                    stable_idempotency_key, status, request_hash
                ) VALUES (%s, %s, %s, 'model.invoke', %s, 'READY', %s)
                """,
                [
                    external_effect_id,
                    operation_id,
                    project_id,
                    f"{operation_id}:draft",
                    hashlib.sha256(operation_id.encode()).hexdigest(),
                ],
            )

        writer = AuthorityAssetWriter(DATABASE_URL)
        contracts = (
            (route_ref, "route_snapshot", route.to_dict()),
            (
                f"production_execution/model_profiles/{profile_id}/v1",
                "model_profile",
                profile.to_dict(),
            ),
            (
                f"production_execution/route_policies/{policy_id}/v1",
                "route_policy",
                policy.to_dict(),
            ),
            (input_ref, "input_manifest", manifest.to_dict()),
        )
        for logical_ref, asset_type, content in contracts:
            write_operation = identifier("contract-write")
            write_definition = identifier("contract-definition")
            with transaction() as connection, connection.cursor() as cursor:
                insert_definition(cursor, write_definition)
                insert_operation(
                    cursor,
                    operation_id=write_operation,
                    definition_name=write_definition,
                    project_id=project_id,
                    status="EXECUTING",
                )
            writer.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=write_operation,
                    project_id=project_id,
                    asset_id=identifier(asset_type),
                    asset_type=asset_type,
                    logical_ref=logical_ref,
                    category="production_execution_contracts",
                    output_key=asset_type,
                    role="primary",
                    content={"contract": content},
                    qualification_policy="production-execution-contract-v1",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                )
            )

        request = ExecutionRequest(
            execution_id=identifier("execution"),
            operation_id=operation_id,
            root_operation_id=operation_id,
            saga_id=identifier("saga"),
            attempt_id=attempt_id,
            fencing_token=1,
            project_id=project_id,
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
            route_snapshot_id=route_ref,
            workspace_snapshot_ref="workspace:1",
            input_manifest_ref=input_ref,
            resource_claims=("fixture:request",),
            timeout_policy_ref=definition.timeout_policy_ref,
            budget_policy_ref=definition.budget_policy_ref,
            permission_policy_ref=definition.permission_policy_ref,
            validation_policy_ref=definition.validation_policy_ref,
            commit_policy_ref=definition.commit_policy_ref,
            stable_idempotency_key=f"{operation_id}:draft",
            trace_id="trace:integration",
            correlation_id="correlation:integration",
            external_effect_id=external_effect_id,
            budget_reservation_id="budget-reservation:integration",
        )
        source = PostgresExecutionContractSource(DATABASE_URL, project_id=project_id)
        verifier = PostgresAttemptFenceVerifier(DATABASE_URL)
        admission = AdmissionController(source, verifier)
        backend = ScriptedFixtureExecutionBackend(
            admission=admission,
            payload_resolver=StaticExecutionPayloadResolver({
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": {"text": "postgres admitted fixture"}},
                    input_text="fixture",
                    working_directory=".",
                    timeout_seconds=5,
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
        with self.assertRaisesRegex(ValueError, "stale Authority fencing token"):
            verifier.assert_current(operation_id, attempt_id, 2)


if __name__ == "__main__":
    unittest.main()
