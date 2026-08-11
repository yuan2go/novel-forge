from __future__ import annotations

import unittest

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
        *,
        state_kinds: tuple[str, ...] = (),
        through_chapter: int,
    ) -> tuple[TemporalStateEvent, ...]:
        return tuple(
            event
            for event in self.fixture_events
            if event.project_id == project_id
            and event.accepted_chapter <= through_chapter
            and event.effective_chapter <= through_chapter
            and (not state_kinds or event.state_kind in state_kinds)
        )


def _event(
    *,
    chapter: int,
    state_kind: str,
    payload: dict[str, object],
    version: str,
    accepted_chapter: int | None = None,
) -> TemporalStateEvent:
    return TemporalStateEvent(
        project_id="project-a",
        book_id="book-a",
        book_run_id="run-a",
        acceptance_id=f"acceptance-{version}",
        operation_id=f"operation-{version}",
        trace_id=f"trace-{version}",
        accepted_chapter=accepted_chapter or chapter,
        state_kind=state_kind,
        asset_type=f"{state_kind}_snapshot",
        asset_version_id=version,
        effective_chapter=chapter,
        payload=payload,
        recorded_at=f"2026-08-11T00:{chapter:02d}:00+00:00",
    )


class TemporalQueryDomainTests(unittest.TestCase):
    def test_character_knowledge_is_hidden_before_acquisition_chapter(self) -> None:
        service = _FixtureTemporalQueryService(
            (
                _event(
                    chapter=30,
                    state_kind="character_state",
                    version="knowledge-v30",
                    payload={
                        "character_id": "hero",
                        "fact_id": "secret-origin",
                        "knowledge_state": "KNOWN",
                    },
                ),
            )
        )

        before = service.character_knows_at("project-a", "hero", "secret-origin", 20)
        after = service.character_knows_at("project-a", "hero", "secret-origin", 35)

        self.assertEqual(before["status"], "NOT_FOUND")
        self.assertEqual(before["project_id"], "project-a")
        self.assertFalse(before["knows"])
        self.assertEqual(after["status"], "FOUND")
        self.assertEqual(after["project_id"], "project-a")
        self.assertTrue(after["knows"])

    def test_as_of_boundary_excludes_future_information(self) -> None:
        events = (
            _event(
                chapter=10,
                state_kind="character_state",
                version="character-v10",
                payload={"character_id": "hero", "location": "harbor"},
            ),
            _event(
                chapter=30,
                state_kind="character_state",
                version="character-v30",
                payload={
                    "character_id": "hero",
                    "fact_id": "secret-origin",
                    "knowledge_state": "KNOWN",
                },
            ),
        )

        result = reduce_entity_state(
            events,
            state_kind="character_state",
            identity=("character_id", "hero"),
            as_of_chapter=20,
        )

        self.assertEqual(result["status"], "FOUND")
        self.assertEqual(result["state"]["location"], "harbor")
        self.assertNotIn("fact_id", result["state"])
        self.assertEqual(result["observed_through_chapter"], 10)
        self.assertEqual(result["trace_ids"], ["trace-character-v10"])

    def test_relationship_transition_returns_old_then_new_state(self) -> None:
        events = (
            _event(
                chapter=12,
                state_kind="relationship_state",
                version="relationship-v12",
                payload={
                    "source_id": "hero",
                    "target_id": "mentor",
                    "relationship_state": "TRUSTED",
                },
            ),
            _event(
                chapter=40,
                state_kind="relationship_state",
                version="relationship-v40",
                payload={
                    "source_id": "hero",
                    "target_id": "mentor",
                    "relationship_state": "HOSTILE",
                },
            ),
        )

        old = reduce_entity_state(
            events,
            state_kind="relationship_state",
            identity=("relationship", ("hero", "mentor")),
            as_of_chapter=35,
        )
        new = reduce_entity_state(
            events,
            state_kind="relationship_state",
            identity=("relationship", ("hero", "mentor")),
            as_of_chapter=45,
        )

        self.assertEqual(old["state"]["relationship_state"], "TRUSTED")
        self.assertEqual(new["state"]["relationship_state"], "HOSTILE")
        self.assertEqual(
            new["source_asset_version_ids"],
            [
                "relationship-v12",
                "relationship-v40",
            ],
        )

    def test_unaccepted_future_effective_event_is_not_visible(self) -> None:
        events = (
            _event(
                chapter=20,
                accepted_chapter=30,
                state_kind="power_state",
                version="power-v30",
                payload={"character_id": "hero", "tier": 4},
            ),
        )

        result = reduce_entity_state(
            events,
            state_kind="power_state",
            identity=("character_id", "hero"),
            as_of_chapter=25,
        )

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(result["missing_reason"], "NO_ACCEPTED_STATE_AT_BOUNDARY")

    def test_explicit_supersession_removes_prior_fields_before_reduction(self) -> None:
        events = (
            _event(
                chapter=8,
                state_kind="world_rule",
                version="rule-v8",
                payload={"rule_id": "magic-cost", "cost": "memory", "status": "ACTIVE"},
            ),
            _event(
                chapter=18,
                state_kind="world_rule",
                version="rule-v18",
                payload={
                    "rule_id": "magic-cost",
                    "cost": "lifespan",
                    "status": "ACTIVE",
                    "supersedes_version_id": "rule-v8",
                },
            ),
        )

        result = reduce_entity_state(
            events,
            state_kind="world_rule",
            identity=("rule_id", "magic-cost"),
            as_of_chapter=20,
        )

        self.assertEqual(result["state"]["cost"], "lifespan")
        self.assertNotIn("rule-v8", result["source_asset_version_ids"])
        self.assertEqual(result["superseded_asset_version_ids"], ["rule-v8"])

    def test_changes_between_is_left_open_right_closed(self) -> None:
        events = tuple(
            _event(
                chapter=chapter,
                state_kind="foreshadow_state",
                version=f"thread-v{chapter}",
                payload={"thread_id": "door", "status": status},
            )
            for chapter, status in ((20, "PLANTED"), (30, "DEVELOPED"), (40, "PAID"))
        )

        result = changes_in_range(
            events,
            chapter_from=20,
            chapter_to=40,
        )

        self.assertEqual([item.effective_chapter for item in result], [30, 40])

    def test_accepted_rollback_event_rebuilds_prior_state_deterministically(
        self,
    ) -> None:
        events = (
            _event(
                chapter=8,
                state_kind="world_rule",
                version="snapshot-v8",
                payload={
                    "rule_id": "magic-cost",
                    "source_asset_version_id": "rule-v1",
                    "cost": "memory",
                },
            ),
            _event(
                chapter=18,
                state_kind="world_rule",
                version="snapshot-v18",
                payload={
                    "rule_id": "magic-cost",
                    "source_asset_version_id": "rule-v2",
                    "supersedes_version_id": "rule-v1",
                    "cost": "lifespan",
                },
            ),
            _event(
                chapter=25,
                state_kind="world_rule",
                version="snapshot-v25",
                payload={
                    "rule_id": "magic-cost",
                    "source_asset_version_id": "rule-v3-rollback",
                    "supersedes_version_id": "rule-v2",
                    "rollback_to_asset_version_id": "rule-v1",
                    "cost": "memory",
                },
            ),
        )

        first = reduce_entity_state(
            events,
            state_kind="world_rule",
            identity=("rule_id", "magic-cost"),
            as_of_chapter=25,
        )
        rebuilt = reduce_entity_state(
            (events[2], events[0], events[1]),
            state_kind="world_rule",
            identity=("rule_id", "magic-cost"),
            as_of_chapter=25,
        )

        self.assertEqual(first, rebuilt)
        self.assertEqual(first["state"]["cost"], "memory")
        self.assertEqual(first["state"]["rollback_to_asset_version_id"], "rule-v1")
        self.assertIn("rule-v2", first["superseded_asset_version_ids"])

    def test_missing_state_is_explicit_and_never_inferred(self) -> None:
        result = reduce_entity_state(
            (),
            state_kind="plot_thread",
            identity=("thread_id", "missing"),
            as_of_chapter=12,
        )

        self.assertEqual(
            result,
            {
                "status": "NOT_FOUND",
                "state_kind": "plot_thread",
                "as_of_chapter": 12,
                "boundary": "INCLUSIVE",
                "accepted_state_only": True,
                "missing_reason": "NO_ACCEPTED_STATE_AT_BOUNDARY",
                "state": None,
                "source_asset_version_ids": [],
                "source_operation_ids": [],
                "trace_ids": [],
                "superseded_asset_version_ids": [],
                "observed_through_chapter": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
