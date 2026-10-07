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


def test_typed_canon_interface_conflicts_remain_blocking_but_do_not_authorize_prose_edit():
    from novel_forge.modules.chapter_quality_authority.creative_validation import apply_work_constraint_actions
    for code, action in [("NARRATIVE_TRANSITION_BASELINE_MISSING", "EVIDENCE_REASSESSMENT"), ("CANON_FACT_CONFLICT", "LOCAL_REPAIR")]:
        content = {"required_actions": [{"observation": "canon_consistency", "required_action": "LOCAL_REPAIR"}],
            "evidence_reports": [], "decision_chain": {}}
        admission = {"blocked_dimensions": ["canon_consistency"]}
        corrected = apply_work_constraint_actions(content, admission=admission, revision={}, target="draft", canon={"conflicts": [{"conflict_code": code}]})
        assert corrected["required_actions"][0]["required_action"] == action
        assert admission["blocked_dimensions"] == ["canon_consistency"]
