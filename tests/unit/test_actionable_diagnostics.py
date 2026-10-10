from __future__ import annotations

import pytest

from novel_forge.modules.chapter_authority.domain_handlers import normalize_review_result, normalize_rereview_result
from novel_forge.modules.command_kernel.errors import KernelError


def review(issue):
    return normalize_review_result(
        draft={"chapter": 1, "text": "她作出了选择。"}, draft_asset_version_id="draft:v1",
        result={"diagnostic_contract_version": "actionable-diagnostics.v1", "decision": "NEEDS_REVISION", "score": 72, "issues": [issue]},
        provider_evidence={}, project_id="p", context_bundle_version_id="context:v1",
    )


def diagnosis():
    return {"code": "COST", "severity": "blocking", "message": "选择没有可见代价。",
            "category": "CAUSALITY", "judgment_kind": "SEMANTIC_CONFLICT",
            "evidence": {"start": 0, "end": 7, "quote": "她作出了选择。"},
            "violated_constraint": "选择必须有后果", "revision_goal": "呈现选择失去的具体机会",
            "preserve": ["人物的选择"], "acceptance_criteria": ["正文呈现代价及其后果"]}


def test_diagnosis_keeps_exact_evidence_and_actionable_revision_contract():
    result = review(diagnosis())
    assert result["target_text_hash"].startswith("sha256:")
    assert result["issues"][0]["acceptance_criteria"] == ["正文呈现代价及其后果"]
    assert result["issues"][0]["evidence_locator"]["quote"] == "她作出了选择。"


@pytest.mark.parametrize("field", ["revision_goal", "acceptance_criteria", "preserve", "violated_constraint"])
def test_diagnosis_missing_repair_contract_is_rejected(field):
    issue = diagnosis()
    issue.pop(field)
    with pytest.raises(KernelError):
        review(issue)


def test_revision_claim_plus_higher_score_does_not_prove_resolution():
    initial = review(diagnosis())
    result = normalize_rereview_result(
        draft_asset_version_id="draft:v1", review=initial, review_asset_version_id="review:v1",
        revision={"chapter": 1, "text": "她作出了选择。", "resolution_claimed_issue_codes": ["COST"]},
        revision_asset_version_id="revision:v1", context_bundle_version_id="context:v1",
        result={"diagnostic_contract_version": "actionable-diagnostics.v1", "decision": "PASSED", "score": 99, "issues": [], "resolution_checks": []},
        provider_evidence={}, project_id="p",
    )
    assert result["decision"] != "PASSED"
    assert result["resolved_issue_codes"] == []


def test_aesthetic_preference_cannot_masquerade_as_an_objective_blocker():
    issue = diagnosis()
    issue["judgment_kind"] = "AESTHETIC_SUGGESTION"
    with pytest.raises(KernelError):
        review(issue)


def test_score_only_revision_cannot_replace_candidate_under_actionable_contract():
    from novel_forge.modules.chapter_authority.candidate_selection import CandidateEvidence, compare_candidates
    original = CandidateEvidence("draft:v1", {"text": "她作出了选择。"}, 80, (), "review:v1")
    revised = CandidateEvidence("revision:v1", {"text": "她作出了选择！"}, 99, (), "rereview:v1",
                                diagnostic_contract_version="actionable-diagnostics.v1", resolution_checks=())
    result = compare_candidates(project_id="p", chapter_root_operation_id="root", previous=original,
                                challenger=revised, minimum_net_improvement=3)
    assert result["selected_asset_version_id"] == "draft:v1"


def test_selected_original_reuses_its_review_without_claiming_revision_resolutions():
    from novel_forge.modules.chapter_authority.candidate_selection import bind_selected_review
    initial = review(diagnosis())
    bound = bind_selected_review(candidate={"text": "她作出了选择。"}, candidate_id="draft:v1",
                                 review=initial, review_id="review:v1")
    assert bound["revision_version_id"] == "draft:v1"
    assert bound["decision"] == "NEEDS_REVISION"
    assert bound["issues"][0]["status"] == "OPEN"
    assert bound["resolved_issue_codes"] == []
    assert bound["selection_review_source_asset_version_id"] == "review:v1"
    with pytest.raises(KernelError):
        bind_selected_review(candidate={"text": "她拒绝了选择。"}, candidate_id="draft:v1",
                             review=initial, review_id="review:v1")


def test_creative_guidance_is_retained_for_review_and_directed_revision():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    from novel_forge.modules.revision.domain import apply_revision_result
    guide = {"memo_asset_version_id": "memo:v1", "guidance": {"chapter_goal": "让选择付出代价"}}
    draft = {"chapter": 1, "title": "选择", "text": "她作出了选择。", "creative_execution": guide}
    revised = apply_revision_result(project_id="p", draft=draft, review=review(diagnosis()),
        draft_asset_version_id="draft:v1", review_asset_version_id="review:v1", context_bundle_version_id="context:v1",
        result={"text": "她作出了选择，失去了回家的机会。", "resolved_issue_codes": ["COST"]}, provider_evidence={})
    assert revised["creative_execution"] == guide
    for stage, payload in (("review", {"draft": draft}), ("revision", {"draft": draft, "review": review(diagnosis())}), ("rereview", {"revision": revised, "review": review(diagnosis())})):
        assert build_provider_task_view(stage, payload)["creative_execution"] == guide


def test_retained_review_is_usable_only_for_unchanged_selected_prose():
    from novel_forge.modules.chapter_authority.candidate_selection import bind_selected_review
    from novel_forge.modules.review.diagnostics import review_covers_candidate
    bound = bind_selected_review(candidate={"text": "她作出了选择。"}, candidate_id="draft:v1", review=review(diagnosis()), review_id="review:v1")
    assert review_covers_candidate(bound, text="她作出了选择。", source_id="draft:v1")
    assert not review_covers_candidate(bound, text="她改变了选择。", source_id="draft:v1")
    assert not review_covers_candidate(bound, text="她作出了选择。", source_id="draft:v2")


def test_omitted_blocker_survives_three_rereviews_and_reaches_revision_input():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    initial = review(diagnosis())
    issue_id = initial["issues"][0]["review_issue_id"]
    for generation in range(3):
        result = normalize_rereview_result(
            draft_asset_version_id="draft:v1", review=initial, review_asset_version_id=f"review:{generation}",
            revision={"chapter": 1, "text": "她作出了选择。", "resolution_claimed_issue_codes": ["COST"]},
            revision_asset_version_id=f"revision:{generation}", context_bundle_version_id="context:v1",
            result={"diagnostic_contract_version": "actionable-diagnostics.v1", "decision": "PASSED", "score": 99,
                    "issues": [], "resolution_checks": []}, provider_evidence={}, project_id="p")
        assert result["blocking_issue_count"] == 1
        assert result["remaining_issue_codes"] == ["COST"]
        assert result["resolution_summary"]["denominator_issue_codes"] == ["COST"]
        assert result["resolution_summary"]["resolved_issue_codes"] == []
        assert result["unresolved_issues"][0]["review_issue_id"] == issue_id
        task = build_provider_task_view("revision", {"draft": {"text": "她作出了选择。"}, "review": result})
        assert task["review_issues"][0]["code"] == "COST"
        initial = result


def test_knowledge_use_is_checked_against_exact_prose_and_frozen_card_versions():
    from novel_forge.modules.review.domain import evaluate_review_result
    text = "她交出最后一枚筹码，换来了开门的机会。"
    check = {"knowledge_card_asset_version_id": "card:v1", "status": "VERIFIED_IN_PROSE",
             "evidence": {"start": 0, "end": len(text), "quote": text},
             "reason": "资源交换改变了可行动的选项", "conditions_checked": ["持有筹码"],
             "exceptions_checked": ["没有赊欠许可"], "issue_codes": []}
    inputs = dict(project_id="p", target_asset_version_id="draft:v1", context_bundle_version_id="context:v1",
                  chapter=1, provider_evidence={}, prose_text=text,
                  knowledge_targets=[{"knowledge_card_asset_version_id": "card:v1", "usage_role": "PRINCIPLE"}])
    result = {"decision": "PASSED", "score": 90, "issues": [], "knowledge_checks": [check]}
    checked = evaluate_review_result(**inputs, result=result)
    assert checked["knowledge_checks"][0]["target_text_hash"] == checked["knowledge_target_text_hash"]
    assert checked["knowledge_checks"][0]["evidence_class"] == "FIXTURE_SEMANTIC_REVIEW"
    for invalid in ({**check, "knowledge_card_asset_version_id": "another-book-card"},
                    {**check, "evidence": {"start": 0, "end": 2, "quote": "假证据"}}):
        with pytest.raises(KernelError):
            evaluate_review_result(**inputs, result={**result, "knowledge_checks": [invalid]})
    with pytest.raises(KernelError, match="knowledge"):
        evaluate_review_result(**inputs, result={**result, "knowledge_checks": []})


def test_conditional_inspiration_may_remain_unused_but_misapplication_needs_diagnosis():
    from novel_forge.modules.review.domain import evaluate_review_result
    check = {"knowledge_card_asset_version_id": "card:v1", "status": "NOT_USED", "evidence": None,
             "reason": "本章未采用该灵感", "conditions_checked": [], "exceptions_checked": [], "issue_codes": []}
    args = dict(project_id="p", target_asset_version_id="d", context_bundle_version_id="c", chapter=1,
                provider_evidence={}, prose_text="她离开了。",
                knowledge_targets=[{"knowledge_card_asset_version_id": "card:v1", "usage_role": "REFERENCE"}])
    result = {"decision": "PASSED", "score": 90, "issues": [], "knowledge_checks": [check]}
    assert evaluate_review_result(**args, result=result)["decision"] == "PASSED"
    with pytest.raises(KernelError):
        evaluate_review_result(**args, result={**result, "knowledge_checks": [{**check, "status": "MISAPPLIED"}]})


def test_repeated_diagnosis_cannot_erase_prior_preservation_requirements():
    from novel_forge.modules.review.diagnostics import open_diagnoses
    original = {**diagnosis(), "review_issue_id": "original", "preserve": ["保留尚未兑现的木牌承诺"]}
    later = {**diagnosis(), "review_issue_id": "later", "preserve": ["保留本章人物选择"],
             "acceptance_criteria": ["不可凭空增加资源"]}
    merged = open_diagnoses({"issues": [later], "unresolved_issues": [original]})[0]
    assert merged["preserve"] == ["保留尚未兑现的木牌承诺", "保留本章人物选择"]
    assert merged["acceptance_criteria"] == ["正文呈现代价及其后果", "不可凭空增加资源"]


def test_duplicate_issue_codes_cannot_collapse_distinct_unresolved_locations():
    from novel_forge.modules.review.domain import evaluate_review_result
    issue = {"code": "KNOWLEDGE_COST", "severity": "blocking", "message": "resource conflict"}
    with pytest.raises(KernelError, match="unique"):
        evaluate_review_result(project_id="p", target_asset_version_id="draft", context_bundle_version_id="c",
                               chapter=1, provider_evidence={},
                               result={"decision": "NEEDS_REVISION", "score": 50, "issues": [issue, issue]})


def test_review_targets_resolve_native_context_identity_and_translated_obligations():
    import json
    from novel_forge.modules.review.knowledge import knowledge_review_targets
    translation = {"knowledge_card_asset_version_id": "card:v1", "usage_role": "CONSTRAINT",
                   "use_sites": [{"verification_checks": ["Water must decrease after cooling."]}]}
    context = {"context_manifest": {
        "knowledge_usage": [{"asset_type": "knowledge_card", "asset_version_id": "card:v1"},
                            {"asset_type": "knowledge_pack", "asset_version_id": "pack:v1"}],
        "selected_inputs": [{"asset_version_id": "pack:v1", "provenance": {"knowledge_card_asset_version_ids": ["other:v2"], "knowledge_card_usages": [{"knowledge_card_asset_version_id": "other:v2", "usage_role": "CONSTRAINT"}]}}]},
        "context_segments": [{"asset_version_id": "card:v1", "asset_type": "knowledge_card",
                              "safe_summary": json.dumps({"mechanism": "Cooling spends water.", "preconditions": ["Water exists."],
                                                          "translation": translation})}]}
    targets = knowledge_review_targets(context)
    assert [item["knowledge_card_asset_version_id"] for item in targets] == ["card:v1", "other:v2"]
    assert targets[0]["usage_role"] == "CONSTRAINT"
    assert targets[0]["translation"] == translation
    assert targets[0]["preconditions"] == ["Water exists."]
    assert targets[1]["usage_role"] == "CONSTRAINT"
    pack_provenance = context["context_manifest"]["selected_inputs"][0]["provenance"]
    pack_provenance["knowledge_card_asset_version_ids"].append("card:v1")
    pack_provenance["knowledge_card_usages"].append({"knowledge_card_asset_version_id": "card:v1", "usage_role": "CONSTRAINT"})
    translation["usage_role"] = "INSPIRATION"
    context["context_segments"][0]["safe_summary"] = json.dumps({"mechanism": "Cooling spends water.", "translation": translation})
    repeated = knowledge_review_targets(context)
    assert repeated[0]["usage_role"] == "CONSTRAINT"
    assert repeated[0]["mechanism"] == "Cooling spends water."
    assert repeated[0]["translation"] == translation
    context["context_manifest"]["knowledge_usage"].reverse()
    assert knowledge_review_targets(context) == repeated
    pack_provenance["knowledge_card_usages"][0]["knowledge_card_asset_version_id"] = "unselected:v3"
    with pytest.raises(KernelError, match="REVIEW_KNOWLEDGE_TARGET_INVALID"):
        knowledge_review_targets(context)
    context["context_manifest"]["selected_inputs"][0]["provenance"].pop("knowledge_card_usages")
    with pytest.raises(KernelError, match="REVIEW_KNOWLEDGE_TARGET_INVALID"):
        knowledge_review_targets(context)


def test_promised_mechanism_cannot_be_marked_unused_without_repair_target():
    from novel_forge.modules.review.domain import evaluate_review_result
    target = {"knowledge_card_asset_version_id": "card:v1", "usage_role": "MECHANISM",
              "translation": {"use_sites": [{"verification_checks": ["Show resource loss."]}]}}
    check = {"knowledge_card_asset_version_id": "card:v1", "status": "NOT_USED", "evidence": None,
             "reason": "No resource loss occurs in the prose.", "conditions_checked": [], "exceptions_checked": [], "issue_codes": []}
    with pytest.raises(KernelError, match="promised mechanism"):
        evaluate_review_result(project_id="p", target_asset_version_id="d", context_bundle_version_id="c", chapter=1,
                               provider_evidence={}, prose_text="她离开了。", knowledge_targets=[target],
                               result={"decision": "PASSED", "score": 99, "issues": [], "knowledge_checks": [check]})
