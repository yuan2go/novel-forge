from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    compact_current_state_facts,
    events_from_canon_patch,
    expire_effective_ranges,
    measure_narrative_runtime,
    reduce_story_state_v2,
)


def _events(chapter: int, changes: dict[str, list[dict]]) -> tuple:
    return events_from_canon_patch(
        project_id="project-a",
        book_id="book-a",
        source_chapter=chapter,
        chapter_outcome_id=f"outcome-{chapter}",
        canon_patch_asset_version_id=f"canon-{chapter}",
        accepted_draft_asset_version_id=f"draft-{chapter}",
        source_operation_id=f"operation-{chapter}",
        trace_id="trace-a",
        canon_patch={"state_changes": changes},
    )


def test_temporal_state_contract_covers_knowledge_world_and_obligations() -> None:
    events = _events(
        12,
        {
            "character_knowledge": [
                {
                    "character_id": "hero",
                    "fact_id": "fact:heir",
                    "status": "KNOWN",
                    "entity_version": 1,
                    "effective_from_chapter": 12,
                    "effective_to_chapter": 20,
                    "narrative_position": {
                        "chapter": 12,
                        "volume_id": "volume-1",
                        "arc_id": "arc-1",
                        "sequence_id": "sequence-3",
                        "sequence_ordinal": 2,
                    },
                    "canon_status": "APPROVED_CANON_PATCH",
                }
            ],
            "character_belief": [
                {
                    "character_id": "hero",
                    "proposition_id": "proposition:mentor-traitor",
                    "stance": "DOUBTS",
                    "belief_confidence": 0.65,
                    "entity_version": 1,
                }
            ],
            "world_state": [
                {
                    "world_state_id": "weather:capital",
                    "status": "STORM",
                    "entity_version": 1,
                }
            ],
            "faction_state": [
                {"faction_id": "council", "status": "SPLIT", "entity_version": 1}
            ],
            "location_state": [
                {"location_id": "north-gate", "status": "SEALED", "entity_version": 1}
            ],
            "consequence_state": [
                {
                    "consequence_id": "consequence:riot",
                    "source_event_id": "event:riot",
                    "status": "ACTIVE",
                    "entity_version": 1,
                }
            ],
            "conflict_state": [
                {"conflict_id": "conflict:crown", "status": "OPEN", "entity_version": 1}
            ],
            "character_arc": [
                {
                    "character_id": "hero",
                    "arc_id": "arc:trust",
                    "status": "OPEN",
                    "entity_version": 1,
                }
            ],
            "narrative_obligation": [
                {
                    "obligation_id": "obligation:sealed-door",
                    "obligation_type": "MYSTERY",
                    "status": "OPEN",
                    "priority": "HIGH",
                    "target_window": {
                        "status": "SCHEDULED",
                        "from_chapter": 18,
                        "to_chapter": 24,
                    },
                    "linked_character_ids": ["hero"],
                    "linked_arc_ids": ["arc-1"],
                    "linked_event_ids": ["event:door-sealed"],
                    "entity_version": 1,
                }
            ],
        },
    )

    assert {event.state_kind.value for event in events} == {
        "character_knowledge",
        "character_belief",
        "world_state",
        "faction_state",
        "location_state",
        "consequence_state",
        "conflict_state",
        "character_arc",
        "narrative_obligation",
    }
    snapshot = reduce_story_state_v2(
        previous=None,
        events=events,
        chapter_outcome_asset_version_id="outcome-version-12",
        chapter_outcome_id="outcome-12",
    )
    facts = {
        (item["state_kind"], item["entity_key"]): item
        for item in compact_current_state_facts(snapshot)
    }
    knowledge = facts[("character_knowledge", "character_id=hero|fact_id=fact:heir")]
    assert knowledge["effective_to_chapter"] == 20
    assert knowledge["narrative_position"]["arc_id"] == "arc-1"
    assert knowledge["canon_status"] == "APPROVED_CANON_PATCH"
    obligation = facts[("narrative_obligation", "obligation_id=obligation:sealed-door")]
    assert obligation["state"]["target_window"]["to_chapter"] == 24


def test_obligation_terminal_state_requires_payoff_and_cannot_reopen() -> None:
    with pytest.raises(KernelError) as missing_payoff:
        _events(
            10,
            {
                "narrative_obligation": [
                    {
                        "obligation_id": "obligation:x",
                        "obligation_type": "PROMISE",
                        "status": "FULFILLED",
                        "priority": "HIGH",
                        "target_window": {
                            "status": "SCHEDULED",
                            "from_chapter": 8,
                            "to_chapter": 10,
                        },
                    }
                ]
            },
        )
    assert missing_payoff.value.code == (
        "NARRATIVE_OBLIGATION_PAYOFF_EVIDENCE_REQUIRED"
    )

    opened = _events(
        10,
        {
            "narrative_obligation": [
                {
                    "obligation_id": "obligation:x",
                    "obligation_type": "PROMISE",
                    "status": "OPEN",
                    "priority": "HIGH",
                    "target_window": {
                        "status": "SCHEDULED",
                        "from_chapter": 8,
                        "to_chapter": 10,
                    },
                    "entity_version": 1,
                }
            ]
        },
    )
    state = reduce_story_state_v2(
        previous=None,
        events=opened,
        chapter_outcome_asset_version_id="outcome-version-10",
        chapter_outcome_id="outcome-10",
    )
    fulfilled = _events(
        11,
        {
            "narrative_obligation": [
                {
                    "obligation_id": "obligation:x",
                    "obligation_type": "PROMISE",
                    "from_status": "OPEN",
                    "status": "FULFILLED",
                    "priority": "HIGH",
                    "target_window": {
                        "status": "SCHEDULED",
                        "from_chapter": 8,
                        "to_chapter": 10,
                    },
                    "payoff_evidence": {
                        "asset_version_id": "draft-11",
                        "event_id": "payoff-event-11",
                    },
                    "entity_version": 2,
                }
            ]
        },
    )
    state = reduce_story_state_v2(
        previous=state,
        events=fulfilled,
        chapter_outcome_asset_version_id="outcome-version-11",
        chapter_outcome_id="outcome-11",
    )
    reopened = _events(
        12,
        {
            "narrative_obligation": [
                {
                    "obligation_id": "obligation:x",
                    "obligation_type": "PROMISE",
                    "from_status": "FULFILLED",
                    "status": "OPEN",
                    "priority": "HIGH",
                    "target_window": {
                        "status": "SCHEDULED",
                        "from_chapter": 12,
                        "to_chapter": 15,
                    },
                    "entity_version": 3,
                }
            ]
        },
    )
    with pytest.raises(KernelError) as reopened_error:
        reduce_story_state_v2(
            previous=state,
            events=reopened,
            chapter_outcome_asset_version_id="outcome-version-12",
            chapter_outcome_id="outcome-12",
        )
    assert reopened_error.value.code == "NARRATIVE_TERMINAL_STATE_REOPEN_FORBIDDEN"


def test_effective_range_is_absent_from_later_projection_without_deleting_history() -> (
    None
):
    events = _events(
        5,
        {
            "location_state": [
                {
                    "location_id": "bridge",
                    "status": "FLOODED",
                    "effective_to_chapter": 7,
                    "entity_version": 1,
                }
            ]
        },
    )
    snapshot = reduce_story_state_v2(
        previous=None,
        events=events,
        chapter_outcome_asset_version_id="outcome-version-5",
        chapter_outcome_id="outcome-5",
    )

    assert expire_effective_ranges(snapshot, at_chapter=7)["current_state"][
        "location_state"
    ]
    assert not expire_effective_ranges(snapshot, at_chapter=8)["current_state"][
        "location_state"
    ]
    assert len(snapshot["reducer_applications"]) == 1


def test_proof_hooks_measure_without_promoting_longform_capability() -> None:
    measurement = measure_narrative_runtime(
        story_state={
            "accepted_through_chapter": 30,
            "state_hash": "sha256:state",
            "current_state": {
                "narrative_obligation": [
                    {
                        "effective_from_chapter": 10,
                        "effective_to_chapter": 0,
                        "state": {
                            "status": "OPEN",
                            "target_window": {
                                "status": "SCHEDULED",
                                "from_chapter": 15,
                                "to_chapter": 20,
                            },
                        },
                    }
                ]
            },
        },
        context_bundle={
            "actual_context_digest": "sha256:context",
            "context_manifest": {
                "narrative_position": {"chapter": 30},
                "selected_inputs": [
                    {
                        "asset_version_id": "knowledge-v1",
                        "relevance_score": 0.8,
                        "inclusion_reason": "CAPABILITY_KNOWLEDGE_SELECTION",
                    }
                ],
                "replay": {"input_digest": "sha256:replay"},
            },
            "context_segments": [
                {
                    "structured_facts": [
                        {
                            "state_kind": "character_knowledge",
                            "effective_from_chapter": 31,
                            "source_chapter": 1,
                        }
                    ]
                }
            ],
        },
        planning_candidate={
            "constraint_envelope": {"envelope_digest": "sha256:envelope"},
            "constraint_violations": ["objective drift"],
        },
        quality_decision={
            "required_actions": [
                {
                    "status": "OPEN",
                    "issue": {"code": "CANON_CONTRADICTION"},
                }
            ]
        },
        mkaos_usage_records=[{"result_asset_version_id": "draft-v30"}],
        provider_usage_records=[
            {"trace_id": "trace-30", "token_count": 1200, "cost": 0.08}
        ],
    )

    metrics = measurement["metrics"]
    assert metrics["future_knowledge_leakage_count"] == 1
    assert metrics["obligation_overdue_count"] == 1
    assert metrics["long_distance_context_selected_count"] == 1
    assert metrics["context_retrieval_recall"] is None
    assert measurement["observations"]["expected_context"]["status"] == "NOT_OBSERVED"
    assert metrics["planning_drift_count"] == 1
    assert metrics["mkaos_consumption_count"] == 1
    assert measurement["proof_status"] == "MEASURED_NOT_QUALIFIED"
    assert measurement["qualification"] == {
        "longform_proven": False,
        "multibook_proven": False,
        "production_proven": False,
    }


def test_measurement_derives_current_state_from_frozen_context() -> None:
    measurement = measure_narrative_runtime(
        story_state={"accepted_through_chapter": 12},
        context_bundle={
            "context_segments": [
                {
                    "structured_facts": [
                        {
                            "state_kind": "narrative_obligation",
                            "entity_key": "obligation_id=promise:door",
                            "effective_from_chapter": 2,
                            "state": {
                                "status": "OPEN",
                                "target_window": {
                                    "status": "SCHEDULED",
                                    "to_chapter": 10,
                                },
                            },
                        }
                    ]
                }
            ]
        },
    )

    assert measurement["metrics"]["obligation_unresolved_count"] == 1
    assert measurement["metrics"]["obligation_overdue_count"] == 1


def test_measurement_never_turns_missing_evidence_into_false_zero() -> None:
    measurement = measure_narrative_runtime(
        story_state={"accepted_through_chapter": 2},
        context_bundle={},
    )

    metrics = measurement["metrics"]
    assert metrics["provider_call_count"] is None
    assert metrics["provider_token_count"] is None
    assert metrics["provider_cost"] is None
    assert metrics["provider_trace_missing_count"] is None
    assert metrics["mkaos_consumption_count"] is None
    assert metrics["planning_drift_count"] is None
    assert measurement["observations"]["provider_usage"]["status"] == "NOT_OBSERVED"
    assert measurement["observations"]["mkaos_consumption"]["status"] == "NOT_OBSERVED"
    assert measurement["observations"]["planning"]["status"] == "NOT_OBSERVED"


def test_context_recall_requires_an_expected_relevant_set() -> None:
    measurement = measure_narrative_runtime(
        story_state={"accepted_through_chapter": 20},
        context_bundle={
            "context_manifest": {
                "narrative_position": {"chapter": 20},
                "selected_inputs": [
                    {"asset_version_id": "expected-v1", "relevance_score": 0.8},
                    {"asset_version_id": "irrelevant-v1", "relevance_score": 0.1},
                ],
            }
        },
        expected_context_asset_version_ids=("expected-v1", "missing-v1"),
    )

    assert measurement["metrics"]["context_retrieval_recall"] == 0.5
    assert measurement["metrics"]["context_retrieval_precision"] == 0.5
    assert measurement["observations"]["expected_context"]["status"] == "MEASURED"
