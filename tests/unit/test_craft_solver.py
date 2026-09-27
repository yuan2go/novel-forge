from copy import deepcopy
from itertools import combinations
import random

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import core_catalog
from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_policy
from novel_forge.modules.mkaos_authority.craft_solver import solve_candidates
from novel_forge.modules.mkaos_authority.domain import select_narrative_intelligence
from tests.unit.test_craft_selection import _card, _need


def card(name, *, requires=(), conflicts=(), dependency_only=False):
    mechanism = deepcopy(core_catalog()[0])
    mechanism['mechanism_id'] = name
    mechanism['composition'] = dict(compatible=[], complementary=[], conflicting=list(conflicts), requires=list(requires), precedes=[])
    return dict(knowledge_card_asset_version_id='card:' + name, content_hash='sha256:test',
                selected_content=dict(craft_mechanism=mechanism), applicability_assessment=dict(status='UNKNOWN'),
                craft_assessment=dict(rejection_reason='CRAFT_NO_CONTEXT_MATCH' if dependency_only else ''))


def names(selected):
    return [item['selected_content']['craft_mechanism']['mechanism_id'] for item in selected]


def test_dependency_bundles_reserve_transitive_shared_capacity_and_refill():
    pool = [card('primary', requires=['support']), card('intruder'), card('support', requires=['base']), card('base')]
    chosen, _ = solve_candidates(pool, limit=3, required_ids={'card:primary'}, policy=validate_craft_policy())
    assert names(chosen) == ['primary', 'support', 'base']
    pool = [card('bad-root', requires=['missing']), card('primary', requires=['base']), card('other', requires=['base']), card('base', dependency_only=True)]
    chosen, rejected = solve_candidates(pool, limit=3, required_ids=set(), policy=validate_craft_policy())
    assert names(chosen) == ['primary', 'other', 'base']
    assert rejected[0]['reason'] == 'CRAFT_DEPENDENCY_UNAVAILABLE'


def test_required_alternative_can_displace_earlier_optional_conflict():
    pool = [card('tempting', conflicts=['required']), card('required'), card('alternative')]
    selected, _ = solve_candidates(pool, limit=2, required_ids={'card:required'}, policy=validate_craft_policy())
    assert names(selected) == ['required', 'alternative']


def test_orphan_dependencies_are_removed_even_when_they_form_a_cycle():
    pool = [card('unusable', requires=['missing', 'dependency']), card('dependency', requires=['cycle'], dependency_only=True), card('cycle', requires=['dependency'], dependency_only=True), card('replacement')]
    selected, _ = solve_candidates(pool, limit=3, required_ids=set(), policy=validate_craft_policy())
    assert names(selected) == ['replacement']


def test_infeasibility_and_exhausted_search_are_distinct_and_located():
    pool = [card('primary', requires=['support']), card('support')]
    with pytest.raises(KernelError, match='MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE.*card:primary.*capacity'):
        solve_candidates(pool, limit=1, required_ids={'card:primary'}, policy=validate_craft_policy())
    with pytest.raises(KernelError, match='CRAFT_SEARCH_BUDGET_EXHAUSTED'):
        solve_candidates(pool, limit=2, required_ids=set(), policy=validate_craft_policy(), search_budget=1)


def test_native_selection_keeps_contextless_dependency_but_enforces_its_cooldown():
    primary, support = card('primary', requires=['support']), card('support')
    mechanism = support['selected_content']['craft_mechanism']
    cards = tuple(_card(item['selected_content']['craft_mechanism']) for item in (primary, support))
    need = _need(required_card_asset_version_ids=('card:primary',))
    selected = select_narrative_intelligence(need, cards, limit=2)
    assert set(names(selected['selected'])) == {'primary', 'support'}
    from dataclasses import replace
    from tests.unit.test_craft_selection import _accepted_usage_binding
    usage = {'chapter': 6, 'use_id': 'prior', 'mechanism_id': mechanism['mechanism_id'], **_accepted_usage_binding()}
    with pytest.raises(KernelError, match='MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE'):
        select_narrative_intelligence(replace(need, recent_craft_usage=(usage,)), cards, limit=2)


def test_small_exhaustive_oracle_agrees_for_conflicts_dependencies_and_required_sets():
    rng = random.Random(260926)
    for _ in range(240):
        size = rng.randint(2, 7)
        labels = ['mechanism-' + str(i) for i in range(size)]
        pool = []
        for label in labels:
            deps = [other for other in labels if other != label and rng.random() < .16]
            conflicts = [other for other in labels if other != label and other not in deps and rng.random() < .13]
            pool.append(card(label, requires=deps, conflicts=conflicts))
        required = {i for i in range(size) if rng.random() < .2}
        limit = rng.randint(1, size)
        craft_limit = rng.randint(1, size)
        feasible = []
        for count in range(min(limit, craft_limit) + 1):
            for indexes in combinations(range(size), count):
                if not required <= set(indexes):
                    continue
                selected_names = {labels[i] for i in indexes}
                if all(set(pool[i]['selected_content']['craft_mechanism']['composition']['requires']) <= selected_names and not set(pool[i]['selected_content']['craft_mechanism']['composition']['conflicting']) & selected_names for i in indexes) and reference_realizable(pool, indexes):
                    feasible.append(indexes)
        policy = validate_craft_policy({'max_craft_candidates': craft_limit})
        kwargs = dict(limit=limit, required_ids={'card:' + labels[i] for i in required}, policy=policy)
        if not feasible:
            with pytest.raises(KernelError, match='MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE'):
                solve_candidates(pool, **kwargs)
            continue
        expected = max(feasible, key=lambda indexes: tuple(i in indexes for i in range(size)))
        selected, rejected = solve_candidates(pool, **kwargs)
        assert names(selected) == [labels[i] for i in expected]
        assert solve_candidates(deepcopy(pool), **kwargs) == (selected, rejected)


def reference_realizable(pool, indexes):
    states = {frozenset(): 0}
    bundles = []
    for size in range(1, min(3, len(indexes)) + 1):
        for group in combinations(indexes, size):
            group_names = {pool[i]['selected_content']['craft_mechanism']['mechanism_id'] for i in group}
            if all(set(pool[i]['selected_content']['craft_mechanism']['composition']['requires']) <= group_names for i in group):
                bundles.append(frozenset(group))
    for _ in indexes:
        for covered, cost in list(states.items()):
            for group in bundles:
                union = covered | group
                if cost + len(group) < states.get(union, 9):
                    states[union] = cost + len(group)
    return states.get(frozenset(indexes), 9) <= 8


def test_scene_density_and_precedence_failures_refill_with_realizable_alternative():
    pool = [card('primary', requires=['support']), card('support'), card('alternative')]
    policy = validate_craft_policy({'max_uses_per_scene': 1, 'max_uses_per_chapter': 1})
    chosen, _ = solve_candidates(pool, limit=2, required_ids=set(), policy=policy)
    assert names(chosen) == ['support']
    pool[1]['craft_assessment']['rejection_reason'] = 'CRAFT_NO_CONTEXT_MATCH'
    chosen, _ = solve_candidates(pool, limit=2, required_ids=set(), policy=policy)
    assert names(chosen) == ['alternative']
    policy = validate_craft_policy()
    pool[0]['selected_content']['craft_mechanism']['composition']['precedes'] = ['support']
    pool[1]['selected_content']['craft_mechanism']['composition']['precedes'] = ['primary']
    chosen, _ = solve_candidates(pool, limit=3, required_ids=set(), policy=policy)
    assert names(chosen) == ['alternative']


def test_dependency_reused_in_distinct_scenes_consumes_each_realization():
    pool = [card('first', requires=['base']), card('second', requires=['base']), card('base', dependency_only=True), card('alternative')]
    policy = validate_craft_policy({'max_uses_per_scene': 2, 'max_uses_per_chapter': 3})
    chosen, _ = solve_candidates(pool, limit=4, required_ids=set(), policy=policy)
    assert names(chosen) == ['first', 'base', 'alternative']


def test_repeated_dependency_realization_reserves_typed_frequency_in_selection():
    pool = [card('first', requires=['base']), card('second', requires=['base']), card('base', dependency_only=True)]
    policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v3', 'max_uses_per_scene': 2, 'max_uses_per_chapter': 4, 'max_frequency_in_window': 1})
    selected, _ = solve_candidates(pool, limit=3, required_ids=set(), policy=policy)
    assert names(selected) == ['first', 'base']
    pool[2]['craft_assessment']['budget_assessment'] = {'temporal_budget_applied': False}
    selected, _ = solve_candidates(pool, limit=3, required_ids=set(), policy=policy)
    assert names(selected) == ['first', 'second', 'base']
