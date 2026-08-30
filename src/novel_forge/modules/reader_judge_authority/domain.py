from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    JudgeMode,
    ReaderJudgeQualificationStatus,
    transition_reader_judge_qualification,
)


@dataclass(frozen=True, slots=True)
class ReaderJudgeDefinition:
    judge_id: str
    definition_version: int
    model_profile_ref: str
    model_version: str
    capability_pack_ref: str
    prompt_ref: str
    skill_ref: str
    reader_segment_scope: str
    platform_scope: str
    genre_scope: str
    subgenre_scope: str
    chapter_type_scope: str
    evaluation_contract_ref: str
    calibration_policy_ref: str
    decision_policy_ref: str
    mode: JudgeMode
    status: ReaderJudgeQualificationStatus
    maximum_adjustment_chapters: int = 0

    def __post_init__(self) -> None:
        required = (
            self.judge_id,
            self.model_profile_ref,
            self.model_version,
            self.capability_pack_ref,
            self.prompt_ref,
            self.skill_ref,
            self.reader_segment_scope,
            self.platform_scope,
            self.genre_scope,
            self.subgenre_scope,
            self.chapter_type_scope,
            self.evaluation_contract_ref,
            self.calibration_policy_ref,
            self.decision_policy_ref,
        )
        if self.definition_version <= 0 or any(
            not str(item).strip() for item in required
        ):
            raise ValueError("Reader Judge definition is incomplete")
        if self.maximum_adjustment_chapters < 0:
            raise ValueError("Reader Judge adjustment bound cannot be negative")
        if (
            self.mode is JudgeMode.BOUNDED_PRODUCTION
            and self.maximum_adjustment_chapters <= 0
        ):
            raise ValueError("Bounded Production requires a positive Chapter bound")
        # ``mode`` is the requested deployment mode; qualification is a
        # separate append-only decision stream.  A definition may therefore
        # be registered while UNQUALIFIED, but activation still calls
        # ``require_mode_status`` and fails closed until evidence permits it.

    @property
    def definition_hash(self) -> str:
        value = asdict(self)
        value["mode"] = self.mode.value
        value["status"] = self.status.value
        return canonical_hash(value)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        value["status"] = self.status.value
        value["definition_hash"] = self.definition_hash
        return value


@dataclass(frozen=True, slots=True)
class ReaderJudgeResolutionScope:
    project_id: str
    book_id: str
    platform: str
    genre: str
    subgenre: str
    chapter_type: str
    reader_segment: str
    model_version: str

    def __post_init__(self) -> None:
        if any(not str(item).strip() for item in asdict(self).values()):
            raise ValueError("Reader Judge resolution scope is incomplete")


@dataclass(frozen=True, slots=True)
class ReaderJudgeExecutionSnapshot:
    snapshot_id: str
    project_id: str
    book_id: str
    judge_id: str
    judge_version_id: str
    definition_hash: str
    qualification_decision_id: str
    calibration_profile_id: str
    mode: JudgeMode
    calibration_status: ReaderJudgeQualificationStatus
    score_semantics: str
    publish_blocking: bool
    authority_commit_allowed: bool
    human_review_recommended: bool
    plan_adjustment_candidate_allowed: bool
    maximum_adjustment_chapters: int
    capability_pack_ref: str
    prompt_ref: str
    skill_ref: str
    model_profile_ref: str
    model_version: str
    fallback_reason: str = ""

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.project_id or not self.book_id:
            raise ValueError("Reader Judge execution snapshot identity is incomplete")
        if self.publish_blocking:
            raise ValueError(
                "Reader Judge publication blocking is not qualified in this slice"
            )
        if self.mode is JudgeMode.SHADOW and (
            self.authority_commit_allowed or self.plan_adjustment_candidate_allowed
        ):
            raise ValueError(
                "Shadow Judge cannot commit or create plan adjustment candidates"
            )
        if self.plan_adjustment_candidate_allowed and (
            self.mode is not JudgeMode.BOUNDED_PRODUCTION
            or self.maximum_adjustment_chapters <= 0
        ):
            raise ValueError("plan adjustment requires a bounded production snapshot")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        value["qualification_status"] = self.calibration_status.value
        value["calibration_status"] = self.calibration_label
        return value

    @property
    def calibration_label(self) -> str:
        if not self.calibration_profile_id:
            return "UNCALIBRATED"
        return "CALIBRATED"


def require_mode_status(
    mode: JudgeMode, status: ReaderJudgeQualificationStatus
) -> None:
    if mode is JudgeMode.ADVISORY and status not in {
        ReaderJudgeQualificationStatus.CALIBRATED,
        ReaderJudgeQualificationStatus.QUALIFIED,
    }:
        raise KernelError(
            "READER_JUDGE_ADVISORY_QUALIFICATION_REQUIRED",
            "Advisory mode requires a Calibrated or Qualified decision",
        )
    if (
        mode is JudgeMode.BOUNDED_PRODUCTION
        and status is not ReaderJudgeQualificationStatus.QUALIFIED
    ):
        raise KernelError(
            "READER_JUDGE_BOUNDED_QUALIFICATION_REQUIRED",
            "Bounded Production requires a Qualified decision",
        )


def validate_qualification_transition(
    current: ReaderJudgeQualificationStatus,
    target: ReaderJudgeQualificationStatus,
    *,
    evidence_level: str,
    sample_size: int,
    minimum_sample_size: int,
    drift_detected: bool,
) -> None:
    transition_reader_judge_qualification(
        current,
        target,
        evidence_level=evidence_level,
        sample_size=sample_size,
        minimum_sample_size=minimum_sample_size,
        drift_detected=drift_detected,
    )


def safe_shadow_snapshot(
    scope: ReaderJudgeResolutionScope, *, reason: str
) -> ReaderJudgeExecutionSnapshot:
    payload = {**asdict(scope), "fallback_reason": reason, "mode": "SHADOW"}
    return ReaderJudgeExecutionSnapshot(
        snapshot_id="reader-judge-snapshot:"
        + canonical_hash(payload).removeprefix("sha256:"),
        project_id=scope.project_id,
        book_id=scope.book_id,
        judge_id="",
        judge_version_id="",
        definition_hash="",
        qualification_decision_id="",
        calibration_profile_id="",
        mode=JudgeMode.SHADOW,
        calibration_status=ReaderJudgeQualificationStatus.UNQUALIFIED,
        score_semantics="RAW_SCORE",
        publish_blocking=False,
        authority_commit_allowed=False,
        human_review_recommended=False,
        plan_adjustment_candidate_allowed=False,
        maximum_adjustment_chapters=0,
        capability_pack_ref="",
        prompt_ref="",
        skill_ref="",
        model_profile_ref="",
        model_version=scope.model_version,
        fallback_reason=reason,
    )


def scope_matches(expected: str, actual: str) -> bool:
    return expected in {"*", actual}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ReaderJudgeDefinition",
    "ReaderJudgeExecutionSnapshot",
    "ReaderJudgeResolutionScope",
    "canonical_hash",
    "require_mode_status",
    "safe_shadow_snapshot",
    "scope_matches",
    "validate_qualification_transition",
]
