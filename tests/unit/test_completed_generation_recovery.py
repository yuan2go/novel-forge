from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.generation_isolation import partition_generation_effects
from novel_forge.modules.command_kernel.manual_effect_resolution import ExternalEffectManualResolutionCommand, _same_isolation_replay
from novel_forge.modules.chapter_authority.provider_views import compile_exact_context_references, expand_exact_context_references
from novel_forge.modules.chapter_authority.author_editor import author_input_provenance


def test_multi_model_node_keeps_completed_compression_and_isolates_only_interrupted_fidelity():
    complete = {'external_effect_id': 'compress', 'effect_type': 'model.invoke', 'status': 'SUCCEEDED'}
    interrupted = {'external_effect_id': 'fidelity', 'effect_type': 'model.invoke', 'status': 'UNKNOWN'}
    assert partition_generation_effects([complete, interrupted]) == ([interrupted], [complete])
    with pytest.raises(KernelError, match='GENERATION_ISOLATION_EFFECT_BOUNDARY_UNSAFE'):
        partition_generation_effects([interrupted, {'effect_type': 'payment', 'status': 'UNKNOWN'}])
    with pytest.raises(KernelError, match='GENERATION_ISOLATION_RESULT_RECOVERABLE'):
        partition_generation_effects([complete])


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
