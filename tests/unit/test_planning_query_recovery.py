from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.production_execution.contracts import ExecutionOutcome, ExecutionRuntimeClass
from novel_forge.modules.story_planning_runtime.execution import _PlanningGatewayEffectAdapter


def adapter_with_record(record=None, outcome=ExecutionOutcome.UNKNOWN):
    request = SimpleNamespace(execution_id="original", stable_idempotency_key="key", capability="model.test",
        external_effect_id="effect", contract_hash="frozen", to_dict=lambda: {})
    handle = SimpleNamespace(transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        backend_execution_id="receipt", provider_request_id=None, to_dict=lambda: {})
    result = SimpleNamespace(outcome=outcome, started_at="started", usage_receipt_ref=None,
        cost_receipt_ref=None, normalized_output_ref=None, to_dict=lambda: {})
    if record is True:
        record = SimpleNamespace(request=request, handle=handle, raw_evidence={})
    gateway = SimpleNamespace(submit=Mock(side_effect=AssertionError("query started a new execution")),
        reconcile=Mock(return_value=result))
    store = SimpleNamespace(find_record=Mock(return_value=record), get_record=Mock(return_value=record))
    adapter = _PlanningGatewayEffectAdapter(transport=SimpleNamespace(provider="gateway", reconciliation_mode="query", capability_profile={}),
        session=SimpleNamespace(gateway=gateway, evidence_store=store),
        binding=SimpleNamespace(request=request, route_snapshot=SimpleNamespace(model_provider="codex-cli", model_id="frozen", to_dict=lambda: {}),
            input_manifest=SimpleNamespace(prompt_bundle_version="v1", skill_bundle_version="v1", to_dict=lambda: {})))
    return adapter, gateway


def query(adapter):
    return adapter.query(stable_idempotency_key="key", capability="model.test", request_payload={"external_effect_id": "effect"})


def test_missing_original_record_cannot_start_execution():
    adapter, gateway = adapter_with_record()
    assert query(adapter).outcome == "ambiguous"
    gateway.submit.assert_not_called()
    gateway.reconcile.assert_not_called()


@pytest.mark.parametrize("outcome", [ExecutionOutcome.UNKNOWN, ExecutionOutcome.TIMED_OUT, ExecutionOutcome.CANCELLED, ExecutionOutcome.ORPHANED])
def test_local_terminal_without_remote_usage_remains_ambiguous(outcome):
    adapter, gateway = adapter_with_record(True, outcome)
    assert query(adapter).outcome == "ambiguous"
    gateway.submit.assert_not_called()



def test_cached_historical_process_exit_is_unknown_not_not_found():
    adapter, gateway = adapter_with_record(True, ExecutionOutcome.RETRYABLE_FAILURE)
    adapter.session.evidence_store.find_record.return_value.raw_evidence['failure_code'] = 'PROCESS_EXIT_FAILURE'
    assert query(adapter).outcome == 'ambiguous'
    gateway.submit.assert_not_called()


def test_query_rejects_changed_persisted_contract():
    adapter, gateway = adapter_with_record(True)
    adapter.session.evidence_store.find_record.return_value.request = SimpleNamespace(contract_hash='other')
    with pytest.raises(Exception, match='original execution contract'):
        query(adapter)
    gateway.submit.assert_not_called()
    gateway.reconcile.assert_not_called()


@pytest.mark.parametrize('receipt_sha', ['', 'a'*40, 'c'*40])
def test_original_receipt_pack_release_is_preserved_but_fresh_drift_is_rejected(monkeypatch, receipt_sha):
    from dataclasses import fields
    from novel_forge.modules.story_planning_runtime import binder
    from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
    from novel_forge.modules.production_execution.postgres import PostgresAttemptFenceVerifier
    from novel_forge.modules.command_kernel.errors import KernelError
    from tests.unit.test_story_planning_runtime import _command
    command = _command('chapter_group_plan.generate')
    definition = GENERATOR_CATALOG[command.generator_operation_name]
    h = 'sha256:'+'1'*64
    values = {f.name:(h if f.name.endswith('_hash') or f.name=='narrative_intelligence_selection_digest' else 'ref')
        for f in fields(binder.PreparedPlanningExecution)}
    values.update(execution_port=SimpleNamespace(production_execution_gateway_backed=True,external_effect_backed=True),
        receipt_consumption_release_sha=receipt_sha)
    prepared = binder.PreparedPlanningExecution(**values)
    frozen = SimpleNamespace(operation_definition_ref='story_planning.generate@1.21.0',operation_definition_hash=h,
        agent_definition_ref='agent',agent_definition_hash=h,capability_ref='capability',capability_hash=h,
        execution_capability_id=definition.capability,execution_capability_hash=h,
        tool_policy_ref='ref',tool_policy_hash=h,context_policy_ref='ref',context_policy_hash=h,
        evaluation_policy_ref='ref',evaluation_policy_hash=h,release_sha='a'*40,
        prompt_bundle_ref='ref',prompt_bundle_hash=h,skill_bundle_ref='ref',skill_bundle_hash=h,
        commit_authority='HIERARCHICAL_PLANNING_AUTHORITY')
    snapshot = SimpleNamespace(execution_snapshot=frozen,snapshot_id='snapshot',snapshot_hash=h)
    resolver = binder.PostgresPlanningExecutionBundleResolver('db',execution_preparer=SimpleNamespace(prepare=lambda **_:prepared),
        workflow_definition_ref='workflow',pack_id='pack',environment='validation',runtime_profile='profile',
        release_channel='channel',release_sha='b'*40)
    resolver.pack_resolver = SimpleNamespace(freeze_attempt_snapshot=lambda *args,**kwargs:snapshot)
    class Uow:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(binder,'AuthorityUnitOfWork',lambda _:Uow())
    monkeypatch.setattr(PostgresAttemptFenceVerifier,'assert_recovery_current',lambda *args:None)
    monkeypatch.setattr(resolver,'_operation',lambda *args:{'definition_name':'story_planning.generate',
        'definition_version':'1.21.0','definition_hash':h})
    args = dict(operation_id='operation',attempt_id='attempt',fencing_token=2,worker_id='worker',
        command=command,inputs=(),definition=definition)
    if receipt_sha=='a'*40:
        assert resolver.resolve(**args).execution_port is prepared.execution_port
    else:
        with pytest.raises(KernelError,match='CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT'):
            resolver.resolve(**args)
