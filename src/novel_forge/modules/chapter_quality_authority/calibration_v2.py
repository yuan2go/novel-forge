"""Canonical v2 Judge calibration with bounded-evidence semantics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import math
from statistics import fmean
from typing import Any, Iterable, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration.domain import (
    BLIND_EVALUATION_DIMENSIONS,
)


PAIR_CHOICES = frozenset({"A", "B", "TIE", "CANNOT_JUDGE"})
EVALUATOR_ROLES = frozenset({"HUMAN", "AUTOMATED_JUDGE"})
EVALUATION_SCOPES = frozenset({"CHAPTER", "ARC"})
BOUNDED_EVIDENCE = "BOUNDED_EVIDENCE"


def _require_scope(scope_type: str, chapter_start: int, chapter_end: int) -> None:
    if (
        scope_type not in EVALUATION_SCOPES
        or chapter_start <= 0
        or chapter_end < chapter_start
    ):
        raise ValueError("evaluation scope is invalid")
    if scope_type == "CHAPTER" and chapter_start != chapter_end:
        raise ValueError("Chapter scope must cover exactly one chapter")


@dataclass(frozen=True, slots=True)
class JudgeEvaluation:
    evaluation_id: str
    subject_asset_version_id: str
    dimension: str
    status: str
    score: float | None
    confidence: float
    evaluator_id: str
    provider_id: str
    model_id: str
    generator_provider_id: str
    generator_model_id: str
    reviewer_provider_id: str
    reviewer_model_id: str
    prompt_version: str
    prompt_hash: str
    result_asset_version_id: str

    def __post_init__(self) -> None:
        required = (
            self.evaluation_id,
            self.subject_asset_version_id,
            self.dimension,
            self.status,
            self.evaluator_id,
            self.provider_id,
            self.model_id,
            self.generator_provider_id,
            self.generator_model_id,
            self.reviewer_provider_id,
            self.reviewer_model_id,
            self.prompt_version,
            self.prompt_hash,
            self.result_asset_version_id,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("JudgeEvaluation provenance is incomplete")
        if not 0 <= self.confidence <= 1:
            raise ValueError("JudgeEvaluation confidence is outside [0,1]")
        if self.score is not None and not 0 <= self.score <= 100:
            raise ValueError("JudgeEvaluation score is outside [0,100]")
        if not self.prompt_hash.startswith("sha256:"):
            raise ValueError("JudgeEvaluation prompt hash is invalid")


@dataclass(frozen=True, slots=True)
class HumanEvaluation:
    evaluation_id: str
    subject_asset_version_id: str
    dimension: str
    status: str
    score: float | None
    evaluator_id: str
    evaluator_group: str
    evaluator_identity_class: str
    protocol_version: str
    evaluation_version: str
    scope_type: str
    chapter_start: int
    chapter_end: int
    confidence: float
    evidence: tuple[Mapping[str, Any], ...]
    blind: bool
    evaluation_asset_version_id: str

    def __post_init__(self) -> None:
        required = (
            self.evaluation_id,
            self.subject_asset_version_id,
            self.dimension,
            self.status,
            self.evaluator_id,
            self.evaluator_group,
            self.evaluator_identity_class,
            self.protocol_version,
            self.evaluation_version,
            self.evaluation_asset_version_id,
        )
        if any(not str(value).strip() for value in required):
            raise ValueError("HumanEvaluation lineage is incomplete")
        _require_scope(self.scope_type, self.chapter_start, self.chapter_end)
        if not 0 <= self.confidence <= 1:
            raise ValueError("HumanEvaluation confidence is outside [0,1]")
        if self.score is not None and not 0 <= self.score <= 100:
            raise ValueError("HumanEvaluation score is outside [0,100]")
        if any(not isinstance(item, Mapping) for item in self.evidence):
            raise ValueError("HumanEvaluation evidence must be structured")


@dataclass(frozen=True, slots=True)
class BlindPairPreference:
    preference_id: str
    pair_id: str
    subject_id: str
    candidate_a_asset_version_id: str
    candidate_b_asset_version_id: str
    choice: str
    evaluator_id: str
    evaluator_role: str
    evaluator_identity_class: str
    protocol_version: str
    evaluation_version: str
    scope_type: str
    chapter_start: int
    chapter_end: int
    presentation_order: str
    dimension_scores: Mapping[str, Mapping[str, int | None]]
    confidence: float
    rationale: str
    preference_asset_version_id: str

    def __post_init__(self) -> None:
        candidates = {
            self.candidate_a_asset_version_id,
            self.candidate_b_asset_version_id,
        }
        if not str(self.evaluator_identity_class).strip():
            raise ValueError("blind pair evaluator identity is invalid")
        required = (
            self.preference_id,
            self.pair_id,
            self.subject_id,
            self.evaluator_id,
            self.protocol_version,
            self.evaluation_version,
            self.rationale,
            self.preference_asset_version_id,
        )
        if len(candidates) != 2 or any(not str(value).strip() for value in required):
            raise ValueError("BlindPairPreference identity is invalid")
        if self.choice not in PAIR_CHOICES:
            raise ValueError("blind pair choice is invalid")
        if self.evaluator_role not in EVALUATOR_ROLES:
            raise ValueError("blind pair evaluator identity is invalid")
        if self.presentation_order not in {"AB", "BA"}:
            raise ValueError("blind pair ordering is invalid")
        _require_scope(self.scope_type, self.chapter_start, self.chapter_end)
        if not 0 <= self.confidence <= 1:
            raise ValueError("blind pair confidence is outside [0,1]")
        if set(self.dimension_scores) != set(BLIND_EVALUATION_DIMENSIONS):
            raise ValueError("dimension_scores differ from frozen dimensions")
        for dimension in BLIND_EVALUATION_DIMENSIONS:
            scores = self.dimension_scores[dimension]
            if not isinstance(scores, Mapping) or set(scores) != {"a", "b"}:
                raise ValueError("dimension_scores differ from frozen dimensions")
            a, b = scores["a"], scores["b"]
            if self.choice == "CANNOT_JUDGE" and a is None and b is None:
                continue
            if (
                not isinstance(a, int)
                or isinstance(a, bool)
                or not isinstance(b, int)
                or isinstance(b, bool)
                or not 1 <= a <= 5
                or not 1 <= b <= 5
            ):
                raise ValueError("blind pair dimension scores must be 1-5")

    @property
    def preferred_asset_version_id(self) -> str | None:
        if self.choice == "A":
            return self.candidate_a_asset_version_id
        if self.choice == "B":
            return self.candidate_b_asset_version_id
        return None


@dataclass(frozen=True, slots=True)
class AdjudicatedEvaluation:
    adjudication_id: str
    subject_asset_version_id: str
    dimension: str
    status: str
    score_range: tuple[float, float]
    source_human_evaluation_asset_version_ids: tuple[str, ...]
    adjudicator_id: str
    adjudicator_identity_class: str
    protocol_version: str
    evaluation_version: str
    scope_type: str
    chapter_start: int
    chapter_end: int
    rationale: str
    adjudication_asset_version_id: str

    def __post_init__(self) -> None:
        low, high = self.score_range
        required = (
            self.adjudication_id,
            self.subject_asset_version_id,
            self.dimension,
            self.status,
            self.adjudicator_id,
            self.adjudicator_identity_class,
            self.protocol_version,
            self.evaluation_version,
            self.rationale,
            self.adjudication_asset_version_id,
        )
        if (
            len(set(self.source_human_evaluation_asset_version_ids)) < 2
            or low < 0
            or high > 100
            or low > high
            or any(not str(value).strip() for value in required)
        ):
            raise ValueError(
                "AdjudicatedEvaluation requires two independent HumanEvaluations"
            )
        _require_scope(self.scope_type, self.chapter_start, self.chapter_end)


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
        required = (
            self.evidence_id,
            self.subject_asset_version_id,
            self.metric_type,
            self.reader_segment,
            self.platform,
            self.evidence_asset_version_id,
        )
        if (
            self.exposure_count <= 0
            or self.outcome_count < 0
            or self.outcome_count > self.exposure_count
            or any(not str(value).strip() for value in required)
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
    judge_provider_id: str
    judge_model_id: str
    previous_profile_version_id: str = ""
    status: str = "CANDIDATE"

    def __post_init__(self) -> None:
        required = (
            self.profile_version_id,
            self.profile_id,
            self.dimension,
            self.threshold_policy_version_id,
            self.judge_profile_ref,
            self.judge_profile_hash,
            self.judge_provider_id,
            self.judge_model_id,
        )
        if (
            self.version <= 0
            or self.status not in {"CANDIDATE", "ACTIVE", "STALE", "REVOKED"}
            or any(not str(value).strip() for value in required)
        ):
            raise ValueError("QualityProfileVersion identity is incomplete")
        if not self.judge_profile_hash.startswith("sha256:"):
            raise ValueError("QualityProfileVersion hash is invalid")


@dataclass(frozen=True, slots=True)
class CalibrationRun:
    run_id: str
    profile_version_id: str
    dimension: str
    protocol_version: str
    evaluation_version: str
    evidence_scope: str
    judge_evaluation_asset_version_ids: tuple[str, ...]
    adjudicated_evaluation_asset_version_ids: tuple[str, ...]
    human_evaluation_asset_version_ids: tuple[str, ...] = ()
    blind_pair_preference_asset_version_ids: tuple[str, ...] = ()
    reader_outcome_evidence_asset_version_ids: tuple[str, ...] = ()
    fixture_protocol_only: bool = False

    def __post_init__(self) -> None:
        if any(
            not str(value).strip()
            for value in (
                self.run_id,
                self.profile_version_id,
                self.dimension,
                self.protocol_version,
                self.evaluation_version,
            )
        ):
            raise ValueError("CalibrationRun identity is incomplete")
        if self.evidence_scope != BOUNDED_EVIDENCE:
            raise ValueError("Calibration v2 currently accepts BOUNDED_EVIDENCE only")


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
    evidence_status: str
    independence_status: str
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
    """Produce bounded diagnostics; this function cannot activate a profile."""

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
    _validate_protocol_versions(
        run, human_evaluations, adjudicated_evaluations, blind_preferences
    )
    _validate_judge_profile(profile, judge_evaluations)
    _validate_adjudication_sources(human_evaluations, adjudicated_evaluations)

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
    correctness: list[tuple[JudgeEvaluation, bool]] = []
    for judge in judge_evaluations:
        key = (judge.subject_asset_version_id, judge.dimension)
        reference = adjudicated.get(key)
        if reference is None:
            raise KernelError(
                "QUALITY_JUDGE_REFERENCE_MISSING",
                "JudgeEvaluation has no AdjudicatedEvaluation reference",
            )
        is_correct = judge.status == reference.status
        correctness.append((judge, is_correct))
        correct += int(is_correct)
        if judge.score is not None:
            score_in_range += int(
                reference.score_range[0] <= judge.score <= reference.score_range[1]
            )
        false_pass += int(judge.status == "PASSED" and reference.status != "PASSED")
        false_reject += int(judge.status != "PASSED" and reference.status == "PASSED")
        disagreement += int(not is_correct)
    count = len(judge_evaluations)
    accuracy = correct / count if count else 0.0
    score_rate = score_in_range / count if count else 0.0
    independence_status, independence_rows = _independence(judge_evaluations)
    pairwise = _pairwise_agreement(blind_preferences)
    weighted = _weighted_ordinal_agreement(blind_preferences)
    diagnostics = {
        "single_human_evaluation_is_ground_truth": False,
        "subjective_reference_source": "ADJUDICATED_SUBJECTIVE_EVIDENCE",
        "reader_outcome_can_mutate_narrative_truth": False,
        "fixture_protocol_only": run.fixture_protocol_only,
        "bounded_evidence": True,
        "independent_activation_eligible": (
            independence_status == "CROSS_PROVIDER_DISTINCT_MODEL"
        ),
        "independence_relationships": independence_rows,
        "pairwise_agreement": pairwise,
        "weighted_ordinal_agreement": weighted,
        "rank_correlation": _rank_correlation(blind_preferences),
        "false_positive_negative": {
            "false_positive_count": false_pass,
            "false_negative_count": false_reject,
        },
        "confidence_calibration": _confidence_calibration(correctness),
        "position_bias": _position_bias(blind_preferences),
        "preference_stability": _preference_stability(blind_preferences),
        "threshold_observation": _threshold_observation(
            profile=profile,
            sample_count=count,
            accuracy=accuracy,
            false_pass_count=false_pass,
        ),
        "calibration_claim_allowed": False,
    }
    manifest = {
        "run": _slots_dict(run),
        "profile": _slots_dict(profile),
        "judge_evaluations": [_slots_dict(item) for item in judge_evaluations],
        "human_evaluations": [_slots_dict(item) for item in human_evaluations],
        "adjudications": [_slots_dict(item) for item in adjudicated_evaluations],
        "blind_preferences": [_slots_dict(item) for item in blind_preferences],
        "reader_outcomes": [_slots_dict(item) for item in reader_outcomes],
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
        calibration_status="UNCALIBRATED",
        evidence_status=BOUNDED_EVIDENCE,
        independence_status=independence_status,
        source_manifest_hash=_hash(manifest),
        activation_allowed=False,
        production_verified=False,
        diagnostics=diagnostics,
    )


def _validate_protocol_versions(
    run: CalibrationRun,
    human_evaluations: Iterable[HumanEvaluation],
    adjudications: Iterable[AdjudicatedEvaluation],
    preferences: Iterable[BlindPairPreference],
) -> None:
    for item in (*tuple(human_evaluations), *tuple(adjudications), *tuple(preferences)):
        if (
            item.protocol_version != run.protocol_version
            or item.evaluation_version != run.evaluation_version
        ):
            raise KernelError(
                "QUALITY_CALIBRATION_PROTOCOL_CONFLICT",
                "calibration evidence differs from the frozen protocol",
            )


def _validate_judge_profile(
    profile: QualityProfileVersion,
    judge_evaluations: Iterable[JudgeEvaluation],
) -> None:
    for judge in judge_evaluations:
        if (
            judge.dimension != profile.dimension
            or judge.evaluator_id != profile.judge_profile_ref
            or judge.provider_id != profile.judge_provider_id
            or judge.model_id != profile.judge_model_id
        ):
            raise KernelError(
                "QUALITY_JUDGE_PROFILE_LINEAGE_CONFLICT",
                "JudgeEvaluation differs from the frozen Quality profile",
            )


def _validate_adjudication_sources(
    human_evaluations: tuple[HumanEvaluation, ...],
    adjudications: tuple[AdjudicatedEvaluation, ...],
) -> None:
    human_by_asset = {
        item.evaluation_asset_version_id: item for item in human_evaluations
    }
    if len(human_by_asset) != len(human_evaluations):
        raise KernelError(
            "QUALITY_HUMAN_EVALUATION_DUPLICATE",
            "frozen run contains duplicate HumanEvaluation evidence",
        )
    for adjudication in adjudications:
        try:
            sources = tuple(
                human_by_asset[item]
                for item in adjudication.source_human_evaluation_asset_version_ids
            )
        except KeyError as exc:
            raise KernelError(
                "QUALITY_ADJUDICATION_SOURCE_MISSING",
                "adjudication references HumanEvaluation outside the frozen run",
            ) from exc
        if len({item.evaluator_id for item in sources}) < 2 or any(
            not item.blind for item in sources
        ):
            raise KernelError(
                "QUALITY_ADJUDICATION_INDEPENDENCE_REQUIRED",
                "adjudication requires two independent blind human evaluations",
            )
        for source in sources:
            if (
                source.subject_asset_version_id != adjudication.subject_asset_version_id
                or source.dimension != adjudication.dimension
                or source.protocol_version != adjudication.protocol_version
                or source.evaluation_version != adjudication.evaluation_version
                or source.scope_type != adjudication.scope_type
                or source.chapter_start != adjudication.chapter_start
                or source.chapter_end != adjudication.chapter_end
            ):
                raise KernelError(
                    "QUALITY_ADJUDICATION_SCOPE_CONFLICT",
                    "adjudication and raw HumanEvaluation scope differ",
                )


def _independence(
    judge_evaluations: Iterable[JudgeEvaluation],
) -> tuple[str, dict[str, str]]:
    relationships: dict[str, str] = {}
    for judge in judge_evaluations:
        judge_route = (judge.provider_id, judge.model_id)
        source_routes = {
            (judge.generator_provider_id, judge.generator_model_id),
            (judge.reviewer_provider_id, judge.reviewer_model_id),
        }
        if judge_route in source_routes:
            relationship = "SAME_MODEL"
        elif judge.provider_id in {
            judge.generator_provider_id,
            judge.reviewer_provider_id,
        }:
            relationship = "SAME_PROVIDER"
        else:
            relationship = "CROSS_PROVIDER_DISTINCT_MODEL"
        relationships[judge.evaluation_id] = relationship
    values = set(relationships.values())
    if "SAME_MODEL" in values:
        status = "SAME_MODEL"
    elif "SAME_PROVIDER" in values:
        status = "SAME_PROVIDER"
    elif values:
        status = "CROSS_PROVIDER_DISTINCT_MODEL"
    else:
        status = "NOT_ESTIMABLE"
    return status, relationships


def _comparison_key(item: BlindPairPreference) -> tuple[Any, ...]:
    return (
        item.subject_id,
        tuple(
            sorted(
                (
                    item.candidate_a_asset_version_id,
                    item.candidate_b_asset_version_id,
                )
            )
        ),
        item.scope_type,
        item.chapter_start,
        item.chapter_end,
    )


def _normalized_choice(item: BlindPairPreference) -> str | None:
    if item.choice in {"A", "B"}:
        return str(item.preferred_asset_version_id)
    if item.choice == "TIE":
        return "TIE"
    return None


def _group_preferences(
    preferences: Iterable[BlindPairPreference],
) -> dict[tuple[Any, ...], list[BlindPairPreference]]:
    grouped: dict[tuple[Any, ...], list[BlindPairPreference]] = defaultdict(list)
    for item in preferences:
        grouped[_comparison_key(item)].append(item)
    return grouped


def _pairwise_agreement(
    preferences: tuple[BlindPairPreference, ...],
) -> dict[str, Any]:
    comparisons = agreements = 0
    for rows in _group_preferences(preferences).values():
        humans = [item for item in rows if item.evaluator_role == "HUMAN"]
        judges = [item for item in rows if item.evaluator_role == "AUTOMATED_JUDGE"]
        for human in humans:
            for judge in judges:
                human_choice = _normalized_choice(human)
                judge_choice = _normalized_choice(judge)
                if human_choice is None or judge_choice is None:
                    continue
                comparisons += 1
                agreements += int(human_choice == judge_choice)
    return {
        "status": "BOUNDED_EVIDENCE" if comparisons else "NOT_ESTIMABLE",
        "comparison_count": comparisons,
        "agreement_count": agreements,
        "agreement_rate": agreements / comparisons if comparisons else None,
    }


def _normalized_dimension_delta(
    item: BlindPairPreference, dimension: str
) -> float | None:
    scores = item.dimension_scores[dimension]
    a, b = scores["a"], scores["b"]
    if a is None or b is None:
        return None
    first = min(
        item.candidate_a_asset_version_id,
        item.candidate_b_asset_version_id,
    )
    return float(a - b if item.candidate_a_asset_version_id == first else b - a)


def _weighted_ordinal_agreement(
    preferences: tuple[BlindPairPreference, ...],
) -> dict[str, Any]:
    values: list[float] = []
    for rows in _group_preferences(preferences).values():
        humans = [item for item in rows if item.evaluator_role == "HUMAN"]
        judges = [item for item in rows if item.evaluator_role == "AUTOMATED_JUDGE"]
        for human in humans:
            for judge in judges:
                for dimension in BLIND_EVALUATION_DIMENSIONS:
                    human_delta = _normalized_dimension_delta(human, dimension)
                    judge_delta = _normalized_dimension_delta(judge, dimension)
                    if human_delta is None or judge_delta is None:
                        continue
                    values.append(1.0 - abs(human_delta - judge_delta) / 8.0)
    return {
        "status": "BOUNDED_EVIDENCE" if values else "NOT_ESTIMABLE",
        "dimension_comparison_count": len(values),
        "agreement": fmean(values) if values else None,
    }


def _rank_correlation(
    preferences: tuple[BlindPairPreference, ...],
) -> dict[str, Any]:
    human_values: list[float] = []
    judge_values: list[float] = []
    for rows in _group_preferences(preferences).values():
        humans = [item for item in rows if item.evaluator_role == "HUMAN"]
        judges = [item for item in rows if item.evaluator_role == "AUTOMATED_JUDGE"]
        human_deltas = [
            value
            for item in humans
            if (value := _normalized_dimension_delta(item, "overall_preference"))
            is not None
        ]
        judge_deltas = [
            value
            for item in judges
            if (value := _normalized_dimension_delta(item, "overall_preference"))
            is not None
        ]
        if human_deltas and judge_deltas:
            human_values.append(fmean(human_deltas))
            judge_values.append(fmean(judge_deltas))
    if (
        len(human_values) < 3
        or len(set(human_values)) < 2
        or len(set(judge_values)) < 2
    ):
        return {
            "status": "NOT_ESTIMABLE",
            "eligible_pair_count": len(human_values),
            "rank_correlation": None,
        }
    return {
        "status": "BOUNDED_EVIDENCE",
        "eligible_pair_count": len(human_values),
        "rank_correlation": _pearson(
            _average_ranks(human_values), _average_ranks(judge_values)
        ),
    }


def _average_ranks(values: list[float]) -> list[float]:
    ranks = [0.0] * len(values)
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        rank = (cursor + 1 + end) / 2
        for index, _ in ordered[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    left_mean, right_mean = fmean(left), fmean(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)
    )
    left_denominator = sum((value - left_mean) ** 2 for value in left)
    right_denominator = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_denominator * right_denominator)
    return numerator / denominator if denominator else None


def _confidence_calibration(
    correctness: list[tuple[JudgeEvaluation, bool]],
) -> dict[str, Any]:
    definitions = (
        ("0.0-0.5", 0.0, 0.5, False),
        ("0.5-0.8", 0.5, 0.8, False),
        ("0.8-1.0", 0.8, 1.0, True),
    )
    bins: list[dict[str, Any]] = []
    for label, lower, upper, include_upper in definitions:
        rows = [
            (judge, correct)
            for judge, correct in correctness
            if lower <= judge.confidence
            and (
                judge.confidence <= upper if include_upper else judge.confidence < upper
            )
        ]
        average_confidence = (
            fmean(item.confidence for item, _ in rows) if rows else None
        )
        observed_accuracy = fmean(int(correct) for _, correct in rows) if rows else None
        bins.append(
            {
                "bin": label,
                "count": len(rows),
                "average_confidence": average_confidence,
                "observed_accuracy": observed_accuracy,
                "calibration_gap": (
                    abs(average_confidence - observed_accuracy)
                    if average_confidence is not None and observed_accuracy is not None
                    else None
                ),
            }
        )
    return {"status": "BOUNDED_EVIDENCE", "bins": bins}


def _position_bias(
    preferences: tuple[BlindPairPreference, ...],
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for role in sorted(EVALUATOR_ROLES):
        rows = [item for item in preferences if item.evaluator_role == role]
        a_count = sum(item.choice == "A" for item in rows)
        b_count = sum(item.choice == "B" for item in rows)
        decisive = a_count + b_count
        report[role] = {
            "status": "BOUNDED_EVIDENCE" if decisive else "NOT_ESTIMABLE",
            "decision_count": len(rows),
            "decisive_count": decisive,
            "a_choice_rate": a_count / decisive if decisive else None,
            "position_imbalance": (
                abs(a_count - b_count) / decisive if decisive else None
            ),
            "presentation_orders": {
                order: sum(item.presentation_order == order for item in rows)
                for order in ("AB", "BA")
            },
        }
    return report


def _preference_stability(
    preferences: tuple[BlindPairPreference, ...],
) -> dict[str, Any]:
    grouped: dict[tuple[Any, ...], list[BlindPairPreference]] = defaultdict(list)
    for item in preferences:
        grouped[
            (
                item.evaluator_role,
                item.evaluator_id,
                *_comparison_key(item),
            )
        ].append(item)
    comparisons = stable = 0
    for rows in grouped.values():
        choices = [
            choice for item in rows if (choice := _normalized_choice(item)) is not None
        ]
        if len(choices) < 2:
            continue
        comparisons += len(choices) - 1
        stable += sum(choice == choices[0] for choice in choices[1:])
    return {
        "status": "BOUNDED_EVIDENCE" if comparisons else "NOT_ESTIMABLE",
        "repeat_comparison_count": comparisons,
        "stability_rate": stable / comparisons if comparisons else None,
    }


def _threshold_observation(
    *,
    profile: QualityProfileVersion,
    sample_count: int,
    accuracy: float,
    false_pass_count: int,
) -> dict[str, Any]:
    minimum_samples = int(profile.thresholds.get("minimum_sample_count", 1))
    minimum_accuracy = float(profile.thresholds.get("minimum_status_accuracy", 1.0))
    maximum_false_pass = int(profile.thresholds.get("maximum_false_pass_count", 0))
    return {
        "observed_thresholds_met": (
            sample_count >= minimum_samples
            and accuracy >= minimum_accuracy
            and false_pass_count <= maximum_false_pass
        ),
        "activation_effect": "NONE_BOUNDED_EVIDENCE_ONLY",
    }


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
