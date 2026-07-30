from __future__ import annotations

import unittest

from novel_forge.modules.chapter_group_authority import (
    ChapterGroupRange,
    ChapterGroupState,
    require_next_chapter,
    state_after_acceptance,
)
from novel_forge.modules.command_kernel.errors import KernelError


class ChapterGroupAuthorityDomainTests(unittest.TestCase):
    def test_group_range_is_three_to_eight_chapters(self) -> None:
        self.assertEqual(ChapterGroupRange(3, 5).count, 3)
        for boundaries in ((1, 2), (1, 9), (0, 3)):
            with self.assertRaises(ValueError):
                ChapterGroupRange(*boundaries)

    def test_group_dispatches_one_active_child_at_a_time(self) -> None:
        with self.assertRaisesRegex(
            KernelError, "CHAPTER_GROUP_ACTIVE_CHILD_EXISTS"
        ):
            require_next_chapter(
                state=ChapterGroupState.READY,
                accepted_through=0,
                active_chapter=1,
                chapter_number=1,
                chapter_range=ChapterGroupRange(1, 3),
            )
        with self.assertRaisesRegex(
            KernelError, "CHAPTER_GROUP_SEQUENCE_CONFLICT"
        ):
            require_next_chapter(
                state=ChapterGroupState.READY,
                accepted_through=0,
                active_chapter=None,
                chapter_number=2,
                chapter_range=ChapterGroupRange(1, 3),
            )

    def test_group_closure_requires_final_chapter(self) -> None:
        chapter_range = ChapterGroupRange(1, 3)
        self.assertEqual(
            state_after_acceptance(
                chapter_number=2, chapter_range=chapter_range
            ),
            ChapterGroupState.READY,
        )
        self.assertEqual(
            state_after_acceptance(
                chapter_number=3, chapter_range=chapter_range
            ),
            ChapterGroupState.CLOSURE_PENDING,
        )


if __name__ == "__main__":
    unittest.main()
