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


def test_uncertain_plan_evidence_can_be_retained_without_authorizing_plan_or_prose_mutation():
    from novel_forge.modules.review.diagnostics import structural_repair_scope

    diagnosis = repair(root_cause="UNCERTAIN", repair_scope="INVESTIGATE")
    validate_repair(diagnosis)
    route = finding_repair_route({"status": "UNRESOLVED", "members": [{"judgment": "ISSUE", "repair": diagnosis}]})
    assert route == {"contract_version": "prose-root-cause.v1", "repair_scope": "INVESTIGATE",
        "consumer": "AUTHOR_DIAGNOSIS", "authorization": "PROPOSAL_ONLY"}
    assert structural_repair_scope([{"repair": diagnosis, "judgment_kind": "UNCERTAIN", "status": "OPEN"}]) == "LOCAL_PROSE"


@pytest.mark.parametrize("diagnosis", [
    repair(root_cause="UNCERTAIN", repair_scope="INVESTIGATE"),
    repair(problem_owner="UNKNOWN", repair_scope="INVESTIGATE"),
    repair(problem_owner="PROSE", root_cause="UNCERTAIN", repair_scope="INVESTIGATE"),
    repair(),
])
def test_semantic_label_cannot_turn_investigation_or_plan_proposal_into_prose_permission(diagnosis):
    from novel_forge.modules.review.diagnostics import open_diagnoses, prose_repair_diagnoses, validate_prose_repair_scope

    validate_repair(diagnosis)
    issue = {"code": "timeline", "severity": "major", "judgment_kind": "SEMANTIC_CONFLICT",
        "repair": diagnosis, "evidence_locator": {"quote": "昨日交出的粗盘。"}}
    review = {"issues": [issue]}
    assert open_diagnoses(review) == [issue]
    assert prose_repair_diagnoses(review, work_requirements=True) == []
    with pytest.raises(KernelError, match="unaffected"):
        validate_prose_repair_scope({"text": "昨日交出的粗盘。"},
            prose_repair_diagnoses(review, work_requirements=True), "上月交出的粗盘。")


@pytest.mark.parametrize("scope", ["LOCAL_PROSE", "SCENE_REVISION", "CHAPTER_REVISION", None])
def test_concrete_prose_diagnoses_and_legacy_diagnoses_remain_repairable(scope):
    from novel_forge.modules.review.diagnostics import prose_repair_diagnoses

    issue = {"code": "repeat", "severity": "minor", "judgment_kind": "SEMANTIC_CONFLICT"}
    if scope:
        issue["repair"] = repair(problem_owner="PROSE", repair_scope=scope)
        validate_repair(issue["repair"])
    assert prose_repair_diagnoses({"issues": [issue]}, work_requirements=True) == [issue]


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
