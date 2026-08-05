from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    ReaderJudgeQualificationStatus,
    ReaderOutcomeDecisionPolicy,
    evaluate_reader_outcome_consumption,
    transition_reader_judge_qualification,
)


POLICY = ReaderOutcomeDecisionPolicy(
    policy_version="fixture-policy-v1",
    minimum_sample_size=3,
    minimum_confidence=0.8,
    minimum_consecutive_chapters=3,
    cooldown_chapters=2,
    maximum_adjustment_chapters=2,
)


def test_fixture_evidence_cannot_qualify_reader_judge() -> None:
    with pytest.raises(KernelError) as raised:
        transition_reader_judge_qualification(
            ReaderJudgeQualificationStatus.CALIBRATED,
            ReaderJudgeQualificationStatus.QUALIFIED,
            evidence_level="FIXTURE",
            sample_size=100,
            minimum_sample_size=3,
            drift_detected=False,
        )

    assert raised.value.code == "READER_JUDGE_QUALIFICATION_EVIDENCE_INSUFFICIENT"


def test_shadow_outcome_cannot_create_plan_adjustment_candidate() -> None:
    decision = evaluate_reader_outcome_consumption(
        qualification_status=ReaderJudgeQualificationStatus.SHADOW,
        sample_size=100,
        confidence=0.99,
        recent_reports=[{"declining": True}] * 3,
        current_chapter=10,
        last_adjustment_chapter=None,
        disagreement=False,
        position_bias=False,
        ood=False,
        drift_detected=False,
        policy=POLICY,
    )

    assert decision["decision"] == "SHADOW_ONLY"
    assert decision["future_production_influence_allowed"] is False
    assert "JUDGE_NOT_QUALIFIED" in decision["reasons"]


def test_qualified_trend_only_creates_bounded_human_approved_candidate() -> None:
    decision = evaluate_reader_outcome_consumption(
        qualification_status=ReaderJudgeQualificationStatus.QUALIFIED,
        sample_size=3,
        confidence=0.9,
        recent_reports=[{"declining": True}] * 3,
        current_chapter=10,
        last_adjustment_chapter=7,
        disagreement=False,
        position_bias=False,
        ood=False,
        drift_detected=False,
        policy=POLICY,
    )

    assert decision["decision"] == "PLAN_ADJUSTMENT_CANDIDATE"
    assert decision["future_production_influence_allowed"] is True
    assert decision["direct_plan_activation_allowed"] is False
    assert decision["human_approval_required"] is True
    assert decision["maximum_adjustment_chapters"] == 2
