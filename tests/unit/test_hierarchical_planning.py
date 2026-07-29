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


if __name__ == "__main__":
    unittest.main()
