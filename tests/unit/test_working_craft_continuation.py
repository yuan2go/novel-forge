from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy, validate_craft_policy, validate_craft_strategy
from novel_forge.modules.mkaos_authority.craft_usage import WORKING_CRAFT_POLICY
from novel_forge.modules.mkaos_authority.domain import select_narrative_intelligence
from novel_forge.modules.story_planning_runtime.knowledge_translation import add_translation_contract
from tests.unit.test_craft_selection import _card, _need
from tests.unit.test_craft_solver import card
from tests.unit.test_craft_usage import _typed_candidate


def selection(history=(), *, version="narrative-craft-budget.v5", mode="staged", chapter=7, scope="arc:bridge", book="book", **changes):
    mechanism = card("continuing-mechanism")["selected_content"]["craft_mechanism"]
    policy = validate_craft_policy({"schema_version": version, "mechanism_usage_types": {"continuing-mechanism": mode}, **changes})
    return select_narrative_intelligence(replace(_need(), craft_policy=policy, recent_craft_usage=history,
        craft_context={"scene_goal": [mechanism["narrative_problem"]], "chapter_number": chapter,
            "usage_scope_context": {"project_id": "project", "book_id": book, "chapter_number": chapter,
                "arc_plan_version_ids": [scope], "scope_transitions": []}}), (_card(mechanism),))


def strategy(selected, *, previous=None, action="START", phase="SETUP"):
    candidate = _typed_candidate(selected)
    candidate["knowledge_translations"][0]["use_sites"][0]["craft_usage"] = {
        "instance_id": previous["usage"]["instance_id"] if previous else "",
        "predecessor_use_id": previous["use_id"] if previous else "", "phase": phase,
        "scope_id": selected["need"]["craft_context"]["usage_scope_context"]["arc_plan_version_ids"][0],
        "transition": {"action": action, "condition": "人物仍须偿还已发生的承诺。", "progress": "用新的行动延续承诺，保留选择空间。"}}
    return build_craft_strategy(candidate, selected)


def delivery(value, chapter=4, **changes):
    use = value["uses"][0]
    return {**deepcopy(use), "chapter": chapter, "usage_basis": "SELECTED_WORKING_DELIVERY", "effect_status": "NOT_ASSESSED",
        "book_run_id": "run", "selected_source_asset_version_id": "draft:" + str(chapter),
        "selected_source_content_hash": "sha256:source", "target_text_hash": "sha256:text",
        "working_snapshot_hash": "sha256:snapshot", "external_receipt_ids": ["receipt:" + str(chapter)],
        "working_craft_policy": dict(WORKING_CRAFT_POLICY), "formal_acceptance": "NOT_GRANTED",
        "evidence_ceiling": "DELIVERED_PLANNED_ALLOCATION_NOT_REALIZED_EFFECT", **changes}


def observed(row, *, status="SUPPORTED", **changes):
    location = {"start": 0, "end": 8, "quote": "人物留下偿还承诺"}
    return {**deepcopy(row), "usage_basis": "SELECTED_WORKING_PROSE_REVIEW", "effect_status": "UNCERTAIN",
        "review_asset_version_id": "review:1", "review_content_hash": "sha256:review", "evidence": location,
        "evidence_class": "MODEL_SEMANTIC_REVIEW", "phase_transition": {"action": row["usage"]["transition"]["action"],
            "phase": row["usage"]["phase"], "status": status, "evidence": location, "progress": "承诺得到可定位延续。", "reason": "行动支持阶段状态。"}, **changes}


def test_exact_selected_delivery_continues_without_acceptance_or_claimed_effect():
    start = delivery(strategy(selection()))
    for action in ("CONTINUE", "DEFER"):
        value = strategy(selection((start,)), previous=start, action=action)
        usage = value["uses"][0]["usage"]
        assert value["schema_version"] == "narrative-craft-strategy.v4"
        assert usage["accepted_predecessor"] is None
        assert usage["working_predecessor"]["effect_status"] == "NOT_ASSESSED"
        assert usage["working_predecessor"]["realized_observation"] is None
        assert usage["status"] == "PLANNED"
        assert "working_predecessor" not in usage["working_predecessor"]["usage"]
        assert validate_craft_strategy(value) == value


def test_phase_advance_and_end_require_a_separate_located_working_review():
    start = delivery(strategy(selection()))
    for action, phase in (("ADVANCE", "DEVELOPMENT"), ("END", "SETUP")):
        for history in ((start,), (start, observed(start, status="UNCERTAIN")), (start, observed(start, status="FAILED"))):
            with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
                strategy(selection(history), previous=start, action=action, phase=phase)
        value = strategy(selection((start, observed(start))), previous=start, action=action, phase=phase)
        assert value["uses"][0]["usage"]["accepted_predecessor"] is None
        assert value["uses"][0]["usage"]["working_predecessor"]["realized_observation"]["effect_status"] == "UNCERTAIN"
        assert validate_craft_strategy(value) == value
    with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
        strategy(selection((start, observed(start))), previous=start, action="ADVANCE", phase="PAYOFF")


def test_unreviewed_advance_delivery_does_not_create_a_realized_later_phase():
    start = delivery(strategy(selection()))
    advanced = delivery(strategy(selection((start, observed(start))), previous=start, action="ADVANCE", phase="DEVELOPMENT"), chapter=5)
    with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
        strategy(selection((start, advanced)), previous=advanced, action="CONTINUE", phase="DEVELOPMENT")
    current = strategy(selection((start, advanced, observed(advanced))), previous=advanced, action="CONTINUE", phase="DEVELOPMENT")
    assert current["uses"][0]["usage"]["working_predecessor"]["realized_observation"]["phase_transition"]["phase"] == "DEVELOPMENT"


@pytest.mark.parametrize("change", [{"selected_source_asset_version_id": "replaced"}, {"target_text_hash": "changed"},
    {"working_snapshot_hash": "changed"}, {"review_content_hash": ""}, {"acceptance_id": "fabricated"}])
def test_review_cannot_cross_selected_versions_or_be_relabelled_accepted(change):
    start = delivery(strategy(selection()))
    with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
        strategy(selection((start, observed(start, **change))), previous=start, action="ADVANCE", phase="DEVELOPMENT")


def test_latest_delivery_and_exact_book_scope_own_continuation():
    start = delivery(strategy(selection()))
    next_use = delivery(strategy(selection((start,)), previous=start, action="CONTINUE"), chapter=5)
    with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
        strategy(selection((start, next_use)), previous=start, action="CONTINUE")
    for selected in (selection((next_use,), book="other"), selection((next_use,), scope="arc:new"), selection(())):
        with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
            strategy(selected, previous=next_use, action="CONTINUE")
    current = strategy(selection((start, next_use)), previous=next_use, action="CONTINUE")
    assert current["uses"][0]["usage"]["working_predecessor"]["use_id"] == next_use["use_id"]


def test_delivery_budget_blocks_new_instances_while_allowing_same_instance():
    start = delivery(strategy(selection(max_frequency_in_window=1)))
    selected = selection((start,), max_frequency_in_window=1)
    budget = selected["selected"][0]["craft_assessment"]["budget_assessment"]
    assert budget["frequency"] == 0 and budget["working_frequency"] == 1
    assert budget["accepted_usage_history"] == [] and not budget["temporal_budget_applied"]
    with pytest.raises(KernelError, match="CRAFT_USAGE_FREQUENCY_EXCEEDED"):
        strategy(selected)
    assert strategy(selected, previous=start, action="CONTINUE")


def test_persistent_and_old_outside_recent_window_continuations_keep_source_evidence():
    start = delivery(strategy(selection(mode="support"), phase="SUSTAIN"), chapter=2)
    selected = selection((start,), mode="support", chapter=180)
    value = strategy(selected, previous=start, action="CONTINUE", phase="SUSTAIN")
    assert value["uses"][0]["usage"]["working_predecessor"]["selected_source_asset_version_id"] == "draft:2"
    assert validate_craft_strategy(value) == value


def test_v4_frozen_semantics_and_no_optional_methods_remain_unchanged():
    old = strategy(selection(version="narrative-craft-budget.v4"))
    assert "working_predecessor" not in old["uses"][0]["usage"]
    assert validate_craft_strategy(old) == old
    row = delivery(old)
    with pytest.raises(KernelError, match="CRAFT_PHASE_PREDECESSOR_UNAVAILABLE"):
        strategy(selection((row,), version="narrative-craft-budget.v4"), previous=row, action="CONTINUE")
    with pytest.raises(KernelError, match="CRAFT_POLICY_INVALID"):
        validate_craft_policy({"schema_version": "narrative-craft-budget.v4", "working_craft_policy": WORKING_CRAFT_POLICY})
    assert build_craft_strategy({"scene_plan": []}, {"selected": []}) is None
    schema = add_translation_contract({"properties": {}, "required": []}, selection())
    assert "Working continuation" in schema["properties"]["knowledge_translations"]["description"]


def test_native_working_review_keeps_located_phase_and_delivery_separate():
    from novel_forge.modules.book_authority.manuscript_memory import _working_review_observations
    from novel_forge.modules.review.craft import SIDE_EFFECTS, craft_review_targets, validate_craft_checks
    from novel_forge.modules.review.diagnostics import prose_hash
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    value = strategy(selection())
    text = "陆衡把最后一枚返程木牌交给守门人，仍未说出师门密道的位置。"
    draft = {"text": text, "realization_contract": {"craft_strategy": value, "slots": [{"slot_id": "slot:1", "scene_id": "scene-1"}]},
        "scene_artifacts": [{"slot_id": "slot:1", "text": text}]}
    row = delivery(value, target_text_hash=prose_hash(text))
    location = {"start": 0, "end": len(text), "quote": text}
    check = {"use_id": row["use_id"], "effect_status": "UNCERTAIN", "reason": "阶段行动可见，文学效果仍不确定。",
        "signals_checked": ["返程木牌交付。"], "issue_codes": [], "evidence": location,
        "side_effects": [{"kind": kind, "status": "CLEAR", "reason": "没有观察到此副作用。", "issue_codes": [], "evidence": location} for kind in SIDE_EFFECTS],
        "phase_transition": {"action": "START", "phase": "SETUP", "status": "SUPPORTED", "evidence": location,
            "progress": "承诺影响了可见行动。", "reason": "交牌发生在方法承诺的场景。"}}
    checks = validate_craft_checks(checks=[check], targets=craft_review_targets(draft), issues=[], text=text,
        target_asset_version_id=row["selected_source_asset_version_id"], real_model_call=False)
    review = {"project_id": "project", "chapter": row["chapter"], "report_type": "ReviewReport", "target_text_hash": prose_hash(text),
        "craft_checks": checks, "provider_evidence": {"real_model_call": False}, "issues": []}
    source = {"chapter": row["chapter"], "asset_version_id": row["selected_source_asset_version_id"], "text_hash": prose_hash(text)}
    cursor = SimpleNamespace(execute=lambda *args: None, fetchall=lambda: [("review:1",)])
    def read(**kwargs):
        return SimpleNamespace(content=review, content_hash=canonical_hash(review), asset_version_id="review:1")
    uow = SimpleNamespace(cursor=cursor, repositories=SimpleNamespace(asset_documents=SimpleNamespace(require=read)))
    result = _working_review_observations(uow, snapshot={"project_id": "project", "book_run_id": "run"}, source=source, draft=draft, deliveries=[row])
    assert len(result) == 1 and result[0]["usage_basis"] == "SELECTED_WORKING_PROSE_REVIEW"
    assert result[0]["formal_acceptance"] == "NOT_GRANTED" and result[0]["evidence_class"] == "FIXTURE_SEMANTIC_REVIEW"
    assert row["effect_status"] == "NOT_ASSESSED" and result[0]["effect_status"] == "UNCERTAIN"
    review["craft_checks"][0]["phase_transition"]["evidence"]["quote"] = "不存在的句子"
    assert _working_review_observations(uow, snapshot={"project_id": "project", "book_run_id": "run"}, source=source, draft=draft, deliveries=[row]) == []


def test_selected_history_excludes_replacements_and_transitive_stale_sources(monkeypatch):
    from novel_forge.modules.book_authority import manuscript, manuscript_memory, working_prose
    from novel_forge.storage import authority_uow
    value = strategy(selection())
    rows = [{"chapter": 1, "asset_version_id": "draft:1", "content_hash": "sha256:source1", "text_hash": "sha256:text1"},
        {"chapter": 2, "asset_version_id": "draft:2", "content_hash": "sha256:source2", "text_hash": "sha256:text2",
            "dependency_changes": [{"chapter": 1, "old_asset_version_id": "discarded:1"}]}]
    monkeypatch.setattr(working_prose, "working_source_rows", lambda snapshot: rows)
    monkeypatch.setattr(manuscript, "effective_workflow", lambda *args: manuscript.AUTHOR_WORKFLOW)
    checks = []
    monkeypatch.setattr(manuscript, "verify_working_context", lambda *args: checks.append(True))
    monkeypatch.setattr(manuscript_memory, "_working_review_observations", lambda *args, **kwargs: [])
    class Uow:
        def __enter__(self):
            self.cursor = SimpleNamespace(execute=lambda *args: None, fetchone=lambda: ({"book_run_id": "run"},))
            self.repositories = SimpleNamespace(asset_documents=SimpleNamespace(require=lambda **kwargs:
                SimpleNamespace(content={"text": "正文"}, asset_type="draft_chapter")))
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(authority_uow, "AuthorityUnitOfWork", lambda *args: Uow())
    calls = []
    def usage(**kwargs):
        calls.append(kwargs["result_asset_version_id"])
        use = {**value["uses"][0], "chapter": 1, "external_receipt_ids": ["receipt:1"]}
        return [{"result_asset_version_id": "draft:1", "craft_usage": [use]}]
    mkaos = SimpleNamespace(list_runtime_usage=usage)
    snapshot = {"book_run_id": "run", "project_id": "project", "book_id": "book", "snapshot_hash": "sha256:snapshot", "sources": []}
    history = manuscript_memory.selected_working_craft_history("unused", snapshot=snapshot, mkaos=mkaos, policy=WORKING_CRAFT_POLICY)
    assert calls == ["draft:1"] and len(checks) == 2
    assert history[0]["selected_source_asset_version_id"] == "draft:1" and history[0]["effect_status"] == "NOT_ASSESSED"
    assert history[1]["reason"] == "DEPENDENCY_CHANGED" and history[1]["chapter"] == 2
    rows[0] = {**rows[0], "asset_version_id": "replacement:1", "content_hash": "sha256:replacement"}
    changed = manuscript_memory.selected_working_craft_history("unused", snapshot=snapshot, mkaos=mkaos, policy=WORKING_CRAFT_POLICY)
    assert all(row["usage_basis"] == "WORKING_CRAFT_COVERAGE" for row in changed)
    assert changed[0]["selected_source_asset_version_id"] == "replacement:1"


def test_provider_history_references_roundtrip_working_observations_without_upgrading():
    from novel_forge.modules.mkaos_authority.craft_context_projection import project_planning_craft_histories, resolve_planning_craft_histories
    start = delivery(strategy(selection()))
    selected = selection((start, observed(start)))
    projected = project_planning_craft_histories(selected)
    assert resolve_planning_craft_histories(projected) == selected
    budget = selected["selected"][0]["craft_assessment"]["budget_assessment"]
    assert budget["accepted_usage_history"] == []
    assert budget["working_realization_cautions"][0]["effect_status"] == "UNCERTAIN"
    assert budget["working_feedback_penalty"] > 0
