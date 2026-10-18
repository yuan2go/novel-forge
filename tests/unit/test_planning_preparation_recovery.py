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


def test_terminal_handoff_uses_released_failure_receipt_without_reinterpreting_ack(retained, monkeypatch):
    retained.binding['target_runtime']['preparation_handoff']['contract_version'] = 'planning-terminal-preparation-handoff.v1'
    read = MagicMock(return_value=retained.receipt)
    monkeypatch.setattr('novel_forge.modules.command_kernel.external_effect_runtime.read_terminal_preparation_success_in_uow', read)
    assert consume(retained)['_execution_evidence']['receipt_reuse']['provider_invoked_this_attempt'] is False
    read.assert_called_once()
    retained.read.assert_not_called()


@pytest.mark.parametrize('row', [None, ('EXECUTING', False, False, False, False, 'context_fidelity'),
    ('FAILED_FINAL', True, False, False, False, 'context_fidelity'),
    ('FAILED_FINAL', False, True, False, False, 'context_fidelity'),
    ('FAILED_FINAL', False, False, True, False, 'context_fidelity'),
    ('FAILED_FINAL', False, False, False, True, 'context_fidelity'),
    ('FAILED_FINAL', False, False, False, False, 'chapter_plan.generate'),
    ('FAILED_FINAL', False, False, False, False, 'context_fidelity')])
def test_terminal_receipt_reader_requires_original_failure_and_released_submission_rights(monkeypatch, row):
    from novel_forge.modules.command_kernel import external_effect_runtime as runtime
    uow = MagicMock()
    uow.cursor.fetchone.return_value = row
    read = MagicMock(return_value={'original': 'verified'})
    monkeypatch.setattr(runtime, '_read_verified_success', read)
    context = runtime.EffectCommandContext('original', 'project', 'author', 'trace', 'correlation')
    if row == ('FAILED_FINAL', False, False, False, False, 'context_fidelity'):
        assert runtime.read_terminal_preparation_success_in_uow(uow, context, effect_id='effect') == {'original':'verified'}
        read.assert_called_once_with(uow, uow.repositories.external_effects, context, 'effect', retained_generation_stage=True)
    else:
        with pytest.raises(KernelError, match='EFFECT_RETAINED_STAGE_INVALID'):
            runtime.read_terminal_preparation_success_in_uow(uow, context, effect_id='effect')
        read.assert_not_called()


@pytest.mark.parametrize('change', ['unchanged', 'history', 'context', 'source_hash'])
def test_reconstructs_exact_custodian_capture_and_rejects_any_projection_drift(change):
    from novel_forge.modules.chapter_authority.provider_views import project_planning_narrative_intent
    from novel_forge.modules.story_planning_runtime.preparation_recovery import reconstruct_preparation_capture

    history = dict(snapshot_hash='history', text='原稿中她尚未开闸。')
    compiled = dict(selection_explanation=dict(literal_references=[]), frozen_by_operation_id='original-operation')
    context = dict(arc_working_set=dict(working_manuscript=history), context_manifest=dict(provider_context_view=dict(
        compiled_view=compiled, content_hash=canonical_hash(compiled))))
    original = dict(stage='chapter_plan.generate', output_protocol=dict(arc_working_set=dict(working_manuscript=history)), narrative_inputs={})
    _, projected, _ = project_planning_narrative_intent({}, compiled)
    capture = dict(input_manifest=original, context_bundle=projected)
    compressed = deepcopy(original)
    compressed['output_protocol']['arc_working_set']['working_manuscript'] = dict(source_projection_hash=canonical_hash(history), delivery='ORIGINAL_SOURCE_UNITS_PER_CHUNK')
    task = dict(task=dict(task_context=compressed, source_projection_hash=canonical_hash(capture)))
    if change == 'history':
        context['arc_working_set']['working_manuscript']['text'] += '改写'
    elif change == 'context':
        compiled['frozen_by_operation_id'] = 'new-consumer'
    elif change == 'source_hash':
        task['task']['source_projection_hash'] = 'wrong'
    if change == 'unchanged':
        assert reconstruct_preparation_capture(context, task) == capture
        assert compressed['output_protocol']['arc_working_set']['working_manuscript']['delivery'] == 'ORIGINAL_SOURCE_UNITS_PER_CHUNK'
    else:
        with pytest.raises(KernelError, match='PLANNING_PREPARATION_REUSE_DRIFT'):
            reconstruct_preparation_capture(context, task)


@pytest.mark.parametrize('drift', [False, True])
def test_realization_consumer_projection_preserves_original_sources_and_raw_custody(retained, monkeypatch, drift):
    from novel_forge.modules.story_planning_runtime.preparation_recovery import consumer_realization_catalog
    reference = dict(asset_version_id='original-source', content_hash='original-hash', frozen_by_operation_id='old-operation')
    context = dict(realization_reference_contract=dict(references_by_domain=dict(WORLD_STATE=[reference])))
    proof = dict(source_operation_id='old-operation', context_content_hash=canonical_hash(context))
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.preparation_recovery.terminal_custody', lambda *_: proof)
    if drift:
        reference['frozen_by_operation_id'] = 'foreign'
        proof['context_content_hash'] = canonical_hash(context)
        with pytest.raises(KernelError, match='PLANNING_PREPARATION_REUSE_DRIFT'):
            consumer_realization_catalog('database', command=retained.command, operation_id='new-operation', context=context)
    else:
        projected = consumer_realization_catalog('database', command=retained.command, operation_id='new-operation', context=context)
        assert projected['references_by_domain']['WORLD_STATE'] == [{**reference, 'frozen_by_operation_id':'new-operation'}]
        assert reference['frozen_by_operation_id'] == 'old-operation'
        assert canonical_hash(context) == proof['context_content_hash']


def test_terminal_group_without_world_preparation_keeps_the_native_non_world_path(monkeypatch):
    from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
    preparer = PostgresPlanningExecutionPreparer.__new__(PostgresPlanningExecutionPreparer)
    preparer.database_url = 'database'
    preparer._prepare_stage = MagicMock(return_value='native-stage')
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.preparation_recovery.terminal_custody', lambda *_: {'source_operation_id':'original'})
    action = MagicMock(side_effect=AssertionError('No World source was requested'))
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.preparation_recovery.retained_world_action', action)
    command = SimpleNamespace(world_preparation_request={})
    assert preparer.prepare(operation_id='successor', attempt_id='attempt', fencing_token=1, worker_id='worker',
        command=command, inputs=(), definition=None, attempt_snapshot=None) == 'native-stage'
    action.assert_not_called()
    assert preparer._prepare_stage.call_args.kwargs['world_action'] is None


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
