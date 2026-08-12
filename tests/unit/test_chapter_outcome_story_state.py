from __future__ import annotations

from copy import deepcopy
import unittest

from novel_forge.modules.chapter_outcome.domain import (
    build_chapter_outcome,
    reduce_story_state,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import project_entity_state


class ChapterOutcomeStoryStateTests(unittest.TestCase):
    def _chapter_outcome(
        self,
        *,
        chapter: int = 1,
        location: str = "Hangzhou",
        previous_location_event_id: str = "",
    ) -> dict:
        character: dict[str, object] = {
            "character_id": "character:hero",
            "location": location,
            "status": "INJURED" if chapter == 1 else "RECOVERING",
        }
        if previous_location_event_id:
            character["supersedes_event_id"] = previous_location_event_id
        return build_chapter_outcome(
            project_id="project-1",
            book_id="book-1",
            chapter_number=chapter,
            chapter_plan_version_id=f"plan-v{chapter}",
            parent_group_version_id="group-v1",
            accepted_draft_version_id=f"draft-v{chapter}",
            final_release_gate_version_id=f"release-v{chapter}",
            quality_aggregate_version_id=f"quality-v{chapter}",
            canon_patch_asset_version_id=f"canon-patch-v{chapter}",
            canon_patch={
                "gate": "PASSED",
                "conflicts": [],
                "state_changes": {
                    "timeline_event": [
                        {
                            "event_id": f"event-{chapter}",
                            "summary": f"Chapter {chapter} accepted event",
                        }
                    ],
                    "character_state": [character],
                    "reader_promise": [
                        {
                            "promise_id": "promise-1",
                            "status": "OPEN",
                            **(
                                {"from_status": "OPEN"}
                                if chapter > 1
                                else {}
                            ),
                        }
                    ],
                },
            },
            cost_receipt_refs=("cost-1",),
            created_by_operation_id=f"operation-{chapter}",
            trace_id="trace-book-1",
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
                canon_patch_asset_version_id="canon-patch-v1",
                canon_patch={"gate": "BLOCKED", "conflicts": [{"code": "x"}]},
                cost_receipt_refs=(),
                created_by_operation_id="operation-1",
                trace_id="trace-1",
            )

    def test_chapter_outcome_binds_plan_and_normalized_state_events(self) -> None:
        outcome = self._chapter_outcome()
        self.assertEqual(outcome["contract_version"], "chapter-outcome-v2")
        self.assertEqual(outcome["chapter_plan_version_id"], "plan-v1")
        self.assertEqual(outcome["accepted_draft_asset_version_id"], "draft-v1")
        self.assertEqual(outcome["canon_patch_asset_version_id"], "canon-patch-v1")
        self.assertEqual(len(outcome["state_events"]), 3)
        self.assertNotIn("character_deltas", outcome)
        self.assertNotIn("occurred_events", outcome)

    def test_story_state_materializes_current_entity_and_preserves_input(self) -> None:
        first_outcome = self._chapter_outcome()
        first = reduce_story_state(
            previous=None,
            chapter_outcome=first_outcome,
            chapter_outcome_asset_version_id="outcome-v1",
        )
        untouched = deepcopy(first)
        hero_v1 = project_entity_state(
            first, "character_state", "character_id=character:hero"
        )
        second_outcome = self._chapter_outcome(
            chapter=2,
            location="Beijing",
            previous_location_event_id=hero_v1["source_event_id"],
        )
        second = reduce_story_state(
            previous=first,
            chapter_outcome=second_outcome,
            chapter_outcome_asset_version_id="outcome-v2",
        )

        self.assertEqual(first, untouched)
        self.assertEqual(second["contract_version"], "story-state-snapshot-v2")
        self.assertEqual(second["state_version"], 2)
        self.assertEqual(second["accepted_through_chapter"], 2)
        self.assertEqual(
            project_entity_state(
                second, "character_state", "character_id=character:hero"
            )["state"]["location"],
            "Beijing",
        )
        self.assertEqual(len(second["current_state"]["character_state"]), 1)

    def test_story_state_reducer_is_idempotent(self) -> None:
        outcome = self._chapter_outcome()
        first = reduce_story_state(
            previous=None,
            chapter_outcome=outcome,
            chapter_outcome_asset_version_id="outcome-v1",
        )
        replay = reduce_story_state(
            previous=first,
            chapter_outcome=outcome,
            chapter_outcome_asset_version_id="outcome-v1",
        )
        self.assertEqual(replay, first)


if __name__ == "__main__":
    unittest.main()
