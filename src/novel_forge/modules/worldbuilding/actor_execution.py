from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


EXECUTION_VERSION = "world-scene-execution.v2"


def compile_current_actor_steps(action: Mapping[str, Any], proposals: list[dict[str, Any]],
                                references: list[dict[str, str]]) -> list[dict[str, Any]]:
    from novel_forge.modules.canon_graph.background import scheduled_world_events

    if action["world_plan"]["disposition"] == "BLOCKED":
        return []
    result = []
    for event in scheduled_world_events({"action": action}):
        if event["camera"] != "ON_CAMERA":
            continue
        matching = [(proposal, ref) for proposal, ref in zip(proposals, references, strict=True)
                    if proposal["actor_id"] == event["actor_id"] and proposal["action"] == event["action"]]
        if len(matching) != 1:
            raise KernelError("WORLD_ACTOR_EXECUTION_SOURCE_INVALID", "each on-camera execution must bind exactly one judged Actor proposal")
        proposal, ref = matching[0]
        state = proposal["intent_state"]
        step = next((item for item in state["steps"] if item["step_id"] == state["selected_step_id"]), None)
        if step is None or step["status"] != "PLANNED" or step["action"] != event["action"]:
            raise KernelError("WORLD_ACTOR_EXECUTION_STEP_INVALID", "only the current executable intention step may enter prose planning")
        result.append({
            "transition_id": event["transition_id"], "actor_id": event["actor_id"], "action": event["action"],
            "intent_id": state["intent_id"], "goal_id": state["goal_id"], "intent_revision": state["revision"],
            "step_id": step["step_id"], "step_version": step["version"], "proposal_ref": deepcopy(ref),
        })
    return result


def current_actor_step(binding: Mapping[str, Any], transition: Mapping[str, Any]) -> dict[str, Any] | None:
    action = binding["action"]
    version = action.get("execution_contract_version")
    if version is None:
        return None
    if version != EXECUTION_VERSION:
        raise KernelError("WORLD_ACTOR_EXECUTION_CONTRACT_INVALID", "the frozen execution contract is unsupported")
    matched = [item for item in action.get("current_actor_steps", []) if item["transition_id"] == transition["transition_id"]]
    if len(matched) != 1 or any(matched[0][key] != transition[key] for key in ("actor_id", "action")) or matched[0]["proposal_ref"] not in action.get("actor_proposals", []):
        raise KernelError("WORLD_ACTOR_EXECUTION_SOURCE_INVALID", "execution must retain the exact approved action and proposal lineage")
    return deepcopy(matched[0])


def actor_execution_comparison(binding: Mapping[str, Any], transition: Mapping[str, Any],
                               observed: Mapping[str, Any]) -> dict[str, Any] | None:
    target = current_actor_step(binding, transition)
    if target is None:
        return None
    return {
        "contract_version": "actor-step-execution-comparison.v1",
        "approved_target": target,
        "target_source": {"asset_version_id": binding["asset_version_id"], "content_hash": binding["content_hash"]},
        "observed_action": json.loads(observed["payload_json"])["action"],
        "support_requirement": "Compare the actual observed action and its final-prose evidence with the approved current step. SUPPORT requires the prose to realize this specific action; a matching actor, transition ID or state counter is insufficient. A future intention, different action, ambiguity or missing evidence is UNSUPPORTED or UNCERTAIN. The approved target is a plan, never observed evidence.",
    }


def require_accepted_actor_execution(*, binding: Mapping[str, Any], transition: Mapping[str, Any],
                                     output: Mapping[str, Any], event: Mapping[str, Any]) -> None:
    target = current_actor_step(binding, transition)
    if target is None:
        return
    state = output["intent_state"]
    selected = next(item for item in state["steps"] if item["step_id"] == state["selected_step_id"])
    if any(target[key] != value for key, value in {
        "intent_id": state["intent_id"], "goal_id": state["goal_id"], "intent_revision": state["revision"],
        "step_id": selected["step_id"], "step_version": selected["version"], "action": output["action"],
    }.items()):
        raise KernelError("WORLD_ACTOR_COMPLETION_STEP_DRIFT", "accepted execution belongs to another version of the intended step")
    payload = event.get("mutation", {}).get("payload", {})
    expected = actor_execution_comparison(binding, transition, payload["world_transition"])
    if payload.get("actor_step_execution") != expected or not payload.get("grounded_claim_id") or not event.get("evidence", {}).get("quote"):
        raise KernelError("WORLD_ACTOR_COMPLETION_SUPPORT_REQUIRED", "completion requires the grounded accepted comparison of actual prose action and exact current step")
