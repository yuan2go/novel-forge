"""Versioned quality calibration with explicit evidence-role separation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


@dataclass(frozen=True, slots=True)
class JudgeEvaluation:
    evaluation_id: str
    subject_asset_version_id: str
    dimension: str
    status: str
    score: float | None
    confidence: float
    evaluator_id: str
    model_id: str
    prompt_version: str
    prompt_hash: str
    result_asset_version_id: str

    def __post_init__(self) -> None:
        if (
            any(
                not str(value).strip()
                for value in (
                    self.evaluation_id,
                    self.subject_asset_version_id,
                    self.dimension,
                    self.status,
                    self.evaluator_id,
                    self.model_id,
                    self.prompt_version,
                    self.prompt_hash,
                    self.result_asset_version_id,
                )
            )
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("JudgeEvaluation provenance is incomplete")


@dataclass(frozen=True, slots=True)
class HumanEvaluation:
    evaluation_id: str
    subject_asset_version_id: str
    dimension: str
    status: str
    score: float | None
    evaluator_id: str
    evaluator_group: str
    evidence: tuple[Mapping[str, Any], ...]
    blind: bool
    evaluation_asset_version_id: str

    def __post_init__(self) -> None:
        if any(
            not str(value).strip()
            for value in (
                self.evaluation_id,
                self.subject_asset_version_id,
                self.dimension,
                self.status,
                self.evaluator_id,
                self.evaluator_group,
                self.evaluation_asset_version_id,
            )
        ):
            raise ValueError("HumanEvaluation lineage is incomplete")


@dataclass(frozen=True, slots=True)
class BlindPairPreference:
    preference_id: str
    pair_id: str
    candidate_a_asset_version_id: str
    candidate_b_asset_version_id: str
    preferred_asset_version_id: str
    evaluator_id: str
    presentation_order: str
    rationale: str
    preference_asset_version_id: str

    def __post_init__(self) -> None:
        candidates = {
            self.candidate_a_asset_version_id,
            self.candidate_b_asset_version_id,
        }
        if (
            len(candidates) != 2
            or self.preferred_asset_version_id not in candidates
            or self.presentation_order not in {"AB", "BA"}
            or any(
                not str(value).strip()
                for value in (
                    self.preference_id,
                    self.pair_id,
                    self.evaluator_id,
                    self.rationale,
                    self.preference_asset_version_id,
                )
            )
        ):
            raise ValueError("BlindPairPreference identity is invalid")


@dataclass(frozen=True, slots=True)
class AdjudicatedEvaluation:
    adjudication_id: str
    subject_asset_version_id: str
    dimension: str
    status: str
    score_range: tuple[float, float]
    source_human_evaluation_asset_version_ids: tuple[str, ...]
    adjudicator_id: str
    rationale: str
    adjudication_asset_version_id: str

    def __post_init__(self) -> None:
        low, high = self.score_range
        if (
            len(set(self.source_human_evaluation_asset_version_ids)) < 2
            or low < 0
            or high > 100
            or low > high
            or any(
                not str(value).strip()
                for value in (
                    self.adjudication_id,
                    self.subject_asset_version_id,
                    self.dimension,
                    self.status,
                    self.adjudicator_id,
                    self.rationale,
                    self.adjudication_asset_version_id,
                )
            )
        ):
            raise ValueError(
                "AdjudicatedEvaluation requires two independent HumanEvaluations"
            )


@dataclass(frozen=True, slots=True)
class ReaderOutcomeEvidence:
    evidence_id: str
    subject_asset_version_id: str
    metric_type: str
    exposure_count: int
    outcome_count: int
    reader_segment: str
    platform: str
    evidence_asset_version_id: str

    def __post_init__(self) -> None:
        if (
            self.exposure_count <= 0
            or self.outcome_count < 0
            or self.outcome_count > self.exposure_count
            or any(
                not str(value).strip()
                for value in (
                    self.evidence_id,
                    self.subject_asset_version_id,
                    self.metric_type,
                    self.reader_segment,
                    self.platform,
                    self.evidence_asset_version_id,
                )
            )
        ):
            raise ValueError(
                "ReaderOutcomeEvidence requires a valid exposure denominator"
            )


@dataclass(frozen=True, slots=True)
class QualityProfileVersion:
    profile_version_id: str
    profile_id: str
    version: int
    dimension: str
    threshold_policy_version_id: str
    thresholds: Mapping[str, float]
    judge_profile_ref: str
    judge_profile_hash: str
    previous_profile_version_id: str = ""
    status: str = "CANDIDATE"

    def __post_init__(self) -> None:
        if (
            self.version <= 0
            or self.status not in {"CANDIDATE", "ACTIVE", "STALE", "REVOKED"}
            or any(
                not str(value).strip()
                for value in (
                    self.profile_version_id,
                    self.profile_id,
                    self.dimension,
                    self.threshold_policy_version_id,
                    self.judge_profile_ref,
                    self.judge_profile_hash,
                )
            )
        ):
            raise ValueError("QualityProfileVersion identity is incomplete")


@dataclass(frozen=True, slots=True)
class CalibrationRun:
    run_id: str
    profile_version_id: str
    dimension: str
    judge_evaluation_asset_version_ids: tuple[str, ...]
    adjudicated_evaluation_asset_version_ids: tuple[str, ...]
    human_evaluation_asset_version_ids: tuple[str, ...] = ()
    blind_pair_preference_asset_version_ids: tuple[str, ...] = ()
    reader_outcome_evidence_asset_version_ids: tuple[str, ...] = ()
    fixture_protocol_only: bool = False


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    run_id: str
    profile_version_id: str
    dimension: str
    sample_count: int
    status_accuracy: float
    score_in_range_rate: float
    false_pass_count: int
    false_reject_count: int
    judge_disagreement_count: int
    blind_pair_evidence_count: int
    reader_outcome_evidence_count: int
    calibration_status: str
    source_manifest_hash: str
    activation_allowed: bool
    production_verified: bool = False
    contract_version: str = "quality-calibration-result-v2"
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def evaluate_quality_calibration_v2(
    *,
    run: CalibrationRun,
    profile: QualityProfileVersion,
    judge_evaluations: tuple[JudgeEvaluation, ...],
    human_evaluations: tuple[HumanEvaluation, ...],
    adjudicated_evaluations: tuple[AdjudicatedEvaluation, ...],
    blind_preferences: tuple[BlindPairPreference, ...] = (),
    reader_outcomes: tuple[ReaderOutcomeEvidence, ...] = (),
) -> CalibrationResult:
    """Evaluate Judges only against adjudication, never one subjective annotator."""

    if (
        run.profile_version_id != profile.profile_version_id
        or run.dimension != profile.dimension
    ):
        raise KernelError(
            "QUALITY_CALIBRATION_V2_PROFILE_CONFLICT",
            "CalibrationRun does not target the frozen QualityProfileVersion",
        )
    _require_exact_set(
        "judge",
        run.judge_evaluation_asset_version_ids,
        tuple(item.result_asset_version_id for item in judge_evaluations),
    )
    _require_exact_set(
        "adjudicated",
        run.adjudicated_evaluation_asset_version_ids,
        tuple(item.adjudication_asset_version_id for item in adjudicated_evaluations),
    )
    _require_exact_set(
        "human",
        run.human_evaluation_asset_version_ids,
        tuple(item.evaluation_asset_version_id for item in human_evaluations),
    )
    _require_exact_set(
        "blind pair",
        run.blind_pair_preference_asset_version_ids,
        tuple(item.preference_asset_version_id for item in blind_preferences),
    )
    _require_exact_set(
        "reader outcome",
        run.reader_outcome_evidence_asset_version_ids,
        tuple(item.evidence_asset_version_id for item in reader_outcomes),
    )
    human_ids = {item.evaluation_asset_version_id for item in human_evaluations}
    for adjudication in adjudicated_evaluations:
        if not set(adjudication.source_human_evaluation_asset_version_ids).issubset(
            human_ids
        ):
            raise KernelError(
                "QUALITY_ADJUDICATION_SOURCE_MISSING",
                "adjudication references HumanEvaluation outside the frozen run",
            )
    adjudicated = {
        (item.subject_asset_version_id, item.dimension): item
        for item in adjudicated_evaluations
    }
    if len(adjudicated) != len(adjudicated_evaluations):
        raise KernelError(
            "QUALITY_ADJUDICATION_DUPLICATE",
            "frozen run has multiple adjudications for one subject and dimension",
        )
    correct = score_in_range = false_pass = false_reject = disagreement = 0
    for judge in judge_evaluations:
        key = (judge.subject_asset_version_id, judge.dimension)
        reference = adjudicated.get(key)
        if reference is None:
            raise KernelError(
                "QUALITY_JUDGE_REFERENCE_MISSING",
                "JudgeEvaluation has no AdjudicatedEvaluation reference",
            )
        correct += int(judge.status == reference.status)
        if judge.score is not None:
            score_in_range += int(
                reference.score_range[0] <= judge.score <= reference.score_range[1]
            )
        false_pass += int(judge.status == "PASSED" and reference.status != "PASSED")
        false_reject += int(judge.status != "PASSED" and reference.status == "PASSED")
        disagreement += int(judge.status != reference.status)
    count = len(judge_evaluations)
    minimum_samples = int(profile.thresholds.get("minimum_sample_count", 1))
    minimum_accuracy = float(profile.thresholds.get("minimum_status_accuracy", 1.0))
    maximum_false_pass = int(profile.thresholds.get("maximum_false_pass_count", 0))
    accuracy = correct / count if count else 0.0
    score_rate = score_in_range / count if count else 0.0
    passes = (
        count >= minimum_samples
        and accuracy >= minimum_accuracy
        and false_pass <= maximum_false_pass
        and not run.fixture_protocol_only
        and profile.status == "CANDIDATE"
    )
    manifest = {
        "run": run.__dict__ if hasattr(run, "__dict__") else _slots_dict(run),
        "profile_version_id": profile.profile_version_id,
        "judge_ids": list(run.judge_evaluation_asset_version_ids),
        "human_ids": list(run.human_evaluation_asset_version_ids),
        "adjudication_ids": list(run.adjudicated_evaluation_asset_version_ids),
        "blind_pair_ids": list(run.blind_pair_preference_asset_version_ids),
        "reader_outcome_ids": list(run.reader_outcome_evidence_asset_version_ids),
    }
    return CalibrationResult(
        run_id=run.run_id,
        profile_version_id=profile.profile_version_id,
        dimension=run.dimension,
        sample_count=count,
        status_accuracy=accuracy,
        score_in_range_rate=score_rate,
        false_pass_count=false_pass,
        false_reject_count=false_reject,
        judge_disagreement_count=disagreement,
        blind_pair_evidence_count=len(blind_preferences),
        reader_outcome_evidence_count=len(reader_outcomes),
        calibration_status="CALIBRATION_CANDIDATE" if passes else "UNCALIBRATED",
        source_manifest_hash=_hash(manifest),
        activation_allowed=passes,
        production_verified=False,
        diagnostics={
            "single_human_evaluation_is_ground_truth": False,
            "subjective_reference_source": "ADJUDICATED_EVALUATION",
            "reader_outcome_can_mutate_narrative_truth": False,
            "fixture_protocol_only": run.fixture_protocol_only,
        },
    )


def _require_exact_set(
    label: str, expected: tuple[str, ...], actual: tuple[str, ...]
) -> None:
    if (
        len(expected) != len(set(expected))
        or set(expected) != set(actual)
        or len(expected) != len(actual)
    ):
        raise KernelError(
            "QUALITY_CALIBRATION_V2_INPUT_SET_CONFLICT",
            f"CalibrationRun {label} evidence differs from frozen inputs",
        )


def _slots_dict(value: Any) -> dict[str, Any]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _hash(value: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


__all__ = [
    "AdjudicatedEvaluation",
    "BlindPairPreference",
    "CalibrationResult",
    "CalibrationRun",
    "HumanEvaluation",
    "JudgeEvaluation",
    "QualityProfileVersion",
    "ReaderOutcomeEvidence",
    "evaluate_quality_calibration_v2",
]
