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


def test_internal_disposition_repairs_real_semantic_failure_without_certification():
    from novel_forge.modules.chapter_quality_authority.creative_validation import internal_required_actions
    from novel_forge.modules.revision.domain import freeze_quality_edit_scope
    reports=groups()
    row=reports[0]['dimensions'][0]
    row.update(semantic_verdict='FAILED',target_asset_version_id='draft',evidence_locations=[{'start':0,'end':2,'quote':'重复'}])
    admission=assess_internal_quality(groups=reports,target='draft',disposition_version=2)
    assert admission['status']=='BLOCKED' and admission['strict_certification_eligible'] is False
    actions=internal_required_actions(admission=admission,evidence_reports=[row],target='draft')
    assert len(actions)==1 and actions[0]['required_action']=='LOCAL_REPAIR'
    scope=freeze_quality_edit_scope(revision={'text':'重复，但还需要保留的正文。'},revision_asset_version_id='draft',quality={'evidence_reports':[row]},action=actions[0])
    assert scope['status']=='LOCATED' and scope['permitted_ranges']==[{'start':0,'end':2,'quote':'重复'}]
    assert not scope['whole_chapter_edit_authorized']
    row['provider_verified']=False
    assert internal_required_actions(admission=admission,evidence_reports=[row],target='draft')[0]['required_action']=='EVIDENCE_REASSESSMENT'


def test_missing_evidence_disposition_cannot_authorize_prose_rewrite():
    from novel_forge.modules.chapter_quality_authority.creative_validation import internal_required_actions
    reports=groups()
    row=reports[0]['dimensions'][0]
    row.update(semantic_verdict='INSUFFICIENT_EVIDENCE',target_asset_version_id='draft')
    admission=assess_internal_quality(groups=reports,target='draft',disposition_version=2)
    action=internal_required_actions(admission=admission,evidence_reports=[row],target='draft')[0]
    assert action['required_action']=='EVIDENCE_REASSESSMENT' and action['permitted_change_scope']=='EVIDENCE_ONLY'


def test_internal_v2_cannot_promote_fixture_claims_to_real_assessment():
    reports=groups()
    row=reports[0]['dimensions'][0]
    row.update(fixture=True,calibration_status='FIXTURE_UNCALIBRATED')
    result=assess_internal_quality(groups=reports,target='draft',disposition_version=2)
    assert result['status']=='BLOCKED' and row['dimension'] in result['blocked_dimensions']
