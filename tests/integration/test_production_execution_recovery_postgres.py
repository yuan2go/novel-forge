from __future__ import annotations

from dataclasses import replace
import json
import logging
import unittest

import pytest

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


def test_diagnostics_distinguish_committed_record_from_failed_authority_write(caplog, monkeypatch):
    ensure_migrated()
    caplog.set_level(logging.INFO, logger="novel_forge.execution")
    project_id, operation_id = ProductionExecutionRecoveryPostgresTests._operation()
    request = ProductionExecutionRecoveryPostgresTests._request(project_id, operation_id)
    record = ExecutionRecord(request=request,
        handle=ProductionExecutionRecoveryPostgresTests._handle(request),
        started_at="2026-07-26T00:00:00Z", raw_evidence={"provider_state": "unknown"})
    store = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)
    store.put_record(record)
    before = store.get_record(request.execution_id)

    def fail_write(*args, **kwargs):
        raise OSError("PRIVATE CONNECTION STRING")

    monkeypatch.setattr(store.writer, "materialize_output", fail_write)
    record.raw_evidence = {"provider_state": "observed"}
    with pytest.raises(OSError):
        store.save_record(record)
    recovered = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id).get_record(request.execution_id)
    assert recovered.raw_evidence == before.raw_evidence
    rows = [json.loads(row.message) for row in caplog.records if row.name == "novel_forge.execution"]
    assert any(row["step"].endswith("._save_record") and row["phase"] == "failed"
        and row["execution_id"] == request.execution_id for row in rows)
    assert "PRIVATE CONNECTION STRING" not in caplog.text


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
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE authority_operation SET status='FAILED_FINAL',version=version+1 WHERE operation_id=%s", [operation_id])
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
            self.assertEqual(cursor.fetchone(), (2, 1, "FAILED_FINAL"))

        from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
        from novel_forge.storage.authority_asset_store import AuthorityAssetWriter
        from novel_forge.modules.command_kernel.errors import KernelError
        receipt = store.put_evidence("process-receipt", request.execution_id, {"outcome": "unknown"})
        assert store.read_evidence(receipt)["outcome"] == "unknown"
        with pytest.raises(KernelError, match="OPERATION_STATUS_CONFLICT"):
            AuthorityAssetWriter(DATABASE_URL).materialize_output(AuthorityAssetWriteCommand(
                operation_id, project_id, identifier("asset"), "execution_evidence",
                "authority-execution-evidence.v1", "forbidden/primary", "production_execution_evidence",
                "primary", "primary", {"execution_id": request.execution_id}, "fixture",
                request.trace_id, request.correlation_id))

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


def test_stale_unknown_cannot_overwrite_a_recovered_terminal_result():
    ensure_migrated()
    project_id, operation_id = ProductionExecutionRecoveryPostgresTests._operation()
    request = ProductionExecutionRecoveryPostgresTests._request(project_id, operation_id)
    store = AuthorityExecutionRecoveryStore(DATABASE_URL, project_id=project_id)
    record = ExecutionRecord(request=request,
        handle=ProductionExecutionRecoveryPostgresTests._handle(request),
        started_at='2026-10-09T00:00:00Z', raw_evidence={})
    store.put_record(record)
    stale = store.get_record(request.execution_id)
    from novel_forge.modules.production_execution.backends import ExecutionReconciler
    record.result = ExecutionReconciler.non_success(record, ExecutionOutcome.FINAL_FAILURE)
    store.save_record(record)
    with pytest.raises(ValueError, match='terminal execution'):
        store.save_record(stale)
    assert store.get_record(request.execution_id).result == record.result


@pytest.fixture
def isolated_api_generation():
    from psycopg.types.json import Jsonb
    from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
    from novel_forge.modules.command_kernel.external_effect_runtime import (
        EffectCommandContext, plan_external_effect, prepare_effect_dispatch,
        acquire_effect_dispatch, submit_effect_dispatch_result, _hash,
    )
    from novel_forge.modules.command_kernel.budget_runtime import (
        BudgetReservationRequest, reserve_provider_budget, resolve_provider_budget_failure,
    )
    from tests.integration.authority_postgres_support import seed_authority_project_book
    from tests.integration.test_cli_effect_reconciliation_postgres import asset
    from tests.unit.test_production_execution_gateway import contracts, _admitted_remote_payload
    from novel_forge.modules.production_execution.backends import _freeze_output_contract
    project, workspace, book, operation = (identifier(x) for x in ('api-project','workspace','book','operation'))
    seed_authority_project_book(project_id=project, workspace_id=workspace, book_id=book)
    with transaction() as c:
        if not c.execute("SELECT 1 FROM authority_operation_definition WHERE name='story_planning.generate' AND definition_version='1.0.0'").fetchone():
            insert_definition(c.cursor(), 'story_planning.generate')
        insert_operation(c.cursor(), operation_id=operation, definition_name='story_planning.generate',
            project_id=project, workspace_id=workspace, status='EXECUTING',
            command_payload={'payload':{'project_id':project,'workspace_id':workspace,'book_id':book}})
        c.execute("UPDATE authority_operation SET actor_id='operator' WHERE operation_id=%s", [operation])
        c.execute("INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,book_id,generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status) VALUES(%s,%s,%s,%s,%s,'book_plan.generate','BOOK','book:api','[]',%s,'EXECUTING')", [identifier('generation'),operation,project,workspace,book,_hash([])])
    materialization = {'contract':{'tool_permissions':{'default':'DENY','allowed':['model.provider.invoke']}}}
    materialization_ref = asset(project, materialization, 'capability_materialization_manifest', 'fixture-materialization.v1')
    capability = {'provider_request_envelope_hash':'sha256:original-envelope',
        'materialization_asset_version_id':materialization_ref.split(':',1)[1],
        'materialization_content_hash':_hash(materialization)}
    context = EffectCommandContext(operation,project,'operator','api-trace','api-correlation')
    adapter = FakeDeterministicProvider('success')
    effect = plan_external_effect(DATABASE_URL, context, effect_type='model.invoke', provider=adapter.provider,
        capability='model.test', stable_idempotency_key=identifier('api-effect'), max_attempts=2, reversible=False,
        request_payload={'stage':'draft','_production_execution':{'book_id':book,'capability_runtime':capability}},
        provider_capability_profile=adapter.capability_profile)['external_effect_id']
    request = contracts(backend_id='remote-provider',runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API)[5]
    request = replace(request, project_id=project,workspace_id=workspace,book_id=book,operation_id=operation,
        root_operation_id=operation,external_effect_id=effect,execution_id=identifier('execution'),
        target_scope={**request.target_scope.to_dict(),"project_id":project,"book_id":book})
    payload = _admitted_remote_payload(request, 'original API input')
    with transaction() as c:
        request_hash = c.execute('SELECT request_hash FROM authority_external_effect WHERE external_effect_id=%s',[effect]).fetchone()[0]
    session = {'execution_id':request.execution_id,'request_contract_hash':request.contract_hash,'record':{'request':request.to_dict(),
        'handle':{'transport':'REMOTE_PROVIDER_API'},'raw_evidence':{'submission_phase':'PROVIDER_OUTCOME_UNKNOWN'},
        'frozen_output_contract':_freeze_output_contract(request,payload,capability['provider_request_envelope_hash'])}}
    session_ref = asset(project, session, 'execution_recovery_session', 'authority-execution-recovery.v1')
    reservation = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(operation, effect, project,
        identifier('api-budget'),adapter.provider,'USD','0.5',1000,accounting_basis='PRICED'))
    dispatch = prepare_effect_dispatch(DATABASE_URL,context,effect_id=effect)
    lease = acquire_effect_dispatch(DATABASE_URL,context,dispatch_id=dispatch['dispatch_id'],worker_id='fixture',lease_seconds=30)
    submit_effect_dispatch_result(DATABASE_URL,context,dispatch_id=dispatch['dispatch_id'],worker_id='fixture',
        fencing_token=lease['fencing_token'],outcome='unknown',provider_request_id='trusted-original-api',evidence={'production_execution':{
            'execution_handle':{'transport':'REMOTE_PROVIDER_API'},'execution_request':request.to_dict()}})
    resolve_provider_budget_failure(DATABASE_URL,reservation_id=reservation['reservation_id'],project_id=project,external_state_unknown=True)
    proof = {'contract_version':'pure-generation-isolation.v1','project_id':project,'workspace_id':workspace,
        'book_id':book,'operation_id':operation,'remote_outcome':'UNKNOWN','usage':'UNKNOWN',
        'business_commit_right':'REVOKED','activation_right':'REVOKED','actor_id':'operator',
        'continuation_id':'planning-runtime-continuation:'+operation,'execution_transport':'REMOTE_PROVIDER_API',
        'evidence_asset_version_id':session_ref.split(':',1)[1],
        'local_execution':{key:getattr(request,key) for key in ('execution_id','attempt_id','fencing_token')}}
    with transaction() as c:
        c.execute("UPDATE authority_operation SET status='FAILED_FINAL' WHERE operation_id=%s",[operation])
        c.execute('INSERT INTO authority_generation_isolation(isolation_id,external_effect_id,operation_id,project_id,workspace_id,book_id,request_hash,materialization_asset_version_id,proof) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',[identifier('isolation'),effect,operation,project,workspace,book,request_hash,materialization_ref.split(':',1)[1],Jsonb(proof)])
        version = c.execute('SELECT version FROM authority_operation WHERE operation_id=%s',[operation]).fetchone()[0]
    identity = {'project_id':project,'workspace_id':workspace,'book_id':book,'operation_id':operation,
        'external_effect_id':effect,'request_hash':request_hash,'dispatch_id':dispatch['dispatch_id'],
        'generation':dispatch['generation'],**proof['local_execution'],
        'execution_request_hash':request.contract_hash,'input_manifest_ref':request.input_manifest_ref,
        'model_id':'','provider':adapter.provider}
    return context, effect, reservation, identity, version


def _api_confirmation(seeded, **changes):
    from novel_forge.modules.command_kernel.manual_effect_resolution import ExternalEffectManualResolutionCommand
    context,effect,_,identity,version = seeded
    facts = {**identity,'provider_request_id':'trusted-original-api','outcome':'success',
        'usage':{'measurement':'PROVIDER_REPORTED','input_tokens':120,'output_tokens':30,'total_tokens':150},
        'cost':{'measurement':'PROVIDER_REPORTED','amount':'0.02','currency':'USD'},
        'result':{'text':'late isolated original'},**changes}
    source = {'contract_version':'generation-provider-record.v1',**facts}
    receipt = {'contract_version':'generation-remote-receipt.v1',**facts,
        'verification_basis':'AUTHORIZED_OPERATOR_ATTESTATION','verified_by':context.actor_id}
    return ExternalEffectManualResolutionCommand(effect,context.operation_id,context.project_id,context.actor_id,
        'MARK_SUCCEEDED','Late original API evidence only',{'original_remote_receipt':receipt,'original_provider_record':source},identifier('late-api'),
        version,context.trace_id,context.correlation_id)



def test_isolated_api_late_receipt_settles_once_without_restoring_business_rights(isolated_api_generation, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from novel_forge.modules.command_kernel.manual_effect_resolution import resolve_external_effect_manually
    from novel_forge.modules.command_kernel.external_effect_runtime import read_succeeded_external_effect
    from novel_forge.modules.command_kernel.errors import KernelError
    seeded = isolated_api_generation
    context,effect,reservation,_,_ = seeded
    with transaction() as c:
        before = c.execute('SELECT to_jsonb(e),to_jsonb(d),to_jsonb(o) FROM authority_external_effect e JOIN authority_external_effect_dispatch d USING(external_effect_id) JOIN authority_operation o ON o.operation_id=e.operation_id WHERE e.external_effect_id=%s',[effect]).fetchone()
    command = _api_confirmation(seeded)
    from novel_forge.modules.command_kernel import manual_effect_resolution
    def fail_after_receipt(*args, **kwargs):
        raise RuntimeError("controlled crash after receipt persistence")
    with monkeypatch.context() as crash:
        crash.setattr(manual_effect_resolution, "_record", fail_after_receipt)
        with pytest.raises(RuntimeError, match="controlled crash after receipt persistence"):
            resolve_external_effect_manually(DATABASE_URL, command)
    with transaction() as c:
        assert c.execute('SELECT status FROM authority_budget_reservation WHERE reservation_id=%s', [reservation['reservation_id']]).fetchone() == ('HELD_UNKNOWN',)
        assert c.execute('SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s', [effect]).fetchone() == (0,)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:resolve_external_effect_manually(DATABASE_URL,command),range(2)))
    assert sorted(result['replayed'] for result in results) == [False,True]
    assert resolve_external_effect_manually(DATABASE_URL,_api_confirmation(seeded))['operation_status']=='FAILED_FINAL'
    with pytest.raises(KernelError,match='ISOLATED_API_RECEIPT_CONFLICT'):
        resolve_external_effect_manually(DATABASE_URL,_api_confirmation(seeded,result={'text':'conflict'}))
    with transaction() as c:
        assert c.execute('SELECT to_jsonb(e),to_jsonb(d),to_jsonb(o) FROM authority_external_effect e JOIN authority_external_effect_dispatch d USING(external_effect_id) JOIN authority_operation o ON o.operation_id=e.operation_id WHERE e.external_effect_id=%s',[effect]).fetchone()==before
        assert c.execute('SELECT status,actual_tokens,settled_amount FROM authority_budget_reservation WHERE reservation_id=%s',[reservation['reservation_id']]).fetchone()==('SETTLED',150,__import__('decimal').Decimal('0.02'))
        assert c.execute("SELECT count(*) FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s AND evidence->>'contract_version'='isolated-api-reconciliation.v1'",[effect]).fetchone()==(1,)
    with pytest.raises(KernelError,match='OPERATION_STATUS_CONFLICT'):
        read_succeeded_external_effect(DATABASE_URL,context,effect_id=effect)
    from tests.integration.migration_window_postgres_support import restored_generation_backup
    with restored_generation_backup(DATABASE_URL, backup_root=tmp_path / "api-joint-backup") as restored_url:
        assert resolve_external_effect_manually(restored_url, command)["replayed"]
        with pytest.raises(KernelError, match='OPERATION_STATUS_CONFLICT'):
            read_succeeded_external_effect(restored_url, context, effect_id=effect)


@pytest.mark.parametrize('change',[{'book_id':'foreign-book'},{'project_id':'foreign-project'},
    {'generation':99},{'attempt_id':'foreign-attempt'},{'fencing_token':99},
    {'request_hash':'sha256:foreign'},{'provider_request_id':'foreign-request'},{'usage':None},{'cost':{'amount':None,'currency':'USD'}}])
def test_isolated_api_receipt_cannot_cross_original_identity_or_invent_usage(isolated_api_generation,change):
    from novel_forge.modules.command_kernel.manual_effect_resolution import resolve_external_effect_manually
    from novel_forge.modules.command_kernel.errors import KernelError
    with pytest.raises(KernelError,match='ISOLATED_API_RECEIPT_INVALID'):
        resolve_external_effect_manually(DATABASE_URL,_api_confirmation(isolated_api_generation,**change))
