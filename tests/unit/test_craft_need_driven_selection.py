from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import core_catalog, craft_candidate, craft_hash, validate_craft_mechanism
from novel_forge.modules.mkaos_authority.craft_matching import LEGACY_SELECTION, NEED_DRIVEN_SELECTION, LEGACY_SIGNATURE, SEMANTIC_SIGNATURE
from novel_forge.modules.mkaos_authority.craft_selection import craft_candidate_assessment, craft_pattern_signature, validate_craft_policy
from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed, select_narrative_intelligence
from tests.unit.test_craft_selection import _card, _previous_craft_delivery

LEGACY = json.loads((Path(__file__).parents[1] / 'fixtures/narrative_craft/need_driven_legacy.json').read_text())


def assess(mechanism, context, **kwargs):
    return craft_candidate_assessment(mechanism, context=context, recent_usage=kwargs.pop('recent_usage', []), policy=validate_craft_policy({'cooldown_chapters': 0}), **kwargs)


def need(context, **kwargs):
    return NarrativeIntelligenceNeed(scope='SCENE', target_stage='chapter_plan.generate', craft_context=context, **kwargs)


def test_bounded_candidate_review_delivers_zero_lexical_matches_without_claiming_adoption():
    cards = tuple(_card(item) for item in core_catalog()[:3])
    cold = need({'writing_problem': ['这是全新的中文创作简报'], 'chapter_function': ['WORK_PRODUCTION']})
    assert select_narrative_intelligence(cold, cards)['selected'] == []
    ids = tuple(card['asset_version_id'] for card in cards)
    result = select_narrative_intelligence(cold, cards, candidate_review_card_asset_version_ids=ids)
    assert len(result['selected']) == 3
    assert result['need']['required_card_asset_version_ids'] == []
    assert all(card['craft_assessment']['matching_assessment']['need_score'] == 0 for card in result['selected'])
    assert all(card['craft_assessment']['selection_reason'] == 'BOUNDED_CANDIDATE_REVIEW' for card in result['selected'])
    assert 'PLANNING_MUST_ADOPT_ADAPT_OR_REJECT' in result['candidate_review']['authority_boundary']
    assert 'craft_strategy' not in result
    bounded = select_narrative_intelligence(cold, cards, limit=1, candidate_review_card_asset_version_ids=ids)
    assert len(bounded['selected']) == 1
    assert bounded['candidate_review']['bounded_pool_card_asset_version_ids'] == sorted(ids)
    assert bounded['candidate_review']['exact_candidate_card_asset_version_ids'] == [bounded['selected'][0]['knowledge_card_asset_version_id']]
    blocked = deepcopy(cards[0])
    blocked['content']['abstract_content']['applicability_contract'] = {'schema_version': 'knowledge-applicability.v1',
        'usage_role': 'MECHANISM', 'prerequisites': [], 'exceptions': [], 'hard_conflicts': [
            {'condition_id': 'author-forbids', 'path': '/hard_constraints', 'operator': 'CONTAINS', 'value': '禁止此方法'}]}
    refused = select_narrative_intelligence(need({}, hard_constraints=('禁止此方法',)), (blocked,),
        candidate_review_card_asset_version_ids=(blocked['asset_version_id'],))
    assert refused['selected'] == []
    assert refused['rejected'][0]['reason'] == 'KNOWLEDGE_APPLICABILITY_REJECTED'
    assert refused['candidate_review']['exact_candidate_card_asset_version_ids'] == []
    with pytest.raises(KernelError, match='CRAFT_CANDIDATE_REVIEW_SCOPE_INVALID'):
        select_narrative_intelligence(need({}, craft_selection_policy_version=LEGACY_SELECTION), cards,
            candidate_review_card_asset_version_ids=ids)


def test_exact_baseline_selections_replay_under_legacy_contract():
    cards = tuple(_card(m) for m in LEGACY['mechanisms'])
    for frozen in LEGACY['selections']:
        arguments = {k: v for k, v in frozen['need'].items() if k != 'need_digest'}
        current = select_narrative_intelligence(NarrativeIntelligenceNeed(**arguments, craft_selection_policy_version=LEGACY_SELECTION), cards)
        assert current == frozen
        new = select_narrative_intelligence(NarrativeIntelligenceNeed(**arguments), cards)
        assert new['craft_selection_policy_version'] == NEED_DRIVEN_SELECTION
        if not arguments['craft_context'].get('scene_goal'):
            assert new['selected'] == []
        else:
            assert new['selected']
        assert all(item['selected_content']['selection_tags']['genre'] == [] for item in new['selected'])
        assert all(item['selected_content']['craft_mechanism'] == card['content']['abstract_content']['craft_mechanism'] for item in new['selected'] for card in cards if item['knowledge_card_asset_version_id'] == card['asset_version_id'])


@pytest.mark.parametrize('genre,pov', [('wuxia','limited'), ('xuanhuan','first_person'), ('romance','omniscient'), ('science_fiction','multiple'), ('historical','first_person'), ('campus','omniscient')])
def test_all_core_cards_are_neutral_to_unsupported_genre_and_pov(genre, pov):
    for mechanism in core_catalog():
        baseline = assess(mechanism, {'writing_problem': [mechanism['narrative_problem']]})
        changed = deepcopy(mechanism)
        changed['affinity']['genre'] = [genre]
        changed['affinity']['pov'] = [pov]
        result = assess(changed, {'writing_problem': [mechanism['narrative_problem']], 'genre': [genre], 'pov': [pov]})
        assert result['score'] == baseline['score'] > 0
        assert craft_pattern_signature(mechanism) == craft_pattern_signature(changed)
        assert assess(changed, {'genre': [genre], 'pov': [pov]})['rejection_reason'] == 'CRAFT_NO_CONTEXT_MATCH'
    cards = tuple(_card(m) for m in core_catalog())
    plain = select_narrative_intelligence(need({'writing_problem': ['每个动机和感受都被重复解释']}), cards)
    labeled = select_narrative_intelligence(need({'writing_problem': ['每个动机和感受都被重复解释'], 'genre': [genre], 'pov': [pov]}), cards)
    assert [(c['knowledge_card_asset_version_id'], c['score']) for c in plain['selected']] == [(c['knowledge_card_asset_version_id'], c['score']) for c in labeled['selected']]


def test_dimensions_do_not_match_metadata_or_each_others_semantics():
    mechanism = core_catalog()[0]
    for dimension in ('genre', 'pov', 'scene_type', 'task', 'characters', 'obligations', 'unknown_metadata'):
        assert assess(mechanism, {dimension: [mechanism['narrative_problem']]})['score'] == 0
    assert assess(mechanism, {'reader_effect': [mechanism['narrative_problem']]})['score'] == 0
    assert assess(mechanism, {'writing_problem': {'narrative_problem': mechanism['narrative_problem']}})['score'] == 0
    assert assess(mechanism, {'reader_effect': [mechanism['desired_reader_effect']]})['score'] > 0
    assert assess(mechanism, {'scene_demand': [mechanism['abstract_mechanism']]})['score'] > 0


def test_affinity_needs_exact_evidence_need_and_resolved_applicability_and_is_bounded():
    mechanism = core_catalog()[0]
    mechanism['affinity'] = {key: [key+'-value'] for key in ('genre', 'pov', 'scene_type', 'pacing')}
    mechanism['effect_evidence'] = [{'kind':'CONTROLLED_COMPARISON', 'asset_version_id':'comparison:v1', 'claim':'Scoped comparison, not universal quality'}]
    mechanism['affinity_evidence'] = [{'dimension': key, 'value': values[0], 'asset_version_id':'comparison:v1'} for key,values in mechanism['affinity'].items()]
    labels = deepcopy(mechanism['affinity'])
    assert assess(mechanism, labels, applicability_status='APPLICABLE')['score'] == 0
    context = {**labels, 'writing_problem': [mechanism['narrative_problem']]}
    unknown = assess(mechanism, context)
    scoped = assess(mechanism, context, applicability_status='APPLICABLE')
    assert unknown['matching_assessment']['affinity_adjustment'] == 0
    assert scoped['matching_assessment']['affinity_adjustment'] == 2
    assert scoped['score'] == unknown['score'] + 2
    invalid = deepcopy(mechanism)
    invalid['affinity_evidence'][0]['value'] = 'other-genre'
    with pytest.raises(KernelError, match='exact descriptive tag'):
        validate_craft_mechanism(invalid)
    invalid = deepcopy(mechanism)
    invalid['effect_evidence'] = []
    with pytest.raises(KernelError, match='governed effect evidence'):
        validate_craft_mechanism(invalid)


def test_optional_abstention_mandatory_dependencies_and_hard_conflicts_remain_protected():
    primary, dependency = deepcopy(core_catalog()[:2])
    primary['composition']['requires'] = [dependency['mechanism_id']]
    cards = (_card(primary), _card(dependency))
    assert select_narrative_intelligence(need({'genre':['xuanhuan']}), cards)['selected'] == []
    selected = select_narrative_intelligence(need({'genre':['xuanhuan']}, required_card_asset_version_ids=(cards[0]['asset_version_id'],)), cards)['selected']
    assert {item['knowledge_card_asset_version_id'] for item in selected} == {card['asset_version_id'] for card in cards}
    assert {item['craft_assessment']['selection_reason'] for item in selected} == {'AUTHOR_OR_PARENT_REQUIRED', 'REQUIRED_DEPENDENCY'}
    cards[0]['content']['abstract_content']['applicability_contract'] = {'schema_version':'knowledge-applicability.v1','usage_role':'MECHANISM', 'prerequisites': [], 'exceptions': [], 'hard_conflicts':[{'condition_id':'author-forbids','path':'/hard_constraints','operator':'CONTAINS','value':'禁止此方法'}]}
    with pytest.raises(KernelError, match='MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE'):
        select_narrative_intelligence(need({'writing_problem':[primary['narrative_problem']]}, required_card_asset_version_ids=(cards[0]['asset_version_id'],), hard_constraints=('禁止此方法',)), cards)
    primary['composition']['conflicting'] = [dependency['mechanism_id']]
    primary['composition']['requires'] = []
    conflict = select_narrative_intelligence(need({'writing_problem':[primary['narrative_problem'],dependency['narrative_problem']]}), (_card(primary),_card(dependency)))
    assert len(conflict['selected']) == 1
    assert any(item['reason']=='CRAFT_COMPOSITION_CONFLICT' for item in conflict['rejected'])


def test_signature_compatibility_preserves_frequency_and_feedback_without_label_penalty():
    mechanism = core_catalog()[0]
    row = _previous_craft_delivery(mechanism, chapter=5)
    row['mechanism_id'] = 'other-pattern'
    row['pattern_signature'] = craft_pattern_signature(mechanism, version=LEGACY_SIGNATURE)
    context = {'writing_problem':[mechanism['narrative_problem']], 'chapter_number':7}
    unknown = assess(mechanism, context, recent_usage=[row])
    assert unknown['budget_assessment']['noncomparable_pattern_use_ids'] == [row['use_id']]
    assert unknown['budget_assessment']['pattern_similarity_penalty'] == 0
    row['semantic_pattern_signature'] = craft_pattern_signature(mechanism)
    comparable = assess(mechanism, context, recent_usage=[row])
    assert comparable['budget_assessment']['pattern_comparisons'][0]['similarity_percent'] == 100
    assert comparable['budget_assessment']['pattern_signature_version'] == SEMANTIC_SIGNATURE
    row.update(mechanism_id=mechanism['mechanism_id'], effect_status='FAILED')
    negative = assess(mechanism, context, recent_usage=[row])
    assert negative['budget_assessment']['realization_cautions'] == [row]
    assert negative['budget_assessment']['feedback_penalty'] > 0


def test_noncraft_selection_is_unchanged_between_selection_contracts():
    from tests.unit.test_mkaos_authority_domain import _planning_card
    cards = (_planning_card(0),)
    for version in (LEGACY_SELECTION, NEED_DRIVEN_SELECTION):
        result = select_narrative_intelligence(need({}, craft_selection_policy_version=version), cards)
        if version == LEGACY_SELECTION:
            baseline = result
        else:
            assert result['selected'] == baseline['selected']
            assert result['rejected'] == baseline['rejected']


def test_each_catalog_revision_preserves_real_semantics_and_has_mechanism_local_metadata():
    hashes = LEGACY['catalog_semantic_hashes']
    assert set(hashes) == {m['mechanism_id'] for m in core_catalog()}
    for mechanism in core_catalog():
        assert mechanism['version'] == 2
        assert craft_hash({k:v for k,v in mechanism.items() if k not in {'schema_version','version','affinity','affinity_evidence'}}) == hashes[mechanism['mechanism_id']]
        assert mechanism['affinity_evidence'] == []
        assert craft_candidate(mechanism)['selection_tags']['genre'] == []
    by_id = {m['mechanism_id']:m for m in core_catalog()}
    assert by_id['martial-intent-consequence']['affinity']['genre'] == ['wuxia','xuanhuan']
    assert by_id['indirect-mastery']['family'] == 'WUXIA_XUANHUAN'
    assert by_id['indirect-mastery']['affinity']['genre'] == []
    assert by_id['power-cost-shadow']['affinity']['genre'] == []
    assert by_id['attention-relay']['affinity']['pov'] == ['limited','first_person']
    assert by_id['intentional-gap']['affinity']['pov'] == []


def test_new_selection_of_v1_card_marks_downstream_metadata_without_rewriting_old_plan():
    from tests.unit.test_craft_selection import _candidate
    from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy
    from novel_forge.modules.chapter_authority.craft_execution import bind_craft_realization
    mechanism = next(m for m in LEGACY['mechanisms'] if m['mechanism_id']=='intentional-gap')
    cards = (_card(mechanism),)
    context = {'scene_goal':['省去说明'], 'genre':['xuanhuan'], 'pov':['first_person']}
    results = []
    for version in (LEGACY_SELECTION, NEED_DRIVEN_SELECTION):
        selection = select_narrative_intelligence(need(context, craft_selection_policy_version=version), cards)
        candidate = _candidate(selection)
        strategy = build_craft_strategy(candidate, selection)
        contract = {'slots':[{'slot_id':'slot-1','scene_id':'scene-1'}], 'voices':{}, 'craft_tasks':{'tasks':[{'slot_id':'slot-1'}]}}
        result = bind_craft_realization(contract, strategy, scenes=candidate['scene_plan'])
        assert strategy['uses'][0]['mechanism'] == mechanism
        results.append(result)
    assert 'metadata_boundary' not in results[0]['craft_tasks']
    assert 'not author requirements' in results[1]['craft_tasks']['metadata_boundary']


def test_concrete_reselection_keeps_predecessor_contract_and_does_not_add_new_legacy_scoring_dimensions():
    from novel_forge.modules.mkaos_authority.craft_matching import inherit_reselection_contract
    fresh = need({'scene_goal':['省去说明'], 'writing_problem':['only new input'], 'scene_demand':['new demand'], 'scene_type':['description']})
    legacy = inherit_reselection_contract(fresh, LEGACY['selections'][1])
    assert legacy.craft_selection_policy_version == LEGACY_SELECTION
    assert legacy.craft_context == {'scene_goal':['省去说明']}
    assert 'craft_selection_policy_version' not in legacy.to_dict()
    modern = inherit_reselection_contract(fresh, {'craft_selection_policy_version': NEED_DRIVEN_SELECTION})
    assert modern == fresh
    with pytest.raises(KernelError, match='Unknown frozen Craft selection'):
        inherit_reselection_contract(fresh, {'craft_selection_policy_version':'unsupported-policy'})


def test_draft_card_projection_neutralizes_legacy_tags_only_for_new_adopted_contract():
    from novel_forge.modules.production_preparation.contracts import ResolvedProductionAsset
    from novel_forge.modules.production_preparation.service import ProductionPreparationService
    mechanism = LEGACY['mechanisms'][0]
    content = {'abstract_content':craft_candidate(mechanism)}
    frozen = deepcopy(content)
    card = ResolvedProductionAsset(project_id='p',asset_id='card',asset_version_id='card:v1',asset_type='knowledge_card',content_hash=craft_hash(content),
        content=content,qualification='ELIGIBLE',selected_reason='exact frozen card')
    summaries = []
    for projection in (None, {'craft_metadata_boundary':'Affinity is descriptive, not an author requirement'}):
        candidate = ProductionPreparationService._context_candidate(card,evidence_only_types=(),task_narrative_projection={},
            chapter=1,book_id='b',accepted_boundary={},knowledge_projection=projection)
        summaries.append(json.loads(candidate['safe_summary']))
    assert summaries[0]['selection_tags']['genre'] == ['wuxia','xuanhuan','chinese_serial']
    assert summaries[1]['selection_tags']['genre'] == []
    assert summaries[1]['selection_tags']['conflict'] == []
    assert summaries[0]['craft_mechanism'] == summaries[1]['craft_mechanism'] == mechanism
    assert content == frozen


def test_affinity_evidence_is_not_structural_or_model_judgment_and_is_semantically_bound():
    from novel_forge.modules.mkaos_authority.craft import craft_semantic_hash
    mechanism = core_catalog()[0]
    metadata = deepcopy(mechanism)
    metadata.update(name='A renamed descriptive label', version=3, family='PROSE')
    metadata['affinity']['genre'] = ['romance']
    assert craft_semantic_hash(metadata) == craft_semantic_hash(mechanism)
    metadata['prerequisites'].append('A new necessary knowledge condition')
    assert craft_semantic_hash(metadata) != craft_semantic_hash(mechanism)
    for kind in ('STRUCTURAL','MODEL_JUDGMENT'):
        candidate = deepcopy(mechanism)
        candidate['effect_evidence'] = [{'kind':kind, 'asset_version_id':'evidence:v1', 'claim':'An unsupported affinity assertion'}]
        candidate['affinity_evidence'] = [{'dimension':'scene_type','value':candidate['affinity']['scene_type'][0],'asset_version_id':'evidence:v1'}]
        with pytest.raises(KernelError, match='governed effect evidence'):
            validate_craft_mechanism(candidate)
