from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning import (
    validate_chapter_function_matrix,
)


def _matrix_row(
    chapter_number: int,
    *,
    primary_function: str,
    ending_hook: str,
) -> dict:
    return {
        "chapter_number": chapter_number,
        "primary_function": primary_function,
        "secondary_functions": ["continuity"],
        "required_state_delta": {"pressure": chapter_number},
        "required_arc_contributions": ["arc:main:v1"],
        "promise_action": "advance",
        "foreshadow_action": "plant",
        "reward_action": "partial",
        "ending_hook": ending_hook,
        "prohibited_outcomes": ["premature closure"],
    }


class HierarchicalPlanningDomainTests(unittest.TestCase):
    def test_chapter_function_matrix_detects_repetition(self) -> None:
        rows = [
            _matrix_row(
                chapter,
                primary_function="EXPOSITION",
                ending_hook="same cliffhanger",
            )
            for chapter in (1, 2, 3)
        ]
        with self.assertRaisesRegex(
            KernelError,
            "CHAPTER_FUNCTION_MATRIX_BLOCKED.*ENDING_HOOK_HOMOGENEITY",
        ):
            validate_chapter_function_matrix(
                rows,
                group_objective="force an irreversible local choice",
            )

    def test_chapter_function_matrix_accepts_progressive_functions(self) -> None:
        rows = [
            _matrix_row(
                1,
                primary_function="DISCOVERY",
                ending_hook="new threat",
            ),
            _matrix_row(
                2,
                primary_function="ESCALATION",
                ending_hook="cost revealed",
            ),
            _matrix_row(
                3,
                primary_function="REVERSAL",
                ending_hook="choice demanded",
            ),
        ]
        result = validate_chapter_function_matrix(
            rows,
            group_objective="force an irreversible local choice",
        )
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["chapter_count"], 3)

    def test_progressive_matrix_rejects_one_note_reader_experience(self) -> None:
        rows = [
            {
                **_matrix_row(
                    chapter,
                    primary_function=function,
                    ending_hook=hook,
                ),
                "narrative_density": density,
                "reader_experience": {
                    "target_emotion": "unchanged tension",
                    "reward_mode": "DISCOVERY",
                },
                "arc_cadence": [
                    {
                        "arc_plan_version_id": "arc:main:v1",
                        "action": "ADVANCE",
                    }
                ],
                "obligation_actions": [],
            }
            for chapter, function, hook, density in (
                (1, "DISCOVERY", "new threat", "LOW"),
                (2, "ESCALATION", "cost revealed", "MEDIUM"),
                (3, "REVERSAL", "choice demanded", "HIGH"),
            )
        ]

        with self.assertRaisesRegex(
            KernelError,
            "CHAPTER_FUNCTION_MATRIX_BLOCKED.*READER_EXPERIENCE_HOMOGENEITY",
        ):
            validate_chapter_function_matrix(
                rows,
                group_objective="force an irreversible local choice",
            )

    def test_single_chapter_window_requires_complete_row_without_false_repetition(
        self,
    ) -> None:
        row = {
            **_matrix_row(
                1,
                primary_function="DISCOVERY",
                ending_hook="new threat",
            ),
            "narrative_density": "MEDIUM",
            "reader_experience": {
                "target_emotion": "rising pressure",
                "reward_mode": "DISCOVERY",
            },
            "arc_cadence": [
                {"arc_plan_version_id": "arc:main:v1", "action": "ADVANCE"}
            ],
            "obligation_actions": [],
        }
        result = validate_chapter_function_matrix(
            [row], group_objective="advance one accepted-reality window"
        )
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["chapter_count"], 1)
        self.assertEqual(
            result["reader_experience_comparison"],
            {"status": "NOT_APPLICABLE", "observation_count": 1},
        )

        with self.assertRaisesRegex(KernelError, "READER_EXPERIENCE_HOMOGENEITY"):
            validate_chapter_function_matrix(
                [row, {**row, "chapter_number": 2}],
                group_objective="advance the next window",
            )
        with self.assertRaisesRegex(KernelError, "GROUP_OBJECTIVE_NO_PROGRESS"):
            validate_chapter_function_matrix(
                [{**row, "required_state_delta": {}}],
                group_objective="advance one accepted-reality window",
            )


if __name__ == "__main__":
    unittest.main()
