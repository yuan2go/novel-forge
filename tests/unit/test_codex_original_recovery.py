from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from novel_forge.modules.production_execution import ExecutionOutcome, ExecutionRuntimeClass
from novel_forge.modules.production_execution.backends import (
    CodexCliExecutionBackend, InMemoryExecutionRecordStore, LocalProcessExecutionPolicy,
    ResolvedExecutionPayload, StaticExecutionPayloadResolver,
)
from novel_forge.modules.production_execution.gateway import AdmissionController, StaticAttemptFenceVerifier, StaticExecutionContractSource
from novel_forge.modules.production_execution.process_supervisor import CodexProcessSupervisor, PersistentExecutionDirectory, ProcessReceiptStatus
from tests.unit.test_codex_execution_evidence import _entitlement
from tests.unit.test_production_execution_gateway import contracts


@pytest.fixture
def execution(tmp_path):
    _, profile, policy, route, manifest, request = contracts(backend_id='codex-cli', runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    admission = AdmissionController(StaticExecutionContractSource(route_snapshots=(route,), model_profiles=(profile,), route_policies=(policy,), input_manifests=(manifest,)), StaticAttemptFenceVerifier({('operation:1', 'attempt:1'): 7}))
    directory = PersistentExecutionDirectory(tmp_path / 'executions')
    result_path = directory.prepare(request.execution_id).result_path('result.json')
    events = [{'type': 'thread.started', 'thread_id': 'original-thread'},
        {'type': 'turn.started'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"text":"original result"}'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 4}}]
    payload = ResolvedExecutionPayload(request_payload={'stage': 'draft'}, input_text='original prompt', working_directory=str(tmp_path), timeout_seconds=5,
        output_schema_version='schema:test:1', output_schema={'type': 'object'}, allowed_tools=('model.provider.invoke',),
        command=(sys.executable, '-c', "import sys; open(sys.argv[1],'w').write(sys.argv[2]); print(sys.argv[3])", str(result_path), '{"text":"original result"}', '\n'.join(map(json.dumps, events))))
    store = InMemoryExecutionRecordStore()
    supervisor = CodexProcessSupervisor(directory)
    backend = CodexCliExecutionBackend(admission=admission, payload_resolver=StaticExecutionPayloadResolver({request.execution_id: payload}), record_store=store,
        supervisor=supervisor, account_entitlement=_entitlement(), structured_result_validator=lambda stage, schema, value: value,
        execution_policy=LocalProcessExecutionPolicy(fixed_working_directory=str(tmp_path), allowed_command_prefixes=((sys.executable,),), maximum_result_bytes=10000))
    handle = backend.submit(request)
    return backend, handle, store, directory


@pytest.mark.parametrize('initial', [ProcessReceiptStatus.FAILED, ProcessReceiptStatus.RUNNING])
def test_late_original_receipt_replaces_uncertain_cache_without_launch(execution, monkeypatch, initial):
    backend, handle, store, directory = execution
    final = backend.supervisor.recover(handle.execution_id)
    early = replace(final, receipt=replace(final.receipt, status=initial, returncode=None, completed_at=None))
    monkeypatch.setattr(backend.supervisor, 'recover', lambda _: early)
    first = backend.reconcile(handle)
    assert first.outcome in {ExecutionOutcome.UNKNOWN, ExecutionOutcome.RUNNING}
    monkeypatch.setattr(backend.supervisor, 'recover', lambda _: final)
    monkeypatch.setattr(backend.supervisor, 'run', lambda _: pytest.fail('recovery must never launch'))
    result = backend.reconcile(handle)
    assert result.outcome == ExecutionOutcome.SUCCEEDED
    assert store.read_evidence(result.normalized_output_ref) == {'text': 'original result'}
    record = store.get_record(handle.execution_id)
    history = record.raw_evidence['prior_result_refs']
    assert store.read_evidence(history[0])['outcome'] == first.outcome.value
    assert backend.reconcile(handle) == result
    assert len(record.raw_evidence['prior_result_refs']) == 1


def test_orphaned_complete_turn_recovers_without_rewriting_process_receipt(execution, monkeypatch):
    backend, handle, store, directory = execution
    original = directory.read_receipt(handle.execution_id)
    orphan = replace(original, status=ProcessReceiptStatus.ORPHANED, returncode=None)
    directory.write_receipt(orphan)
    monkeypatch.setattr(backend.supervisor, 'run', lambda _: pytest.fail('recovery must never launch'))
    result = backend.reconcile(handle)
    assert result.outcome == ExecutionOutcome.SUCCEEDED
    assert directory.read_receipt(handle.execution_id) == orphan
    assert store.read_evidence(result.usage_receipt_ref)['total_tokens'] == 7


@pytest.mark.parametrize('mutation', ['missing_usage', 'failed_turn', 'truncated_json', 'another_turn', 'wrong_fence'])
def test_incomplete_or_mismatched_original_evidence_never_becomes_success(execution, mutation):
    backend, handle, store, directory = execution
    receipt = directory.read_receipt(handle.execution_id)
    stdout = Path(receipt.stdout_path)
    events = [json.loads(line) for line in stdout.read_text().splitlines()]
    if mutation == 'missing_usage':
        events.pop()
    elif mutation == 'failed_turn':
        events.append({'type': 'turn.failed', 'error': {'message': 'stream disconnected before completion'}})
    elif mutation == 'another_turn':
        events.append({'type': 'turn.started'})
    stdout.write_text('\n'.join(map(json.dumps, events)) + ('\n{"type":' if mutation == 'truncated_json' else '\n'))
    receipt = replace(receipt, status=ProcessReceiptStatus.ORPHANED, returncode=None,
        fencing_token=99 if mutation == 'wrong_fence' else receipt.fencing_token)
    directory.write_receipt(receipt)
    if mutation == 'wrong_fence':
        with pytest.raises(ValueError, match='identity'):
            backend.reconcile(handle)
    else:
        result = backend.reconcile(handle)
        assert result.outcome != ExecutionOutcome.SUCCEEDED
        assert result.normalized_output_ref is None


def test_zero_exit_without_measured_usage_keeps_unknown(execution):
    backend, handle, store, directory = execution
    receipt = directory.read_receipt(handle.execution_id)
    Path(receipt.stdout_path).write_text(json.dumps({'type': 'turn.completed', 'usage': {}}) + '\n')
    result = backend.reconcile(handle)
    assert result.outcome == ExecutionOutcome.UNKNOWN
    assert result.usage_receipt_ref is None
    assert store.get_record(handle.execution_id).raw_evidence['failure_disposition'] == 'RECONCILIATION_REQUIRED'


def test_late_usage_under_same_receipt_is_rechecked_without_redispatch(execution, monkeypatch):
    backend, handle, store, directory = execution
    receipt = directory.read_receipt(handle.execution_id)
    stdout = Path(receipt.stdout_path)
    complete = stdout.read_text()
    stdout.write_text(json.dumps({'type': 'turn.started'}) + '\n')
    assert backend.reconcile(handle).outcome == ExecutionOutcome.UNKNOWN
    stdout.write_text(complete)
    monkeypatch.setattr(backend.supervisor, 'run', lambda _: pytest.fail('no redispatch'))
    assert backend.reconcile(handle).outcome == ExecutionOutcome.SUCCEEDED
