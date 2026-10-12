from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.generation_isolation import partition_generation_effects
from novel_forge.modules.command_kernel.manual_effect_resolution import ExternalEffectManualResolutionCommand, _same_isolation_replay
from novel_forge.modules.chapter_authority.provider_views import compile_exact_context_references, expand_exact_context_references
from novel_forge.modules.chapter_authority.author_editor import author_input_provenance


def test_completed_only_validation_port_never_dispatches_changed_or_missing_input():
    from novel_forge.modules.chapter_authority.receipt_recovery import _CompletedOnlyPort
    expected = {"draft": {"text": "真实原始正文"}}
    result = object()
    port = _CompletedOnlyPort([({"stage": "review", "input": expected}, result)])
    assert port.invoke(None, stage="review", payload=expected) is result
    for stage, payload in (("revision", expected), ("review", {"draft": {"text": "改过的输入"}})):
        with pytest.raises(KernelError, match="KNOWN_RECEIPT_INPUT_DRIFT"):
            port.invoke(None, stage=stage, payload=payload)


@pytest.mark.parametrize('fault', [None, 'changed-input', 'foreign-book', 'unverified'])
def test_retry_reuses_exact_verified_result_without_new_dispatch_or_settlement(monkeypatch, fault):
    from contextlib import nullcontext
    from novel_forge.modules.chapter_authority import receipt_recovery, model_effects
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
    payload = {'draft': {'text': '完整真实输入'}}
    cursor = Mock()
    original = {'input': {'changed': True} if fault == 'changed-input' else payload,
        '_production_execution': {'book_id': 'other' if fault == 'foreign-book' else 'book'}}
    cursor.fetchone.side_effect = [('effect', 'request-hash', original, 'actor', 'trace', 'correlation'), None]
    uow = SimpleNamespace(cursor=cursor, repositories=SimpleNamespace(external_effects=Mock()))
    monkeypatch.setattr(receipt_recovery, 'AuthorityUnitOfWork', lambda *args: nullcontext(uow))
    evidence = {'result': {'edits': [], 'resolved_issue_codes': []}, 'provider_id': 'fixture', 'model_id': 'fixture',
        'prompt_version': 'fixture', 'skill_version': 'fixture', 'real_model_call': False,
        'usage': {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN'},
        'cost': {'availability': 'UNAVAILABLE', 'measurement': 'UNKNOWN', 'currency': 'UNKNOWN'}}
    verified = Mock(return_value=None if fault == 'unverified' else {'provider_evidence': evidence, 'budget_reservation_status': 'HELD_UNKNOWN'})
    monkeypatch.setattr(receipt_recovery, '_read_verified_success', verified)
    request = ChapterHandlerRequest('op', 'p', 'w', 'trace', 'root', {'book_id': 'book'}, (),
        attempt_id='new-attempt', database_url='fixture-only')
    if fault in {'foreign-book', 'unverified'}:
        with pytest.raises(KernelError, match='KNOWN_RECEIPT_'):
            receipt_recovery.consume_completed_generation_result(request, stage='revision', payload=payload)
        return
    if fault == 'changed-input':
        assert receipt_recovery.consume_completed_generation_result(request, stage='revision', payload=payload) is None
        verified.assert_not_called()
        return
    adapter = SimpleNamespace(cost_accounting_basis='ACCOUNT_ENTITLEMENT', account_authorization_ref='fixture-grant', invoke=Mock())
    port = model_effects.ExternalEffectChapterModelPort('fixture-only', adapter=adapter, worker_id='worker')
    result = port.invoke(request, stage='revision', payload=payload)
    adapter.invoke.assert_not_called()
    assert result.output == evidence['result']
    assert result.to_evidence()['cost'] == evidence['cost']
    assert result.to_evidence()['usage'] == evidence['usage']
    assert result.execution_evidence['completed_attempt_reuse']['accounting_status'] == 'HELD_UNKNOWN'
    from novel_forge.modules.chapter_authority.handlers import _model_output
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    output = _model_output(ChapterNode.REVISION, {'text': '原文'}, request=request, generated=result)
    assert output.content['retained_generation_revalidation']['provider_invoked'] is False
    assert all(a.asset_type != 'execution_commit_manifest' for a in output.auxiliary_outputs)


def test_multi_model_node_keeps_completed_compression_and_isolates_only_interrupted_fidelity():
    complete = {'external_effect_id': 'compress', 'effect_type': 'model.invoke', 'status': 'SUCCEEDED'}
    interrupted = {'external_effect_id': 'fidelity', 'effect_type': 'model.invoke', 'status': 'UNKNOWN'}
    assert partition_generation_effects([complete, interrupted]) == ([interrupted], [complete])
    with pytest.raises(KernelError, match='GENERATION_ISOLATION_EFFECT_BOUNDARY_UNSAFE'):
        partition_generation_effects([interrupted, {'effect_type': 'payment', 'status': 'UNKNOWN'}])
    with pytest.raises(KernelError, match='GENERATION_ISOLATION_RESULT_RECOVERABLE'):
        partition_generation_effects([complete])


def test_completed_sibling_cannot_create_new_attempt_commit_manifest():
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterNode
    from novel_forge.modules.chapter_authority.handlers import _model_output
    from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
    proof = {'source_effect_id': 'old-effect', 'provider_invoked': False}
    generated = ModelProviderResult({'text': '完整正文'}, 'fixture', 'fixture', 'fixture', 'fixture', 0, 0, '0', 'UNKNOWN', False,
        execution_evidence={'completed_sibling_reuse': proof, 'validation_manifest_ref': 'original-validation'})
    request = ChapterHandlerRequest('new-op', 'p', 'w', 'trace', 'root', {}, (), attempt_id='new-attempt', fencing_token=2)
    output = _model_output(ChapterNode.REVISION, {'text': '完整正文'}, request=request, generated=generated)
    assert output.content['retained_generation_revalidation'] == proof
    assert not any(item.asset_type == 'execution_commit_manifest' for item in output.auxiliary_outputs)
    from novel_forge.modules.chapter_authority.handlers import _execution_commit_auxiliary
    assert _execution_commit_auxiliary(ChapterNode.REVISION, request, generated) is None


@pytest.mark.parametrize('status', ['FAILED_FINAL','FAILED_RETRYABLE','DEAD_LETTER','SUCCEEDED','EXECUTING','CANCELLED'])
def test_completed_generation_stage_reads_stopped_original_owner_and_preserves_unknown_usage(monkeypatch,status):
    from contextlib import nullcontext
    from novel_forge.modules.command_kernel import external_effect_runtime as runtime
    cursor=Mock()
    cursor.fetchone.return_value=(status,)
    uow=SimpleNamespace(cursor=cursor,repositories=SimpleNamespace(external_effects=Mock()))
    monkeypatch.setattr(runtime,'AuthorityUnitOfWork',lambda *args:nullcontext(uow))
    receipt={'budget_reservation_status':'HELD_UNKNOWN','provider_evidence':{'result':{'text':'完整结果'},'usage':{'availability':'UNAVAILABLE'}}}
    read=Mock(return_value=receipt)
    monkeypatch.setattr(runtime,'_read_verified_success',read)
    context=runtime.EffectCommandContext('op','p','actor','trace','root')
    if status in {'EXECUTING','CANCELLED'}:
        with pytest.raises(KernelError,match='EFFECT_RETAINED_RESULT_OWNER_INVALID'):
            runtime.read_retained_generation_stage_success('fixture-only',context,effect_id='effect')
        read.assert_not_called()
    else:
        assert runtime.read_retained_generation_stage_success('fixture-only',context,effect_id='effect') is receipt
        assert read.call_args.kwargs['retained_generation_stage'] is True
        assert receipt['budget_reservation_status']=='HELD_UNKNOWN'


def test_isolation_replay_ignores_only_cas_observation_and_keeps_all_semantic_fields():
    command = ExternalEffectManualResolutionCommand('effect', 'operation', 'project', 'actor',
        'ISOLATE_PURE_GENERATION', 'reason', {'authorization_ref': 'grant'}, 'key', 99, 'trace', 'correlation')
    cursor = Mock()
    cursor.fetchone.return_value = ('operation', 'actor', 'ISOLATE_PURE_GENERATION', 'reason',
        {'authorization_ref': 'grant'}, 'trace', 'correlation')
    assert _same_isolation_replay(cursor, command)
    cursor.fetchone.return_value = ('operation', 'other-actor', 'ISOLATE_PURE_GENERATION', 'reason',
        {'authorization_ref': 'grant'}, 'trace', 'correlation')
    assert not _same_isolation_replay(cursor, command)


def test_lossless_context_references_keep_all_constraints_failed_findings_and_unicode():
    constraint = {'must': '沈砚保留选择。' * 100, 'facts': ['许庭', '程观'], 'status': 'UNKNOWN'}
    view = {'a/~': constraint, 'window': [constraint, {'failed_finding': constraint}], 'none': None}
    encoded, proof = compile_exact_context_references(view)
    assert proof['reference_count'] == 2 and proof['decoded_equal']
    assert expand_exact_context_references(encoded) == view
    assert encoded['window'][0] == {'__exact_value_ref__': '/a~1~0'}


@pytest.mark.parametrize('encoded', [
    {'before': {'__exact_value_ref__': '/after'}, 'after': 'value'},
    {'__exact_value_ref__': ''}, {'x': {'__exact_value_ref__': 'https://remote/result'}},
    {'a': 'x', 'b': {'__exact_value_ref__': '/a', 'extra': True}},
])
def test_context_reference_cannot_introduce_external_forward_or_cyclic_data(encoded):
    with pytest.raises(KernelError, match='PROVIDER_EXACT_REFERENCE_INVALID'):
        expand_exact_context_references(encoded)


def test_assistant_revision_candidate_does_not_claim_human_choice_or_acceptance():
    base = SimpleNamespace(asset_version_id='draft-v1', content_hash='sha256:original')
    provenance = {key: 'recorded' for key in ('authorization_ref', 'provider_id', 'model_id',
        'prompt_version', 'skill_version', 'usage_status', 'trace_id')}
    payload = {'input_origin': 'ASSISTANT_REVISION_PROPOSAL', 'rights_basis': 'AUTHORIZED_INPUT',
        'revision_provenance': provenance}
    saved = author_input_provenance(payload, operation_id='save-op', base=base)
    assert saved['kind'] == 'ASSISTANT_REVISION_PROPOSAL'
    assert saved['author_decision'] == saved['formal_acceptance'] == 'NOT_RECORDED'
    assert saved['base_content_hash'] == base.content_hash
    with pytest.raises(KernelError, match='AUTHOR_INPUT_PROVENANCE_INVALID'):
        author_input_provenance({**payload, 'rights_basis': 'ORIGINAL_AUTHOR_INPUT'}, operation_id='save-op', base=base)


def test_shared_review_port_accepts_authority_request_without_chapter_database_field(monkeypatch):
    from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest
    from novel_forge.modules.chapter_authority import model_effects

    request = AuthorityHandlerRequest('operation', 'project', 'workspace', 'actor',
        'trace', 'correlation', 'longform.prose_review', '1.0.0', {'payload': {}}, ())
    adapter = SimpleNamespace(cost_accounting_basis='PRICED')
    port = model_effects.ExternalEffectChapterModelPort('postgresql://not-connected',
        adapter=adapter, worker_id='worker')
    reached_intent = Mock(side_effect=KernelError('TEST_INTENT_BOUNDARY', 'normal review intent'))
    monkeypatch.setattr(model_effects, 'read_external_effect_intent', reached_intent)
    with pytest.raises(KernelError, match='TEST_INTENT_BOUNDARY'):
        port.invoke(request, stage='longform_prose_review', payload={})
    reached_intent.assert_called_once()


@pytest.mark.parametrize('boundary', [(True,False,False,True),(False,True,False,True),(False,False,True,True),(False,False,False,False)])
def test_unsent_transport_correction_rejects_sent_paid_or_unrelated_failure(boundary):
    from novel_forge.modules.command_kernel.context_transport_recovery import CONTRACT, require_unsent_context_transport
    cursor = Mock()
    cursor.fetchone.return_value = boundary
    source = {'operation_id':'op','definition_name':'chapter.draft.generate','definition_version':'3.10.0'}
    with pytest.raises(KernelError, match='CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE'):
        require_unsent_context_transport(cursor, source, {'contract_version':CONTRACT})


def test_unsent_transport_correction_cannot_mask_authorization_or_paid_budget_failure():
    from novel_forge.modules.command_kernel.context_transport_recovery import CONTRACT, require_unsent_context_transport
    cursor = Mock()
    cursor.fetchone.return_value = (False,False,False,True)
    cursor.fetchall.return_value = [({'status':'BLOCKED','candidates':[{'rejected_reasons':['AUTHORIZATION_MISSING','BUDGET_HARD_LIMIT']}]},)]
    source = {'operation_id':'op','definition_name':'chapter.draft.generate','definition_version':'3.10.0'}
    with pytest.raises(KernelError, match='CHAPTER_UNSENT_TRANSPORT_ROUTE_UNPROVEN'):
        require_unsent_context_transport(cursor, source, {'contract_version':CONTRACT})


def test_context_references_remain_backward_after_canonical_json_serialization():
    import json
    repeated = {"constraint": "retain the approved plan " * 100}
    source = {"z_task": repeated, "a_context": {"copy": repeated}}
    encoded, proof = compile_exact_context_references(source)
    assert proof["reference_count"] == 1
    assert expand_exact_context_references(json.loads(json.dumps(encoded,sort_keys=True))) == source
    assert encoded["z_task"] == {"__exact_value_ref__": "/a_context/copy"}


def test_route_diagnostics_distinguish_unsent_capacity_from_permission_failure():
    from novel_forge.modules.production_execution.routing_runtime import routing_failure_details
    route = {'decision_id':'route','task':{'operation_id':'op','attempt_id':'attempt','task_type':'draft'},
        'candidates':[{'candidate':{'candidate_id':'model'},'rejected_reasons':['CONTEXT_CAPACITY_EXCEEDED','BUDGET_HARD_LIMIT']}]}
    result = routing_failure_details(route)
    assert result['cause'] == 'CONTEXT_CAPACITY_EXCEEDED'
    assert result['stage'] == 'PROVIDER_ROUTE_ADMISSION' and result['recovery_state'] == 'NOT_SENT'
    assert result['execution_identity']['operation_id'] == 'op' and result['provider_invoked'] is False
    route['candidates'][0]['rejected_reasons'] = ['AUTHORIZATION_MISSING']
    assert routing_failure_details(route)['cause'] == 'ROUTE_CANDIDATES_REJECTED'


def test_current_prose_review_context_budget_is_not_an_output_budget():
    from novel_forge.modules.chapter_authority.model_effects import task_scoped_prose_review
    window = SimpleNamespace(asset_type='longform_prose_review_window',content={'schema_version':'longform-prose-window.v3'})
    request = SimpleNamespace(inputs=(window,))
    assert task_scoped_prose_review(request,'longform_prose_review')
    assert not task_scoped_prose_review(request,'draft')
    window.content['schema_version']='longform-prose-window.v1'
    assert not task_scoped_prose_review(request,'longform_prose_review')


def test_planning_envelope_references_deduplicate_task_and_context_without_losing_repair():
    content = {'characters': ['沈砚', '许庭'], 'constraints': '已有事实与尚未发生的规划必须区分。' * 100}
    source = {'input_manifest': {'constraints': content}, 'context_bundle': {'constraints': content,
        'repair': {'error_code': 'CHAPTER_STATE_TRANSITION_IDENTITY_INVALID', 'candidate': content}}}
    encoded, proof = compile_exact_context_references(source)
    assert expand_exact_context_references(encoded) == source
    assert proof['reference_count'] >= 2
    assert len(__import__('json').dumps(encoded)) < len(__import__('json').dumps(source)) / 2


@pytest.mark.parametrize('intent_boundary,version', [(True, 'v3'), (False, 'v2')])
def test_current_planning_template_binds_whole_envelope_and_retains_historical_template(intent_boundary, version):
    from pathlib import Path
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    root = Path(__file__).resolve().parents[2]
    historical = {} if intent_boundary else {'narrative_intent_boundary': False}
    current = build_story_planning_pack_profile(root, operation_definition_hash='sha256:' + 'a' * 64, execution_contract_version='1.21.0', **historical)
    assert current.manifest['prompt_binding']['template_version'] == version
    assert '{{provider_data_envelope}}' in (root / f'config/capability_packs/artifacts/story_planning_template_{version}.md').read_text()
    assert '{{input_manifest}}' in (root / 'config/capability_packs/artifacts/story_planning_template.md').read_text()


@pytest.mark.parametrize('reasons,allowed', [
    ([['TEMPLATE_MODEL_UNAUTHORIZED', 'CONTEXT_CAPACITY_EXCEEDED'], ['CONTEXT_CAPACITY_EXCEEDED', 'BUDGET_HARD_LIMIT']], True),
    ([['TEMPLATE_MODEL_UNAUTHORIZED', 'CONTEXT_CAPACITY_EXCEEDED']], False),
    ([['AUTHORIZATION_MISSING', 'CONTEXT_CAPACITY_EXCEEDED']], False),
    ([['BUDGET_HARD_LIMIT']], False),
    ([['QUALITY_FLOOR_NOT_MET', 'CONTEXT_CAPACITY_EXCEEDED']], False),
    ([['CONTEXT_CAPACITY_EXCEEDED', 'PROVIDER_MODEL_CAPACITY_UNAVAILABLE']], True),
    ([['PROVIDER_MODEL_CAPACITY_UNAVAILABLE']], False),
    ([['CONTEXT_CAPACITY_EXCEEDED', 'PROVIDER_UNAVAILABLE:PROVIDER_MODEL_CAPACITY_UNAVAILABLE:receipt:until:2026-10-12T14:05:15+00:00']], True),
    ([['CONTEXT_CAPACITY_EXCEEDED', 'PROVIDER_UNAVAILABLE:AUTHORIZATION_MISSING:receipt:until:2026-10-12T14:05:15+00:00']], False),
])
def test_planning_capacity_recovery_uses_authorized_candidate_failures(reasons, allowed):
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_capacity_route_candidates
    frozen = {'project_id': 'project', 'book_id': 'book'}
    decision = {'status': 'BLOCKED', 'task': {'project_id': 'project', 'work_id': 'book', 'operation_id': 'operation'},
        'candidates': [{'rejected_reasons': value} for value in reasons]}
    if allowed:
        require_capacity_route_candidates(decision, frozen=frozen, source_operation_id='operation')
    else:
        with pytest.raises(KernelError, match='PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED'):
            require_capacity_route_candidates(decision, frozen=frozen, source_operation_id='operation')


def test_structured_exact_transport_reconstructs_full_json_and_object_deltas_after_canonical_ordering():
    import json
    shared = {'experience': '实际经历不能遗漏。' * 120, 'constraints': ['完整保留作品约束。' * 50]}
    scene = {**shared, 'action': '实际执行而非核验。' * 50}
    source = {'context_bundle': {'segments': [{'safe_summary': json.dumps(shared,ensure_ascii=False,sort_keys=True,separators=(',',':'))}],
              'mission': scene}, 'input_manifest': {'plan': {**scene, 'scene_plan': [shared], 'scene_sequence': [shared]}}}
    legacy, _ = compile_exact_context_references(source)
    encoded, proof = compile_exact_context_references(source, structured_transport=True)
    restored = expand_exact_context_references(json.loads(json.dumps(encoded,sort_keys=True)))
    assert restored == source
    assert proof['decoded_equal'] and proof['canonical_json_string_count'] == 1 and proof['delta_reference_count'] > 0
    assert len(json.dumps(encoded,ensure_ascii=False).encode()) < len(json.dumps(legacy,ensure_ascii=False).encode())
    assert compile_exact_context_references(source)[0] == legacy


@pytest.mark.parametrize('start', [0, 19])
def test_contiguous_text_transport_keeps_unicode_whitespace_hashes_and_referenced_fragments(start):
    import hashlib
    import json
    parts = ['徐照接过盘。\n\n', '裴晏说：“先学引气。”\n', '她停步🙂，没再追问。' * 40]
    passages, offset = [], start
    for text in parts:
        passages.append({'start':offset,'end':offset+len(text),'text':text,'text_hash':'sha256:'+hashlib.sha256(text.encode()).hexdigest()})
        offset += len(text)
    source = {'a':{'asset_version_id':'selected-v4','passages':passages},'b':passages,'c':passages[-1]}
    encoded,proof = compile_exact_context_references(source,structured_transport=True)
    assert expand_exact_context_references(json.loads(json.dumps(encoded,sort_keys=True))) == source
    assert proof['transport_version']=='provider-structured-exact-reference.v2'
    assert proof['text_fragment_group_count']>=1
    assert encoded['a']['passages']['__text_fragments__']['text']==''.join(parts)


@pytest.mark.parametrize('fault', ['gap','bad-hash','extra-field'])
def test_inexact_passages_keep_original_data_without_reconstructed_claims(fault):
    import hashlib
    source=[{'start':i,'end':i+1,'text':'甲','text_hash':'sha256:'+hashlib.sha256('甲'.encode()).hexdigest()} for i in (0,1)]
    if fault=='gap':
        source[1].update(start=2,end=3)
    if fault=='bad-hash':
        source[1]['text_hash']='sha256:unverified'
    if fault=='extra-field':
        source[1]['unresolved']='still open'
    encoded,proof=compile_exact_context_references(source,structured_transport=True)
    assert expand_exact_context_references(encoded)==source
    assert proof['text_fragment_group_count']==0


def test_working_context_fits_real_transport_without_dropping_prose_or_calling_compressor():
    import hashlib
    import json
    from novel_forge.modules.context_contracts import ContextCandidate
    from novel_forge.modules.context_builder.task_compression import compile_task_context
    paragraphs, offset = [], 0
    for index in range(80):
        text = str(index) + '徐照把盘子放稳。' * 5 + '\n\n'
        paragraphs.append({'start':offset,'end':offset+len(text),'text':text,'text_hash':'sha256:'+hashlib.sha256(text.encode()).hexdigest()})
        offset += len(text)
    intent = {'working_manuscript':{'projection_policy':{'version':'working-prose-projection.v3'},
        'sources':[{'asset_version_id':'selected:v4','passages':paragraphs}]}}
    serialized = json.dumps(intent,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    assert len(serialized.encode()) > 15000
    boundary = {'accepted_through_chapter':0}
    source = ContextCandidate(asset_version_id='intent',asset_type='chapter_execution_intent',project_id='p',
        estimated_tokens=0,safe_summary=serialized,provenance={'working_artifact':True},accepted_boundary=boundary)
    compressor = Mock(side_effect=AssertionError('FULL_INPUT_ALREADY_FITS_REAL_REPRESENTATION'))
    selected, receipt = compile_task_context([source],task={'stage':'draft','accepted_boundary':boundary},
        token_budget=15000,required_asset_types=('chapter_execution_intent',),model_call=compressor,compression_input_tokens=64000)
    assert len(selected)==1 and selected[0].safe_summary==serialized
    assert selected[0].asset_version_id=='intent' and selected[0].estimated_tokens<15000
    assert not receipt['excluded_asset_version_ids'] and not receipt['compression_trace']
    compressor.assert_not_called()


@pytest.mark.parametrize('payload', [
    {'start':True,'ends':[1,2],'text':'甲乙'}, {'start':0,'ends':[1,1],'text':'甲乙'},
    {'start':0,'ends':[1,2],'text':'甲乙丙'}, {'start':0,'ends':[1,3],'text':'甲乙'},
    {'start':0,'ends':[1],'text':'甲'}, {'start':0,'ends':[1,2],'text':'甲乙','extra':True},
])
def test_text_transport_cannot_fabricate_boundaries_or_discard_characters(payload):
    with pytest.raises(KernelError,match='PROVIDER_EXACT_REFERENCE_INVALID'):
        expand_exact_context_references({'__text_fragments__':payload})


@pytest.mark.parametrize('invalid', [
    {'__exact_value_ref__': '/future', '__exact_value_overrides__': {}},
    {'__exact_value_ref__': '/source', '__exact_value_removed_keys__': ['absent']},
    {'__exact_value_ref__': '/source', '__exact_value_overrides__': []},
    {'__canonical_json_string__': []},
    {'__canonical_json_string__': {}, 'unexpected': True},
    {'__exact_value_overrides__': {}},
])
def test_structured_exact_transport_rejects_invalid_or_forward_data(invalid):
    with pytest.raises(KernelError, match='PROVIDER_EXACT_REFERENCE_INVALID'):
        expand_exact_context_references({'source': {'required': 'retained'}, 'target': invalid})


@pytest.mark.parametrize('marker', ['__exact_value_overrides__', '__exact_value_removed_keys__', '__canonical_json_string__'])
def test_structured_transport_cannot_confuse_source_text_with_host_markers(marker):
    with pytest.raises(KernelError, match='PROVIDER_EXACT_REFERENCE_COLLISION'):
        compile_exact_context_references({'safe_summary': {marker: 'author data'}},structured_transport=True)
