from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    compact_canon_facts,
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


def test_legacy_obligation_kinds_keep_source_identity_when_linked() -> None:
    _, outcome = _outcome(
        2,
        {
            "plot_thread": [
                {
                    "thread_id": "thread:revised-record",
                    "promise_id": "promise:resolve-record",
                    "status": "ACTIVE",
                }
            ],
            "reader_promise": [
                {
                    "promise_id": "promise:resolve-record",
                    "thread_id": "thread:revised-record",
                    "status": "OPEN",
                }
            ],
            "foreshadow_state": [
                {
                    "entity_id": "foreshadow:recorded-subject",
                    "promise_id": "promise:resolve-record",
                    "thread_id": "thread:revised-record",
                    "status": "OPEN",
                }
            ],
            "mystery_state": [
                {
                    "mystery_id": "mystery:recorded-subject",
                    "promise_id": "promise:resolve-record",
                    "thread_id": "thread:revised-record",
                    "status": "OPEN",
                }
            ],
        },
    )

    identities = {
        event["identity"]["entity_key"] for event in outcome["state_events"]
    }
    assert identities == {
        "obligation_id=thread:revised-record",
        "obligation_id=promise:resolve-record",
        "obligation_id=foreshadow:recorded-subject",
        "obligation_id=mystery:recorded-subject",
    }


def test_initial_legacy_active_plot_thread_opens_unified_obligation() -> None:
    _, outcome = _outcome(
        1,
        {
            "plot_thread": [
                {
                    "thread_id": "thread:impossible-death-record",
                    "promise_id": "promise:post-death-marker-explanation",
                    "status": "ACTIVE",
                    "state": "OPEN",
                    "transition_kind": "THREAD_OPENED",
                    "impact_type": "NEW",
                }
            ]
        },
    )

    state = rebuild_story_state([("outcome-v1", outcome)])
    obligation = project_entity_state(
        state,
        "narrative_obligation",
        "obligation_id=thread:impossible-death-record",
    )

    assert obligation["state"]["status"] == "OPEN"
    assert obligation["state"]["lifecycle_migration"]["source_status"] == "ACTIVE"


@pytest.mark.parametrize(
    ("state_kind", "identity", "entity_key"),
    (
        (
            "reader_promise",
            {"promise_id": "promise:active"},
            "obligation_id=promise:active",
        ),
        ("plot_thread", {"thread_id": "thread:active"}, "obligation_id=thread:active"),
        (
            "mystery_state",
            {"mystery_id": "mystery:active"},
            "obligation_id=mystery:active",
        ),
        (
            "foreshadow_state",
            {"entity_id": "foreshadow:active"},
            "obligation_id=foreshadow:active",
        ),
    ),
)
def test_new_legacy_active_obligation_kinds_open(
    state_kind: str,
    identity: dict[str, str],
    entity_key: str,
) -> None:
    version, outcome = _outcome(
        1,
        {state_kind: [{**identity, "status": "ACTIVE", "impact_type": "NEW"}]},
    )

    state = rebuild_story_state([(version, outcome)])

    assert (
        project_entity_state(state, "narrative_obligation", entity_key)["state"][
            "status"
        ]
        == "OPEN"
    )


def test_existing_developing_legacy_active_does_not_regress() -> None:
    state = rebuild_story_state(
        [
            _outcome(1, {"plot_thread": [{"thread_id": "thread:p", "status": "OPEN"}]}),
            _outcome(
                2,
                {
                    "plot_thread": [
                        {
                            "thread_id": "thread:p",
                            "from_status": "OPEN",
                            "status": "DEVELOPED",
                        }
                    ]
                },
            ),
            _outcome(
                3, {"plot_thread": [{"thread_id": "thread:p", "status": "ACTIVE"}]}
            ),
        ]
    )

    assert (
        project_entity_state(state, "narrative_obligation", "obligation_id=thread:p")[
            "state"
        ]["status"]
        == "DEVELOPING"
    )


def test_legacy_active_from_status_is_liveness_not_open_precondition() -> None:
    state = rebuild_story_state(
        [
            _outcome(1, {"plot_thread": [{"thread_id": "thread:p", "status": "OPEN"}]}),
            _outcome(
                2,
                {
                    "plot_thread": [
                        {
                            "thread_id": "thread:p",
                            "from_status": "OPEN",
                            "status": "DEVELOPED",
                        }
                    ]
                },
            ),
            _outcome(
                3,
                {
                    "plot_thread": [
                        {
                            "thread_id": "thread:p",
                            "from_status": "ACTIVE",
                            "status": "ACTIVE",
                        }
                    ]
                },
            ),
        ]
    )

    assert (
        project_entity_state(state, "narrative_obligation", "obligation_id=thread:p")[
            "state"
        ]["status"]
        == "DEVELOPING"
    )


def test_explicit_legacy_progress_signal_advances_open_to_developing() -> None:
    state = rebuild_story_state(
        [
            _outcome(1, {"plot_thread": [{"thread_id": "thread:p", "status": "OPEN"}]}),
            _outcome(
                2,
                {
                    "plot_thread": [
                        {
                            "thread_id": "thread:p",
                            "status": "ACTIVE",
                            "state": "DEVELOPING",
                            "transition_kind": "THREAD_DEVELOPED",
                            "impact_type": "UPDATE",
                        }
                    ]
                },
            ),
        ]
    )

    assert (
        project_entity_state(state, "narrative_obligation", "obligation_id=thread:p")[
            "state"
        ]["status"]
        == "DEVELOPING"
    )


def test_terminal_legacy_active_obligation_does_not_reopen() -> None:
    state = rebuild_story_state(
        [
            _outcome(1, {"plot_thread": [{"thread_id": "thread:p", "status": "OPEN"}]}),
            _outcome(
                2,
                {
                    "plot_thread": [
                        {
                            "thread_id": "thread:p",
                            "from_status": "OPEN",
                            "status": "RESOLVED",
                            "payoff_evidence": "The thread closes with accepted evidence.",
                        }
                    ]
                },
            ),
            _outcome(
                3, {"plot_thread": [{"thread_id": "thread:p", "status": "ACTIVE"}]}
            ),
        ]
    )

    assert (
        project_entity_state(state, "narrative_obligation", "obligation_id=thread:p")[
            "state"
        ]["status"]
        == "FULFILLED"
    )


def test_obligation_supersession_must_target_current_same_identity_event() -> None:
    first_version, first_outcome = _outcome(
        1, {"plot_thread": [{"thread_id": "thread:p", "status": "OPEN"}]}
    )
    first_event_id = first_outcome["state_events"][0]["event_id"]
    second_version, second_outcome = _outcome(
        2,
        {
            "plot_thread": [
                {
                    "thread_id": "thread:p",
                    "status": "DEVELOPED",
                    "supersedes_event_id": first_event_id,
                }
            ]
        },
    )

    state = rebuild_story_state(
        [(first_version, first_outcome), (second_version, second_outcome)]
    )
    assert (
        project_entity_state(state, "narrative_obligation", "obligation_id=thread:p")[
            "state"
        ]["status"]
        == "DEVELOPING"
    )

    _wrong_version, wrong_outcome = _outcome(
        2,
        {
            "plot_thread": [
                {
                    "thread_id": "thread:p",
                    "status": "DEVELOPED",
                    "supersedes_event_id": "event:another-obligation",
                }
            ]
        },
    )
    with pytest.raises(KernelError) as mismatch:
        rebuild_story_state(
            [(first_version, first_outcome), (second_version, wrong_outcome)]
        )
    assert mismatch.value.code == "NARRATIVE_SUPERSESSION_TARGET_INVALID"


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
        state, "narrative_obligation", "obligation_id=promise:p"
    )["state"]["status"] == "FULFILLED"
    assert project_entity_state(
        state, "narrative_obligation", "obligation_id=plot:t"
    )["state"]["status"] == "FULFILLED"


def test_character_trajectory_and_reader_disclosure_share_one_state_plane() -> None:
    version, outcome = _outcome(
        1,
        {
            "character_knowledge": [
                {
                    "character_id": "character:lin",
                    "fact_id": "fact:ledger",
                    "status": "KNOWN",
                }
            ],
            "character_belief": [
                {
                    "character_id": "character:lin",
                    "proposition_id": "proposition:silence-is-safe",
                    "stance": "DOUBTS",
                    "belief_confidence": 0.7,
                }
            ],
            "character_arc": [
                {
                    "character_id": "character:lin",
                    "arc_id": "arc:accountability",
                    "status": "OPEN",
                    "stage": "DENIAL",
                    "causal_trigger": "the ledger names a witness",
                }
            ],
            "reader_knowledge": [
                {
                    "fact_id": "fact:traitor",
                    "status": "HINTED",
                }
            ],
            "disclosure_event": [
                {
                    "disclosure_id": "disclosure:traitor-shadow",
                    "fact_id": "fact:traitor",
                    "audience": "READER",
                    "disclosure_mode": "HINT",
                    "presentation_channel": "OBJECT_DETAIL",
                }
            ],
        },
    )

    state = rebuild_story_state([(version, outcome)])

    assert project_entity_state(
        state,
        "character_knowledge",
        "character_id=character:lin|fact_id=fact:ledger",
    )["state"]["status"] == "KNOWN"
    assert project_entity_state(
        state,
        "character_belief",
        "character_id=character:lin|proposition_id=proposition:silence-is-safe",
    )["state"]["stance"] == "DOUBTS"
    assert project_entity_state(
        state,
        "character_arc",
        "character_id=character:lin|arc_id=arc:accountability",
    )["state"]["stage"] == "DENIAL"
    assert project_entity_state(
        state,
        "reader_knowledge",
        "fact_id=fact:traitor",
    )["state"]["status"] == "HINTED"
    assert project_entity_state(
        state,
        "disclosure_event",
        "disclosure_id=disclosure:traitor-shadow",
    )["state"]["presentation_channel"] == "OBJECT_DETAIL"


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
        _at(39), "narrative_obligation", "obligation_id=promise:p"
    )["status"] == "NOT_FOUND"
    assert project_entity_state(
        _at(79), "narrative_obligation", "obligation_id=promise:p"
    )["state"]["status"] == "OPEN"
    assert project_entity_state(
        _at(80), "narrative_obligation", "obligation_id=promise:p"
    )["state"]["status"] == "FULFILLED"
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


def test_compact_context_keeps_narrative_truth_and_digested_lineage() -> None:
    outcome_version, outcome = _outcome(
        1,
        {
            "character_state": [
                {
                    "character_id": "character:lin",
                    "canonical_name": "Lin Qiao",
                    "location": "archive",
                    "approval_resolution": {"decision": "APPROVE"},
                    "change_reasons": ["provider extraction metadata"],
                    "model_id": "model-a",
                    "provider_id": "provider-a",
                }
            ]
        },
    )
    snapshot = reduce_story_state_v2(
        previous=None,
        events=events_from_chapter_outcome(outcome_version, outcome),
        chapter_outcome_asset_version_id=outcome_version,
        chapter_outcome_id=outcome["chapter_outcome_id"],
    )

    story_fact = compact_current_state_facts(snapshot)[0]
    original = snapshot["current_state"]["character_state"][0]
    assert story_fact["state"]["location"] == "archive"
    assert story_fact["source_event_id"] == original["source_event_id"]
    assert story_fact["evidence_digest"].startswith("sha256:")
    assert "approval_resolution" not in story_fact["state"]
    assert "change_reasons" not in story_fact["state"]
    assert "model_id" not in story_fact["state"]
    assert original["state"]["model_id"] == "model-a"

    canon = {
        "contract_version": "canon-snapshot-v2",
        "current_facts": [
            {
                **original,
                "state": {
                    **original["state"],
                    "statement": "The revision trace remains visible.",
                },
            }
        ],
    }
    canon_fact = compact_canon_facts(canon)[0]
    assert canon_fact["state"]["statement"] == (
        "The revision trace remains visible."
    )
    assert canon_fact["source_event_id"] == original["source_event_id"]
    assert canon_fact["evidence_digest"].startswith("sha256:")
    assert "provider_id" not in canon_fact["state"]


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
