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
    background = reality.get("foundation_rule_background") or {}
    if background:
        if (background.get("contract_version") != "foundation-rule-background.v1"
            or background.get("character_knowledge_granted") is not False
            or background.get("accepted_history_mutation_allowed") is not False
            or not (background.get("source_binding") or {}).get("asset_version_id")):
            raise KernelError("WORLD_FOUNDATION_BACKGROUND_SOURCE_INVALID", "Require the explicit source-bound background projection")
        for field in background.get("field_bindings", []):
            if field.get("state_kind") != "world_rule":
                raise KernelError("WORLD_FOUNDATION_BACKGROUND_KIND_INVALID", "World-rule declarations cannot grant character state or knowledge")
            key = ("world_rule", field["entity_key"])
            prior = result.get(key) or {"entity_key": field["entity_key"], "source_event_id": "foundation:" + background["source_binding"]["asset_version_id"]}
            state = dict(prior.get("state") or {})
            state.setdefault(field["field"], field["value"])
            result[key] = {**prior, "state": state}
    working = reality.get("working_observation_context")
    if working is not None:
        if (not isinstance(working, Mapping)
            or working.get("contract_version") != "world-working-observations.v1"
            or working.get("authority") != "SELECTED_WORKING_EXPERIENCE_FOR_CANDIDATES"
            or working.get("semantic_support") != "NOT_VERIFIED"
            or working.get("accepted_history_mutation_allowed") is not False
            or working.get("character_knowledge_granted") is not False
            or working.get("accepted_through_chapter") != reality["chapter_number"]
            or type(working.get("target_chapter")) is not int
            or working["target_chapter"] <= reality["chapter_number"]
            or working.get("projection_hash") != narrative_hash({key: value for key, value in working.items() if key != "projection_hash"})):
            raise KernelError("WORLD_WORKING_OBSERVATION_INVALID", "Candidate experience must retain its source-bound non-Canon projection")
        causes = {row["source_event_id"] for row in working["causes"]}
        for entry in working["entries"]:
            key = (entry["state_kind"], entry["entity_key"])
            if (entry["state_kind"] not in {"character_knowledge", "character_belief"}
                or key in result or entry["source_event_id"] not in causes
                or entry["entity_key"] != entry["source_event_id"]
                or not reality["chapter_number"] < entry["source_chapter"] < working["target_chapter"]
                or entry["state"]["character_id"] not in reality["approved_character_ids"]
                or entry["state"].get("epistemic_status") != "UNREVIEWED_WORKING_OBSERVATION"
                or entry["state"].get("perspective") not in {"OBSERVED", "BELIEF", "HEARSAY"}):
                raise KernelError("WORLD_WORKING_OBSERVATION_INVALID", "Working experience cannot grant objective state or another character's knowledge")
            result[key] = dict(entry)
    return result


def candidate_chapter(reality: Mapping[str, Any]) -> int:
    working = reality.get("working_observation_context")
    if working is None:
        return reality["chapter_number"] + 1
    state_index(reality)
    return working["target_chapter"]


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

    @property
    def action_mode(self) -> str:
        return ""

    def __post_init__(self) -> None:
        if (
            not all((self.transition_id, self.actor_id, self.action, self.entity_key))
            or self.camera not in {"ON_CAMERA", "OFF_CAMERA", "UNDERCURRENT"}
            or not isinstance(self.story_time, StoryTime)
            or self.story_time.precision == "UNSPECIFIED"
            or not self.changes
            or not self.cause_refs
            or self.action_mode
            not in {"", "ROUTINE", "PERCEPTION", "INFORMATION_DEPENDENT"}
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

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not self.action_mode:
            result.pop("action_mode", None)
        return result

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
            optional={"epistemic_basis", "action_mode"},
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
        creator = WorldAgencyTransition if "action_mode" in value else cls
        changes = dict(value["changes"])
        if (
            value.get("action_mode") == "PERCEPTION"
            and value["state_kind"] == "character_knowledge"
        ):
            changes.setdefault("character_id", value["actor_id"])
            if (
                not (changes.get("fact_id") or changes.get("proposition_id"))
                and isinstance(changes.get("proposition"), str)
                and changes["proposition"].strip()
            ):
                changes["proposition_id"] = "observation:" + narrative_hash(
                    {
                        "actor_id": value["actor_id"],
                        "proposition": changes["proposition"],
                        "observation_source": changes.get("observation_source"),
                    }
                )
        return creator(
            str(value["transition_id"]),
            str(value["actor_id"]),
            str(value["camera"]),
            StoryTime.from_dict(dict(value["story_time"])),
            str(value["action"]),
            NarrativeStateKind(value["state_kind"]),
            str(value["entity_key"]),
            changes,
            tuple(
                CausalRequirement.from_mapping(r) for r in value.get("requirements", [])
            ),
            tuple(str(ref) for ref in value["cause_refs"]),
            tuple(
                CausalRequirement.from_mapping(r)
                for r in value.get("epistemic_basis", [])
            ),
            **({"action_mode": value["action_mode"]} if "action_mode" in value else {}),
        )


@dataclass(frozen=True, slots=True)
class WorldAgencyTransition(WorldTransition):
    action_mode: str = "INFORMATION_DEPENDENT"


def validate_world_state_rules(
    *,
    reality: Mapping[str, Any],
    state: Mapping[tuple[str, str], Mapping[str, Any]],
    affected_kinds: set[str],
) -> None:
    for rule_source in reality.get("world_rule_constraints", []):
        from .foundation import WorldRule

        rule = WorldRule.from_mapping(rule_source["rule"])
        if rule.enforcement in {
            "SOFT_CAUSAL",
            "MECHANISM",
        } or not affected_kinds.intersection(rule.applicability):
            continue
        if (
            rule.predicate is None
            or not evaluate_requirement(rule.predicate, state)["satisfied"]
        ):
            raise KernelError(
                "WORLD_COMPILED_RULE_VIOLATION",
                f"world transition violates compiled rule {rule.rule_id} from {rule_source['asset_version_id']}",
            )


def validate_world_transition(
    transition: WorldTransition, reality: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    state = state_index(reality)
    if "approved_entity_ids" in reality and transition.actor_id not in set(
        reality["approved_entity_ids"]
    ) | {
        entry["state"].get("character_id")
        for (kind, _), entry in state.items()
        if kind == "character_state"
    }:
        raise KernelError(
            "WORLD_ACTOR_UNKNOWN",
            "transition actors must resolve to approved Foundation or accepted character identities",
        )
    old = dict(
        (state.get((transition.state_kind.value, transition.entity_key)) or {}).get(
            "state"
        )
        or {}
    )
    changes = dict(transition.changes)
    if (
        reality.get("epistemic_contract") == "world-agency.v2"
        and not transition.action_mode
    ):
        raise KernelError(
            "WORLD_ACTION_MODE_REQUIRED",
            "classify ordinary agency, observation and information-dependent decisions explicitly",
        )
    from .mechanisms import require_world_mechanism

    mechanism = require_world_mechanism(transition, reality, state)
    post_state = dict(state)
    post_state[(transition.state_kind.value, transition.entity_key)] = {
        "state": {**old, **changes}
    }
    validate_world_state_rules(
        reality=reality, state=post_state, affected_kinds={transition.state_kind.value}
    )
    for (kind, _), entry in state.items():
        payload = dict(entry.get("state") or {})
        if (
            kind == "character_state"
            and payload.get("character_id") == transition.actor_id
            and str(payload.get("life_status") or payload.get("status") or "").upper()
            == "DEAD"
            and not (mechanism == "REVIVAL" and changes.get("life_status") == "ALIVE")
        ):
            raise KernelError(
                "WORLD_DEAD_ACTOR", "a canonically dead actor cannot perform an action"
            )
    if (
        (
            transition.actor_id in reality.get("approved_character_ids", [])
            or any(
                kind == "character_state"
                and entry.get("state", {}).get("character_id") == transition.actor_id
                for (kind, _), entry in state.items()
            )
        )
        and not transition.epistemic_basis
        and not (
            reality.get("epistemic_contract") == "world-agency.v2"
            and transition.action_mode in {"ROUTINE", "PERCEPTION"}
        )
    ):
        raise KernelError(
            "WORLD_CHARACTER_DECISION_BASIS_REQUIRED",
            "a known character's action requires its own accepted knowledge or belief basis",
        )
    if transition.action_mode in {"ROUTINE", "PERCEPTION"}:
        validate_initial_agency(transition, reality, state)
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
        and mechanism != "MULTIPRESENCE"
    ):
        raise KernelError(
            "WORLD_UNIQUE_ITEM_DUPLICATED", "a unique item has one current location"
        )
    if (
        old.get("location_id")
        and changes.get("location_id") != old.get("location_id")
        and "location_id" in changes
        and mechanism != "INSTANT_TRAVEL"
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
        departure_ordinal = latest_ordinal
        if reality.get("world_dynamics_contract") == "world-dynamics.v2":
            clock_key = f"{transition.state_kind.value}|{transition.entity_key}|{transition.story_time.timeline_id}"
            departure_ordinal = reality.get("entity_clocks", {}).get(clock_key)
            entry_time = (
                state.get((transition.state_kind.value, transition.entity_key)) or {}
            ).get("story_time")
            if isinstance(entry_time, Mapping):
                time = StoryTime.from_dict(dict(entry_time))
                if (
                    time.timeline_id == transition.story_time.timeline_id
                    and time.precision != "UNSPECIFIED"
                ):
                    departure_ordinal = max(departure_ordinal or 0, time.end_ordinal)
            if (
                not isinstance(departure_ordinal, int)
                or isinstance(departure_ordinal, bool)
                or departure_ordinal < 0
            ):
                raise KernelError(
                    "WORLD_ENTITY_TIME_REQUIRED",
                    "travel requires this entity's frozen location time",
                )
            if departure_ordinal > transition.story_time.start_ordinal:
                raise KernelError(
                    "WORLD_TIME_REGRESSION",
                    "travel cannot begin before this entity's preceding event",
                )
        if distance > speed * (transition.story_time.start_ordinal - departure_ordinal):
            raise KernelError(
                "WORLD_TRAVEL_IMPOSSIBLE",
                "travel distance exceeds elapsed time and canonical speed",
            )
    if (
        str(old.get("life_status") or "").upper() == "DEAD"
        and changes.get("life_status") == "ALIVE"
        and mechanism != "REVIVAL"
    ):
        raise KernelError(
            "WORLD_REVIVAL_RULE_REQUIRED",
            "revival requires an explicit approved world mechanism",
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
        if (
            changes["power_level"] not in old.get("allowed_power_transitions", [])
            and mechanism != "POWER_TRANSITION"
        ):
            raise KernelError(
                "WORLD_POWER_TRANSITION_FORBIDDEN",
                "power transitions require an explicit canonical rule",
            )
    epistemic_requirements = (
        tuple(
            r
            for r in transition.requirements
            if r.state_kind
            in {
                NarrativeStateKind.CHARACTER_KNOWLEDGE,
                NarrativeStateKind.CHARACTER_BELIEF,
            }
        )
        if reality.get("epistemic_contract") == "world-agency.v2"
        else ()
    )
    for requirement in (*transition.epistemic_basis, *epistemic_requirements):
        entry = state.get((requirement.state_kind.value, requirement.entity_key))
        if (entry or {}).get("state", {}).get("character_id") != transition.actor_id:
            raise KernelError(
                "WORLD_EPISTEMIC_ACTOR_MISMATCH",
                "one actor cannot borrow another actor's knowledge",
            )
        if reality.get("epistemic_contract") == "world-agency.v2":
            origin = (entry or {}).get("source_event_id")
            if origin and origin not in transition.cause_refs:
                raise KernelError(
                    "WORLD_EPISTEMIC_CAUSE_REQUIRED",
                    "information-dependent action must reference its own acquisition",
                )
            timestamp = (entry or {}).get("story_time")
            if timestamp:
                acquired = StoryTime.from_dict(timestamp)
                if (
                    acquired.timeline_id != transition.story_time.timeline_id
                    or acquired.end_ordinal >= transition.story_time.start_ordinal
                ):
                    raise KernelError(
                        "WORLD_EPISTEMIC_ORDER_INVALID",
                        "knowledge acquisition must precede the dependent action",
                    )
    return tuple(
        evaluate_requirement(r, state)
        for r in (*transition.requirements, *transition.epistemic_basis)
    )


def validate_initial_agency(transition, reality, state):
    if reality.get("epistemic_contract") != "world-agency.v2":
        raise KernelError(
            "WORLD_AGENCY_CONTRACT_REQUIRED",
            "historical transitions retain their frozen knowledge requirement",
        )
    epistemic = transition.state_kind in {
        NarrativeStateKind.CHARACTER_KNOWLEDGE,
        NarrativeStateKind.CHARACTER_BELIEF,
        NarrativeStateKind.READER_KNOWLEDGE,
        NarrativeStateKind.DISCLOSURE_EVENT,
    }
    if transition.action_mode == "ROUTINE":
        if epistemic:
            raise KernelError(
                "WORLD_ROUTINE_CANNOT_GRANT_KNOWLEDGE",
                "ordinary agency cannot assert knowledge, belief or reader disclosure",
            )
        return
    if not transition.requirements:
        raise KernelError(
            "WORLD_PERCEPTION_SOURCE_REQUIRED",
            "perception requires an exact available objective source predicate",
        )
    sources = [
        requirement
        for requirement in transition.requirements
        if requirement.state_kind
        not in {
            NarrativeStateKind.CHARACTER_KNOWLEDGE,
            NarrativeStateKind.CHARACTER_BELIEF,
            NarrativeStateKind.READER_KNOWLEDGE,
            NarrativeStateKind.DISCLOSURE_EVENT,
            NarrativeStateKind.READER_PROMISE,
            NarrativeStateKind.NARRATIVE_OBLIGATION,
        }
    ]
    if not sources:
        raise KernelError(
            "WORLD_PERCEPTION_SOURCE_REQUIRED",
            "reader knowledge or another character's private knowledge cannot be an observation source",
        )
    for requirement in sources:
        entry = state.get((requirement.state_kind.value, requirement.entity_key)) or {}
        origin = str(entry.get("source_event_id") or "")
        if origin and origin not in transition.cause_refs:
            raise KernelError(
                "WORLD_PERCEPTION_CAUSE_REQUIRED",
                "perception must depend on its exact source event",
            )
        timestamp = entry.get("story_time")
        if timestamp:
            time = StoryTime.from_dict(timestamp)
            if (
                time.timeline_id != transition.story_time.timeline_id
                or time.end_ordinal >= transition.story_time.start_ordinal
            ):
                raise KernelError(
                    "WORLD_PERCEPTION_ORDER_INVALID",
                    "observation must follow source availability on its timeline",
                )
    if epistemic:
        changes = transition.changes
        if (
            transition.state_kind != NarrativeStateKind.CHARACTER_KNOWLEDGE
            or changes.get("character_id") != transition.actor_id
        ):
            raise KernelError(
                "WORLD_PERCEPTION_ACTOR_INVALID",
                "perception grants only its observer's character knowledge",
            )
        if changes.get("status") != "KNOWN" or not (
            changes.get("fact_id") or changes.get("proposition_id")
        ):
            raise KernelError(
                "WORLD_PERCEPTION_KNOWLEDGE_INVALID",
                "observation requires one typed known proposition",
            )
        source = changes.get("observation_source")
        if not isinstance(source, Mapping) or set(source) != {
            "state_kind",
            "entity_key",
            "field",
            "value",
        }:
            raise KernelError(
                "WORLD_PERCEPTION_EVIDENCE_REQUIRED",
                "knowledge acquisition binds an exact objective field and observed value",
            )
        matched = [
            r
            for r in sources
            if r.state_kind.value == source["state_kind"]
            and r.entity_key == source["entity_key"]
            and r.field == source["field"]
            and r.operator == RequirementOperator.EQUALS
            and type(r.value) is type(source["value"])
            and r.value == source["value"]
        ]
        if not matched:
            raise KernelError(
                "WORLD_PERCEPTION_EVIDENCE_MISMATCH",
                "observed proposition must match its own objective source predicate",
            )


def candidate_transition(
    transition: WorldTransition, reality: Mapping[str, Any]
) -> dict[str, Any]:
    approved_foundation = (
        reality.get("world_dynamics_contract") == "world-dynamics.v2"
        and reality.get("baseline_kind") == "APPROVED_FOUNDATION"
        and str(reality.get("revision_id") or "").startswith("foundation:sha256:")
        and reality.get("chapter_number") == 0
        and bool(reality.get("foundation_cause_refs"))
    )
    if not approved_foundation and not str(reality.get("revision_id") or "").startswith(
        "reality:sha256:"
    ):
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
    known_causes.update(row["source_event_id"] for row in (reality.get("working_observation_context") or {}).get("causes", []))
    known_causes.discard("")
    if reality.get("world_dynamics_contract") == "world-dynamics.v2":
        known_causes.update(reality.get("foundation_cause_refs", []))
    if not set(transition.cause_refs).issubset(known_causes):
        raise KernelError(
            "WORLD_CAUSAL_SOURCE_UNKNOWN",
            "causal support must resolve to events in the accepted Reality",
        )
    receipts = validate_world_transition(transition, reality)
    return {
        "contract_version": "world-transition-candidate.v1",
        "reality_revision_id": reality["revision_id"],
        "transition": transition.to_dict(),
        "requirements": list(receipts),
        "eligible": all(receipt["satisfied"] for receipt in receipts),
        "candidate_id": "candidate-future:"
        + narrative_hash(
            {
                "transition": transition.to_dict(),
                "reality_revision_id": reality["revision_id"],
            }
        ),
        "authority": "PLANNING_CANDIDATE",
        "fact_mutation_allowed": False,
    }
