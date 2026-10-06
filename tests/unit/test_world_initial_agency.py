from copy import deepcopy
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import StoryTime
from novel_forge.modules.worldbuilding.dynamics import (
    WorldTransition,
    candidate_transition,
)
from novel_forge.modules.worldbuilding.working_state import validate_preparation_batch


def genesis():
    return {
        "project_id": "project:agency",
        "book_id": "book:agency",
        "book_run_id": "book-run:agency",
        "chapter_number": 0,
        "revision_id": "foundation:sha256:" + "a" * 64,
        "baseline_kind": "APPROVED_FOUNDATION",
        "world_dynamics_contract": "world-dynamics.v2",
        "epistemic_contract": "world-agency.v2",
        "approved_entity_ids": [
            "character:keeper",
            "character:reader",
            "resource:record",
        ],
        "approved_character_ids": ["character:keeper", "character:reader"],
        "foundation_cause_refs": ["foundation:approved"],
        "events": [],
        "current_state": {},
    }


def action(
    name,
    actor,
    mode,
    kind,
    key,
    changes,
    ordinal,
    *,
    causes=("foundation:approved",),
    requirements=(),
    basis=(),
):
    return {
        "transition_id": name,
        "actor_id": actor,
        "camera": "ON_CAMERA",
        "action": name,
        "action_mode": mode,
        "story_time": StoryTime("main", ordinal, ordinal, "ORDERED", name).to_dict(),
        "state_kind": kind,
        "entity_key": key,
        "changes": changes,
        "requirements": list(requirements),
        "cause_refs": list(causes),
        "epistemic_basis": list(basis),
    }


def predicate(kind, key, field, value):
    return {
        "requirement_id": key + ":" + field,
        "state_kind": kind,
        "entity_key": key,
        "field": field,
        "operator": "EQUALS",
        "value": value,
    }


def chain():
    available = action(
        "open",
        "character:keeper",
        "ROUTINE",
        "world_state",
        "resource:record",
        {"access": "AVAILABLE"},
        1,
    )
    observe = action(
        "read",
        "character:reader",
        "PERCEPTION",
        "character_knowledge",
        "reader:access",
        {
            "character_id": "character:reader",
            "fact_id": "record:access",
            "status": "KNOWN",
            "observation_source": {
                "state_kind": "world_state",
                "entity_key": "resource:record",
                "field": "access",
                "value": "AVAILABLE",
            },
        },
        2,
        causes=("local:open",),
        requirements=(
            predicate("world_state", "resource:record", "access", "AVAILABLE"),
        ),
    )
    decide = action(
        "choose",
        "character:reader",
        "INFORMATION_DEPENDENT",
        "world_state",
        "resource:record",
        {"request_copy": True},
        3,
        causes=("local:read",),
        basis=(predicate("character_knowledge", "reader:access", "status", "KNOWN"),),
    )
    return [available, observe, decide]


def test_empty_genesis_supports_first_agency_then_perception_then_own_decision_without_mutation():
    source = genesis()
    frozen = deepcopy(source)
    ordered, preview = validate_preparation_batch(
        reality=source, transitions=chain(), chapter_number=1, path_id="first"
    )
    assert [item["transition_id"] for item in ordered] == ["open", "read", "choose"]
    assert (
        preview["current_state"]["character_knowledge"][0]["state"]["character_id"]
        == "character:reader"
    )
    assert source == frozen
    assert (
        preview["current_state"]["character_knowledge"][0]["source_event_id"]
        == "local:read"
    )


@pytest.mark.parametrize(
    "defect,code",
    [
        ("borrow", "WORLD_EPISTEMIC_ACTOR_MISMATCH"),
        ("future", "WORLD_BATCH_FUTURE_CAUSE"),
        ("cycle", "WORLD_BATCH_CAUSAL_CYCLE"),
        ("observed_value", "WORLD_PERCEPTION_EVIDENCE_MISMATCH"),
        ("stolen_perception", "WORLD_PERCEPTION_ACTOR_INVALID"),
        ("routine_knowledge", "WORLD_ROUTINE_CANNOT_GRANT_KNOWLEDGE"),
        ("missing_dependency", "WORLD_BATCH_CONCURRENT_WRITE"),
    ],
)
def test_invalid_initial_knowledge_chain_is_rejected(defect, code):
    transitions = chain()
    if defect == "borrow":
        transitions[2]["actor_id"] = "character:keeper"
    elif defect == "future":
        transitions[1]["story_time"]["start_ordinal"] = 4
        transitions[1]["story_time"]["end_ordinal"] = 4
    elif defect == "cycle":
        transitions[0]["cause_refs"] = ["local:choose"]
    elif defect == "observed_value":
        transitions[1]["changes"]["observation_source"]["value"] = "SECRET"
    elif defect == "stolen_perception":
        transitions[1]["changes"]["character_id"] = "character:keeper"
    elif defect == "routine_knowledge":
        transitions[1]["action_mode"] = "ROUTINE"
    else:
        transitions[2]["cause_refs"] = ["foundation:approved"]
    with pytest.raises(KernelError) as rejected:
        validate_preparation_batch(
            reality=genesis(),
            transitions=transitions,
            chapter_number=1,
            path_id="first",
        )
    assert rejected.value.code == code


def test_reader_knowledge_cannot_support_first_perception():
    observation = chain()[1]
    observation["requirements"] = [
        predicate("reader_knowledge", "reader:audience", "status", "KNOWN")
    ]
    with pytest.raises(KernelError, match="WORLD_READER_STATE_NOT_CAUSAL_AUTHORITY"):
        WorldTransition.from_mapping(observation)


def test_host_binds_first_observation_owner_from_typed_actor_without_inventing_content():
    transitions = chain()
    transitions[1]["changes"].pop("character_id")
    transitions[1]["changes"].pop("fact_id")
    transitions[1]["changes"]["proposition"] = "The record is available for inspection."
    frozen = deepcopy(transitions)
    _, preview = validate_preparation_batch(
        reality=genesis(), transitions=transitions, chapter_number=1, path_id="first"
    )
    acquired = preview["current_state"]["character_knowledge"][0]["state"]
    assert acquired["character_id"] == transitions[1]["actor_id"]
    assert acquired["proposition"] == "The record is available for inspection."
    assert acquired["proposition_id"].startswith("observation:sha256:")
    assert transitions == frozen


def test_legacy_genesis_contract_is_preserved_and_cannot_take_new_modes():
    source = genesis()
    source.pop("epistemic_contract")
    raw = chain()[0]
    raw.pop("action_mode")
    with pytest.raises(KernelError, match="WORLD_CHARACTER_DECISION_BASIS_REQUIRED"):
        candidate_transition(WorldTransition.from_mapping(raw), source)
    assert json.loads(json.dumps(WorldTransition.from_mapping(raw).to_dict())) == raw
    with pytest.raises(KernelError, match="WORLD_CHARACTER_DECISION_BASIS_REQUIRED"):
        candidate_transition(WorldTransition.from_mapping(chain()[0]), source)


@pytest.mark.parametrize(
    "fault,code",
    [
        (None, None),
        ("unknown", "WORLD_DISCLOSURE_SOURCE_UNKNOWN"),
        ("private", "WORLD_DISCLOSURE_FIELDS_INVALID"),
        ("future", "WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID"),
        ("cycle", "WORLD_BATCH_CAUSAL_CYCLE"),
    ],
)
def test_local_disclosure_requires_selected_causal_path_and_remains_unaccepted(
    fault, code
):
    from novel_forge.modules.narrative_state.information import (
        project_candidate_disclosure,
        project_disclosure,
    )

    source = genesis()
    frozen = deepcopy(source)
    transitions = chain()
    disclosure = {
        "disclosure_id": "reader-copy",
        "event_id": "local:choose",
        "audience": "READER",
        "mode": "PARTIAL",
        "fields": ["request_copy"],
        "presentation_channel": "ACTION",
        "claim_kind": "CURRENT_ASSERTION",
    }
    chapter = 1
    if fault == "unknown":
        disclosure["event_id"] = "local:other-path"
    elif fault == "private":
        disclosure["fields"] = ["world_transition"]
    elif fault == "future":
        chapter = 2
    elif fault == "cycle":
        transitions[0]["cause_refs"] = ["local:choose"]
    if code:
        with pytest.raises(KernelError, match=code):
            project_candidate_disclosure(
                source,
                disclosure,
                transitions=transitions,
                chapter_number=chapter,
                path_id="first",
            )
    else:
        result = project_candidate_disclosure(
            source,
            disclosure,
            transitions=transitions,
            chapter_number=chapter,
            path_id="first",
        )
        assert result["source"]["evidence_role"] == "PLANNED_LOCAL_OCCURRENCE"
        assert result["source"]["state"] == {"request_copy": True}
        with pytest.raises(KernelError, match="WORLD_DISCLOSURE_SOURCE_UNKNOWN"):
            project_disclosure(source, disclosure)
    assert source == frozen


def test_schema_diagnosis_collects_multiple_nested_defects_in_one_result():
    from novel_forge.modules.worldbuilding.production_schema import (
        decode_world_generation,
    )

    raw = chain()[1]
    raw["story_time"]["start_ordinal"] = "later"
    raw["epistemic_basis"] = "I know"
    raw["requirements"][0].pop("entity_key")
    generated = {
        "candidates": [
            {"transition": {"payload_json": json.dumps(raw)}, "preparation_paths": []}
        ]
    }
    with pytest.raises(KernelError) as rejected:
        decode_world_generation(generated)
    diagnostics = json.loads(rejected.value.message)["diagnostics"]
    assert {row["field_path"] for row in diagnostics} >= {
        "$.candidates[0].transition.payload_json.story_time.start_ordinal",
        "$.candidates[0].transition.payload_json.epistemic_basis",
        "$.candidates[0].transition.payload_json.requirements[0].entity_key",
    }


@pytest.mark.parametrize("fault", [None, "identity", "future"])
def test_first_chapter_plan_binds_canon_identity_and_executes_only_due_causal_batch(
    fault,
):
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )
    from novel_forge.modules.worldbuilding.production_schema import (
        agency_transition_paths,
    )
    from novel_forge.modules.hierarchical_planning.causal_domain import (
        DIRECTOR_DIMENSIONS,
    )
    from novel_forge.modules.canon_graph.background import scheduled_world_events

    source = genesis()
    transitions = chain()
    candidate = {
        "transition": transitions[-1],
        "affected_entities": ["character:reader", "resource:record"],
        "world_consequences": ["A grounded copying decision."],
        "arc_refs": [],
        "obligation_refs": [],
        "risks": [],
        "rationale": "Observe before choosing.",
        "soft_assumptions": [],
        "narrative_preferences": [],
        "preparation_paths": [
            {
                "path_id": "first",
                "steps": [
                    {"transition": raw, "chapter_offset": 0} for raw in transitions[:-1]
                ],
                "rationale": "Make the record available before inspecting.",
            }
        ],
    }
    if fault == "identity":
        transitions[0]["changes"]["world_state_id"] = "resource:invented"
    elif fault == "future":
        candidate["preparation_paths"][0]["steps"][1]["chapter_offset"] = 1
    generated = {
        "disposition": "CANDIDATES",
        "reason": "First lawful encounter.",
        "candidates": [candidate],
    }
    evaluation = {
        "evaluations": [
            {
                "transition_id": "choose",
                "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 0.8),
                "rationale": "Located source supports action.",
                "preferred_path_id": "first",
            }
        ],
        "action_classifications": [
            {
                "field_path": path,
                "supported": True,
                "rationale": "The observation precedes its own dependent choice.",
            }
            for path in agency_transition_paths(generated)
        ],
    }
    frozen = deepcopy((source, generated))
    if fault == "identity":
        with pytest.raises(KernelError, match="WORLD_BACKGROUND_IDENTITY_MISMATCH"):
            compile_world_plan(
                reality=source,
                generated=generated,
                evaluation=evaluation,
                policy=WorldProductionPolicy(),
                chapter_number=1,
                intent_version_id="intent:approved",
            )
    else:
        plan = compile_world_plan(
            reality=source,
            generated=generated,
            evaluation=evaluation,
            policy=WorldProductionPolicy(),
            chapter_number=1,
            intent_version_id="intent:approved",
        )
        binding = {
            "action": {
                "contract_version": "world-production-action.v2",
                "world_plan": plan,
            },
            "frozen_source": {"reality": source},
        }
        due = scheduled_world_events(binding)
        assert [item["transition_id"] for item in due] == (
            ["open"] if fault == "future" else ["open", "read", "choose"]
        )
        assert all("=" in item["entity_key"] for item in due)
        assert plan.get("target_in_current_batch", False) == (fault is None)
        assert plan["fact_mutation_allowed"] is False
    assert (source, generated) == frozen
