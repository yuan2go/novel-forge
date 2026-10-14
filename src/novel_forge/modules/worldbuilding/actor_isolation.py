from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash

ACTOR_STAGES = ("world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2")
ACTOR_TRAITS = ("name", "desire", "need", "fear", "false_belief", "moral_boundary", "capability", "weakness", "behavioral_pattern", "risk_preference")
KNOWLEDGE_FIELDS = ("character_id", "fact_id", "proposition_id", "status", "stance", "proposition", "claim", "content", "statement", "description")

CURRENT_KNOWLEDGE_FIELDS = (*KNOWLEDGE_FIELDS, "summary", "belief_confidence")
ACTOR_COMMITMENT_TYPES = frozenset({"PROMISE", "CHARACTER_COMMITMENT"})

SELF_STATE_FIELDS = {
    "character_state": ("character_id", "goal", "desire", "intention", "status", "action_state", "life_status", "state"),
    "relationship_state": ("source_id", "target_id", "relationship_type", "status", "stance", "attitude", "commitment", "state"),
    "narrative_obligation": ("character_id", "obligation_id", "obligation_type", "status", "current_development"),
}


def accepted_self_state(source: Mapping[str, Any], actor_id: str) -> list[dict[str, Any]]:
    result = []
    for kind, fields in SELF_STATE_FIELDS.items():
        for entry in source["reality"]["current_state"].get(kind, []):
            state = entry.get("state") or {}
            owner = state.get("source_id") if kind == "relationship_state" else state.get("character_id")
            if owner != actor_id:
                continue
            if kind == "narrative_obligation" and state.get("obligation_type") not in ACTOR_COMMITMENT_TYPES:
                continue
            result.append({"kind": kind, "source_event_id": entry["source_event_id"],
                "content": {key: state[key] for key in fields if isinstance(state.get(key), (str, int, float, bool))}})
    return sorted(result, key=lambda row: (row["kind"], row["source_event_id"]))


def validate_actor_policy(value: Mapping[str, Any], *, character_ids: list[str], policy: Any) -> dict[str, Any]:
    persistent = value.get("version") == "world-actor-experiment.v2"
    fields = {"version", "actor_ids", "max_rounds", "max_actions_per_actor"} | ({"max_intent_steps"} if persistent else set())
    if "execution_contract_version" in value:
        if not persistent or value["execution_contract_version"] != "world-scene-execution.v2":
            raise KernelError("WORLD_ACTOR_POLICY_INVALID", "explicit step execution requires the persistent Actor contract")
        fields.add("execution_contract_version")
    if set(value) != fields or value["version"] not in {"world-actor-experiment.v1", "world-actor-experiment.v2"}:
        raise KernelError("WORLD_ACTOR_POLICY_INVALID", "an explicit bounded actor experiment policy is required")
    actors = value["actor_ids"]
    if (not isinstance(actors, list) or not 1 <= len(actors) <= 3
        or any(not isinstance(actor, str) or actor not in character_ids for actor in actors)
        or len(set(actors)) != len(actors) or any(type(value[key]) is not int or value[key] != 1 for key in ("max_rounds", "max_actions_per_actor"))
        or policy.version not in {"world-production-policy.v2", "world-production-policy.v3", "world-production-policy.v4"} or policy.max_provider_stages != len(actors) + 2
        or policy.max_candidates > len(actors) or policy.max_paths_per_candidate != 1
        or policy.max_preparation_steps != 1 or policy.planning_window_chapters != 1):
        raise KernelError("WORLD_ACTOR_POLICY_INVALID", "experiment admits at most three approved actors, one action each and one frozen round plus judge and Director")
    if persistent and (type(value["max_intent_steps"]) is not int or not 2 <= value["max_intent_steps"] <= 8):
        raise KernelError("WORLD_ACTOR_POLICY_INVALID", "persistent intentions require between two and eight retained steps")
    return deepcopy(dict(value))


def actor_task(source: Mapping[str, Any], source_ref: Mapping[str, str], actor_id: str) -> dict[str, Any]:
    cast = next((item for item in source["character_definitions"] if item["character_id"] == actor_id), None)
    if cast is None or not str(cast.get("desire") or "").strip():
        raise KernelError("WORLD_ACTOR_GOAL_UNAVAILABLE", "actor needs its own approved desire before any dispatch")
    traits = {key: cast[key] for key in ACTOR_TRAITS if isinstance(cast.get(key), str)}
    persistent = source.get("actor_experiment", {}).get("version") == "world-actor-experiment.v2"
    continuous = source.get("provider_projection_version") in {"world-role-delivery.v2", "world-role-delivery.v3", "world-role-delivery.v4"}
    if persistent and not continuous:
        raise KernelError("WORLD_ACTOR_POLICY_INVALID", "multi-step intentions require the current accepted private projection")
    knowledge_fields = CURRENT_KNOWLEDGE_FIELDS if continuous else KNOWLEDGE_FIELDS
    observations = []
    for kind in ("character_knowledge", "character_belief"):
        for entry in source["reality"]["current_state"].get(kind, []):
            state = entry.get("state") or {}
            if state.get("character_id") != actor_id or (kind == "character_knowledge" and state.get("status") not in {"KNOWN", "SUSPECTED"}):
                continue
            projected = {key: state[key] for key in knowledge_fields if isinstance(state.get(key), (str, int, float, bool))}
            observations.append({"source_event_id": entry["source_event_id"], "kind": kind, "content": projected})
    if not observations:
        raise KernelError(
            "WORLD_ACTOR_KNOWLEDGE_UNAVAILABLE",
            "an actor needs its own frozen initial or accepted knowledge/belief before any dispatch",
        )
    private = {"actor_id": actor_id, "traits": traits, "observations": observations}
    if continuous:
        private["accepted_self_state"] = accepted_self_state(source, actor_id)
    if persistent:
        from .actor_intents import intent_context
        private["intent_context"] = intent_context(source, actor_id)
    return {
        "contract_version": "world-actor-task.v3" if persistent else "world-actor-task.v2" if continuous else "world-actor-task.v1", "role": "ACTOR", "source_ref": dict(source_ref),
        "baseline_id": source["reality"]["revision_id"], "baseline_kind": source["reality"]["baseline_kind"],
        "accepted_through_chapter": source["reality"]["chapter_number"], "private_observation": private,
        "projection_identity": narrative_hash(private), "policy": dict(source["policy"]), "fact_mutation_allowed": False,
        "instructions": ("Maintain the bounded stable intent, goal and step identities. Reevaluate every pending step against current own knowledge, beliefs, resources, relations and obligations, explicitly continuing, deferring, reordering, renegotiating or abandoning with reasons and current trigger refs. Preserve terminal steps. Completed steps come only from the supplied accepted predecessor, never from simulation or a judge. Select a step only when its dependencies are completed, and preserve its action verbatim. Deferred or abandoned intention may select no step; any accompanying action remains a proposal. An abandoned intention never cancels an accepted commitment. " if persistent else "") + ("Explicitly CONTINUE or DEFER every supplied open own commitment, preserving its obligation and accepted source identity; continuation must cite that source in the judged transition. A deferred commitment remains open, and only observed prose accepted by Book may change it. " if continuous else "") + "Choose one intended action from your own desire and supplied knowledge or beliefs. Other characters, global secrets, the outline and future events are unavailable. Beliefs are not objective facts. Do not invent acquired knowledge. Supply only a short action-basis summary and listed source IDs; never provide internal reasoning or a chain of thought. A judge determines feasibility and consequences, and cannot rewrite your intention.",
    }


def validate_actor_task(task: Mapping[str, Any]) -> None:
    allowed = {"contract_version", "role", "source_ref", "baseline_id", "baseline_kind", "accepted_through_chapter", "private_observation", "projection_identity", "policy", "fact_mutation_allowed", "instructions"}
    private = task.get("private_observation") or {}
    version = task.get("contract_version")
    private_fields = {"actor_id", "traits", "observations"} | ({"accepted_self_state"} if version in {"world-actor-task.v2", "world-actor-task.v3"} else set()) | ({"intent_context"} if version == "world-actor-task.v3" else set())
    if (set(task) != allowed or version not in {"world-actor-task.v1", "world-actor-task.v2", "world-actor-task.v3"} or task.get("role") != "ACTOR"
        or task.get("fact_mutation_allowed") is not False or set(private) != private_fields
        or task.get("projection_identity") != narrative_hash(private) or not set(private["traits"]).issubset(ACTOR_TRAITS)
        or any(set(row) != {"source_event_id", "kind", "content"} or not row.get("source_event_id")
               or row.get("kind") not in {"character_knowledge", "character_belief"}
               or row.get("content", {}).get("character_id") != private["actor_id"]
               or not set(row.get("content", {})).issubset(CURRENT_KNOWLEDGE_FIELDS if version in {"world-actor-task.v2", "world-actor-task.v3"} else KNOWLEDGE_FIELDS)
               or any(not isinstance(value, (str, int, float, bool)) for value in row.get("content", {}).values())
               for row in private["observations"])):
        raise KernelError("WORLD_ACTOR_CONTEXT_LEAK", "actor request must contain only its frozen private projection")
    for row in private.get("accepted_self_state", []):
        kind, content = row.get("kind"), row.get("content") or {}
        if (set(row) != {"source_event_id", "kind", "content"}
            or kind not in SELF_STATE_FIELDS or not set(content).issubset(SELF_STATE_FIELDS[kind])
            or any(not isinstance(value, (str, int, float, bool)) for value in content.values())
            or (kind == "narrative_obligation" and content.get("obligation_type") not in ACTOR_COMMITMENT_TYPES)
            or content.get("source_id" if kind == "relationship_state" else "character_id") != private["actor_id"]
            or not row.get("source_event_id")):
            raise KernelError("WORLD_ACTOR_CONTEXT_LEAK", "accepted self state must retain directional ownership and source identity")

    if version == "world-actor-task.v3":
        from .actor_intents import validate_intent_context
        validate_intent_context(private["intent_context"], private["actor_id"])


def actor_output_schema(task: Mapping[str, Any]) -> dict[str, Any]:
    private = task["private_observation"]
    refs = ["APPROVED_SELF_TRAITS", *[row["source_event_id"] for row in private["observations"]], *[row["source_event_id"] for row in private.get("accepted_self_state", [])]]
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
            "properties": {"actor_id": {"type": "string", "enum": [private["actor_id"]]},
                           "action": {"type": "string", "minLength": 1, "maxLength": 1000},
                           "basis_summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                           "basis_refs": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "enum": refs}}},
            "required": ["actor_id", "action", "basis_summary", "basis_refs"]}
    if task["contract_version"] in {"world-actor-task.v2", "world-actor-task.v3"}:
        commitments = pending_commitments(task)
        schema["properties"]["commitment_dispositions"] = {
            "type": "array", "minItems": len(commitments), "maxItems": len(commitments),
            "items": {"type": "object", "additionalProperties": False,
                      "properties": {"obligation_id": {"type": "string", "minLength": 1},
                                     "source_event_id": {"type": "string", "minLength": 1},
                                     "decision": {"type": "string", "enum": ["CONTINUE", "DEFER"]},
                                     "reason": {"type": "string", "minLength": 1, "maxLength": 1000}},
                      "required": ["obligation_id", "source_event_id", "decision", "reason"]}}
        schema["required"].append("commitment_dispositions")
    if task["contract_version"] == "world-actor-task.v3":
        from .actor_intents import intent_schema
        intent_refs = list(dict.fromkeys([*refs, *(ref for step in (private["intent_context"].get("state") or {}).get("steps", []) for ref in step["basis_refs"])]))
        schema["properties"]["intent_plan"] = intent_schema(task, intent_refs)
        schema["required"].append("intent_plan")
    return schema


def pending_commitments(task: Mapping[str, Any]) -> dict[str, str]:
    return {
        row["content"]["obligation_id"]: row["source_event_id"]
        for row in task["private_observation"].get("accepted_self_state", [])
        if row["kind"] == "narrative_obligation"
        and row["content"].get("obligation_type") in ACTOR_COMMITMENT_TYPES
        and row["content"].get("status") in {"OPEN", "DEVELOPING", "DUE"}
    }


def actor_output_payload(output: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    return {key: output[key] for key in actor_output_schema(task)["required"]}


def validate_actor_output(raw: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    validate_chapter_provider_output_against_schema("actor", actor_output_schema(task), raw)
    if task["contract_version"] in {"world-actor-task.v2", "world-actor-task.v3"}:
        expected = pending_commitments(task)
        actual = raw["commitment_dispositions"]
        if (len({row["obligation_id"] for row in actual}) != len(actual)
            or {row["obligation_id"]: row["source_event_id"] for row in actual} != expected
            or any(row["decision"] == "CONTINUE" and row["source_event_id"] not in raw["basis_refs"] for row in actual)):
            raise KernelError("WORLD_ACTOR_COMMITMENT_CONTINUITY_INVALID", "every open own commitment requires one exact accepted-source disposition and continuing actions must cite it")
    result = {**deepcopy(dict(raw)), "projection_identity": task["projection_identity"], "proposal_hash": narrative_hash(raw)}
    if task["contract_version"] == "world-actor-task.v3":
        from .actor_intents import validate_intent_plan
        result["intent_state"] = validate_intent_plan(raw, task)
    return result


def actor_judge_schema(schema: Mapping[str, Any], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(dict(schema))
    result["properties"]["actor_adjudications"] = {
        "type": "array", "minItems": len(proposals), "maxItems": len(proposals),
        "items": {"type": "object", "additionalProperties": False,
                  "properties": {"actor_id": {"type": "string", "enum": [row["actor_id"] for row in proposals]},
                                 "proposal_hash": {"type": "string", "enum": [row["proposal_hash"] for row in proposals]},
                                 "decision": {"type": "string", "enum": ["EXECUTABLE", "REJECTED"]},
                                 "consequence_summary": {"type": "string", "minLength": 1}},
                  "required": ["actor_id", "proposal_hash", "decision", "consequence_summary"]}}
    result["required"].append("actor_adjudications")
    return result


def require_actor_judgments(generated: Mapping[str, Any], proposals: list[dict[str, Any]], *, agency: bool = False) -> None:
    from novel_forge.modules.worldbuilding.production_schema import decode_world_generation
    by_actor = {row["actor_id"]: row for row in proposals}
    judgments = generated.get("actor_adjudications")
    if not isinstance(judgments, list) or len(judgments) != len(by_actor) or {row.get("actor_id") for row in judgments} != set(by_actor):
        raise KernelError("WORLD_ACTOR_JUDGMENT_INCOMPLETE", "all actor proposals need one exact adjudication before a world action")
    decoded = decode_world_generation({key: value for key, value in generated.items() if key not in {"actor_adjudications", "knowledge_translations"}}, agency=agency)
    candidates = decoded["candidates"]
    for judgment in judgments:
        proposal = by_actor[judgment["actor_id"]]
        matching = [row for row in candidates if row["transition"]["actor_id"] == proposal["actor_id"]]
        if (judgment.get("proposal_hash") != proposal["proposal_hash"] or judgment.get("decision") not in {"EXECUTABLE", "REJECTED"}
            or bool(matching) != (judgment["decision"] == "EXECUTABLE") or len(matching) > 1
            or (matching and proposal.get("intent_state") is not None and proposal["intent_state"]["selected_step_id"] is None)
            or any(row["transition"]["action"] != proposal["action"] or row["preparation_paths"] for row in matching)
            or any(item["source_event_id"] not in row["transition"]["cause_refs"]
                   or item["obligation_id"] not in row["obligation_refs"]
                   for item in proposal.get("commitment_dispositions", []) if item["decision"] == "CONTINUE"
                   for row in matching)):
            raise KernelError("WORLD_ACTOR_INTENT_REWRITTEN", "judge must preserve intention and accepted commitment causes and identities; only feasibility and consequences may change")
    if any(row["transition"]["actor_id"] not in by_actor for row in candidates):
        raise KernelError("WORLD_ACTOR_INTENT_REWRITTEN", "judge introduced an unadmitted actor")
