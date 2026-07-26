"""Typed evidence contract for model-backed judges.

Scoring policy remains in Quality/Evaluation domains.  This contract records what an
uncertain judge execution observed and prevents uncalibrated scores from being named
probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class JudgeKind(StrEnum):
    INTRINSIC = "intrinsic"
    ORIGINALITY = "originality"
    PLATFORM = "platform"
    STYLE = "style"
    SEMANTIC = "semantic"
    READER_OUTCOME = "reader_outcome"
    PAIRWISE = "pairwise"
    MUTATION = "mutation"
    OOD = "ood"


_JUDGE_CAPABILITIES = {
    JudgeKind.INTRINSIC: "quality.intrinsic.judge",
    JudgeKind.ORIGINALITY: "quality.originality.judge",
    JudgeKind.PLATFORM: "quality.platform.judge",
    JudgeKind.STYLE: "quality.intrinsic.judge",
    JudgeKind.SEMANTIC: "quality.intrinsic.judge",
    JudgeKind.READER_OUTCOME: "quality.reader_outcome.judge",
    JudgeKind.PAIRWISE: "quality.pairwise.judge",
    JudgeKind.MUTATION: "quality.pairwise.judge",
    JudgeKind.OOD: "quality.intrinsic.judge",
}


def capability_for_judge(kind: JudgeKind | str) -> str:
    return _JUDGE_CAPABILITIES[JudgeKind(kind)]


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    start: int
    end: int
    label: str = ""

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("judge evidence span is invalid")


@dataclass(frozen=True, slots=True)
class JudgeExecutionEvidence:
    judge_kind: JudgeKind
    judge_profile_version: str
    target_asset_version_id: str
    input_manifest_ref: str
    route_snapshot_id: str
    raw_score: float | None
    ordinal_band: str
    pairwise_preference: str
    evidence_spans: tuple[EvidenceSpan, ...]
    calibration_status: str
    disagreement: Mapping[str, Any]
    usage_receipt_ref: str
    cost_receipt_ref: str
    score_semantics: str = "Raw Score"

    def __post_init__(self) -> None:
        if not all(
            (
                self.judge_profile_version,
                self.target_asset_version_id,
                self.input_manifest_ref,
                self.route_snapshot_id,
                self.calibration_status,
                self.usage_receipt_ref,
                self.cost_receipt_ref,
            )
        ):
            raise ValueError("judge execution evidence is incomplete")
        if self.raw_score is not None and not 0 <= self.raw_score <= 100:
            raise ValueError("raw judge score must be between 0 and 100")
        if (
            self.calibration_status != "calibrated"
            and self.score_semantics.lower() in {"probability", "true_probability"}
        ):
            raise ValueError(
                "uncalibrated judge output cannot claim probability semantics"
            )
        if self.judge_kind in {JudgeKind.PAIRWISE, JudgeKind.MUTATION} and not (
            self.pairwise_preference or self.ordinal_band
        ):
            raise ValueError("pairwise judge requires preference or ordinal evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_kind": self.judge_kind.value,
            "capability": capability_for_judge(self.judge_kind),
            "judge_profile_version": self.judge_profile_version,
            "target_asset_version_id": self.target_asset_version_id,
            "input_manifest_ref": self.input_manifest_ref,
            "route_snapshot_id": self.route_snapshot_id,
            "raw_score": self.raw_score,
            "ordinal_band": self.ordinal_band,
            "pairwise_preference": self.pairwise_preference,
            "evidence_spans": [
                {"start": span.start, "end": span.end, "label": span.label}
                for span in self.evidence_spans
            ],
            "calibration_status": self.calibration_status,
            "disagreement": dict(self.disagreement),
            "usage_receipt_ref": self.usage_receipt_ref,
            "cost_receipt_ref": self.cost_receipt_ref,
            "score_semantics": self.score_semantics,
        }


__all__ = [
    "EvidenceSpan",
    "JudgeExecutionEvidence",
    "JudgeKind",
    "capability_for_judge",
]
