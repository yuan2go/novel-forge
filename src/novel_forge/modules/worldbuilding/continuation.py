from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from .dynamics import (
    WorldTransition,
    candidate_transition,
    state_index,
    validate_world_state_rules,
)
from .working_state import preview_preparation_transition


def decide_preparation(
    *,
    reality: Mapping[str, Any],
    origin: Mapping[str, Any],
    accepted_steps: Mapping[str, str],
    chapter_number: int,
    intent_version_id: str,
) -> dict[str, Any]:
    original = origin["action"]["world_plan"]
    selected = next(
        item
        for item in original["candidate_futures"]
        if item.get("candidate_id") == original["selected_candidate_id"]
    )
    target = selected["transition"]
    scope = {
        "asset_version_id": origin["asset_version_id"],
        "content_hash": origin["content_hash"],
        "path_id": original["selected_path_id"],
    }
    decision = {
        "contract_version": "world-preparation-continuation.v1",
        "origin": scope,
        "baseline_id": reality["revision_id"],
        "chapter_number": chapter_number,
        "accepted_step_mapping": dict(accepted_steps),
        "due_transitions": [],
        "target_transition_id": target["transition_id"],
        "fact_mutation_allowed": False,
    }
    if target["transition_id"] in accepted_steps:
        return {**decision, "status": "COMPLETE", "reason": "TARGET_ACCEPTED"}
    if original["intent_version_id"] != intent_version_id:
        return {**decision, "status": "CANCEL", "reason": "APPROVED_INTENT_REPLACED"}
    if (
        chapter_number
        >= original["chapter_number"] + original["policy"]["planning_window_chapters"]
    ):
        return {**decision, "status": "CANCEL", "reason": "PREPARATION_WINDOW_EXPIRED"}
    support = dict(accepted_steps)
    reused = {}
    index = state_index(reality)
    for step in original["preparation_schedule"]:
        raw = step["transition"]
        name = raw["transition_id"]
        if name in support:
            continue
        entry = index.get((raw["state_kind"], raw["entity_key"]), {})
        expected = dict(raw["changes"])
        if raw["state_kind"] == "resource_state" and "balance_after" in expected:
            expected = {
                key: value
                for key, value in expected.items()
                if key not in {"balance_before", "balance_after", "delta"}
            }
            expected["balance"] = raw["changes"]["balance_after"]
        if (
            expected
            and entry.get("source_event_id")
            and all(
                type(entry.get("state", {}).get(key)) is type(value)
                and entry["state"].get(key) == value
                for key, value in expected.items()
            )
        ):
            support[name] = entry["source_event_id"]
            reused[name] = {
                "event_id": entry["source_event_id"],
                "basis": "ACCEPTED_EFFECT_MATCH",
                "expected_effect": expected,
            }
    decision["reused_effect_evidence"] = reused
    remaining = [
        step
        for step in original["preparation_schedule"]
        if step["transition"]["transition_id"] not in support
    ]
    due = [step for step in remaining if step["chapter_number"] <= chapter_number]
    is_target = not remaining
    if is_target:
        due = [{"transition": target, "chapter_number": chapter_number}]
    if not due:
        return {**decision, "status": "DEFER", "reason": "WAIT_SCHEDULED_CHAPTER"}
    working = deepcopy(reality)
    checked = []
    for step in due:
        raw = deepcopy(step["transition"])
        raw["cause_refs"] = [
            support.get(ref[6:], ref) if ref.startswith("local:") else ref
            for ref in raw["cause_refs"]
        ]
        try:
            transition = WorldTransition.from_mapping(json.loads(json.dumps(raw)))
            result = candidate_transition(transition, working)
            if not result["eligible"]:
                return {
                    **decision,
                    "status": "WAIT_PRECONDITION",
                    "reason": "ACCEPTED_CONDITIONS_UNSATISFIED",
                    "requirements": result["requirements"],
                }
            working["current_state"], simulated = preview_preparation_transition(
                reality=working,
                transition=transition,
                chapter_number=chapter_number,
                path_id=original["selected_path_id"],
            )
            working.setdefault("events", []).append(simulated)
            checked.append(raw)
        except KernelError as exc:
            return {
                **decision,
                "status": "BLOCKED",
                "reason": exc.code,
                "error": str(exc),
            }
    try:
        validate_world_state_rules(
            reality=reality,
            state=state_index(working),
            affected_kinds={raw["state_kind"] for raw in checked},
        )
    except KernelError as exc:
        return {**decision, "status": "BLOCKED", "reason": exc.code, "error": str(exc)}
    return {
        **decision,
        "status": "EXECUTE",
        "reason": "ACCEPTED_PREPARATION_CONTINUES",
        "due_transitions": checked,
        "execute_target": is_target,
        "original_plan": deepcopy(original),
    }


def apply_preparation_decisions(
    *,
    fresh_plan: Mapping[str, Any],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    plan = deepcopy(fresh_plan)
    active = sorted(
        (d for d in decisions if d["status"] == "EXECUTE"),
        key=lambda d: d["origin"]["asset_version_id"],
    )
    retained = deepcopy(decisions)
    for row in retained:
        row.pop("original_plan", None)
    if active:
        selected = active[0]
        prior = selected["original_plan"]
        for row in retained:
            if row["status"] == "EXECUTE" and row["origin"] != selected["origin"]:
                row.update(status="DEFER", reason="ONE_PREPARATION_GOAL_PER_CHAPTER")
                row["due_transitions"] = []
        plan.update(
            disposition="ELIGIBLE"
            if selected["execute_target"]
            else "PREPARATION_REQUIRED",
            reason="Continue the original accepted preparation before new world proposals.",
            selected_candidate_id=prior["selected_candidate_id"],
            selected_path_id=prior["selected_path_id"],
            candidate_futures=deepcopy(prior["candidate_futures"]),
            causal_debts=deepcopy(prior["causal_debts"]),
            preparation_schedule=[
                {
                    "transition": raw,
                    "chapter_number": plan["chapter_number"],
                    "depends_on": raw["cause_refs"],
                    "expected_effect": raw["changes"],
                    "status": "PLANNED_NOT_ACCEPTED",
                    "path_id": prior["selected_path_id"],
                }
                for raw in selected["due_transitions"]
            ],
            continuation_origin=selected["origin"],
            fresh_portfolio={
                key: deepcopy(fresh_plan[key])
                for key in ("disposition", "candidate_futures", "rejected_paths")
            },
        )
        if selected["execute_target"]:
            for candidate in plan["candidate_futures"]:
                if candidate.get("candidate_id") == plan["selected_candidate_id"]:
                    candidate.update(
                        eligible=True, transition=selected["due_transitions"][0]
                    )
        plan["disclosure_projection"] = []
    elif any(d["status"] in {"BLOCKED", "WAIT_PRECONDITION"} for d in decisions):
        plan.update(
            disposition="BLOCKED",
            reason="An accepted preparation requires a directed future decision before production can continue.",
        )
    plan["continuation_decisions"] = retained
    plan.pop("plan_digest", None)
    return {**plan, "plan_digest": narrative_hash(plan)}
