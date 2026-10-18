from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.modules.story_planning_runtime.preparation_recovery import preparation_boundary, reuse_completed_task


@pytest.fixture
def retained(monkeypatch):
    task = {'contract_version': 'task-context-compression.v3', 'units': [{'unit_id': 'text:1', 'text': '原始段落'}], 'target_tokens': 30}
    output = {'selected_unit_ids': ['text:1']}
    original = dict(operation_id='old-operation', attempt_id='old-attempt', fencing_token=1,
        capability='model.planning', route_snapshot_id='old-route', input_manifest_ref='old-input')
    result = dict(execution_id='old-execution', output_manifest_ref='old-output', validation_report_ref='old-validation',
        usage_receipt_ref='old-usage', cost_receipt_ref='old-cost')
    receipt = dict(budget_reservation_status='SETTLED', provider_evidence=dict(result=output,
        real_model_call=True, provider_id='provider', model_id='model', production_execution=dict(
            execution_request=original, execution_result=result, execution_handle={'backend_id':'backend'})))
    retained = dict(external_effect_id='old-effect', stage='context_compress', task_hash=canonical_hash(task),
        result_hash=canonical_hash(output), request_hash='original-request-hash')
    binding = dict(source_operation_id='old-operation', project_id='project', workspace_id='workspace',book_id='book',
        successor_operation_id='new-operation',source_command={'actor_id':'author'},target_runtime={'preparation_handoff': {'retained_preparation':[retained]}})
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.return_value = ({'stage':'context_compress','input':{'context_compression_task':task}}, retained['request_hash'])
    read = MagicMock(return_value=receipt)
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.runtime_continuation.require_binding', lambda *_args:binding)
    monkeypatch.setattr('novel_forge.storage.authority_uow.AuthorityUnitOfWork', lambda *_args:uow)
    monkeypatch.setattr('novel_forge.modules.command_kernel.external_effect_runtime.read_acknowledged_preparation_success_in_uow', read)
    command = SimpleNamespace(runtime_continuation_id='registered-handoff', project_id='project',workspace_id='workspace',book_id='book', actor_id='author', trace_id='trace', correlation_id='correlation')
    return SimpleNamespace(task=task, output=output, receipt=receipt, retained=retained, binding=binding, uow=uow, read=read, command=command)


def test_registered_original_custody_survives_new_context_and_attempt_identity(retained):
    capture = {'input_manifest': {'past': '原始工作稿'}}
    original = dict(kind='FROZEN_STAGE_INPUTS',project_id='project',book_id='book',
        pack_snapshot_hash='old-snapshot',sources=[dict(asset_version_id='old-context',content_hash='old-context-hash')])
    current = {**original, 'pack_snapshot_hash':'new-snapshot', 'sources':[dict(asset_version_id='new-context',content_hash='new-context-hash')]}
    handoff = retained.binding['target_runtime']['preparation_handoff']
    handoff.update(preparation_source_projection_hash=canonical_hash(capture),preparation_source_boundary=original)
    boundary = preparation_boundary('database',command=retained.command,operation_id='new-operation',capture=capture,current=current)
    assert boundary == original
    assert current['sources'][0]['asset_version_id'] == 'new-context'
    boundary['sources'][0]['content_hash'] = 'local-edit'
    assert handoff['preparation_source_boundary'] == original
    assert preparation_boundary('database',command=retained.command,operation_id='new-operation',capture={'changed':'input'},current=current) == current


def consume(fixture, **changes):
    return reuse_completed_task('database', command=fixture.command, operation_id='new-operation',
        stage=changes.get('stage','context_compress'), task=changes.get('task',fixture.task))


def test_unchanged_preparation_consumes_original_receipt_and_identity(retained):
    recovered = consume(retained)
    assert recovered['selected_unit_ids'] == retained.output['selected_unit_ids']
    evidence = recovered['_execution_evidence']
    assert (evidence['operation_id'], evidence['attempt_id'], evidence['fencing_token'], evidence['external_receipt_ref']) == (
        'old-operation','old-attempt',1,'old-effect')
    assert evidence['receipt_reuse']['consumer_operation_id'] == 'new-operation'
    assert evidence['receipt_reuse']['provider_invoked_this_attempt'] is False
    retained.read.assert_called_once()
    retained.uow.commit.assert_not_called()


@pytest.mark.parametrize('change', ['text','target','unit_identity','stage','historical_contract','no_continuation'])
def test_changed_or_unregistered_task_cannot_borrow_old_unit_meaning(retained, change):
    task = deepcopy(retained.task)
    stage = 'context_compress'
    if change == 'text':
        task['units'][0]['text'] += '发生变化'
    elif change == 'target':
        task['target_tokens'] -= 1
    elif change == 'unit_identity':
        task['units'][0]['unit_id'] = 'text:2'
    elif change == 'stage':
        stage = 'context_fidelity'
    elif change == 'historical_contract':
        retained.binding['target_runtime'] = {}
    else:
        retained.command.runtime_continuation_id = ''
    assert consume(retained, stage=stage, task=task) is None
    retained.read.assert_not_called()


@pytest.mark.parametrize('change', ['request_hash','source_task','result_hash','unsettled','missing_receipt','book','actor','operation'])
def test_receipt_reuse_rejects_identity_drift_and_unsettled_results(retained, change):
    if change == 'request_hash':
        retained.retained['request_hash'] = 'wrong'
    elif change == 'source_task':
        payload, hash_value = retained.uow.cursor.fetchone.return_value
        payload = deepcopy(payload)
        payload['input']['context_compression_task']['units'][0]['text'] = '另一个来源'
        retained.uow.cursor.fetchone.return_value = payload, hash_value
    elif change == 'result_hash':
        retained.retained['result_hash'] = 'wrong'
    elif change == 'unsettled':
        retained.receipt['budget_reservation_status'] = 'HELD_UNKNOWN'
    elif change == 'missing_receipt':
        retained.read.return_value = None
    elif change == 'book':
        retained.command.book_id = 'foreign'
    elif change == 'actor':
        retained.command.actor_id = 'foreign'
    else:
        retained.binding['successor_operation_id'] = 'concurrent-successor'
    with pytest.raises(KernelError, match='PLANNING_PREPARATION_REUSE_DRIFT'):
        consume(retained)


def test_complete_request_preparer_replays_unchanged_tasks_from_original_receipts(retained):
    import json
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection, prepare_request_capacity
    from tests.unit.test_complete_request_capacity import route, run_preparation, source_data

    data, cache = source_data(), {}
    first, sent = run_preparation(data, limit=5000, cache=cache)
    assert first and sent
    records = {}
    for index, (stage, task) in enumerate(sent):
        output = cache[stage + json.dumps(task, sort_keys=True)]
        effect = f'old-effect-{index}'
        records[effect] = (stage, task, output)
    retained.binding['target_runtime']['preparation_handoff']['retained_preparation'] = [dict(
        external_effect_id=effect, stage=stage, task_hash=canonical_hash(task), result_hash=canonical_hash(output), request_hash=effect)
        for effect, (stage, task, output) in records.items()]

    def frozen_record():
        effect = retained.uow.cursor.execute.call_args.args[1][0]
        stage, task, _ = records[effect]
        return {'stage':stage,'input':{'context_compression_task':task}}, effect

    def read_receipt(_uow, _context, *, effect_id):
        receipt = deepcopy(retained.receipt)
        receipt['provider_evidence']['result'] = records[effect_id][2]
        return receipt

    retained.uow.cursor.fetchone.side_effect = frozen_record
    retained.read.side_effect = read_receipt
    capture = dict(data)
    boundary = dict(kind='FROZEN_STAGE_INPUTS',project_id='p',book_id='b',
        sources=[dict(asset_version_id='context:one',content_hash='sha256:'+'a'*64)])
    retained.binding['target_runtime']['preparation_handoff'].update(
        preparation_source_projection_hash=canonical_hash(capture), preparation_source_boundary=boundary)
    boundary = preparation_boundary('database', command=retained.command, operation_id='new-operation', capture=capture,
        current={**boundary, 'sources':[dict(asset_version_id='new-context',content_hash='new-hash')]})
    consumed = []

    def replay(stage, task):
        recovered = reuse_completed_task('database', command=retained.command, operation_id='new-operation',stage=stage,task=task)
        assert recovered is not None, 'unchanged real preparer task must not dispatch a new Provider call'
        consumed.append(recovered['_execution_evidence']['external_receipt_ref'])
        return recovered

    second = prepare_request_capacity(original=data, stage='draft', source_boundary=boundary,
        route=route(method='SCRIPTED_UTF8_BYTES_EXACT_V1',model='fixture',limit=5000),
        measure=lambda projection: (len(json.dumps(apply_capacity_projection(data,projection) if projection else data,ensure_ascii=False).encode())+100,5000),
        model_call=replay,chunk_fits=lambda chunk: len(json.dumps(chunk['units'])) < 1100)
    assert consumed and len(consumed) == len(sent)
    assert apply_capacity_projection(data, first) == apply_capacity_projection(data, second)
    assert all(effect in records for effect in consumed)
    retained.uow.commit.assert_not_called()
