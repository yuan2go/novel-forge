from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import NarrativeStateKind, StoryTime
from novel_forge.modules.narrative_state.reality import narrative_hash


class RequirementOperator(StrEnum):
    EQUALS = "EQUALS"
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"
    EXISTS = "EXISTS"


def require_contract_fields(
    value: Mapping[str, Any], *, required: set[str], optional: set[str] = frozenset()
) -> None:
    if (
        not isinstance(value, Mapping)
        or not required.issubset(value)
        or set(value) - required - optional
    ):
        raise KernelError(
            "CAUSAL_CONTRACT_INVALID",
            "causal contract fields must match the declared version",
        )


def require_text_fields(value: Mapping[str, Any], fields: tuple[str, ...]) -> None:
    if any(
        not isinstance(value.get(key), str) or not value[key].strip() for key in fields
    ):
        raise KernelError(
            "CAUSAL_CONTRACT_INVALID",
            "causal identities and text must be nonempty strings",
        )


@dataclass(frozen=True, slots=True)
class CausalRequirement:
    requirement_id: str
    state_kind: NarrativeStateKind
    entity_key: str
    field: str
    operator: RequirementOperator
    value: str | int | float | bool | None

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.entity_key or not self.field:
            raise KernelError(
                "CAUSAL_REQUIREMENT_INVALID",
                "causal predicates need an identity, typed state and field",
            )
        if self.operator in {
            RequirementOperator.AT_LEAST,
            RequirementOperator.AT_MOST,
        } and (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not isfinite(self.value)
        ):
            raise KernelError(
                "CAUSAL_QUANTITY_INVALID",
                "quantitative preconditions require finite numeric values",
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CausalRequirement:
        require_contract_fields(
            value,
            required={
                "requirement_id",
                "state_kind",
                "entity_key",
                "field",
                "operator",
            },
            optional={"value"},
        )
        require_text_fields(
            value, ("requirement_id", "state_kind", "entity_key", "field", "operator")
        )
        if (
            value["state_kind"] not in set(NarrativeStateKind)
            or value["operator"] not in set(RequirementOperator)
            or not isinstance(value.get("value"), (str, int, float, bool, type(None)))
            or (
                value["operator"] != RequirementOperator.EXISTS and "value" not in value
            )
        ):
            raise KernelError(
                "CAUSAL_REQUIREMENT_INVALID",
                "predicate kind, operator and scalar value must be typed",
            )
        return cls(
            str(value["requirement_id"]),
            NarrativeStateKind(value["state_kind"]),
            str(value["entity_key"]),
            str(value["field"]),
            RequirementOperator(value["operator"]),
            value.get("value"),
        )


def state_index(reality: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for kind, entries in (reality.get("current_state") or {}).items():
        NarrativeStateKind(kind)
        for entry in entries:
            key = str(
                entry.get("entity_key")
                or (entry.get("identity") or {}).get("entity_key")
                or ""
            )
            if not key or (kind, key) in result:
                raise KernelError(
                    "WORLD_IDENTITY_AMBIGUOUS",
                    "World Dynamics requires unique canonical state identities",
                )
            result[(kind, key)] = dict(entry)
    return result


def evaluate_requirement(
    requirement: CausalRequirement, state: Mapping[tuple[str, str], Mapping[str, Any]]
) -> dict[str, Any]:
    entry = state.get((requirement.state_kind.value, requirement.entity_key))
    payload = dict((entry or {}).get("state") or {})
    actual = payload.get(requirement.field)
    if requirement.operator == RequirementOperator.EXISTS:
        satisfied = requirement.field in payload
    elif requirement.operator == RequirementOperator.EQUALS:
        satisfied = (
            requirement.field in payload
            and type(actual) is type(requirement.value)
            and actual == requirement.value
        )
    else:
        numeric = (
            not isinstance(actual, bool)
            and isinstance(actual, (int, float))
            and isfinite(actual)
        )
        satisfied = bool(
            numeric
            and (
                actual >= requirement.value
                if requirement.operator == RequirementOperator.AT_LEAST
                else actual <= requirement.value
            )
        )
    return {
        **asdict(requirement),
        "satisfied": satisfied,
        "observed_value": actual,
        "source_event_id": str((entry or {}).get("source_event_id") or ""),
    }


@dataclass(frozen=True, slots=True)
class WorldTransition:
    transition_id: str
    actor_id: str
    camera: str
    story_time: StoryTime
    action: str
    state_kind: NarrativeStateKind
    entity_key: str
    changes: Mapping[str, Any]
    requirements: tuple[CausalRequirement, ...]
    cause_refs: tuple[str, ...]
    epistemic_basis: tuple[CausalRequirement, ...] = ()

    def __post_init__(self) -> None:
        if (
            not all((self.transition_id, self.actor_id, self.action, self.entity_key))
            or self.camera not in {"ON_CAMERA", "OFF_CAMERA", "UNDERCURRENT"}
            or not isinstance(self.story_time, StoryTime)
            or self.story_time.precision == "UNSPECIFIED"
            or not self.changes
            or not self.cause_refs
            or len(set(self.cause_refs)) != len(self.cause_refs)
            or len({r.requirement_id for r in self.requirements})
            != len(self.requirements)
        ):
            raise KernelError(
                "WORLD_TRANSITION_INVALID",
                "candidate transitions need frozen cause, time, actor and unique requirements",
            )
        if any(
            r.state_kind
            not in {
                NarrativeStateKind.CHARACTER_KNOWLEDGE,
                NarrativeStateKind.CHARACTER_BELIEF,
            }
            for r in self.epistemic_basis
        ):
            raise KernelError(
                "WORLD_EPISTEMIC_BASIS_INVALID",
                "actor decisions must use character knowledge or belief",
            )
        if any(
            r.state_kind
            in {
                NarrativeStateKind.READER_KNOWLEDGE,
                NarrativeStateKind.DISCLOSURE_EVENT,
                NarrativeStateKind.READER_PROMISE,
                NarrativeStateKind.NARRATIVE_OBLIGATION,
            }
            for r in self.requirements
        ):
            raise KernelError(
                "WORLD_READER_STATE_NOT_CAUSAL_AUTHORITY",
                "reader knowledge and narrative obligations cannot satisfy objective world conditions",
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorldTransition:
        require_contract_fields(
            value,
            required={
                "transition_id",
                "actor_id",
                "camera",
                "story_time",
                "action",
                "state_kind",
                "entity_key",
                "changes",
                "requirements",
                "cause_refs",
            },
            optional={"epistemic_basis"},
        )
        require_text_fields(
            value,
            (
                "transition_id",
                "actor_id",
                "camera",
                "action",
                "state_kind",
                "entity_key",
            ),
        )
        if (
            value["state_kind"] not in set(NarrativeStateKind)
            or not isinstance(value["story_time"], dict)
            or not isinstance(value["changes"], dict)
            or any(
                not isinstance(value.get(key, []), list)
                for key in ("requirements", "cause_refs", "epistemic_basis")
            )
            or any(not isinstance(ref, str) or not ref for ref in value["cause_refs"])
        ):
            raise KernelError(
                "WORLD_TRANSITION_INVALID",
                "world transition fields must match their typed contracts",
            )
        return cls(
            str(value["transition_id"]),
            str(value["actor_id"]),
            str(value["camera"]),
            StoryTime.from_dict(dict(value["story_time"])),
            str(value["action"]),
            NarrativeStateKind(value["state_kind"]),
            str(value["entity_key"]),
            dict(value["changes"]),
            tuple(
                CausalRequirement.from_mapping(r) for r in value.get("requirements", [])
            ),
            tuple(str(ref) for ref in value["cause_refs"]),
            tuple(
                CausalRequirement.from_mapping(r)
                for r in value.get("epistemic_basis", [])
            ),
        )


def validate_world_transition(
    transition: WorldTransition, reality: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    state = state_index(reality)
    old = dict(
        (state.get((transition.state_kind.value, transition.entity_key)) or {}).get(
            "state"
        )
        or {}
    )
    changes = dict(transition.changes)
    post_state = dict(state)
    post_state[(transition.state_kind.value, transition.entity_key)] = {
        "state": {**old, **changes}
    }
    for rule_source in reality.get("world_rule_constraints", []):
        from .foundation import WorldRule

        rule = WorldRule.from_mapping(rule_source["rule"])
        if (
            rule.enforcement == "SOFT_CAUSAL"
            or transition.state_kind.value not in rule.applicability
        ):
            continue
        if (
            rule.predicate is None
            or not evaluate_requirement(rule.predicate, post_state)["satisfied"]
        ):
            raise KernelError(
                "WORLD_COMPILED_RULE_VIOLATION",
                f"world transition violates compiled rule {rule.rule_id} from {rule_source['asset_version_id']}",
            )
    for (kind, _), entry in state.items():
        payload = dict(entry.get("state") or {})
        if (
            kind == "character_state"
            and payload.get("character_id") == transition.actor_id
            and str(payload.get("life_status") or payload.get("status") or "").upper()
            == "DEAD"
        ):
            raise KernelError(
                "WORLD_DEAD_ACTOR", "a canonically dead actor cannot perform an action"
            )
    if (
        any(
            kind == "character_state"
            and entry.get("state", {}).get("character_id") == transition.actor_id
            for (kind, _), entry in state.items()
        )
        and not transition.epistemic_basis
    ):
        raise KernelError(
            "WORLD_CHARACTER_DECISION_BASIS_REQUIRED",
            "a known character's action requires its own accepted knowledge or belief basis",
        )
    previous_times = [
        StoryTime.from_dict(event["story_time"])
        for event in reality.get("events", [])
        if isinstance(event.get("story_time"), dict)
        and event["story_time"].get("timeline_id") == transition.story_time.timeline_id
        and "world_transition" in (event.get("mutation") or {}).get("payload", {})
    ]
    latest_ordinal = max(
        (
            time.end_ordinal
            for time in previous_times
            if time.precision != "UNSPECIFIED"
        ),
        default=0,
    )
    latest_ordinal = max(
        latest_ordinal,
        int(reality.get("world_clock", {}).get(transition.story_time.timeline_id, 0)),
    )
    if transition.story_time.start_ordinal < latest_ordinal:
        raise KernelError(
            "WORLD_TIME_REGRESSION",
            "world transitions cannot precede the accepted frontier on their timeline",
        )
    if (
        (old.get("unique") is True or changes.get("unique") is True)
        and isinstance(changes.get("location_ids"), list)
        and len(set(changes["location_ids"])) != 1
    ):
        raise KernelError(
            "WORLD_UNIQUE_ITEM_DUPLICATED", "a unique item has one current location"
        )
    if (
        old.get("location_id")
        and changes.get("location_id") != old.get("location_id")
        and "location_id" in changes
    ):
        distance = changes.get("travel_distance")
        speed = old.get("max_travel_speed")
        if not all(
            isinstance(n, (int, float))
            and not isinstance(n, bool)
            and isfinite(n)
            and n >= 0
            for n in (distance, speed)
        ):
            raise KernelError(
                "WORLD_TRAVEL_EVIDENCE_REQUIRED",
                "a location change requires canonical speed and measured distance",
            )
        if transition.story_time.precision != "EXACT":
            raise KernelError(
                "WORLD_TRAVEL_TIME_UNCERTAIN",
                "quantitative travel requires exact elapsed story time",
            )
        if distance > speed * (transition.story_time.start_ordinal - latest_ordinal):
            raise KernelError(
                "WORLD_TRAVEL_IMPOSSIBLE",
                "travel distance exceeds elapsed time and canonical speed",
            )
    for field in (
        "balance",
        "balance_after",
        "inventory",
        "cooldown",
        "recovery_remaining",
    ):
        if field in changes and (
            isinstance(changes[field], bool)
            or not isinstance(changes[field], (int, float))
            or not isfinite(changes[field])
            or changes[field] < 0
        ):
            raise KernelError(
                "WORLD_QUANTITY_INVALID",
                "resource and temporal quantities must remain finite and nonnegative",
            )
    if "power_level" in changes and changes["power_level"] != old.get("power_level"):
        if changes["power_level"] not in old.get("allowed_power_transitions", []):
            raise KernelError(
                "WORLD_POWER_TRANSITION_FORBIDDEN",
                "power transitions require an explicit canonical rule",
            )
    for requirement in transition.epistemic_basis:
        entry = state.get((requirement.state_kind.value, requirement.entity_key))
        if (entry or {}).get("state", {}).get("character_id") != transition.actor_id:
            raise KernelError(
                "WORLD_EPISTEMIC_ACTOR_MISMATCH",
                "one actor cannot borrow another actor's knowledge",
            )
    return tuple(
        evaluate_requirement(r, state)
        for r in (*transition.requirements, *transition.epistemic_basis)
    )


def candidate_transition(
    transition: WorldTransition, reality: Mapping[str, Any]
) -> dict[str, Any]:
    if not str(reality.get("revision_id") or "").startswith("reality:sha256:"):
        raise KernelError(
            "WORLD_REALITY_REQUIRED",
            "World Dynamics requires an exact accepted Reality revision",
        )
    known_causes = {
        str(entry.get("source_event_id") or "")
        for entry in state_index(reality).values()
    }
    known_causes.update(
        str(event.get("event_id") or "") for event in reality.get("events", [])
    )
    known_causes.discard("")
    if not set(transition.cause_refs).issubset(known_causes):
        raise KernelError(
            "WORLD_CAUSAL_SOURCE_UNKNOWN",
            "causal support must resolve to events in the accepted Reality",
        )
    receipts = validate_world_transition(transition, reality)
    return {
        "contract_version": "world-transition-candidate.v1",
        "reality_revision_id": reality["revision_id"],
        "transition": asdict(transition),
        "requirements": list(receipts),
        "eligible": all(receipt["satisfied"] for receipt in receipts),
        "candidate_id": "candidate-future:"
        + narrative_hash(
            {
                "transition": asdict(transition),
                "reality_revision_id": reality["revision_id"],
            }
        ),
        "authority": "PLANNING_CANDIDATE",
        "fact_mutation_allowed": False,
    }
