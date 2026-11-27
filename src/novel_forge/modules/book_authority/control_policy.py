from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.intent import ControlMode

CONTROL_POLICY_OWNER = "BOOK_CONTROL"
CONTROL_BOUNDARIES = frozenset(
    {
        "BOOK",
        "VOLUME",
        "ARC",
        "NEAR_TERM",
        "CHAPTER",
        "SCENE",
        "FINAL_CANDIDATE",
        "REALITY_COMMIT",
        "MAJOR_DECISION",
        "DIRECTOR",
    }
)


@dataclass(frozen=True, slots=True)
class ControlPolicy:
    policy_version: str = "book-control-v1:auto"
    mode: str = ControlMode.AUTO.value
    planning_selection_mode: str = ""

    def __post_init__(self) -> None:
        if (not self.policy_version or self.mode not in set(ControlMode)
                or self.planning_selection_mode not in {"", "AVAILABLE_QUALIFIED"}):
            raise KernelError(
                "BOOK_CONTROL_POLICY_INVALID",
                "ControlPolicy requires one versioned declared mode",
            )

    def requires(self, boundary: str) -> bool:
        if boundary not in CONTROL_BOUNDARIES:
            raise KernelError(
                "BOOK_CONTROL_BOUNDARY_INVALID", "Unknown editorial boundary"
            )
        boundaries = {
            ControlMode.AUTO: set(),
            ControlMode.AUTHOR_SUPERVISED: {"BOOK", "VOLUME", "ARC", "NEAR_TERM", "CHAPTER", "SCENE", "FINAL_CANDIDATE", "REALITY_COMMIT", "MAJOR_DECISION"},
            ControlMode.REVIEW_MAJOR_DECISION: {"MAJOR_DECISION"},
            ControlMode.REVIEW_PLAN: {
                "BOOK",
                "VOLUME",
                "ARC",
                "NEAR_TERM",
                "CHAPTER",
                "SCENE",
            },
            ControlMode.REVIEW_CHAPTER: {"FINAL_CANDIDATE"},
            ControlMode.REVIEW_REALITY_COMMIT: {"REALITY_COMMIT"},
            ControlMode.MANUAL_DIRECTOR: {"DIRECTOR"},
        }
        return boundary in boundaries[ControlMode(self.mode)]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if not self.planning_selection_mode:
            value.pop("planning_selection_mode")
        return value
