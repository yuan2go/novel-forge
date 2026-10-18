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
