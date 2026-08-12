from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    compact_current_state_facts,
    events_from_canon_patch,
    events_from_chapter_outcome,
    project_entity_state,
    rebuild_story_state,
    reduce_story_state_v2,
)


PROJECT = "project-river-city"
BOOK = "book-river-city"


def _outcome(chapter: int, state_changes: dict[str, list[dict]]) -> tuple[str, dict]:
    outcome_id = f"chapter-outcome:{BOOK}:{chapter}:plan-v{chapter}"
    version_id = f"outcome-v{chapter}"
    events = events_from_canon_patch(
        project_id=PROJECT,
        book_id=BOOK,
        source_chapter=chapter,
        chapter_outcome_id=outcome_id,
        canon_patch_asset_version_id=f"canon-v{chapter}",
        accepted_draft_asset_version_id=f"draft-v{chapter}",
        source_operation_id=f"operation-v{chapter}",
        trace_id="trace-river-city",
        canon_patch={"state_changes": state_changes},
    )
    return version_id, {
        "type": "ChapterOutcome",
        "contract_version": "chapter-outcome-v2",
        "chapter_outcome_id": outcome_id,
        "project_id": PROJECT,
        "book_id": BOOK,
        "chapter_number": chapter,
        "state_events": [event.to_dict() for event in events],
    }


def _readable_outcomes() -> list[tuple[str, dict]]:
    return [
        _outcome(
            1,
            {
                "character_state": [
                    {
                        "character_id": "character:lin",
                        "canonical_name": "Lin",
                        "location": "Hangzhou",
                        "life_status": "ALIVE",
                    }
                ],
                "resource_state": [
                    {
                        "entity_id": "character:lin",
                        "resource_id": "resource:x",
                        "balance": 5,
                    }
                ],
            },
        ),
        _outcome(
            10,
            {
                "character_state": [
                    {
                        "character_id": "character:lin",
                        "acquired_fact_ids": ["secret:x"],
                    }
                ]
            },
        ),
        _outcome(
            20,
            {
                "relationship_state": [
                    {
                        "source_id": "character:lin",
                        "target_id": "character:mei",
                        "status": "HOSTILE",
                    }
                ]
            },
        ),
        _outcome(
            30,
            {
                "character_state": [
                    {"character_id": "character:lin", "location": "Beijing"}
                ]
            },
        ),
        _outcome(
            40,
            {
                "reader_promise": [
                    {"promise_id": "promise:p", "status": "OPEN"}
                ],
                "foreshadow_state": [
                    {"thread_id": "foreshadow:f", "status": "PLANTED"}
                ],
                "plot_thread": [
                    {"thread_id": "plot:t", "status": "OPEN"}
                ],
            },
        ),
        _outcome(
            50,
            {
                "world_rule": [
                    {
                        "rule_id": "world-rule:r",
                        "status": "ACTIVE",
                        "definition": "Every gate crossing consumes one seal.",
                    }
                ]
            },
        ),
        _outcome(
            60,
            {
                "resource_state": [
                    {
                        "entity_id": "character:lin",
                        "resource_id": "resource:x",
                        "balance_before": 5,
                        "delta": -2,
                        "balance_after": 3,
                    }
                ]
            },
        ),
        _outcome(
            70,
            {
                "foreshadow_state": [
                    {
                        "thread_id": "foreshadow:f",
                        "from_status": "PLANTED",
                        "status": "PAID",
                        "payoff_evidence": "Lin recognizes the seal from Chapter 40.",
                    }
                ]
            },
        ),
        _outcome(
            80,
            {
                "reader_promise": [
                    {
                        "promise_id": "promise:p",
                        "from_status": "OPEN",
                        "status": "PAID",
                        "payoff_evidence": "The promised identity is revealed.",
                    }
                ]
            },
        ),
        _outcome(
            90,
            {
                "relationship_state": [
                    {
                        "source_id": "character:lin",
                        "target_id": "character:mei",
                        "from_status": "HOSTILE",
                        "status": "REPAIRED",
                    }
                ]
            },
        ),
        _outcome(
            100,
            {
                "plot_thread": [
                    {
                        "thread_id": "plot:t",
                        "from_status": "OPEN",
                        "status": "RESOLVED",
                    }
                ]
            },
        ),
    ]


def _at(chapter: int) -> dict:
    return rebuild_story_state(
        [item for item in _readable_outcomes() if int(item[1]["chapter_number"]) <= chapter]
    )


def test_current_state_is_entity_aware_and_not_a_history_of_character_changes() -> None:
    state = _at(100)
    lin = project_entity_state(state, "character_state", "character_id=character:lin")
    relation = project_entity_state(
        state,
        "relationship_state",
        "source_id=character:lin|target_id=character:mei",
    )
    resource = project_entity_state(
        state,
        "resource_state",
        "entity_id=character:lin|resource_id=resource:x",
    )

    assert state["contract_version"] == "story-state-snapshot-v2"
    assert len(state["current_state"]["character_state"]) == 1
    assert lin["state"]["location"] == "Beijing"
    assert lin["state"]["known_fact_ids"] == ["secret:x"]
    assert relation["state"]["status"] == "REPAIRED"
    assert resource["state"]["balance"] == 3
    assert project_entity_state(
        state, "reader_promise", "promise_id=promise:p"
    )["state"]["status"] == "PAID"
    assert project_entity_state(
        state, "plot_thread", "thread_id=plot:t"
    )["state"]["status"] == "RESOLVED"


def test_as_of_rebuild_exposes_no_future_state() -> None:
    assert project_entity_state(
        _at(1), "character_state", "character_id=character:lin"
    )["state"]["location"] == "Hangzhou"
    assert project_entity_state(
        _at(9), "character_state", "character_id=character:lin"
    )["state"].get("known_fact_ids", []) == []
    assert project_entity_state(
        _at(10), "character_state", "character_id=character:lin"
    )["state"]["known_fact_ids"] == ["secret:x"]
    assert project_entity_state(
        _at(29), "character_state", "character_id=character:lin"
    )["state"]["location"] == "Hangzhou"
    assert project_entity_state(
        _at(30), "character_state", "character_id=character:lin"
    )["state"]["location"] == "Beijing"
    assert project_entity_state(
        _at(39), "reader_promise", "promise_id=promise:p"
    )["status"] == "NOT_FOUND"
    assert project_entity_state(
        _at(79), "reader_promise", "promise_id=promise:p"
    )["state"]["status"] == "OPEN"
    assert project_entity_state(
        _at(80), "reader_promise", "promise_id=promise:p"
    )["state"]["status"] == "PAID"
    assert project_entity_state(
        _at(89),
        "relationship_state",
        "source_id=character:lin|target_id=character:mei",
    )["state"]["status"] == "HOSTILE"


def test_replay_is_deterministic_and_duplicate_head_is_idempotent() -> None:
    outcomes = _readable_outcomes()
    rebuilt_a = rebuild_story_state(outcomes)
    rebuilt_b = rebuild_story_state(deepcopy(outcomes))
    last_version, last_outcome = outcomes[-1]

    assert rebuilt_a == rebuilt_b
    assert reduce_story_state_v2(
        previous=rebuilt_a,
        events=events_from_chapter_outcome(last_version, last_outcome),
        chapter_outcome_asset_version_id=last_version,
        chapter_outcome_id=last_outcome["chapter_outcome_id"],
    ) == rebuilt_a

    _, alternate_head = _outcome(
        100,
        {
            "plot_thread": [
                {
                    "thread_id": "plot:t",
                    "from_status": "OPEN",
                    "status": "RESOLVED",
                }
            ],
            "theme_movement": [
                {"movement": "Responsibility now outweighs safety."}
            ],
        },
    )
    with pytest.raises(KernelError) as mismatch:
        reduce_story_state_v2(
            previous=rebuilt_a,
            events=events_from_chapter_outcome(last_version, alternate_head),
            chapter_outcome_asset_version_id=last_version,
            chapter_outcome_id=last_outcome["chapter_outcome_id"],
        )
    assert mismatch.value.code == "NARRATIVE_IDEMPOTENT_REPLAY_MISMATCH"


def test_out_of_order_replay_and_invalid_resource_balance_fail_closed() -> None:
    state = _at(30)
    old_version, old_outcome = _readable_outcomes()[1]
    with pytest.raises(KernelError) as order_error:
        reduce_story_state_v2(
            previous=state,
            events=events_from_chapter_outcome(old_version, old_outcome),
            chapter_outcome_asset_version_id=old_version,
            chapter_outcome_id=old_outcome["chapter_outcome_id"],
        )
    assert order_error.value.code == "NARRATIVE_REPLAY_OUT_OF_ORDER"

    bad = _outcome(
        61,
        {
            "resource_state": [
                {
                    "entity_id": "character:lin",
                    "resource_id": "resource:x",
                    "balance_before": 5,
                    "delta": -1,
                    "balance_after": 9,
                }
            ]
        },
    )
    with pytest.raises(KernelError) as balance_error:
        rebuild_story_state([*_readable_outcomes()[:7], bad])
    assert balance_error.value.code == "NARRATIVE_RESOURCE_BALANCE_INVALID"


def test_compact_context_has_one_current_fact_per_materialized_entity() -> None:
    state = _at(100)
    facts = compact_current_state_facts(state)
    lin = [
        item
        for item in facts
        if item["state_kind"] == "character_state"
        and item["entity_key"] == "character_id=character:lin"
    ]

    assert len(lin) == 1
    assert lin[0]["state"]["location"] == "Beijing"
    assert not any("Hangzhou" in repr(item) for item in lin)
    assert not any(
        item["state_kind"] in {"canon_fact", "timeline_event", "reward_event", "theme_movement"}
        for item in facts
    )


def test_death_is_visible_only_after_acceptance_and_cannot_silently_reopen() -> None:
    alive = _outcome(
        1,
        {
            "character_state": [
                {
                    "character_id": "character:guard",
                    "canonical_name": "The Gatekeeper",
                    "life_status": "ALIVE",
                }
            ]
        },
    )
    dead = _outcome(
        12,
        {
            "character_state": [
                {
                    "character_id": "character:guard",
                    "life_status": "DEAD",
                    "death_evidence": "The physician confirms death in Chapter 12.",
                }
            ]
        },
    )
    reopened = _outcome(
        13,
        {
            "character_state": [
                {
                    "character_id": "character:guard",
                    "life_status": "ALIVE",
                }
            ]
        },
    )

    assert project_entity_state(
        rebuild_story_state([alive]),
        "character_state",
        "character_id=character:guard",
    )["state"]["life_status"] == "ALIVE"
    assert project_entity_state(
        rebuild_story_state([alive, dead]),
        "character_state",
        "character_id=character:guard",
    )["state"]["life_status"] == "DEAD"
    with pytest.raises(KernelError) as error:
        rebuild_story_state([alive, dead, reopened])
    assert (
        error.value.code
        == "NARRATIVE_CHARACTER_TERMINAL_STATE_REOPEN_FORBIDDEN"
    )
