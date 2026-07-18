from __future__ import annotations

from dataclasses import dataclass
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
    contract_version: str = "quality-calibration-report-v1"


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
    )


def promote_calibration_profile(
    *, profile: QualityCalibrationProfile, report: QualityCalibrationReport
) -> QualityCalibrationProfile:
    if profile.revoked or profile.stale:
        raise KernelError("QUALITY_CALIBRATION_PROFILE_INELIGIBLE", "stale or revoked profile cannot be promoted")
    if report.calibration_status is not QualityCalibrationStatus.CALIBRATION_CANDIDATE:
        raise KernelError("QUALITY_CALIBRATION_POLICY_FAILED", "only a passing calibration candidate can be promoted")
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
        "promote_calibration_profile",
    }
]
