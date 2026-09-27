from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash


DISPOSITIONS = ("CONTINUE", "DEFER", "REORDER", "RENEGOTIATE", "ABANDON")
TERMINAL_STEPS = {"COMPLETED", "ABANDONED"}
STEP_FIELDS = {"step_id", "action", "depends_on", "basis_refs", "obligation_ids", "decision", "reason", "status", "version", "completion"}
STATE_FIELDS = {"intent_id", "goal_id", "revision", "goal", "constraints", "disposition", "reason", "trigger_refs", "steps", "selected_step_id",
                "contract_version", "actor_id", "predecessor", "accepted_predecessor", "status"}


def intent_context(source: Mapping[str, Any], actor_id: str) -> dict[str, Any]:
    prior = source.get("actor_intent_sources", {}).get(actor_id)
    identity = "actor-intent:" + narrative_hash({
        "book_run_id": source["request"]["book_run_id"], "actor_id": actor_id,
    })[:24]
    state = deepcopy(prior["state"]) if prior else None
    if state and state["status"] in {"COMPLETED", "ABANDONED"}:
        identity = "actor-intent:" + narrative_hash({"predecessor": prior["proposal_ref"]})[:24]
        state = None
    elif state:
        identity = state["intent_id"]
    return {
        "contract_version": "actor-intent-context.v1", "actor_id": actor_id,
        "intent_id": identity, "goal_id": state["goal_id"] if state else identity + ":goal",
        "next_revision": state["revision"] + 1 if state else 1,
        "predecessor": deepcopy(prior["proposal_ref"]) if prior else {},
        "accepted_predecessor": {key: deepcopy(prior[key]) for key in ("acceptance_id", "outcome_ref")} if prior else {},
        "state": state,
        "max_steps": source["actor_experiment"]["max_intent_steps"],
    }


def validate_intent_context(context: Mapping[str, Any], actor_id: str) -> None:
    if (set(context) != {"contract_version", "actor_id", "intent_id", "goal_id", "next_revision", "predecessor", "accepted_predecessor", "state", "max_steps"}
        or context["contract_version"] != "actor-intent-context.v1" or context["actor_id"] != actor_id
        or type(context["max_steps"]) is not int or not 2 <= context["max_steps"] <= 8):
        raise KernelError("WORLD_ACTOR_INTENT_CONTEXT_INVALID", "intent context must retain its bounded own accepted lineage")
    state = context["state"]
    if state is not None and (set(state) != STATE_FIELDS or state.get("actor_id") != actor_id or state.get("intent_id") != context["intent_id"]
                              or context["next_revision"] != state["revision"] + 1 or state["goal_id"] != context["goal_id"]
                              or len(state.get("steps", [])) > context["max_steps"]
                              or any(set(step) != STEP_FIELDS for step in state["steps"])):
        raise KernelError("WORLD_ACTOR_INTENT_CONTEXT_INVALID", "another actor or unbounded intention cannot enter private context")


def intent_schema(task: Mapping[str, Any], refs: list[str]) -> dict[str, Any]:
    context = task["private_observation"]["intent_context"]
    text = {"type": "string", "minLength": 1, "maxLength": 1000}
    basis = {"type": "array", "minItems": 1, "maxItems": 16, "uniqueItems": True,
             "items": {"type": "string", "enum": refs}}
    step = {"type": "object", "additionalProperties": False, "properties": {
        "step_id": {"type": "string", "minLength": 1, "maxLength": 160}, "action": text,
        "depends_on": {"type": "array", "maxItems": context["max_steps"], "uniqueItems": True, "items": {"type": "string"}},
        "basis_refs": basis,
        "obligation_ids": {"type": "array", "maxItems": 16, "uniqueItems": True, "items": {"type": "string"}},
        "decision": {"type": "string", "enum": [*DISPOSITIONS, "PRESERVE"]}, "reason": text,
    }, "required": ["step_id", "action", "depends_on", "basis_refs", "obligation_ids", "decision", "reason"]}
    properties = {
        "intent_id": {"const": context["intent_id"], "type": "string"},
        "goal_id": {"const": context["goal_id"], "type": "string"},
        "revision": {"const": context["next_revision"], "type": "integer"},
        "goal": text,
        "constraints": {"type": "array", "maxItems": 8, "items": text},
        "disposition": {"type": "string", "enum": list(DISPOSITIONS)}, "reason": text,
        "trigger_refs": basis,
        "steps": {"type": "array", "minItems": 1 if context["state"] else 2, "maxItems": context["max_steps"], "items": step},
        "selected_step_id": {"type": ["string", "null"]},
    }
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


def validate_intent_plan(raw: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    context = task["private_observation"]["intent_context"]
    plan = raw["intent_plan"]
    prior = context["state"] or {}
    previous = {step["step_id"]: step for step in prior.get("steps", [])}
    steps = plan["steps"]
    ids = [step["step_id"] for step in steps]
    if len(ids) != len(set(ids)) or not set(previous).issubset(ids):
        raise KernelError("WORLD_ACTOR_INTENT_STEP_LOST", "every prior step, including abandoned and completed steps, must retain its stable identity")
    if prior and (plan["goal"] != prior["goal"] or plan["constraints"] != prior["constraints"]) and plan["disposition"] != "RENEGOTIATE":
        raise KernelError("WORLD_ACTOR_INTENT_GOAL_REWRITTEN", "goal or constraint changes require explicit renegotiation and accepted private triggers")
    own_obligations = {row["content"].get("obligation_id") for row in task["private_observation"]["accepted_self_state"] if row["kind"] == "narrative_obligation"}
    prior_refs = {ref for step in previous.values() for ref in step["basis_refs"]}
    current_refs = {"APPROVED_SELF_TRAITS", *[row["source_event_id"] for row in task["private_observation"]["observations"]],
                    *[row["source_event_id"] for row in task["private_observation"]["accepted_self_state"]]}
    if not set(plan["trigger_refs"]).issubset(current_refs):
        raise KernelError("WORLD_ACTOR_INTENT_TRIGGER_STALE", "reevaluation requires current own observations, beliefs or accepted self state")
    result = []
    for step in steps:
        old = previous.get(step["step_id"])
        dependencies = step["depends_on"]
        if not set(dependencies).issubset(ids[:ids.index(step["step_id"])]) or not set(step["obligation_ids"]).issubset(own_obligations | set((old or {}).get("obligation_ids", []))):
            raise KernelError("WORLD_ACTOR_INTENT_DEPENDENCY_INVALID", "steps require an ordered acyclic own-intent dependency graph and owned commitments")
        if not set(step["basis_refs"]).issubset(current_refs | (prior_refs if old else set())):
            raise KernelError("WORLD_ACTOR_INTENT_BASIS_INVALID", "new intentions cannot obtain other actors' or invented knowledge")
        immutable = ("step_id", "action", "depends_on", "basis_refs", "obligation_ids")
        changed = old and any(step[key] != old[key] for key in immutable)
        if old and old["status"] in TERMINAL_STEPS:
            if step["decision"] != "PRESERVE" or changed:
                raise KernelError("WORLD_ACTOR_INTENT_HISTORY_REWRITTEN", "terminal intent history is immutable")
            result.append(deepcopy(old))
            continue
        if step["decision"] == "PRESERVE" or (changed and step["decision"] not in {"REORDER", "RENEGOTIATE"}):
            raise KernelError("WORLD_ACTOR_INTENT_REVISION_INVALID", "pending changes require explicit reorder or renegotiation")
        if old and step["decision"] == "REORDER" and any(step[key] != old[key] for key in ("action", "obligation_ids")):
            raise KernelError("WORLD_ACTOR_INTENT_REVISION_INVALID", "reordering cannot silently change an action or commitment")
        status = {"DEFER": "DEFERRED", "ABANDON": "ABANDONED"}.get(step["decision"], "PLANNED")
        result.append({**deepcopy(step), "status": status, "version": (old["version"] + 1) if old else 1, "completion": None})
    selected = next((step for step in result if step["step_id"] == plan["selected_step_id"]), None)
    if plan["selected_step_id"] is not None and (selected is None or selected["status"] != "PLANNED" or selected["action"] != raw["action"]
            or not set(selected["basis_refs"]).issubset(raw["basis_refs"])
            or any(next(item for item in result if item["step_id"] == dependency)["status"] != "COMPLETED" for dependency in selected["depends_on"])):
        raise KernelError("WORLD_ACTOR_INTENT_SELECTION_INVALID", "current action needs an executable pending step whose dependencies were accepted")
    if plan["disposition"] in {"DEFER", "ABANDON"} and selected is not None:
        raise KernelError("WORLD_ACTOR_INTENT_SELECTION_INVALID", "deferred or abandoned intention cannot execute a step")
    if plan["disposition"] not in {"DEFER", "ABANDON"} and selected is None:
        raise KernelError("WORLD_ACTOR_INTENT_SELECTION_INVALID", "an active intention requires one executable step")
    if plan["disposition"] == "DEFER" and any(step["status"] == "PLANNED" for step in result):
        raise KernelError("WORLD_ACTOR_INTENT_DEFERRAL_INCOMPLETE", "a paused intention retains every pending step as explicitly deferred")
    if plan["disposition"] == "ABANDON" and any(step["status"] not in TERMINAL_STEPS for step in result):
        raise KernelError("WORLD_ACTOR_INTENT_ABANDONMENT_INCOMPLETE", "abandonment must retain an explicit disposition for every pending step")
    return {**deepcopy(plan), "contract_version": "actor-intent-state.v1", "actor_id": raw["actor_id"],
            "predecessor": deepcopy(context["predecessor"]), "accepted_predecessor": deepcopy(context["accepted_predecessor"]),
            "steps": result, "status": "ABANDONED" if plan["disposition"] == "ABANDON" else "ACTIVE"}


def reconcile_accepted_intent(*, output: Mapping[str, Any], binding: Mapping[str, Any], outcome: Mapping[str, Any],
                              acceptance_id: str, outcome_ref: Mapping[str, str]) -> dict[str, Any]:
    from novel_forge.modules.canon_graph.background import preparation_lineage, require_observed_transition, scheduled_world_events

    state = deepcopy(output["intent_state"])
    selected = next((step for step in state["steps"] if step["step_id"] == state["selected_step_id"]), None)
    if selected is None or selected["status"] != "PLANNED":
        return state
    candidates = [transition for transition in scheduled_world_events(binding)
                  if transition["camera"] == "ON_CAMERA" and transition["actor_id"] == state["actor_id"] and transition["action"] == output["action"]]
    matches = []
    for transition in candidates:
        for event in outcome.get("state_events", []):
            payload = event.get("mutation", {}).get("payload", {})
            if payload.get("preparation_lineage") != preparation_lineage(binding, transition["transition_id"]):
                continue
            require_observed_transition(expected=transition, actual=payload.get("world_transition"))
            from .actor_execution import require_accepted_actor_execution

            require_accepted_actor_execution(binding=binding, transition=transition, output=output, event=event)
            if not event.get("provenance", {}).get("accepted_draft_asset_version_id"):
                raise KernelError("WORLD_ACTOR_COMPLETION_PROVENANCE_MISSING", "completion requires an accepted prose observation")
            matches.append(event)
    if len(matches) > 1:
        raise KernelError("WORLD_ACTOR_COMPLETION_AMBIGUOUS", "one intended step cannot bind several accepted observations")
    if matches:
        event = matches[0]
        selected["status"] = "COMPLETED"
        selected["completion"] = {"acceptance_id": acceptance_id, "outcome_ref": dict(outcome_ref), "event_id": event["event_id"],
                                  "accepted_draft_asset_version_id": event["provenance"]["accepted_draft_asset_version_id"]}
        if binding["action"].get("execution_contract_version") == "world-scene-execution.v2":
            payload = event["mutation"]["payload"]
            selected["completion"].update(grounded_claim_id=payload["grounded_claim_id"],
                                          observed_action=payload["actor_step_execution"]["observed_action"],
                                          execution_contract_version="world-scene-execution.v2")
        if all(step["status"] in TERMINAL_STEPS for step in state["steps"]):
            state["status"] = "COMPLETED" if all(step["status"] == "COMPLETED" for step in state["steps"]) else "ABANDONED"
    return state
