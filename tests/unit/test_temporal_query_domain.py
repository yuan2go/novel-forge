from __future__ import annotations

import unittest

from novel_forge.modules.narrative_state import events_from_canon_patch
from novel_forge.modules.temporal_query.service import (
    TemporalQueryService,
    TemporalStateEvent,
    changes_in_range,
    reduce_entity_state,
)


class _FixtureTemporalQueryService(TemporalQueryService):
    def __init__(self, events: tuple[TemporalStateEvent, ...]) -> None:
        self.fixture_events = events

    def _events(
        self,
        project_id: str,
        book_id: str,
        *,
        state_kinds: tuple[str, ...] = (),
        through_chapter: int,
    ) -> tuple[TemporalStateEvent, ...]:
        return tuple(
            event
            for event in self.fixture_events
            if event.project_id == project_id
            and event.book_id == book_id
            and event.accepted_chapter <= through_chapter
            and (not state_kinds or event.event.state_kind.value in state_kinds)
        )


def _event(
    *,
    accepted_chapter: int,
    state_kind: str,
    payload: dict[str, object],
    ordinal: int = 0,
) -> TemporalStateEvent:
    event = events_from_canon_patch(
        project_id="project-a",
        book_id="book-a",
        source_chapter=accepted_chapter,
        chapter_outcome_id=f"outcome-{accepted_chapter}",
        canon_patch_asset_version_id=f"canon-{accepted_chapter}",
        accepted_draft_asset_version_id=f"draft-{accepted_chapter}",
        source_operation_id=f"operation-{accepted_chapter}",
        trace_id=f"trace-{accepted_chapter}",
        canon_patch={"state_changes": {state_kind: [payload]}},
    )[0]
    return TemporalStateEvent(
        project_id="project-a",
        book_id="book-a",
        book_run_id="run-a",
        acceptance_id=f"acceptance-{accepted_chapter}",
        acceptance_operation_id=f"accept-{accepted_chapter}",
        trace_id=f"trace-{accepted_chapter}",
        accepted_chapter=accepted_chapter,
        chapter_outcome_asset_version_id=f"outcome-version-{accepted_chapter}",
        event=event,
        event_ordinal=ordinal,
        recorded_at=f"2026-08-12T00:{accepted_chapter:02d}:00+00:00",
    )


class TemporalQueryDomainTests(unittest.TestCase):
    def test_character_knowledge_is_hidden_before_acquisition_chapter(self) -> None:
        service = _FixtureTemporalQueryService(
            (
                _event(
                    accepted_chapter=30,
                    state_kind="character_state",
                    payload={
                        "character_id": "hero",
                        "acquired_fact_ids": ["secret-origin"],
                    },
                ),
            )
        )

        before = service.character_knows_at(
            "project-a", "book-a", "hero", "secret-origin", 20
        )
        after = service.character_knows_at(
            "project-a", "book-a", "hero", "secret-origin", 35
        )

        self.assertEqual(before["status"], "NOT_FOUND")
        self.assertFalse(before["knows"])
        self.assertEqual(after["status"], "FOUND")
        self.assertTrue(after["knows"])

    def test_as_of_boundary_excludes_future_information(self) -> None:
        events = (
            _event(
                accepted_chapter=10,
                state_kind="character_state",
                payload={"character_id": "hero", "location": "Hangzhou"},
            ),
            _event(
                accepted_chapter=30,
                state_kind="character_state",
                payload={
                    "character_id": "hero",
                    "location": "Beijing",
                    "acquired_fact_ids": ["secret-origin"],
                },
            ),
        )

        result = reduce_entity_state(
            events,
            state_kind="character_state",
            entity_key="character_id=hero",
            as_of_chapter=20,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["state"]["location"], "Hangzhou")
        self.assertNotIn("known_fact_ids", result["state"])

    def test_relationship_transition_returns_old_then_new_state(self) -> None:
        events = (
            _event(
                accepted_chapter=12,
                state_kind="relationship_state",
                payload={"source_id": "hero", "target_id": "mentor", "status": "TRUSTED"},
            ),
            _event(
                accepted_chapter=40,
                state_kind="relationship_state",
                payload={
                    "source_id": "hero",
                    "target_id": "mentor",
                    "from_status": "TRUSTED",
                    "status": "HOSTILE",
                },
            ),
        )

        old = reduce_entity_state(
            events,
            state_kind="relationship_state",
            entity_key="source_id=hero|target_id=mentor",
            as_of_chapter=35,
        )
        new = reduce_entity_state(
            events,
            state_kind="relationship_state",
            entity_key="source_id=hero|target_id=mentor",
            as_of_chapter=45,
        )

        self.assertEqual(old["state"]["status"], "TRUSTED")
        self.assertEqual(new["state"]["status"], "HOSTILE")

    def test_retrospective_event_is_hidden_until_accepted(self) -> None:
        event = _event(
            accepted_chapter=30,
            state_kind="power_state",
            payload={
                "character_id": "hero",
                "tier": 4,
                "effective_from_chapter": 20,
            },
        )

        result = reduce_entity_state(
            (event,),
            state_kind="power_state",
            entity_key="character_id=hero",
            as_of_chapter=25,
        )

        self.assertEqual(result["status"], "NOT_FOUND")

    def test_explicit_supersession_replaces_prior_world_rule(self) -> None:
        first = _event(
            accepted_chapter=8,
            state_kind="world_rule",
            payload={"rule_id": "magic-cost", "definition": "memory", "status": "ACTIVE"},
        )
        second = _event(
            accepted_chapter=18,
            state_kind="world_rule",
            payload={
                "rule_id": "magic-cost",
                "definition": "lifespan",
                "status": "ACTIVE",
                "supersedes_event_id": first.event.event_id,
            },
        )

        result = reduce_entity_state(
            (first, second),
            state_kind="world_rule",
            entity_key="rule_id=magic-cost",
            as_of_chapter=20,
        )

        self.assertEqual(result["state"]["definition"], "lifespan")
        self.assertEqual(
            result["supersedes_event_id"], first.event.event_id
        )

    def test_changes_between_is_left_open_right_closed_by_acceptance(self) -> None:
        events = tuple(
            _event(
                accepted_chapter=chapter,
                state_kind="foreshadow_state",
                payload={"thread_id": f"door-{chapter}", "status": status},
            )
            for chapter, status in ((20, "PLANTED"), (30, "DEVELOPED"), (40, "PAID"))
        )

        result = changes_in_range(events, chapter_from=20, chapter_to=40)

        self.assertEqual([item.accepted_chapter for item in result], [30, 40])

    def test_missing_state_is_explicit_and_never_inferred(self) -> None:
        result = reduce_entity_state(
            (),
            state_kind="plot_thread",
            entity_key="thread_id=missing",
            as_of_chapter=12,
        )

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["missing_reason"], "NO_ACCEPTED_STATE_AT_BOUNDARY")
        self.assertTrue(result["accepted_state_only"])


if __name__ == "__main__":
    unittest.main()
