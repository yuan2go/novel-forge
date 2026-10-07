from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.domain_handlers import build_publish_gate
from novel_forge.modules.publishing.domain import prepare_internal_release, reviewed_work_admission
from novel_forge.modules.review.diagnostics import prose_hash


def evidence():
    text = "门开了。"
    review = {"report_type": "ReReviewReport", "decision": "NEEDS_REVISION", "blocking_issue_count": 0,
        "review_decision_contract": "work-review-decision.v1", "revision_version_id": "candidate",
        "target_text_hash": prose_hash(text), "issues": [], "unresolved_issues": [], "regression_issue_codes": [],
        "quality_resolution_checks": [{"observation": "chapter_length", "status": "UNCERTAIN", "preservation": "PRESERVED",
            "target_asset_version_id": "candidate", "target_text_hash": prose_hash(text)}]}
    quality = {"target_asset_version_id": "selection", "internal_admission": {
        "version": "creative-quality-admission.v3", "status": "INTERNAL_ADMITTED", "blocked_dimensions": [],
        "target_asset_version_id": "selection", "work_constraints": [{"dimension": "chapter_length", "status": "PASSED",
            "target_asset_version_id": "selection", "unit": "UNICODE_CODE_POINTS_V1", "minimum": 1,
            "maximum": 10, "observed": len(text)}]}}
    return text, review, quality


def test_host_objective_length_admission_preserves_uncertain_review_and_is_current_only():
    text, review, quality = evidence()
    assert callable(build_publish_gate)
    arguments = dict(project_id="project", revision={"chapter": 1, "text": text, "selected_source_asset_version_id": "candidate"},
        revision_asset_version_id="selection", quality=quality, quality_asset_version_id="quality", review=review,
        review_asset_version_id="review", canon={"gate": "PASSED", "conflicts": []}, canon_asset_version_id="canon",
        context_bundle={}, context_bundle_version_id="context")
    assert prepare_internal_release(**arguments)["gate"] == "PUBLISH_GATE_BLOCKED"
    admitted = prepare_internal_release(**arguments, work_admission=True)
    assert admitted["gate"] == "INTERNAL_ADMITTED"
    assert admitted["review_admission"]["source_review_decision"] == "NEEDS_REVISION"
    assert admitted["review_admission"]["literary_quality_proven"] is False
    assert review["decision"] == "NEEDS_REVISION"


@pytest.mark.parametrize("mutate", [
    lambda r, q: r.update(target_text_hash="forged"),
    lambda r, q: r.update(revision_version_id="foreign"),
    lambda r, q: r.update(blocking_issue_count=1),
    lambda r, q: r.update(regression_issue_codes=["regression"]),
    lambda r, q: r["quality_resolution_checks"][0].update(observation="readability"),
    lambda r, q: r["quality_resolution_checks"][0].update(preservation="UNCERTAIN"),
    lambda r, q: r["quality_resolution_checks"][0].update(status="UNRESOLVED"),
    lambda r, q: q["internal_admission"].update(version="creative-quality-admission.v2"),
    lambda r, q: q["internal_admission"].update(blocked_dimensions=["readability"]),
    lambda r, q: q["internal_admission"]["work_constraints"][0].update(observed=1),
    lambda r, q: q["internal_admission"]["work_constraints"][0].update(unit="UNKNOWN"),
    lambda r, q: q["internal_admission"]["work_constraints"].append({"dimension": "readability"}),
])
def test_host_length_admission_rejects_scope_or_other_semantic_failure(mutate):
    text, review, quality = evidence()
    review, quality = deepcopy(review), deepcopy(quality)
    mutate(review, quality)
    assert not reviewed_work_admission(review=review, quality=quality, text=text, source_id="candidate")
