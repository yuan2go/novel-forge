from copy import deepcopy

import pytest

from novel_forge.modules.book_followup_authority.prose_semantic_relations import accepted_relation_evidence, RELATION_VERSION
from novel_forge.modules.book_followup_authority.prose_review import freeze_manifest, text_digest, validate_window_report
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_longform_prose_editorial import report


def source(number, text, *, identity='promise:boat'):
    version = 'draft:' + str(number)
    event = {'event_id': 'event:' + str(number), 'state_kind': 'narrative_obligation',
             'identity': {'entity_key': identity}, 'mutation': {'payload': {'obligation_id': identity}},
             'provenance': {'accepted_draft_asset_version_id': version},
             'evidence': {'source_revision_asset_version_id': version, 'span': {'start': 0, 'end': len(text)}, 'excerpt_digest': text_digest(text)}}
    evidence, coverage = accepted_relation_evidence({'state_events': [event]}, {'text': text}, version)
    return {'acceptance_id': 'accepted:' + str(number), 'chapter_number': number, 'asset_version_id': version,
            'asset_hash': 'hash:' + str(number), 'text': text, 'relation_evidence': evidence, 'relation_evidence_coverage': coverage}


def freeze(sources, version=RELATION_VERSION):
    return freeze_manifest(project_id='project', workspace_id='workspace', book_run_id='book', sources=sources,
        policy={'policy_version': 'semantic-review-test-v2', 'window_codepoints': 128, 'overlap_codepoints': 0,
                'context_token_budget': 4096, 'maximum_windows': 10, 'relation_window_limit': 2,
                'relation_retrieval_version': version})


def test_paraphrases_without_common_text_use_accepted_identity_and_three_passages():
    sources = [source(1, 'She pledged to fetch him.'), source(6, '老艄公等着姑娘归航。'), source(10, 'The debt remained unpaid.')]
    frozen = freeze(sources)
    window = next(row for row in frozen['windows'] if row.get('relation_hypothesis'))
    assert len(window['spans']) == 3
    assert window['relation_hypothesis']['basis'] == 'ACCEPTED_STATE_IDENTITIES_AND_CAUSES'
    assert window['relation_hypothesis']['status'] == 'UNVERIFIED'
    assert not window['relation_hypothesis']['hard_dependency_created']
    assert sum(len(row['text']) for row in window['spans']) <= 128
    reviewed = report(frozen, window)
    reviewed['findings'][0]['evidence'] = [dict(asset_version_id=row['asset_version_id'], text_hash=row['text_hash'], start=row['start'], end=row['end'], quote=row['text']) for row in window['spans']]
    validate_window_report(reviewed, manifest=frozen, window=window)
    reviewed['findings'][0]['evidence'].pop()
    with pytest.raises(KernelError, match='retrieved passages'):
        validate_window_report(reviewed, manifest=frozen, window=window)
    assert freeze(deepcopy(sources)) == frozen
    assert 'UNINDEXED_PARAPHRASE' in frozen['relation_retrieval']['uncovered_relation_classes']


def test_same_word_does_not_create_structural_identity_or_causal_edge():
    frozen = freeze([source(1, 'A silver seal.', identity='object:a'), source(8, 'A silver seal.', identity='object:b')])
    assert not any(row.get('relation_hypothesis') for row in frozen['windows'])
    assert frozen['relation_retrieval']['global_relationships_verified'] is False


def test_missing_or_stale_locations_are_coverage_gaps_not_semantic_proof():
    event = {'event_id': 'event', 'state_kind': 'character_knowledge', 'mutation': {'payload': {'character_id': 'hero'}},
        'provenance': {'accepted_draft_asset_version_id': 'different'},
        'evidence': {'source_revision_asset_version_id': 'different', 'span': {'start': 0, 'end': 4}, 'excerpt_digest': text_digest('some')}}
    evidence, coverage = accepted_relation_evidence({'state_events': [event, {**event, 'evidence': {}}]}, {'text': 'some text'}, 'draft')
    assert evidence == []
    assert coverage['invalid_location'] == coverage['unlocated'] == 1


def test_legacy_window_identity_ignores_new_structural_evidence():
    inputs = [source(1, 'There is no common anchor.'), source(8, '岸边只剩一盏灯。')]
    frozen = freeze(inputs, 'lexical.v1')
    inputs[0]['relation_evidence'][0]['references'].append('other')
    assert freeze(inputs, 'lexical.v1') == frozen
