from copy import deepcopy
from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy, validate_craft_policy, validate_craft_strategy
from novel_forge.modules.mkaos_authority.craft_reselection import next_reselection_context, validate_concrete_selection
from novel_forge.modules.mkaos_authority.craft_solver import solve_candidates
from novel_forge.modules.mkaos_authority.craft_usage import realized_instances
from novel_forge.modules.mkaos_authority.domain import select_narrative_intelligence
from novel_forge.modules.mkaos_authority.runtime_usage import _continuing_usage
from novel_forge.modules.story_planning_runtime.knowledge_translation import add_translation_contract
from tests.unit.test_craft_selection import _card, _need
from tests.unit.test_craft_solver import card, names
from tests.unit.test_craft_usage import _typed_candidate, accepted


def selection(history=(), scope='arc:bridge', scope_transitions=(), **changes):
    mechanism = card('continuing-mechanism')['selected_content']['craft_mechanism']
    policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v4',
        'mechanism_usage_types': {'continuing-mechanism': 'staged'}, **changes})
    return select_narrative_intelligence(replace(_need(), craft_policy=policy, recent_craft_usage=history,
        craft_context={'scene_goal': [mechanism['narrative_problem']], 'chapter_number': 7,
            'usage_scope_context': {'project_id': 'project', 'book_id': 'book', 'chapter_number': 7,
                'arc_plan_version_ids': [scope], 'scope_transitions': list(scope_transitions)}}), (_card(mechanism),))


def strategy(selected, *, action='START', phase='SETUP', previous=None):
    candidate = _typed_candidate(selected)
    candidate['knowledge_translations'][0]['use_sites'][0]['craft_usage'] = {
        'instance_id': previous['usage']['instance_id'] if previous else '',
        'predecessor_use_id': previous['use_id'] if previous else '', 'phase': phase,
        'scope_id': selected['need']['craft_context']['usage_scope_context']['arc_plan_version_ids'][0],
        'transition': {'action': action, 'condition': '人物仍须偿还已接纳的承诺；此处以行动保留线索。', 'progress': '同阶段新增可见代价，暂不兑现。'}}
    return build_craft_strategy(candidate, selected)


def realized(value, chapter=4, status='SUPPORTED', **changes):
    use = value['uses'][0]
    return accepted(value, chapter=chapter, phase_transition={'action': use['usage']['transition']['action'],
        'phase': use['usage']['phase'], 'status': status, 'progress': '接纳正文中的承诺得到延续。',
        'evidence': {'start': 0, 'end': 8, 'quote': '人物留下偿还承诺'}, 'reason': '定位行动支持该阶段处置。'}, **changes)


def test_new_explicit_policy_does_not_reinterpret_legacy_and_preserves_planned_status():
    from tests.unit.test_craft_usage import selection as legacy_selection, strategy as legacy_strategy
    legacy = legacy_strategy(legacy_selection('staged'), phase='SETUP')
    value = strategy(selection())
    assert value['schema_version'] == 'narrative-craft-strategy.v3'
    assert value['uses'][0]['usage']['status'] == 'PLANNED'
    assert validate_craft_strategy(value) == value
    assert validate_craft_strategy(legacy) == legacy
    schema = add_translation_contract({'properties': {}, 'required': []}, selection())
    site = schema['properties']['knowledge_translations']['items']['properties']['use_sites']['items']
    assert 'transition' in site['properties']['craft_usage']['required']
    assert {'rejected_scene_ids', 'failure_condition'} <= set(schema['properties']['knowledge_translations']['items']['required'])


def test_same_phase_continue_defer_advance_and_explicit_end_do_not_force_chapter_progress():
    start = realized(strategy(selection()), chapter=2)
    continued = strategy(selection((start,)), previous=start, action='CONTINUE')
    current = realized(continued, chapter=3)
    assert current['usage']['instance_id'] == start['usage']['instance_id']
    assert current['usage']['phase'] == 'SETUP'
    deferred = realized(strategy(selection((start, current)), previous=current, action='DEFER'), chapter=4)
    assert deferred['usage']['phase'] == 'SETUP'
    advanced = realized(strategy(selection((deferred,)), previous=deferred, action='ADVANCE', phase='DEVELOPMENT'), chapter=5)
    assert advanced['usage']['phase'] == 'DEVELOPMENT'
    ended = realized(strategy(selection((advanced,)), previous=advanced, action='END', phase='DEVELOPMENT'), chapter=6)
    assert _continuing_usage([ended, advanced, deferred, current, start], set()) == []
    with pytest.raises(KernelError):
        strategy(selection((ended,), cooldown_chapters=0), previous=ended, action='CONTINUE', phase='DEVELOPMENT')
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selection((start,)), previous=start, action='CONTINUE', phase='DEVELOPMENT')
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selection((start,)), previous=start, action='ADVANCE', phase='PAYOFF')


def test_final_phase_can_continue_until_explicit_closure():
    start = realized(strategy(selection()), chapter=2)
    development = realized(strategy(selection((start,)), previous=start, action='ADVANCE', phase='DEVELOPMENT'), chapter=3)
    payoff = realized(strategy(selection((development,)), previous=development, action='ADVANCE', phase='PAYOFF'), chapter=4)
    continued = strategy(selection((payoff,)), previous=payoff, action='CONTINUE', phase='PAYOFF')
    assert continued['uses'][0]['usage']['accepted_predecessor']['use_id'] == payoff['use_id']
    assert _continuing_usage([payoff, development, start], set()) == [payoff]


def test_effect_success_cannot_substitute_for_located_phase_judgment():
    start = realized(strategy(selection()), chapter=2)
    proposed = strategy(selection((start,)), previous=start, action='ADVANCE', phase='DEVELOPMENT')
    uncertain = realized(proposed, chapter=4, status='UNCERTAIN')
    assert realized_instances([start, uncertain], start['usage']['type_policy']) == {}
    assert _continuing_usage([uncertain, start], set()) == [uncertain, start]
    with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
        strategy(selection((start, uncertain)), previous=start, action='ADVANCE', phase='DEVELOPMENT')
    failed = realized(proposed, chapter=4, status='FAILED')
    retry = strategy(selection((start, failed)), previous=start, action='ADVANCE', phase='DEVELOPMENT')
    assert retry['uses'][0]['usage']['accepted_predecessor']['use_id'] == start['use_id']


def test_rebind_requires_exact_approved_scope_and_accepted_predecessor():
    from novel_forge.modules.mkaos_authority.craft_scope import freeze_scope_dispositions
    start = realized(strategy(selection()), chapter=2)
    transition = freeze_scope_dispositions(evidence={'craft_scope_dispositions': [{
        'instance_id': start['usage']['instance_id'], 'knowledge_card_asset_version_id': start['knowledge_card_asset_version_id'],
        'content_hash': start['content_hash'], 'predecessor_use_id': start['use_id'], 'acceptance_id': start['acceptance_id'],
        'action': 'REBIND', 'reason': '批准未来轨迹换版，已接纳承诺和阶段保持不变。'}]},
        project_id='project', book_id='book', old_scope='arc:bridge', new_scope='arc:new', proposal_id='proposal',
        decision_asset_version_id='decision:v1', decision_content_hash='sha256:decision', activation_operation_id='activation')
    rebound = strategy(selection((start,), scope='arc:new', scope_transitions=transition), previous=start, action='CONTINUE')
    usage = rebound['uses'][0]['usage']
    assert usage['scope_transition'] == transition[0]
    assert usage['accepted_predecessor']['usage']['scope_id'] == 'arc:bridge'
    assert usage['scope_id'] == 'arc:new'
    assert validate_craft_strategy(rebound) == rebound
    for key, value in [('action', 'END'), ('predecessor_use_id', 'invented'), ('acceptance_id', 'other')]:
        changed = [{**transition[0], key: value}]
        with pytest.raises(KernelError, match='CRAFT_PHASE_PREDECESSOR_UNAVAILABLE'):
            strategy(selection((start,), scope='arc:new', scope_transitions=changed, cooldown_chapters=0), previous=start, action='CONTINUE')


def rejection_source(selected, *, scenes=None, identity=None, version='failure:1'):
    candidate = _typed_candidate(selected)
    candidate['scene_plan'] = scenes or candidate['scene_plan']
    translation = candidate['knowledge_translations'][0]
    translation.update(decision='REJECT', use_sites=[], rejected_scene_ids=[candidate['scene_plan'][0]['scene_id']], failure_condition='该场景没有可供人物选择的行动空间。')
    if identity:
        translation['knowledge_card_asset_version_id'] = identity
    return {'asset_version_id': version, 'content_hash': 'sha256:failure', 'source_operation_id': 'operation:1',
        'raw_result': candidate, 'diagnostic': {'error_code': 'CRAFT_CONCRETE_REJECTED'},
        'execution_evidence': {'external_receipt_ref': 'effect:1', 'usage_receipt_ref': 'usage:1', 'cost_receipt_ref': 'cost:1'}}


def test_rejection_is_scoped_versioned_and_not_a_transport_retry():
    selected = selection()
    source = rejection_source(selected)
    original = deepcopy(selected)
    with pytest.raises(KernelError, match='CRAFT_CONCRETE_REJECTED'):
        validate_concrete_selection(source['raw_result'], selected)
    state = next_reselection_context(selection=selected, source=source, task_identity='frozen-task')
    assert selected == original
    assert state['history'][0]['failure_class'] == 'BUSINESS_REJECT'
    assert state['history'][0]['execution_evidence']['external_receipt_ref'] == 'effect:1'
    assert state['exclusions'][0]['knowledge_card_asset_version_id'] == selected['selected'][0]['knowledge_card_asset_version_id']
    next_selection = deepcopy(selected)
    next_selection['need']['craft_context']['reselection'] = state
    with pytest.raises(KernelError, match='CRAFT_RESELECTION_CYCLE_DETECTED'):
        next_reselection_context(selection=next_selection, source=source, task_identity='frozen-task')
    with pytest.raises(KernelError, match='CRAFT_RESELECTION_TASK_DRIFT'):
        next_reselection_context(selection=next_selection, source=source, task_identity='other-task')
    contract_failure = {**source, 'diagnostic': {'error_code': 'CRAFT_COMPOSITION_SEQUENCE'}}
    assert next_reselection_context(selection=next_selection, source=contract_failure, task_identity='frozen-task') == state


def test_concrete_solver_preserves_shared_dependencies_and_repositions_required_card():
    pool = [card('first', requires=['base']), card('second', requires=['base']), card('base', dependency_only=True), card('fallback')]
    scope = {'scene_ids': ['scene:one', 'scene:two'], 'exclusions': [{
        'knowledge_card_asset_version_id': 'card:first', 'content_hash': 'sha256:test', 'scene_ids': ['scene:one']} ]}
    policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v4', 'max_uses_per_scene': 2})
    selected, _ = solve_candidates(pool, required_ids={'card:first'}, limit=4, policy=policy, placement_scope=scope)
    assert names(selected) == ['first', 'second', 'base']
    scope['exclusions'][0]['scene_ids'].append('scene:two')
    with pytest.raises(KernelError, match='CRAFT_CONCRETE_PLACEMENT_INFEASIBLE'):
        solve_candidates(pool, required_ids={'card:first'}, limit=4, policy=policy, placement_scope=scope)
    selected, _ = solve_candidates(pool, required_ids=set(), limit=4, policy=policy, placement_scope=scope)
    assert names(selected) == ['second', 'base', 'fallback']
    scope['exclusions'].append({'knowledge_card_asset_version_id': 'card:second', 'content_hash': 'sha256:test', 'scene_ids': scope['scene_ids']})
    selected, _ = solve_candidates(pool, required_ids=set(), limit=4, policy=policy, placement_scope=scope)
    assert names(selected) == ['fallback']
    with pytest.raises(KernelError, match='CRAFT_SEARCH_BUDGET_EXHAUSTED'):
        solve_candidates(pool, required_ids=set(), limit=4, policy=policy, placement_scope=scope, search_budget=1)


def test_scene_exclusions_cannot_be_evaded_by_new_provider_placement_or_scene_ids():
    selected = selection()
    source = rejection_source(selected)
    selected['need']['craft_context']['reselection'] = next_reselection_context(selection=selected, source=source, task_identity='task')
    candidate = _typed_candidate(selected)
    with pytest.raises(KernelError, match='CRAFT_RESELECTION_EXCLUDED_SITE'):
        validate_concrete_selection(candidate, selected)
    candidate['scene_plan'][0]['scene_id'] = 'invented-scene'
    with pytest.raises(KernelError, match='CRAFT_RESELECTION_SCENE_DRIFT'):
        validate_concrete_selection(candidate, selected)


def test_phase_review_requires_separate_located_evidence_even_when_effect_is_achieved():
    from novel_forge.modules.review.craft import SIDE_EFFECTS, validate_craft_checks, extend_craft_provider_schema
    value = strategy(selection())
    use = value['uses'][0]
    prose = '陆衡把最后一枚返程木牌交给守门人，仍未说出师门密道的位置。'
    location = {'start': 0, 'end': len(prose), 'quote': prose}
    target = {**use, 'selection_digest': value['selection_digest'], 'scene_ranges': [location]}
    check = {'use_id': use['use_id'], 'effect_status': 'ACHIEVED', 'reason': '可见行动符合预期效果。',
        'signals_checked': ['木牌交付是有代价的选择。'], 'issue_codes': [], 'evidence': location,
        'side_effects': [{'kind': kind, 'status': 'CLEAR', 'reason': '未观察到该项副作用。', 'issue_codes': [], 'evidence': location} for kind in SIDE_EFFECTS]}
    kwargs = dict(targets=[target], issues=[], text=prose, target_asset_version_id='draft:v1', real_model_call=False)
    with pytest.raises(KernelError, match='CRAFT_PHASE_REVIEW_REQUIRED'):
        validate_craft_checks(checks=[check], **kwargs)
    check['phase_transition'] = {'action': 'START', 'phase': 'SETUP', 'status': 'UNCERTAIN', 'progress': '保留了承诺，但动机证据仍不足。', 'evidence': location, 'reason': '效果成立不表示阶段条件已满足。'}
    normalized = validate_craft_checks(checks=[check], **kwargs)[0]
    assert normalized['phase_transition']['status'] == 'UNCERTAIN'
    assert normalized['effect_status'] == 'ACHIEVED'
    check['phase_transition']['phase'] = 'PAYOFF'
    with pytest.raises(KernelError, match='CRAFT_PHASE_REVIEW_REQUIRED'):
        validate_craft_checks(checks=[check], **kwargs)
    schema = extend_craft_provider_schema({'properties': {}, 'required': []}, 'review', phase_transitions=True)
    assert 'phase_transition' in schema['properties']['craft_checks']['items']['required']


def test_reselection_attempt_budget_is_explicit_and_preserves_alternating_failures():
    selected = selection()
    source = rejection_source(selected)
    state = next_reselection_context(selection=selected, source=source, task_identity='task')
    selected['need']['craft_context']['reselection'] = state
    alternative = deepcopy(source)
    alternative['asset_version_id'] = 'failure:2'
    alternative['raw_result']['knowledge_translations'][0]['failure_condition'] = '当前视角无法合法观察该行动的代价。'
    second = next_reselection_context(selection=selected, source=alternative, task_identity='task')
    assert len(second['history']) == 2
    assert second['history'][0] == state['history'][0]
    selected['need']['craft_context']['reselection'] = second
    with pytest.raises(KernelError, match='CRAFT_RESELECTION_BUDGET_EXHAUSTED'):
        next_reselection_context(selection=selected, source=source, task_identity='task')


def test_concrete_search_matches_exhaustive_scene_assignment_oracle():
    from itertools import combinations, product
    import random

    rng = random.Random(270927)
    for _ in range(80):
        size = rng.randint(2, 5)
        labels = [f'mechanism-{index}' for index in range(size)]
        pool = [card(label, requires=[other for other in labels if other != label and rng.random() < .13],
                     conflicts=[other for other in labels if other != label and rng.random() < .09]) for label in labels]
        excluded = {scene: {i for i in range(size) if rng.random() < .3} for scene in ('scene:a', 'scene:b')}
        required = {i for i in range(size) if rng.random() < .2}
        limit = rng.randint(1, size)
        policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v4', 'max_uses_per_scene': 2, 'max_uses_per_chapter': 3})
        scope = {'scene_ids': list(excluded), 'exclusions': [
            {'knowledge_card_asset_version_id': 'card:' + labels[i], 'content_hash': 'sha256:test', 'scene_ids': [scene]}
            for scene, indexes in excluded.items() for i in indexes]}
        feasible = []
        for count in range(limit + 1):
            for indexes in combinations(range(size), count):
                chosen = set(indexes)
                if not required <= chosen:
                    continue
                chosen_names = {labels[i] for i in indexes}
                if any(set(pool[i]['selected_content']['craft_mechanism']['composition']['conflicting']) & chosen_names for i in indexes):
                    continue
                placements = []
                for scene in excluded:
                    groups = [set(group) for group_size in range(min(2, count) + 1) for group in combinations(indexes, group_size)]
                    placements.append([group for group in groups if not group & excluded[scene]
                        and all(set(pool[i]['selected_content']['craft_mechanism']['composition']['requires']) <= {labels[j] for j in group} for i in group)])
                if any(set.union(set(), *groups) == chosen and sum(map(len, groups)) <= 3 for groups in product(*placements)):
                    feasible.append(indexes)
        kwargs = dict(limit=limit, required_ids={'card:' + labels[i] for i in required}, policy=policy, placement_scope=scope)
        if not feasible:
            with pytest.raises(KernelError, match='CRAFT_CONCRETE_PLACEMENT_INFEASIBLE'):
                solve_candidates(pool, **kwargs)
        else:
            expected = max(feasible, key=lambda indexes: tuple(i in indexes for i in range(size)))
            selected, _ = solve_candidates(pool, **kwargs)
            assert names(selected) == [labels[i] for i in expected]


def test_scope_approval_checks_accepted_predecessor_without_reinterpreting_failed_uses(monkeypatch):
    from novel_forge.modules.mkaos_authority.craft_scope import validate_scope_transition_decision
    from novel_forge.modules.mkaos_authority import runtime_usage
    start = realized(strategy(selection()), chapter=2)
    advanced = realized(strategy(selection((start,)), previous=start, action='ADVANCE', phase='DEVELOPMENT'), chapter=3, status='FAILED')
    history = [advanced, start]
    monkeypatch.setattr(runtime_usage, 'list_accepted_craft_usage', lambda *args, **kwargs: history)
    proposal = {'project_id': 'project', 'book_id': 'book', 'proposal_id': 'proposal',
        'target_contract_type': 'ARC', 'target_asset_version_id': 'arc:bridge', 'proposed_asset_version_id': 'arc:next'}
    evidence = {'craft_scope_dispositions': [{'instance_id': start['usage']['instance_id'],
        'knowledge_card_asset_version_id': start['knowledge_card_asset_version_id'], 'content_hash': start['content_hash'],
        'predecessor_use_id': start['use_id'], 'acceptance_id': start['acceptance_id'], 'action': 'REBIND',
        'reason': '保留已接纳的阶段基础，失败尝试不作为阶段进展。'}]}
    validate_scope_transition_decision('isolated', proposal=proposal, evidence=evidence)
    uncertain = deepcopy(advanced)
    uncertain['phase_transition']['status'] = 'UNCERTAIN'
    history[:] = [uncertain, start]
    with pytest.raises(KernelError, match='CRAFT_SCOPE_ACCEPTED_PREDECESSOR_REQUIRED'):
        validate_scope_transition_decision('isolated', proposal=proposal, evidence=evidence)
    history[:] = [start]
    evidence['craft_scope_dispositions'][0]['predecessor_use_id'] = 'invented'
    with pytest.raises(KernelError, match='CRAFT_SCOPE_ACCEPTED_PREDECESSOR_REQUIRED'):
        validate_scope_transition_decision('isolated', proposal=proposal, evidence=evidence)


def test_rejected_immutable_planning_payload_retains_serializable_exact_result():
    from types import MappingProxyType
    from novel_forge.modules.story_planning_runtime.result_recovery import PlanningResultValidationError
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    selected = selection()
    raw = rejection_source(selected)['raw_result']
    error = PlanningResultValidationError(KernelError('CRAFT_CONCRETE_REJECTED', '场景拒绝'),
        raw_result=MappingProxyType(raw), execution_evidence={'external_receipt_ref': 'effect:1'})
    assert canonical_hash(error.raw_result) == canonical_hash(raw)
    assert error.diagnostic['failure_class'] == 'BUSINESS_REJECT'
    assert error.raw_result == raw


def test_protected_craft_projection_keeps_one_exact_full_copy_and_delivery_trace():
    import json
    from novel_forge.modules.context_builder.domain import ContextCandidate
    from novel_forge.modules.mkaos_authority.craft_context_projection import reference_duplicate_craft_uses, resolve_projected_craft_uses
    use = {"use_id": "use", "knowledge_card_asset_version_id": "card", "mechanism": {"description": "定向事实" * 500}}
    strategy = {"schema_version": "narrative-craft-strategy.v3", "strategy_digest": "digest", "uses": [use]}
    summary = {"craft_uses": [use], "craft_strategy_digest": "digest", "translation": {"knowledge_card_asset_version_id": "card"}}
    candidate = ContextCandidate(asset_version_id="card", asset_type="knowledge_card", project_id="p", book_id="b",
        estimated_tokens=1000, relevance_score=1, safe_summary=json.dumps(summary))
    compact = reference_duplicate_craft_uses([candidate], intent={"craft_strategy": strategy}, intent_asset_version_id="intent")[0]
    assert compact.estimated_tokens < candidate.estimated_tokens
    projected = json.loads(compact.safe_summary)
    assert "craft_uses" not in projected and candidate.safe_summary == json.dumps(summary)
    assert resolve_projected_craft_uses(projected, [{"asset_version_id": "intent", "safe_summary": json.dumps({"craft_strategy": strategy})}]) == [use]
    with pytest.raises(KernelError, match="PROJECTION_DRIFT"):
        resolve_projected_craft_uses(projected, [])

    drifted = replace(candidate, safe_summary=json.dumps({**summary, "craft_strategy_digest": "different"}))
    independent = reference_duplicate_craft_uses([drifted], intent={"craft_strategy": strategy}, intent_asset_version_id="intent")[0]
    independent_summary = json.loads(independent.safe_summary)
    assert independent_summary["craft_uses"] == [use]
    assert independent_summary["craft_strategy_digest"] == "different"
    assert "craft_uses_reference" not in independent_summary
    assert independent_summary["context_diagnostics"][0]["status"] == "DIAGNOSTIC_ONLY"
