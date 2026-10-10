from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.provider_output_contracts import _validate
from novel_forge.modules.hierarchical_planning.domain import PlanContractType
from novel_forge.modules.story_planning_runtime.execution import _canonical_narrative_provider_properties, planning_provider_output_schema
from novel_forge.modules.story_planning_runtime.semantic_fields import bind_semantic_fields


@pytest.mark.parametrize('scope,current', [(PlanContractType.CHAPTER,'ACTIVE'), (PlanContractType.CHAPTER_GROUP,'DETAILED')])
def test_current_realization_schema_uses_owner_rank_and_preserves_source_schema(scope,current):
    schema = {'properties': _canonical_narrative_provider_properties(scope)}
    before = deepcopy(schema)
    bound = bind_semantic_fields(schema,scope)
    assert schema == before
    assert bound['properties']['realization_level']['const'] == current
    for manifest in ('world_realization','character_realization'):
        current_schema, future_schema = bound['properties'][manifest]['items']['anyOf']
        _validate(current_schema['properties']['realization_level'],current,path='$')
        with pytest.raises(ValueError):
            _validate(current_schema['properties']['realization_level'],'DEFINED',path='$')
        _validate(future_schema['properties']['realization_level'],'DEFINED',path='$')
        with pytest.raises(ValueError):
            _validate(future_schema['properties']['narrative_relevance'],'CURRENT',path='$')


def test_scene_contract_describes_entry_knowledge_and_returned_timeline():
    bound = bind_semantic_fields({'properties': _canonical_narrative_provider_properties(PlanContractType.CHAPTER)},PlanContractType.CHAPTER)
    props=bound['properties']['scene_plan']['items']['properties']
    assert 'earlier scene' in props['accessible_knowledge']['description']
    assert 'Never write prose summaries' in props['accessible_knowledge']['description']
    assert 'ESTABLISHES' in props['narrative_time_relation']['description']
    assert 'not earlier chapters' in props['narrative_time_relation']['description']


def test_formal_state_and_segment_references_are_host_bound_and_legacy_is_unchanged():
    schema=planning_provider_output_schema(PlanContractType.VOLUME)
    legacy=bind_semantic_fields(schema,PlanContractType.VOLUME)
    new=bind_semantic_fields(schema,PlanContractType.VOLUME,story_state_version='state:exact-frozen-book')
    for part in [new['properties']['entry_state_ref'],new['properties']['narrative_segments']['items']['properties']['entry_state_ref']]:
        _validate(part,'state:exact-frozen-book',path='$')
        for foreign in ['state:another-book','authority-output:working-draft-version']:
            with pytest.raises(ValueError):
                _validate(part,foreign,path='$')
    assert 'const' not in legacy['properties']['entry_state_ref']
    with pytest.raises(ValueError):
        bind_semantic_fields(schema,PlanContractType.VOLUME,story_state_version='')
