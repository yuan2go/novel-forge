from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


class NarrativeLayer(StrEnum):
    TRUTH = "TRUTH"
    ACCEPTED_ACTUAL = "ACCEPTED_ACTUAL"
    STATE_EVENT = "STATE_EVENT"
    CURRENT_STATE = "CURRENT_STATE"
    TEMPORAL_PROJECTION = "TEMPORAL_PROJECTION"
    FUTURE_INTENT = "FUTURE_INTENT"
    EXECUTION_CONTEXT = "EXECUTION_CONTEXT"
    RETRIEVABLE_KNOWLEDGE = "RETRIEVABLE_KNOWLEDGE"
    OBSERVATION = "OBSERVATION"


class NarrativeStateKind(StrEnum):
    CANON_FACT = "canon_fact"
    TIMELINE_EVENT = "timeline_event"
    CHARACTER_STATE = "character_state"
    RELATIONSHIP_STATE = "relationship_state"
    WORLD_RULE = "world_rule"
    RESOURCE_STATE = "resource_state"
    POWER_STATE = "power_state"
    FORESHADOW_STATE = "foreshadow_state"
    READER_PROMISE = "reader_promise"
    PLOT_THREAD = "plot_thread"
    NARRATIVE_DEBT = "narrative_debt"
    MYSTERY_STATE = "mystery_state"
    ANTAGONIST_STATE = "antagonist_state"
    ARC_STATE = "arc_state"
    REWARD_EVENT = "reward_event"
    THEME_MOVEMENT = "theme_movement"
    CHARACTER_KNOWLEDGE = "character_knowledge"
    CHARACTER_BELIEF = "character_belief"
    CHARACTER_ARC = "character_arc"
    READER_KNOWLEDGE = "reader_knowledge"
    DISCLOSURE_EVENT = "disclosure_event"
    WORLD_STATE = "world_state"
    FACTION_STATE = "faction_state"
    LOCATION_STATE = "location_state"
    CONSEQUENCE_STATE = "consequence_state"
    CONFLICT_STATE = "conflict_state"
    NARRATIVE_OBLIGATION = "narrative_obligation"
    PAYOFF_EVENT = "payoff_event"


_CHARACTER_KNOWLEDGE_STATUSES = frozenset(
    {"UNKNOWN", "SUSPECTED", "KNOWN", "FORGOTTEN"}
)
_CHARACTER_BELIEF_STANCES = frozenset(
    {"BELIEVES", "DOUBTS", "DISBELIEVES", "UNCERTAIN"}
)


def atomize_character_knowledge_changes(
    changes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:

    atoms: list[dict[str, Any]] = []
    for raw in changes:
        change = dict(raw)
        status = str(change.get("status") or "").strip().upper()
        state_alias = str(change.get("state") or "").strip().upper()
        if status and state_alias and status != state_alias:
            raise KernelError(
                "NARRATIVE_CHARACTER_KNOWLEDGE_STATUS_CONFLICT",
                "character knowledge state and status aliases disagree",
            )
        status = status or state_alias
        if status not in _CHARACTER_KNOWLEDGE_STATUSES:
            raise KernelError(
                "NARRATIVE_CHARACTER_KNOWLEDGE_STATUS_INVALID",
                "character knowledge requires UNKNOWN, SUSPECTED, KNOWN, or FORGOTTEN",
            )
        # ``state`` was emitted by the v5 Provider schema even though the durable
        # Narrative State vocabulary has always named this field ``status``.  Make
        # the read-boundary upgrade deterministic, then persist only one canonical
        # representation for new extraction and Canon assets.
        change["status"] = status
        change.pop("state", None)
        character_id = str(change.get("character_id") or "").strip()
        fact_id = str(change.get("fact_id") or "").strip()
        proposition_id = str(change.get("proposition_id") or "").strip()
        acquired_fact_ids = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in change.get("acquired_fact_ids") or ()
                if str(item).strip()
            )
        )
        if not character_id or not (fact_id or proposition_id or acquired_fact_ids):
            raise KernelError(
                "NARRATIVE_CHARACTER_KNOWLEDGE_IDENTITY_INVALID",
                "character knowledge requires character_id and one fact_id or proposition_id",
            )

        if fact_id or proposition_id:
            atom = dict(change)
            atom.pop("acquired_fact_ids", None)
            atoms.append(atom)

        for acquired_fact_id in acquired_fact_ids:
            if fact_id and acquired_fact_id == fact_id:
                continue
            atom = dict(change)
            atom.pop("acquired_fact_ids", None)
            atom.pop("proposition_id", None)
            atom["fact_id"] = acquired_fact_id
            atoms.append(atom)
    return atoms


def normalize_character_belief_changes(
    changes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:

    normalized: list[dict[str, Any]] = []
    for raw in changes:
        change = dict(raw)
        stance_values = {
            str(change[key]).strip().upper()
            for key in ("stance", "status", "state")
            if change.get(key) not in {None, ""}
        }
        if len(stance_values) > 1:
            raise KernelError(
                "NARRATIVE_CHARACTER_BELIEF_STANCE_CONFLICT",
                "character belief stance, status, and state aliases disagree",
            )
        stance = next(iter(stance_values), "")
        if stance not in _CHARACTER_BELIEF_STANCES:
            raise KernelError(
                "NARRATIVE_CHARACTER_BELIEF_STANCE_INVALID",
                "character belief requires BELIEVES, DOUBTS, DISBELIEVES, or UNCERTAIN",
            )
        from_values = {
            str(change[key]).strip().upper()
            for key in ("from_stance", "from_status", "from_state")
            if change.get(key) not in {None, ""}
        }
        if len(from_values) > 1:
            raise KernelError(
                "NARRATIVE_CHARACTER_BELIEF_PRECONDITION_CONFLICT",
                "character belief from_stance, from_status, and from_state aliases disagree",
            )
        from_stance = next(iter(from_values), "")
        if from_stance and from_stance not in _CHARACTER_BELIEF_STANCES:
            raise KernelError(
                "NARRATIVE_CHARACTER_BELIEF_PRECONDITION_INVALID",
                "character belief from_stance uses an unsupported value",
            )
        confidence = change.get("belief_confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise KernelError(
                "NARRATIVE_CHARACTER_BELIEF_CONFIDENCE_INVALID",
                "character belief confidence must be between zero and one",
            )
        character_id = str(change.get("character_id") or "").strip()
        fact_id = str(change.get("fact_id") or "").strip()
        proposition_id = str(change.get("proposition_id") or "").strip()
        if not character_id or not (fact_id or proposition_id):
            raise KernelError(
                "NARRATIVE_CHARACTER_BELIEF_IDENTITY_INVALID",
                "character belief requires character_id and fact_id or proposition_id",
            )
        change["stance"] = stance
        for alias in ("status", "state", "from_status", "from_state"):
            change.pop(alias, None)
        if from_stance:
            change["from_stance"] = from_stance
        else:
            change.pop("from_stance", None)
        normalized.append(change)
    return normalized


def normalize_relationship_state_changes(
    changes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:

    normalized: list[dict[str, Any]] = []
    for raw in changes:
        change = dict(raw)
        source_values = {
            str(change[key]).strip()
            for key in ("source_id", "source_character_id", "character_id")
            if change.get(key) not in {None, ""}
        }
        target_values = {
            str(change[key]).strip()
            for key in ("target_id", "target_character_id")
            if change.get(key) not in {None, ""}
        }
        if len(source_values) > 1 or len(target_values) > 1:
            raise KernelError(
                "NARRATIVE_RELATIONSHIP_IDENTITY_CONFLICT",
                "relationship endpoint aliases disagree",
            )
        source_id = next(iter(source_values), "")
        target_id = next(iter(target_values), "")
        if not source_id or not target_id:
            raise KernelError(
                "NARRATIVE_RELATIONSHIP_IDENTITY_INVALID",
                "relationship state requires source_id and target_id",
            )
        if source_id == target_id and not change.get("allow_self_relation"):
            raise KernelError(
                "NARRATIVE_RELATIONSHIP_SELF_REFERENCE_INVALID",
                "relationship endpoints must be distinct",
            )
        change["source_id"] = source_id
        change["target_id"] = target_id
        for alias in (
            "source_character_id",
            "target_character_id",
            "character_id",
        ):
            change.pop(alias, None)
        normalized.append(change)
    return normalized


class NarrativeObligationType(StrEnum):
    PROMISE = "PROMISE"
    FORESHADOWING = "FORESHADOWING"
    MYSTERY = "MYSTERY"
    CONFLICT = "CONFLICT"
    OPEN_LOOP = "OPEN_LOOP"
    HOOK = "HOOK"
    CHARACTER_COMMITMENT = "CHARACTER_COMMITMENT"
    READER_EXPECTATION = "READER_EXPECTATION"
    NARRATIVE_DEBT = "NARRATIVE_DEBT"


class NarrativeObligationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    DEVELOPING = "DEVELOPING"
    DUE = "DUE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class NarrativeObligationPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReducerSemantics(StrEnum):
    UPSERT = "UPSERT"
    TRANSITION = "TRANSITION"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    ACTIVATE = "ACTIVATE"
    SUPERSEDE = "SUPERSEDE"
    INCREMENT = "INCREMENT"
    DECREMENT = "DECREMENT"
    APPEND = "APPEND"


@dataclass(frozen=True, slots=True)
class NarrativeScope:
    project_id: str
    book_id: str

    def __post_init__(self) -> None:
        if not self.project_id.strip() or not self.book_id.strip():
            raise KernelError(
                "NARRATIVE_SCOPE_INVALID",
                "Narrative State requires non-empty Project and Book identity",
            )

    def to_dict(self) -> dict[str, str]:
        return {"project_id": self.project_id, "book_id": self.book_id}


@dataclass(frozen=True, slots=True)
class NarrativePosition:

    chapter: int
    volume_id: str = ""
    arc_id: str = ""
    sequence_id: str = ""
    sequence_ordinal: int = 0

    def __post_init__(self) -> None:
        if self.chapter <= 0 or self.sequence_ordinal < 0:
            raise KernelError(
                "NARRATIVE_POSITION_INVALID",
                "Narrative position requires a positive chapter and non-negative sequence ordinal",
            )
        if bool(self.sequence_id) != bool(self.sequence_ordinal):
            raise KernelError(
                "NARRATIVE_POSITION_INVALID",
                "Narrative sequence identity and ordinal must be supplied together",
            )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"chapter": self.chapter}
        if self.volume_id:
            value["volume_id"] = self.volume_id
        if self.arc_id:
            value["arc_id"] = self.arc_id
        if self.sequence_id:
            value.update(
                {
                    "sequence_id": self.sequence_id,
                    "sequence_ordinal": self.sequence_ordinal,
                }
            )
        return value


@dataclass(frozen=True, slots=True)
class NarrativeIdentity:
    identity_kind: str
    entity_key: str
    components: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.identity_kind or not self.entity_key or not self.components:
            raise KernelError(
                "NARRATIVE_IDENTITY_REQUIRED",
                "Narrative State event requires a typed entity identity",
            )
        if any(not key or not value for key, value in self.components):
            raise KernelError(
                "NARRATIVE_IDENTITY_REQUIRED",
                "Narrative State identity components must be non-empty",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_kind": self.identity_kind,
            "entity_key": self.entity_key,
            "components": {key: value for key, value in self.components},
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NarrativeIdentity:
        components = value.get("components")
        if not isinstance(components, dict):
            raise KernelError(
                "NARRATIVE_IDENTITY_REQUIRED",
                "Narrative State identity components must be an object",
            )
        return cls(
            identity_kind=str(value.get("identity_kind") or ""),
            entity_key=str(value.get("entity_key") or ""),
            components=tuple(sorted((str(key), str(item)) for key, item in components.items())),
        )


@dataclass(frozen=True, slots=True)
class NarrativeCoordinate:
    source_chapter: int
    effective_from_chapter: int
    effective_to_chapter: int = 0
    position: NarrativePosition | None = None

    def __post_init__(self) -> None:
        if (
            self.source_chapter <= 0
            or self.effective_from_chapter <= 0
            or self.effective_from_chapter > self.source_chapter
            or (
                self.effective_to_chapter
                and (
                    self.effective_to_chapter < self.effective_from_chapter
                )
            )
        ):
            raise KernelError(
                "NARRATIVE_TEMPORAL_BOUNDARY_INVALID",
                "Narrative State effective start must be non-future and its range ordered",
            )
        if self.position is not None and self.position.chapter != self.source_chapter:
            raise KernelError(
                "NARRATIVE_POSITION_INVALID",
                "Narrative position chapter must equal the source chapter",
            )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "source_chapter": self.source_chapter,
            "effective_from_chapter": self.effective_from_chapter,
        }
        if self.effective_to_chapter:
            value["effective_to_chapter"] = self.effective_to_chapter
        if self.position is not None:
            value["position"] = self.position.to_dict()
        return value


@dataclass(frozen=True, slots=True)
class StoryTime:

    timeline_id: str
    start_ordinal: int
    end_ordinal: int
    precision: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.timeline_id or self.precision not in {
            "EXACT",
            "ORDERED",
            "RANGE",
            "UNSPECIFIED",
        }:
            raise KernelError(
                "STORY_TIME_INVALID",
                "Story Time requires a timeline and supported precision",
            )
        if self.precision == "UNSPECIFIED":
            if self.start_ordinal != 0 or self.end_ordinal != 0:
                raise KernelError(
                    "STORY_TIME_INVALID",
                    "unspecified Story Time cannot invent an ordering",
                )
        elif self.start_ordinal <= 0 or self.end_ordinal < self.start_ordinal:
            raise KernelError(
                "STORY_TIME_INVALID",
                "ordered Story Time requires positive ordered boundaries",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeline_id": self.timeline_id,
            "start_ordinal": self.start_ordinal,
            "end_ordinal": self.end_ordinal,
            "precision": self.precision,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StoryTime:
        return cls(
            timeline_id=str(value.get("timeline_id") or ""),
            start_ordinal=int(value.get("start_ordinal") or 0),
            end_ordinal=int(value.get("end_ordinal") or 0),
            precision=str(value.get("precision") or ""),
            label=str(value.get("label") or ""),
        )


@dataclass(frozen=True, slots=True)
class NarrativeCausality:
    cause_refs: tuple[str, ...]
    precondition_refs: tuple[str, ...]
    participant_ids: tuple[str, ...]
    effect_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.cause_refs
            or not self.participant_ids
            or not self.effect_kinds
            or any(
                not str(item).strip()
                for item in (
                    *self.cause_refs,
                    *self.precondition_refs,
                    *self.participant_ids,
                    *self.effect_kinds,
                )
            )
            or not set(self.effect_kinds).issubset(
                {"FACT", "STATE", "KNOWLEDGE", "OBLIGATION", "ARC", "DISCLOSURE", "PAYOFF"}
            )
        ):
            raise KernelError(
                "NARRATIVE_CAUSALITY_INVALID",
                "Accepted Narrative Event requires cause, participants, and typed effects",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause_refs": list(self.cause_refs),
            "precondition_refs": list(self.precondition_refs),
            "participant_ids": list(self.participant_ids),
            "effect_kinds": list(self.effect_kinds),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NarrativeCausality:
        return cls(
            cause_refs=tuple(str(item) for item in value.get("cause_refs") or ()),
            precondition_refs=tuple(
                str(item) for item in value.get("precondition_refs") or ()
            ),
            participant_ids=tuple(
                str(item) for item in value.get("participant_ids") or ()
            ),
            effect_kinds=tuple(
                str(item).upper() for item in value.get("effect_kinds") or ()
            ),
        )


@dataclass(frozen=True, slots=True)
class NarrativeStateEvent:
    event_id: str
    state_kind: NarrativeStateKind
    scope: NarrativeScope
    identity: NarrativeIdentity
    coordinate: NarrativeCoordinate
    semantics: ReducerSemantics
    payload: dict[str, Any]
    supersedes_event_id: str
    provenance: dict[str, Any]
    confidence: float
    coverage: str
    evidence: dict[str, Any]
    event_version: int = 1
    entity_version: int = 1
    canon_status: str = "APPROVED_CANON_PATCH"
    story_time: StoryTime | None = None
    causality: NarrativeCausality | None = None

    def __post_init__(self) -> None:
        if not self.event_id.startswith("narrative-event:sha256:"):
            raise KernelError(
                "NARRATIVE_EVENT_ID_INVALID", "Narrative event ID must be content-derived"
            )
        if (
            not 0 <= self.confidence <= 1
            or not self.coverage
            or self.event_version <= 0
            or self.entity_version <= 0
            or self.canon_status not in {"APPROVED_CANON_PATCH", "NON_CANON_OBSERVATION"}
        ):
            raise KernelError(
                "NARRATIVE_EVIDENCE_INVALID",
                "Narrative State confidence and coverage are required",
            )
        _reject_v2_aliases(self.payload)
        _validate_event_payload(self.state_kind, self.payload)
        if self.event_version >= 3 and (
            self.story_time is None or self.causality is None
        ):
            raise KernelError(
                "NARRATIVE_EVENT_CAUSALITY_REQUIRED",
                "Narrative State event v3 requires Story Time and causal lineage",
            )
        if self.event_version < 3 and (
            self.story_time is not None or self.causality is not None
        ):
            raise KernelError(
                "NARRATIVE_EVENT_VERSION_INVALID",
                "Story Time and causality require Narrative State event v3",
            )
        expected = _event_id(
            state_kind=self.state_kind,
            scope=self.scope,
            identity=self.identity,
            coordinate=self.coordinate,
            semantics=self.semantics,
            payload=self.payload,
            supersedes_event_id=self.supersedes_event_id,
            provenance=self.provenance,
            confidence=self.confidence,
            coverage=self.coverage,
            evidence=self.evidence,
            event_version=self.event_version,
            entity_version=self.entity_version,
            canon_status=self.canon_status,
            story_time=self.story_time,
            causality=self.causality,
        )
        if self.event_id != expected:
            raise KernelError(
                "NARRATIVE_EVENT_INTEGRITY_FAILED",
                "Narrative event ID does not match its immutable semantic content",
            )

    def to_dict(self) -> dict[str, Any]:
        authority = {
            "status": "PENDING_BOOK_ACCEPTANCE",
            "required_boundary": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
        }
        version = {"event_contract": self.event_version}
        if self.event_version >= 2:
            authority["canon_status"] = self.canon_status
            version["entity"] = self.entity_version
        result = {
            "event_id": self.event_id,
            "contract_version": (
                "narrative-state-event-v3"
                if self.event_version >= 3
                else "narrative-state-event-v2"
            ),
            "layer": NarrativeLayer.STATE_EVENT.value,
            "state_kind": self.state_kind.value,
            "scope": self.scope.to_dict(),
            "identity": self.identity.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "authority": authority,
            "mutation": {
                "semantics": self.semantics.value,
                "payload": _deep_copy(self.payload),
            },
            "version": version,
            "supersession": {"supersedes_event_id": self.supersedes_event_id},
            "provenance": _deep_copy(self.provenance),
            "confidence": self.confidence,
            "coverage": self.coverage,
            "evidence": _deep_copy(self.evidence),
        }
        if self.event_version >= 3:
            result["story_time"] = self.story_time.to_dict()  # type: ignore[union-attr]
            result["causality"] = self.causality.to_dict()  # type: ignore[union-attr]
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NarrativeStateEvent:
        if value.get("contract_version") not in {
            "narrative-state-event-v2",
            "narrative-state-event-v3",
        }:
            raise KernelError(
                "NARRATIVE_EVENT_CONTRACT_UNSUPPORTED",
                "only Narrative State event v2/v3 is accepted by the production reducer",
            )
        mutation = value.get("mutation")
        if not isinstance(mutation, dict) or not isinstance(mutation.get("payload"), dict):
            raise KernelError(
                "NARRATIVE_MUTATION_INVALID", "Narrative State mutation must be typed"
            )
        payload = dict(mutation["payload"])
        _reject_v2_aliases(payload)
        scope = value.get("scope")
        coordinate = value.get("coordinate")
        identity = value.get("identity")
        supersession = value.get("supersession") or {}
        if not all(isinstance(item, dict) for item in (scope, coordinate, identity)):
            raise KernelError(
                "NARRATIVE_EVENT_CONTRACT_INVALID",
                "Narrative State scope, identity and coordinate are required",
            )
        position_value = coordinate.get("position")
        position = None
        if isinstance(position_value, dict):
            position = NarrativePosition(
                chapter=int(position_value.get("chapter") or 0),
                volume_id=str(position_value.get("volume_id") or ""),
                arc_id=str(position_value.get("arc_id") or ""),
                sequence_id=str(position_value.get("sequence_id") or ""),
                sequence_ordinal=int(position_value.get("sequence_ordinal") or 0),
            )
        try:
            state_kind = NarrativeStateKind(str(value.get("state_kind") or ""))
            semantics = ReducerSemantics(str(mutation.get("semantics") or ""))
        except ValueError as exc:
            raise KernelError(
                "NARRATIVE_EVENT_ENUM_INVALID",
                "Narrative State kind and reducer semantics must use the v2 vocabulary",
            ) from exc
        return cls(
            event_id=str(value.get("event_id") or ""),
            state_kind=state_kind,
            scope=NarrativeScope(
                project_id=str(scope.get("project_id") or ""),
                book_id=str(scope.get("book_id") or ""),
            ),
            identity=NarrativeIdentity.from_dict(identity),
            coordinate=NarrativeCoordinate(
                source_chapter=int(coordinate.get("source_chapter") or 0),
                effective_from_chapter=int(
                    coordinate.get("effective_from_chapter") or 0
                ),
                effective_to_chapter=int(coordinate.get("effective_to_chapter") or 0),
                position=position,
            ),
            semantics=semantics,
            payload=payload,
            supersedes_event_id=str(supersession.get("supersedes_event_id") or ""),
            provenance=dict(value.get("provenance") or {}),
            confidence=float(value.get("confidence", 0.0)),
            coverage=str(value.get("coverage") or ""),
            evidence=dict(value.get("evidence") or {}),
            event_version=int((value.get("version") or {}).get("event_contract") or 0),
            entity_version=int((value.get("version") or {}).get("entity") or 1),
            canon_status=str(
                (value.get("authority") or {}).get("canon_status")
                or "APPROVED_CANON_PATCH"
            ),
            story_time=(
                StoryTime.from_dict(dict(value["story_time"]))
                if isinstance(value.get("story_time"), dict)
                else None
            ),
            causality=(
                NarrativeCausality.from_dict(dict(value["causality"]))
                if isinstance(value.get("causality"), dict)
                else None
            ),
        )


_PATCH_FIELDS: dict[NarrativeStateKind, tuple[str, ...]] = {
    NarrativeStateKind.CANON_FACT: ("facts",),
    NarrativeStateKind.CHARACTER_STATE: ("character_state_changes",),
    NarrativeStateKind.RELATIONSHIP_STATE: ("relationship_changes",),
    NarrativeStateKind.TIMELINE_EVENT: ("timeline_event_candidates", "timeline_events"),
    NarrativeStateKind.FORESHADOW_STATE: ("foreshadow_changes",),
    NarrativeStateKind.READER_PROMISE: ("promise_changes",),
    NarrativeStateKind.REWARD_EVENT: ("reward_changes",),
    NarrativeStateKind.WORLD_RULE: ("world_rule_usages",),
    NarrativeStateKind.POWER_STATE: ("power_state_changes",),
    NarrativeStateKind.PLOT_THREAD: ("plot_thread_changes",),
    NarrativeStateKind.RESOURCE_STATE: ("resource_state_changes",),
    NarrativeStateKind.MYSTERY_STATE: ("mystery_actions",),
    NarrativeStateKind.THEME_MOVEMENT: ("theme_movements",),
    NarrativeStateKind.ANTAGONIST_STATE: ("antagonist_pressure_changes", "antagonist_actions"),
    NarrativeStateKind.ARC_STATE: ("arc_contributions",),
    NarrativeStateKind.CHARACTER_KNOWLEDGE: ("character_knowledge_changes",),
    NarrativeStateKind.CHARACTER_BELIEF: ("character_belief_changes",),
    NarrativeStateKind.CHARACTER_ARC: ("character_arc_changes",),
    NarrativeStateKind.READER_KNOWLEDGE: ("reader_knowledge_changes",),
    NarrativeStateKind.DISCLOSURE_EVENT: ("disclosure_events",),
    NarrativeStateKind.WORLD_STATE: ("world_state_changes",),
    NarrativeStateKind.FACTION_STATE: ("faction_state_changes",),
    NarrativeStateKind.LOCATION_STATE: ("location_state_changes",),
    NarrativeStateKind.CONSEQUENCE_STATE: ("consequence_changes",),
    NarrativeStateKind.CONFLICT_STATE: ("conflict_state_changes",),
    NarrativeStateKind.NARRATIVE_OBLIGATION: ("obligation_changes",),
    NarrativeStateKind.PAYOFF_EVENT: ("payoff_events",),
}

_LEGACY_OBLIGATION_KINDS = frozenset(
    {
        NarrativeStateKind.FORESHADOW_STATE,
        NarrativeStateKind.READER_PROMISE,
        NarrativeStateKind.PLOT_THREAD,
        NarrativeStateKind.NARRATIVE_DEBT,
        NarrativeStateKind.MYSTERY_STATE,
    }
)

_LEGACY_OBLIGATION_IDENTITY_FIELDS = {
    NarrativeStateKind.FORESHADOW_STATE: ("entity_id", "thread_id"),
    NarrativeStateKind.READER_PROMISE: ("promise_id",),
    NarrativeStateKind.PLOT_THREAD: ("thread_id",),
    NarrativeStateKind.NARRATIVE_DEBT: ("debt_id",),
    NarrativeStateKind.MYSTERY_STATE: ("mystery_id", "entity_id"),
}

_OBLIGATION_PATCH_FIELDS: tuple[
    tuple[str, NarrativeObligationType, tuple[str, ...]], ...
] = (
    ("promise_changes", NarrativeObligationType.PROMISE, ("promise_id",)),
    (
        "foreshadow_changes",
        NarrativeObligationType.FORESHADOWING,
        ("entity_id", "thread_id"),
    ),
    (
        "mystery_actions",
        NarrativeObligationType.MYSTERY,
        ("mystery_id", "entity_id"),
    ),
    ("conflict_changes", NarrativeObligationType.CONFLICT, ("conflict_id",)),
    ("plot_thread_changes", NarrativeObligationType.OPEN_LOOP, ("thread_id",)),
    ("open_loop_changes", NarrativeObligationType.OPEN_LOOP, ("thread_id",)),
    ("hook_changes", NarrativeObligationType.HOOK, ("hook_id",)),
    (
        "character_commitment_changes",
        NarrativeObligationType.CHARACTER_COMMITMENT,
        ("commitment_id",),
    ),
    (
        "reader_expectation_changes",
        NarrativeObligationType.READER_EXPECTATION,
        ("expectation_id",),
    ),
    (
        "narrative_debt_changes",
        NarrativeObligationType.NARRATIVE_DEBT,
        ("debt_id",),
    ),
)

_SNAPSHOT_KIND_ALIASES = {
    "canon_snapshot": NarrativeStateKind.CANON_FACT,
    "character_state": NarrativeStateKind.CHARACTER_STATE,
    "relationship_state": NarrativeStateKind.RELATIONSHIP_STATE,
    "timeline_snapshot": NarrativeStateKind.TIMELINE_EVENT,
    "foreshadow_state": NarrativeStateKind.FORESHADOW_STATE,
    "reader_promise": NarrativeStateKind.READER_PROMISE,
    "reward_ledger": NarrativeStateKind.REWARD_EVENT,
    "world_rule": NarrativeStateKind.WORLD_RULE,
    "power_state": NarrativeStateKind.POWER_STATE,
    "plot_thread": NarrativeStateKind.PLOT_THREAD,
    "resource_state": NarrativeStateKind.RESOURCE_STATE,
}

_V1_OUTCOME_FIELDS = {
    "occurred_events": NarrativeStateKind.TIMELINE_EVENT,
    "character_deltas": NarrativeStateKind.CHARACTER_STATE,
    "relationship_deltas": NarrativeStateKind.RELATIONSHIP_STATE,
    "world_deltas": NarrativeStateKind.WORLD_RULE,
    "resource_deltas": NarrativeStateKind.RESOURCE_STATE,
    "power_deltas": NarrativeStateKind.POWER_STATE,
    "foreshadow_actions": NarrativeStateKind.FORESHADOW_STATE,
    "mystery_actions": NarrativeStateKind.MYSTERY_STATE,
    "promise_actions": NarrativeStateKind.READER_PROMISE,
    "reward_actions": NarrativeStateKind.REWARD_EVENT,
    "narrative_debt_actions": NarrativeStateKind.NARRATIVE_DEBT,
    "theme_movements": NarrativeStateKind.THEME_MOVEMENT,
    "antagonist_actions": NarrativeStateKind.ANTAGONIST_STATE,
    "arc_contributions": NarrativeStateKind.ARC_STATE,
}


def events_from_canon_patch(
    *,
    project_id: str,
    book_id: str,
    source_chapter: int,
    chapter_outcome_id: str,
    canon_patch_asset_version_id: str,
    accepted_draft_asset_version_id: str,
    source_operation_id: str,
    trace_id: str,
    canon_patch: dict[str, Any],
) -> tuple[NarrativeStateEvent, ...]:

    scope = NarrativeScope(project_id, book_id)
    changes: dict[NarrativeStateKind, list[dict[str, Any]]] = {
        kind: [] for kind in NarrativeStateKind
    }
    state_changes = canon_patch.get("state_changes")
    if isinstance(state_changes, dict):
        for raw_kind, values in state_changes.items():
            try:
                kind = NarrativeStateKind(str(raw_kind))
            except ValueError as exc:
                raise KernelError(
                    "NARRATIVE_STATE_KIND_UNSUPPORTED",
                    f"unsupported Narrative State kind: {raw_kind}",
                ) from exc
            items = _object_items(values)
            if kind in _LEGACY_OBLIGATION_KINDS:
                obligation_type = {
                    NarrativeStateKind.READER_PROMISE: NarrativeObligationType.PROMISE,
                    NarrativeStateKind.FORESHADOW_STATE: NarrativeObligationType.FORESHADOWING,
                    NarrativeStateKind.MYSTERY_STATE: NarrativeObligationType.MYSTERY,
                    NarrativeStateKind.PLOT_THREAD: NarrativeObligationType.OPEN_LOOP,
                    NarrativeStateKind.NARRATIVE_DEBT: NarrativeObligationType.NARRATIVE_DEBT,
                }[kind]
                changes[NarrativeStateKind.NARRATIVE_OBLIGATION].extend(
                    _normalize_obligation(
                        item,
                        obligation_type,
                        source_chapter,
                        legacy_adapter=True,
                        legacy_identity_fields=(
                            _LEGACY_OBLIGATION_IDENTITY_FIELDS[kind]
                        ),
                    )
                    for item in items
                )
            elif kind is NarrativeStateKind.NARRATIVE_OBLIGATION:
                changes[kind].extend(
                    _normalize_obligation(
                        item,
                        NarrativeObligationType(
                            str(item.get("obligation_type") or "").upper()
                        ),
                        source_chapter,
                    )
                    for item in items
                )
            else:
                changes[kind].extend(items)
    for kind, fields in _PATCH_FIELDS.items():
        if kind in _LEGACY_OBLIGATION_KINDS:
            continue
        if changes[kind]:
            continue
        for field in fields:
            items = _object_items(canon_patch.get(field))
            if kind is NarrativeStateKind.NARRATIVE_OBLIGATION:
                changes[kind].extend(
                    _normalize_obligation(
                        item,
                        NarrativeObligationType(
                            str(item.get("obligation_type") or "").upper()
                        ),
                        source_chapter,
                    )
                    for item in items
                )
            else:
                changes[kind].extend(items)
    for field, obligation_type, identity_fields in _OBLIGATION_PATCH_FIELDS:
        changes[NarrativeStateKind.NARRATIVE_OBLIGATION].extend(
            _normalize_obligation(
                item,
                obligation_type,
                source_chapter,
                legacy_adapter=True,
                legacy_identity_fields=identity_fields,
            )
            for item in _object_items(canon_patch.get(field))
        )
    for snapshot in _object_items(canon_patch.get("snapshot_candidates")):
        kind = _SNAPSHOT_KIND_ALIASES.get(str(snapshot.get("state_kind") or ""))
        if kind is not None and not changes[kind]:
            items = _object_items(snapshot.get("changes"))
            if kind in _LEGACY_OBLIGATION_KINDS:
                obligation_type = {
                    NarrativeStateKind.READER_PROMISE: NarrativeObligationType.PROMISE,
                    NarrativeStateKind.FORESHADOW_STATE: NarrativeObligationType.FORESHADOWING,
                    NarrativeStateKind.MYSTERY_STATE: NarrativeObligationType.MYSTERY,
                    NarrativeStateKind.PLOT_THREAD: NarrativeObligationType.OPEN_LOOP,
                    NarrativeStateKind.NARRATIVE_DEBT: NarrativeObligationType.NARRATIVE_DEBT,
                }[kind]
                changes[NarrativeStateKind.NARRATIVE_OBLIGATION].extend(
                    _normalize_obligation(
                        item,
                        obligation_type,
                        source_chapter,
                        legacy_adapter=True,
                        legacy_identity_fields=(
                            _LEGACY_OBLIGATION_IDENTITY_FIELDS[kind]
                        ),
                    )
                    for item in items
                )
            else:
                changes[kind].extend(items)

    # Recover Canon patches created before Character Knowledge became an atomic
    # character/proposition event.  This is a deterministic read-boundary upgrade;
    # the immutable source patch remains untouched and event identities stay stable.
    changes[NarrativeStateKind.CHARACTER_KNOWLEDGE] = (
        atomize_character_knowledge_changes(
            changes[NarrativeStateKind.CHARACTER_KNOWLEDGE]
        )
    )
    changes[NarrativeStateKind.CHARACTER_BELIEF] = (
        normalize_character_belief_changes(
            changes[NarrativeStateKind.CHARACTER_BELIEF]
        )
    )
    changes[NarrativeStateKind.RELATIONSHIP_STATE] = (
        normalize_relationship_state_changes(
            changes[NarrativeStateKind.RELATIONSHIP_STATE]
        )
    )

    events: list[NarrativeStateEvent] = []
    for kind in NarrativeStateKind:
        for ordinal, raw in enumerate(changes[kind]):
            events.append(
                _build_event(
                    scope=scope,
                    state_kind=kind,
                    source_chapter=source_chapter,
                    chapter_outcome_id=chapter_outcome_id,
                    source_asset_version_id=canon_patch_asset_version_id,
                    accepted_draft_asset_version_id=accepted_draft_asset_version_id,
                    source_operation_id=source_operation_id,
                    trace_id=trace_id,
                    source_field="canon_patch",
                    ordinal=ordinal,
                    raw=raw,
                    legacy=False,
                )
            )
    return tuple(events)


def events_from_chapter_outcome(
    chapter_outcome_asset_version_id: str,
    chapter_outcome: dict[str, Any],
    *,
    trace_id: str = "",
) -> tuple[NarrativeStateEvent, ...]:

    contract = str(chapter_outcome.get("contract_version") or "")
    if contract in {"chapter-outcome-v2", "chapter-outcome-v3"}:
        return tuple(
            NarrativeStateEvent.from_dict(item)
            for item in _object_items(chapter_outcome.get("state_events"))
        )
    if contract != "chapter-outcome-v1":
        raise KernelError(
            "CHAPTER_OUTCOME_CONTRACT_UNSUPPORTED",
            f"cannot replay ChapterOutcome contract {contract or 'missing'}",
        )
    source_chapter = int(chapter_outcome.get("chapter_number") or 0)
    scope = NarrativeScope(
        str(chapter_outcome.get("project_id") or ""),
        str(chapter_outcome.get("book_id") or ""),
    )
    events: list[NarrativeStateEvent] = []
    for field, kind in _V1_OUTCOME_FIELDS.items():
        for ordinal, raw_item in enumerate(chapter_outcome.get(field) or ()):
            raw = dict(raw_item) if isinstance(raw_item, dict) else {"summary": str(raw_item)}
            events.append(
                _build_event(
                    scope=scope,
                    state_kind=kind,
                    source_chapter=source_chapter,
                    chapter_outcome_id=str(
                        chapter_outcome.get("chapter_outcome_id") or chapter_outcome_asset_version_id
                    ),
                    source_asset_version_id=chapter_outcome_asset_version_id,
                    accepted_draft_asset_version_id=str(
                        chapter_outcome.get("accepted_draft_version_id") or ""
                    ),
                    source_operation_id=str(
                        chapter_outcome.get("created_by_operation_id") or ""
                    ),
                    trace_id=trace_id,
                    source_field=field,
                    ordinal=ordinal,
                    raw=raw,
                    legacy=True,
                )
            )
    return tuple(events)


def _build_event(
    *,
    scope: NarrativeScope,
    state_kind: NarrativeStateKind,
    source_chapter: int,
    chapter_outcome_id: str,
    source_asset_version_id: str,
    accepted_draft_asset_version_id: str,
    source_operation_id: str,
    trace_id: str,
    source_field: str,
    ordinal: int,
    raw: dict[str, Any],
    legacy: bool,
) -> NarrativeStateEvent:
    if not chapter_outcome_id or not source_asset_version_id or not source_operation_id:
        raise KernelError(
            "NARRATIVE_PROVENANCE_REQUIRED",
            "Narrative State event requires Outcome, AssetVersion and Operation lineage",
        )
    identity = _identity_for(
        state_kind,
        raw,
        ordinal=ordinal,
        source=source_asset_version_id,
        allow_legacy_fallback=legacy,
    )
    effective_from = int(
        raw.get("effective_from_chapter")
        or (raw.get("effective_chapter") if legacy else 0)
        or (raw.get("chapter") if legacy else 0)
        or source_chapter
    )
    raw_position = raw.get("narrative_position")
    position = None
    if not legacy and (
        isinstance(raw_position, dict)
        or any(
            raw.get(key)
            for key in ("volume_id", "arc_id", "sequence_id", "sequence_ordinal")
        )
    ):
        position_data = dict(raw_position) if isinstance(raw_position, dict) else {}
        sequence_id = str(
            position_data.get("sequence_id") or raw.get("sequence_id") or ""
        )
        sequence_ordinal = int(
            position_data.get("sequence_ordinal")
            or raw.get("sequence_ordinal")
            or 0
        )
        position = NarrativePosition(
            chapter=source_chapter,
            volume_id=str(
                position_data.get("volume_id") or raw.get("volume_id") or ""
            ),
            arc_id=str(position_data.get("arc_id") or raw.get("arc_id") or ""),
            sequence_id=sequence_id,
            sequence_ordinal=sequence_ordinal,
        )
    coordinate = NarrativeCoordinate(
        source_chapter=source_chapter,
        effective_from_chapter=effective_from,
        effective_to_chapter=int(raw.get("effective_to_chapter") or 0),
        position=position,
    )
    supersedes = str(
        raw.get("supersedes_event_id")
        or (raw.get("supersedes_version_id") if legacy else "")
        or (raw.get("supersedes_asset_version_id") if legacy else "")
        or ""
    )
    if not legacy and any(
        key in raw for key in ("effective_chapter", "supersedes_version_id", "supersedes_asset_version_id")
    ):
        raise KernelError(
            "NARRATIVE_V2_ALIAS_FORBIDDEN",
            "v2 Narrative State input uses a legacy temporal or supersession alias",
        )
    legacy_obligation_adapter = bool(raw.get("_legacy_obligation_adapter"))
    payload = {
        key: _deep_copy(value)
        for key, value in raw.items()
        if key
        not in {
            "effective_from_chapter",
            "effective_to_chapter",
            "effective_chapter",
            "chapter",
            "narrative_position",
            "volume_id",
            "arc_id",
            "sequence_id",
            "sequence_ordinal",
            "entity_version",
            "canon_status",
            "_legacy_obligation_adapter",
            "supersedes_event_id",
            "supersedes_version_id",
            "supersedes_asset_version_id",
            "confidence",
            "coverage",
            "extraction_evidence",
            "evidence",
            "story_time",
            "causality",
        }
    }
    if (
        state_kind is NarrativeStateKind.NARRATIVE_OBLIGATION
        and str(payload.get("status") or "").upper() == "FULFILLED"
        and not dict(payload.get("payoff_evidence") or {})
        and legacy_obligation_adapter
    ):
        payload["payoff_evidence"] = {
            "asset_version_id": accepted_draft_asset_version_id,
            "event_id": f"{source_asset_version_id}#{source_field}:{ordinal}",
            "evidence_mode": "ACCEPTED_DRAFT_CANON_LINEAGE",
        }
    semantics = _semantics_for(state_kind, payload, supersedes)
    provenance = {
        "source_asset_version_id": source_asset_version_id,
        "accepted_draft_asset_version_id": accepted_draft_asset_version_id,
        "source_operation_id": source_operation_id,
        "trace_id": trace_id,
        "chapter_outcome_id": chapter_outcome_id,
        "source_field": source_field,
        "source_ordinal": ordinal,
    }
    evidence = dict(raw.get("extraction_evidence") or raw.get("evidence") or {})
    confidence = float(raw.get("confidence", 1.0 if legacy else 0.0))
    coverage = str(
        raw.get("coverage") or ("LEGACY_ADAPTED" if legacy else "UNSPECIFIED")
    )
    story_time_value = raw.get("story_time")
    causality_value = raw.get("causality")
    if not legacy and bool(isinstance(story_time_value, dict)) != bool(
        isinstance(causality_value, dict)
    ):
        raise KernelError(
            "NARRATIVE_EVENT_CAUSALITY_REQUIRED",
            "Story Time and causal lineage must be supplied together",
        )
    requires_v3 = not legacy and (
        "entity_version" in raw
        or (
            isinstance(story_time_value, dict)
            and isinstance(causality_value, dict)
        )
    )
    story_time = (
        StoryTime.from_dict(dict(story_time_value))
        if isinstance(story_time_value, dict)
        else StoryTime(
            timeline_id="story-time:unspecified",
            start_ordinal=0,
            end_ordinal=0,
            precision="UNSPECIFIED",
        )
        if requires_v3
        else None
    )
    causality = (
        NarrativeCausality.from_dict(dict(causality_value))
        if isinstance(causality_value, dict)
        else _derived_causality(
            state_kind=state_kind,
            identity=identity,
            raw=raw,
            accepted_draft_asset_version_id=accepted_draft_asset_version_id,
            source_asset_version_id=source_asset_version_id,
            supersedes_event_id=supersedes,
        )
        if requires_v3
        else None
    )
    event_version = (
        3
        if requires_v3 and story_time is not None and causality is not None
        else 2
        if not legacy
        and (
            "entity_version" in raw
            or "effective_to_chapter" in raw
            or position is not None
        )
        else 1
    )
    entity_version = int(raw.get("entity_version") or 1)
    canon_status = str(raw.get("canon_status") or "APPROVED_CANON_PATCH")
    return NarrativeStateEvent(
        event_id=_event_id(
            state_kind=state_kind,
            scope=scope,
            identity=identity,
            coordinate=coordinate,
            semantics=semantics,
            payload=payload,
            supersedes_event_id=supersedes,
            provenance=provenance,
            confidence=confidence,
            coverage=coverage,
            evidence=evidence,
            event_version=event_version,
            entity_version=entity_version,
            canon_status=canon_status,
            story_time=story_time,
            causality=causality,
        ),
        state_kind=state_kind,
        scope=scope,
        identity=identity,
        coordinate=coordinate,
        semantics=semantics,
        payload=payload,
        supersedes_event_id=supersedes,
        provenance=provenance,
        confidence=confidence,
        coverage=coverage,
        evidence=evidence,
        event_version=event_version,
        entity_version=entity_version,
        canon_status=canon_status,
        story_time=story_time,
        causality=causality,
    )


def _derived_causality(
    *,
    state_kind: NarrativeStateKind,
    identity: NarrativeIdentity,
    raw: dict[str, Any],
    accepted_draft_asset_version_id: str,
    source_asset_version_id: str,
    supersedes_event_id: str,
) -> NarrativeCausality:
    preconditions = [
        f"{key}={value}"
        for key, value in sorted(raw.items())
        if key.startswith("from_") and value is not None and value != ""
    ]
    preconditions.extend(
        f"requires_fact_id={item}"
        for item in raw.get("requires_fact_ids") or ()
        if str(item)
    )
    if supersedes_event_id:
        preconditions.append(f"supersedes_event_id={supersedes_event_id}")
    effect_kind = (
        "FACT"
        if state_kind is NarrativeStateKind.CANON_FACT
        else "KNOWLEDGE"
        if state_kind
        in {
            NarrativeStateKind.CHARACTER_KNOWLEDGE,
            NarrativeStateKind.CHARACTER_BELIEF,
            NarrativeStateKind.READER_KNOWLEDGE,
        }
        else "OBLIGATION"
        if state_kind
        in {
            NarrativeStateKind.NARRATIVE_OBLIGATION,
            NarrativeStateKind.NARRATIVE_DEBT,
            NarrativeStateKind.FORESHADOW_STATE,
            NarrativeStateKind.READER_PROMISE,
        }
        else "ARC"
        if state_kind
        in {
            NarrativeStateKind.ARC_STATE,
            NarrativeStateKind.CHARACTER_ARC,
            NarrativeStateKind.PLOT_THREAD,
        }
        else "DISCLOSURE"
        if state_kind is NarrativeStateKind.DISCLOSURE_EVENT
        else "PAYOFF"
        if state_kind in {NarrativeStateKind.PAYOFF_EVENT, NarrativeStateKind.REWARD_EVENT}
        else "STATE"
    )
    participant_keys = {
        "character_id",
        "source_id",
        "target_id",
        "entity_id",
        "subject",
        "antagonist_id",
        "faction_id",
        "location_id",
    }
    participants = tuple(
        dict.fromkeys(
            value
            for key, value in identity.components
            if key in participant_keys and value
        )
    ) or (identity.entity_key,)
    return NarrativeCausality(
        cause_refs=(
            accepted_draft_asset_version_id,
            source_asset_version_id,
        ),
        precondition_refs=tuple(preconditions),
        participant_ids=participants,
        effect_kinds=(effect_kind,),
    )


def _event_id(
    *,
    state_kind: NarrativeStateKind,
    scope: NarrativeScope,
    identity: NarrativeIdentity,
    coordinate: NarrativeCoordinate,
    semantics: ReducerSemantics,
    payload: dict[str, Any],
    supersedes_event_id: str,
    provenance: dict[str, Any],
    confidence: float,
    coverage: str,
    evidence: dict[str, Any],
    event_version: int,
    entity_version: int = 1,
    canon_status: str = "APPROVED_CANON_PATCH",
    story_time: StoryTime | None = None,
    causality: NarrativeCausality | None = None,
) -> str:
    seed = {
        "state_kind": state_kind.value,
        "scope": scope.to_dict(),
        "identity": identity.to_dict(),
        "coordinate": coordinate.to_dict(),
        "semantics": semantics.value,
        "payload": payload,
        "supersedes_event_id": supersedes_event_id,
        "provenance": provenance,
        "confidence": confidence,
        "coverage": coverage,
        "evidence": evidence,
        "event_version": event_version,
    }
    if event_version >= 2:
        seed["entity_version"] = entity_version
        seed["canon_status"] = canon_status
    if event_version >= 3:
        if story_time is None or causality is None:
            raise KernelError(
                "NARRATIVE_EVENT_CAUSALITY_REQUIRED",
                "Narrative State event v3 requires Story Time and causal lineage",
            )
        seed["story_time"] = story_time.to_dict()
        seed["causality"] = causality.to_dict()
    digest = hashlib.sha256(_canonical_json(seed).encode()).hexdigest()
    return f"narrative-event:sha256:{digest}"


def _identity_for(
    state_kind: NarrativeStateKind,
    raw: dict[str, Any],
    *,
    ordinal: int,
    source: str,
    allow_legacy_fallback: bool = False,
) -> NarrativeIdentity:
    fields: tuple[str, ...]
    if state_kind is NarrativeStateKind.CANON_FACT:
        fields = ("subject", "predicate")
    elif state_kind is NarrativeStateKind.CHARACTER_STATE:
        fields = ("character_id",)
    elif state_kind in {
        NarrativeStateKind.CHARACTER_KNOWLEDGE,
        NarrativeStateKind.CHARACTER_BELIEF,
    }:
        fields = (
            "character_id",
            "proposition_id" if raw.get("proposition_id") else "fact_id",
        )
    elif state_kind is NarrativeStateKind.CHARACTER_ARC:
        fields = ("character_id", "arc_id")
    elif state_kind is NarrativeStateKind.READER_KNOWLEDGE:
        fields = ("proposition_id" if raw.get("proposition_id") else "fact_id",)
    elif state_kind is NarrativeStateKind.DISCLOSURE_EVENT:
        fields = ("disclosure_id",)
    elif state_kind is NarrativeStateKind.RELATIONSHIP_STATE:
        fields = (
            "source_id" if raw.get("source_id") else "source_character_id",
            "target_id" if raw.get("target_id") else "target_character_id",
        )
    elif state_kind is NarrativeStateKind.WORLD_RULE:
        fields = ("rule_id",)
    elif state_kind is NarrativeStateKind.WORLD_STATE:
        fields = ("world_state_id",)
    elif state_kind is NarrativeStateKind.FACTION_STATE:
        fields = ("faction_id",)
    elif state_kind is NarrativeStateKind.LOCATION_STATE:
        fields = ("location_id",)
    elif state_kind is NarrativeStateKind.CONSEQUENCE_STATE:
        fields = ("consequence_id",)
    elif state_kind is NarrativeStateKind.CONFLICT_STATE:
        fields = ("conflict_id",)
    elif state_kind is NarrativeStateKind.NARRATIVE_OBLIGATION:
        fields = ("obligation_id",)
    elif state_kind is NarrativeStateKind.PAYOFF_EVENT:
        fields = ("payoff_id",)
    elif state_kind is NarrativeStateKind.RESOURCE_STATE:
        fields = ("entity_id", "resource_id")
    elif state_kind is NarrativeStateKind.POWER_STATE:
        fields = ("character_id",)
    elif state_kind in {NarrativeStateKind.FORESHADOW_STATE, NarrativeStateKind.PLOT_THREAD}:
        fields = ("thread_id",)
    elif state_kind is NarrativeStateKind.READER_PROMISE:
        fields = ("promise_id",)
    elif state_kind is NarrativeStateKind.NARRATIVE_DEBT:
        fields = ("debt_id",)
    elif state_kind is NarrativeStateKind.MYSTERY_STATE:
        fields = ("mystery_id",)
    elif state_kind is NarrativeStateKind.ANTAGONIST_STATE:
        fields = ("antagonist_id" if raw.get("antagonist_id") else "entity_id",)
    elif state_kind is NarrativeStateKind.ARC_STATE:
        fields = ("arc_id",)
    elif state_kind is NarrativeStateKind.TIMELINE_EVENT and raw.get("event_id"):
        fields = ("event_id",)
    elif state_kind is NarrativeStateKind.REWARD_EVENT and raw.get("reward_id"):
        fields = ("reward_id",)
    else:
        digest = hashlib.sha256(
            _canonical_json({"source": source, "ordinal": ordinal, "payload": raw}).encode()
        ).hexdigest()
        fields = ("event_id",)
        raw = {**raw, "event_id": f"{state_kind.value}:sha256:{digest}"}
    components = tuple((field, str(raw.get(field) or "").strip()) for field in fields)
    if any(not value for _, value in components):
        if allow_legacy_fallback:
            digest = hashlib.sha256(
                _canonical_json(
                    {
                        "state_kind": state_kind.value,
                        "source": source,
                        "ordinal": ordinal,
                        "payload": raw,
                    }
                ).encode()
            ).hexdigest()
            components = (("legacy_identity", f"sha256:{digest}"),)
            fields = ("legacy_identity",)
        else:
            raise KernelError(
                "NARRATIVE_IDENTITY_REQUIRED",
                f"{state_kind.value} requires identity fields: {', '.join(fields)}",
            )
    entity_key = "|".join(f"{key}={value}" for key, value in components)
    return NarrativeIdentity(state_kind.value, entity_key, components)


def _semantics_for(
    state_kind: NarrativeStateKind, payload: dict[str, Any], supersedes: str
) -> ReducerSemantics:
    if supersedes:
        return ReducerSemantics.SUPERSEDE
    if state_kind in {
        NarrativeStateKind.TIMELINE_EVENT,
        NarrativeStateKind.REWARD_EVENT,
        NarrativeStateKind.THEME_MOVEMENT,
        NarrativeStateKind.PAYOFF_EVENT,
        NarrativeStateKind.DISCLOSURE_EVENT,
    }:
        return ReducerSemantics.APPEND
    if state_kind is NarrativeStateKind.RESOURCE_STATE and payload.get("delta") is not None:
        return (
            ReducerSemantics.DECREMENT
            if float(payload["delta"]) < 0
            else ReducerSemantics.INCREMENT
        )
    status = str(payload.get("status") or "").upper()
    if status in {"OPEN", "PLANTED", "PROMISED", "PROPOSED"}:
        return ReducerSemantics.OPEN
    if status in {
        "PAID",
        "CLOSED",
        "RESOLVED",
        "FULFILLED",
        "CANCELLED",
        "ABANDONED",
    }:
        return ReducerSemantics.CLOSE
    if state_kind is NarrativeStateKind.WORLD_RULE and status in {"ACTIVE", "ACTIVATED"}:
        return ReducerSemantics.ACTIVATE
    if any(
        key in payload
        for key in ("from_state", "from_status", "from_stance", "from_tier")
    ):
        return ReducerSemantics.TRANSITION
    return ReducerSemantics.UPSERT


def _reject_v2_aliases(payload: dict[str, Any]) -> None:
    aliases = {
        "chapter",
        "effective_chapter",
        "supersedes_version_id",
        "supersedes_asset_version_id",
        "state_version_id",
    }
    found = sorted(aliases & set(payload))
    if found:
        raise KernelError(
            "NARRATIVE_V2_ALIAS_FORBIDDEN",
            "v2 Narrative State payload contains legacy aliases: " + ", ".join(found),
        )


def _normalize_obligation(
    raw: dict[str, Any],
    obligation_type: NarrativeObligationType,
    source_chapter: int,
    *,
    legacy_adapter: bool = False,
    legacy_identity_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    value = dict(raw)
    obligation_id = str(
        value.get("obligation_id")
        or next(
            (value.get(field) for field in legacy_identity_fields if value.get(field)),
            "",
        )
        or value.get("promise_id")
        or value.get("thread_id")
        or value.get("mystery_id")
        or value.get("conflict_id")
        or value.get("debt_id")
        or value.get("hook_id")
        or value.get("commitment_id")
        or value.get("expectation_id")
        or ""
    )
    if not obligation_id:
        raise KernelError(
            "NARRATIVE_OBLIGATION_ID_REQUIRED",
            "Narrative obligation requires an explicit stable identity",
        )
    status_alias = str(value.get("status") or "OPEN").upper()
    from_status_alias = str(value.get("from_status") or "").upper()
    status_map = {
        "PLANTED": "OPEN",
        "PROMISED": "OPEN",
        # Legacy plot-thread ACTIVE means that the thread remains open.  It is
        # not evidence that the unified obligation has already advanced from
        # OPEN to DEVELOPING; mapping it to DEVELOPING makes a Chapter 1
        # obligation violate the fail-closed initial-transition invariant.
        "ACTIVE": "OPEN",
        "DEVELOPED": "DEVELOPING",
        "PAID": "FULFILLED",
        "RESOLVED": "FULFILLED",
        "CLOSED": "FULFILLED",
        "ABANDONED": "CANCELLED",
    }
    status = status_map.get(status_alias, status_alias)
    if value.get("from_status") is not None:
        value["from_status"] = status_map.get(
            str(value["from_status"]).upper(), str(value["from_status"]).upper()
        )
    window = value.get("target_window")
    if not isinstance(window, dict):
        target_from = int(
            value.get("target_from_chapter")
            or value.get("due_from_chapter")
            or 0
        )
        target_to = int(
            value.get("target_to_chapter")
            or value.get("due_chapter")
            or 0
        )
        window = {
            "status": "SCHEDULED" if target_from and target_to else "UNSCHEDULED",
            "from_chapter": target_from,
            "to_chapter": target_to,
        }
    payoff = value.get("payoff_evidence")
    if not isinstance(payoff, dict):
        payoff = {}
    excluded = {
        "promise_id",
        "thread_id",
        "mystery_id",
        "conflict_id",
        "debt_id",
        "target_from_chapter",
        "target_to_chapter",
        "due_from_chapter",
        "due_chapter",
        "hook_id",
        "commitment_id",
        "expectation_id",
    }
    current_development = str(
        value.get("current_development")
        or value.get("development")
        or value.get("summary")
        or ""
    )
    development_history = value.get("development_history") or ()
    if not isinstance(development_history, (list, tuple)) or any(
        not isinstance(item, dict) for item in development_history
    ):
        raise KernelError(
            "NARRATIVE_OBLIGATION_DEVELOPMENT_HISTORY_INVALID",
            "Narrative obligation development history must contain typed entries",
        )
    if current_development and not development_history:
        development_history = (
            {
                "chapter": source_chapter,
                "status": status,
                "development": current_development,
            },
        )
    dependencies = value.get("dependencies") or value.get("dependency_ids") or ()
    if not isinstance(dependencies, (list, tuple)):
        raise KernelError(
            "NARRATIVE_OBLIGATION_DEPENDENCIES_INVALID",
            "Narrative obligation dependencies must be a list",
        )
    normalized = {key: item for key, item in value.items() if key not in excluded}
    normalized.update(
        {
            "obligation_id": obligation_id,
            "obligation_type": obligation_type.value,
            "status": status,
            "priority": str(value.get("priority") or "MEDIUM").upper(),
            "target_window": window,
            "introduced_at": (
                dict(value["introduced_at"])
                if isinstance(value.get("introduced_at"), dict)
                else {"chapter": int(value.get("opened_chapter") or source_chapter)}
            ),
            "current_development": current_development,
            "development_history": [dict(item) for item in development_history],
            "dependencies": sorted({str(item) for item in dependencies if str(item)}),
            "urgency": str(
                value.get("urgency") or value.get("priority") or "MEDIUM"
            ).upper(),
            "reader_visibility": str(
                value.get("reader_visibility") or "PARTIAL"
            ).upper(),
            "expected_payoff": (
                dict(value["expected_payoff"])
                if isinstance(value.get("expected_payoff"), dict)
                else {}
            ),
            "actual_payoff": (
                dict(value["actual_payoff"])
                if isinstance(value.get("actual_payoff"), dict)
                else dict(payoff)
            ),
            "overdue": bool(value.get("overdue", False)),
            "stale": bool(value.get("stale", False)),
            "linked_character_ids": sorted(
                {str(item) for item in value.get("linked_character_ids") or () if str(item)}
            ),
            "linked_arc_ids": sorted(
                {str(item) for item in value.get("linked_arc_ids") or () if str(item)}
            ),
            "linked_event_ids": sorted(
                {str(item) for item in value.get("linked_event_ids") or () if str(item)}
            ),
            "linked_volume_ids": sorted(
                {str(item) for item in value.get("linked_volume_ids") or () if str(item)}
            ),
            "payoff_evidence": payoff,
            "resolution_evidence": (
                [dict(item) for item in value.get("resolution_evidence") or ()]
                if isinstance(value.get("resolution_evidence") or (), (list, tuple))
                and all(
                    isinstance(item, dict)
                    for item in value.get("resolution_evidence") or ()
                )
                else []
            ),
            "opened_chapter": int(value.get("opened_chapter") or source_chapter),
            "lifecycle_migration": (
                {
                    "legacy_adapter": True,
                    "source_status": status_alias,
                    "source_from_status": from_status_alias,
                    "target_window_inferred": False,
                }
                if legacy_adapter
                else {}
            ),
            "_legacy_obligation_adapter": legacy_adapter,
        }
    )
    return normalized


def _validate_event_payload(
    state_kind: NarrativeStateKind, payload: dict[str, Any]
) -> None:
    if state_kind is NarrativeStateKind.CHARACTER_KNOWLEDGE:
        if (
            str(payload.get("status") or "").upper()
            not in _CHARACTER_KNOWLEDGE_STATUSES
        ):
            raise KernelError(
                "CHARACTER_KNOWLEDGE_STATUS_INVALID",
                "Character Knowledge requires UNKNOWN, SUSPECTED, KNOWN, or FORGOTTEN",
            )
    if state_kind is NarrativeStateKind.CHARACTER_BELIEF:
        if str(payload.get("stance") or "").upper() not in {
            "BELIEVES",
            "DOUBTS",
            "DISBELIEVES",
            "UNCERTAIN",
        }:
            raise KernelError(
                "CHARACTER_BELIEF_STANCE_INVALID",
                "Character Belief requires a typed stance",
            )
        confidence = payload.get("belief_confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise KernelError(
                "CHARACTER_BELIEF_CONFIDENCE_INVALID",
                "Character Belief confidence must be between zero and one",
            )
    if state_kind is NarrativeStateKind.READER_KNOWLEDGE:
        if str(payload.get("status") or "").upper() not in {
            "UNKNOWN",
            "HINTED",
            "SUSPECTED",
            "KNOWN",
            "MISDIRECTED",
            "CORRECTED",
        }:
            raise KernelError(
                "READER_KNOWLEDGE_STATUS_INVALID",
                "Reader Knowledge requires a typed epistemic status",
            )
    if state_kind is NarrativeStateKind.DISCLOSURE_EVENT:
        if (
            str(payload.get("disclosure_mode") or "").upper()
            not in {"HINT", "PARTIAL", "MISDIRECT", "CONFIRM", "WITHHOLD"}
            or not str(payload.get("audience") or "")
            or not str(payload.get("presentation_channel") or "")
        ):
            raise KernelError(
                "DISCLOSURE_EVENT_CONTRACT_INVALID",
                "Disclosure requires mode, audience, and presentation channel",
            )
    if state_kind is NarrativeStateKind.NARRATIVE_OBLIGATION:
        required = ("obligation_id", "obligation_type", "status", "priority")
        if any(not str(payload.get(key) or "") for key in required):
            raise KernelError(
                "NARRATIVE_OBLIGATION_CONTRACT_INVALID",
                "Narrative obligation identity, type, status, and priority are required",
            )
        try:
            NarrativeObligationType(str(payload["obligation_type"]).upper())
            status = NarrativeObligationStatus(str(payload["status"]).upper())
            NarrativeObligationPriority(str(payload["priority"]).upper())
        except ValueError as exc:
            raise KernelError(
                "NARRATIVE_OBLIGATION_CONTRACT_INVALID",
                "Narrative obligation uses an unsupported type, status, or priority",
            ) from exc
        window = payload.get("target_window")
        if not isinstance(window, dict) or str(window.get("status") or "") not in {
            "SCHEDULED",
            "UNSCHEDULED",
        }:
            raise KernelError(
                "NARRATIVE_OBLIGATION_WINDOW_INVALID",
                "Narrative obligation requires an explicit target-window status",
            )
        start = int(window.get("from_chapter") or 0)
        end = int(window.get("to_chapter") or 0)
        if window["status"] == "SCHEDULED" and (
            start <= 0 or end < start
        ):
            raise KernelError(
                "NARRATIVE_OBLIGATION_WINDOW_INVALID",
                "scheduled obligation window must be positive and ordered",
            )
        legacy_unscheduled = bool(
            payload.get("lifecycle_migration", {}).get("legacy_adapter")
        )
        if (
            status
            in {
                NarrativeObligationStatus.DEVELOPING,
                NarrativeObligationStatus.DUE,
            }
            and window["status"] != "SCHEDULED"
            and not legacy_unscheduled
        ):
            raise KernelError(
                "NARRATIVE_OBLIGATION_WINDOW_REQUIRED",
                "developing or due obligation must have a scheduled target window",
            )
        if str(payload.get("urgency") or "") not in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }:
            raise KernelError(
                "NARRATIVE_OBLIGATION_URGENCY_INVALID",
                "Narrative obligation urgency is invalid",
            )
        if str(payload.get("reader_visibility") or "") not in {
            "HIDDEN",
            "PARTIAL",
            "VISIBLE",
        }:
            raise KernelError(
                "NARRATIVE_OBLIGATION_VISIBILITY_INVALID",
                "Narrative obligation reader visibility is invalid",
            )
        payoff = payload.get("payoff_evidence")
        if status is NarrativeObligationStatus.FULFILLED and (
            not isinstance(payoff, dict)
            or not str(payoff.get("asset_version_id") or "")
            or not str(payoff.get("event_id") or "")
        ):
            raise KernelError(
                "NARRATIVE_OBLIGATION_PAYOFF_EVIDENCE_REQUIRED",
                "fulfilled obligation requires payoff AssetVersion and event evidence",
            )


def _object_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise KernelError(
            "NARRATIVE_CHANGE_SET_INVALID", "Narrative State changes must be an array"
        )
    if any(not isinstance(item, dict) for item in value):
        raise KernelError(
            "NARRATIVE_CHANGE_SET_INVALID", "Narrative State changes must be objects"
        )
    return [dict(item) for item in value]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def event_dicts(events: Iterable[NarrativeStateEvent]) -> list[dict[str, Any]]:
    return [event.to_dict() for event in events]


__all__ = [
    "NarrativeCoordinate",
    "NarrativeIdentity",
    "NarrativeCausality",
    "NarrativeLayer",
    "NarrativeObligationPriority",
    "NarrativeObligationStatus",
    "NarrativeObligationType",
    "NarrativePosition",
    "NarrativeScope",
    "NarrativeStateEvent",
    "NarrativeStateKind",
    "StoryTime",
    "ReducerSemantics",
    "event_dicts",
    "events_from_canon_patch",
    "events_from_chapter_outcome",
]
