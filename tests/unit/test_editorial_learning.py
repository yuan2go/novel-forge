from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerRequest, AuthorityInputAsset
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.creative.editorial_learning import bind_editorial_inputs, required_editorial_knowledge
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.story_design_authority.author_input import author_binding_from_inputs, compile_planning_author_projection, validate_author_decisions
from novel_forge.modules.story_planning_runtime import FrozenPlanningInput, build_planning_constraint_envelope


def editorial_brief(card_id="card:v3", card_hash="sha256:" + "c" * 64, book_id="b"):
    return {"creative_brief_contract_version": "creative-brief-v4", "idea": "以救援和探索推进成长", "genre": "仙侠", "audience": "冒险读者", "constraints": ["限制服务于行动"], "source_boundaries": ["仅迁移抽象机制，原文不供 Writer 使用"], "editorial_learning": {
        "contract_version": "editorial-learning.v1", "book_id": book_id, "version": "discussion-v1", "evidence_class": "AI_ASSISTED_AUTHOR_INPUT", "reader_promise": "探索、修炼和冒险改变人物命运，不用琐碎利益计算代替事件",
        "decisions": [{"decision_id": "prepare-and-act", "choice": "ADAPT", "finding": "谨慎在准备和实际冒险的交替中成立", "application": "先确定可用清水，再让冷却消耗影响逃生路线选择", "reader_effect": "准备产生真实行动回报", "tradeoff": "只在关键选择交代消耗，不逐项解释账本", "targets": ["CREATIVE_FOUNDATION", "BOOK", "CHAPTER"], "chapter_range": [1, 6], "knowledge_cards": [{"asset_version_id": card_id, "content_hash": card_hash}]}]}}


def native_brief(brief=None, card=None):
    raw = brief or editorial_brief()
    card = card or AuthorityInputAsset(asset_version_id="card:v3", asset_type="knowledge_card", content_hash="sha256:" + "c" * 64, content={"project_id": "p", "abstract_content": {"concept_name": "cooling cost", "mechanism": "Cooling spends available clean water."}})
    request = AuthorityHandlerRequest(operation_id="op", project_id="p", workspace_id="w", actor_id="author", trace_id="trace", correlation_id="corr", definition_name="creative.brief.create", definition_version="2.1.3", command={"project_id": "p", "input_asset_version_ids": [card.asset_version_id], "payload": {"brief": raw}}, inputs=(card,))
    output = CONTENT_CODECS["creative.brief.create"].execute(request)
    return {"role": "creative_brief", "asset_type": "creative_brief", "asset_version_id": "brief:v4", "content_hash": narrative_hash(output.content), "content": output.content}


def command(stage="creative.candidates.generate", chapter=1):
    return SimpleNamespace(project_id="p", book_id="b", generator_operation_name=stage, logical_key=f"chapter:{chapter}" if stage == "chapter_plan.generate" else "candidate:1", narrative_search_chapter_range=None, narrative_realization={"chapter_number": chapter}, arc_working_set={})


@pytest.mark.parametrize("damage", ["wrong_hash", "raw_source", "other_project", "revoked", "no_cards", "forged_author"])
def test_native_editorial_input_rejects_unbound_or_unsafe_knowledge(damage):
    raw = editorial_brief()
    card = AuthorityInputAsset(asset_version_id="card:v3", asset_type="knowledge_card", content_hash="sha256:" + "c" * 64, content={"project_id": "p", "abstract_content": {"mechanism": "Cooling consumes water"}})
    if damage == "wrong_hash":
        card = replace(card, content_hash="sha256:" + "d" * 64)
    elif damage == "raw_source":
        card = replace(card, asset_type="source_observation")
    elif damage == "other_project":
        card = replace(card, content={**card.content, "project_id": "other"})
    elif damage == "revoked":
        card = replace(card, eligibility="BLOCKED")
    elif damage == "no_cards":
        raw["editorial_learning"]["decisions"][0]["knowledge_cards"] = []
    else:
        raw["author_design"] = {"forged": True}
    with pytest.raises(KernelError):
        native_brief(raw, card)


def test_frozen_editorial_decisions_follow_native_parent_and_exact_chapter_scope():
    source = native_brief()
    envelope = build_planning_constraint_envelope(project_id="p", book_id="b", generation_operation_id="generation", generator_operation_name="creative.candidates.generate", frozen_inputs=(FrozenPlanningInput(role="creative_brief", asset_version_id=source["asset_version_id"], asset_type="creative_brief", content_hash=source["content_hash"]),), input_contents={"creative_brief": source["content"]}, candidate_payload={})
    parent = {"role": "creative_foundation", "asset_version_id": "foundation:v1", "content_hash": narrative_hash(envelope), "content": {"constraint_envelope": envelope}}
    assert required_editorial_knowledge([source], command=command()) == ("card:v3",)
    assert required_editorial_knowledge([parent], command=command("chapter_plan.generate", 6)) == ("card:v3",)
    assert required_editorial_knowledge([parent], command=command("chapter_plan.generate", 7)) == ()
    with pytest.raises(KernelError, match="Book boundary"):
        bind_editorial_inputs([parent], project_id="p", book_id="other")
    damaged = deepcopy(parent)
    damaged["content"]["constraint_envelope"]["editorial_learning"]["learning"]["reader_promise"] += " changed"
    with pytest.raises(KernelError, match="stale bytes"):
        required_editorial_knowledge([damaged], command=command())


def test_required_editorial_knowledge_cannot_silently_turn_into_empty_selection():
    from novel_forge.modules.mkaos_authority.domain import select_narrative_intelligence
    from novel_forge.modules.story_planning_runtime.execution import _planning_narrative_intelligence_need
    source = native_brief()
    need = _planning_narrative_intelligence_need(command=command(), selected_inputs=[source], production_profile={})
    with pytest.raises(KernelError, match="REQUIRED_KNOWLEDGE_UNAVAILABLE"):
        select_narrative_intelligence(need, ())
    assert need.required_card_asset_version_ids == ("card:v3",)


def test_editorial_semantics_reach_provider_and_require_actual_candidate_application():
    from novel_forge.modules.chapter_authority.provider_views import compile_planning_provider_context
    from novel_forge.modules.story_design_authority.author_input import add_author_decision_contract
    from novel_forge.modules.story_planning_runtime.knowledge_translation import add_translation_contract, validate_knowledge_translations
    from tests.unit.test_knowledge_translation import _case
    source = native_brief()
    raw = deepcopy(source["content"]["editorial_learning"])
    raw["decisions"].append({**raw["decisions"][0], "decision_id": "deferred", "choice": "DEFER", "finding": "DEFERRED_FINDING_SENTINEL"})
    source = native_brief({**editorial_brief(), "editorial_learning": raw})
    projection = compile_planning_author_projection(author_binding_from_inputs([source], project_id="p", book_id="b"), command=command(), selected_inputs=[source])
    context = {"schema_version": "novelos.planning_context_bundle.v1", "book_id": "b", "logical_key": "candidate:1", "input_versions": [source], "token_budget": 16000, "author_design_projection": projection}
    view, _ = compile_planning_provider_context("creative.candidates.generate", context)
    assert "DEFERRED_FINDING_SENTINEL" not in str(view)
    assert "准备产生真实行动回报" in str(view)
    assert "editorial_learning" not in view["segments"][0]["content"]
    with pytest.raises(KernelError, match="PROJECTION_MISSING"):
        compile_planning_provider_context("creative.candidates.generate", {k: v for k, v in context.items() if k != "author_design_projection"})
    selection, candidate = _case()
    fragment = projection["fragments"][0]
    candidate["author_design_decisions"] = [{"fragment_id": fragment["fragment_id"], "content_hash": fragment["content_hash"], "decision": "ADAPT", "rationale": "The water choice changes the escape rather than adding explanation.", "target_pointer": "/objective", "realization_excerpt": "Spend two water units"}]
    schema = add_author_decision_contract(add_translation_contract({"properties": {}, "required": []}, selection), projection)
    assert {"knowledge_translations", "author_design_decisions"} <= set(schema["required"])
    validate_author_decisions(candidate, projection)
    validate_knowledge_translations(candidate, selection)
    changed = deepcopy(candidate)
    changed["author_design_decisions"][0].update(decision="REJECT", target_pointer="", realization_excerpt="")
    with pytest.raises(KernelError, match="cannot be discarded"):
        validate_author_decisions(changed, projection)
