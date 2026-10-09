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
