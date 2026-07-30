"""Pure state and contract rules for ChapterGroup production."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from novel_forge.modules.command_kernel.errors import KernelError


class ChapterGroupState(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    CHAPTER_RUNNING = "CHAPTER_RUNNING"
    CLOSURE_PENDING = "CLOSURE_PENDING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ChapterGroupRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start <= 0 or self.end < self.start:
            raise ValueError("ChapterGroup range is invalid")
        if not 3 <= self.end - self.start + 1 <= 8:
            raise ValueError("ChapterGroup contains three to eight Chapters")

    @property
    def count(self) -> int:
        return self.end - self.start + 1


def require_next_chapter(
    *,
    state: ChapterGroupState,
    accepted_through: int,
    active_chapter: int | None,
    chapter_number: int,
    chapter_range: ChapterGroupRange,
) -> None:
    if state is not ChapterGroupState.READY:
        raise KernelError(
            "CHAPTER_GROUP_DISPATCH_NOT_READY",
            "ChapterGroup must be READY before dispatch",
        )
    if active_chapter is not None:
        raise KernelError(
            "CHAPTER_GROUP_ACTIVE_CHILD_EXISTS",
            "only one active Chapter child is allowed",
        )
    if chapter_number != accepted_through + 1:
        raise KernelError(
            "CHAPTER_GROUP_SEQUENCE_CONFLICT",
            "ChapterGroup dispatch must be sequential",
        )
    if not chapter_range.start <= chapter_number <= chapter_range.end:
        raise KernelError(
            "CHAPTER_GROUP_CHAPTER_OUT_OF_RANGE",
            "Chapter is outside the frozen ChapterGroup range",
        )


def state_after_acceptance(
    *, chapter_number: int, chapter_range: ChapterGroupRange
) -> ChapterGroupState:
    if not chapter_range.start <= chapter_number <= chapter_range.end:
        raise KernelError(
            "CHAPTER_GROUP_ACCEPTANCE_OUT_OF_RANGE",
            "accepted Chapter is outside the frozen ChapterGroup",
        )
    return (
        ChapterGroupState.CLOSURE_PENDING
        if chapter_number == chapter_range.end
        else ChapterGroupState.READY
    )


__all__ = [
    "ChapterGroupRange",
    "ChapterGroupState",
    "require_next_chapter",
    "state_after_acceptance",
]
