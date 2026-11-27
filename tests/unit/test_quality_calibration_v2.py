from __future__ import annotations

from dataclasses import replace
import importlib.util

import pytest

from novel_forge.modules.chapter_quality_authority import (
    AdjudicatedEvaluation,
    BlindPairPreference,
    CalibrationRun,
    HumanEvaluation,
    JudgeEvaluation,
    QualityProfileVersion,
    ReaderOutcomeEvidence,
    evaluate_quality_calibration_v2,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from novel_forge.modules.content_authority.handlers import CONTENT_DOMAIN_HANDLERS
from novel_forge.modules.reader_calibration import BLIND_EVALUATION_DIMENSIONS


PROTOCOL_VERSION = "human-blind-comparison-v1"
EVALUATION_VERSION = "editorial-pairwise-v1"


def test_reference_agreement_retains_false_pass_and_never_mints_calibration():
    from novel_forge.modules.chapter_quality_authority.reference_sampling import chapter_reference_agreement

    reference = {"labels": [{"dimension": "review_decision", "status": "NEEDS_REVISION", "score_range": [0, 100]}],
                 "production_qualification_eligible": False, "reference_basis": "ADJUDICATED_SUBJECTIVE_EVIDENCE"}
    result = chapter_reference_agreement(reference, stage="review", result={"decision": "PASSED"})
    assert result["status_accuracy"] == 0
    assert result["comparisons"][0]["observed_status"] == "PASSED"
    assert result["comparisons"][0]["score_in_range"] is None
    assert result["calibration_claim_allowed"] is False
    assert result["reader_preference_proven"] is False
    assert result["production_qualification_eligible"] is False


def test_reference_quality_compares_every_dimension_and_separates_status_from_score():
    from novel_forge.modules.chapter_quality_authority.reference_sampling import chapter_reference_agreement, reference_dimensions

    dimensions = reference_dimensions("quality_structural")
    reference = {"labels": [{"dimension": dimension, "status": "PASSED", "score_range": [75, 85]} for dimension in dimensions]}
    output = {"dimensions": [{"dimension": dimension, "gate_status": "PASSED", "score": 90} for dimension in dimensions]}
    result = chapter_reference_agreement(reference, stage="quality_structural", result=output)
    assert result["status_accuracy"] == 1
    assert not any(row["score_in_range"] for row in result["comparisons"])
    with pytest.raises(KernelError, match="QUALITY_REFERENCE_RESULT_INVALID"):
        chapter_reference_agreement(reference, stage="quality_structural", result={"dimensions": output["dimensions"][:-1]})
    output["dimensions"][-1] = output["dimensions"][0]
    with pytest.raises(KernelError, match="QUALITY_REFERENCE_RESULT_INVALID"):
        chapter_reference_agreement(reference, stage="quality_structural", result=output)


def _scores(a: int | None = 4, b: int | None = 3):
    return {dimension: {"a": a, "b": b} for dimension in BLIND_EVALUATION_DIMENSIONS}


def _preference(
    *,
    ordinal: int,
    evaluator_id: str,
    evaluator_role: str,
    evaluator_identity_class: str,
    choice: str,
    candidate_a: str = "draft:v1",
    candidate_b: str = "draft:v2",
    presentation_order: str = "AB",
    scores=None,
) -> BlindPairPreference:
    return BlindPairPreference(
        preference_id=f"preference:{ordinal}:{evaluator_id}",
        pair_id=f"pair:{ordinal}:{evaluator_id}",
        subject_id=f"subject:{ordinal}",
        candidate_a_asset_version_id=candidate_a,
        candidate_b_asset_version_id=candidate_b,
        choice=choice,
        evaluator_id=evaluator_id,
        evaluator_role=evaluator_role,
        evaluator_identity_class=evaluator_identity_class,
        protocol_version=PROTOCOL_VERSION,
        evaluation_version=EVALUATION_VERSION,
        scope_type="CHAPTER",
        chapter_start=ordinal,
        chapter_end=ordinal,
        presentation_order=presentation_order,
        dimension_scores=scores or _scores(),
        confidence=0.8,
        rationale="The chosen version has clearer causal progression.",
        preference_asset_version_id=f"preference-asset:{ordinal}:{evaluator_id}",
    )


def _fixture(*, fixture_protocol_only: bool = False):
    humans = (
        HumanEvaluation(
            evaluation_id="human:1",
            subject_asset_version_id="draft:v1",
            dimension="readability",
            status="PASSED",
            score=82,
            evaluator_id="editor:1",
            evaluator_group="EDITORIAL_PANEL",
            evaluator_identity_class="PROFESSIONAL_EDITOR",
            protocol_version=PROTOCOL_VERSION,
            evaluation_version=EVALUATION_VERSION,
            scope_type="CHAPTER",
            chapter_start=1,
            chapter_end=1,
            confidence=0.8,
            evidence=({"span": [0, 10]},),
            blind=True,
            evaluation_asset_version_id="human-evaluation:v1",
        ),
        HumanEvaluation(
            evaluation_id="human:2",
            subject_asset_version_id="draft:v1",
            dimension="readability",
            status="PASSED",
            score=84,
            evaluator_id="reader:2",
            evaluator_group="EDITORIAL_PANEL",
            evaluator_identity_class="EXPERIENCED_READER",
            protocol_version=PROTOCOL_VERSION,
            evaluation_version=EVALUATION_VERSION,
            scope_type="CHAPTER",
            chapter_start=1,
            chapter_end=1,
            confidence=0.7,
            evidence=({"span": [12, 24]},),
            blind=True,
            evaluation_asset_version_id="human-evaluation:v2",
        ),
    )
    adjudication = AdjudicatedEvaluation(
        adjudication_id="adjudication:1",
        subject_asset_version_id="draft:v1",
        dimension="readability",
        status="PASSED",
        score_range=(78, 90),
        source_human_evaluation_asset_version_ids=tuple(
            item.evaluation_asset_version_id for item in humans
        ),
        adjudicator_id="chief-editor:1",
        adjudicator_identity_class="PROFESSIONAL_EDITOR",
        protocol_version=PROTOCOL_VERSION,
        evaluation_version=EVALUATION_VERSION,
        scope_type="CHAPTER",
        chapter_start=1,
        chapter_end=1,
        rationale="Two independent subjective evaluations were preserved.",
        adjudication_asset_version_id="adjudication:v1",
    )
    judge = JudgeEvaluation(
        evaluation_id="judge:1",
        subject_asset_version_id="draft:v1",
        dimension="readability",
        status="PASSED",
        score=84,
        confidence=0.91,
        evaluator_id="judge-profile:1",
        provider_id="provider:judge",
        model_id="model:judge",
        generator_provider_id="provider:generator",
        generator_model_id="model:generator",
        reviewer_provider_id="provider:reviewer",
        reviewer_model_id="model:reviewer",
        prompt_version="prompt:quality:v3",
        prompt_hash="sha256:" + "1" * 64,
        result_asset_version_id="judge-evaluation:v1",
    )
    blind = (
        _preference(
            ordinal=1,
            evaluator_id="editor:1",
            evaluator_role="HUMAN",
            evaluator_identity_class="PROFESSIONAL_EDITOR",
            choice="A",
        ),
        _preference(
            ordinal=1,
            evaluator_id="reader:2",
            evaluator_role="HUMAN",
            evaluator_identity_class="EXPERIENCED_READER",
            choice="B",
            candidate_a="draft:v2",
            candidate_b="draft:v1",
            presentation_order="BA",
            scores=_scores(3, 4),
        ),
        _preference(
            ordinal=1,
            evaluator_id="judge-profile:1",
            evaluator_role="AUTOMATED_JUDGE",
            evaluator_identity_class="MODEL_JUDGE",
            choice="A",
        ),
    )
    reader = ReaderOutcomeEvidence(
        evidence_id="reader-outcome:1",
        subject_asset_version_id="draft:v1",
        metric_type="COMPLETION",
        exposure_count=120,
        outcome_count=96,
        reader_segment="serial-readers",
        platform="fixture-platform",
        evidence_asset_version_id="reader-outcome:v1",
    )
    profile = QualityProfileVersion(
        profile_version_id="quality-profile:v2",
        profile_id="quality-profile",
        version=2,
        dimension="readability",
        threshold_policy_version_id="threshold-policy:v2",
        thresholds={
            "minimum_sample_count": 1,
            "minimum_status_accuracy": 1.0,
            "maximum_false_pass_count": 0,
        },
        judge_profile_ref="judge-profile:1",
        judge_profile_hash="sha256:" + "2" * 64,
        judge_provider_id="provider:judge",
        judge_model_id="model:judge",
    )
    run = CalibrationRun(
        run_id="calibration-run:v2",
        profile_version_id=profile.profile_version_id,
        dimension=profile.dimension,
        protocol_version=PROTOCOL_VERSION,
        evaluation_version=EVALUATION_VERSION,
        evidence_scope="BOUNDED_EVIDENCE",
        judge_evaluation_asset_version_ids=(judge.result_asset_version_id,),
        adjudicated_evaluation_asset_version_ids=(
            adjudication.adjudication_asset_version_id,
        ),
        human_evaluation_asset_version_ids=tuple(
            item.evaluation_asset_version_id for item in humans
        ),
        blind_pair_preference_asset_version_ids=tuple(
            item.preference_asset_version_id for item in blind
        ),
        reader_outcome_evidence_asset_version_ids=(reader.evidence_asset_version_id,),
        fixture_protocol_only=fixture_protocol_only,
    )
    return profile, run, humans, adjudication, judge, blind, reader


def _evaluate(fixture):
    profile, run, humans, adjudication, judge, blind, reader = fixture
    return evaluate_quality_calibration_v2(
        run=run,
        profile=profile,
        judge_evaluations=(judge,),
        human_evaluations=humans,
        adjudicated_evaluations=(adjudication,),
        blind_preferences=blind,
        reader_outcomes=(reader,),
    )


def test_bounded_v2_separates_roles_but_never_activates_profile() -> None:
    result = _evaluate(_fixture())

    assert result.contract_version == "quality-calibration-result-v2"
    assert result.calibration_status == "UNCALIBRATED"
    assert result.evidence_status == "BOUNDED_EVIDENCE"
    assert result.activation_allowed is False
    assert result.status_accuracy == 1
    assert result.false_pass_count == 0
    assert result.blind_pair_evidence_count == 3
    assert result.reader_outcome_evidence_count == 1
    assert result.independence_status == "CROSS_PROVIDER_DISTINCT_MODEL"
    assert result.diagnostics["pairwise_agreement"]["agreement_rate"] == 1
    assert result.diagnostics["weighted_ordinal_agreement"]["agreement"] == 1
    assert result.diagnostics["position_bias"]["HUMAN"]["a_choice_rate"] == 0.5
    assert result.diagnostics["single_human_evaluation_is_ground_truth"] is False
    assert result.diagnostics["reader_outcome_can_mutate_narrative_truth"] is False
    assert result.production_verified is False


@pytest.mark.parametrize("choice", ["A", "B", "TIE", "CANNOT_JUDGE"])
def test_pair_protocol_supports_all_frozen_choices(choice: str) -> None:
    scores = _scores(None, None) if choice == "CANNOT_JUDGE" else _scores()
    preference = _preference(
        ordinal=1,
        evaluator_id="editor:1",
        evaluator_role="HUMAN",
        evaluator_identity_class="PROFESSIONAL_EDITOR",
        choice=choice,
        scores=scores,
    )
    assert preference.choice == choice


def test_pair_protocol_rejects_dimension_scope_confidence_and_identity_drift() -> None:
    base = _preference(
        ordinal=1,
        evaluator_id="editor:1",
        evaluator_role="HUMAN",
        evaluator_identity_class="PROFESSIONAL_EDITOR",
        choice="A",
    )
    with pytest.raises(ValueError, match="frozen dimensions"):
        replace(base, dimension_scores={"readability": {"a": 4, "b": 3}})
    with pytest.raises(ValueError, match="Chapter scope"):
        replace(base, chapter_end=2)
    with pytest.raises(ValueError, match="confidence"):
        replace(base, confidence=1.1)
    with pytest.raises(ValueError, match="evaluator identity"):
        replace(base, evaluator_identity_class="")


def test_subjective_adjudication_requires_two_distinct_blind_humans() -> None:
    profile, run, humans, adjudication, judge, blind, reader = _fixture()
    duplicate_identity = replace(humans[1], evaluator_id=humans[0].evaluator_id)
    with pytest.raises(KernelError) as raised:
        evaluate_quality_calibration_v2(
            run=run,
            profile=profile,
            judge_evaluations=(judge,),
            human_evaluations=(humans[0], duplicate_identity),
            adjudicated_evaluations=(adjudication,),
            blind_preferences=blind,
            reader_outcomes=(reader,),
        )
    assert raised.value.code == "QUALITY_ADJUDICATION_INDEPENDENCE_REQUIRED"


@pytest.mark.parametrize(
    ("judge", "expected"),
    [
        (
            {
                "generator_provider_id": "provider:judge",
                "generator_model_id": "model:judge",
            },
            "SAME_MODEL",
        ),
        (
            {
                "generator_provider_id": "provider:judge",
                "generator_model_id": "model:other",
            },
            "SAME_PROVIDER",
        ),
    ],
)
def test_same_model_or_provider_is_explicit_and_cannot_activate(
    judge: dict[str, str], expected: str
) -> None:
    profile, run, humans, adjudication, current, blind, reader = _fixture()
    result = evaluate_quality_calibration_v2(
        run=run,
        profile=profile,
        judge_evaluations=(replace(current, **judge),),
        human_evaluations=humans,
        adjudicated_evaluations=(adjudication,),
        blind_preferences=blind,
        reader_outcomes=(reader,),
    )
    assert result.independence_status == expected
    assert result.diagnostics["independent_activation_eligible"] is False
    assert result.activation_allowed is False


def test_diagnostics_report_small_sample_limits_without_threshold_games() -> None:
    result = _evaluate(_fixture(fixture_protocol_only=True))

    assert result.calibration_status == "UNCALIBRATED"
    assert result.evidence_status == "BOUNDED_EVIDENCE"
    assert result.diagnostics["rank_correlation"]["status"] == "NOT_ESTIMABLE"
    assert result.diagnostics["preference_stability"]["status"] == "NOT_ESTIMABLE"
    assert result.diagnostics["confidence_calibration"]["bins"]
    assert result.diagnostics["false_positive_negative"] == {
        "false_positive_count": 0,
        "false_negative_count": 0,
    }


def test_lineage_drift_fails_closed() -> None:
    profile, run, humans, adjudication, judge, blind, reader = _fixture()
    with pytest.raises(KernelError) as raised:
        evaluate_quality_calibration_v2(
            run=replace(run, judge_evaluation_asset_version_ids=("drift:v1",)),
            profile=profile,
            judge_evaluations=(judge,),
            human_evaluations=humans,
            adjudicated_evaluations=(adjudication,),
            blind_preferences=blind,
            reader_outcomes=(reader,),
        )
    assert raised.value.code == "QUALITY_CALIBRATION_V2_INPUT_SET_CONFLICT"


def test_v1_calibration_is_not_a_current_content_authority() -> None:
    legacy_operations = {
        "quality.golden_sample.create",
        "quality.human_decision.record",
        "quality.calibration.run",
        "quality.calibration.profile.promote",
        "quality.calibration.profile.revoke",
    }
    assert legacy_operations.isdisjoint(CONTENT_CODECS)
    assert legacy_operations.isdisjoint(CONTENT_DOMAIN_HANDLERS)
    assert (
        importlib.util.find_spec(
            "novel_forge.modules.chapter_quality_authority.calibration"
        )
        is None
    )


@pytest.mark.parametrize("stage", ["quality_structural", "canon_support"])
def test_new_quality_call_requires_its_qualified_reference_route_and_unchanged_served_model(stage):
    from copy import deepcopy
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash, task_policy
    from novel_forge.modules.chapter_quality_authority.reference_sampling import reference_decision_qualifies
    from tests.unit.test_cost_aware_routing import candidate, samples, task, route

    current = task(task_type=stage, producer_contract={"fixture": "exact-producer-v1"},
        producer_contract_hash=snapshot_hash({"fixture": "exact-producer-v1"}))
    model = candidate(model_revision="revision-1")
    observations = [replace(row, evidence_class="REFERENCE_EVALUATION", production_eligible=False,
        quality_score=None, accepted=None, reference_agreed=True, reference_label_classes=("PASS" if i % 2 else "FAIL",),
        reference_risk=task_policy(stage).risk, reference_context_tokens=1000, reference_protocol_hash="sha256:" + "d" * 64,
        served_model_identity_hash="sha256:" + "e" * 64, outcome_refs=("asset-version:reference:" + str(i),))
        for i, row in enumerate(samples(n=160))]
    frozen = route(current, [model], {"flash": observations})
    evidence = {"real_model_call": True, "provider_id": model.provider, "model_id": model.model,
        "production_execution": {"execution_request": {key: frozen["task"][key] for key in ("project_id", "operation_id", "attempt_id")},
            "execution_result": {"outcome": "SUCCEEDED"}, "route_snapshot": {"reasoning_effort": model.reasoning},
            "process_evidence": {"model_revision": model.model_revision, "served_model_identity_hash": "sha256:" + "e" * 64}}}
    assert reference_decision_qualifies(frozen, evidence=evidence, stage=current.task_type)
    legacy = {**frozen, "schema_version": "quality-constrained-routing.v10", "policy_version": "quality-constrained-routing.v10"}
    assert reference_decision_qualifies(legacy, evidence=evidence, stage=current.task_type) is (stage != "canon_support")
    previous = deepcopy(frozen)
    previous.update(schema_version="quality-constrained-routing.v12", policy_version="quality-constrained-routing.v12")
    previous["policy"].pop("retain_failed_domain_samples")
    unchanged = deepcopy(previous)
    assert reference_decision_qualifies(previous, evidence=evidence, stage=stage)
    assert previous == unchanged
    previous["schema_version"] = "quality-constrained-routing.v120"
    assert not reference_decision_qualifies(previous, evidence=evidence, stage=stage)
    for mutation in ("sampling", "missing-protocol", "missing-stratum", "wrong-task", "changed-producer", "lowered-policy"):
        invalid = deepcopy(frozen)
        if mutation == "sampling":
            invalid.update(status="BENCHMARK_SELECTED", bootstrap_authorization={"authorization_id": "fixture"})
        elif mutation == "missing-protocol":
            invalid["selected"]["benchmark"]["reference_protocol_hashes"] = []
        elif mutation == "missing-stratum":
            invalid["selected"]["benchmark"]["reference_label_strata"]["FAIL"]["sample_count"] = 0
        elif mutation == "wrong-task":
            invalid["task"]["task_type"] = "quality_commercial"
        elif mutation == "changed-producer":
            invalid["task"]["producer_contract"] = {"fixture": "changed"}
        else:
            invalid["policy"]["minimum_samples"] = 0
        assert not reference_decision_qualifies(invalid, evidence=evidence, stage=current.task_type)
    for mutation in ("fixture", "model", "fingerprint", "revision", "operation", "reasoning"):
        invalid = deepcopy(evidence)
        if mutation == "fixture":
            invalid["real_model_call"] = False
        elif mutation == "model":
            invalid["model_id"] = "another-model"
        elif mutation in {"fingerprint", "revision"}:
            invalid["production_execution"]["process_evidence"]["served_model_identity_hash" if mutation == "fingerprint" else "model_revision"] = "changed"
        elif mutation == "operation":
            invalid["production_execution"]["execution_request"]["operation_id"] = "another-operation"
        else:
            invalid["production_execution"]["route_snapshot"]["reasoning_effort"] = "max"
        assert not reference_decision_qualifies(frozen, evidence=invalid, stage=current.task_type)


def test_quality_context_cannot_self_assert_reference_calibration_or_retarget_a_receipt():
    from copy import deepcopy
    from novel_forge.modules.chapter_quality_authority.domain import build_quality_group_evidence

    receipt = {"schema_version": "chapter-reference-calibration.v1", "stage": "quality_source_originality",
        "target_asset_version_id": "draft-target", "operation_id": "native-quality-operation"}
    context = {"context_segments": [{"asset_version_id": "external-effect:native-quality-operation",
        "structured_facts": [{"key": "dimension_evidence", "value": [{"dimension": "originality",
            "target_asset_version_id": "draft-target", "gate_status": "PASSED", "score": 90,
            "provider_verified": True, "calibration_status": "REFERENCE_CALIBRATED"}]}]}]}
    inputs = dict(group="source_originality", project_id="project", revision={"text": "The choice creates a consequence."},
        revision_asset_version_id="draft-target", context_bundle=context, canon={}, fixture=False)
    def originality(report):
        return next(row for row in report["dimensions"] if row["dimension"] == "originality")
    assert originality(build_quality_group_evidence(**inputs))["gate_status"] != "PASSED"
    report = build_quality_group_evidence(**inputs, reference_calibration=receipt)
    assert originality(report)["gate_status"] == "PASSED"
    assert originality(report)["calibration_status"] == "REFERENCE_CALIBRATED"
    assert originality(report)["reference_calibration"] == receipt
    assert not report["human_verified"] and not report["production_verified"]
    forged_context = deepcopy(context)
    forged_context["context_segments"][0]["asset_version_id"] = "arbitrary-context-claim"
    assert originality(build_quality_group_evidence(**{**inputs, "context_bundle": forged_context}, reference_calibration=receipt))["gate_status"] != "PASSED"
    for invalid in ({**receipt, "target_asset_version_id": "other-target"}, {**receipt, "stage": "quality_commercial"}):
        with pytest.raises(KernelError, match="QUALITY_REFERENCE_SCOPE_INVALID"):
            build_quality_group_evidence(**inputs, reference_calibration=invalid)
    with pytest.raises(KernelError, match="QUALITY_REFERENCE_SCOPE_INVALID"):
        build_quality_group_evidence(**{**inputs, "fixture": True}, reference_calibration=receipt)
