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


@pytest.mark.parametrize('receipt_contract', ['TERMINAL_PREPARATION', 'ISOLATED_GENERATION_SIBLING'])
def test_isolated_handoff_reads_each_receipt_from_its_actual_original_owner(retained, monkeypatch, receipt_contract):
    handoff = retained.binding['target_runtime']['preparation_handoff']
    handoff['contract_version'] = 'planning-isolated-preparation-handoff.v1'
    retained.retained.update(operation_id='actual-preparation-owner', receipt_contract=receipt_contract)
    read = MagicMock(return_value=retained.receipt)
    reader = 'read_terminal_preparation_success_in_uow' if receipt_contract == 'TERMINAL_PREPARATION' else 'read_retained_generation_stage_success_in_uow'
    monkeypatch.setattr('novel_forge.modules.command_kernel.external_effect_runtime.' + reader, read)
    assert consume(retained)['_execution_evidence']['receipt_reuse']['provider_invoked_this_attempt'] is False
    assert read.call_args.args[1].operation_id == 'actual-preparation-owner'
    retained.read.assert_not_called()


@pytest.fixture
def isolated_chain(monkeypatch):
    from novel_forge.modules.story_planning_runtime import preparation_recovery as recovery
    frozen = dict(project_id='project', workspace_id='workspace', book_id='book', actor_id='author', trace_id='trace',
        correlation_id='correlation', runtime_continuation_id='isolated-link', idempotency_key='new',
        arc_working_set=dict(working_manuscript=dict(book_run_id='run')))
    task = dict(frozen_input_boundary={'kind': 'original-boundary'}, task={'source_projection_hash': 'projection'})
    output = {'retained': 'original result'}
    receipt = dict(budget_reservation_status='SETTLED', provider_evidence=dict(result=output))
    def item(effect):
        return dict(external_effect_id=effect, stage='context_compress', request_hash='request',
                    task_hash=canonical_hash(task), result_hash=canonical_hash(output))
    handoff = dict(contract_version='planning-terminal-preparation-handoff.v1', source_operation_id='original',
        retained_preparation=[item('original-success')], context_asset_version_id='context', context_content_hash='hash',
        preparation_source_boundary=task['frozen_input_boundary'], preparation_source_projection_hash='projection',
        current_chapter=18, accepted_through_chapter=0, input_snapshot_id='book-input')
    capacity = dict(context_revalidation=dict(contract_version='same-capacity-semantic-preparation.v1',
        context_asset_version_id='context', context_content_hash='hash'))
    def row(operation, source, target):
        return ('link:' + operation, source, deepcopy(frozen), deepcopy(frozen), target, 'FAILED_FINAL',
            'author', 'workspace', 'book', None, deepcopy(frozen), {'operation_id':operation})
    chain = {'interrupted': row('interrupted', 'consumer', dict(planning_capacity=deepcopy(capacity))),
             'consumer': row('consumer', 'original', dict(planning_capacity=deepcopy(capacity), preparation_handoff=handoff))}
    def effect(identity, status='SUCCEEDED', stage='context_compress'):
        return dict(external_effect_id=identity, effect_type='model.invoke', status=status, request_hash='request',
                    request_payload=dict(stage=stage, input=dict(context_compression_task=deepcopy(task))))
    effects = {'original': [(effect('original-success'), 'SETTLED', False)],
               'consumer': [(effect('consumer-success'), 'SETTLED', False), (effect('unknown', 'UNKNOWN'), 'HELD_UNKNOWN', True)],
               'interrupted': [(effect('world-unknown', 'UNKNOWN', 'world_candidates.evaluate'), 'HELD_UNKNOWN', True)]}
    state = SimpleNamespace(chain=chain, effects=effects, frozen=frozen, handoff=handoff,no_isolation=set(),
        book=(18, 0, 'book-input', 'PAUSED', None), held=False,
        isolation=dict(contract_version='pure-generation-isolation.v1',business_commit_right='REVOKED',activation_right='REVOKED'))
    uow = MagicMock()
    def execute(sql, args):
        assert sql.count('%s') == len(args)
    uow.cursor.execute.side_effect = execute
    def fetchone():
        sql, args = uow.cursor.execute.call_args.args
        if 'FROM authority_story_planning_runtime_continuation link' in sql:
            return chain.get(args[0])
        if 'SELECT root_operation_id' in sql:
            return ('book-root',)
        if 'SELECT current_chapter' in sql:
            return state.book
        if 'SELECT proof FROM authority_generation_isolation' in sql:
            return None if args[0] in state.no_isolation else (state.isolation,)
        if 'SELECT EXISTS' in sql:
            return (state.held,)
        raise AssertionError(sql)
    uow.cursor.fetchone.side_effect = fetchone
    uow.cursor.fetchall.side_effect = lambda: effects[uow.cursor.execute.call_args.args[1][0]]
    monkeypatch.setattr('novel_forge.modules.book_authority.manuscript.historical_working_inputs', lambda *_:('book', []))
    monkeypatch.setattr('novel_forge.modules.chapter_group_authority.replan_retirement.lock_replan_roots', lambda *_a, **_k:None)
    for name in ('read_terminal_preparation_success_in_uow', 'read_retained_generation_stage_success_in_uow'):
        monkeypatch.setattr('novel_forge.modules.command_kernel.external_effect_runtime.' + name, MagicMock(return_value=receipt))
    state.uow = uow
    state.consume = lambda: recovery.isolated_preparation_source(uow, source_operation_id='interrupted', frozen=frozen)
    return state


def test_isolated_ancestry_collects_only_settled_successful_tasks_and_keeps_original_custody(isolated_chain):
    proof = isolated_chain.consume()
    assert proof['contract_version'] == 'planning-isolated-preparation-handoff.v1'
    assert proof['source_operation_id'] == 'original'
    assert proof['isolation_source_operation_id'] == 'interrupted'
    assert [(item['operation_id'], item['external_effect_id']) for item in proof['retained_preparation']] == [
        ('original', 'original-success'), ('consumer', 'consumer-success')]
    assert proof['original_handoff_hash'] == canonical_hash(isolated_chain.handoff)
    assert isolated_chain.effects['consumer'][1][0]['status'] == 'UNKNOWN'


@pytest.mark.parametrize('drift', ['actor', 'book', 'command', 'frontier', 'acceptance', 'snapshot', 'cancelled_book', 'active_child',
    'live_rights', 'isolation_right', 'unisolated_unknown', 'unsettled', 'boundary', 'projection', 'candidate', 'capacity_context'])
def test_isolated_preparation_rejects_stale_foreign_live_unknown_and_changed_input(isolated_chain, drift):
    state = isolated_chain
    if drift in {'actor', 'book', 'command', 'candidate', 'capacity_context'}:
        row = list(state.chain['interrupted'])
        if drift == 'actor':
            row[6] = 'other'
        elif drift == 'book':
            row[8] = 'foreign'
        elif drift == 'command':
            row[3]['idempotency-independent-input'] = 'changed'
        elif drift == 'candidate':
            row[9] = 'already-generated'
        else:
            row[4]['planning_capacity']['context_revalidation']['context_content_hash'] = 'changed'
        state.chain['interrupted'] = tuple(row)
    elif drift in {'frontier', 'acceptance', 'snapshot', 'cancelled_book', 'active_child'}:
        row = list(state.book)
        index, value = {'frontier':(0,19),'acceptance':(1,1),'snapshot':(2,'other'),'cancelled_book':(3,'CANCELLED'),'active_child':(4,'other')}[drift]
        row[index] = value
        state.book = tuple(row)
    elif drift == 'live_rights':
        state.held = True
    elif drift == 'isolation_right':
        state.isolation['business_commit_right'] = 'ACTIVE'
    else:
        effect, budget, isolated = state.effects['consumer'][1 if drift == 'unisolated_unknown' else 0]
        if drift == 'unisolated_unknown':
            state.effects['consumer'][1] = effect, budget, False
        elif drift == 'unsettled':
            state.effects['consumer'][0] = effect, 'HELD', isolated
        elif drift == 'boundary':
            effect['request_payload']['input']['context_compression_task']['frozen_input_boundary'] = {'foreign':'source'}
        else:
            effect['request_payload']['input']['context_compression_task']['task']['source_projection_hash'] = 'changed'
    with pytest.raises(KernelError, match='PLANNING_PREPARATION_HANDOFF_UNSAFE'):
        state.consume()


@pytest.mark.parametrize('stage', ['world_candidates.actor_0', 'world_candidates.actor_1', 'world_candidates.actor_2'])
def test_original_world_actor_stage_names_do_not_block_same_input_preparation(isolated_chain, stage):
    state = isolated_chain
    actor = deepcopy(state.effects['consumer'][0][0])
    actor.update(external_effect_id='actor-success', request_payload={'stage': stage})
    state.effects['consumer'].append((actor, 'SETTLED', False))
    proof = state.consume()
    assert len(proof['retained_preparation']) == 2
    assert all(item['external_effect_id'] != 'actor-success' for item in proof['retained_preparation'])


def test_sent_main_retains_existing_isolation_recovery_without_unsent_preparation_authority(isolated_chain):
    state = isolated_chain
    state.effects['consumer'][1][0]['request_payload']['stage'] = 'chapter_plan.generate'
    assert state.consume() is None
    assert state.effects['consumer'][1][0]['status'] == 'UNKNOWN'


@pytest.fixture(params=["query", "lineage"])
def query_handoff(monkeypatch, request):
    from novel_forge.modules.story_planning_runtime.preparation_recovery import unsent_query_source, ISOLATED_HANDOFF
    frozen = dict(project_id='project',workspace_id='workspace',book_id='book',actor_id='author',runtime_continuation_id='prior',
        arc_working_set=dict(working_manuscript=dict(book_run_id='run')))
    content = dict(arc_working_set=frozen['arc_working_set'],input_versions=[dict(role='plan',asset_version_id='plan',content_hash='plan-hash',asset_type='chapter_group_plan')])
    digest = canonical_hash(content)
    inherited = dict(contract_version=ISOLATED_HANDOFF,context_asset_version_id='original-context',context_content_hash=digest,
        current_chapter=18,accepted_through_chapter=0,input_snapshot_id='book-input',retained_preparation=[{'external_effect_id':'old-success'}])
    binding = dict(successor_operation_id='failed',successor_command=frozen,target_runtime=dict(preparation_handoff=inherited,
        planning_capacity=dict(source_failure={'original':'capacity'},context_revalidation={'original':'frozen'})))
    failure = dict(error_code='PROGRAMMING_BUG',error_message='canceling statement due to statement timeout',failure_class='programming_bug',failure_details={})
    lineage = request.param == 'lineage'
    if lineage:
        failure.update(error_code='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED', error_message='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth', failure_class='retryable')
    status = 'FAILED_RETRYABLE' if lineage else 'FAILED_FINAL'
    state = SimpleNamespace(status=status,contract='planning-unsent-preparation-lineage-handoff.v1' if lineage else 'planning-unsent-preparation-query-handoff.v1',failure_key='unsent_lineage_failure' if lineage else 'unsent_query_failure',unsafe=False,book=(18,0,'book-input','READY',None,False),
        operation=dict(actor_id='author',workspace_id='workspace'),frozen=frozen,binding=binding,
        outputs=[('saved-context',digest,'planning.context_bundle','context_bundle')],failure=failure,
        snapshot=[({'context_policy_ref':'context-policy:chapter-generation-pack:v4'},'snapshot','snapshot-hash','failed-attempt')])
    documents = {'original-context':SimpleNamespace(asset_version_id='original-context',content_hash=digest,content=content,asset_type='context_bundle'),
                 'saved-context':SimpleNamespace(asset_version_id='saved-context',content_hash=digest,content=deepcopy(content),asset_type='context_bundle'),
                 'plan':SimpleNamespace(content_hash='plan-hash',asset_type='chapter_group_plan')}
    state.documents = documents
    uow = MagicMock()
    uow.database_url = 'db'
    def execute(sql, args):
        assert sql.count('%s') == len(args)
    uow.cursor.execute.side_effect = execute
    def fetchone():
        sql,_ = uow.cursor.execute.call_args.args
        if 'to_jsonb(operation)' in sql:
            return state.operation,state.unsafe
        if 'SELECT root_operation_id' in sql:
            return ('book-root',)
        if 'SELECT current_chapter' in sql:
            return state.book
        if 'SELECT input_snapshot ' in sql:
            return (deepcopy(content['input_versions']),)
        if 'SELECT chain_depth' in sql:
            return (8,)
        raise AssertionError(sql)
    uow.cursor.fetchone.side_effect = fetchone
    uow.cursor.fetchall.side_effect = lambda:state.outputs if 'FROM authority_operation_output_asset' in uow.cursor.execute.call_args.args[0] else state.snapshot
    uow.repositories.asset_documents.require.side_effect = lambda **kw:documents[kw['asset_version_id']]
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.runtime_continuation.require_binding',lambda *_:binding)
    monkeypatch.setattr('novel_forge.modules.book_authority.manuscript.historical_working_inputs',lambda *_:('book',[]))
    monkeypatch.setattr('novel_forge.modules.chapter_group_authority.replan_retirement.lock_replan_roots',lambda *_a,**_kw:None)
    state.consume = lambda:unsent_query_source(uow,source_operation_id='failed',row=(state.status,3),frozen=frozen,attempt=(state.status,{},failure))
    return state


def test_terminal_unsent_query_retains_saved_context_and_original_preparation_in_new_proof(query_handoff):
    state = query_handoff
    original = deepcopy(state.binding)
    source = state.consume()
    proof = source['completed_preparation']
    assert source['mode'] == 'PRE_SEND_CAPACITY' and source['depth'] == 9
    assert proof['contract_version'] == state.contract
    assert proof['retained_preparation'] == original['target_runtime']['preparation_handoff']['retained_preparation']
    failure = proof[state.failure_key]
    assert failure['source_context']['asset_version_id'] == 'saved-context'
    assert failure['original_failure_hash'] == canonical_hash(state.failure)
    assert failure['inherited_preparation_hash'] == canonical_hash(original['target_runtime']['preparation_handoff'])
    assert state.binding == original


@pytest.mark.parametrize('change', ['effects_or_budget_or_live_rights','actor','frontier','acceptance','snapshot','cancel','active_child',
    'wrong_output','extra_output','output_hash','primary_output','saved_bytes','source_hash','input_hash','input_type','source_command','failure'])
def test_query_handoff_rejects_source_context_frontier_or_execution_drift(query_handoff, change):
    state = query_handoff
    if change == 'effects_or_budget_or_live_rights':
        state.unsafe = True
    elif change == 'actor':
        state.operation['actor_id'] = 'foreign'
    elif change in {'frontier','acceptance','snapshot','cancel','active_child'}:
        values = list(state.book)
        index,value = {'frontier':(0,19),'acceptance':(1,1),'snapshot':(2,'changed'),'cancel':(5,True),'active_child':(4,'child')}[change]
        values[index] = value
        state.book = tuple(values)
    elif change in {'wrong_output','extra_output','output_hash','primary_output'}:
        values = list(state.outputs[0])
        if change == 'extra_output':
            state.outputs.append(tuple(values))
        else:
            index,value = {'wrong_output':(2,'chapter.draft'),'output_hash':(1,'changed'),'primary_output':(3,'primary')}[change]
            values[index] = value
            state.outputs[0] = tuple(values)
    elif change == 'saved_bytes':
        state.documents['saved-context'].content['changed'] = True
    elif change == 'source_hash':
        state.documents['original-context'].content_hash = 'changed'
    elif change in {'input_hash','input_type'}:
        setattr(state.documents['plan'],'content_hash' if change=='input_hash' else 'asset_type','changed')
    elif change == 'source_command':
        state.binding['successor_command'] = {'other':'request'}
    else:
        state.failure['error_message'] = 'another programming bug'
    with pytest.raises(KernelError,match='PLANNING_PREPARATION_QUERY_HANDOFF_UNSAFE'):
        state.consume()


@pytest.mark.parametrize('damage', [None, 'pack', 'attempt', 'stage', 'bytes', 'inner_hash', 'type', 'role', 'key', 'hash'])
def test_unsent_host_failure_retains_only_exact_local_preparation_materialization(query_handoff, damage):
    state = query_handoff
    pack = dict(pack_id='pack',pack_version='version',manifest_hash='manifest',compilation_hash='compilation',catalog_snapshot_hash='catalog',binding_set_id='binding',binding_set_hash='binding-hash')
    state.snapshot[0][0].update(pack)
    contract = dict(schema_version='novelos.planning_capability_materialization.v1',stage='context_fidelity',pack_identity=deepcopy(pack),
        attempt_snapshot=dict(operation_id='failed',attempt_id='failed-attempt',snapshot_id='snapshot',snapshot_hash='snapshot-hash'))
    if damage == 'pack':
        contract['pack_identity']['pack_id']='foreign'
    if damage == 'attempt':
        contract['attempt_snapshot']['attempt_id']='foreign'
    if damage == 'stage':
        contract['stage']='chapter_plan.generate'
    contract['materialization_hash']=canonical_hash(contract)
    if damage == 'inner_hash':
        contract['materialization_hash']='wrong'
    content=dict(contract=contract)
    digest=canonical_hash(content)
    state.documents['materialization']=SimpleNamespace(asset_type='other' if damage=='type' else 'capability_materialization_manifest',content=content,content_hash=digest)
    if damage == 'bytes':
        content['altered']=True
    state.outputs.append(('materialization','wrong' if damage=='hash' else digest,
        'planning.other' if damage=='key' else 'production_execution.contract.capability_materialization_manifest.token',
        'primary' if damage=='role' else 'execution_contract'))
    if damage:
        with pytest.raises(KernelError,match='PLANNING_PREPARATION_QUERY_HANDOFF_UNSAFE'):
            state.consume()
    else:
        proof=state.consume()['completed_preparation']
        assert proof['retained_local_preparation']==[dict(asset_version_id='materialization',content_hash=digest,
            output_key=state.outputs[-1][2],role='execution_contract',asset_type='capability_materialization_manifest',stage='context_fidelity')]
        assert proof['retained_preparation']==state.binding['target_runtime']['preparation_handoff']['retained_preparation']


@pytest.mark.parametrize('damage', [None, 'missing_receipt', 'receipt_hash', 'retained_proof', 'live_source', 'unisolated_current'])
def test_isolation_crosses_only_control_proven_unsent_carriers_without_granting_them_isolation(isolated_chain, monkeypatch, damage):
    from novel_forge.modules.story_planning_runtime.preparation_recovery import LINEAGE_HANDOFF, QUERY_HANDOFF
    state = isolated_chain
    def carrier_row(identity, source, handoff):
        row = list(state.chain['interrupted'])
        row[0],row[1] = 'link:'+identity,source
        row[4] = {**deepcopy(row[4]), 'preparation_handoff':handoff}
        row[11] = {'operation_id':identity}
        return tuple(row)
    query = dict(contract_version=QUERY_HANDOFF,unsent_query_failure=dict(source_operation_id='query-carrier'))
    lineage = dict(contract_version=LINEAGE_HANDOFF,unsent_lineage_failure=dict(source_operation_id='lineage-carrier'))
    state.chain['interrupted'] = carrier_row('interrupted','lineage-carrier',lineage)
    state.chain['lineage-carrier'] = carrier_row('lineage-carrier','query-carrier',query)
    state.chain['query-carrier'] = carrier_row('query-carrier','consumer',dict(contract_version='planning-isolated-preparation-handoff.v1'))
    state.effects.update({'lineage-carrier':[],'query-carrier':[]})
    state.no_isolation.update({'lineage-carrier','query-carrier'})
    if damage == 'unisolated_current':
        state.no_isolation.add('interrupted')
    receipts={}
    proofs={'lineage-carrier':lineage,'query-carrier':query}
    for identity in ('interrupted','lineage-carrier'):
        row=state.chain[identity]
        receipt=dict(source_operation_id=row[1],successor_command=row[3],target_runtime=row[4])
        receipts[row[0]]=[(receipt,canonical_hash(receipt))]
    if damage == 'missing_receipt':
        receipts['link:lineage-carrier']=[]
    if damage == 'receipt_hash':
        receipts['link:lineage-carrier'][0]=(receipts['link:lineage-carrier'][0][0],'changed')
    original_fetch=state.uow.cursor.fetchall.side_effect
    def fetchall():
        sql,args=state.uow.cursor.execute.call_args.args
        return receipts[args[0]] if 'control.status' in sql else original_fetch()
    state.uow.cursor.fetchall.side_effect=fetchall
    seen=[]
    def require_source(uow, *, source_operation_id, project_id):
        seen.append(source_operation_id)
        assert not state.effects[source_operation_id]
        if damage == 'live_source':
            raise KernelError('PLANNING_PREPARATION_HANDOFF_UNSAFE','Source has active rights')
        return dict(completed_preparation={} if damage=='retained_proof' else proofs[source_operation_id])
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.runtime_continuation.require_source',require_source)
    if damage:
        with pytest.raises(KernelError,match='PLANNING_PREPARATION_HANDOFF_UNSAFE'):
            state.consume()
    else:
        result=state.consume()
        assert set(seen)=={'lineage-carrier','query-carrier'}
        assert {row['external_effect_id'] for row in result['retained_preparation']}=={'original-success','consumer-success'}
        assert state.effects['consumer'][1][0]['status']=='UNKNOWN'


@pytest.mark.parametrize('changed', ['', 'input', 'projection', 'request', 'actor', 'book', 'consumer'])
def test_prepared_main_projection_reuses_complete_frozen_inputs_without_new_preparation(retained, changed):
    from novel_forge.modules.story_planning_runtime.preparation_recovery import retained_main_projection
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection
    from tests.unit.test_complete_request_capacity import run_preparation, source_data

    data = source_data()
    projection, sent = run_preparation(data, limit=5000, cache={})
    assert projection and sent
    original_inputs = dict(narrative=data, _context_capacity_projection=deepcopy(projection))
    payload = dict(stage='chapter_plan.generate', input=deepcopy(original_inputs))
    frozen = deepcopy(payload)
    retained.command.generator_operation_name = 'chapter_plan.generate'
    handoff = retained.binding['target_runtime']['preparation_handoff']
    handoff.update(contract_version='planning-prepared-main-handoff.v1', prepared_main_failure=dict(
        external_effect_id='main',source_operation_id='source',request_hash=canonical_hash(payload),
        input_hash=canonical_hash(original_inputs),projection_hash=canonical_hash(projection)))
    inputs = dict(narrative=deepcopy(data))
    if changed == 'input':
        inputs['foreign'] = 'changed'
    elif changed == 'projection':
        payload['input']['_context_capacity_projection']['result_hash'] = 'changed'
    elif changed == 'request':
        payload['stage'] = 'changed'
    elif changed in {'actor','book'}:
        setattr(retained.command,changed+'_id','foreign')
    elif changed == 'consumer':
        retained.binding['successor_operation_id'] = 'foreign'
    retained.uow.cursor.fetchone.return_value = (payload, canonical_hash(frozen))
    if changed:
        with pytest.raises(KernelError,match='PLANNING_PREPARATION_REUSE_DRIFT'):
            retained_main_projection('database',command=retained.command,operation_id='new-operation',inputs=inputs,stage='chapter_plan.generate')
    else:
        restored = retained_main_projection('database',command=retained.command,operation_id='new-operation',inputs=inputs,stage='chapter_plan.generate')
        assert restored == projection
        assert apply_capacity_projection(data, restored) == apply_capacity_projection(data, projection)
        restored['result_hash'] = 'consumer-local-change'
        assert payload == frozen
    retained.read.assert_not_called()
    retained.uow.commit.assert_not_called()


@pytest.mark.parametrize('major', range(1,11))
def test_continuation_contract_uses_full_frozen_major(major):
    from novel_forge.modules.story_planning_runtime.runtime_continuation import runtime_continuation_definition
    definition = runtime_continuation_definition(application_build_id='build',commit_sha='sha',definition_version=f'{major}.0.0')
    assert definition['handler_contract_version'] == f'planning-runtime-continuation.v{major}'
    assert definition['command_schema_version'] == f'planning-runtime-continuation.command.v{major}'
    assert definition['result_schema_version'] == f'planning-runtime-continuation.result.v{major}'


@pytest.fixture
def prepared_main_source_state(monkeypatch):
    from novel_forge.modules.story_planning_runtime import (
        preparation_recovery as recovery,
    )

    frozen = dict(
        project_id="project",
        workspace_id="workspace",
        book_id="book",
        actor_id="author",
        runtime_continuation_id="prior",
        execution_contract_version="1.21.0",
        generator_operation_name="chapter_plan.generate",
        trace_id="trace",
        correlation_id="correlation",
        arc_working_set=dict(working_manuscript=dict(book_run_id="run")),
    )
    content = dict(arc_working_set=frozen["arc_working_set"], input_versions=[])
    boundary = dict(kind="FROZEN_STAGE_INPUTS")
    inherited = dict(
        contract_version=recovery.LINEAGE_HANDOFF,
        context_asset_version_id="context",
        context_content_hash=canonical_hash(content),
        current_chapter=18,
        accepted_through_chapter=0,
        input_snapshot_id="book-input",
        retained_preparation=[],
        preparation_source_boundary=boundary,
        preparation_source_projection_hash="projection",
    )
    binding = dict(
        successor_operation_id="source",
        successor_command=frozen,
        target_runtime=dict(
            preparation_handoff=inherited,
            planning_capacity=dict(
                source_failure={"retained": "failure"},
                context_revalidation={"retained": "policy"},
            ),
        ),
    )
    failure = dict(
        error_code="EFFECT_RETRYABLE_FAILURE_RECORDED",
        error_message="EFFECT_RETRYABLE_FAILURE_RECORDED: adapter exception was recorded as retryable_failure",
        failure_class="retryable",
        failure_details={},
    )
    payload = dict(
        stage="chapter_plan.generate",
        operation_id="source",
        _production_execution=dict(attempt_id="attempt"),
        input=dict(
            _context_capacity_projection=dict(
                source_boundary=boundary, original_hash="projection"
            )
        ),
    )
    main = dict(
        external_effect_id="main",
        effect_type="model.invoke",
        status="FAILED_RETRYABLE",
        request_payload=payload,
        request_hash=canonical_hash(payload),
        last_error=deepcopy(recovery.PRE_SUBMIT_FAILURE),
    )
    task = dict(
        frozen_input_boundary=boundary, task=dict(source_projection_hash="projection")
    )
    prepared = dict(
        external_effect_id="prepared",
        effect_type="model.invoke",
        status="SUCCEEDED",
        request_hash="prepared-hash",
        request_payload=dict(
            stage="context_fidelity", input=dict(context_compression_task=task)
        ),
    )
    state = SimpleNamespace(
        frozen=frozen,
        binding=binding,
        failure=failure,
        unsafe=False,
        external_unsafe=False,
        operation=dict(actor_id="author", workspace_id="workspace"),
        book=(18, 0, "book-input", "READY", None, False),
        snapshot=[
            (
                {"context_policy_ref": "context-policy:chapter-generation-pack:v4"},
                "snapshot",
                "snapshot-hash",
                "attempt",
            )
        ],
        effects=[(main, "RELEASED"), (prepared, "SETTLED")],
        dispatches=[
            ("dispatch", 1, "FAILED_RETRYABLE", deepcopy(recovery.PRE_SUBMIT_FAILURE))
        ],
    )
    uow = MagicMock()
    uow.database_url = "db"
    uow.cursor.execute.side_effect = lambda sql, args: (
        None if sql.count("%s") == len(args) else pytest.fail("SQL arguments drift")
    )

    def fetchone():
        sql, _ = uow.cursor.execute.call_args.args
        if "to_jsonb(operation)" in sql:
            return state.operation, state.unsafe
        if "SELECT root_operation_id" in sql:
            return ("book-root",)
        if "SELECT current_chapter" in sql:
            return state.book
        if "SELECT EXISTS" in sql:
            return (state.external_unsafe,)
        if "SELECT input_snapshot " in sql:
            return ([],)
        if "SELECT chain_depth" in sql:
            return (9,)
        raise AssertionError(sql)

    def fetchall():
        sql, _ = uow.cursor.execute.call_args.args
        if "SELECT snapshot_payload" in sql:
            return state.snapshot
        if "to_jsonb(effect)" in sql:
            return state.effects
        if "SELECT dispatch_id" in sql:
            return state.dispatches
        raise AssertionError(sql)

    uow.cursor.fetchone.side_effect = fetchone
    uow.cursor.fetchall.side_effect = fetchall
    uow.repositories.asset_documents.require.return_value = SimpleNamespace(
        asset_version_id="context",
        content_hash=canonical_hash(content),
        content=content,
    )
    monkeypatch.setattr(
        "novel_forge.modules.story_planning_runtime.runtime_continuation.require_binding",
        lambda *_: binding,
    )
    monkeypatch.setattr(
        "novel_forge.modules.book_authority.manuscript.historical_working_inputs",
        lambda *_: ("book", []),
    )
    monkeypatch.setattr(
        "novel_forge.modules.chapter_group_authority.replan_retirement.lock_replan_roots",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "novel_forge.modules.command_kernel.external_effect_runtime.read_retained_generation_stage_success_in_uow",
        MagicMock(
            return_value=dict(
                budget_reservation_status="SETTLED",
                provider_evidence=dict(result={"verified": True}),
            )
        ),
    )
    state.consume = lambda: recovery.prepared_main_source(
        uow,
        source_operation_id="source",
        row=("FAILED_RETRYABLE", 3, "workspace", frozen, "book", None),
        frozen=frozen,
        attempt=("FAILED_RETRYABLE", {}, failure),
    )
    state.uow = uow
    return state


@pytest.mark.parametrize(
    "damage",
    [
        "",
        "actor",
        "book-frontier",
        "accepted",
        "concurrent",
        "cancelled",
        "input-snapshot",
        "lease",
        "external-rights",
        "snapshot",
        "sent",
        "unknown",
        "request-hash",
        "duplicate-main",
        "extra-effect",
        "unsettled-preparation",
        "wrong-preparation-boundary",
        "dispatch",
        "second-dispatch",
        "projection",
    ],
)
def test_prepared_main_source_requires_exact_failed_send_boundary_and_all_settled_preparation(
    prepared_main_source_state, damage
):
    s = prepared_main_source_state
    main = s.effects[0][0]
    if damage == "actor":
        s.operation["actor_id"] = "foreign"
    elif damage in {
        "book-frontier",
        "accepted",
        "concurrent",
        "cancelled",
        "input-snapshot",
    }:
        book = list(s.book)
        index, value = {
            "book-frontier": (0, 19),
            "accepted": (1, 1),
            "concurrent": (4, "other"),
            "cancelled": (5, True),
            "input-snapshot": (2, "changed"),
        }[damage]
        book[index] = value
        s.book = tuple(book)
    elif damage == "lease":
        s.unsafe = True
    elif damage == "external-rights":
        s.external_unsafe = True
    elif damage == "snapshot":
        s.snapshot = []
    elif damage == "sent":
        main["last_error"]["request_sent"] = True
    elif damage == "unknown":
        main["status"] = "UNKNOWN"
    elif damage == "request-hash":
        main["request_hash"] = "changed"
    elif damage == "duplicate-main":
        s.effects.append(deepcopy(s.effects[0]))
    elif damage == "extra-effect":
        s.effects.append(
            (
                dict(
                    external_effect_id="extra",
                    effect_type="model.invoke",
                    status="UNKNOWN",
                    request_payload={},
                ),
                "HELD_UNKNOWN",
            )
        )
    elif damage == "unsettled-preparation":
        s.effects[1] = (s.effects[1][0], "HELD_UNKNOWN")
    elif damage == "wrong-preparation-boundary":
        s.effects[1][0]["request_payload"]["input"]["context_compression_task"][
            "frozen_input_boundary"
        ] = {"foreign": True}
    elif damage == "dispatch":
        s.dispatches[0] = ("dispatch", 1, "UNKNOWN", {})
    elif damage == "second-dispatch":
        s.dispatches.append(s.dispatches[0])
    elif damage == "projection":
        main["request_payload"]["input"]["_context_capacity_projection"][
            "original_hash"
        ] = "changed"
        main["request_hash"] = canonical_hash(main["request_payload"])
    original = deepcopy(s.binding)
    if damage:
        with pytest.raises(KernelError, match="PLANNING_PREPARED_MAIN_HANDOFF_UNSAFE"):
            s.consume()
    else:
        proof = s.consume()["completed_preparation"]
        assert proof["main_dispatch_count"] == 1
        assert proof["prepared_main_failure"]["request_hash"] == main["request_hash"]
        assert proof["retained_preparation"][0]["operation_id"] == "source"
        assert (
            proof["retained_preparation"][0]["receipt_contract"]
            == "STOPPED_GENERATION_SIBLING"
        )
    assert s.binding == original
    s.uow.commit.assert_not_called()


@pytest.mark.parametrize("router", [None, "router"])
@pytest.mark.parametrize("change", ["", "missing", "route"])
def test_complete_main_projection_retains_capacity_bound_candidate(
    retained, monkeypatch, router, change
):
    from novel_forge.modules.story_planning_runtime.preparation_recovery import (
        retained_main_capacity_binding,
    )
    from novel_forge.modules.production_execution.token_meter import (
        capacity_route_contract,
    )
    from tests.unit.test_complete_request_capacity import route

    selected = route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture", limit=5000)
    selected.model_profile.reasoning_effort = "medium"
    selected.model_profile.backend_id = "fixture"
    selected.model_output_limit = 5000
    selected.output_reservation_policy = ""
    binding = dict(
        route=capacity_route_contract(selected), candidate={"candidate_id": "frozen"}
    )
    bindings = {"chapter_plan.generate": binding}
    if change == "missing":
        bindings = {}
    elif change == "route":
        binding["route"]["reasoning"] = "changed"
    handoff = retained.binding["target_runtime"]["preparation_handoff"]
    handoff.update(
        contract_version="planning-prepared-main-handoff.v1",
        prepared_main_failure={"source_operation_id": "original-main-owner"},
    )
    read = MagicMock(return_value=bindings)
    monkeypatch.setattr(
        "novel_forge.modules.chapter_authority.receipt_recovery.retained_capacity_bindings",
        read,
    )
    args = dict(
        command=retained.command,
        operation_id="new-operation",
        projection=dict(original_hash="original", source_boundary={"original": True}),
        stage="chapter_plan.generate",
        route=selected,
        router=router,
    )
    if change == "missing" or change == "route" and router is None:
        with pytest.raises(KernelError, match="ROUTING_CAPACITY_BINDING_DRIFT"):
            retained_main_capacity_binding("db", **args)
    else:
        assert retained_main_capacity_binding("db", **args) == binding
    assert read.call_args.kwargs["operation_id"] == "original-main-owner"
    assert read.call_args.kwargs["source_hash"] == "original"


def test_host_failure_after_prepared_main_keeps_complete_projection_custody(
    query_handoff,
):
    from novel_forge.modules.story_planning_runtime.preparation_recovery import (
        PREPARED_MAIN_HANDOFF,
    )

    state = query_handoff
    inherited = state.binding["target_runtime"]["preparation_handoff"]
    inherited.update(
        contract_version=PREPARED_MAIN_HANDOFF,
        main_dispatch_count=1,
        prepared_main_failure=dict(
            source_operation_id="original-main",
            external_effect_id="failed-main",
            projection_hash="frozen",
        ),
    )
    original = deepcopy(inherited)
    proof = state.consume()["completed_preparation"]
    assert proof["contract_version"] == PREPARED_MAIN_HANDOFF
    assert proof["main_dispatch_count"] == 1
    assert proof["prepared_main_failure"] == original["prepared_main_failure"]
    assert proof[state.failure_key]["inherited_preparation"] == original
    assert state.consume()["source_effect_count"] == 0


@pytest.fixture
def first_isolation(monkeypatch):
    from novel_forge.modules.story_planning_runtime import preparation_recovery as recovery
    from novel_forge.modules.story_planning_runtime import fresh_preparation_custody as fresh
    frozen = dict(project_id='project', workspace_id='workspace', book_id='book', actor_id='author',
        trace_id='trace', correlation_id='correlation', execution_contract_version='1.21.0',
        arc_working_set=dict(working_manuscript=dict(book_run_id='run', target_chapter=20, accepted_through_chapter=0, snapshot_hash='working')))
    command = deepcopy(frozen)
    operation = dict(operation_id='original', command_payload=dict(payload=command), actor_id='author', workspace_id='workspace',
        project_id='project', definition_version='1.21.0', status='FAILED_FINAL', version=4)
    generation = dict(book_id='book', generator_operation_name='chapter_plan.generate', input_snapshot=[], candidate_asset_version_id=None)
    isolation = dict(contract_version='pure-generation-isolation.v1', operation_id='original', project_id='project',
        book_id='book', actor_id='author', business_commit_right='REVOKED', activation_right='REVOKED')
    boundary = dict(kind='FROZEN_STAGE_INPUTS', project_id='project', book_id='book', pack_snapshot_hash='snapshot-hash',
        sources=[dict(asset_version_id='context', content_hash='context-hash')])
    capture = {'original': 'complete source'}
    task = dict(frozen_input_boundary=boundary, task=dict(source_projection_hash=canonical_hash(capture)))
    def effect(identity, status):
        payload = dict(stage='context_compress', input=dict(context_compression_task=deepcopy(task)))
        return dict(external_effect_id=identity, operation_id='original', project_id='project', effect_type='model.invoke', status=status,
            request_payload=payload, request_hash=canonical_hash(payload))
    snapshot = dict(context_policy_ref='context-policy:chapter-generation-pack:v4', context_policy_payload_json='{"planning_task_token_budget":512000}')
    state = SimpleNamespace(members={'original': (operation, generation, isolation)}, parents={},
        effects={'original': [(effect('success', 'SUCCEEDED'), 'SETTLED', False), (effect('unknown', 'UNKNOWN'), 'HELD_UNKNOWN', True)]},
        attempts={'original': [('attempt', 'CANCELLED', {})]}, cancellations={}, acknowledged=True, held=False,
        book=(19, 0, 'input-snapshot', 'PAUSED', None), cancelled_book=False, snapshot=snapshot,
        frozen=frozen, context=SimpleNamespace(asset_version_id='context', content_hash='context-hash', content=dict(arc_working_set=frozen['arc_working_set'], input_versions=[])))
    uow = MagicMock()
    def execute(sql, args):
        assert sql.count('%s') == len(args)
    def one():
        sql, args = uow.cursor.execute.call_args.args
        if 'to_jsonb(op),to_jsonb(generation)' in sql:
            return state.members.get(args[0])
        if 'to_jsonb(link)' in sql:
            return (state.parents[args[0]],) if args[0] in state.parents else None
        if 'SELECT root_operation_id' in sql:
            return ('root',)
        if 'SELECT current_chapter' in sql:
            return state.book
        if 'authority_lease_acquisition' in sql:
            return (state.held,)
        if 'status=\'ACKNOWLEDGED\'' in sql:
            return (state.acknowledged,)
        if 'SELECT EXISTS' in sql:
            return (state.cancelled_book,)
        raise AssertionError(sql)
    def many():
        sql, args = uow.cursor.execute.call_args.args
        if 'snapshot_payload,snapshot_id' in sql:
            return [(state.snapshot, 'snapshot', 'snapshot-hash', 'attempt')]
        if 'planning.context_bundle' in sql:
            return [('context', 'context-hash')]
        if 'FROM authority_attempt' in sql:
            return state.attempts[args[0]]
        if 'SELECT actor_id' in sql:
            return state.cancellations.get(args[0], [])
        if 'to_jsonb(effect)' in sql:
            return state.effects[args[0]]
        raise AssertionError(sql)
    uow.cursor.execute.side_effect = execute
    uow.cursor.fetchone.side_effect = one
    uow.cursor.fetchall.side_effect = many
    uow.repositories.asset_documents.require.side_effect = lambda **_: state.context
    monkeypatch.setattr('novel_forge.modules.book_authority.manuscript.historical_working_inputs', lambda *_: ('book', []))
    monkeypatch.setattr('novel_forge.modules.chapter_group_authority.replan_retirement.lock_replan_roots', lambda *_a, **_k: None)
    monkeypatch.setattr(recovery, 'reconstruct_preparation_capture', lambda *_: capture)
    state.read = MagicMock(return_value=dict(budget_reservation_status='SETTLED', provider_evidence=dict(result={'selected_unit_ids': ['text:0']}, production_execution=dict(route_snapshot=dict(model_id='model', model_provider='codex-cli', backend_id='backend', reasoning_effort='medium', auth_profile_ref='auth')))))
    for name in ('read_retained_generation_stage_success_in_uow', 'read_acknowledged_preparation_success_in_uow'):
        monkeypatch.setattr('novel_forge.modules.command_kernel.external_effect_runtime.'+name, state.read)
    monkeypatch.setattr('novel_forge.modules.chapter_authority.receipt_recovery.retained_capacity_bindings_in_uow',
        lambda *_a, **_k: {'chapter_plan.generate': {'route': dict(provider='codex-cli', model='model', backend='backend', reasoning='medium')}})
    state.consume = lambda source='original': fresh.require_source(uow, source_operation_id=source, frozen=state.frozen)
    return state


def test_fresh_isolation_retains_verified_preparation_without_fabricating_a_terminal_anchor(first_isolation):
    s = first_isolation
    before = deepcopy(s.effects)
    source = s.consume()
    assert source['mode'] == 'FIRST_ISOLATED_PREPARATION_CUSTODY'
    proof = source['fresh_preparation']
    assert [(r['operation_id'], r['external_effect_id']) for r in proof['retained_preparation']] == [('original', 'success')]
    assert proof['source_operation_id'] == 'original'
    assert 'host_failure' not in proof
    assert s.effects == before
    assert s.read.call_count == 1


@pytest.mark.parametrize('damage', ['actor', 'book', 'frontier', 'accepted', 'active_chapter', 'lease', 'live_rights',
    'unisolated_unknown', 'unsettled', 'request_hash', 'context_hash', 'boundary', 'projection', 'main_send', 'candidate', 'book_cancel'])
def test_first_isolation_custody_rejects_foreign_stale_unsettled_or_live_sources(first_isolation, damage):
    s = first_isolation
    op, gen, iso = s.members['original']
    success = s.effects['original'][0][0]
    if damage == 'actor':
        op['actor_id'] = 'other'
    elif damage == 'book':
        gen['book_id'] = 'foreign'
    elif damage in {'frontier', 'accepted', 'active_chapter'}:
        book = list(s.book)
        book[{'frontier': 0, 'accepted': 1, 'active_chapter': 4}[damage]] = 1
        s.book = tuple(book)
    elif damage == 'lease':
        s.held = True
    elif damage == 'live_rights':
        iso['activation_right'] = 'GRANTED'
    elif damage == 'unisolated_unknown':
        e, b, _ = s.effects['original'][1]
        s.effects['original'][1] = (e, b, False)
    elif damage == 'unsettled':
        s.effects['original'][0] = (success, 'RESERVED', False)
    elif damage == 'request_hash':
        success['request_hash'] = 'wrong'
    elif damage == 'context_hash':
        s.context.content_hash = 'wrong'
    elif damage in {'boundary', 'projection'}:
        task = success['request_payload']['input']['context_compression_task']
        if damage == 'boundary':
            task['frozen_input_boundary']['book_id'] = 'foreign'
        else:
            task['task']['source_projection_hash'] = 'wrong'
        success['request_hash'] = canonical_hash(success['request_payload'])
    elif damage == 'main_send':
        success['request_payload']['stage'] = 'chapter_plan.generate'
        success['request_hash'] = canonical_hash(success['request_payload'])
    elif damage == 'candidate':
        gen['candidate_asset_version_id'] = 'already-produced'
    else:
        s.cancelled_book = True
    with pytest.raises(KernelError, match='PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE'):
        s.consume()


@pytest.mark.parametrize('stop', ['acknowledged', 'isolated', 'query', 'lineage', 'routing-link'])
def test_first_custody_continues_through_stopped_children_without_reassigning_old_receipts(first_isolation, stop):
    s = first_isolation
    original, generation, isolation = s.members['original']
    child = deepcopy(original)
    child.update(operation_id='child', status='RECONCILIATION_REQUIRED' if stop == 'acknowledged' else 'FAILED_FINAL')
    child['command_payload']['payload']['runtime_continuation_id'] = 'first-link'
    s.parents['child'] = dict(continuation_id='first-link', source_operation_id='original', successor_command=child['command_payload']['payload'],
        source_command=deepcopy(s.frozen), target_runtime={}, chain_depth=1)
    child_isolation = None
    if stop == 'isolated':
        child_isolation = {**isolation, 'operation_id': 'child'}
    s.members['child'] = child, deepcopy(generation), child_isolation
    s.effects['child'] = []
    if stop == 'acknowledged':
        s.attempts['child'] = [('child-attempt', 'CANCELLED', {})]
        s.cancellations['child'] = [('author',)]
    elif stop == 'isolated':
        s.attempts['child'] = [('child-attempt', 'CANCELLED', {})]
    else:
        failure = dict(error_code='PROGRAMMING_BUG' if stop == 'query' else 'PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED',
            error_message='canceling statement due to statement timeout' if stop == 'query' else 'PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth')
        if stop == 'routing-link':
            from novel_forge.modules.story_planning_runtime.fresh_preparation_custody import LINEAGE_LINK_FAILURE
            failure = deepcopy(LINEAGE_LINK_FAILURE)
        s.attempts['child'] = [('child-attempt', 'FAILED_FINAL', failure)]
    source = s.consume('child')
    assert source['depth'] == 2
    proof = source['fresh_preparation']
    assert proof['source_operation_id'] == 'original' and proof['custody_source_operation_id'] == 'child'
    assert [r['external_effect_id'] for r in proof['retained_preparation']] == ['success']
    assert len(proof['stopped_ancestry']) == 2


@pytest.mark.parametrize('drift', [None, 'model_id', 'model_provider', 'model_backend_id', 'reasoning_effort', 'auth_profile_ref', 'context_policy_hash'])
def test_first_custody_allows_a_new_physical_build_but_keeps_frozen_semantics_and_route(first_isolation, drift):
    from novel_forge.modules.story_planning_runtime.fresh_preparation_custody import target_runtime
    source = first_isolation.consume()
    original = source['fresh_preparation']['original_pack_snapshot']
    original.update(compilation_hash='old-physical-compilation', release_sha='old')
    target = dict(pack_snapshot={**original, 'compilation_hash': 'new-physical-compilation', 'release_sha': 'new'},
        model_provider='codex-cli', model_id='model', model_backend_id='backend', reasoning_effort='medium', auth_profile_ref='auth')
    if drift:
        if drift == 'context_policy_hash':
            target['pack_snapshot'][drift] = 'changed'
        else:
            target[drift] = 'changed'
        with pytest.raises(KernelError, match='PLANNING_PREPARATION_REUSE_DRIFT'):
            target_runtime(None, source, target)
    else:
        result = target_runtime(None, source, target)
        assert result['pack_snapshot']['compilation_hash'] == 'new-physical-compilation'
        assert result['preparation_handoff']['original_pack_snapshot']['compilation_hash'] == 'old-physical-compilation'
        assert result['planning_capacity']['allocated_task_tokens'] == 512000


def test_fresh_reader_defers_historical_contract_changes_to_their_existing_owner(first_isolation):
    s = first_isolation
    s.members['original'][0]['definition_version'] = '1.19.0'
    s.members['original'][0]['command_payload']['payload']['execution_contract_version'] = '1.19.0'
    assert s.consume() is None


def test_first_custody_uses_the_frozen_main_stage_route_instead_of_compressor_reasoning(first_isolation, monkeypatch):
    from novel_forge.modules.story_planning_runtime.fresh_preparation_custody import target_runtime
    monkeypatch.setattr('novel_forge.modules.chapter_authority.receipt_recovery.retained_capacity_bindings_in_uow',
        lambda *_a, **_k: {'chapter_plan.generate': {'route': dict(provider='codex-cli', model='model', backend='backend', reasoning='high')}})
    source = first_isolation.consume()
    assert source['fresh_preparation']['original_route']['reasoning_effort'] == 'high'
    assert first_isolation.read.return_value['provider_evidence']['production_execution']['route_snapshot']['reasoning_effort'] == 'medium'
    target = dict(pack_snapshot=deepcopy(source['snapshot']), model_provider='codex-cli', model_id='model', model_backend_id='backend',
        reasoning_effort='high', auth_profile_ref='auth')
    assert target_runtime(None, source, target)['preparation_handoff']['original_capacity_bindings']['chapter_plan.generate']['route']['reasoning'] == 'high'
    with pytest.raises(KernelError, match='PLANNING_PREPARATION_REUSE_DRIFT'):
        target_runtime(None, source, {**target, 'reasoning_effort': 'medium'})


@pytest.fixture
def first_native_route(first_isolation):
    from novel_forge.modules.production_execution.codex_configuration import codex_local_binding_hash
    account = dict(codex_home='/original/account', executable='/original/codex',
        entitlement=dict(authorization_ref='original-native-authority'), retry_policy='', input_only_policy='')
    reference = 'original:codex:' + codex_local_binding_hash(**account)
    first_isolation.read.return_value['provider_evidence']['production_execution']['route_snapshot']['auth_profile_ref'] = reference
    source = first_isolation.consume()
    target = dict(pack_snapshot=deepcopy(source['snapshot']), model_provider='codex-cli', model_id='model',
        model_backend_id='backend', reasoning_effort='medium', auth_profile_ref=reference,
        cost_accounting_basis='ACCOUNT_ENTITLEMENT', account=account)
    return source, target


def test_first_custody_authorizes_the_original_native_receipt_without_legacy_book_policy(first_native_route, monkeypatch):
    from novel_forge.modules.story_planning_runtime import fresh_preparation_custody as fresh
    from novel_forge.modules.story_planning_runtime import runtime_continuation as continuation
    source, target = first_native_route
    capacity = MagicMock(return_value={'authorization_ref': 'original-native-authority'})
    monkeypatch.setattr(continuation, '_capacity_authorization', capacity)
    uow = MagicMock()
    uow.cursor.fetchone.return_value = None
    result = fresh.authorization(uow, source=source, successor=SimpleNamespace(repair_number=0),
        principal=SimpleNamespace(principal_id='author'), target=target)
    assert result['route_authorization']['account_evidence_source'] == 'VERIFIED_PREPARATION_AND_MAIN_ROUTE'
    assert result['route_authorization']['source_auth_profile_ref'] == target['auth_profile_ref']
    assert result['retained_preparation_count'] == 1
    assert result['preserved_repair_number'] == 0
    capacity.assert_called_once()
    uow.cursor.execute.assert_not_called()


@pytest.mark.parametrize('damage', ['auth_profile_ref', 'codex_home', 'executable', 'entitlement', 'retry_policy',
    'input_only_policy', 'empty_account', 'cost_accounting_basis', 'model_id', 'model_provider', 'model_backend_id',
    'reasoning_effort', 'pack', 'missing_original_auth', 'main_send', 'unisolated', 'live_rights', 'foreign_owner', 'empty_receipts'])
def test_first_native_route_rejects_changed_identity_custody_and_capacity(first_native_route, damage):
    from novel_forge.modules.story_planning_runtime.fresh_preparation_custody import _first_route_authorization
    source, target = first_native_route
    proof = source['fresh_preparation']
    if damage in {'auth_profile_ref', 'cost_accounting_basis', 'model_id', 'model_provider', 'model_backend_id', 'reasoning_effort'}:
        target[damage] = 'different'
    elif damage in {'codex_home', 'executable', 'retry_policy', 'input_only_policy'}:
        target['account'][damage] = 'different'
    elif damage == 'entitlement':
        target['account']['entitlement']['authorization_ref'] = 'different'
    elif damage == 'empty_account':
        target['account'] = {}
    elif damage == 'pack':
        target['pack_snapshot']['context_policy_hash'] = 'different'
    elif damage == 'missing_original_auth':
        proof['original_route'].pop('auth_profile_ref')
    elif damage == 'main_send':
        proof['main_dispatch_count'] = 1
    elif damage == 'unisolated':
        proof['stopped_ancestry'][0]['kind'] = 'ACTIVE'
    elif damage == 'live_rights':
        proof['source_submission_rights'] = 'ACTIVE'
    elif damage == 'foreign_owner':
        proof['source_operation_id'] = 'other'
    else:
        proof['retained_preparation'] = []
    with pytest.raises(KernelError, match='PLANNING_(RUNTIME_CONTINUATION_ACCOUNT|PREPARATION_REUSE)_DRIFT'):
        _first_route_authorization(source, target)


def test_first_custody_existing_successor_keeps_registered_account_validation(first_native_route, monkeypatch):
    from novel_forge.modules.story_planning_runtime import fresh_preparation_custody as fresh
    from novel_forge.modules.story_planning_runtime import runtime_continuation as continuation
    source, target = first_native_route
    source['command']['runtime_continuation_id'] = 'registered-parent'
    capacity = MagicMock(return_value={'authorization_ref': 'original-native-authority'})
    route = MagicMock(return_value={'account_evidence_source': 'PRIOR_REGISTERED_RUNTIME'})
    monkeypatch.setattr(continuation, '_capacity_authorization', capacity)
    monkeypatch.setattr(continuation, 'require_route_evidence', route)
    result = fresh.authorization(MagicMock(), source=source, successor=SimpleNamespace(repair_number=3),
        principal=SimpleNamespace(principal_id='author'), target=target)
    assert result['route_authorization']['account_evidence_source'] == 'PRIOR_REGISTERED_RUNTIME'
    assert result['preserved_repair_number'] == 3
    route.assert_called_once()
    capacity.assert_called_once()


@pytest.fixture
def settled_capacity_child(first_isolation, monkeypatch):
    s = first_isolation
    original, generation, _ = s.members['original']
    child = deepcopy(original)
    child.update(operation_id='child', status='FAILED_RETRYABLE')
    child['command_payload']['payload']['runtime_continuation_id'] = 'first-link'
    s.parents['child'] = dict(continuation_id='first-link', source_operation_id='original',
        successor_command=child['command_payload']['payload'], source_command=deepcopy(s.frozen), target_runtime={}, chain_depth=1)
    s.members['child'] = child, deepcopy(generation), None
    effect = deepcopy(s.effects['original'][0][0])
    effect.update(external_effect_id='child-success', operation_id='child')
    s.effects['child'] = [(effect, 'SETTLED', False)]
    task = effect['request_payload']['input']['context_compression_task']
    projection = dict(contract_version='complete-request-capacity.v1', semantic_contract='source-unit-dependency-and-final-composition.v2',
        original_hash=task['task']['source_projection_hash'], result_hash=task['task']['source_projection_hash'],
        source_boundary=deepcopy(task['frozen_input_boundary']), stage='chapter_plan.generate',
        compression_receipt=dict(fast_path=True), measurement=dict(before_reserved=5000, after_reserved=5001, limit=4000,
            token_method='CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1', actual_provider_tokens=None))
    failure = dict(error_code='TASK_CONTEXT_COMPRESSION_NO_PROGRESS', failure_class='retryable',
        error_message='TASK_CONTEXT_COMPRESSION_NO_PROGRESS: All remaining source expression is required or already verified; the complete request still exceeds capacity',
        failure_details=dict(projection=projection))
    s.attempts['child'] = [('child-attempt', 'FAILED_RETRYABLE', failure)]
    monkeypatch.setattr('novel_forge.modules.chapter_authority.receipt_recovery.retained_capacity_bindings_in_uow',
        lambda *_a, **_k: {'chapter_plan.generate': {'route': dict(provider='codex-cli', model='model', backend='backend', reasoning='medium',
            context_limit=4000, method='CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1')}})
    s.capacity, s.capacity_failure = projection, failure
    return s


@pytest.mark.parametrize('damage', [None, 'projection', 'result', 'boundary', 'stage', 'method', 'limit', 'not_overflow',
    'fast_path', 'failure', 'main_send', 'world_send', 'unsettled', 'unknown', 'lease', 'cancel', 'actor', 'frontier'])
def test_settled_capacity_handoff_preserves_preparation_and_rejects_changed_or_live_sources(settled_capacity_child, damage):
    s = settled_capacity_child
    effect, _, _ = s.effects['child'][0]
    if damage in {'projection', 'result'}:
        s.capacity['original_hash' if damage == 'projection' else 'result_hash'] = 'changed'
    elif damage == 'boundary':
        s.capacity['source_boundary']['book_id'] = 'foreign'
    elif damage == 'stage':
        s.capacity['stage'] = 'draft'
    elif damage in {'method', 'limit', 'not_overflow'}:
        s.capacity['measurement'][{'method': 'token_method', 'limit': 'limit', 'not_overflow': 'after_reserved'}[damage]] = 'other' if damage == 'method' else 3000
    elif damage == 'fast_path':
        s.capacity['compression_receipt']['fast_path'] = False
    elif damage == 'failure':
        s.capacity_failure['failure_class'] = 'programming_bug'
    elif damage in {'main_send', 'world_send'}:
        effect['request_payload']['stage'] = 'chapter_plan.generate' if damage == 'main_send' else 'world_candidates.generate'
        effect['request_hash'] = canonical_hash(effect['request_payload'])
    elif damage == 'unsettled':
        s.effects['child'][0] = effect, 'RESERVED', False
    elif damage == 'unknown':
        effect['status'] = 'UNKNOWN'
    elif damage == 'lease':
        s.held = True
    elif damage == 'cancel':
        s.cancellations['child'] = [('author',)]
    elif damage == 'actor':
        s.members['child'][0]['actor_id'] = 'foreign'
    elif damage == 'frontier':
        s.book = (20, *s.book[1:])
    if damage:
        with pytest.raises(KernelError, match='PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE'):
            s.consume('child')
        return
    before = deepcopy(s.effects)
    source = s.consume('child')
    proof = source['fresh_preparation']
    assert proof['contract_version'] == 'planning-first-isolated-preparation-handoff.v3'
    assert source['source_operation_status'] == 'FAILED_RETRYABLE'
    assert proof['main_dispatch_count'] == 0
    assert [item['external_effect_id'] for item in proof['retained_preparation']] == ['success', 'child-success']
    assert proof['stopped_ancestry'][-1]['kind'] == 'UNSENT_CAPACITY_FAILURE'
    assert proof['stopped_ancestry'][-1]['failure_hash'] == canonical_hash(s.capacity_failure)
    assert s.effects == before


@pytest.mark.parametrize('damage', ['', 'unacknowledged', 'lease', 'unknown', 'main-send', 'foreign-cancellation'])
def test_first_acknowledged_preparation_keeps_native_receipts_without_inventing_isolation(first_isolation, damage):
    s = first_isolation
    op, generation, _ = s.members['original']
    op['status'] = 'RECONCILIATION_REQUIRED'
    s.members['original'] = (op, generation, None)
    s.cancellations['original'] = [('author',)]
    s.effects['original'] = s.effects['original'][:1]
    if damage == 'unacknowledged':
        s.acknowledged = False
    elif damage == 'lease':
        s.held = True
    elif damage == 'unknown':
        effect = deepcopy(s.effects['original'][0][0])
        effect['status'] = 'UNKNOWN'
        s.effects['original'].append((effect, 'HELD_UNKNOWN', False))
    elif damage == 'main-send':
        effect = s.effects['original'][0][0]
        effect['request_payload']['stage'] = 'chapter_plan.generate'
        effect['request_hash'] = canonical_hash(effect['request_payload'])
    elif damage == 'foreign-cancellation':
        s.cancellations['original'] = [('other',)]
    before = deepcopy(s.effects)
    if damage:
        with pytest.raises(KernelError, match='PLANNING_FIRST_PREPARATION_CUSTODY_UNSAFE'):
            s.consume()
    else:
        source = s.consume()
        assert source['mode'] == 'ACKNOWLEDGED_PREPARATION_CUSTODY'
        proof = source['fresh_preparation']
        assert proof['contract_version'] == 'planning-acknowledged-preparation-handoff.v1'
        assert proof['isolated_generation_count'] == 0
        assert proof['retained_preparation'][0]['receipt_contract'] == 'ACKNOWLEDGED_PREPARATION'
    assert s.effects == before
