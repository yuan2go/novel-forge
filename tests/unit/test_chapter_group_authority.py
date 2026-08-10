from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from novel_forge.modules.chapter_group_authority import (
    ChapterGroupRange,
    ChapterGroupState,
    PostgresChapterGroupAuthority,
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
        with self.assertRaisesRegex(KernelError, "CHAPTER_GROUP_ACTIVE_CHILD_EXISTS"):
            require_next_chapter(
                state=ChapterGroupState.READY,
                accepted_through=0,
                active_chapter=1,
                chapter_number=1,
                chapter_range=ChapterGroupRange(1, 3),
            )
        with self.assertRaisesRegex(KernelError, "CHAPTER_GROUP_SEQUENCE_CONFLICT"):
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
            state_after_acceptance(chapter_number=2, chapter_range=chapter_range),
            ChapterGroupState.READY,
        )
        self.assertEqual(
            state_after_acceptance(chapter_number=3, chapter_range=chapter_range),
            ChapterGroupState.CLOSURE_PENDING,
        )

    def test_overlapping_replacement_group_requires_current_resolved_snapshot(
        self,
    ) -> None:
        authority = object.__new__(PostgresChapterGroupAuthority)
        authority.database_url = "postgresql://authority"
        cursor = SimpleNamespace(
            execute=lambda *_args, **_kwargs: None,
            fetchone=lambda: ("chapter-group:v2",),
        )
        uow = MagicMock()
        uow.cursor = cursor
        uow.__enter__.return_value = uow
        book = {
            "input_mode": "RESOLVED_AUTHORITY_INPUT",
            "input_snapshot_id": "snapshot:v2",
        }

        with patch(
            "novel_forge.modules.chapter_group_authority.application.AuthorityUnitOfWork",
            return_value=uow,
        ):
            authority._require_replacement_group_snapshot(
                book=book,
                group_plan_version_id="chapter-group:v2",
            )
            with self.assertRaisesRegex(
                KernelError, "CHAPTER_GROUP_REPLACEMENT_SNAPSHOT_MISMATCH"
            ):
                authority._require_replacement_group_snapshot(
                    book=book,
                    group_plan_version_id="chapter-group:stale",
                )

        with self.assertRaisesRegex(
            KernelError, "CHAPTER_GROUP_REPLACEMENT_RESOLVED_INPUT_REQUIRED"
        ):
            authority._require_replacement_group_snapshot(
                book={**book, "input_mode": "LEGACY_FIXTURE_INPUT"},
                group_plan_version_id="chapter-group:v2",
            )

    def test_approved_replan_supersede_rejects_wrong_plan_or_active_child(
        self,
    ) -> None:
        authority = object.__new__(PostgresChapterGroupAuthority)
        group = {
            "group_run_id": "group-run:1",
            "project_id": "project:1",
            "group_plan_version_id": "chapter-group:v1",
            "active_chapter_request_id": None,
            "state": ChapterGroupState.READY.value,
        }
        authority.require = lambda _group_run_id: dict(group)
        principal = SimpleNamespace(require=lambda *_args: None)

        with self.assertRaisesRegex(
            KernelError, "CHAPTER_GROUP_REPLAN_TARGET_MISMATCH"
        ):
            authority.supersede_for_approved_replan(
                "group-run:1",
                replan_id="replan:1",
                target_group_plan_version_id="chapter-group:other",
                principal=principal,
            )

        group["active_chapter_request_id"] = "chapter-request:2"
        with self.assertRaisesRegex(KernelError, "CHAPTER_GROUP_REPLAN_ACTIVE_CHILD"):
            authority.supersede_for_approved_replan(
                "group-run:1",
                replan_id="replan:1",
                target_group_plan_version_id="chapter-group:v1",
                principal=principal,
            )


if __name__ == "__main__":
    unittest.main()
