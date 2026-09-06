from copy import deepcopy
import json
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.modules.worldbuilding.dynamics import WorldTransition


def scheduled_world_events(binding: Mapping[str, Any]) -> list[dict[str, Any]]:
    action = binding["action"]
    if action.get("contract_version") not in {
        "world-production-action.v1",
        "world-production-action.v2",
    }:
        raise KernelError(
            "WORLD_ACTION_CONTRACT_INVALID", "unsupported frozen world action"
        )
    plan = action["world_plan"]
    if plan["disposition"] == "ELIGIBLE":
        selected = [
            item
            for item in plan["candidate_futures"]
            if item.get("candidate_id") == plan["selected_candidate_id"]
            and item.get("eligible")
        ]
        if len(selected) != 1:
            raise KernelError(
                "WORLD_ACTION_SELECTION_INVALID",
                "exactly one eligible selected candidate is required",
            )
        return [deepcopy(selected[0]["transition"])]
    if plan["disposition"] == "PREPARATION_REQUIRED":
        return [
            deepcopy(step["transition"])
            for step in plan["preparation_schedule"]
            if step["chapter_number"] == plan["chapter_number"]
        ]
    if plan["disposition"] not in {"NO_OP", "DEFER"}:
        raise KernelError(
            "WORLD_ACTION_BLOCKED", "blocked world search cannot enter production"
        )
    return []


def public_world_direction(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "world-planning-direction.v1",
        "action_asset_version_id": binding["asset_version_id"],
        "action_content_hash": binding["content_hash"],
        "disposition": binding["action"]["world_plan"]["disposition"],
        "on_camera_events": [
            {
                key: deepcopy(event[key])
                for key in (
                    "transition_id",
                    "actor_id",
                    "camera",
                    "story_time",
                    "state_kind",
                    "entity_key",
                    "changes",
                )
            }
            for event in scheduled_world_events(binding)
            if event["camera"] == "ON_CAMERA"
        ],
        "disclosures": deepcopy(
            binding["action"]["world_plan"].get("disclosure_projection") or []
        ),
        "fact_mutation_allowed": False,
    }


def bind_world_execution(
    binding: Mapping[str, Any], scenes: list[dict[str, Any]]
) -> dict[str, Any]:
    public = public_world_direction(binding)
    selected = {
        raw["transition_id"]: raw
        for raw in scheduled_world_events(binding)
        if raw["camera"] == "ON_CAMERA"
    }
    assigned = {name: [] for name in selected}
    for scene in scenes:
        names = scene.get("world_event_ids", [])
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) or name not in selected for name in names)
            or len(names) != len(set(names))
        ):
            raise KernelError(
                "WORLD_SCENE_EVENT_REFERENCE_INVALID",
                "Scene assignments must reference distinct selected local event identities",
            )
        for name in names:
            assigned[name].append(scene["scene_id"])
    if any(len(ids) != 1 for ids in assigned.values()):
        raise KernelError(
            "WORLD_SCENE_EVENT_COVERAGE_INVALID",
            "each scheduled on-camera event requires exactly one Scene owner",
        )
    for event in public["on_camera_events"]:
        event["scene_id"] = assigned[event["transition_id"]][0]
        event["cause_refs"] = list(selected[event["transition_id"]]["cause_refs"])
    return {
        **public,
        "contract_version": "world-scene-execution.v1",
        "observation_contract": "Observe only effects evidenced in the final prose within the assigned Scene. Preserve exact identity, observed scalar changes, story_time and causal_batch local_id=transition_id with depends_on=cause_refs. Absent planned effects remain unexecuted; never invent fact_origin or preparation_lineage.",
    }


def without_private_world(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: without_private_world(item)
            for key, item in value.items()
            if key != "world_preparation"
        }
    if isinstance(value, (list, tuple)):
        return [without_private_world(item) for item in value]
    return deepcopy(value)


def require_background_payload(
    *, expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> None:
    from novel_forge.modules.narrative_state.contracts import narrative_event_payload

    normalized = narrative_event_payload(dict(expected))
    comparable = {
        key: value for key, value in actual.items() if key != "approval_resolution"
    }
    if comparable != normalized:
        raise KernelError(
            "WORLD_ACCEPTANCE_SOURCE_DRIFT",
            "accepted background payload must equal the complete frozen decision",
        )


def attach_background_proposals(
    *, extraction: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    from .domain import HIGH_IMPACT_CHANGE_TYPES, SEMANTIC_CHANGE_FIELDS

    from .disclosure import bind_disclosure_policy

    result = bind_disclosure_policy(extraction, binding)
    for field in SEMANTIC_CHANGE_FIELDS:
        if any(
            "fact_origin" in item or "preparation_lineage" in item
            for item in result.get(field, [])
        ):
            raise KernelError(
                "WORLD_FACT_ORIGIN_FORGED",
                "Observer cannot manufacture a governed background origin",
            )
    if not binding:
        return result
    action = binding["action"]
    if int(action["world_plan"]["chapter_number"]) != int(extraction["chapter"]):
        raise KernelError(
            "WORLD_ACTION_CHAPTER_DRIFT",
            "background selection belongs to another chapter",
        )
    fields = {kind: field for field, kind in SEMANTIC_CHANGE_FIELDS.items()}
    for raw in scheduled_world_events(binding):
        transition = WorldTransition.from_mapping(raw)
        if transition.camera == "ON_CAMERA":
            if action["contract_version"] == "world-production-action.v2":
                expected_lineage = preparation_lineage(
                    binding, transition.transition_id
                )
                for item in result.get(fields.get(transition.state_kind.value, ""), []):
                    if (item.get("causal_batch") or {}).get(
                        "local_id"
                    ) != transition.transition_id:
                        continue
                    identity = dict(
                        part.split("=", 1) for part in transition.entity_key.split("|")
                    )
                    if any(
                        item.get(key) != value
                        for key, value in {**identity, **transition.changes}.items()
                    ):
                        raise KernelError(
                            "WORLD_PREPARATION_OBSERVED_EFFECT_MISMATCH",
                            "an observed preparation must match its exact scheduled identity and effects",
                        )
                    if item["causal_batch"].get("depends_on") != list(
                        transition.cause_refs
                    ):
                        raise KernelError(
                            "WORLD_PREPARATION_OBSERVED_CAUSE_MISMATCH",
                            "the observed local event must preserve the scheduled prerequisites",
                        )
                    item["preparation_lineage"] = expected_lineage
                    item["world_transition"] = {
                        "payload_json": json.dumps(
                            raw, sort_keys=True, separators=(",", ":")
                        )
                    }
            continue
        kind = transition.state_kind.value
        if kind in {
            "reader_knowledge",
            "character_knowledge",
            "character_belief",
            "disclosure_event",
        }:
            raise KernelError(
                "WORLD_BACKGROUND_KNOWLEDGE_FORBIDDEN",
                "background world selection cannot grant an audience knowledge",
            )
        if kind not in fields:
            raise KernelError(
                "WORLD_BACKGROUND_KIND_UNSUPPORTED",
                "background changes must use an existing Canon reconciliation kind",
            )
        identity = dict(part.split("=", 1) for part in transition.entity_key.split("|"))
        changes = dict(transition.changes)
        if any(
            key in changes and changes[key] != value for key, value in identity.items()
        ):
            raise KernelError(
                "WORLD_BACKGROUND_IDENTITY_MISMATCH",
                "world transition cannot replace its canonical identity",
            )
        major = (
            str(changes.get("impact_type") or "") in HIGH_IMPACT_CHANGE_TYPES
            or str(changes.get("life_status") or changes.get("status") or "").upper()
            in {"DEAD", "DESTROYED"}
            or any(
                key in changes
                for key in (
                    "identity_revelation",
                    "owner_id",
                    "rule",
                    "rule_definition",
                    "secret_disclosure",
                    "major_relationship_change",
                )
            )
            or kind == "world_rule"
        )
        origin = {
            "kind": "GOVERNED_BACKGROUND",
            "contract_version": "world-fact-origin.v1",
            "action_asset_version_id": binding["asset_version_id"],
            "action_content_hash": binding["content_hash"],
            "source": deepcopy(action["source"]),
            "generation": deepcopy(action["generation"]),
            "evaluation": deepcopy(action["evaluation"]),
            "transition_id": transition.transition_id,
            "transition_digest": narrative_hash(raw),
            "acceptance_policy": "book-canon-background.v1",
        }
        item = {
            **identity,
            **changes,
            "visibility": "HIDDEN",
            "fact_origin": origin,
            "world_transition": {
                "payload_json": json.dumps(raw, sort_keys=True, separators=(",", ":"))
            },
            "confidence": 1.0,
            "coverage": "GOVERNED_WORLD_DECISION",
            "approval_requirement": "REQUIRED" if major else "NONE",
            "entity_id": transition.actor_id,
            "story_time": transition.story_time.to_dict(),
            "causality": {
                "cause_refs": list(transition.cause_refs),
                "precondition_refs": [
                    r.requirement_id for r in transition.requirements
                ],
                "participant_ids": [transition.actor_id],
                "effect_kinds": ["STATE"],
            },
            "causal_batch": {
                "contract_version": "causal-batch-event.v1",
                "local_id": transition.transition_id,
                "depends_on": list(transition.cause_refs),
            },
        }
        if action["contract_version"] == "world-production-action.v2":
            item["preparation_lineage"] = preparation_lineage(
                binding, transition.transition_id
            )
        result.setdefault(fields[kind], []).append(item)
        if major:
            result.setdefault("approval_required_changes", []).append(
                {"change_field": fields[kind], "change": item}
            )
    if "frozen_source" in binding:
        from .causal_preparation import preparation_observations

        result.setdefault("obligation_changes", []).extend(
            preparation_observations(binding)
        )
    return result


def world_action_boundaries(binding: Mapping[str, Any]) -> tuple[str, ...]:
    plan = binding["action"]["world_plan"]
    proposed = attach_background_proposals(
        extraction={"chapter": plan["chapter_number"]}, binding=binding
    )
    selected = next(
        (
            item
            for item in plan["candidate_futures"]
            if item.get("candidate_id") == plan["selected_candidate_id"]
        ),
        {},
    )
    return (
        ("DIRECTOR", "MAJOR_DECISION")
        if proposed.get("approval_required_changes") or selected.get("risks")
        else ("DIRECTOR",)
    )


def preparation_lineage(
    binding: Mapping[str, Any], transition_id: str
) -> dict[str, str]:
    plan = binding["action"]["world_plan"]
    return {
        "contract_version": "world-preparation-lineage.v1",
        "origin_action_version_id": (plan.get("continuation_origin") or {}).get(
            "asset_version_id", binding["asset_version_id"]
        ),
        "path_id": plan["selected_path_id"],
        "transition_id": transition_id,
    }
