from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class QualityCalibrationStatus(StrEnum):
    UNCALIBRATED = "UNCALIBRATED"
    PROVIDER_UNCALIBRATED = "PROVIDER_UNCALIBRATED"
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
) -> QualityCalibrationReport:
    if run.dimension != profile.dimension or run.dataset_version != profile.dataset_version:
        raise KernelError(
            "QUALITY_CALIBRATION_PROFILE_CONFLICT",
            "calibration run does not match its versioned profile",
        )
    if profile.revoked:
        status = QualityCalibrationStatus.CALIBRATION_REVOKED
    elif profile.stale:
        status = QualityCalibrationStatus.CALIBRATION_STALE
    else:
        status = QualityCalibrationStatus.GOLDEN_SET_CALIBRATED
    by_sample = {item.sample_id: item for item in decisions}
    matched = 0
    score_in_range = 0
    for sample in samples:
        if sample.dimension != run.dimension or sample.dataset_version != run.dataset_version:
            raise KernelError(
                "QUALITY_CALIBRATION_SAMPLE_CONFLICT",
                "golden sample dimension or dataset version is wrong",
            )
        decision = by_sample.get(sample.sample_id)
        if decision is None:
            continue
        if decision.dimension != sample.dimension:
            raise KernelError(
                "QUALITY_CALIBRATION_DECISION_CONFLICT",
                "provider decision targets the wrong dimension",
            )
        matched += int(decision.status == sample.expected_status)
        if decision.score is not None:
            score_in_range += int(
                sample.expected_score_range[0]
                <= decision.score
                <= sample.expected_score_range[1]
            )
    total = len(samples)
    return QualityCalibrationReport(
        run_id=run.run_id,
        dimension=run.dimension,
        dataset_version=run.dataset_version,
        matched=matched,
        total=total,
        status_accuracy=matched / total if total else 0.0,
        score_in_range_rate=score_in_range / total if total else 0.0,
        calibration_status=status,
    )


__all__ = [name for name in globals() if name.startswith("Quality") or name == "evaluate_calibration_run"]
