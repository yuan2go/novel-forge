from copy import deepcopy

import pytest

from novel_forge.modules.book_followup_authority.prose_review import aggregate_reports, freeze_manifest, validate_window_report
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.repair_scope import finding_repair_route, validate_repair
from tests.unit.test_longform_prose_editorial import manifest, report


def repair(**changes):
    return {"root_cause": "SCENE_ORGANIZATION", "problem_owner": "PLAN", "repair_scope": "FUTURE_REPLAN",
            "revision_goal": "Replace repeated preparation with a future event that uses existing progress.",
            "preserve": ["Delivered events and selected prose."], "resolution_criteria": ["A new choice changes a later opportunity."], **changes}


def test_root_cause_review_retains_exact_sources_and_routes_plan_defect_to_native_replan():
    old = manifest()
    frozen = freeze_manifest(project_id="p", workspace_id="w", book_run_id="b",
        sources=[{"acceptance_id": "a", "chapter_number": 1, "asset_version_id": "draft", "asset_hash": "hash",
                  "text": "剑锋停在门外。她没有追击，因为桥下还有孩子。"}],
        policy={**old["policy"], "diagnosis_contract": "prose-root-cause.v1"})
    result = report(frozen, frozen["windows"][0])
    result["schema_version"] = "longform-prose-review.v2"
    result["findings"][0]["repair"] = repair()
    validate_window_report(result, manifest=frozen, window=frozen["windows"][0])
    aggregate = aggregate_reports(frozen, [result])
    route = aggregate["findings"][0]["repair_route"]
    assert route["consumer"] == "NATIVE_PLAN_CHANGE_OR_BOOK_REPLAN" and route["authorization"] == "PROPOSAL_ONLY"
    assert not aggregate["coverage_complete"]
    with pytest.raises(KernelError, match="frozen diagnosis contract"):
        validate_window_report(result, manifest=old, window=old["windows"][0])


@pytest.mark.parametrize("changes", [{"repair_scope": "LOCAL_PROSE"}, {"repair_scope": "CHAPTER_REVISION"},
    {"problem_owner": "UNKNOWN"}, {"root_cause": "UPPER_PLOT", "problem_owner": "PROSE", "repair_scope": "SCENE_REVISION"}])
def test_structural_plan_issue_never_authorizes_prose_overwrite(changes):
    with pytest.raises(KernelError):
        validate_repair(repair(**changes))


def test_mixed_or_uncertain_diagnoses_remain_investigation():
    finding = {"status": "CONFLICT_REQUIRES_REVIEW", "members": [{"judgment": "ISSUE", "repair": repair()}]}
    assert finding_repair_route(finding)["repair_scope"] == "INVESTIGATE"


def test_native_provider_schema_and_context_expose_root_causes_only_for_selected_policy():
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage="longform_prose_review",
        request_payload={"input": {"prose_diagnosis_contract": "prose-root-cause.v1"}})
    assert ref.endswith(":v2") and schema["properties"]["schema_version"]["enum"] == ["longform-prose-review.v2"]
    context = {"schema_version": "novelos.longform_prose_review_context_bundle.v2", "selected_inputs": [
        {"asset_type": "longform_prose_review_window", "projection": {"schema_version": "longform-prose-window.v3",
         "policy": {"diagnosis_contract": "prose-root-cause.v1"}}}]}
    assert "FUTURE_REPLAN" in build_provider_context_view("longform_prose_review", context, {})["diagnosis_instruction"]
    old = deepcopy(context)
    old["selected_inputs"][0]["projection"]["policy"] = {}
    assert "diagnosis_instruction" not in build_provider_context_view("longform_prose_review", old, {})
