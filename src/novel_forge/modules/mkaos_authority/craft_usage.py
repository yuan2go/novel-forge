from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


DEFAULT_USAGE_TYPES = {
    "event": {"mode": "EVENT", "scope": "SCENE", "phases": ["MANIFEST"], "frequency_unit": "MANIFESTATION"},
    "support": {"mode": "PERSISTENT", "scope": "ARC", "phases": ["SUSTAIN"], "frequency_unit": "INSTANCE"},
    "staged": {"mode": "PHASED", "scope": "ARC", "phases": ["SETUP", "DEVELOPMENT", "PAYOFF"], "frequency_unit": "INSTANCE"},
}

WORKING_CRAFT_POLICY = {"version": "working-craft-delivery.v2", "use": "SELECTED_CONTINUATION_WITH_LOCATED_TRANSITIONS"}


def is_working_delivery(row: Mapping[str, Any]) -> bool:
    return (row.get("usage_basis") == "SELECTED_WORKING_DELIVERY" and row.get("effect_status") == "NOT_ASSESSED"
        and row.get("working_craft_policy") == WORKING_CRAFT_POLICY and row.get("formal_acceptance") == "NOT_GRANTED"
        and not row.get("acceptance_id") and not row.get("accepted_draft_asset_version_id")
        and all(row.get(key) for key in ("book_run_id", "selected_source_asset_version_id", "selected_source_content_hash",
            "target_text_hash", "working_snapshot_hash", "external_receipt_ids", "use_id"))
        and type(row.get("chapter")) is int and row["chapter"] > 0)


def working_instances(history: list[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for row in history:
        usage = row.get("usage") or {}
        identity = usage.get("instance_id")
        if not identity or usage.get("type_policy") != spec or not is_working_delivery(row):
            continue
        if identity not in result or (row["chapter"], row["use_id"]) > (result[identity]["chapter"], result[identity]["use_id"]):
            result[identity] = row
    return result


def working_phase_observation(history, delivery):
    matches = [row for row in history if row.get("usage_basis") == "SELECTED_WORKING_PROSE_REVIEW"
        and row.get("formal_acceptance") == "NOT_GRANTED" and not row.get("acceptance_id")
        and all(row.get(key) for key in ("review_asset_version_id", "review_content_hash", "evidence"))
        and row.get("evidence_class") in {"MODEL_SEMANTIC_REVIEW", "FIXTURE_SEMANTIC_REVIEW"}
        and row.get("phase_transition", {}).get("action") == delivery.get("usage", {}).get("transition", {}).get("action")
        and row.get("phase_transition", {}).get("phase") == delivery.get("usage", {}).get("phase")
        and all(row.get(key) == delivery.get(key) for key in ("chapter", "use_id", "book_run_id",
            "selected_source_asset_version_id", "selected_source_content_hash", "target_text_hash", "working_snapshot_hash",
            "knowledge_card_asset_version_id", "content_hash", "usage"))]
    return matches[0] if len(matches) == 1 else None


def working_usage_is_open(row, history):
    usage = row["usage"]
    if not usage_is_open(usage):
        return False
    if usage.get("transition", {}).get("action") == "ADVANCE":
        observed = working_phase_observation(history, row)
        return bool(observed and observed.get("phase_transition", {}).get("status") == "SUPPORTED")
    return True


def validate_usage_policy(policy: Mapping[str, Any]) -> None:
    types, assignments = policy["usage_types"], policy["mechanism_usage_types"]
    if not isinstance(types, Mapping) or not 1 <= len(types) <= 16 or not isinstance(assignments, Mapping) or len(assignments) > 256 or "event" not in types:
        raise KernelError("CRAFT_USAGE_POLICY_INVALID", "Usage types and mechanism assignments must be explicit and bounded")
    for name, spec in types.items():
        if (not isinstance(name, str) or not name or len(name) > 64 or not isinstance(spec, Mapping)
            or set(spec) != {"mode", "scope", "phases", "frequency_unit"} | ({"transition_policy"} if policy["schema_version"] in {"narrative-craft-budget.v4", "narrative-craft-budget.v5"} else set())
            or spec["mode"] not in {"EVENT", "PERSISTENT", "PHASED"}
            or spec["scope"] not in {"SCENE", "CHAPTER", "ARC", "BOOK"}
            or spec["frequency_unit"] != ("MANIFESTATION" if spec["mode"] == "EVENT" else "INSTANCE")):
            raise KernelError("CRAFT_USAGE_POLICY_INVALID", "Usage type mode, scope and frequency unit are inconsistent")
        if "transition_policy" in spec and spec["transition_policy"] != "accepted-phase-transitions.v1":
            raise KernelError("CRAFT_USAGE_POLICY_INVALID", "Phase transitions require an explicit supported contract")
        phases = spec["phases"]
        if (not isinstance(phases, list) or not 1 <= len(phases) <= 8
            or any(not isinstance(phase, str) or not phase or len(phase) > 64 for phase in phases)
            or len(set(phases)) != len(phases) or (len(phases) != 1 and spec["mode"] != "PHASED")):
            raise KernelError("CRAFT_USAGE_POLICY_INVALID", "Phases must be unique, bounded and ordered")
    if any(not isinstance(key, str) or not key or not isinstance(value, str) or value not in types for key, value in assignments.items()):
        raise KernelError("CRAFT_USAGE_POLICY_INVALID", "Mechanisms must reference a declared usage type")


def usage_type(policy: Mapping[str, Any], mechanism_id: str) -> tuple[str, Mapping[str, Any]]:
    identity = policy["mechanism_usage_types"].get(mechanism_id, "event")
    return identity, policy["usage_types"][identity]


def accepted_transition_status(row: Mapping[str, Any]) -> str:
    status = row.get("effect_status", "UNCERTAIN")
    if (row.get("usage") or {}).get("type_policy", {}).get("transition_policy"):
        observed = row.get("phase_transition") or {}
        if observed.get("status") == "UNCERTAIN" or not observed:
            return "UNCERTAIN"
        if observed.get("status") != "SUPPORTED":
            return "FAILED"
    return status


def usage_is_open(usage: Mapping[str, Any]) -> bool:
    spec = usage["type_policy"]
    if spec.get("transition_policy"):
        return spec["mode"] != "EVENT" and usage.get("transition", {}).get("action") != "END"
    return spec["mode"] == "PERSISTENT" or (spec["mode"] == "PHASED" and usage["phase"] != spec["phases"][-1])


def realized_instances(history: list[Mapping[str, Any]], spec: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    realized, uncertain = {}, {}
    for row in history:
        usage = row.get("usage") or {}
        identity = usage.get("instance_id")
        if not identity or usage.get("type_policy") != spec:
            continue
        order = (row["chapter"], row["use_id"])
        if accepted_transition_status(row) == "UNCERTAIN":
            uncertain[identity] = max(row["chapter"], uncertain.get(identity, 0))
        elif accepted_transition_status(row) == "ACHIEVED" and (identity not in realized or order > (realized[identity]["chapter"], realized[identity]["use_id"])):
            realized[identity] = row
    return {identity: row for identity, row in realized.items() if uncertain.get(identity, 0) < row["chapter"]}


def _scope_binding(request, use, spec, scope_context):
    if (not isinstance(scope_context, Mapping) or set(scope_context) != {"project_id", "book_id", "chapter_number", "arc_plan_version_ids"} | ({"scope_transitions"} if spec.get("transition_policy") else set())
        or not all(isinstance(scope_context[key], str) and scope_context[key] for key in ("project_id", "book_id"))
        or type(scope_context["chapter_number"]) is not int or scope_context["chapter_number"] < 1
        or not isinstance(scope_context["arc_plan_version_ids"], list)
        or any(not isinstance(value, str) or not value for value in scope_context["arc_plan_version_ids"])):
        raise KernelError("CRAFT_USAGE_SCOPE_UNAVAILABLE", "Typed use requires the authoritative Book, Chapter and frozen Arc scope")
    allowed = {"SCENE": [use["scene_id"]], "CHAPTER": ["chapter:" + str(scope_context["chapter_number"])],
               "ARC": scope_context["arc_plan_version_ids"], "BOOK": [scope_context["book_id"]]}[spec["scope"]]
    if request["scope_id"] not in allowed:
        raise KernelError("CRAFT_USAGE_SCOPE_DRIFT", "Usage scope is outside the frozen planning inputs")
    return {"project_id": scope_context["project_id"], "book_id": scope_context["book_id"],
            "scope": spec["scope"], "scope_id": request["scope_id"],
            **({"chapter_number": scope_context["chapter_number"]} if spec["scope"] in {"SCENE", "CHAPTER"} else {})}


def bind_usage(*, site: Mapping[str, Any], use: Mapping[str, Any], card: Mapping[str, Any], policy: Mapping[str, Any], scope_context: Mapping[str, Any]) -> dict[str, Any]:
    request = site.get("craft_usage")
    explicit = policy["schema_version"] in {"narrative-craft-budget.v4", "narrative-craft-budget.v5"}
    working_enabled = policy["schema_version"] == "narrative-craft-budget.v5"
    fields = {"instance_id", "phase", "predecessor_use_id", "scope_id"}
    if not isinstance(request, Mapping) or set(request) != fields | ({"transition"} if explicit else set()) or any(not isinstance(request[key], str) or len(request[key]) > 256 for key in fields):
        raise KernelError("CRAFT_USAGE_INVALID", "Usage requires an exact instance, phase, scope and accepted predecessor")
    type_id, spec = usage_type(policy, use["mechanism_id"])
    if not request["scope_id"] or request["phase"] not in spec["phases"]:
        raise KernelError("CRAFT_USAGE_INVALID", "Usage scope and phase must match the frozen policy")
    binding = _scope_binding(request, use, spec, scope_context)
    transition = request.get("transition")
    if explicit and (not isinstance(transition, Mapping) or set(transition) != {"action", "condition", "progress"}
        or transition["action"] not in {"START", "CONTINUE", "ADVANCE", "DEFER", "END"}
        or any(not isinstance(transition[key], str) or not transition[key].strip() or len(transition[key]) > 512 for key in ("condition", "progress"))):
        raise KernelError("CRAFT_PHASE_TRANSITION_INVALID", "Explicit phase action requires a bounded condition and proposed in-phase progress")
    previous = None
    working_previous = None
    scope_transition = None
    budget = card.get("craft_assessment", {}).get("budget_assessment", {})
    history = budget.get("accepted_usage_history", budget.get("recent_usage", []))
    if request["instance_id"]:
        latest = realized_instances(history, spec).get(request["instance_id"])
        working_history = budget.get("working_usage_history", []) if working_enabled else []
        latest_working = working_instances(working_history, spec).get(request["instance_id"])
        if latest and latest_working and (latest_working["chapter"], latest_working["use_id"]) > (latest["chapter"], latest["use_id"]):
            latest = None
        if latest:
            prior = latest["usage"]
            scope_matches = prior["scope_id"] == request["scope_id"] and prior.get("scope_binding") == binding
            if explicit and not scope_matches:
                scope_transition = approved_scope_transition(scope_context, prior=prior, use=use, latest=latest, binding=binding)
                scope_matches = scope_transition is not None
            if (latest["use_id"] == request["predecessor_use_id"] and latest.get("effect_status") == "ACHIEVED"
                and latest.get("usage_basis") == "ACCEPTED_PROSE_REVIEW" and latest.get("acceptance_id")
                and latest.get("accepted_draft_asset_version_id") and latest.get("review_asset_version_id")
                and latest.get("target_text_hash") and latest.get("evidence")
                and latest["knowledge_card_asset_version_id"] == use["knowledge_card_asset_version_id"]
                and latest["content_hash"] == use["content_hash"]
                and prior["type_id"] == type_id and scope_matches and prior["type_policy"] == spec and spec["mode"] != "EVENT"):
                expected = spec["phases"].index(prior["phase"]) + (1 if spec["mode"] == "PHASED" else 0)
                legal = expected < len(spec["phases"]) and request["phase"] == spec["phases"][expected]
                if explicit:
                    expected = spec["phases"].index(prior["phase"]) + (1 if transition["action"] == "ADVANCE" else 0)
                    legal = (usage_is_open(prior) and transition["action"] != "START"
                             and (transition["action"] != "ADVANCE" or spec["mode"] == "PHASED")
                             and expected < len(spec["phases"]) and request["phase"] == spec["phases"][expected])
                if legal:
                    previous = {key: deepcopy(latest[key]) for key in (
                        "chapter", "use_id", "effect_status", "usage_basis", "acceptance_id", "accepted_draft_asset_version_id",
                        "review_asset_version_id", "target_text_hash", "evidence", "knowledge_card_asset_version_id", "content_hash")}
                    previous["usage"] = {key: deepcopy(prior[key]) for key in ("instance_id", "type_id", "scope_id", "scope_binding", "type_policy", "phase")}
                    if explicit:
                        previous["usage"]["transition"] = deepcopy(prior["transition"])
                        previous["phase_transition"] = deepcopy(latest["phase_transition"])
                        if latest.get("book_run_id"):
                            previous["book_run_id"] = latest["book_run_id"]

        if previous is None and working_enabled:
            latest = latest_working
            if latest:
                prior = latest["usage"]
                observed = working_phase_observation(working_history, latest)
                expected = spec["phases"].index(prior["phase"]) + int(transition["action"] == "ADVANCE")
                supported = observed and observed.get("phase_transition", {}).get("status") == "SUPPORTED"
                if (latest["use_id"] == request["predecessor_use_id"] and spec["mode"] != "EVENT"
                    and (latest["knowledge_card_asset_version_id"], latest["content_hash"]) == (use["knowledge_card_asset_version_id"], use["content_hash"])
                    and prior["type_id"] == type_id and prior["scope_id"] == request["scope_id"]
                    and prior.get("scope_binding") == binding and working_usage_is_open(latest, working_history)
                    and transition["action"] in {"CONTINUE", "DEFER", "ADVANCE", "END"}
                    and (transition["action"] != "ADVANCE" or spec["mode"] == "PHASED")
                    and expected < len(spec["phases"]) and request["phase"] == spec["phases"][expected]
                    and (transition["action"] not in {"ADVANCE", "END"} or supported)):
                    working_previous = {key: deepcopy(latest[key]) for key in ("chapter", "use_id", "effect_status", "usage_basis",
                        "book_run_id", "selected_source_asset_version_id", "selected_source_content_hash", "target_text_hash",
                        "working_snapshot_hash", "external_receipt_ids", "knowledge_card_asset_version_id", "content_hash",
                        "working_craft_policy", "formal_acceptance", "evidence_ceiling")}
                    working_previous["usage"] = {key: deepcopy(prior[key]) for key in ("instance_id", "type_id", "scope_id", "scope_binding", "type_policy", "phase", "transition")}
                    working_previous["realized_observation"] = deepcopy(observed)
                    if observed:
                        working_previous["realized_observation"]["usage"] = deepcopy(working_previous["usage"])
        if previous is None and working_previous is None:
            message = ("Working continuation requires this exact Card, selected source, latest instance and scope; advancement or closure additionally requires located native phase Review support"
                if working_enabled else "Continuation requires the latest successful accepted phase of this exact Card, instance, scope and policy; truncated or uncertain history cannot prove progression")
            raise KernelError("CRAFT_PHASE_PREDECESSOR_UNAVAILABLE", message)
    elif request["predecessor_use_id"] or request["phase"] != spec["phases"][0] or (explicit and transition["action"] != "START"):
        raise KernelError("CRAFT_PHASE_PREDECESSOR_UNAVAILABLE", "A new usage instance starts at its declared first phase")
    budget = card.get("craft_assessment", {}).get("budget_assessment", {})
    working_frequency = budget.get("working_frequency", 0) if working_enabled else 0
    if previous is None and working_previous is None and (budget.get("in_cooldown") or budget.get("frequency", 0) + working_frequency >= policy["max_frequency_in_window"]):
        raise KernelError("CRAFT_USAGE_FREQUENCY_EXCEEDED", "A continuation allowance cannot authorize a new usage instance")
    return {"type_id": type_id, "type_policy": deepcopy(dict(spec)), "instance_id": request["instance_id"] or "craft-instance:" + use["use_id"].split(":")[-1],
            "scope_id": request["scope_id"], "scope_binding": binding, "scope_context": deepcopy(dict(scope_context)),
            "budget_snapshot": {"frequency": budget.get("frequency", 0), "in_cooldown": budget.get("in_cooldown", False), **({"working_frequency": working_frequency} if working_enabled else {})},
            "phase": request["phase"], "status": "PLANNED", "accepted_predecessor": previous,
            **({"working_predecessor": working_previous} if working_enabled else {}),
            **({"transition": deepcopy(dict(transition)), "scope_transition": scope_transition} if explicit else {})}


def approved_scope_transition(scope_context, *, prior, use, latest, binding):
    transitions = scope_context.get("scope_transitions", [])
    if not isinstance(transitions, list) or len(transitions) > 256:
        raise KernelError("CRAFT_SCOPE_TRANSITION_INVALID", "Approved scope transitions must be bounded")
    for transition in transitions:
        if (transition.get("instance_id") == prior["instance_id"]
            and transition.get("from_scope_id") == prior["scope_id"]
            and transition.get("to_scope_id") == binding["scope_id"]
            and transition.get("knowledge_card_asset_version_id") == use["knowledge_card_asset_version_id"]
            and transition.get("content_hash") == use["content_hash"]
            and transition.get("predecessor_use_id") == latest["use_id"]
            and transition.get("acceptance_id") == latest["acceptance_id"]
            and transition.get("action") in {"INHERIT", "REBIND"}
            and transition.get("project_id") == binding["project_id"] and transition.get("book_id") == binding["book_id"]
            and transition.get("proposal_id") and transition.get("decision_asset_version_id")
            and transition.get("decision_content_hash") and transition.get("activation_operation_id")
            and transition.get("reason") and prior["scope_binding"]["project_id"] == binding["project_id"]
            and prior["scope_binding"]["book_id"] == binding["book_id"]
            and prior["scope_binding"]["scope"] == binding["scope"] == "ARC"):
            return deepcopy(transition)
    return None


def validate_usage_occupancy(uses, policy):
    working_enabled = policy["schema_version"] == "narrative-craft-budget.v5"
    if policy["schema_version"] in {"narrative-craft-budget.v4", "narrative-craft-budget.v5"}:
        transitions = {}
        for use in uses:
            usage = use["usage"]
            identity = usage["instance_id"]
            transition = (usage["phase"], usage["transition"]["action"], (usage["accepted_predecessor"] or usage.get("working_predecessor") or {}).get("use_id"))
            if identity in transitions and transitions[identity] != transition:
                raise KernelError("CRAFT_PHASE_OCCUPANCY_CONFLICT", "One plan cannot propose competing stage dispositions for the same stable instance")
            transitions[identity] = transition
    groups = {}
    for use in uses:
        groups.setdefault(use["mechanism_id"], []).append(use)
    for group in groups.values():
        snapshots = [use["usage"]["budget_snapshot"] for use in group]
        if any(snapshot != snapshots[0] for snapshot in snapshots):
            raise KernelError("CRAFT_USAGE_BUDGET_DRIFT", "One mechanism must retain a consistent accepted usage budget")
        snapshot = snapshots[0]
        if (set(snapshot) != {"frequency", "in_cooldown"} | ({"working_frequency"} if working_enabled else set()) or type(snapshot["frequency"]) is not int
            or snapshot["frequency"] < 0 or type(snapshot["in_cooldown"]) is not bool
            or working_enabled and (type(snapshot["working_frequency"]) is not int or snapshot["working_frequency"] < 0)):
            raise KernelError("CRAFT_USAGE_BUDGET_DRIFT", "Usage budget must retain exact accepted frequency and cooldown")
        new = {use["usage"]["instance_id"] for use in group if use["usage"]["accepted_predecessor"] is None and not use["usage"].get("working_predecessor")}
        if new and (snapshot["in_cooldown"] or snapshot["frequency"] + snapshot.get("working_frequency", 0) + len(new) > policy["max_frequency_in_window"]):
            raise KernelError("CRAFT_USAGE_FREQUENCY_EXCEEDED", "The whole plan exceeds the accepted-history plus new-instance allowance")


def validate_frozen_usage(use: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    usage = use.get("usage")
    working_enabled = policy["schema_version"] == "narrative-craft-budget.v5"
    if not isinstance(usage, Mapping) or set(usage) != {"type_id", "type_policy", "instance_id", "scope_id", "scope_binding", "scope_context", "budget_snapshot", "phase", "status", "accepted_predecessor"} | ({"transition", "scope_transition"} if policy["schema_version"] in {"narrative-craft-budget.v4", "narrative-craft-budget.v5"} else set()) | ({"working_predecessor"} if working_enabled else set()) or usage.get("status") != "PLANNED":
        raise KernelError("CRAFT_USAGE_INVALID", "Frozen use requires the planned usage and accepted predecessor evidence")
    previous = usage["accepted_predecessor"]
    card = {"craft_assessment": {"budget_assessment": {**usage["budget_snapshot"], "recent_usage": [previous] if previous else []}}}
    if working_enabled:
        predecessor = usage["working_predecessor"]
        observation = predecessor.get("realized_observation") if predecessor else None
        card["craft_assessment"]["budget_assessment"]["working_usage_history"] = ([predecessor] if predecessor else []) + ([observation] if observation else [])
    rebound = bind_usage(site=use["planning_use_site"], use=use, card=card, policy=policy, scope_context=usage["scope_context"])
    if usage != rebound:
        raise KernelError("CRAFT_USAGE_DRIFT", "Frozen usage differs from its exact planning site, policy or accepted predecessor")
