import pytest

from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_creative_baseline,
)
from novel_forge.modules.chapter_quality_authority.context_views import (
    build_quality_context_view,
)
from novel_forge.modules.chapter_quality_authority.domain import (
    build_quality_group_evidence,
)
from novel_forge.modules.content_quality_loop.domain import derive_quality_actions
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_work_intent_consistency import work_input


def evaluate(
    *,
    status="FAILED",
    calibration="HUMAN_CALIBRATED",
    score=100,
    selected=True,
    fixture=False,
):
    plan, context, candidate = work_input("严肃观察叙述", {"reward": 70})
    plan.update(
        chapter_contract_schema_version="chapter-mission-scene.v3",
        reward_action="兑现已选择承诺" if selected else None,
        reward_setup=[],
        reward_payoff=[],
    )
    candidate["creative_baseline"] = build_creative_baseline(plan, context)
    view = build_quality_context_view(
        group="commercial",
        revision=candidate,
        revision_asset_version_id="candidate:v1",
        chapter_plan=plan,
        chapter_plan_asset_version_id="plan:v1",
        context_bundle=context,
        context_bundle_asset_version_id="context:v1",
        canon={},
        canon_asset_version_id="canon:v1",
        work_requirements=True,
    )
    evidence = {
        "dimension": "reward",
        "gate_status": status,
        "score": score,
        "calibration_status": calibration,
        "provider_verified": True,
        "human_verified": False,
        "target_asset_version_id": "candidate:v1",
        "evaluation_semantics_version": view.get(
            "evaluation_semantics_version", "work-quality.v1"
        ),
        "quality_policy_digest": view["compiled_quality_policy"]["policy_digest"],
        "creative_baseline_digest": candidate["creative_baseline"]["baseline_digest"],
        "evidence_locations": [{"quote": candidate["text"][:10]}],
    }
    context["context_segments"].append(
        {
            "asset_version_id": "evidence:v1",
            "structured_facts": [{"key": "dimension_evidence", "value": [evidence]}],
        }
    )
    result = build_quality_group_evidence(
        group="commercial",
        project_id="project-1",
        revision=candidate,
        revision_asset_version_id="candidate:v1",
        context_bundle=context,
        canon={},
        fixture=fixture,
        quality_context=view,
    )
    return next(item for item in result["dimensions"] if item["dimension"] == "reward")


def test_generic_threshold_cannot_reactivate_work_non_applicability():
    result = evaluate(selected=False)
    assert result["gate_status"] == "NOT_APPLICABLE"
    assert result["score"] is None and result["weight"] == 0 and not result["blocking"]
    assert derive_quality_actions([result]) == []


def test_semantic_failure_survives_passing_score_and_requires_located_repair():
    result = evaluate()
    assert result["gate_status"] == "FAILED"
    assert result["semantic_verdict"] == "FAILED"
    assert result["score"] == 100 and result["threshold_evaluation"] == "PASSED"
    assert result["blocking"] and result["required_action"] == "LOCAL_REPAIR"
    assert derive_quality_actions([result])[0]["required_action"] == "LOCAL_REPAIR"


@pytest.mark.parametrize("status", ["PASSED", "PASSED_WITH_UNCALIBRATED"])
def test_uncalibrated_high_score_requires_new_evidence(status):
    result = evaluate(status=status, calibration="PROVIDER_UNCALIBRATED")
    assert result["gate_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["score"] == 100 and result["threshold_evaluation"] == "PASSED"
    assert result["blocking"] and result["required_action"] == "EVIDENCE_REASSESSMENT"
    assert (
        derive_quality_actions([result])[0]["permitted_change_scope"] == "EVIDENCE_ONLY"
    )


def test_declared_uncalibrated_verdict_cannot_be_promoted_by_calibration_label():
    result = evaluate(status="PASSED_WITH_UNCALIBRATED")
    assert result["gate_status"] == "INSUFFICIENT_EVIDENCE"


def test_selected_requirement_rejects_provider_non_applicability():
    with pytest.raises(KernelError, match="QUALITY_APPLICABILITY_CONFLICT"):
        evaluate(status="NOT_APPLICABLE")


def test_numeric_threshold_can_fail_a_qualified_pass_but_never_reverse_a_failure():
    result = evaluate(status="PASSED", score=30)
    assert result["semantic_verdict"] == "PASSED"
    assert result["threshold_evaluation"] == result["gate_status"] == "FAILED"


@pytest.mark.parametrize("status", ["PROHIBITED", "UNDETERMINED"])
def test_host_applicability_is_independent_of_measurement(status):
    from novel_forge.modules.chapter_quality_authority.work_semantics import (
        finalize_work_dimension,
    )

    result = finalize_work_dimension(
        evaluate(),
        policy={
            "thresholds": {"reward": 70},
            "dimension_weights": {},
            "policy_digest": "policy",
        },
        requirement={"status": status},
        baseline_digest="baseline",
    )
    assert result["applicability"] == status
    assert result["threshold_evaluation"] == "NOT_EVALUATED"
    assert result["required_action"] == (
        "EVIDENCE_REASSESSMENT" if status == "UNDETERMINED" else "NONE"
    )


def test_old_policy_evidence_cannot_be_rescored_as_current_semantics():
    from novel_forge.modules.chapter_quality_authority.domain import (
        _calibrated_evidence,
    )

    row = {
        "dimension": "reward",
        "target_asset_version_id": "candidate:v1",
        "gate_status": "PASSED",
        "score": 100,
        "calibration_status": "HUMAN_CALIBRATED",
        "evaluation_semantics_version": "work-quality.v1",
        "quality_policy_digest": "policy",
        "creative_baseline_digest": "baseline",
    }
    assert (
        _calibrated_evidence(
            "reward",
            [{"structured_facts": [{"key": "dimension_evidence", "value": [row]}]}],
            target_asset_version_id="candidate:v1",
            fixture=False,
            quality_policy_digest="policy",
            creative_baseline_digest="baseline",
        )
        is None
    )


def test_qualified_verdict_without_required_measurement_requires_evidence():
    result = evaluate(status="PASSED", score=None)
    assert result["semantic_verdict"] == "PASSED"
    assert result["gate_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["threshold_evaluation"] == "NOT_EVALUATED"
    assert (
        derive_quality_actions([result])[0]["permitted_change_scope"] == "EVIDENCE_ONLY"
    )


def test_uncalibrated_failure_blocks_but_cannot_authorize_prose_mutation():
    result = evaluate(calibration="PROVIDER_UNCALIBRATED")
    assert result["gate_status"] == result["semantic_verdict"] == "FAILED"
    assert result["required_action"] == "EVIDENCE_REASSESSMENT"
    assert (
        derive_quality_actions([result])[0]["permitted_change_scope"] == "EVIDENCE_ONLY"
    )


@pytest.mark.parametrize("review_score", [0, 100])
def test_aggregate_keeps_uncalibrated_review_as_semantic_veto_without_numeric_vote(
    review_score,
):
    from novel_forge.modules.chapter_quality_authority.domain import QUALITY_DIMENSIONS
    from novel_forge.modules.content_quality_loop.domain import (
        evaluate_quality_evidence,
    )
    from novel_forge.modules.review.diagnostics import prose_hash

    _, _, candidate = work_input("观察")
    candidate["selected_source_asset_version_id"] = "candidate:v1"
    digest = candidate["creative_baseline"]["baseline_digest"]
    review = {
        "report_type": "ReReviewReport",
        "selection_review_contract": "immutable-review-projection.v1",
        "selection_review_source_asset_version_id": "review:v1",
        "revision_version_id": "candidate:v1",
        "target_text_hash": prose_hash(candidate["text"]),
        "creative_baseline_digest": digest,
        "decision": "PASSED",
        "blocking_issue_count": 0,
        "score": review_score,
        "provider_evidence": {"real_model_call": True},
        "issues": [],
    }
    reports = [
        dict(
            project_id="project-1",
            dimension=name,
            gate_type="structural_quality_gate",
            target_asset_version_id="candidate:v1",
            score=80,
            weight=1,
            blocking=True,
            source="provider_judge",
            gate_status="PASSED",
            calibration_status="REFERENCE_CALIBRATED",
            evaluation_semantics_version="work-quality.v2",
            quality_policy_digest="policy:v1",
            creative_baseline_digest=digest,
        )
        for name in QUALITY_DIMENSIONS
    ]

    def run():
        return evaluate_quality_evidence(
            project_id="project-1",
            revision=candidate,
            revision_asset_version_id="candidate:v1",
            review=review,
            review_asset_version_id="review:v1",
            canon={"gate": "PASSED", "conflicts": []},
            canon_asset_version_id="canon:v1",
            context_bundle_version_id="context:v1",
            evidence_reports=reports,
        )

    result = run()
    assert result["aggregate_score"] == 80
    auxiliary = next(
        row for row in result["dimensions"] if row["dimension"] == "structural_evidence"
    )
    assert auxiliary["score"] is None and auxiliary["weight"] == 0
    assert (
        auxiliary["gate_status"] == "UNCALIBRATED"
        and auxiliary["evidence_status"] == "UNQUALIFIED"
    )
    assert result["gate"] == "PASSED_WITH_UNCALIBRATED"
    review.update(decision="FAILED", blocking_issue_count=1)
    failed = run()
    assert failed["gate"] == "FAILED" and failed["aggregate_score"] == 80
    action = next(
        row
        for row in failed["required_actions"]
        if row["observation"] == "structural_evidence"
    )
    assert action["required_action"] == "EVIDENCE_REASSESSMENT"
    assert action["permitted_change_scope"] == "EVIDENCE_ONLY"


def test_quality_schema_freezes_host_applicability_without_forcing_positive_evidence():
    from novel_forge.modules.chapter_quality_authority.applicability_contract import bind_quality_applicability_schema
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema, validate_chapter_provider_output_against_schema
    from novel_forge.modules.chapter_authority.execution_gateway import default_chapter_fixture_response
    from copy import deepcopy
    schema=chapter_provider_output_schema('quality_commercial',work_requirements=True)
    baseline={'method_requirements':{'golden_opening':{'status':'NOT_APPLICABLE'}}}
    bound=bind_quality_applicability_schema(schema,baseline,'commercial')
    original=deepcopy(schema)
    assert schema==original
    choices={b['properties']['dimension']['enum'][0]:b['properties']['gate_status']['enum'] for b in bound['properties']['dimensions']['items']['anyOf']}
    assert choices['golden_opening']==['NOT_APPLICABLE']
    assert 'NOT_APPLICABLE' not in choices['toxic_point']
    assert {'FAILED','INSUFFICIENT_EVIDENCE'} <= set(choices['toxic_point'])
    from novel_forge.modules.chapter_quality_authority.domain import QUALITY_GROUPS
    result=default_chapter_fixture_response('quality_commercial',{'revision':{'text':'她关上门。'},'dimensions':list(QUALITY_GROUPS['commercial'])})
    for item in result['dimensions']:
        item['evidence_locations']=[{'quote':'她关上门。','claim':'The narrated action is legible.'}]
        if item['dimension']=='golden_opening':
            item.update(gate_status='NOT_APPLICABLE',score=None,evidence_locations=[])
    validate_chapter_provider_output_against_schema('quality_commercial',bound,result)
    invalid=deepcopy(result)
    next(i for i in invalid['dimensions'] if i['dimension']=='toxic_point').update(gate_status='NOT_APPLICABLE',score=None,evidence_locations=[])
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema('quality_commercial',bound,invalid)
