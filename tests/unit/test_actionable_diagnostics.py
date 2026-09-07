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
        assert result["unresolved_issues"][0]["review_issue_id"] == issue_id
        task = build_provider_task_view("revision", {"draft": {"text": "她作出了选择。"}, "review": result})
        assert task["review_issues"][0]["code"] == "COST"
        initial = result
