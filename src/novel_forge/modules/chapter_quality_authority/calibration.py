from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class QualityCalibrationStatus(StrEnum):
    UNCALIBRATED = "UNCALIBRATED"
    PROVIDER_UNCALIBRATED = "PROVIDER_UNCALIBRATED"
    CALIBRATION_CANDIDATE = "CALIBRATION_CANDIDATE"
    HUMAN_CALIBRATED = "HUMAN_CALIBRATED"
    GOLDEN_SET_CALIBRATED = "GOLDEN_SET_CALIBRATED"
    CALIBRATION_STALE = "CALIBRATION_STALE"
    CALIBRATION_REVOKED = "CALIBRATION_REVOKED"


@dataclass(frozen=True, slots=True)
class QualityGoldenSample:
    sample_id: str
    project_scope: str
    dimension: str
    input_asset_version_ids: tuple[str, ...]
    expected_status: str
    expected_score_range: tuple[float, float]
    human_evidence: tuple[dict[str, Any], ...]
    annotator: str
    adjudication_status: str
    dataset_version: str

    def __post_init__(self) -> None:
        if not all((self.sample_id, self.dimension, self.input_asset_version_ids, self.annotator, self.dataset_version)):
            raise ValueError("golden sample lineage is incomplete")
        low, high = self.expected_score_range
        if low < 0 or high > 100 or low > high:
            raise ValueError("golden sample score range is invalid")


@dataclass(frozen=True, slots=True)
class QualityHumanDecision:
    sample_id: str
    dimension: str
    status: str
    score: float | None
    evidence: tuple[dict[str, Any], ...]
    annotator: str


@dataclass(frozen=True, slots=True)
class QualityProviderDecision:
    sample_id: str
    dimension: str
    status: str
    score: float | None
    confidence: float
    provider_evidence_asset_version_id: str
    calibration_status: QualityCalibrationStatus = (
        QualityCalibrationStatus.PROVIDER_UNCALIBRATED
    )

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("provider calibration confidence is outside [0,1]")
        if self.calibration_status is not QualityCalibrationStatus.PROVIDER_UNCALIBRATED:
            raise ValueError("provider confidence cannot self-assert calibrated status")


@dataclass(frozen=True, slots=True)
class QualityCalibrationProfile:
    profile_id: str
    dimension: str
    dataset_version: str
    threshold_policy_version_id: str
    status: QualityCalibrationStatus
    revoked: bool = False
    stale: bool = False


@dataclass(frozen=True, slots=True)
class QualityCalibrationPolicy:
    policy_version: str
    minimum_sample_count: int
    minimum_coverage: float
    minimum_status_accuracy: float
    minimum_score_in_range_rate: float
    minimum_per_status_precision: float
    minimum_per_status_recall: float
    minimum_inter_annotator_agreement: float
    maximum_unresolved_adjudication: int
    confidence_interval_policy: str = "deterministic-fixture-exact"

    def __post_init__(self) -> None:
        if not self.policy_version or self.minimum_sample_count <= 0:
            raise ValueError("calibration policy identity and sample floor are required")
        rates = (
            self.minimum_coverage,
            self.minimum_status_accuracy,
            self.minimum_score_in_range_rate,
            self.minimum_per_status_precision,
            self.minimum_per_status_recall,
            self.minimum_inter_annotator_agreement,
        )
        if any(not 0 <= value <= 1 for value in rates) or self.maximum_unresolved_adjudication < 0:
            raise ValueError("calibration policy thresholds are invalid")


DEFAULT_CALIBRATION_POLICY = QualityCalibrationPolicy(
    policy_version="quality-calibration-policy-v1",
    minimum_sample_count=5,
    minimum_coverage=1.0,
    minimum_status_accuracy=0.9,
    minimum_score_in_range_rate=0.9,
    minimum_per_status_precision=0.8,
    minimum_per_status_recall=0.8,
    minimum_inter_annotator_agreement=0.8,
    maximum_unresolved_adjudication=0,
)


@dataclass(frozen=True, slots=True)
class QualityCalibrationRun:
    run_id: str
    profile_id: str
    dimension: str
    dataset_version: str
    provider_decision_asset_version_ids: tuple[str, ...]
    sample_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityCalibrationReport:
    run_id: str
    dimension: str
    dataset_version: str
    matched: int
    total: int
    status_accuracy: float
    score_in_range_rate: float
    covered_count: int
    coverage_rate: float
    confusion_matrix: dict[str, dict[str, int]]
    per_status_precision: dict[str, float]
    per_status_recall: dict[str, float]
    agreement: float
    confidence_interval: tuple[float, float]
    failed_policy_rules: tuple[str, ...]
    policy_version: str
    calibration_status: QualityCalibrationStatus
    production_verified: bool = False
    real_provider_proven: bool = False
    fixture_protocol_only: bool = False
    contract_version: str = "quality-calibration-report-v1"
    extended_metrics: dict[str, Any] = field(default_factory=dict)


def evaluate_calibration_run(
    *,
    run: QualityCalibrationRun,
    profile: QualityCalibrationProfile,
    samples: tuple[QualityGoldenSample, ...],
    decisions: tuple[QualityProviderDecision, ...],
    policy: QualityCalibrationPolicy = DEFAULT_CALIBRATION_POLICY,
) -> QualityCalibrationReport:
    if (
        run.profile_id != profile.profile_id
        or run.dimension != profile.dimension
        or run.dataset_version != profile.dataset_version
    ):
        raise KernelError(
            "QUALITY_CALIBRATION_PROFILE_CONFLICT",
            "calibration run does not match its versioned profile",
        )
    sample_ids = tuple(item.sample_id for item in samples)
    decision_ids = tuple(item.provider_evidence_asset_version_id for item in decisions)
    if len(set(sample_ids)) != len(sample_ids) or len(set(decision_ids)) != len(decision_ids):
        raise KernelError("QUALITY_CALIBRATION_DUPLICATE_INPUT", "calibration inputs contain duplicate identity")
    if set(run.sample_ids) != set(sample_ids) or len(run.sample_ids) != len(sample_ids):
        raise KernelError("QUALITY_CALIBRATION_SAMPLE_SET_CONFLICT", "run sample IDs differ from frozen samples")
    if (
        set(run.provider_decision_asset_version_ids) != set(decision_ids)
        or len(run.provider_decision_asset_version_ids) != len(decision_ids)
    ):
        raise KernelError("QUALITY_CALIBRATION_DECISION_SET_CONFLICT", "run decision IDs differ from frozen decisions")
    by_sample: dict[str, QualityProviderDecision] = {}
    for item in decisions:
        if item.sample_id in by_sample:
            raise KernelError("QUALITY_CALIBRATION_DUPLICATE_DECISION", "a sample has multiple provider decisions")
        by_sample[item.sample_id] = item
    matched = 0
    score_in_range = 0
    confusion: dict[str, dict[str, int]] = {}
    unresolved = 0
    for sample in samples:
        if sample.dimension != run.dimension or sample.dataset_version != run.dataset_version:
            raise KernelError(
                "QUALITY_CALIBRATION_SAMPLE_CONFLICT",
                "golden sample dimension or dataset version is wrong",
            )
        if sample.adjudication_status != "ADJUDICATED":
            unresolved += 1
        decision = by_sample.get(sample.sample_id)
        if decision is None:
            continue
        if decision.dimension != sample.dimension:
            raise KernelError(
                "QUALITY_CALIBRATION_DECISION_CONFLICT",
                "provider decision targets the wrong dimension",
            )
        matched += int(decision.status == sample.expected_status)
        confusion.setdefault(sample.expected_status, {}).setdefault(decision.status, 0)
        confusion[sample.expected_status][decision.status] += 1
        if decision.score is not None:
            score_in_range += int(
                sample.expected_score_range[0]
                <= decision.score
                <= sample.expected_score_range[1]
            )
    total = len(samples)
    covered = len(by_sample)
    statuses = sorted(
        {sample.expected_status for sample in samples}
        | {decision.status for decision in decisions}
    )
    precision: dict[str, float] = {}
    recall: dict[str, float] = {}
    for status_code in statuses:
        true_positive = confusion.get(status_code, {}).get(status_code, 0)
        predicted = sum(row.get(status_code, 0) for row in confusion.values())
        expected = sum(confusion.get(status_code, {}).values())
        precision[status_code] = true_positive / predicted if predicted else 0.0
        recall[status_code] = true_positive / expected if expected else 0.0
    accuracy = matched / total if total else 0.0
    score_rate = score_in_range / total if total else 0.0
    coverage = covered / total if total else 0.0
    agreement = 1.0 if total and unresolved == 0 else 0.0
    failures: list[str] = []
    checks = {
        "minimum_sample_count": total >= policy.minimum_sample_count,
        "minimum_coverage": coverage >= policy.minimum_coverage,
        "minimum_status_accuracy": accuracy >= policy.minimum_status_accuracy,
        "minimum_score_in_range_rate": score_rate >= policy.minimum_score_in_range_rate,
        "minimum_per_status_precision": bool(precision) and min(precision.values()) >= policy.minimum_per_status_precision,
        "minimum_per_status_recall": bool(recall) and min(recall.values()) >= policy.minimum_per_status_recall,
        "minimum_inter_annotator_agreement": agreement >= policy.minimum_inter_annotator_agreement,
        "maximum_unresolved_adjudication": unresolved <= policy.maximum_unresolved_adjudication,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    if profile.revoked:
        status = QualityCalibrationStatus.CALIBRATION_REVOKED
    elif profile.stale:
        status = QualityCalibrationStatus.CALIBRATION_STALE
    elif not failures:
        status = QualityCalibrationStatus.CALIBRATION_CANDIDATE
    else:
        status = QualityCalibrationStatus.PROVIDER_UNCALIBRATED
    return QualityCalibrationReport(
        run_id=run.run_id,
        dimension=run.dimension,
        dataset_version=run.dataset_version,
        matched=matched,
        total=total,
        status_accuracy=accuracy,
        score_in_range_rate=score_rate,
        covered_count=covered,
        coverage_rate=coverage,
        confusion_matrix=confusion,
        per_status_precision=precision,
        per_status_recall=recall,
        agreement=agreement,
        confidence_interval=(accuracy, accuracy),
        failed_policy_rules=tuple(failures),
        policy_version=policy.policy_version,
        calibration_status=status,
        fixture_protocol_only=bool(samples) and all(
            sample.project_scope.strip().lower() == "fixture"
            for sample in samples
        ),
        extended_metrics=quality_calibration_metrics(samples, decisions),
    )


def quality_calibration_metrics(
    samples: tuple[QualityGoldenSample, ...],
    decisions: tuple[QualityProviderDecision, ...],
) -> dict[str, Any]:
    """Compute calibration diagnostics without upgrading qualification status."""

    by_sample = {item.sample_id: item for item in decisions}
    matched = [
        (sample, by_sample[sample.sample_id])
        for sample in samples
        if sample.sample_id in by_sample
    ]
    labels = sorted(
        {sample.expected_status for sample, _ in matched}
        | {decision.status for _, decision in matched}
    )
    label_index = {label: index for index, label in enumerate(labels)}
    weighted_kappa = _weighted_kappa(
        [label_index[sample.expected_status] for sample, _ in matched],
        [label_index[decision.status] for _, decision in matched],
        len(labels),
    )
    scored = [
        (
            (sample.expected_score_range[0] + sample.expected_score_range[1]) / 2,
            float(decision.score),
        )
        for sample, decision in matched
        if decision.score is not None
    ]
    correctness = [
        (decision.confidence, int(decision.status == sample.expected_status))
        for sample, decision in matched
    ]
    false_positive = sum(
        sample.expected_status == "PASSED" and decision.status != "PASSED"
        for sample, decision in matched
    )
    false_negative = sum(
        sample.expected_status != "PASSED" and decision.status == "PASSED"
        for sample, decision in matched
    )
    segments: dict[str, dict[str, int | float]] = {}
    for sample, decision in matched:
        segment = segments.setdefault(
            sample.project_scope, {"count": 0, "matched": 0, "accuracy": 0.0}
        )
        segment["count"] = int(segment["count"]) + 1
        segment["matched"] = int(segment["matched"]) + int(
            sample.expected_status == decision.status
        )
    for segment in segments.values():
        segment["accuracy"] = int(segment["matched"]) / int(segment["count"])
    return {
        "weighted_kappa": weighted_kappa,
        "rank_correlation": _spearman(scored),
        "calibration_error": _expected_calibration_error(correctness),
        "false_positive_count": false_positive,
        "false_negative_count": false_negative,
        "segment_breakdown": segments,
        "position_bias": {"status": "NOT_MEASURED", "value": None},
        "judge_disagreement": {"status": "NOT_MEASURED", "value": None},
        "ood_rate": {"status": "NOT_MEASURED", "value": None},
        "harmless_mutation_stability": {
            "status": "NOT_MEASURED",
            "value": None,
        },
    }


def _weighted_kappa(
    expected: list[int], predicted: list[int], label_count: int
) -> float | None:
    count = len(expected)
    if not count or label_count <= 1:
        return None
    scale = float((label_count - 1) ** 2)
    observed = sum((left - right) ** 2 / scale for left, right in zip(expected, predicted)) / count
    expected_counts = [expected.count(index) / count for index in range(label_count)]
    predicted_counts = [predicted.count(index) / count for index in range(label_count)]
    random_disagreement = sum(
        expected_counts[left]
        * predicted_counts[right]
        * ((left - right) ** 2 / scale)
        for left in range(label_count)
        for right in range(label_count)
    )
    if random_disagreement == 0:
        return 1.0 if observed == 0 else 0.0
    return 1.0 - observed / random_disagreement


def _spearman(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    left = _ranks([item[0] for item in pairs])
    right = _ranks([item[1] for item in pairs])
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    left_scale = sum((item - left_mean) ** 2 for item in left) ** 0.5
    right_scale = sum((item - right_mean) ** 2 for item in right) ** 0.5
    return (
        numerator / (left_scale * right_scale)
        if left_scale and right_scale
        else None
    )


def _ranks(values: list[float]) -> list[float]:
    ranks = [0.0] * len(values)
    ordered = sorted(range(len(values)), key=values.__getitem__)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2
        for index in ordered[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def _expected_calibration_error(
    observations: list[tuple[float, int]], bins: int = 10
) -> float | None:
    if not observations:
        return None
    total = len(observations)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            item
            for item in observations
            if lower <= item[0] <= upper
            and (index == bins - 1 or item[0] < upper)
        ]
        if not bucket:
            continue
        confidence = sum(item[0] for item in bucket) / len(bucket)
        accuracy = sum(item[1] for item in bucket) / len(bucket)
        error += len(bucket) / total * abs(confidence - accuracy)
    return error


def promote_calibration_profile(
    *, profile: QualityCalibrationProfile, report: QualityCalibrationReport
) -> QualityCalibrationProfile:
    if profile.revoked or profile.stale:
        raise KernelError("QUALITY_CALIBRATION_PROFILE_INELIGIBLE", "stale or revoked profile cannot be promoted")
    if report.calibration_status is not QualityCalibrationStatus.CALIBRATION_CANDIDATE:
        raise KernelError("QUALITY_CALIBRATION_POLICY_FAILED", "only a passing calibration candidate can be promoted")
    if report.fixture_protocol_only:
        raise KernelError(
            "QUALITY_FIXTURE_PROMOTION_FORBIDDEN",
            "Fixture Golden Set evidence cannot activate a calibrated Judge profile",
        )
    if report.dimension != profile.dimension or report.dataset_version != profile.dataset_version:
        raise KernelError("QUALITY_CALIBRATION_PROFILE_CONFLICT", "report does not target the profile")
    return QualityCalibrationProfile(
        profile_id=profile.profile_id,
        dimension=profile.dimension,
        dataset_version=profile.dataset_version,
        threshold_policy_version_id=profile.threshold_policy_version_id,
        status=QualityCalibrationStatus.GOLDEN_SET_CALIBRATED,
    )


__all__ = [
    name for name in globals()
    if name.startswith("Quality") or name in {
        "DEFAULT_CALIBRATION_POLICY", "evaluate_calibration_run",
        "promote_calibration_profile", "quality_calibration_metrics",
    }
]
