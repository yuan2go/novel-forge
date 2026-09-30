from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from novel_forge.modules.canon_graph.world_reconciliation import (
    validate_actual_world_events,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import (
    NarrativeStateKind,
    StoryTime,
    events_from_canon_patch,
)
from tests.unit.test_narrative_reality_causality import reality_state, transition


def test_actor_travel_uses_its_own_clock_not_an_unrelated_world_event():
    from novel_forge.modules.worldbuilding.dynamics import candidate_transition

    reality = reality_state()
    reality["world_dynamics_contract"] = "world-dynamics.v2"
    reality["world_clock"]["main"] = 11
    reality["entity_clocks"] = {"character_state|hero|main": 10}
    move = replace(
        transition(),
        state_kind=NarrativeStateKind.CHARACTER_STATE,
        entity_key="hero",
        requirements=(),
        changes={"location_id": "city", "travel_distance": 4},
    )
    assert candidate_transition(move, reality)["eligible"]


def test_unordered_same_batch_knowledge_cannot_authorize_a_decision():
    reality, events = knowledge_then_action()
    event = events[0]
    event["mutation"]["payload"]["causal_batch"]["depends_on"] = ["event:supply"]
    event["causality"]["cause_refs"] = ["event:supply"]
    raw = json.loads(event["mutation"]["payload"]["world_transition"]["payload_json"])
    raw["cause_refs"] = ["event:supply"]
    event["mutation"]["payload"]["world_transition"]["payload_json"] = json.dumps(raw)
    with pytest.raises(KernelError) as error:
        validate_actual_world_events(
            previous_reality=reality,
            chapter_outcome={"state_events": typed_events(events)},
        )
    assert error.value.code == "WORLD_EPISTEMIC_ACTOR_MISMATCH"


def batch_event(local_id, *, kind, key, payload, time, dependencies=(), actor="hero"):
    return {
        "event_id": f"narrative-event:sha256:{local_id}",
        "state_kind": kind,
        "identity": {"entity_key": key},
        "story_time": StoryTime("main", time, time, "EXACT").to_dict(),
        "causality": {"cause_refs": list(dependencies), "participant_ids": [actor]},
        "mutation": {
            "payload": {
                **payload,
                "causal_batch": {
                    "contract_version": "causal-batch-event.v1",
                    "local_id": local_id,
                    "depends_on": list(dependencies),
                },
            }
        },
    }


def knowledge_then_action():
    knowledge = batch_event(
        "receive",
        kind="character_knowledge",
        key="hero:supplies",
        time=11,
        payload={"character_id": "hero", "fact_id": "supply", "status": "KNOWN"},
    )
    action = replace(
        transition(),
        state_kind=NarrativeStateKind.WORLD_STATE,
        entity_key="world_state_id=inquiry",
        changes={"status": "OPEN"},
        requirements=(),
        cause_refs=("local:receive",),
        epistemic_basis=(
            replace(
                transition().epistemic_basis[0],
                entity_key="character_id=hero|fact_id=supply",
            ),
        ),
    )
    event = batch_event(
        "act",
        kind="world_state",
        key="world_state_id=inquiry",
        time=12,
        dependencies=("local:receive",),
        payload={
            "world_state_id": "inquiry",
            "status": "OPEN",
            "world_transition": {"payload_json": json.dumps(asdict(action))},
        },
    )
    reality = reality_state()
    reality["current_state"]["character_knowledge"] = []
    return reality, [event, knowledge]


def test_same_chapter_acquisition_supports_dependent_decision_without_mutating_baseline():
    reality, events = knowledge_then_action()
    frozen = deepcopy(reality)
    validate_actual_world_events(
        previous_reality=reality, chapter_outcome={"state_events": typed_events(events)}
    )
    assert reality == frozen


@pytest.mark.parametrize(
    "damage, code",
    [
        ("missing", "WORLD_BATCH_REFERENCE_UNKNOWN"),
        ("future", "WORLD_BATCH_FUTURE_CAUSE"),
        ("cycle", "WORLD_BATCH_CAUSAL_CYCLE"),
        ("other_actor", "WORLD_EPISTEMIC_ACTOR_MISMATCH"),
        ("unordered_write", "WORLD_BATCH_CONCURRENT_WRITE"),
    ],
)
def test_invalid_causal_batch_has_no_partial_state(damage, code):
    reality, events = knowledge_then_action()
    if damage == "missing":
        events.pop()
    elif damage == "future":
        events[1]["story_time"] = StoryTime("main", 13, 13, "EXACT").to_dict()
    elif damage == "cycle":
        events[1]["mutation"]["payload"]["causal_batch"]["depends_on"] = ["local:act"]
    elif damage == "other_actor":
        events[1]["mutation"]["payload"]["character_id"] = "villain"
    else:
        duplicate = deepcopy(events[1])
        duplicate["event_id"] += "-other"
        duplicate["mutation"]["payload"]["causal_batch"]["local_id"] = "other"
        events.append(duplicate)
    frozen = deepcopy(reality)
    with pytest.raises(KernelError) as error:
        validate_actual_world_events(
            previous_reality=reality,
            chapter_outcome={"state_events": typed_events(events)},
        )
    assert error.value.code == code
    assert reality == frozen


def test_independent_same_time_events_are_legal():
    reality, events = knowledge_then_action()
    first = events[1]
    second = deepcopy(first)
    second["event_id"] += "-other"
    second["identity"]["entity_key"] = "villain:supplies"
    second["mutation"]["payload"]["character_id"] = "villain"
    second["mutation"]["payload"]["causal_batch"]["local_id"] = "other"
    validate_actual_world_events(
        previous_reality=reality,
        chapter_outcome={"state_events": typed_events([second, first])},
    )


def test_legacy_write_cannot_bypass_batch_order_for_same_identity():
    reality, events = knowledge_then_action()
    legacy = deepcopy(events[1])
    del legacy["mutation"]["payload"]["causal_batch"]
    with pytest.raises(KernelError, match="WORLD_BATCH_MIXED_WRITE"):
        validate_actual_world_events(
            previous_reality=reality,
            chapter_outcome={"state_events": typed_events([*events, legacy])},
        )


def typed_events(events):
    result = []
    for event in events:
        cause = event["causality"]["cause_refs"] or ["event:supply"]
        raw = {
            **event["mutation"]["payload"],
            "story_time": event["story_time"],
            "causality": {
                **event["causality"],
                "cause_refs": cause,
                "precondition_refs": [],
                "effect_kinds": ["STATE"],
            },
            "entity_version": 1,
        }
        typed = events_from_canon_patch(
            project_id="project",
            book_id="book",
            source_chapter=2,
            chapter_outcome_id="outcome:2",
            canon_patch_asset_version_id="patch:2",
            accepted_draft_asset_version_id="draft:2",
            source_operation_id="operation:2",
            trace_id="trace:2",
            canon_patch={"state_changes": {event["state_kind"]: [raw]}},
        )
        result.extend(item.to_dict() for item in typed)
    return result


def test_observer_batch_contract_has_a_distinct_identity_from_unbatched_extraction():
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        chapter_provider_output_schema,
        chapter_provider_output_schema_ref,
    )

    old = chapter_provider_output_schema("canon_extraction")
    current = chapter_provider_output_schema("canon_extraction", causal_batch=True)
    assert (
        "causal_batch"
        not in old["properties"]["character_knowledge_changes"]["items"]["properties"]
    )
    assert current["properties"]["character_knowledge_changes"]["items"]["properties"][
        "causal_batch"
    ]
    assert chapter_provider_output_schema_ref(
        "canon_extraction", causal_batch=True
    ).endswith(":v21")
    assert chapter_provider_output_schema_ref("canon_extraction").endswith(":v20")
    assert chapter_provider_output_schema_ref(
        "canon_extraction", causal_batch=True, legacy_contract=True
    ).endswith(":v19")


def test_ordered_changes_to_one_entity_get_consecutive_versions():
    from novel_forge.modules.canon_graph.domain import _bind_narrative_entity_versions

    first = {
        "world_state_id": "inquiry",
        "status": "OPEN",
        "story_time": StoryTime("main", 1, 1, "EXACT").to_dict(),
        "causal_batch": {
            "contract_version": "causal-batch-event.v1",
            "local_id": "first",
            "depends_on": [],
        },
    }
    second = {
        **deepcopy(first),
        "status": "RESOLVED",
        "story_time": StoryTime("main", 2, 2, "EXACT").to_dict(),
        "causal_batch": {
            "contract_version": "causal-batch-event.v1",
            "local_id": "second",
            "depends_on": ["local:first"],
        },
    }
    changes = {"world_state": [second, first]}
    _bind_narrative_entity_versions(changes, {})
    assert (first["entity_version"], second["entity_version"]) == (1, 2)


def test_why_trace_resolves_batch_names_within_exact_outcome_without_mutation():
    from novel_forge.modules.narrative_state.read_models import project_why_trace

    reality, raw = knowledge_then_action()
    events = typed_events(raw)
    before = deepcopy(events)
    action = next(event for event in events if event["state_kind"] == "world_state")
    acquisition = next(
        event for event in events if event["state_kind"] == "character_knowledge"
    )
    trace = project_why_trace(
        {**reality, "events": events}, event_id=action["event_id"]
    )
    assert any(
        edge["cause"] == acquisition["event_id"]
        and edge["effect"] == action["event_id"]
        for edge in trace["edges"]
    )
    assert events == before


def test_approved_world_mechanism_can_allow_instant_travel_but_model_flag_cannot():
    from novel_forge.modules.worldbuilding.dynamics import candidate_transition

    reality = reality_state()
    reality["world_dynamics_contract"] = "world-dynamics.v2"
    reality["entity_clocks"] = {"character_state|hero|main": 10}
    rule = {
        "rule_id": "gate-travel",
        "category": "core_laws",
        "statement": "The supplied gate permits instantaneous travel.",
        "enforcement": "MECHANISM",
        "applicability": ["character_state"],
        "consequences": ["The gate must already be funded."],
        "predicate": {
            "requirement_id": "funded",
            "state_kind": "resource_state",
            "entity_key": "supply",
            "field": "balance",
            "operator": "AT_LEAST",
            "value": 1,
        },
        "mechanism": {
            "contract_version": "world-mechanism.v1",
            "effect": "INSTANT_TRAVEL",
            "entity_keys": ["hero"],
        },
    }
    reality["world_rule_constraints"] = [
        {
            "asset_version_id": "world-rules",
            "content_hash": "sha256:" + "a" * 64,
            "rule": rule,
        }
    ]
    move = replace(
        transition(),
        state_kind=NarrativeStateKind.CHARACTER_STATE,
        entity_key="hero",
        requirements=(),
        changes={
            "location_id": "city",
            "travel_distance": 999,
            "world_mechanism": {
                "rule_id": "gate-travel",
                "asset_version_id": "world-rules",
                "content_hash": "sha256:" + "a" * 64,
            },
        },
    )
    assert candidate_transition(move, reality)["eligible"]
    forged = replace(
        move,
        changes={
            **move.changes,
            "world_mechanism": {
                **move.changes["world_mechanism"],
                "asset_version_id": "invented-rule",
            },
        },
    )
    with pytest.raises(KernelError, match="WORLD_MECHANISM_UNAPPROVED"):
        candidate_transition(forged, reality)


def test_observed_root_cannot_invent_its_accepted_draft_evidence():
    reality, raw = knowledge_then_action()
    acquisition = raw[1]
    acquisition["causality"]["cause_refs"] = ["observed:invented-draft:0:4"]
    with pytest.raises(KernelError, match="WORLD_OBSERVED_ROOT_UNVERIFIED"):
        validate_actual_world_events(
            previous_reality=reality,
            chapter_outcome={"state_events": typed_events(raw)},
        )


def test_approved_revival_projects_a_new_event_without_superseding_death():
    from novel_forge.modules.narrative_state.contracts import NarrativeStateEvent
    from novel_forge.modules.narrative_state.reducers import preview_state_events

    reality = reality_state()
    reality["world_dynamics_contract"] = "world-dynamics.v2"
    old = reality["current_state"]["character_state"][0]
    old["entity_key"] = "character_id=hero"
    old["state"]["life_status"] = "DEAD"
    rule = {
        "rule_id": "restoration",
        "category": "life_death_disease",
        "statement": "An already funded shrine can restore this character.",
        "enforcement": "MECHANISM",
        "applicability": ["character_state"],
        "consequences": ["The shrine requires supplies."],
        "predicate": {
            "requirement_id": "funded",
            "state_kind": "resource_state",
            "entity_key": "supply",
            "field": "balance",
            "operator": "AT_LEAST",
            "value": 1,
        },
        "mechanism": {
            "contract_version": "world-mechanism.v1",
            "effect": "REVIVAL",
            "entity_keys": ["character_id=hero"],
        },
    }
    reference = {
        "rule_id": "restoration",
        "asset_version_id": "approved-world",
        "content_hash": "sha256:" + "a" * 64,
    }
    reality["world_rule_constraints"] = [
        {
            "asset_version_id": reference["asset_version_id"],
            "content_hash": reference["content_hash"],
            "rule": rule,
        }
    ]
    revival = replace(
        transition(),
        actor_id="faction:healers",
        state_kind=NarrativeStateKind.CHARACTER_STATE,
        entity_key="character_id=hero",
        requirements=(),
        epistemic_basis=(),
        changes={"life_status": "ALIVE", "world_mechanism": reference},
    )
    raw = batch_event(
        "restore",
        kind="character_state",
        key="character_id=hero",
        time=11,
        actor="faction:healers",
        dependencies=revival.cause_refs,
        payload={
            "character_id": "hero",
            **revival.changes,
            "world_transition": {"payload_json": json.dumps(asdict(revival))},
        },
    )
    raw["story_time"] = revival.story_time.to_dict()
    events = typed_events([raw])
    validate_actual_world_events(
        previous_reality=reality, chapter_outcome={"state_events": events}
    )
    projected = preview_state_events(
        previous=reality,
        events=[NarrativeStateEvent.from_dict(event) for event in events],
    )
    assert projected["character_state"][0]["state"]["life_status"] == "ALIVE"
    assert not projected["character_state"][0]["supersedes_event_id"]
    assert old["state"]["life_status"] == "DEAD"
    forged = deepcopy(reality)
    forged["world_rule_constraints"] = []
    with pytest.raises(KernelError, match="WORLD_MECHANISM_UNAPPROVED"):
        validate_actual_world_events(
            previous_reality=forged, chapter_outcome={"state_events": events}
        )


def test_combined_batch_checks_rules_against_the_final_projection():
    reality = reality_state()
    reality["current_state"]["resource_state"][0]["entity_key"] = (
        "entity_id=caravan|resource_id=supply"
    )
    reality["current_state"]["resource_state"][0]["state"]["balance"] = 3
    reality["world_rule_constraints"] = [
        {
            "asset_version_id": "approved:rules",
            "content_hash": "sha256:" + "c" * 64,
            "rule": {
                "rule_id": "operational-reserve",
                "category": "economy",
                "statement": "Operations require a maintained reserve.",
                "enforcement": "HARD",
                "applicability": ["world_state"],
                "consequences": ["Operations must stop without reserve."],
                "predicate": {
                    "requirement_id": "reserve",
                    "state_kind": "resource_state",
                    "entity_key": "entity_id=caravan|resource_id=supply",
                    "field": "balance",
                    "operator": "AT_LEAST",
                    "value": 3,
                },
            },
        }
    ]
    operations = replace(
        transition(),
        actor_id="faction:caravan",
        epistemic_basis=(),
        state_kind=NarrativeStateKind.WORLD_STATE,
        entity_key="world_state_id=operations",
        requirements=(),
        changes={"status": "ACTIVE"},
    )
    raw = batch_event(
        "operate",
        kind="world_state",
        key="world_state_id=operations",
        time=12,
        dependencies=("event:supply",),
        payload={
            "world_state_id": "operations",
            "status": "ACTIVE",
            "world_transition": {"payload_json": json.dumps(asdict(operations))},
        },
    )
    withdrawal = replace(
        operations,
        transition_id="withdraw",
        state_kind=NarrativeStateKind.RESOURCE_STATE,
        entity_key="entity_id=caravan|resource_id=supply",
        changes={"balance": 1},
    )
    other = batch_event(
        "withdraw",
        kind="resource_state",
        key="entity_id=caravan|resource_id=supply",
        time=12,
        dependencies=("event:supply",),
        payload={
            "entity_id": "caravan",
            "resource_id": "supply",
            "balance": 1,
            "world_transition": {"payload_json": json.dumps(asdict(withdrawal))},
        },
    )
    before = deepcopy(reality)
    for ordered in ([raw, other], [other, raw]):
        with pytest.raises(KernelError, match="WORLD_COMPILED_RULE_VIOLATION"):
            validate_actual_world_events(
                previous_reality=reality,
                chapter_outcome={"state_events": typed_events(ordered)},
            )
    assert reality == before
