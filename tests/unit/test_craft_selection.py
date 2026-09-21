from copy import deepcopy
from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import core_catalog, craft_candidate, craft_hash
from novel_forge.modules.mkaos_authority.craft_selection import (
    build_craft_strategy,
    craft_candidate_assessment,
    craft_pattern_signature,
    validate_craft_policy,
    validate_craft_strategy,
)
from novel_forge.modules.mkaos_authority.domain import NarrativeIntelligenceNeed, select_narrative_intelligence
from novel_forge.modules.story_planning_runtime.knowledge_translation import add_translation_contract, validate_knowledge_translations


def _card(mechanism):
    content = {"abstract_content": craft_candidate(mechanism)}
    return {"asset_version_id": "card:" + mechanism["mechanism_id"], "content_hash": craft_hash(content), "content": content}


def _need(**changes):
    return NarrativeIntelligenceNeed(scope="SCENE", target_stage="chapter_plan.generate", craft_context={"scene_goal": ["战斗攻防动作因果与空间位置锚定"], "genre": ["武侠"], "chapter_number": 7}, **changes)


def _selection(*identities):
    return select_narrative_intelligence(_need(), tuple(_card(mechanism) for mechanism in core_catalog() if mechanism["mechanism_id"] in identities))


def _candidate(selection):
    prose = "明确桥头位置与双方距离，格挡改变落脚点，付出代价后抢到离场机会。"
    candidate = {"scene_plan": [{"scene_id": "scene-1", "purpose": prose}], "knowledge_translations": []}
    for index, card in enumerate(selection["selected"]):
        candidate["knowledge_translations"].append({
            "knowledge_card_asset_version_id": card["knowledge_card_asset_version_id"], "content_hash": card["content_hash"], "decision": "ADAPT", "usage_role": "MECHANISM", "rationale": "只实现既定战斗目标。", "prerequisite_resolution": "双方距离可观察，读者已知出口；不泄露对手内心。", "use_sites": [{"target_pointer": "/scene_plan/0/purpose", "realization_excerpt": prose, "expected_application": "位置和代价支撑选择。", "preservation_requirements": ["保留既定胜负与人物知识边界。"], "verification_checks": ["定位正文中动作导致位置改变的证据。"], "craft_role": "PRIMARY" if index == 0 else "SECONDARY", "craft_sequence": index + 1, "intended_reader_effect": "读者可追踪战斗中的因果与空间。"}],
        })
    return candidate


def _rehash(strategy):
    strategy["strategy_digest"] = craft_hash({key: value for key, value in strategy.items() if key != "strategy_digest"})
    return strategy


def test_governed_catalog_retrieval_is_bounded_replay_stable_and_retains_exact_content():
    cards = tuple(_card(mechanism) for mechanism in core_catalog())
    selection = select_narrative_intelligence(_need(), cards)
    assert 1 <= len(selection["selected"]) <= 6
    assert len(selection["selected"]) + len(selection["rejected"]) == len(cards)
    assert select_narrative_intelligence(_need(), tuple(reversed(cards))) == selection
    originals = {card["asset_version_id"]: card for card in cards}
    for selected in selection["selected"]:
        assert selected["selected_content"]["craft_mechanism"] == originals[selected["knowledge_card_asset_version_id"]]["content"]["abstract_content"]["craft_mechanism"]
        assert selected["applicability_assessment"]["status"] == "UNKNOWN"
        assert selected["craft_assessment"]["match_reasons"]
    assert selection["craft_policy"]["classification"] == "CONFIGURABLE_POLICY"


def test_actual_receipts_have_numeric_window_deduplication_and_explicit_pattern_evidence():
    mechanism = core_catalog()[0]
    row = {"chapter": 6, "use_id": "u1", "scene_id": "scene-1", "mechanism_id": mechanism["mechanism_id"], "family": mechanism["family"], "role": "PRIMARY", "external_effect_id": "effect-1", "external_receipt_ids": ["receipt-1"], "pattern_signature": craft_pattern_signature(mechanism)}
    recent = [row, {**row, "external_effect_id": "effect-2"}, {**row, "use_id": "u2", "chapter": 2}, {**row, "use_id": "u3", "chapter": 9}, {**row, "use_id": "u4", "chapter": 5, "external_receipt_ids": []}, {**row, "use_id": "u5", "chapter": 5, "mechanism_id": "similar-pattern"}]
    policy = validate_craft_policy({"recent_chapter_window": 2})
    assessment = craft_candidate_assessment(mechanism, context={"scene_goal": [mechanism["narrative_problem"]], "chapter_number": 7}, recent_usage=recent, policy=policy)
    budget = assessment["budget_assessment"]
    assert assessment["rejection_reason"] == "CRAFT_COOLDOWN"
    assert budget["frequency"] == 1
    assert budget["salience_penalty"] == policy["salience_penalty"]
    assert len(budget["recent_usage"]) == 2
    assert budget["pattern_comparisons"] == [{"use_id": "u5", "chapter": 5, "method": "ABSTRACT_MECHANISM_AFFINITY_TERM_JACCARD", "similarity_percent": 100}]
    assert budget["pattern_similarity_penalty"] == policy["pattern_similarity_penalty"]


def test_parent_obligation_cannot_silently_bypass_frozen_frequency_policy():
    card = _card(core_catalog()[0])
    with pytest.raises(KernelError, match="MKAOS_REQUIRED_KNOWLEDGE_UNAVAILABLE"):
        select_narrative_intelligence(_need(required_card_asset_version_ids=(card["asset_version_id"],), craft_policy={"max_frequency_in_window": 0}), (card,))


def test_provider_planning_contract_and_derived_strategy_freeze_exact_card_use_sites():
    selection = _selection("spatial-anchor", "action-causal-relay")
    candidate = _candidate(selection)
    schema = add_translation_contract({"properties": {}, "required": []}, selection)
    site_contract = schema["properties"]["knowledge_translations"]["items"]["properties"]["use_sites"]["items"]
    assert {"craft_role", "craft_sequence", "intended_reader_effect"} <= set(site_contract["required"])
    validate_knowledge_translations(candidate, selection)
    strategy = build_craft_strategy(candidate, selection)
    assert len(strategy["uses"]) == 2
    assert strategy["composition"][0]["ordered_use_ids"] == [use["use_id"] for use in strategy["uses"]]
    assert build_craft_strategy(deepcopy(candidate), deepcopy(selection)) == strategy
    assert validate_craft_strategy(strategy, scenes=candidate["scene_plan"]) == strategy
    drift = deepcopy(strategy)
    drift["uses"][0]["mechanism"]["abstract_mechanism"] += "改变当前章计划。"
    with pytest.raises(KernelError, match="CRAFT_STRATEGY_DRIFT"):
        validate_craft_strategy(drift)
    with pytest.raises(KernelError, match="CRAFT_SCENE_DRIFT"):
        validate_craft_strategy(strategy, scenes=[{"scene_id": "another-scene"}])
    candidate["knowledge_translations"][0]["decision"] = "ADOPT"
    with pytest.raises(KernelError, match="PREREQUISITES_UNRESOLVED"):
        validate_knowledge_translations(candidate, selection)


def test_composition_conflict_density_dependency_and_scene_binding_fail_closed():
    selection = _selection("spatial-anchor", "action-causal-relay")
    candidate = _candidate(selection)
    strategy = build_craft_strategy(candidate, selection)
    for mutate, error in (
        (lambda value: value["policy"].update(max_uses_per_scene=1), "CRAFT_COMPOSITION_INVALID"),
        (lambda value: (value["uses"][1].update(role="PRIMARY"), value["uses"][1]["planning_use_site"].update(craft_role="PRIMARY")), "CRAFT_COMPOSITION_INVALID"),
        (lambda value: (value["uses"][1].update(sequence=value["uses"][0]["sequence"]), value["uses"][1]["planning_use_site"].update(craft_sequence=value["uses"][0]["sequence"])), "CRAFT_COMPOSITION_INVALID"),
        (lambda value: value["uses"][0]["mechanism"]["composition"].update(requires=["missing-mechanism"]), "CRAFT_COMPOSITION_CONFLICT"),
        (lambda value: value["uses"][1]["mechanism"]["composition"].update(precedes=[value["uses"][0]["mechanism_id"]]), "CRAFT_COMPOSITION_SEQUENCE"),
    ):
        changed = deepcopy(strategy)
        mutate(changed)
        with pytest.raises(KernelError, match=error):
            validate_craft_strategy(_rehash(changed))
    candidate["knowledge_translations"][0]["use_sites"][0]["target_pointer"] = "/objective"
    with pytest.raises(KernelError, match="CRAFT_USE_SITE_UNLOCATED"):
        build_craft_strategy(candidate, selection)
    hooks = tuple(_card(item) for item in core_catalog() if item["mechanism_id"] in {"unfinished-action-hook", "new-question-hook"})
    hooks[0]["content"]["abstract_content"]["craft_mechanism"]["composition"]["conflicting"] = [hooks[1]["content"]["abstract_content"]["craft_mechanism"]["mechanism_id"]]
    need = replace(_need(), craft_context={"reader_effect": [item["content"]["abstract_content"]["craft_mechanism"]["desired_reader_effect"] for item in hooks]})
    selection = select_narrative_intelligence(need, hooks)
    assert len(selection["selected"]) == 1
    assert any(item["reason"] == "CRAFT_COMPOSITION_CONFLICT" for item in selection["rejected"])


def test_chapter_plan_and_production_preparation_preserve_and_verify_the_exact_mechanism():
    from novel_forge.modules.chapter_authority.chapter_plan_views import normalize_authoritative_chapter_plan, build_draft_plan_view
    from novel_forge.modules.production_preparation.contracts import ProductionPreparationRequest, ResolvedProductionAsset
    from novel_forge.modules.production_preparation.service import ProductionPreparationService
    from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy

    selection = _selection("spatial-anchor")
    candidate = _candidate(selection)
    strategy = build_craft_strategy(candidate, selection)
    plan = {**candidate, "craft_strategy": strategy, "chapter": 1, "title": "桥头", "premise": "双方争夺出口。", "chapter_objective": "离开桥头", "scene_sequence": candidate["scene_plan"], "chapter_hook": "桥另一端有人等待。"}
    normalized, _ = normalize_authoritative_chapter_plan(project_id="p", expected_chapter=1, content=plan, asset_version_id="plan:v1", content_hash=craft_hash(plan))
    assert build_draft_plan_view(normalized)["craft_strategy"] == strategy
    selected = selection["selected"][0]
    mechanism = selected["selected_content"]["craft_mechanism"]
    card = ResolvedProductionAsset(project_id="p", asset_id="card", asset_version_id=selected["knowledge_card_asset_version_id"], asset_type="knowledge_card", content_hash=selected["content_hash"], content={"abstract_content": craft_candidate(mechanism)}, qualification="ELIGIBLE", selected_reason="exact frozen card")
    plan_asset = replace(card, asset_id="plan", asset_version_id="plan:v1", asset_type="chapter_plan", content=plan, content_hash=craft_hash(plan))
    service = ProductionPreparationService(object())
    request = ProductionPreparationRequest(project_id="p", workspace_id="w", book_id="b", chapter=1, stage="draft", idempotency_key="craft-proof")
    access = resolve_book_knowledge_access_policy(production_profile={}, project_id="p", book_id="b")
    blocked = []
    projection = service._bind_translated_knowledge(request=request, plan=plan_asset, selected_by_type={"chapter_plan": [plan_asset], "knowledge_card": [card]}, selections=[], rejections=[], blocked=blocked, knowledge_access=access)
    assert blocked == []
    assert projection[card.asset_version_id]["craft_uses"] == strategy["uses"]
    altered = deepcopy(card.content)
    altered["abstract_content"]["craft_mechanism"]["abstract_mechanism"] += "绕过世界规则。"
    blocked = []
    projection = service._bind_translated_knowledge(request=request, plan=plan_asset, selected_by_type={"chapter_plan": [plan_asset], "knowledge_card": [replace(card, content=altered)]}, selections=[], rejections=[], blocked=blocked, knowledge_access=access)
    assert not projection
    assert blocked[0]["code"] == "CRAFT_MECHANISM_DRIFT"


def test_craft_retrieval_prunes_private_prose_examples_and_uses_frozen_current_chapter():
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.execution import _planning_narrative_intelligence_need

    command = SimpleNamespace(generator_operation_name="chapter_plan.generate", arc_working_set={}, narrative_realization={"chapter_number": 7, "events": [{"actor_ref": "hero", "action": "在桥边向后撤步", "knowledge_boundary": {"actor_knows": ["出口在东"]}}]})
    inputs = [{"role": "character_cast", "content": {"characters": [{"character_id": "hero", "core_desire": "守住同伴", "voice_anchors": ["DO_NOT_COPY_CHARACTER_EXPRESSION"]}]}}, {"role": "creative_foundation", "content": {"style_profile": {"rhythm": "短句接力", "original_examples": ["DO_NOT_COPY_STYLE_EXPRESSION"]}, "private_planning": {"style_policy": "DO_NOT_SEND_PRIVATE_POLICY"}}}, {"role": "chapter_group_plan", "content": {"chapter_function_matrix": [{"chapter_number": 6, "objective": "PAST_SCOPE_SENTINEL"}, {"chapter_number": 7, "objective": "CURRENT_SCOPE_SENTINEL", "obligation_actions": [{"obligation_id": "promise:escape", "action": "ADVANCE"}]}, {"chapter_number": 8, "objective": "FUTURE_SCOPE_SENTINEL"}]}}]
    need = _planning_narrative_intelligence_need(command=command, selected_inputs=inputs, production_profile={})
    serialized = str(need.craft_context)
    assert "DO_NOT" not in serialized
    assert "PAST_SCOPE_SENTINEL" not in serialized and "FUTURE_SCOPE_SENTINEL" not in serialized
    assert "CURRENT_SCOPE_SENTINEL" in serialized and "在桥边向后撤步" in serialized
    assert need.craft_context["chapter_number"] == 7
    assert "hero" in need.craft_context["characters"]
    assert "出口在东" in need.craft_context["information"]
    assert "promise:escape" in need.craft_context["obligations"]


def test_multi_scene_strategy_and_rejections_keep_specific_sites_and_prevent_side_channel_content():
    selection = _selection("spatial-anchor", "action-causal-relay")
    candidate = _candidate(selection)
    candidate["scene_plan"].append({"scene_id": "scene-2", "purpose": "离开桥头后才回头查看追兵方位，延续已发生的代价。"})
    site = candidate["knowledge_translations"][1]["use_sites"][0]
    site.update(target_pointer="/scene_plan/1/purpose", realization_excerpt=candidate["scene_plan"][1]["purpose"], craft_role="PRIMARY", craft_sequence=1)
    strategy = build_craft_strategy(candidate, selection)
    assert {item["scene_id"] for item in strategy["composition"]} == {"scene-1", "scene-2"}
    assert all(len(item["ordered_use_ids"]) == 1 for item in strategy["composition"])
    changed = deepcopy(strategy)
    changed["uses"][0]["source_excerpt"] = "An unauthorized source quotation."
    with pytest.raises(KernelError, match="CRAFT_USE_INVALID"):
        validate_craft_strategy(_rehash(changed))
    changed = deepcopy(strategy)
    changed["uses"][0]["preservation_requirements"] = ["Only preserve technique names"]
    with pytest.raises(KernelError, match="CRAFT_PRESERVATION_DRIFT"):
        validate_craft_strategy(_rehash(changed))
    candidate["knowledge_translations"][1].update(decision="REJECT", use_sites=[], rationale="The second scene no longer needs this mechanism.")
    revised = build_craft_strategy(candidate, selection)
    assert len(revised["uses"]) == 1
    assert candidate["knowledge_translations"][1]["rationale"]


def test_frozen_craft_budget_does_not_fill_from_changed_runtime_defaults(monkeypatch):
    from novel_forge.modules.mkaos_authority import craft_selection

    selection = _selection("spatial-anchor")
    candidate = _candidate(selection)
    before = build_craft_strategy(candidate, selection)
    monkeypatch.setitem(craft_selection.DEFAULT_CRAFT_POLICY, "max_uses_per_scene", 1)
    assert build_craft_strategy(candidate, selection) == before
    changed = deepcopy(before)
    del changed["policy"]["max_uses_per_scene"]
    with pytest.raises(KernelError, match="CRAFT_FROZEN_POLICY_MISSING"):
        validate_craft_strategy(_rehash(changed))
    del selection["craft_policy"]
    with pytest.raises(KernelError, match="CRAFT_FROZEN_POLICY_MISSING"):
        build_craft_strategy(candidate, selection)


def _previous_craft_delivery(mechanism, *, chapter=6, use_id='previous-use'):
    return {'chapter': chapter, 'use_id': use_id, 'scene_id': 'previous-scene',
        'mechanism_id': mechanism['mechanism_id'], 'family': mechanism['family'], 'role': 'PRIMARY',
        'external_effect_id': 'fixture-effect:' + use_id, 'external_receipt_ids': ['fixture-receipt:' + use_id],
        'pattern_signature': craft_pattern_signature(mechanism)}


def test_opt_in_v2_continuous_spatial_need_survives_consecutive_chapter_cooldown():
    mechanism = next(item for item in core_catalog() if item['mechanism_id'] == 'spatial-anchor')
    context = {'scene_goal': ['交战位置与通路难以想象，必须再次交代出口和两人之间的距离'], 'chapter_number': 7}
    previous = [_previous_craft_delivery(mechanism)]
    v1 = craft_candidate_assessment(mechanism, context=context, recent_usage=previous, policy=validate_craft_policy())
    assert v1['rejection_reason'] == 'CRAFT_COOLDOWN'
    v2 = craft_candidate_assessment(mechanism, context=context, recent_usage=previous,
        policy=validate_craft_policy({'schema_version': 'narrative-craft-budget.v2'}))
    assert v2['rejection_reason'] == ''
    assert v2['budget_assessment']['cadence_class'] == 'CONTINUOUS'
    assert v2['budget_assessment']['policy_version'] == 'narrative-craft-budget.v2'
    assert v2['budget_assessment']['in_cooldown'] is True
    assert v2['budget_assessment']['temporal_budget_applied'] is False
    assert v2['budget_assessment']['evidence_ceiling'] == 'DELIVERY_OBSERVATION_NOT_READER_EFFECT'
    assert validate_craft_policy()['schema_version'] == 'narrative-craft-budget.v1'


def test_v2_keeps_expressive_cooldown_frequency_context_and_strategy_guards():
    spatial = next(item for item in core_catalog() if item['mechanism_id'] == 'spatial-anchor')
    expressive = next(item for item in core_catalog() if item['mechanism_id'] == 'choice-exposes-value')
    policy = validate_craft_policy({'schema_version': 'narrative-craft-budget.v2'})
    with pytest.raises(KernelError, match='CRAFT_POLICY_INVALID'):
        validate_craft_policy({**policy, 'mechanism_cadence': {**policy['mechanism_cadence'], 'choice-exposes-value': 'CONTINUOUS'}})
    recent = [_previous_craft_delivery(spatial, chapter=chapter, use_id=str(chapter)) for chapter in (3, 4, 5)]
    assessment = craft_candidate_assessment(spatial, context={'scene_goal': [spatial['narrative_problem']], 'chapter_number': 7}, recent_usage=recent, policy=policy)
    assert assessment['rejection_reason'] == ''
    assert assessment['budget_assessment']['frequency'] == policy['max_frequency_in_window']
    no_match = craft_candidate_assessment(spatial, context={'scene_goal': ['cook cake'], 'chapter_number': 7}, recent_usage=recent, policy=policy)
    assert no_match['rejection_reason'] == 'CRAFT_NO_CONTEXT_MATCH'
    held = craft_candidate_assessment(expressive, context={'scene_goal': [expressive['narrative_problem']], 'chapter_number': 7}, recent_usage=[_previous_craft_delivery(expressive)], policy=policy)
    assert held['rejection_reason'] == 'CRAFT_COOLDOWN'
    assert held['budget_assessment']['cadence_class'] == 'EXPRESSIVE'
    card = _card(spatial)
    selection = select_narrative_intelligence(_need(craft_policy=policy, recent_craft_usage=tuple(recent)), (card,))
    candidate = _candidate(selection)
    strategy = build_craft_strategy(candidate, selection)
    assert strategy['policy'] == policy
    assert validate_craft_strategy(strategy, scenes=candidate['scene_plan']) == strategy
    selection_without_policy = deepcopy(selection)
    del selection_without_policy['craft_policy']['mechanism_cadence']
    with pytest.raises(KernelError, match='CRAFT_FROZEN_POLICY_MISSING'):
        build_craft_strategy(candidate, selection_without_policy)
    damaged = deepcopy(strategy)
    del damaged['policy']['mechanism_cadence']
    with pytest.raises(KernelError, match='CRAFT_FROZEN_POLICY_MISSING'):
        validate_craft_strategy(_rehash(damaged))
    crowded = deepcopy(strategy)
    crowded['uses'].append({**deepcopy(crowded['uses'][0]), 'use_id': 'second-same-mechanism', 'role': 'SECONDARY', 'sequence': 2})
    with pytest.raises(KernelError):
        validate_craft_strategy(_rehash(crowded))
