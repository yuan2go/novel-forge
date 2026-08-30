from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class ArcObservationStatus(StrEnum):
    OBSERVED = "OBSERVED"
    NOT_OBSERVED = "NOT_OBSERVED"
    NOT_MATERIALIZED = "NOT_MATERIALIZED"
    UNKNOWN = "UNKNOWN"


class ArcLifecycleStatus(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class ArcCheckpointDecision(StrEnum):
    CONTINUE = "CONTINUE"
    CORRECT = "CORRECT"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


def _required(*values: str) -> None:
    if any(not str(value).strip() for value in values):
        raise KernelError("ARC_CONTRACT_INCOMPLETE", "Arc contract identity is incomplete")


@dataclass(frozen=True, slots=True)
class ArcActualState:
    project_id: str
    book_id: str
    arc_plan_version_id: str
    accepted_through_chapter: int
    acceptance_operation_id: str
    observation_status: ArcObservationStatus
    lifecycle_status: ArcLifecycleStatus
    cumulative_progress_units: int
    current_phase: str = ""

    def __post_init__(self) -> None:
        _required(
            self.project_id,
            self.book_id,
            self.arc_plan_version_id,
            self.acceptance_operation_id,
        )
        if self.accepted_through_chapter <= 0 or self.cumulative_progress_units < 0:
            raise KernelError("ARC_ACTUAL_STATE_INVALID", "ArcActualState boundary is invalid")
        if (
            self.observation_status
            in {ArcObservationStatus.NOT_OBSERVED, ArcObservationStatus.UNKNOWN}
            and self.cumulative_progress_units < 0
        ):
            raise KernelError("ARC_ACTUAL_STATE_INVALID", "unobserved Arc state is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "ArcActualState",
            "contract_version": "arc-actual-state-v1",
            "layer": "ACCEPTED_PROJECTION",
            **asdict(self),
            "observation_status": self.observation_status.value,
            "lifecycle_status": self.lifecycle_status.value,
        }


@dataclass(frozen=True, slots=True)
class ArcProgress:
    progress_id: str
    project_id: str
    book_id: str
    arc_plan_version_id: str
    chapter_number: int
    acceptance_operation_id: str
    chapter_outcome_asset_version_id: str
    observation_status: ArcObservationStatus
    contribution_kind: str
    progress_units: int
    cumulative_progress_units: int
    deviation_units: int | None
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        _required(
            self.progress_id,
            self.project_id,
            self.book_id,
            self.arc_plan_version_id,
            self.acceptance_operation_id,
            self.chapter_outcome_asset_version_id,
        )
        if self.chapter_number <= 0 or min(self.progress_units, self.cumulative_progress_units) < 0:
            raise KernelError("ARC_PROGRESS_INVALID", "ArcProgress values are invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "ArcProgress",
            "contract_version": "arc-progress-v1",
            "layer": "ACCEPTED_ACTUAL",
            "progress_id": self.progress_id,
            "project_id": self.project_id,
            "book_id": self.book_id,
            "arc_plan_version_id": self.arc_plan_version_id,
            "accepted_boundary": {
                "chapter_number": self.chapter_number,
                "acceptance_operation_id": self.acceptance_operation_id,
            },
            "source": {
                "chapter_outcome_asset_version_id": self.chapter_outcome_asset_version_id
            },
            "observation_status": self.observation_status.value,
            "contribution_kind": self.contribution_kind,
            "progress_units": self.progress_units,
            "cumulative_progress_units": self.cumulative_progress_units,
            "deviation_units": self.deviation_units,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ArcOutcome:
    arc_outcome_id: str
    project_id: str
    book_id: str
    arc_plan_version_id: str
    acceptance_operation_id: str
    accepted_through_chapter: int
    status: ArcLifecycleStatus
    completion_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(
            self.arc_outcome_id,
            self.project_id,
            self.book_id,
            self.arc_plan_version_id,
            self.acceptance_operation_id,
        )
        if self.status not in {ArcLifecycleStatus.COMPLETED, ArcLifecycleStatus.ABANDONED}:
            raise KernelError("ARC_OUTCOME_STATUS_INVALID", "ArcOutcome must be terminal")
        if self.accepted_through_chapter <= 0 or not self.completion_evidence:
            raise KernelError("ARC_OUTCOME_EVIDENCE_REQUIRED", "ArcOutcome evidence is required")


@dataclass(frozen=True, slots=True)
class ArcCheckpoint:
    checkpoint_id: str
    arc_plan_version_id: str
    accepted_through_chapter: int
    acceptance_operation_id: str
    decision: ArcCheckpointDecision
    reasons: tuple[str, ...]
    progress_id: str

    def __post_init__(self) -> None:
        _required(
            self.checkpoint_id,
            self.arc_plan_version_id,
            self.acceptance_operation_id,
            self.progress_id,
        )
        if self.accepted_through_chapter <= 0:
            raise KernelError("ARC_CHECKPOINT_INVALID", "ArcCheckpoint boundary is invalid")


@dataclass(frozen=True, slots=True)
class ArcRevision:
    revision_id: str
    arc_plan_version_id: str
    replacement_candidate_version_id: str
    based_on_checkpoint_id: str
    future_from_chapter: int
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(
            self.revision_id,
            self.arc_plan_version_id,
            self.replacement_candidate_version_id,
            self.based_on_checkpoint_id,
        )
        if self.future_from_chapter <= 0 or not self.reason_codes:
            raise KernelError("ARC_REVISION_INVALID", "ArcRevision requires future scope and reasons")


__all__ = [
    "ArcActualState",
    "ArcCheckpoint",
    "ArcCheckpointDecision",
    "ArcLifecycleStatus",
    "ArcObservationStatus",
    "ArcOutcome",
    "ArcProgress",
    "ArcRevision",
]
