from __future__ import annotations

from novel_forge.modules.narrative_state import (
    events_from_canon_patch,
    project_entity_state,
    reduce_story_state_v2,
)


def _events(chapter: int, change: dict[str, object]):
    return events_from_canon_patch(
        project_id="project:1",
        book_id="book:1",
        source_chapter=chapter,
        chapter_outcome_id=f"outcome:{chapter}",
        canon_patch_asset_version_id=f"canon-patch:{chapter}",
        accepted_draft_asset_version_id=f"draft:{chapter}",
        source_operation_id=f"operation:{chapter}",
        trace_id="trace:1",
        canon_patch={
            "gate": "PASSED",
            "conflicts": [],
            "obligation_changes": [change],
        },
    )


def test_obligation_contract_covers_commitment_visibility_dependencies_and_history() -> None:
    events = _events(
        3,
        {
            "obligation_id": "obligation:commitment:1",
            "obligation_type": "CHARACTER_COMMITMENT",
            "status": "OPEN",
            "priority": "HIGH",
            "urgency": "CRITICAL",
            "reader_visibility": "VISIBLE",
            "current_development": "She promises to return before the siege.",
            "dependencies": ["obligation:mystery:1"],
            "target_window": {
                "status": "SCHEDULED",
                "from_chapter": 8,
                "to_chapter": 12,
            },
            "linked_character_ids": ["character:hero"],
            "linked_arc_ids": ["arc-plan:v1"],
            "linked_volume_ids": ["volume-plan:v1"],
            "expected_payoff": {"description": "return changes the siege"},
        },
    )
    payload = events[0].payload
    assert payload["obligation_type"] == "CHARACTER_COMMITMENT"
    assert payload["dependencies"] == ["obligation:mystery:1"]
    assert payload["reader_visibility"] == "VISIBLE"
    assert payload["development_history"] == [
        {
            "chapter": 3,
            "status": "OPEN",
            "development": "She promises to return before the siege.",
        }
    ]


def test_obligation_development_history_appends_across_accepted_outcomes() -> None:
    first_events = _events(
        1,
        {
            "obligation_id": "obligation:hook:1",
            "obligation_type": "HOOK",
            "status": "OPEN",
            "current_development": "A sealed room hums.",
        },
    )
    first = reduce_story_state_v2(
        previous=None,
        events=first_events,
        chapter_outcome_asset_version_id="outcome:v1",
        chapter_outcome_id="outcome:1",
    )
    second_events = _events(
        2,
        {
            "obligation_id": "obligation:hook:1",
            "obligation_type": "HOOK",
            "from_status": "OPEN",
            "status": "DEVELOPING",
            "current_development": "The hum answers the protagonist.",
            "target_window": {
                "status": "SCHEDULED",
                "from_chapter": 2,
                "to_chapter": 5,
            },
        },
    )
    second = reduce_story_state_v2(
        previous=first,
        events=second_events,
        chapter_outcome_asset_version_id="outcome:v2",
        chapter_outcome_id="outcome:2",
        previous_story_state_asset_version_id="story-state:v1",
    )
    state = project_entity_state(
        second,
        "narrative_obligation",
        second_events[0].identity.entity_key,
    )
    assert [item["chapter"] for item in state["state"]["development_history"]] == [
        1,
        2,
    ]
