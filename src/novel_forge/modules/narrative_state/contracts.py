"""Narrative State v2 identity, temporal, lineage, and event contracts."""
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

    def __post_init__(self) -> None:
        if (
            self.source_chapter <= 0
            or self.effective_from_chapter <= 0
            or self.effective_from_chapter > self.source_chapter
        ):
            raise KernelError(
                "NARRATIVE_TEMPORAL_BOUNDARY_INVALID",
                "Narrative State effective boundary must be positive, non-future, and ordered",
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "source_chapter": self.source_chapter,
            "effective_from_chapter": self.effective_from_chapter,
        }


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

    def __post_init__(self) -> None:
        if not self.event_id.startswith("narrative-event:sha256:"):
            raise KernelError(
                "NARRATIVE_EVENT_ID_INVALID", "Narrative event ID must be content-derived"
            )
        if not 0 <= self.confidence <= 1 or not self.coverage:
            raise KernelError(
                "NARRATIVE_EVIDENCE_INVALID",
                "Narrative State confidence and coverage are required",
            )
        _reject_v2_aliases(self.payload)
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
        )
        if self.event_id != expected:
            raise KernelError(
                "NARRATIVE_EVENT_INTEGRITY_FAILED",
                "Narrative event ID does not match its immutable semantic content",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "contract_version": "narrative-state-event-v2",
            "layer": NarrativeLayer.STATE_EVENT.value,
            "state_kind": self.state_kind.value,
            "scope": self.scope.to_dict(),
            "identity": self.identity.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "authority": {
                "status": "PENDING_BOOK_ACCEPTANCE",
                "required_boundary": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
            },
            "mutation": {
                "semantics": self.semantics.value,
                "payload": _deep_copy(self.payload),
            },
            "version": {"event_contract": self.event_version},
            "supersession": {"supersedes_event_id": self.supersedes_event_id},
            "provenance": _deep_copy(self.provenance),
            "confidence": self.confidence,
            "coverage": self.coverage,
            "evidence": _deep_copy(self.evidence),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NarrativeStateEvent:
        if value.get("contract_version") != "narrative-state-event-v2":
            raise KernelError(
                "NARRATIVE_EVENT_CONTRACT_UNSUPPORTED",
                "only Narrative State event v2 is accepted by the production reducer",
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
            ),
            semantics=semantics,
            payload=payload,
            supersedes_event_id=str(supersession.get("supersedes_event_id") or ""),
            provenance=dict(value.get("provenance") or {}),
            confidence=float(value.get("confidence", 0.0)),
            coverage=str(value.get("coverage") or ""),
            evidence=dict(value.get("evidence") or {}),
            event_version=int((value.get("version") or {}).get("event_contract") or 0),
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
}

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
    """Normalize governed Canon changes into the sole v2 event vocabulary."""

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
            changes[kind].extend(_object_items(values))
    for kind, fields in _PATCH_FIELDS.items():
        if changes[kind]:
            continue
        for field in fields:
            changes[kind].extend(_object_items(canon_patch.get(field)))
    for snapshot in _object_items(canon_patch.get("snapshot_candidates")):
        kind = _SNAPSHOT_KIND_ALIASES.get(str(snapshot.get("state_kind") or ""))
        if kind is not None and not changes[kind]:
            changes[kind].extend(_object_items(snapshot.get("changes")))

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
    """Read v2 events or deterministically adapt immutable v1 evidence."""

    contract = str(chapter_outcome.get("contract_version") or "")
    if contract == "chapter-outcome-v2":
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
    coordinate = NarrativeCoordinate(
        source_chapter=source_chapter,
        effective_from_chapter=effective_from,
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
    payload = {
        key: _deep_copy(value)
        for key, value in raw.items()
        if key
        not in {
            "effective_from_chapter",
            "effective_chapter",
            "chapter",
            "supersedes_event_id",
            "supersedes_version_id",
            "supersedes_asset_version_id",
            "confidence",
            "coverage",
            "extraction_evidence",
            "evidence",
        }
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
            event_version=1,
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
    elif state_kind is NarrativeStateKind.RELATIONSHIP_STATE:
        fields = (
            "source_id" if raw.get("source_id") else "source_character_id",
            "target_id" if raw.get("target_id") else "target_character_id",
        )
    elif state_kind is NarrativeStateKind.WORLD_RULE:
        fields = ("rule_id",)
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
    }:
        return ReducerSemantics.APPEND
    if state_kind is NarrativeStateKind.RESOURCE_STATE and payload.get("delta") is not None:
        return (
            ReducerSemantics.DECREMENT
            if float(payload["delta"]) < 0
            else ReducerSemantics.INCREMENT
        )
    status = str(payload.get("status") or "").upper()
    if status in {"OPEN", "PLANTED", "PROMISED"}:
        return ReducerSemantics.OPEN
    if status in {"PAID", "CLOSED", "RESOLVED", "CANCELLED", "ABANDONED"}:
        return ReducerSemantics.CLOSE
    if state_kind is NarrativeStateKind.WORLD_RULE and status in {"ACTIVE", "ACTIVATED"}:
        return ReducerSemantics.ACTIVATE
    if any(key in payload for key in ("from_state", "from_status", "from_tier")):
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
    "NarrativeLayer",
    "NarrativeScope",
    "NarrativeStateEvent",
    "NarrativeStateKind",
    "ReducerSemantics",
    "event_dicts",
    "events_from_canon_patch",
    "events_from_chapter_outcome",
]
