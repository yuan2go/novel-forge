from __future__ import annotations

from dataclasses import replace

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


def _fixture(*, fixture_protocol_only: bool = False):
    humans = tuple(
        HumanEvaluation(
            evaluation_id=f"human:{number}",
            subject_asset_version_id="draft:v1",
            dimension="readability",
            status="PASSED",
            score=82,
            evaluator_id=f"editor:{number}",
            evaluator_group="EDITOR",
            evidence=({"span": [0, 10]},),
            blind=True,
            evaluation_asset_version_id=f"human-evaluation:v{number}",
        )
        for number in (1, 2)
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
        rationale="independent readers agree and cite supporting spans",
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
        model_id="model:1",
        prompt_version="prompt:quality:v3",
        prompt_hash="sha256:" + "1" * 64,
        result_asset_version_id="judge-evaluation:v1",
    )
    blind = BlindPairPreference(
        preference_id="preference:1",
        pair_id="pair:1",
        candidate_a_asset_version_id="draft:v1",
        candidate_b_asset_version_id="draft:v2",
        preferred_asset_version_id="draft:v1",
        evaluator_id="reader:1",
        presentation_order="BA",
        rationale="clearer causal progression",
        preference_asset_version_id="preference:v1",
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
    )
    run = CalibrationRun(
        run_id="calibration-run:v2",
        profile_version_id=profile.profile_version_id,
        dimension=profile.dimension,
        judge_evaluation_asset_version_ids=(judge.result_asset_version_id,),
        adjudicated_evaluation_asset_version_ids=(
            adjudication.adjudication_asset_version_id,
        ),
        human_evaluation_asset_version_ids=tuple(
            item.evaluation_asset_version_id for item in humans
        ),
        blind_pair_preference_asset_version_ids=(blind.preference_asset_version_id,),
        reader_outcome_evidence_asset_version_ids=(reader.evidence_asset_version_id,),
        fixture_protocol_only=fixture_protocol_only,
    )
    return profile, run, humans, adjudication, judge, blind, reader


def test_v2_separates_all_evidence_roles_and_profile_lineage() -> None:
    profile, run, humans, adjudication, judge, blind, reader = _fixture()
    result = evaluate_quality_calibration_v2(
        run=run,
        profile=profile,
        judge_evaluations=(judge,),
        human_evaluations=humans,
        adjudicated_evaluations=(adjudication,),
        blind_preferences=(blind,),
        reader_outcomes=(reader,),
    )
    assert result.contract_version == "quality-calibration-result-v2"
    assert result.calibration_status == "CALIBRATION_CANDIDATE"
    assert result.activation_allowed is True
    assert result.false_pass_count == 0
    assert result.blind_pair_evidence_count == 1
    assert result.reader_outcome_evidence_count == 1
    assert result.diagnostics["single_human_evaluation_is_ground_truth"] is False
    assert result.diagnostics["reader_outcome_can_mutate_narrative_truth"] is False
    assert result.production_verified is False


def test_subjective_adjudication_requires_two_independent_humans() -> None:
    with pytest.raises(ValueError, match="two independent"):
        AdjudicatedEvaluation(
            "adjudication:single",
            "draft:v1",
            "readability",
            "PASSED",
            (70, 90),
            ("human:v1",),
            "chief-editor",
            "one opinion is not ground truth",
            "adjudication:single:v1",
        )


def test_fixture_cannot_activate_and_lineage_drift_fails_closed() -> None:
    profile, run, humans, adjudication, judge, blind, reader = _fixture(
        fixture_protocol_only=True
    )
    result = evaluate_quality_calibration_v2(
        run=run,
        profile=profile,
        judge_evaluations=(judge,),
        human_evaluations=humans,
        adjudicated_evaluations=(adjudication,),
        blind_preferences=(blind,),
        reader_outcomes=(reader,),
    )
    assert result.activation_allowed is False
    with pytest.raises(KernelError) as raised:
        evaluate_quality_calibration_v2(
            run=replace(run, judge_evaluation_asset_version_ids=("drift:v1",)),
            profile=profile,
            judge_evaluations=(judge,),
            human_evaluations=humans,
            adjudicated_evaluations=(adjudication,),
            blind_preferences=(blind,),
            reader_outcomes=(reader,),
        )
    assert raised.value.code == "QUALITY_CALIBRATION_V2_INPUT_SET_CONFLICT"
