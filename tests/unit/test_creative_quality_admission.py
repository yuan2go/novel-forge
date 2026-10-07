from copy import deepcopy

import pytest

from novel_forge.modules.chapter_quality_authority.creative_validation import assess_internal_quality
from novel_forge.modules.chapter_quality_authority.domain import QUALITY_GROUPS
from novel_forge.modules.command_kernel.errors import KernelError


def groups():
    return [{"group": group, "validation_receipt": {"book_id": "book", "target_asset_version_id": "draft"},
        "dimensions": [{"dimension": dimension, "gate_status": "INSUFFICIENT_EVIDENCE",
            "semantic_verdict": "PASSED_WITH_UNCALIBRATED", "calibration_status": "PROVIDER_UNCALIBRATED",
            "score": 90, "threshold": 70, "threshold_evaluation": "PASSED", "provider_verified": True,
            "evidence_locations": [{"quote": "exact candidate text"}]} for dimension in dimensions]}
        for group, dimensions in QUALITY_GROUPS.items()]


def test_internal_admission_retains_strict_assessment_without_qualified_pass():
    reports = groups()
    original = deepcopy(reports)
    result = assess_internal_quality(groups=reports, target="draft")
    assert result["status"] == "INTERNAL_ADMITTED"
    assert result["literary_qualification"] == "NOT_RUN"
    assert result["strict_certification_eligible"] is False
    assert reports == original


@pytest.mark.parametrize("change", [{"semantic_verdict": "FAILED"}, {"threshold_evaluation": "FAILED"},
                                   {"evidence_locations": []}, {"provider_verified": False}])
def test_validation_cannot_admit_failed_unlocated_or_unverified_basic_quality(change):
    reports = groups()
    row = next(row for group in reports for row in group["dimensions"] if row["dimension"] == "readability")
    row.update(change)
    result = assess_internal_quality(groups=reports, target="draft")
    assert result["status"] == "BLOCKED" and "readability" in result["blocked_dimensions"]


def test_receipt_and_dimension_coverage_fail_closed():
    reports = groups()
    reports[0]["validation_receipt"] = None
    with pytest.raises(KernelError, match="VALIDATION_QUALITY_COVERAGE_REQUIRED"):
        assess_internal_quality(groups=reports, target="draft")


def test_independent_quality_groups_continue_while_required_sibling_waits():
    from novel_forge.modules.chapter_authority.contracts import ChapterNode, QUALITY_GROUP_NODES
    from novel_forge.modules.chapter_authority.scheduler import ChapterAuthorityScheduler
    scheduler = object.__new__(ChapterAuthorityScheduler)
    blocked, ready, *rest = QUALITY_GROUP_NODES
    children = {node: {"operation_id": node.value, "status": "SUCCEEDED"} for node in ChapterNode}
    children[blocked]["status"] = "RECONCILIATION_REQUIRED"
    children[ready]["status"] = "READY"
    assert scheduler._current_or_next(children) == (ready, children[ready])
    children[blocked].update(status="READY", failed_attempts=1)
    assert scheduler._current_or_next(children) == (ready, children[ready])
    children[blocked]["status"] = "RECONCILIATION_REQUIRED"
    children[ready]["status"] = "SUCCEEDED"
    assert scheduler._current_or_next(children) == (blocked, children[blocked])
    children[blocked]["status"] = "FAILED_FINAL"
    children[ready]["status"] = "READY"
    assert scheduler._current_or_next(children) == (blocked, children[blocked])


@pytest.mark.parametrize("observed,status", [(1124, "FAILED"), (1200, "PASSED"), (2401, "FAILED")])
def test_exact_work_length_overrides_only_length_opinion_and_locates_prose_scope(observed, status):
    from novel_forge.modules.chapter_quality_authority.creative_validation import apply_work_constraint_actions
    from novel_forge.modules.revision.domain import freeze_quality_edit_scope
    reports = groups()
    constraint = {"dimension": "chapter_length", "status": status, "observed": observed,
        "minimum": 1200, "maximum": 2400, "unit": "UNICODE_CODE_POINTS_V1", "source_policy": "frozen-platform"}
    admission = assess_internal_quality(groups=reports, target="draft", work_constraints=[constraint])
    assert admission["blocked_dimensions"] == (["chapter_length"] if status == "FAILED" else [])
    text = "首段。中间发生行动和对白。末段。"
    revision = {"text": text, "scene_artifacts": [{"text": "首段。"}, {"text": "中间发生行动和对白。"}, {"text": "末段。"}]}
    content = {"required_actions": [{"observation": "golden_opening", "required_action": "LOCAL_REPAIR"}],
        "evidence_reports": [], "decision_chain": {}}
    corrected = apply_work_constraint_actions(content, admission=admission, revision=revision, target="draft", canon={"conflicts": []})
    assert [a["observation"] for a in corrected["required_actions"]] == (["chapter_length"] if status == "FAILED" else [])
    if status == "FAILED":
        scope = freeze_quality_edit_scope(revision=revision, revision_asset_version_id="draft", quality=corrected, action=corrected["required_actions"][0])
        assert scope["status"] == "LOCATED" and scope["whole_chapter_edit_authorized"] is False
        assert scope["permitted_ranges"][0]["quote"] == "中间发生行动和对白。"


@pytest.mark.parametrize("text,location", [("首段。中间发生行动和对白。末段。", {"start": 3, "end": 13, "quote": "中间发生行动和对白。"}),
    ("First. A developed action here. End.", {"start": 7, "end": 31, "quote": "A developed action here."})])
def test_single_continuous_scene_length_repair_preserves_other_sentences(text, location):
    from novel_forge.modules.chapter_quality_authority.creative_validation import apply_work_constraint_actions
    from novel_forge.modules.revision.domain import freeze_quality_edit_scope
    revision = {"text": text, "scene_artifacts": [{"text": text}]}
    admission = {"blocked_dimensions": ["chapter_length"], "work_constraints": [{"dimension": "chapter_length", "status": "FAILED", "source_policy": "exact-author-policy"}]}
    quality = apply_work_constraint_actions({"required_actions": [], "evidence_reports": [], "decision_chain": {}}, admission=admission, revision=revision, target="draft", canon={})
    scope = freeze_quality_edit_scope(revision=revision, revision_asset_version_id="draft", quality=quality, action=quality["required_actions"][0])
    assert scope["status"] == "LOCATED"
    assert scope["permitted_ranges"] == [location]
    assert scope["whole_chapter_edit_authorized"] is False
    with pytest.raises(KernelError, match="QUALITY_REVISION_LOCATION_REQUIRED"):
        apply_work_constraint_actions({"required_actions": [], "evidence_reports": [], "decision_chain": {}}, admission=admission, revision={"text": "单句", "scene_artifacts": [{"text": "单句"}]}, target="draft", canon={})


def test_typed_canon_interface_conflicts_remain_blocking_but_do_not_authorize_prose_edit():
    from novel_forge.modules.chapter_quality_authority.creative_validation import apply_work_constraint_actions
    for code, action in [("NARRATIVE_TRANSITION_BASELINE_MISSING", "EVIDENCE_REASSESSMENT"), ("CANON_FACT_CONFLICT", "LOCAL_REPAIR")]:
        content = {"required_actions": [{"observation": "canon_consistency", "required_action": "LOCAL_REPAIR"}],
            "evidence_reports": [], "decision_chain": {}}
        admission = {"blocked_dimensions": ["canon_consistency"]}
        corrected = apply_work_constraint_actions(content, admission=admission, revision={}, target="draft", canon={"conflicts": [{"conflict_code": code}]})
        assert corrected["required_actions"][0]["required_action"] == action
        assert admission["blocked_dimensions"] == ["canon_consistency"]


@pytest.mark.parametrize("preservation,selected", [("PRESERVED", "revised"), ("REGRESSED", "original")])
def test_objective_length_resolution_and_model_preservation_decide_together(preservation, selected):
    from novel_forge.modules.chapter_quality_authority.creative_validation import candidate_work_constraint_checks
    from novel_forge.modules.chapter_authority.candidate_selection import CandidateEvidence, compare_candidates
    from novel_forge.modules.review.diagnostics import prose_hash
    old, new = "行动。", "行动之后，她把手里的纸递过去。"
    quality = {"internal_admission": {"work_constraints": [{"dimension": "chapter_length", "target_asset_version_id": "workspace",
        "minimum": 10, "maximum": 100, "unit": "UNICODE_CODE_POINTS_V1"}]}}
    revision = {"text": new, "source_revision_asset_version_id": "workspace", "source_quality_asset_version_id": "quality",
        "quality_action_observations": ["chapter_length"]}
    original_checks = [{"observation": "chapter_length", "status": "UNCERTAIN", "preservation": preservation,
        "target_asset_version_id": "revised", "target_text_hash": prose_hash(new), "source_quality_asset_version_id": "quality"}]
    checks = candidate_work_constraint_checks(revision=revision, target="revised", quality=quality, checks=original_checks)
    assert original_checks[0]["status"] == "UNCERTAIN" and checks[0]["model_status"] == "UNCERTAIN"
    comparison = compare_candidates(project_id="p", chapter_root_operation_id="root",
        previous=CandidateEvidence("original", {"text": old}, 97, ("chapter_length",), "review-original"),
        challenger=CandidateEvidence("revised", revision, 92, (), "review-new", diagnostic_contract_version="actionable-diagnostics.v1",
            quality_resolution_checks=tuple(checks)), minimum_net_improvement=3)
    assert comparison["selected_asset_version_id"] == selected
    assert comparison["net_improvement"] == -5 and comparison["literary_quality_proven"] is False


@pytest.mark.parametrize("fault", [None, "stale_text", "stale_candidate", "open_issue", "other_uncertainty", "regression", "wrong_measurement", "blocked_quality", "legacy_admission"])
def test_publication_closes_only_exact_preserved_length_deferral(fault):
    from novel_forge.modules.publishing.domain import reviewed_work_admission
    from novel_forge.modules.review.diagnostics import prose_hash
    text = "她将纸递过去，却没有放开手。"
    review = {"report_type": "ReReviewReport", "decision": "NEEDS_REVISION", "issues": [], "unresolved_issues": [],
        "review_decision_contract": "work-review-decision.v1", "selection_review_contract": "immutable-review-projection.v1",
        "selection_review_source_asset_version_id": "review", "revision_version_id": "revision", "target_text_hash": prose_hash(text),
        "quality_resolution_checks": [{"observation": "chapter_length", "status": "UNCERTAIN", "preservation": "PRESERVED",
            "target_asset_version_id": "revision", "target_text_hash": prose_hash(text)}]}
    quality = {"target_asset_version_id": "best", "internal_admission": {"version": "creative-quality-admission.v2",
        "status": "INTERNAL_ADMITTED", "target_asset_version_id": "best", "blocked_dimensions": [], "work_constraints": [
            {"dimension": "chapter_length", "status": "PASSED", "minimum": 10, "maximum": 30, "observed": len(text),
                "unit": "UNICODE_CODE_POINTS_V1", "target_asset_version_id": "best"}]}}
    if fault == "stale_text": review["target_text_hash"] = prose_hash("另一稿")
    if fault == "stale_candidate": review["revision_version_id"] = "other"
    if fault == "open_issue": review["issues"] = [{"code": "causality", "severity": "major"}]
    if fault == "other_uncertainty": review["quality_resolution_checks"][0]["observation"] = "canon_consistency"
    if fault == "regression": review["quality_resolution_checks"][0]["preservation"] = "REGRESSED"
    if fault == "wrong_measurement": quality["internal_admission"]["work_constraints"][0]["observed"] += 1
    if fault == "blocked_quality": quality["internal_admission"]["blocked_dimensions"] = ["canon_consistency"]
    if fault == "legacy_admission": quality["internal_admission"]["version"] = "creative-quality-admission.v1"
    frozen = deepcopy(review)
    assert reviewed_work_admission(review=review, quality=quality, text=text, source_id="revision") is (fault is None)
    assert review == frozen and review["decision"] == "NEEDS_REVISION"
