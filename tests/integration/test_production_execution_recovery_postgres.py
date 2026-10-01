from __future__ import annotations

from dataclasses import replace
import unittest

from novel_forge.modules.production_execution import (
    CapabilityAvailability,
    CompletionMode,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeClass,
)
from novel_forge.modules.production_execution.backends import ExecutionRecord
from novel_forge.modules.production_execution.recovery import (
    AuthorityExecutionRecoveryStore,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderInvocationHandle,
    ProviderInvocationResult,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class ProductionExecutionRecoveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_record_and_evidence_survive_complete_worker_restart(self) -> None:
        project_id, operation_id = self._operation()
        request = self._request(project_id, operation_id)
        handle = self._handle(request)
        first = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)
        first.put_record(
            ExecutionRecord(
                request=request,
                handle=handle,
                started_at="2026-07-26T00:00:00Z",
                raw_evidence={"provider_state": "unknown"},
                provider_result=ProviderInvocationResult(
                    outcome="unknown",
                    handle=ProviderInvocationHandle(
                        provider_request_id="provider-request:1",
                        provider_correlation_id="provider-correlation:1",
                        accepted_at="2026-07-26T00:00:00Z",
                        completion_mode="background",
                        query_supported=True,
                        cancel_supported=True,
                        callback_supported=True,
                        idempotency_supported=True,
                    ),
                    evidence={"provider_state": "unknown"},
                    request_sent=True,
                ),
            )
        )
        request_ref = first.put_request(request)
        handle_ref = first.put_handle(handle)
        receipt_ref = first.put_receipt(
            "provider-receipt",
            request.execution_id,
            {
                "outcome": "unknown",
                "provider_request_id": "provider-request:1",
            },
        )

        restarted = AuthorityExecutionRecoveryStore(
            DATABASE_URL,
            project_id=project_id,
        )
        recovered = restarted.get_record(request.execution_id)

        self.assertEqual(recovered.request.contract_hash, request.contract_hash)
        self.assertEqual(recovered.handle.contract_hash, handle.contract_hash)
        self.assertEqual(recovered.raw_evidence, {"provider_state": "unknown"})
        self.assertEqual(
            recovered.provider_result.handle.provider_request_id,
            "provider-request:1",
        )
        self.assertEqual(
            restarted.read_evidence(request_ref),
            request.to_dict(),
        )
        self.assertEqual(restarted.read_evidence(handle_ref), handle.to_dict())
        self.assertEqual(
            restarted.read_evidence(receipt_ref)["outcome"],
            "unknown",
        )

    def test_recovery_versions_state_without_owning_attempt_terminal_status(self) -> None:
        project_id, operation_id = self._operation()
        request = self._request(project_id, operation_id)
        handle = self._handle(request)
        store = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)
        record = ExecutionRecord(
            request=request,
            handle=handle,
            started_at="2026-07-26T00:00:00Z",
            raw_evidence={"provider_state": "unknown"},
        )
        store.put_record(record)
        record.result = ExecutionResult(
            execution_id=request.execution_id,
            operation_id=operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            outcome=ExecutionOutcome.UNKNOWN,
            process_receipt_ref=None,
            provider_receipt_ref="authority-asset-version:receipt",
            raw_output_ref=None,
            normalized_output_ref=None,
            output_manifest_ref=None,
            usage_receipt_ref=None,
            cost_receipt_ref=None,
            validation_report_ref=None,
            started_at=record.started_at,
            completed_at=None,
        )
        store.save_record(record)

        recovered = AuthorityExecutionRecoveryStore(
            DATABASE_URL,
            project_id=project_id,
        ).get_record(request.execution_id)
        self.assertEqual(recovered.result.outcome, ExecutionOutcome.UNKNOWN)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE version.lifecycle = 'ACTIVE'),
                       operation.status
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id = asset.asset_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = %s
                WHERE asset.project_id = %s
                  AND asset.asset_type = 'execution_recovery_session'
                GROUP BY operation.status
                """,
                [operation_id, project_id],
            )
            self.assertEqual(cursor.fetchone(), (2, 1, "EXECUTING"))

    def test_saved_provider_response_reuses_frozen_contract_after_local_failure_and_restart(self):
        for interruption in ("validation", "submit_checkpoint", "query_checkpoint"):
            with self.subTest(interruption=interruption):
                self._assert_saved_provider_response_recovery(interruption)

    def _assert_saved_provider_response_recovery(self, interruption):
        from unittest.mock import patch
        from novel_forge.api.authority_dependencies import validate_production_structured_result
        from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema
        from novel_forge.modules.production_execution.backends import RemoteProviderExecutionBackend, StaticExecutionPayloadResolver
        from novel_forge.modules.production_execution.gateway import AdmissionController, StaticAttemptFenceVerifier, StaticExecutionContractSource
        from tests.unit.test_production_execution_gateway import contracts, _remote_adapter, _admitted_remote_payload

        project_id, operation_id = self._operation()
        capability, profile, policy, route, manifest, request = contracts(
            backend_id="remote-provider", runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API)
        route = replace(route, operation_id=operation_id)
        manifest = replace(manifest, project_id=project_id, operation_id=operation_id,
                           target_scope={**manifest.target_scope.to_dict(), "project_id": project_id})
        request = replace(request, project_id=project_id, operation_id=operation_id,
                          root_operation_id=operation_id, execution_id=identifier("execution"),
                          target_scope={**request.target_scope.to_dict(), "project_id": project_id})
        admission = AdmissionController(StaticExecutionContractSource(route_snapshots=(route,),
            model_profiles=(profile,), route_policies=(policy,), input_manifests=(manifest,)),
            StaticAttemptFenceVerifier({(operation_id, request.attempt_id): request.fencing_token}))
        raw = {"scene_artifacts": [{"slot_id": "scene:1:skeleton", "text": "她守住了灯号。", "used_fact_ids": []}]}
        adapter, transport = _remote_adapter("unknown_after_send" if interruption == "query_checkpoint" else "success", raw)
        payload = replace(_admitted_remote_payload(request, "frozen draft"),
            output_schema_version="schema:chapter-provider-output:draft:v3", output_schema=chapter_provider_output_schema("draft"))
        resolver = StaticExecutionPayloadResolver({request.execution_id: payload})
        store = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)

        def unavailable(*_args, **_kwargs):
            raise RuntimeError("local processing interrupted")

        backend = RemoteProviderExecutionBackend(backend_id="remote-provider", capability_profile=capability,
            provider_adapter=adapter, admission=admission, payload_resolver=resolver, record_store=store,
            structured_result_validator=unavailable)
        if interruption == "submit_checkpoint":
            with patch.object(backend, "_record_provider_result", side_effect=RuntimeError("local processing interrupted")):
                with self.assertRaisesRegex(RuntimeError, "local processing interrupted"):
                    backend.submit(request)
            handle = store.get_record(request.execution_id).handle
        else:
            handle = backend.submit(request)
            if interruption == "query_checkpoint":
                with patch.object(backend, "_record_provider_result", side_effect=RuntimeError("local processing interrupted")):
                    with self.assertRaisesRegex(RuntimeError, "local processing interrupted"):
                        backend.reconcile(handle)
            else:
                with self.assertRaisesRegex(RuntimeError, "local processing interrupted"):
                    backend.reconcile(handle)
        frozen = store.get_record(request.execution_id).frozen_output_contract
        saved_result = store.get_record(request.execution_id).provider_result
        self.assertEqual(saved_result.evidence["result"], raw)
        restarted_store = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)
        restarted = RemoteProviderExecutionBackend(backend_id="remote-provider", capability_profile=capability,
            provider_adapter=adapter, admission=admission, payload_resolver=resolver, record_store=restarted_store,
            structured_result_validator=validate_production_structured_result)
        result = restarted.reconcile(handle)
        self.assertEqual(result.outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual(restarted.reconcile(handle), result)
        self.assertEqual(restarted_store.get_record(request.execution_id).frozen_output_contract, frozen)
        raw_ref = restarted_store.get_record(request.execution_id).raw_evidence["provider_response_ref"]
        self.assertEqual(restarted_store.read_evidence(raw_ref)["evidence"]["result"], raw)
        self.assertEqual(restarted_store.read_evidence(result.normalized_output_ref), raw)
        self.assertEqual(transport.execute_calls, 1)
        self.assertEqual(transport.query_calls, 1 if interruption == "query_checkpoint" else 0)

    def test_same_execution_id_with_different_request_contract_fails_closed(self) -> None:
        project_id, operation_id = self._operation()
        request = self._request(project_id, operation_id)
        handle = self._handle(request)
        store = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)
        store.put_record(
            ExecutionRecord(
                request,
                handle,
                "2026-07-26T00:00:00Z",
                {"provider_state": "unknown"},
            )
        )
        changed = replace(
            request,
            stable_idempotency_key="chapter:1:draft:conflict",
        )
        with self.assertRaisesRegex(ValueError, "different request"):
            store.put_record(
                ExecutionRecord(
                    changed,
                    handle,
                    "2026-07-26T00:00:00Z",
                    {"provider_state": "unknown"},
                )
            )

    @staticmethod
    def _operation() -> tuple[str, str]:
        project_id = identifier("recovery-project")
        operation_id = identifier("recovery-operation")
        definition_name = identifier("recovery-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
        return project_id, operation_id

    @staticmethod
    def _request(project_id: str, operation_id: str) -> ExecutionRequest:
        return ExecutionRequest(
            execution_id=identifier("execution"),
            operation_id=operation_id,
            root_operation_id=operation_id,
            saga_id=identifier("saga"),
            attempt_id=identifier("attempt"),
            fencing_token=3,
            project_id=project_id,
            workspace_id=identifier("workspace"),
            book_id=identifier("book"),
            target_scope={
                "scope_kind": "chapter",
                "scope_id": "chapter:1",
                "chapter_number": 1,
            },
            domain="prose",
            task_kind="chapter.slice.run",
            stage="draft",
            capability="prose.chapter.draft",
            importance_class="HIGH",
            risk_class="high",
            route_snapshot_id=identifier("route"),
            workspace_snapshot_ref=identifier("workspace-snapshot"),
            input_manifest_ref=identifier("input-manifest"),
            resource_claims=("chapter:1",),
            timeout_policy_ref="timeout:prose-chapter-draft:v1",
            budget_policy_ref="budget:prose-chapter-draft:v1",
            permission_policy_ref="permission:prose-chapter-draft:v1",
            validation_policy_ref="validation:prose-chapter-draft:v1",
            commit_policy_ref="commit:prose-chapter-draft:v1",
            stable_idempotency_key="chapter:1:draft:v1",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            external_effect_id=identifier("effect"),
            budget_reservation_id=identifier("budget"),
        )

    @staticmethod
    def _handle(request: ExecutionRequest) -> ExecutionHandle:
        return ExecutionHandle(
            execution_id=request.execution_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            backend_execution_id="provider-request:1",
            backend_id="remote-provider-openai",
            transport=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
            local_execution_receipt_id=None,
            local_process_id=None,
            local_process_group_id=None,
            local_process_start_time=None,
            provider_request_id="provider-request:1",
            completion_mode=CompletionMode.POLL,
            query_capability=CapabilityAvailability.SUPPORTED,
            cancel_capability=CapabilityAvailability.SUPPORTED,
            callback_capability=CapabilityAvailability.SUPPORTED,
        )


if __name__ == "__main__":
    unittest.main()
