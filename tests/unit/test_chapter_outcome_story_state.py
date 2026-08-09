from __future__ import annotations

from copy import deepcopy
import unittest

from novel_forge.modules.chapter_outcome.domain import (
    build_chapter_outcome,
    reduce_story_state,
)
from novel_forge.modules.command_kernel.errors import KernelError


class ChapterOutcomeStoryStateTests(unittest.TestCase):
    def _chapter_outcome(self) -> dict:
        return build_chapter_outcome(
            project_id="project-1",
            book_id="book-1",
            chapter_number=1,
            chapter_plan_version_id="plan-v1",
            parent_group_version_id="group-v1",
            accepted_draft_version_id="draft-v1",
            final_release_gate_version_id="release-v1",
            quality_aggregate_version_id="quality-v1",
            canon_patch={
                "gate": "PASSED",
                "conflicts": [],
                "snapshot_candidates": [
                    {
                        "state_kind": "timeline_snapshot",
                        "changes": [{"event_id": "event-1"}],
                    },
                    {
                        "state_kind": "character_state",
                        "changes": [{"character_id": "hero", "status": "injured"}],
                    },
                    {
                        "state_kind": "reader_promise",
                        "changes": [{"promise_id": "promise-1", "status": "OPEN"}],
                    },
                ],
            },
            cost_receipt_refs=("cost-1",),
            created_by_operation_id="operation-1",
        )

    def test_chapter_outcome_requires_accepted_chapter(self) -> None:
        with self.assertRaisesRegex(
            KernelError, "CHAPTER_OUTCOME_PRECONDITION_FAILED"
        ):
            build_chapter_outcome(
                project_id="project-1",
                book_id="book-1",
                chapter_number=1,
                chapter_plan_version_id="plan-v1",
                parent_group_version_id="group-v1",
                accepted_draft_version_id="draft-v1",
                final_release_gate_version_id="release-v1",
                quality_aggregate_version_id="quality-v1",
                canon_patch={"gate": "BLOCKED", "conflicts": [{"code": "x"}]},
                cost_receipt_refs=(),
                created_by_operation_id="operation-1",
            )

    def test_chapter_outcome_binds_frozen_plan_version(self) -> None:
        outcome = self._chapter_outcome()
        self.assertEqual(outcome["chapter_plan_version_id"], "plan-v1")
        self.assertEqual(outcome["accepted_draft_version_id"], "draft-v1")
        self.assertEqual(outcome["occurred_events"], [{"event_id": "event-1"}])

    def test_story_state_reducer_is_deterministic_and_append_only(self) -> None:
        previous = {
            "type": "StoryStateSnapshot",
            "timeline": [{"event_id": "earlier"}],
            "applied_chapter_outcome_versions": ["outcome-v0"],
            "state_version": 1,
        }
        untouched = deepcopy(previous)
        first = reduce_story_state(
            previous=previous,
            chapter_outcome=self._chapter_outcome(),
            chapter_outcome_asset_version_id="outcome-v1",
        )
        second = reduce_story_state(
            previous=previous,
            chapter_outcome=self._chapter_outcome(),
            chapter_outcome_asset_version_id="outcome-v1",
        )
        self.assertEqual(first, second)
        self.assertEqual(previous, untouched)
        self.assertEqual(
            first["timeline"],
            [{"event_id": "earlier"}, {"event_id": "event-1"}],
        )
        self.assertEqual(first["state_version"], 2)
        self.assertEqual(first["chapter"], 1)
        self.assertEqual(first["chapter_number"], 1)

    def test_story_state_reducer_is_idempotent(self) -> None:
        first = reduce_story_state(
            previous=None,
            chapter_outcome=self._chapter_outcome(),
            chapter_outcome_asset_version_id="outcome-v1",
        )
        replay = reduce_story_state(
            previous=first,
            chapter_outcome=self._chapter_outcome(),
            chapter_outcome_asset_version_id="outcome-v1",
        )
        self.assertEqual(replay, first)


if __name__ == "__main__":
    unittest.main()
