import pytest

from novel_forge.modules.story_planning_runtime.foundation_generation import (
    FOUNDATION_GENERATORS, foundation_output_schema, validate_foundation_applicability,
)
from tests.integration.creative_grounding_support import CreativeGroundingTransport
from tests.integration.synthesis_production_support import SynthesisTransport, SynthesisChapterTransport


@pytest.mark.parametrize('contract', ['foundation-generation.v2', 'foundation-generation.v3', 'foundation-generation.v4'])
@pytest.mark.parametrize('stage', list(FOUNDATION_GENERATORS))
def test_foundation_fixture_paths_match_exact_frozen_contract(stage, contract):
    output = SynthesisTransport().planning(stage, {'foundation_task': {'contract_version': contract}})
    current = contract == 'foundation-generation.v4'
    schema = foundation_output_schema(stage, work_requirements=True, rfc6901_paths=current)
    validate_foundation_applicability(output, schema, rfc6901_paths=current)
    assert all(item['field_path'].startswith('/' if current else '$.') for item in output['applicability'])


@pytest.mark.parametrize('version', ['1.18.0', '1.19.0', '1.20.0'])
def test_current_planning_fixture_uses_mission4_without_rewriting_legacy(monkeypatch, version):
    monkeypatch.setattr(CreativeGroundingTransport, 'planning', lambda *a: {'required_state_delta': {'field': 'value'}})
    # WHY: This unit checks wire-version conversion; native frozen Context loading has PostgreSQL coverage.
    monkeypatch.setattr('tests.integration.current_planning_wire_support.current_planning_fixture_inputs', lambda inputs, database_url: inputs)
    output = SynthesisChapterTransport().planning('chapter_plan.generate', {'planning_command': {
        'execution_contract_version': version, 'creative_requirements_contract': 'work-requirements.v2'}})
    assert output['chapter_contract_schema_version'] == ('chapter-mission-scene.v3' if version == '1.18.0' else 'chapter-mission-scene.v4')
    assert ('serialization_function' in output) is (version in {'1.19.0', '1.20.0'})


@pytest.mark.parametrize('version', ['1.18.0', '1.21.0'])
def test_current_planning_fixture_still_requires_its_frozen_context(version):
    from tests.integration.current_planning_wire_support import current_planning_fixture_inputs

    with pytest.raises(ValueError, match='actual frozen Context'):
        current_planning_fixture_inputs({'stage': 'chapter_plan.generate', 'planning_command': {
            'execution_contract_version': version}}, '')


@pytest.mark.parametrize('agency', [False, True])
def test_world_fixture_classifies_only_current_ordinary_actions(monkeypatch, agency):
    from copy import deepcopy
    import json

    ordinary = {'action': 'act on the approved faction pressure', 'state_kind': 'world_state'}
    disclosure = {**ordinary, 'state_kind': 'disclosure_event'}
    raw = {'candidates': [{'transition': {'payload_json': json.dumps(ordinary)},
                           'preparation_paths': [{'steps': [{'transition': {'payload_json': json.dumps(disclosure)}}]}]}]}
    monkeypatch.setattr(CreativeGroundingTransport, 'planning', lambda *args: deepcopy(raw))
    task = {'accepted_through_chapter': 0, **({'epistemic_contract': 'world-agency.v2'} if agency else {})}
    output = SynthesisChapterTransport().planning('world_candidates.generate', {'world_preparation': task})
    assert ('action_mode' in json.loads(output['candidates'][0]['transition']['payload_json'])) is agency
    assert 'action_mode' not in json.loads(output['candidates'][0]['preparation_paths'][0]['steps'][0]['transition']['payload_json'])
    if not agency:
        assert output == raw


@pytest.mark.parametrize('agency', [False, True])
@pytest.mark.parametrize('noop', [False, True])
def test_world_director_classifies_exact_paths_without_approving_borrowed_knowledge(monkeypatch, agency, noop):
    from novel_forge.modules.worldbuilding.production_schema import agency_transition_paths

    ordinary = {'action': 'act on the approved faction pressure', 'state_kind': 'world_state', 'action_mode': 'ROUTINE'}
    disclosure = {**ordinary, 'state_kind': 'disclosure_event'}
    generated = {'candidates': [] if noop else [{'transition': ordinary,
                     'preparation_paths': [{'steps': [{'transition': disclosure}]}]}]}
    monkeypatch.setattr(CreativeGroundingTransport, 'planning', lambda *args: {'evaluations': []})
    output = SynthesisChapterTransport().planning('world_candidates.evaluate', {'world_preparation': {
        'generated_portfolio': generated, **({'epistemic_contract': 'world-agency.v2'} if agency else {})}})
    if agency:
        checks = output['action_classifications']
        assert [row['field_path'] for row in checks] == list(agency_transition_paths(generated))
        assert [row['supported'] for row in checks] == ([] if noop else [True, False])
        assert all(row['rationale'].strip() for row in checks)
    else:
        assert output == {'evaluations': []}
