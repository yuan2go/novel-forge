"""Pure contracts for human preference and reader behavior calibration."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import math
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class PreferenceChoice(StrEnum):
    A = "A"
    B = "B"
    TIE = "TIE"
    REJECT_BOTH = "REJECT_BOTH"


class CalibrationStatus(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    VALID = "VALID"
    DRIFTED = "DRIFTED"
    INVALID = "INVALID"


class JudgeMode(StrEnum):
    SHADOW = "SHADOW"
    ADVISORY = "ADVISORY"
    BOUNDED_PRODUCTION = "BOUNDED_PRODUCTION"


@dataclass(frozen=True, slots=True)
class CalibrationScope:
    platform: str
    genre: str
    subgenre: str
    chapter_type: str
    reader_segment: str
    judge_profile: str
    model_version: str


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    profile_id: str
    scope: CalibrationScope
    sample_size: int
    minimum_sample_size: int
    status: CalibrationStatus


def blind_pair_order(
    asset_a_version_id: str,
    asset_b_version_id: str,
    *,
    randomization_key: str,
) -> tuple[str, str]:
    if (
        not asset_a_version_id
        or not asset_b_version_id
        or asset_a_version_id == asset_b_version_id
        or not randomization_key
    ):
        raise ValueError("blind preference pair identity is invalid")
    digest = hashlib.sha256(randomization_key.encode()).digest()
    return (
        (asset_a_version_id, asset_b_version_id)
        if digest[0] % 2 == 0
        else (asset_b_version_id, asset_a_version_id)
    )


def preference_bias_report(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    decisive = [
        item for item in decisions if item.get("choice") in {"A", "B"}
    ]
    left_choices = sum(
        1
        for item in decisive
        if (
            item["choice"] == "A"
            and item.get("asset_a_position") == "LEFT"
        )
        or (
            item["choice"] == "B"
            and item.get("asset_b_position") == "LEFT"
        )
    )
    left_rate = left_choices / len(decisive) if decisive else 0.0
    position_bias = bool(decisive) and abs(left_rate - 0.5) >= 0.25
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for item in decisive:
        by_pair.setdefault(str(item.get("canonical_pair_key") or ""), []).append(
            item
        )
    reversals = [
        pair
        for pair in by_pair.values()
        if {item.get("presentation_order") for item in pair}
        >= {"AB", "BA"}
    ]
    consistent = sum(
        1
        for pair in reversals
        if len({item.get("preferred_asset_version_id") for item in pair}) == 1
    )
    return {
        "decision_count": len(decisive),
        "left_choice_rate": left_rate,
        "position_bias_detected": position_bias,
        "reversal_pair_count": len(reversals),
        "reversal_consistency": (
            consistent / len(reversals) if reversals else None
        ),
    }


def human_agreement_report(
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    by_pair: dict[str, list[str]] = {}
    for item in decisions:
        by_pair.setdefault(str(item["pair_id"]), []).append(
            str(item["choice"])
        )
    comparable = [items for items in by_pair.values() if len(items) >= 2]
    agreements = 0
    comparisons = 0
    for items in comparable:
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                comparisons += 1
                agreements += int(left == right)
    return {
        "pair_count": len(by_pair),
        "multi_judge_pair_count": len(comparable),
        "pairwise_comparisons": comparisons,
        "agreement_rate": agreements / comparisons if comparisons else None,
        "status": "MEASURED" if comparisons else "INSUFFICIENT_DATA",
    }


def resolve_calibration_profile(
    scope: CalibrationScope,
    candidates: list[CalibrationCandidate],
) -> CalibrationCandidate | None:
    eligible = [
        item
        for item in candidates
        if item.status is CalibrationStatus.VALID
        and item.sample_size >= item.minimum_sample_size
        and _scope_matches(scope, item.scope)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            _specificity(scope, item.scope),
            item.sample_size,
            item.profile_id,
        ),
    )


def calibration_metrics(
    observations: list[tuple[float, int]],
    *,
    minimum_sample_size: int,
) -> dict[str, Any]:
    if minimum_sample_size <= 0:
        raise ValueError("minimum sample size must be positive")
    count = len(observations)
    for probability, outcome in observations:
        if not 0 <= probability <= 1 or outcome not in {0, 1}:
            raise ValueError("calibration observations are invalid")
    if count < minimum_sample_size:
        return {
            "sample_size": count,
            "minimum_sample_size": minimum_sample_size,
            "calibration_status": CalibrationStatus.INSUFFICIENT_DATA.value,
            "brier_score": None,
            "log_loss": None,
            "calibration_error": None,
            "behavior_probability_allowed": False,
        }
    epsilon = 1e-12
    brier = sum((p - y) ** 2 for p, y in observations) / count
    log_loss = -sum(
        y * math.log(max(p, epsilon))
        + (1 - y) * math.log(max(1 - p, epsilon))
        for p, y in observations
    ) / count
    predicted = sum(p for p, _ in observations) / count
    observed = sum(y for _, y in observations) / count
    return {
        "sample_size": count,
        "minimum_sample_size": minimum_sample_size,
        "calibration_status": CalibrationStatus.VALID.value,
        "brier_score": brier,
        "log_loss": log_loss,
        "calibration_error": abs(predicted - observed),
        "behavior_probability_allowed": True,
    }


def require_exposure_denominator(
    *, exposure_id: str, project_id: str, reader_segment: str
) -> None:
    if not exposure_id or not project_id or not reader_segment:
        raise KernelError(
            "READER_EXPOSURE_REQUIRED",
            "Reader outcomes require a Project- and Segment-scoped exposure",
        )


def calibrated_probability(
    raw_score: float,
    *,
    calibration_status: CalibrationStatus,
) -> float:
    if calibration_status is not CalibrationStatus.VALID:
        raise KernelError(
            "CALIBRATED_PROBABILITY_FORBIDDEN",
            "uncalibrated or drifted scores remain RAW_SCORE",
        )
    return max(0.0, min(1.0, raw_score))


def mode_after_drift(
    current_mode: JudgeMode, *, severe_drift: bool
) -> JudgeMode:
    return JudgeMode.SHADOW if severe_drift else current_mode


def reader_decision_policy(
    *,
    hard_gate_passed: bool,
    blocking_quality_issues: int,
    calibration_status: CalibrationStatus,
    ood: bool,
    disagreement: bool,
    long_term_outcome: str,
    short_term_outcome: str,
) -> dict[str, Any]:
    if not hard_gate_passed:
        return {"decision": "BLOCKED", "reason": "HARD_GATE"}
    if blocking_quality_issues > 0:
        return {"decision": "BLOCKED", "reason": "BLOCKING_QUALITY"}
    if calibration_status is not CalibrationStatus.VALID:
        return {"decision": "SHADOW_ONLY", "reason": "CALIBRATION_INVALID"}
    if ood or disagreement:
        return {"decision": "HUMAN_REVIEW", "reason": "OOD_OR_DISAGREEMENT"}
    return {
        "decision": "ADVISORY",
        "reason": "CALIBRATED_EVIDENCE",
        "long_term_outcome": long_term_outcome,
        "short_term_outcome": short_term_outcome,
    }


def _scope_matches(
    requested: CalibrationScope, candidate: CalibrationScope
) -> bool:
    return all(
        getattr(candidate, field) in {"*", getattr(requested, field)}
        for field in CalibrationScope.__dataclass_fields__
    )


def _specificity(
    requested: CalibrationScope, candidate: CalibrationScope
) -> int:
    return sum(
        getattr(candidate, field) == getattr(requested, field)
        for field in CalibrationScope.__dataclass_fields__
    )


__all__ = [
    "CalibrationCandidate",
    "CalibrationScope",
    "CalibrationStatus",
    "JudgeMode",
    "PreferenceChoice",
    "blind_pair_order",
    "calibrated_probability",
    "calibration_metrics",
    "human_agreement_report",
    "mode_after_drift",
    "preference_bias_report",
    "reader_decision_policy",
    "require_exposure_denominator",
    "resolve_calibration_profile",
]
