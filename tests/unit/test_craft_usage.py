from copy import deepcopy
from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy, validate_craft_policy, validate_craft_strategy
from novel_forge.modules.mkaos_authority.domain import select_narrative_intelligence
from novel_forge.modules.story_planning_runtime.knowledge_translation import add_translation_contract
from tests.unit.test_craft_selection import _card, _need, _candidate, _accepted_usage_binding
from tests.unit.test_craft_solver import card


def selection(mode='support', history=(), **changes):
    mechanism = card('continuing-mechanism')['selected_content']['craft_mechanism']
    policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v3', 'mechanism_usage_types': {'continuing-mechanism': mode}, **changes})
    return select_narrative_intelligence(replace(_need(), craft_policy=policy, recent_craft_usage=history, craft_context={"scene_goal": [mechanism["narrative_problem"]], "chapter_number": 7, "usage_scope_context": {"project_id": "project", "book_id": "book", "chapter_number": 7, "arc_plan_version_ids": ["arc:bridge"]}}), (_card(mechanism),))


def _typed_candidate(selected):
    value = _candidate(selected)
    for translation in value['knowledge_translations']:
        for site in translation['use_sites']:
            site['craft_combination'] = dict(narrative_problem='场景选择缺乏可见代价。', selection_reason='用既定选择显露价值取向。', role_and_order_reason='选择先于后果；主技法承接既定转折。', combined_effect='读者从行动与代价理解动机。', interference_risk='过度解释会削弱行动含义。', preservation_constraint='保持视角、选择和结果。', abstain_condition='没有可见选择时不使用。')
    return value


def strategy(selected, phase='SUSTAIN', previous=None):
    candidate = _typed_candidate(selected)
    candidate['knowledge_translations'][0]['use_sites'][0]['craft_usage'] = dict(instance_id=previous['usage']['instance_id'] if previous else '', phase=phase,
        predecessor_use_id=previous['use_id'] if previous else '', scope_id='arc:bridge')
    return build_craft_strategy(candidate, selected)


def accepted(strategy, chapter=6, **changes):
    use = strategy['uses'][0]
    return {**use, 'chapter': chapter, **_accepted_usage_binding(), **changes}


def test_explicit_usage_policy_preserves_legacy_default_and_multiple_support_types():
    assert validate_craft_policy()['schema_version'] == 'narrative-craft-budget.v1'
    policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v3', 'mechanism_usage_types': {'spatial-anchor': 'support', 'attention-relay': 'support'}})
    assert len(policy['mechanism_usage_types']) == 2
    policy['usage_types']['support']['phases'].append('WRONG')
    with pytest.raises(KernelError, match='CRAFT_USAGE_POLICY_INVALID'):
        validate_craft_policy(policy)
    assert validate_craft_policy({'schema_version': 'narrative-craft-budget.v3'})['usage_types']['support']['phases'] == ['SUSTAIN']


def test_persistent_manifestations_reuse_instance_without_new_frequency_or_recursive_history():
    first = strategy(selection())
    use = accepted(first)
    next_selection = selection(history=(use,))
    assert len(next_selection['selected']) == 1
    next_strategy = strategy(next_selection, previous=use)
    assert next_strategy['schema_version'] == 'narrative-craft-strategy.v2'
    assert next_strategy['uses'][0]['usage']['instance_id'] == use['usage']['instance_id']
    assert validate_craft_strategy(next_strategy) == next_strategy
    assert 'accepted_predecessor' not in next_strategy['uses'][0]['usage']['accepted_predecessor']['usage']
    with pytest.raises(KernelError, match='CRAFT_USAGE_FREQUENCY_EXCEEDED'):
        strategy(next_selection)


def test_phases_need_latest_successful_accepted_predecessor_and_cannot_skip():
    setup = strategy(selection('staged'), phase='SETUP')
    old = accepted(setup)
    selected = selection('staged', history=(old,))
    next_strategy = strategy(selected, phase='DEVELOPMENT', previous=old)
    assert next_strategy['uses'][0]['usage']['phase'] == 'DEVELOPMENT'
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selected, phase='PAYOFF', previous=old)
    for mutation in ({'acceptance_id': ''}, {'effect_status': 'FAILED'}, {'effect_status': 'UNCERTAIN'}):
        bad = {**old, **mutation}
        selected_bad = selection('staged', history=(bad,))
        with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
            strategy(selected_bad, phase='DEVELOPMENT', previous=bad)


def test_typed_output_contract_and_old_frozen_strategies_are_distinct():
    selected = selection()
    schema = add_translation_contract({'properties': {}, 'required': []}, selected)
    site = schema['properties']['knowledge_translations']['items']['properties']['use_sites']['items']
    assert 'craft_usage' in site['required']
    value = strategy(selected)
    from tests.unit.test_craft_selection import _rehash
    value['schema_version'] = 'narrative-craft-strategy.v1'
    with pytest.raises(KernelError, match='CRAFT_POLICY_INVALID'):
        validate_craft_strategy(_rehash(value))


def test_two_scene_instances_are_not_collapsed_and_policy_input_is_not_mutated():
    selected = selection()
    before = deepcopy(selected)
    candidate = _typed_candidate(selected)
    candidate['scene_plan'].append({**candidate['scene_plan'][0], 'scene_id': 'scene-2'})
    sites = candidate['knowledge_translations'][0]['use_sites']
    sites[0]['craft_usage'] = dict(instance_id='', phase='SUSTAIN', predecessor_use_id='', scope_id='arc:bridge')
    sites.append({**deepcopy(sites[0]), 'target_pointer': '/scene_plan/1/purpose'})
    value = build_craft_strategy(candidate, selected)
    assert len({use['usage']['instance_id'] for use in value['uses']}) == 2
    assert selected == before


def test_current_plan_instances_jointly_consume_the_frequency_allowance():
    selected = selection(max_frequency_in_window=1)
    candidate = _typed_candidate(selected)
    candidate['scene_plan'].append({**candidate['scene_plan'][0], 'scene_id': 'scene-2'})
    sites = candidate['knowledge_translations'][0]['use_sites']
    sites[0]['craft_usage'] = dict(instance_id='', phase='SUSTAIN', predecessor_use_id='', scope_id='arc:bridge')
    sites.append({**deepcopy(sites[0]), 'target_pointer': '/scene_plan/1/purpose'})
    with pytest.raises(KernelError, match='CRAFT_USAGE_FREQUENCY_EXCEEDED'):
        build_craft_strategy(candidate, selected)


def test_failed_phase_does_not_advance_but_uncertainty_blocks_retry():
    setup = accepted(strategy(selection('staged'), phase='SETUP'), chapter=4)
    development = accepted(strategy(selection('staged', history=(setup,)), phase='DEVELOPMENT', previous=setup), chapter=6, effect_status='FAILED')
    retried = strategy(selection('staged', history=(setup, development)), phase='DEVELOPMENT', previous=setup)
    assert retried['uses'][0]['usage']['accepted_predecessor']['use_id'] == setup['use_id']
    uncertain = {**development, 'effect_status': 'UNCERTAIN'}
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selection('staged', history=(setup, uncertain)), phase='DEVELOPMENT', previous=setup)


def test_completed_instance_no_longer_bypasses_temporal_budget():
    setup = accepted(strategy(selection('staged'), phase='SETUP'), chapter=4)
    development = accepted(strategy(selection('staged', history=(setup,)), phase='DEVELOPMENT', previous=setup), chapter=5)
    payoff = accepted(strategy(selection('staged', history=(setup, development)), phase='PAYOFF', previous=development), chapter=6)
    selected = selection('staged', history=(setup, development, payoff))
    assert selected['selected'] == []
    assert selected['rejected'][0]['reason'] == 'CRAFT_COOLDOWN'


def test_scope_cannot_alias_another_book_arc_or_chapter():
    selected = selection()
    candidate = _typed_candidate(selected)
    candidate['knowledge_translations'][0]['use_sites'][0]['craft_usage'] = dict(instance_id='', phase='SUSTAIN', predecessor_use_id='', scope_id='invented-arc')
    with pytest.raises(KernelError, match='CRAFT_USAGE_SCOPE_DRIFT'):
        build_craft_strategy(candidate, selected)
    first = accepted(strategy(selected), chapter=4)
    first['usage']['scope_binding']['book_id'] = 'other-book'
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selection(history=(first,)), previous=first)


def test_history_retains_old_open_instances_and_uncertainty_without_reviving_payoffs():
    from novel_forge.modules.mkaos_authority.runtime_usage import _continuing_usage

    setup = accepted(strategy(selection('staged'), phase='SETUP'), chapter=4)
    development = accepted(strategy(selection('staged', history=(setup,)), phase='DEVELOPMENT', previous=setup), chapter=5)
    payoff = accepted(strategy(selection('staged', history=(setup, development)), phase='PAYOFF', previous=development), chapter=6)
    assert _continuing_usage([development, setup], set()) == [development]
    assert _continuing_usage([payoff, development, setup], set()) == []
    uncertain = {**development, 'effect_status': 'UNCERTAIN'}
    retained = _continuing_usage([uncertain, setup], set())
    assert retained == [uncertain, setup]
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selection('staged', history=retained), phase='DEVELOPMENT', previous=setup)
    assert _continuing_usage([payoff], {payoff['acceptance_id']}) == [payoff]


def test_continuing_neighbor_does_not_resurrect_an_already_completed_old_instance():
    from novel_forge.modules.mkaos_authority.runtime_usage import _continuing_usage

    staged = accepted(strategy(selection('staged'), phase='SETUP'), chapter=4)
    neighbor = accepted(strategy(selection()), chapter=4)
    neighbor['use_id'] = 'persistent-neighbor'
    neighbor['usage']['instance_id'] = 'neighbor-instance'
    identities = {(neighbor['acceptance_id'], neighbor['use_id'])}
    assert _continuing_usage([staged, neighbor], set(), identities) == [neighbor]
