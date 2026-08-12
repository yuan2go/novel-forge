"""Accepted-state, as-of Chapter queries over PostgreSQL Authority evidence.

The service is a read model.  It does not own Canon state and cannot activate,
supersede, or roll back an AssetVersion.  Its only source is the immutable
Chapter acceptance boundary and the state snapshot outputs accepted there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class TemporalStateEvent:
    project_id: str
    book_id: str
    book_run_id: str
    acceptance_id: str
    operation_id: str
    trace_id: str
    accepted_chapter: int
    state_kind: str
    asset_type: str
    asset_version_id: str
    effective_chapter: int
    payload: dict[str, Any]
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "book_id": self.book_id,
            "book_run_id": self.book_run_id,
            "acceptance_id": self.acceptance_id,
            "operation_id": self.operation_id,
            "trace_id": self.trace_id,
            "accepted_chapter": self.accepted_chapter,
            "state_kind": self.state_kind,
            "asset_type": self.asset_type,
            "asset_version_id": self.asset_version_id,
            "effective_chapter": self.effective_chapter,
            "payload": dict(self.payload),
            "recorded_at": self.recorded_at,
        }


def changes_in_range(
    events: Iterable[TemporalStateEvent],
    *,
    chapter_from: int,
    chapter_to: int,
) -> tuple[TemporalStateEvent, ...]:
    """Return accepted events in the left-open, right-closed chapter range."""

    if chapter_from < 0 or chapter_to <= chapter_from:
        raise ValueError("chapter range must satisfy 0 <= chapter_from < chapter_to")
    return tuple(
        sorted(
            (
                event
                for event in events
                if chapter_from < event.effective_chapter <= chapter_to
                and event.accepted_chapter <= chapter_to
                and event.effective_chapter <= event.accepted_chapter
            ),
            key=_event_order,
        )
    )


def reduce_entity_state(
    events: Iterable[TemporalStateEvent],
    *,
    state_kind: str,
    identity: tuple[str, Any],
    as_of_chapter: int,
) -> dict[str, Any]:
    """Reduce one typed entity using only accepted events visible at the boundary."""

    if not state_kind or as_of_chapter <= 0:
        raise ValueError("state_kind and a positive as_of_chapter are required")
    visible = [
        event
        for event in events
        if event.state_kind == state_kind
        and event.accepted_chapter <= as_of_chapter
        and event.effective_chapter <= as_of_chapter
        and event.effective_chapter <= event.accepted_chapter
        and _matches_identity(event.payload, identity)
    ]
    visible.sort(key=_event_order)
    if not visible:
        return _missing(state_kind, as_of_chapter)

    active: list[TemporalStateEvent] = []
    superseded: set[str] = set()
    for event in visible:
        supersedes = str(
            event.payload.get("supersedes_version_id")
            or event.payload.get("supersedes_asset_version_id")
            or ""
        )
        if supersedes:
            superseded.add(supersedes)
            active = [item for item in active if _event_lineage_id(item) != supersedes]
        active.append(event)

    state: dict[str, Any] = {}
    for event in active:
        state.update(_state_payload(event.payload))
    return {
        "status": "FOUND",
        "state_kind": state_kind,
        "as_of_chapter": as_of_chapter,
        "boundary": "INCLUSIVE",
        "accepted_state_only": True,
        "missing_reason": "",
        "state": state,
        "source_asset_version_ids": [
            event.asset_version_id
            for event in active
            if event.asset_version_id not in superseded
        ],
        "source_operation_ids": sorted(
            {event.operation_id for event in active if event.operation_id}
        ),
        "trace_ids": sorted({event.trace_id for event in active if event.trace_id}),
        "superseded_asset_version_ids": sorted(superseded),
        "observed_through_chapter": max(event.effective_chapter for event in active),
    }


class TemporalQueryService:
    """Production read service for the governed ``temporal.query`` capability."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def character_state_at(
        self, project_id: str, character_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            chapter,
            state_kind="character_state",
            identity=("character_id", character_id),
        )

    def character_knows_at(
        self, project_id: str, character_id: str, fact_id: str, chapter: int
    ) -> dict[str, Any]:
        events = self._events(
            project_id,
            state_kinds=("character_state", "canon_snapshot"),
            through_chapter=chapter,
        )
        evidence = [
            event
            for event in events
            if _is_knowledge_event(event.payload, character_id, fact_id)
        ]
        evidence.sort(key=_event_order)
        if not evidence:
            return {
                **_missing("character_knowledge", chapter),
                "project_id": project_id,
                "character_id": character_id,
                "fact_id": fact_id,
                "knows": False,
            }
        latest = evidence[-1]
        knowledge_state = str(
            latest.payload.get("knowledge_state")
            or latest.payload.get("status")
            or "KNOWN"
        ).upper()
        return {
            "status": "FOUND",
            "project_id": project_id,
            "state_kind": "character_knowledge",
            "as_of_chapter": chapter,
            "boundary": "INCLUSIVE",
            "accepted_state_only": True,
            "missing_reason": "",
            "character_id": character_id,
            "fact_id": fact_id,
            "knows": knowledge_state in {"KNOWN", "ACQUIRED", "ACTIVE", "TRUE"},
            "knowledge_state": knowledge_state,
            "source_asset_version_ids": [latest.asset_version_id],
            "source_operation_ids": [latest.operation_id],
            "trace_ids": [latest.trace_id],
            "superseded_asset_version_ids": [],
            "observed_through_chapter": latest.effective_chapter,
        }

    def relationship_at(
        self,
        project_id: str,
        source_id: str,
        target_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            chapter,
            state_kind="relationship_state",
            identity=("relationship", (source_id, target_id)),
        )

    def world_state_at(self, project_id: str, chapter: int) -> dict[str, Any]:
        return self._collection_at(project_id, chapter, state_kind="world_rule")

    def power_state_at(
        self, project_id: str, character_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            chapter,
            state_kind="power_state",
            identity=("character_id", character_id),
        )

    def plot_thread_at(
        self, project_id: str, thread_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            chapter,
            state_kind="plot_thread",
            identity=("thread_id", thread_id),
        )

    def foreshadow_state_at(
        self, project_id: str, thread_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            chapter,
            state_kind="foreshadow_state",
            identity=("thread_id", thread_id),
        )

    def pending_promises_at(self, project_id: str, chapter: int) -> dict[str, Any]:
        collection = self._collection_at(
            project_id, chapter, state_kind="reader_promise"
        )
        if collection["status"] == "NOT_FOUND":
            return {**collection, "promises": []}
        pending = [
            item
            for item in collection["states"]
            if str(item["state"].get("status") or "OPEN").upper()
            in {"OPEN", "PLANTED", "PROMISED", "ACTIVE", "DEFERRED"}
        ]
        return {**collection, "states": pending, "promises": pending}

    def changes_between(
        self, project_id: str, chapter_from: int, chapter_to: int
    ) -> dict[str, Any]:
        self._validate_scope(project_id, chapter_to)
        events = changes_in_range(
            self._events(project_id, through_chapter=chapter_to),
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
        return {
            "status": "FOUND" if events else "NOT_FOUND",
            "project_id": project_id,
            "chapter_from": chapter_from,
            "chapter_to": chapter_to,
            "range_semantics": "LEFT_OPEN_RIGHT_CLOSED",
            "accepted_state_only": True,
            "changes": [event.to_dict() for event in events],
        }

    def _entity_at(
        self,
        project_id: str,
        chapter: int,
        *,
        state_kind: str,
        identity: tuple[str, Any],
    ) -> dict[str, Any]:
        self._validate_scope(project_id, chapter)
        return {
            "project_id": project_id,
            **reduce_entity_state(
                self._events(
                    project_id,
                    state_kinds=(state_kind,),
                    through_chapter=chapter,
                ),
                state_kind=state_kind,
                identity=identity,
                as_of_chapter=chapter,
            ),
        }

    def _collection_at(
        self, project_id: str, chapter: int, *, state_kind: str
    ) -> dict[str, Any]:
        self._validate_scope(project_id, chapter)
        events = self._events(
            project_id,
            state_kinds=(state_kind,),
            through_chapter=chapter,
        )
        identities = sorted(
            {
                _collection_identity(state_kind, event.payload)
                for event in events
                if _collection_identity(state_kind, event.payload)
            }
        )
        states = [
            reduce_entity_state(
                events,
                state_kind=state_kind,
                identity=("collection_identity", identity),
                as_of_chapter=chapter,
            )
            for identity in identities
        ]
        return {
            "status": "FOUND" if states else "NOT_FOUND",
            "project_id": project_id,
            "state_kind": state_kind,
            "as_of_chapter": chapter,
            "boundary": "INCLUSIVE",
            "accepted_state_only": True,
            "missing_reason": "" if states else "NO_ACCEPTED_STATE_AT_BOUNDARY",
            "states": states,
        }

    def _events(
        self,
        project_id: str,
        *,
        state_kinds: tuple[str, ...] = (),
        through_chapter: int,
    ) -> tuple[TemporalStateEvent, ...]:
        self._validate_scope(project_id, through_chapter)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, book_id, book_run_id, acceptance_id,
                       operation_id, trace_id, accepted_chapter, state_kind,
                       asset_type, asset_version_id, payload, recorded_at
                FROM authority_temporal_state_event_projection
                WHERE project_id=%s
                  AND accepted_chapter <= %s
                  AND (%s::text[] = '{}'::text[] OR state_kind=ANY(%s))
                ORDER BY accepted_chapter, recorded_at, asset_version_id,
                         event_ordinal
                """,
                [project_id, through_chapter, list(state_kinds), list(state_kinds)],
            )
            rows = uow.cursor.fetchall()
        events = tuple(_event_from_row(row) for row in rows)
        return tuple(
            event
            for event in events
            if event.effective_chapter <= event.accepted_chapter
            and event.effective_chapter <= through_chapter
        )

    @staticmethod
    def _validate_scope(project_id: str, chapter: int) -> None:
        if not project_id.strip() or chapter <= 0:
            raise ValueError("project_id and a positive chapter are required")


def _event_from_row(row: tuple[Any, ...]) -> TemporalStateEvent:
    payload = dict(row[10])
    raw_chapter = payload.get("effective_chapter", payload.get("chapter", row[6]))
    try:
        effective_chapter = int(raw_chapter)
    except (TypeError, ValueError) as exc:
        raise KernelError(
            "TEMPORAL_STATE_CHAPTER_INVALID",
            "accepted state event has an invalid effective chapter",
        ) from exc
    if effective_chapter <= 0:
        raise KernelError(
            "TEMPORAL_STATE_CHAPTER_INVALID",
            "accepted state event has a non-positive effective chapter",
        )
    return TemporalStateEvent(
        project_id=str(row[0]),
        book_id=str(row[1]),
        book_run_id=str(row[2]),
        acceptance_id=str(row[3]),
        operation_id=str(row[4]),
        trace_id=str(row[5]),
        accepted_chapter=int(row[6]),
        state_kind=str(row[7]),
        asset_type=str(row[8]),
        asset_version_id=str(row[9]),
        effective_chapter=effective_chapter,
        payload=payload,
        recorded_at=str(row[11]),
    )


def _event_order(event: TemporalStateEvent) -> tuple[int, int, str, str]:
    return (
        event.effective_chapter,
        event.accepted_chapter,
        event.recorded_at,
        event.asset_version_id,
    )


def _event_lineage_id(event: TemporalStateEvent) -> str:
    return str(
        event.payload.get("source_asset_version_id")
        or event.payload.get("state_version_id")
        or event.asset_version_id
    )


def _matches_identity(payload: dict[str, Any], identity: tuple[str, Any]) -> bool:
    kind, value = identity
    if kind == "relationship":
        source_id, target_id = value
        return (
            str(payload.get("source_id") or payload.get("source_character_id") or "")
            == source_id
            and str(
                payload.get("target_id") or payload.get("target_character_id") or ""
            )
            == target_id
        )
    if kind == "collection_identity":
        return value in {
            str(payload.get(key) or "")
            for key in (
                "rule_id",
                "promise_id",
                "thread_id",
                "entity_id",
                "character_id",
                "state_id",
                "subject",
            )
        }
    return str(payload.get(kind) or payload.get("entity_id") or "") == str(value)


def _collection_identity(state_kind: str, payload: dict[str, Any]) -> str:
    keys = {
        "world_rule": ("rule_id", "state_id", "subject"),
        "reader_promise": ("promise_id", "thread_id", "subject"),
    }.get(state_kind, ("entity_id", "thread_id", "character_id", "subject"))
    return next((str(payload.get(key)) for key in keys if payload.get(key)), "")


def _state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    controls = {
        "effective_chapter",
        "chapter",
        "supersedes_version_id",
        "supersedes_asset_version_id",
    }
    return {key: value for key, value in payload.items() if key not in controls}


def _is_knowledge_event(
    payload: dict[str, Any], character_id: str, fact_id: str
) -> bool:
    direct = (
        str(payload.get("character_id") or payload.get("entity_id") or "")
        == character_id
        and str(payload.get("fact_id") or "") == fact_id
    )
    canon_fact = (
        str(payload.get("subject") or "") == character_id
        and str(payload.get("predicate") or "").lower()
        in {"knows", "knows_fact", "knowledge"}
        and str(payload.get("object") or "") == fact_id
    )
    return direct or canon_fact


def _missing(state_kind: str, chapter: int) -> dict[str, Any]:
    return {
        "status": "NOT_FOUND",
        "state_kind": state_kind,
        "as_of_chapter": chapter,
        "boundary": "INCLUSIVE",
        "accepted_state_only": True,
        "missing_reason": "NO_ACCEPTED_STATE_AT_BOUNDARY",
        "state": None,
        "source_asset_version_ids": [],
        "source_operation_ids": [],
        "trace_ids": [],
        "superseded_asset_version_ids": [],
        "observed_through_chapter": None,
    }


__all__ = [
    "TemporalQueryService",
    "TemporalStateEvent",
    "changes_in_range",
    "reduce_entity_state",
]
