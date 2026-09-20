from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.craft_execution import require_craft_delivery
from novel_forge.modules.chapter_authority.execution_artifacts import (
    build_chapter_execution_intent, qualify_chapter_memo, validate_chapter_memo,
)
from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
from novel_forge.modules.chapter_authority.realization_composition import (
    compile_realization_contract, integrate_realization,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import core_catalog
from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy, validate_craft_policy


def craft_plan():
    mechanism = next(item for item in core_catalog() if not item["composition"]["requires"])
    selection = {
        "craft_policy": validate_craft_policy({}),
        "selection_digest": "sha256:" + "a" * 64,
        "selected": [{"knowledge_card_asset_version_id": "card:original:v1",
                      "content_hash": "sha256:" + "b" * 64,
                      "selected_content": {"craft_mechanism": mechanism}}],
    }
    plan = {
        "chapter": 1, "objective": "追踪拦路者的手势并选择退路",
        "required_arc_contributions": [{"arc_plan_version_id": "arc:escape:v1"}],
        "scene_plan": [{"scene_id": "scene:gate", "goal": "追踪手势并选择退路",
                        "arc_progress": ["arc:escape:v1"], "participants": [],
                        "beats": [{"beat_id": "beat:hand", "function": "notice"}]}],
        "knowledge_translations": [{
            "knowledge_card_asset_version_id": "card:original:v1", "decision": "ADAPT",
            "content_hash": "sha256:" + "b" * 64, "usage_role": "MECHANISM",
            "rationale": "以手势和门闩连接当前退路目标，不增加事件。",
            "prerequisite_resolution": "本场景已有手势及可见退路，保留当前视点。",
            "use_sites": [{"target_pointer": "/scene_plan/0/goal",
                           "realization_excerpt": "追踪手势并选择退路",
                           "expected_application": "让注意力沿现有手势抵达既定退路",
                           "verification_checks": ["检查转移因果和视点内可见性"],
                           "preservation_requirements": ["不得改变退路可见性或新增武功"],
                           "craft_role": "PRIMARY", "craft_sequence": 1,
                           "intended_reader_effect": mechanism["desired_reader_effect"]}],
        }],
    }
    plan["craft_strategy"] = build_craft_strategy(plan, selection)
    return plan


def intent_and_memo(plan):
    intent = build_chapter_execution_intent(
        project_id="project:craft", operation_id="operation:intent",
        chapter_plan_asset_version_id="plan:v1", chapter_plan_content_hash="sha256:" + "c" * 64,
        chapter_plan=plan, accepted_inputs=(),
    )
    memo = qualify_chapter_memo(
        intent=intent, intent_asset_version_id="intent:v1",
        result={"execution_strategy": "承接手势", "tension_strategy": "保持方向可见",
                "scene_directives": [{"scene_id": "scene:gate"}], "retrieval_queries": ["gate"],
                "obligation_actions": [], "arc_actions": [{"arc_plan_version_id": "arc:escape:v1"}]},
        execution_evidence={"fixture_protocol_only": True},
    )
    return intent, memo


def test_adopted_strategy_reaches_memo_and_draft_task_without_catalog_injection():
    plan = craft_plan()
    intent, memo = intent_and_memo(plan)
    memo_task = build_provider_task_view("memo", {"execution_intent": intent})
    assert memo_task["frozen_intent"]["craft_strategy"] == plan["craft_strategy"]
    contract = compile_realization_contract(plan, {"policies": []})
    draft_task = build_provider_task_view("draft", {"plan": plan, "chapter_memo": memo, "realization_contract": contract})
    assert draft_task["realization_contract"]["craft_strategy"] == plan["craft_strategy"]
    assert contract["contract_version"] == "scene-realization-composition.v2"
    assert contract["craft_tasks"]["tasks"][0]["craft_use_ids"] == [plan["craft_strategy"]["uses"][0]["use_id"]]
    assert len(contract["craft_strategy"]["uses"]) == 1
    assert len(core_catalog()) >= 30
    assert memo["craft_strategy"] == intent["craft_strategy"] == plan["craft_strategy"]
    assert compile_realization_contract(deepcopy(plan), {"policies": []}) == contract
    prose = "他循着手势看去，门闩落在对方脚边。"
    candidate = integrate_realization(contract=contract, text=prose, artifacts=[{
        "slot_id": contract["slots"][0]["slot_id"], "text": prose, "used_fact_ids": [],
    }])
    assert candidate["realization_contract"]["craft_strategy"] == plan["craft_strategy"]


def test_draft_requires_exact_context_delivery_and_matching_memo():
    plan = craft_plan()
    intent, memo = intent_and_memo(plan)
    context = {"context_manifest": {"selected_inputs": [{
        "asset_version_id": "card:original:v1", "content_digest": "sha256:" + "b" * 64,
    }]}}
    require_craft_delivery(plan=plan, intent=intent, memo=memo, context=context)
    with pytest.raises(KernelError, match="CRAFT_CONTEXT_DELIVERY_MISSING"):
        require_craft_delivery(plan=plan, intent=intent, memo=memo, context={})
    changed = deepcopy(memo)
    changed.pop("craft_strategy")
    from novel_forge.modules.chapter_authority.execution_artifacts import _hash
    changed["memo_fingerprint"] = _hash({key: value for key, value in changed.items() if key != "memo_fingerprint"})
    with pytest.raises(KernelError, match="CRAFT_EXECUTION_BINDING_DRIFT"):
        require_craft_delivery(plan=plan, intent=intent, memo=changed, context=context)
    with pytest.raises(KernelError, match="CHAPTER_MEMO_CRAFT_DRIFT"):
        validate_chapter_memo(changed, intent=intent, intent_asset_version_id="intent:v1")


def test_scene_removal_and_strategy_tampering_fail_before_provider():
    plan = craft_plan()
    changed = deepcopy(plan)
    changed["scene_plan"][0]["scene_id"] = "unplanned"
    with pytest.raises(KernelError, match="CRAFT_SCENE_DRIFT"):
        compile_realization_contract(changed, {"policies": []})
    changed = deepcopy(plan)
    changed["craft_strategy"]["uses"][0]["intended_reader_effect"] = "自行改写胜负"
    with pytest.raises(KernelError, match="CRAFT_STRATEGY_DRIFT"):
        compile_realization_contract(changed, {"policies": []})


def test_legacy_plan_keeps_its_frozen_realization_contract():
    plan = craft_plan()
    plan.pop("craft_strategy")
    contract = compile_realization_contract(plan, {"policies": []})
    assert contract["contract_version"] == "scene-realization-composition.v1"
    assert "craft_strategy" not in contract
