import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder import semantic_units, source_json
from novel_forge.modules.context_builder.domain import build_authority_context_bundle, validate_task_context_sources
from novel_forge.modules.context_builder.story_projection import clean_context_candidates, story_history
from novel_forge.modules.context_builder.task_compression import compile_task_context
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy


def projected_context(raw, *, semantic=True, early_clean=False):
    boundary = {'accepted_through_chapter': 0}
    original = ContextCandidate(asset_version_id='source', asset_type='chapter_episodic_summary', project_id='p', book_id='b',
        estimated_tokens=1, relevance_score=1, safe_summary=raw, content_digest='original-content-hash', accepted_boundary=boundary, provenance={'authority': 'Book'})
    plan = ContextCandidate(asset_version_id='plan', asset_type='chapter_plan', project_id='p', book_id='b',
        estimated_tokens=1, safe_summary='查证原始记录。', context_class='PROTECTED', accepted_boundary=boundary, provenance={'authority': 'Planning'})
    candidates = [plan, original]
    if early_clean:
        candidates = clean_context_candidates(candidates, stage='draft', preserve_json=semantic)
    access = resolve_book_knowledge_access_policy(production_profile={}, project_id='p', book_id='b')
    admitted = validate_task_context_sources(project_id='p', book_id='b', candidates=candidates, token_budget=512000,
        required_asset_types=(), accepted_boundary=boundary, knowledge_access_policy=access)
    calls = []
    def unexpected(*args):
        calls.append(args)
        raise AssertionError('Fitting input must use the fast path')
    selected, receipt = compile_task_context(candidates, task={'stage': 'draft', 'accepted_boundary': boundary,
        'writer_projection_version': 'accepted-writer-history.v2',
        **({'semantic_contract': semantic_units.SEMANTIC_CONTRACT} if semantic else {})}, token_budget=512000,
        required_asset_types=(), admitted_source_ids=admitted, model_call=unexpected, defer_token_capacity=True)
    bundle = build_authority_context_bundle(project_id='p', book_id='b', stage='draft', created_by_operation_id='operation',
        context_profile_version='draft-context-profile-v4', candidates=selected, token_budget=512000,
        authority_state_boundary=boundary, knowledge_access_policy=access, task_context_receipt=receipt, defer_token_capacity=True)
    provider = build_provider_context_view('draft', bundle, {'chapter': 1}, complete_request_capacity=True,
        writer_projection_version='accepted-writer-history.v2')
    result = next(row for row in provider['segments'] if row['asset_version_id'] == 'source')
    assert not calls and receipt['fast_path']
    assert original.safe_summary == raw and original.content_digest == 'original-content-hash'
    return result['safe_summary']


@pytest.mark.parametrize('early_clean', [False, True])
@pytest.mark.parametrize('number', ['0.123456789012345678901', '-0', '1e99999999999999999999999999', '123456789012345678901234567890'])
def test_first_cleaning_through_actual_provider_keeps_numeric_lexemes_and_filters_private_fields(early_clean, number):
    raw = '{"quantity":' + number + ',"units":"尺","summary":"只有低于该刻度才能开闸。","provider_evidence":{"text":"执行秘密"},"internal":{"provider_visibility":"INTERNAL_QUALITY_ONLY","text":"评审秘密"}}'
    final = projected_context(raw, early_clean=early_clean)
    assert '"quantity":' + number in final
    assert '执行秘密' not in final and '评审秘密' not in final
    assert source_json.loads(final)['units'] == '尺'


@pytest.mark.parametrize('raw,code', [
    ('{"subject":"甲","subject":"乙","summary":"未曾开闸。"}', 'CONTEXT_SOURCE_JSON_AMBIGUOUS'),
    ('{"quantity":NaN,"summary":"未曾开闸。"}', 'CONTEXT_SOURCE_JSON_NONFINITE'),
    ('{"nested":"{\\"subject\\":\\"甲\\",\\"subject\\":\\"乙\\"}"}', 'CONTEXT_SOURCE_JSON_AMBIGUOUS'),
])
def test_ambiguous_source_is_exposed_before_cleaning_can_select_a_winner(raw, code):
    with pytest.raises(KernelError, match=code):
        projected_context(raw, early_clean=True)


def test_old_frozen_writer_projection_retains_its_original_decoding_contract():
    raw = '{"quantity":0.123456789012345678901,"summary":"原始记录。"}'
    assert json.loads(projected_context(raw, semantic=False))['quantity'] == 0.12345678901234568
    assert '0.123456789012345678901' in projected_context(raw)


def test_nested_prose_facts_keep_quantity_and_visibility_in_final_history_projection():
    raw = '{"chapter":1,"text":"她未曾开闸。","structured_facts":[{"quantity":0.123456789012345678901,"units":"尺"},{"provider_visibility":"INTERNAL_QUALITY_ONLY","text":"秘密"}],"selected_review":{"text":"秘密"}}'
    final = story_history(raw, physical_type='draft_chapter', preserve_json=True)
    assert '"quantity":0.123456789012345678901' in final and '秘密' not in final
    assert final == story_history(final, physical_type='draft_chapter', preserve_json=True)


def test_lossless_json_codec_is_reversible_for_unicode_and_nested_number_lexemes():
    raw = '{"text":"🜁\\r\\n条件\\u0000","nested":"{\\"quantity\\":0.123456789012345678901}","values":[-0,1e-999999,12345678901234567890,true,null]}'
    decoded = source_json.loads(raw)
    canonical = source_json.dumps(decoded)
    assert source_json.loads(canonical) == decoded
    assert source_json.dumps(source_json.loads(canonical)) == canonical


def test_rebuild_recovers_only_the_original_selected_json_field_and_keeps_other_scope():
    from novel_forge.modules.context_builder.retrieval_rebuild import writer_index_document
    original = {'safe_summary': '{"quantity":0.123456789012345678901,"units":"尺","summary":"未达条件。"}',
        'unselected': '整份资产中另有材料。'}
    derived = {'safe_summary': '{"quantity":0.12345678901234568,"summary":"未达条件。","units":"尺"}'}
    document = {'source_artifact_type': 'chapter_episodic_summary', 'content_text': json.dumps(derived, ensure_ascii=False), 'metadata': {}}
    rebuilt = writer_index_document(document, original)
    assert '0.123456789012345678901' in rebuilt['content_text'] and '整份资产' not in rebuilt['content_text']
    assert rebuilt['metadata']['source_json_projection'] == 'source-json-values.v1'
    assert writer_index_document(rebuilt, original) == rebuilt


def test_rebuild_rejects_changed_json_field_instead_of_importing_unselected_source():
    from novel_forge.modules.context_builder.story_projection import restore_source_json_fields
    with pytest.raises(KernelError, match='CONTEXT_SOURCE_JSON_SCOPE_CHANGED'):
        restore_source_json_fields('{"safe_summary":"{\\"quantity\\":0.5}"}', {'safe_summary': '{"quantity":0.123456789012345678901}'})


def test_retrieval_merge_keeps_exact_source_numbers_after_selected_document_projection():
    from novel_forge.modules.chapter_authority.handlers import merge_task_retrieval_projections
    raw = '{"safe_summary":"{\\"quantity\\":0.123456789012345678901,\\"summary\\":\\"原始经历。\\"}"}'
    metadata = {'safe_summary': raw, 'content_hash': 'h', 'physical_asset_type': 'chapter_episodic_summary'}
    document = {'retrieval_document_id': 'd', 'source_content_hash': 'h', 'source_artifact_type': 'chapter_episodic_summary',
        'safe_summary': raw, 'compression_provenance': {'writer_projection_version': 'accepted-writer-history.v2'}}
    result = merge_task_retrieval_projections(metadata, [document], preserve_json=True)
    assert '0.123456789012345678901' in result['safe_summary']


def test_filtered_json_list_uses_unique_original_element_scope_and_reports_both_positions():
    from novel_forge.modules.context_builder.story_projection import restore_source_json_fields, visible_business_data
    source = {'entries': [
        {'provider_visibility': 'INTERNAL_QUALITY_ONLY', 'summary': '内部'},
        {'subject': '甲', 'summary': '{"quantity":0.123456789012345678901}'},
    ]}
    old = visible_business_data(json.dumps(source, ensure_ascii=False), stage='draft', history=True)
    restored, bindings = restore_source_json_fields(old, source)
    assert '0.123456789012345678901' in restored and '内部' not in restored
    assert bindings[0]['source_field_path'] == ['entries', 1, 'summary']
    assert bindings[0]['selected_field_path'] == ['entries', 0, 'summary']
    assert restore_source_json_fields(restored, source)[0] == restored


def test_lossy_duplicate_list_matches_do_not_choose_an_arbitrary_original_precision():
    from novel_forge.modules.context_builder.story_projection import restore_source_json_fields
    source = {'entries': [{'summary': '{"quantity":0.123456789012345678901}'}, {'summary': '{"quantity":0.123456789012345678902}'}]}
    with pytest.raises(KernelError, match='CONTEXT_SOURCE_JSON_SCOPE_CHANGED'):
        restore_source_json_fields('{"entries":[{"summary":"{\\"quantity\\":0.12345678901234568}"}]}', source)


def test_reordered_source_records_bind_quantities_to_the_original_event_not_the_list_index():
    from novel_forge.modules.context_builder.story_projection import restore_source_json_fields, visible_business_data
    source = {'records': [{'event_id': 'A', 'payload': '{"quantity":0.123456789012345678901}'},
        {'event_id': 'B', 'payload': '{"quantity":0.123456789012345678902}'}]}
    old = json.loads(visible_business_data(json.dumps(source), stage='draft', history=True))
    old['records'].reverse()
    result, bindings = restore_source_json_fields(json.dumps(old), source)
    values = {row['event_id']: row['payload'] for row in json.loads(result)['records']}
    assert '0.123456789012345678901' in values['A'] and '0.123456789012345678902' in values['B']
    assert bindings[0]['source_field_path'] == ['records', 1, 'payload']
    assert bindings[0]['selected_field_path'] == ['records', 0, 'payload']


def test_changed_subject_cannot_borrow_a_json_field_from_another_original_record():
    from novel_forge.modules.context_builder.story_projection import restore_source_json_fields
    source = {'subject': '甲', 'payload': '{"quantity":0.123456789012345678901}'}
    with pytest.raises(KernelError, match='CONTEXT_SOURCE_JSON_SCOPE_CHANGED'):
        restore_source_json_fields('{"subject":"乙","payload":"{\\"quantity\\":0.12345678901234568}"}', source)


def test_selected_list_cannot_duplicate_one_original_record_as_two_source_events():
    from novel_forge.modules.context_builder.story_projection import restore_source_json_fields, visible_business_data
    source = {'records': [{'event_id': 'A', 'payload': '{"quantity":0.123456789012345678901}'}]}
    legacy = json.loads(visible_business_data(json.dumps(source), stage='draft', history=True))
    legacy['records'] *= 2
    with pytest.raises(KernelError, match='CONTEXT_SOURCE_JSON_SCOPE_CHANGED'):
        restore_source_json_fields(json.dumps(legacy), source)


def test_json_looking_novel_prose_remains_exact_and_is_not_treated_as_business_metadata():
    raw = '{"text":"{\\"quantity\\":0.123456789012345678901,\\"provider_visibility\\":\\"INTERNAL_QUALITY_ONLY\\"}"}'
    projected = story_history(raw, physical_type='draft_chapter', preserve_json=True)
    assert json.loads(projected)['text'] == json.loads(raw)['text']


def test_precise_numeric_opaque_source_still_locates_cross_paragraph_quotes_and_dependencies():
    original = ContextCandidate(asset_version_id='source', asset_type='chapter_episodic_summary', project_id='p', estimated_tokens=1,
        safe_summary='{"quantity":0.123456789012345678901,"event_id":"effect","cause_refs":["cause"],"summary":"🜁门仍未开。\\r\\n\\r\\n只有潮声停下才可以开闸。"}')
    units = semantic_units.source_units(original, {})
    proof = semantic_units.protect_quotes([original], {'source': units}, ['🜁门仍未开。\n\n只有潮声停下才可以开闸。'])
    assert proof[0]['matches'][0]['field_positions'][0][0] == ('summary',)
    assert units[0]['explicit_refs'] == ['cause'] and units[0]['source_aliases'] == ['effect']
    assert semantic_units.reconstruct(original, units, {units[0]['unit_id']})['safe_summary'] == original.safe_summary
    assert semantic_units.close_dependencies([*units, {'unit_id': 'before', 'source_aliases': ['cause'], 'explicit_refs': []}], {units[0]['unit_id']}) == {units[0]['unit_id'], 'before'}
    json.dumps(units)


def test_unchanged_precise_json_record_can_satisfy_a_located_protected_dependency():
    source = {'safe_summary': '{"event_id":"cause","quantity":0.123456789012345678901,"summary":"许可尚未生效。"}'}
    bindings = semantic_units.protected_dependency_bindings(source, excluded_scopes=set())
    assert bindings[0]['alias'] == 'cause'
    assert bindings[0]['original_projection_path'] == ['safe_summary', '$decoded_json']
    assert bindings == semantic_units.protected_dependency_bindings(json.loads(json.dumps(source)), excluded_scopes=set())
    changed = {'safe_summary': source['safe_summary'].replace('901', '902')}
    assert bindings[0]['record_hash'] != semantic_units.protected_dependency_bindings(changed, excluded_scopes=set())[0]['record_hash']


@pytest.mark.parametrize('text', ['858e3085-14c0-42a5-8f7f-ed4e259d8a28:NARRATOR', '123e9999:角色', '1e999999 invalid tail'])
def test_numeric_looking_plain_identifiers_are_not_misclassified_as_json_values(text):
    assert semantic_units.decode_json_values(text) == (None, 'PLAIN_TEXT')
    source = ContextCandidate(asset_version_id='source', asset_type='chapter_episodic_summary', project_id='p', estimated_tokens=1, safe_summary=text)
    units = semantic_units.source_units(source, {})
    assert units[0]['kind'] == 'SOURCE_PARAGRAPH' and units[0]['text'] == text
    assert semantic_units.protect_quotes([source], {'source': units}, [text])


@pytest.mark.parametrize('text', ['NaN is a name.', 'Infinity River', '{"subject":"A","subject":"B"} then a story.', '{"quantity":NaN} then a story.'])
def test_json_looking_prefixes_require_complete_json_syntax_before_source_rejection(text):
    from novel_forge.modules.context_builder.story_projection import visible_business_data
    assert visible_business_data(text, stage='draft', preserve_json=True) == text
    assert semantic_units.decode_json_values(text) == (None, 'PLAIN_TEXT')
    assert projected_context(text) == text


def test_valid_large_json_integer_is_required_original_not_optional_plain_text():
    raw = '{"quantity":' + '7' * 5000 + ',"summary":"只有低于这个值才可开闸。"}'
    original = ContextCandidate(asset_version_id='source', asset_type='chapter_episodic_summary', project_id='p', estimated_tokens=1, safe_summary=raw)
    assert semantic_units.decode_json_values(raw) == (None, 'JSON_NUMERIC_VALUE_NOT_PRESERVED')
    units = semantic_units.source_units(original, {})
    assert len(units) == 1 and units[0]['required'] and units[0]['kind'] == 'OPAQUE_ORIGINAL_JSON'
    assert semantic_units.protect_quotes([original], {'source': units}, ['只有低于这个值才可开闸。'])
    assert semantic_units.reconstruct(original, units, {units[0]['unit_id']})['safe_summary'] == raw
