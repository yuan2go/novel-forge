import json
from typing import Any, Mapping

from novel_forge.modules.narrative_state.contracts import (
    NarrativeCausality,
    NarrativeCoordinate,
    NarrativeIdentity,
    NarrativeScope,
    NarrativeStateEvent,
    ReducerSemantics,
    narrative_event_id,
)
from novel_forge.modules.narrative_state.reducers import preview_state_events

from .dynamics import WorldTransition


def project_working_observation_context(*, reality: Mapping[str, Any], working: Mapping[str, Any],
                                       characters: list[dict[str, Any]]) -> dict[str, Any]:
    from copy import deepcopy
    from novel_forge.modules.book_authority.working_prose import validate_working_projection
    from novel_forge.modules.narrative_state.reality import narrative_hash

    validate_working_projection(working, project_id=reality["project_id"], book_id=reality["book_id"],
        accepted_through_chapter=reality["chapter_number"])
    names: dict[str, set[str]] = {}
    for character in characters:
        identity = character.get("character_id")
        if identity not in reality["approved_character_ids"]:
            continue
        for name in (identity, character.get("name")):
            if isinstance(name, str) and name:
                names.setdefault(name, set()).add(identity)
    entries, causes, omitted = [], [], []
    for row in (working.get("working_memory") or {}).get("entries", []):
        if row["perspective"] == "READER_ONLY" or row["source"]["chapter"] <= reality["chapter_number"]:
            continue
        reference = "working-observation:" + narrative_hash({"snapshot": working["snapshot_hash"], "observation": row["observation_id"]})
        causes.append({"source_event_id": reference, "observation_id": row["observation_id"],
            "source": deepcopy(row["source"]), "perspective": row["perspective"]})
        if row["state_role"] != "LATEST_OBSERVATION" or not (row["kind"] == "KNOWLEDGE" or row["perspective"] in {"BELIEF", "HEARSAY"}):
            continue
        owners = names.get(row["knowledge_owner"], set())
        if len(owners) != 1:
            omitted.append({"observation_id": row["observation_id"], "reason": "CHARACTER_ATTRIBUTION_UNRESOLVED"})
            continue
        identity = next(iter(owners))
        kind = "character_knowledge" if row["kind"] == "KNOWLEDGE" and row["perspective"] == "OBSERVED" else "character_belief"
        entries.append({"state_kind": kind, "entity_key": reference, "source_event_id": reference,
            "source_chapter": row["source"]["chapter"], "observation_id": row["observation_id"],
            "state": {"character_id": identity, "proposition": row["claim"], "state_key": row["state_key"],
                "perspective": row["perspective"], "epistemic_status": "UNREVIEWED_WORKING_OBSERVATION"},
            "evidence_role": "SELECTED_WORKING_OBSERVATION"})
    projection = {"contract_version": "world-working-observations.v1", "snapshot_hash": working["snapshot_hash"],
        "target_chapter": working["target_chapter"], "accepted_through_chapter": reality["chapter_number"],
        "authority": "SELECTED_WORKING_EXPERIENCE_FOR_CANDIDATES", "semantic_support": "NOT_VERIFIED",
        "accepted_history_mutation_allowed": False, "character_knowledge_granted": False,
        "interpretation": "These predicates describe the selected prose's unreviewed representation of the named character's information or belief. They do not establish an objective fact, a verified proposition or accepted knowledge. Director must compare the located observation against the actual passages before supporting a dependent action; belief and hearsay may be wrong.",
        "entries": entries, "causes": causes, "omissions": omitted}
    return {**deepcopy(dict(reality)), "working_observation_context": {**projection, "projection_hash": narrative_hash(projection)}}


def preview_preparation_transition(
    *,
    reality: Mapping[str, Any],
    transition: WorldTransition,
    chapter_number: int,
    path_id: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    previous = next(
        (
            entry
            for entry in reality.get("current_state", {}).get(
                transition.state_kind.value, []
            )
            if entry["entity_key"] == transition.entity_key
        ),
        {},
    )
    local_id = f"local:{transition.transition_id}"
    semantic = dict(
        state_kind=transition.state_kind,
        scope=NarrativeScope(str(reality["project_id"]), str(reality["book_id"])),
        identity=NarrativeIdentity(
            transition.state_kind.value,
            transition.entity_key,
            (("entity_key", transition.entity_key),),
        ),
        coordinate=NarrativeCoordinate(chapter_number, chapter_number),
        semantics=ReducerSemantics.TRANSITION,
        payload={
            **transition.changes,
            "world_transition": {
                "payload_json": json.dumps(
                    transition.to_dict(), sort_keys=True, separators=(",", ":")
                )
            },
        },
        supersedes_event_id="",
        provenance={"planning_baseline": reality["revision_id"], "path_id": path_id},
        confidence=1.0,
        coverage="PRIVATE_PREPARATION_SIMULATION",
        evidence={},
        event_version=3,
        entity_version=int(previous.get("entity_version") or 0) + 1,
        canon_status="NON_CANON_OBSERVATION",
        story_time=transition.story_time,
        causality=NarrativeCausality(
            cause_refs=transition.cause_refs,
            participant_ids=(transition.actor_id,),
            precondition_refs=tuple(
                requirement.requirement_id for requirement in transition.requirements
            ),
            effect_kinds=("STATE",),
        ),
    )
    event = NarrativeStateEvent(event_id=narrative_event_id(**semantic), **semantic)
    current = preview_state_events(previous=dict(reality), events=[event])
    entry = next(
        entry
        for entry in current[transition.state_kind.value]
        if entry["source_event_id"] == event.event_id
    )
    entry["source_event_id"] = local_id
    entry["story_time"] = transition.story_time.to_dict()
    return current, {**event.to_dict(), "event_id": local_id}


def validate_preparation_batch(
    *,
    reality: Mapping[str, Any],
    transitions: list[dict[str, Any]],
    chapter_number: int,
    path_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from copy import deepcopy
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.narrative_state.causal_batch import compile_causal_batch
    from .dynamics import candidate_transition, state_index, validate_world_state_rules

    transitions = json.loads(json.dumps(transitions))
    known = {
        entry.get("source_event_id", "") for entry in state_index(reality).values()
    }
    known.update(event.get("event_id", "") for event in reality.get("events", []))
    known.update(reality.get("foundation_cause_refs", []))
    known.update(row["source_event_id"] for row in (reality.get("working_observation_context") or {}).get("causes", []))
    known.discard("")
    graph = compile_causal_batch(
        [
            {
                "event_id": f"planning:{path_id}:{raw['transition_id']}",
                "state_kind": raw["state_kind"],
                "identity": {"entity_key": raw["entity_key"]},
                "story_time": raw["story_time"],
                "mutation": {
                    "payload": {
                        "causal_batch": {
                            "contract_version": "causal-batch-event.v1",
                            "local_id": raw["transition_id"],
                            "depends_on": raw["cause_refs"],
                        }
                    }
                },
            }
            for raw in transitions
        ],
        accepted_ids=frozenset(known),
    )
    by_name = {raw["transition_id"]: raw for raw in transitions}
    ordered = [
        by_name[node["mutation"]["payload"]["causal_batch"]["local_id"]]
        for node in graph.ordered
    ]
    baseline = deepcopy(reality)
    baseline.setdefault("events", []).extend(
        {"event_id": name} for name in sorted(known)
    )
    for raw in ordered:
        working = deepcopy(baseline)
        for prior in ordered:
            if prior["transition_id"] in graph.ancestors[raw["transition_id"]]:
                working["current_state"], event = preview_preparation_transition(
                    reality=working,
                    transition=WorldTransition.from_mapping(prior),
                    chapter_number=chapter_number,
                    path_id=path_id,
                )
                working["events"].append(event)
        transition = WorldTransition.from_mapping(raw)
        if not candidate_transition(transition, working)["eligible"]:
            raise KernelError(
                "WORLD_PREPARATION_UNSUPPORTED",
                "a due step lacks accepted or causally preceding preconditions",
            )
        preview_preparation_transition(
            reality=working,
            transition=transition,
            chapter_number=chapter_number,
            path_id=path_id,
        )
    combined = deepcopy(baseline)
    for raw in ordered:
        combined["current_state"], event = preview_preparation_transition(
            reality=combined,
            transition=WorldTransition.from_mapping(raw),
            chapter_number=chapter_number,
            path_id=path_id,
        )
        combined["events"].append(event)
    validate_world_state_rules(
        reality=reality,
        state=state_index(combined),
        affected_kinds={raw["state_kind"] for raw in ordered},
    )
    return ordered, combined
