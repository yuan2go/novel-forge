import json

import pytest

from scripts.narrative_closure_campaign import digest
from scripts.narrative_closure_review import main
from tests.unit.test_creation_export import accepted_workspace, document
from tests.unit.test_narrative_closure_campaign import manifest


def prepared_exports(tmp_path):
    value = manifest()
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'campaign-result.json').write_text(json.dumps({
        'campaign_hash': digest(value), 'status': 'PILOT_AWAITING_NATIVE_READING_DECISIONS'}))
    for sample in value['samples'][:2]:
        for name in ('A', 'B'):
            folder = results / sample['sample_id'] / name
            folder.mkdir(parents=True)
            original = accepted_workspace()
            versions = {item['asset_version_id'] for item in original['artifacts']['history']} | {'outcome', 'plan', 'original'}
            prefix = sample['sample_id'] + ':' + name + ':'
            def rewrite(item):
                if isinstance(item, str):
                    return prefix + item if item in versions else item
                if isinstance(item, list):
                    return [rewrite(row) for row in item]
                if isinstance(item, dict):
                    return {key: rewrite(row) for key, row in item.items()}
                return item
            workspace = rewrite(original)
            workspace['acceptance']['accepted_through_chapter'] = 2
            workspace['acceptance']['outcome']['content']['chapter_number'] = 2
            for row in [workspace['acceptance']['outcome'], *workspace['artifacts']['history']]:
                row.update(document(row['asset_type'], row['asset_version_id'], row['content']))
            (folder / 'chapter-workspaces.json').write_text(json.dumps([workspace]))
            (folder / 'result.json').write_text(json.dumps({'status': 'ACCEPTED_TARGET'}))
    frozen = tmp_path / 'manifest.json'
    frozen.write_text(json.dumps(value))
    return frozen, results


def export(tmp_path):
    frozen, results = prepared_exports(tmp_path)
    packs = tmp_path / 'packs'
    assert main(['export', '--manifest', str(frozen), '--results', str(results),
        '--reviewer', 'human-one', '--reviewer', 'human-two', '--output', str(packs)]) == 0
    return packs


def test_blind_cli_preserves_distinct_tasks_private_bindings_and_explicit_not_run(tmp_path):
    packs = export(tmp_path)
    first = json.loads((packs / 'reader-1.json').read_text())
    second = json.loads((packs / 'reader-2.json').read_text())
    assert len(first['pairs']) == len(second['pairs']) == 2
    assert 'pilot-broken-cost' not in json.dumps(first)
    assert 'campaign_hash' not in first
    assert json.loads((packs / 'private/status.json').read_text())['human_editorial'] == 'NOT_RUN'
    response = json.loads((packs / 'reader-1-response.json').read_text())
    assert response['evidence_class'] == 'NOT_SUBMITTED'
    with pytest.raises(ValueError, match='distinct assigned humans'):
        main(['record', '--packs', str(packs), '--response', str(packs / 'reader-1-response.json'),
            '--response', str(packs / 'reader-2-response.json'), '--output', str(tmp_path / 'report.json')])


def test_record_cli_keeps_disagreement_and_never_qualifies_policy(tmp_path):
    packs = export(tmp_path)
    paths = []
    for index in (1, 2):
        source = packs / f'reader-{index}-response.json'
        response = json.loads(source.read_text())
        response.update(evidence_class='HUMAN_SUBMITTED', attestation='Unit fixture, not actual human evidence')
        public = json.loads((packs / f'reader-{index}.json').read_text())
        for row, pair in zip(response['responses'], public['pairs']):
            row.update(choice='A', confidence=0.75, rationale='Fixture response exercises independent unblinding',
                dimension_scores={key: {'a': 4, 'b': 3} for key in row['dimension_scores']},
                evidence_spans=[{'candidate': 'A', 'start': 0, 'end': 1, 'quote': pair['candidate_a'][:1]}])
        target = tmp_path / f'submitted-{index}.json'
        target.write_text(json.dumps(response))
        paths.append(target)
    report = tmp_path / 'review.json'
    assert main(['record', '--packs', str(packs), '--response', str(paths[0]), '--response', str(paths[1]), '--output', str(report)]) == 0
    result = json.loads(report.read_text())
    assert result['status'] == 'HUMAN_RESPONSES_RECORDED_NOT_QUALIFIED'
    assert result['identity_verification'] == 'ATTESTATION_ONLY'
    assert result['craft_effectiveness'] == 'HYPOTHESIS'
    assert not result['policy_change_authorized']
    assert {row['status'] for row in result['subjects']} == {'DISAGREED'}
    tampered = json.loads(paths[0].read_text())
    tampered['responses'][0]['evidence_spans'][0]['quote'] = 'wrong'
    paths[0].write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match='Unicode code-point'):
        main(['record', '--packs', str(packs), '--response', str(paths[0]), '--response', str(paths[1]), '--output', str(tmp_path / 'bad.json')])
