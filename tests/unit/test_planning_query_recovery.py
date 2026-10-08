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
