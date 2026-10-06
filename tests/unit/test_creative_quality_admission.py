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
