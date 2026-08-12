"""Accepted-only, as-of-Chapter projections over Narrative State v2 events."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    NarrativeLayer,
    NarrativeStateEvent,
    NarrativeStateKind,
    project_entity_state,
    reduce_story_state_v2,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class TemporalStateEvent:
    """A v2 event proven accepted by one committed Book chapter boundary."""

    project_id: str
    book_id: str
    book_run_id: str
    acceptance_id: str
    acceptance_operation_id: str
    trace_id: str
    accepted_chapter: int
    chapter_outcome_asset_version_id: str
    event: NarrativeStateEvent
    event_ordinal: int
    recorded_at: str

    def __post_init__(self) -> None:
        if (
            self.project_id != self.event.scope.project_id
            or self.book_id != self.event.scope.book_id
            or self.accepted_chapter != self.event.coordinate.source_chapter
            or self.event.coordinate.effective_from_chapter > self.accepted_chapter
        ):
            raise KernelError(
                "TEMPORAL_ACCEPTANCE_BOUNDARY_INVALID",
                "accepted event scope and chapter must match committed Book acceptance",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "book_id": self.book_id,
            "book_run_id": self.book_run_id,
            "acceptance_id": self.acceptance_id,
            "acceptance_operation_id": self.acceptance_operation_id,
            "trace_id": self.trace_id,
            "accepted_chapter": self.accepted_chapter,
            "chapter_outcome_asset_version_id": (
                self.chapter_outcome_asset_version_id
            ),
            "event_ordinal": self.event_ordinal,
            "authority": {"status": "ACCEPTED", "boundary": "BOOK_CHAPTER"},
            "event": self.event.to_dict(),
            "recorded_at": self.recorded_at,
        }


def changes_in_range(
    events: Iterable[TemporalStateEvent],
    *,
    chapter_from: int,
    chapter_to: int,
) -> tuple[TemporalStateEvent, ...]:
    """Return accepted State Events in the left-open, right-closed range."""

    if chapter_from < 0 or chapter_to <= chapter_from:
        raise ValueError("chapter range must satisfy 0 <= chapter_from < chapter_to")
    return tuple(
        sorted(
            (
                event
                for event in events
                if chapter_from < event.accepted_chapter <= chapter_to
                and event.event.coordinate.effective_from_chapter
                <= event.accepted_chapter
            ),
            key=_event_order,
        )
    )


def reduce_entity_state(
    events: Iterable[TemporalStateEvent],
    *,
    state_kind: str,
    entity_key: str,
    as_of_chapter: int,
) -> dict[str, Any]:
    """Project one entity with the exact same reducers used by current state."""

    if not state_kind or not entity_key or as_of_chapter <= 0:
        raise ValueError("state_kind, entity_key and positive as_of_chapter are required")
    visible = tuple(
        event
        for event in events
        if event.accepted_chapter <= as_of_chapter
        and event.event.coordinate.effective_from_chapter <= as_of_chapter
        and event.event.state_kind.value == state_kind
    )
    snapshot = _rebuild_as_of(visible, as_of_chapter=as_of_chapter)
    result = project_entity_state(snapshot, state_kind, entity_key)
    return {
        **result,
        "as_of_chapter": as_of_chapter,
        "boundary": "INCLUSIVE",
        "accepted_state_only": True,
    }


class TemporalQueryService:
    """Read-only temporal capability rooted in committed Book acceptance."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def state_at(self, project_id: str, book_id: str, chapter: int) -> dict[str, Any]:
        self._validate_scope(project_id, book_id, chapter)
        return _rebuild_as_of(
            self._events(project_id, book_id, through_chapter=chapter),
            as_of_chapter=chapter,
        )

    def character_state_at(
        self, project_id: str, book_id: str, character_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            book_id,
            chapter,
            state_kind="character_state",
            entity_key=f"character_id={character_id}",
        )

    def character_knows_at(
        self,
        project_id: str,
        book_id: str,
        character_id: str,
        fact_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        state = self.character_state_at(project_id, book_id, character_id, chapter)
        known = {
            str(item)
            for item in (state.get("state") or {}).get("known_fact_ids") or ()
        }
        canon = self._collection_at(
            project_id, book_id, chapter, state_kind="canon_fact"
        )
        canon_knows = any(
            str((item.get("state") or {}).get("subject") or "") == character_id
            and str((item.get("state") or {}).get("predicate") or "").lower()
            in {"knows", "knows_fact", "knowledge"}
            and str((item.get("state") or {}).get("object") or "") == fact_id
            for item in canon.get("states") or ()
        )
        knows = fact_id in known or canon_knows
        return {
            "status": "FOUND" if knows else "NOT_FOUND",
            "project_id": project_id,
            "book_id": book_id,
            "state_kind": "character_knowledge",
            "character_id": character_id,
            "fact_id": fact_id,
            "knows": knows,
            "as_of_chapter": chapter,
            "boundary": "INCLUSIVE",
            "accepted_state_only": True,
            "missing_reason": "" if knows else "NO_ACCEPTED_STATE_AT_BOUNDARY",
        }

    def relationship_at(
        self,
        project_id: str,
        book_id: str,
        source_id: str,
        target_id: str,
        chapter: int,
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            book_id,
            chapter,
            state_kind="relationship_state",
            entity_key=f"source_id={source_id}|target_id={target_id}",
        )

    def world_state_at(
        self, project_id: str, book_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._collection_at(
            project_id, book_id, chapter, state_kind="world_rule"
        )

    def power_state_at(
        self, project_id: str, book_id: str, character_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            book_id,
            chapter,
            state_kind="power_state",
            entity_key=f"character_id={character_id}",
        )

    def plot_thread_at(
        self, project_id: str, book_id: str, thread_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            book_id,
            chapter,
            state_kind="plot_thread",
            entity_key=f"thread_id={thread_id}",
        )

    def foreshadow_state_at(
        self, project_id: str, book_id: str, thread_id: str, chapter: int
    ) -> dict[str, Any]:
        return self._entity_at(
            project_id,
            book_id,
            chapter,
            state_kind="foreshadow_state",
            entity_key=f"thread_id={thread_id}",
        )

    def pending_promises_at(
        self, project_id: str, book_id: str, chapter: int
    ) -> dict[str, Any]:
        collection = self._collection_at(
            project_id, book_id, chapter, state_kind="reader_promise"
        )
        pending = [
            item
            for item in collection.get("states") or ()
            if str((item.get("state") or {}).get("status") or "OPEN").upper()
            in {"OPEN", "PLANTED", "PROMISED", "ACTIVE", "DEFERRED"}
        ]
        return {**collection, "states": pending, "promises": pending}

    def changes_between(
        self,
        project_id: str,
        book_id: str,
        chapter_from: int,
        chapter_to: int,
    ) -> dict[str, Any]:
        self._validate_scope(project_id, book_id, chapter_to)
        events = changes_in_range(
            self._events(project_id, book_id, through_chapter=chapter_to),
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
        return {
            "status": "FOUND" if events else "NOT_FOUND",
            "project_id": project_id,
            "book_id": book_id,
            "chapter_from": chapter_from,
            "chapter_to": chapter_to,
            "range_semantics": "LEFT_OPEN_RIGHT_CLOSED_ACCEPTED_CHAPTER",
            "accepted_state_only": True,
            "changes": [event.to_dict() for event in events],
        }

    def _entity_at(
        self,
        project_id: str,
        book_id: str,
        chapter: int,
        *,
        state_kind: str,
        entity_key: str,
    ) -> dict[str, Any]:
        self._validate_scope(project_id, book_id, chapter)
        return {
            "project_id": project_id,
            "book_id": book_id,
            **reduce_entity_state(
                self._events(
                    project_id,
                    book_id,
                    state_kinds=(state_kind,),
                    through_chapter=chapter,
                ),
                state_kind=state_kind,
                entity_key=entity_key,
                as_of_chapter=chapter,
            ),
        }

    def _collection_at(
        self,
        project_id: str,
        book_id: str,
        chapter: int,
        *,
        state_kind: str,
    ) -> dict[str, Any]:
        self._validate_scope(project_id, book_id, chapter)
        snapshot = _rebuild_as_of(
            self._events(
                project_id,
                book_id,
                state_kinds=(state_kind,),
                through_chapter=chapter,
            ),
            as_of_chapter=chapter,
        )
        states = deepcopy((snapshot.get("current_state") or {}).get(state_kind) or [])
        return {
            "status": "FOUND" if states else "NOT_FOUND",
            "project_id": project_id,
            "book_id": book_id,
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
        book_id: str,
        *,
        state_kinds: tuple[str, ...] = (),
        through_chapter: int,
    ) -> tuple[TemporalStateEvent, ...]:
        self._validate_scope(project_id, book_id, through_chapter)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, book_id, book_run_id, acceptance_id,
                       acceptance_operation_id, trace_id, accepted_chapter,
                       chapter_outcome_asset_version_id, event_payload,
                       event_ordinal, recorded_at
                FROM authority_narrative_state_event_projection
                WHERE project_id=%s AND book_id=%s
                  AND accepted_chapter <= %s
                  AND (%s::text[] = '{}'::text[]
                       OR event_payload->>'state_kind'=ANY(%s))
                ORDER BY accepted_chapter, event_ordinal,
                         chapter_outcome_asset_version_id
                """,
                [
                    project_id,
                    book_id,
                    through_chapter,
                    list(state_kinds),
                    list(state_kinds),
                ],
            )
            rows = uow.cursor.fetchall()
        return tuple(_event_from_row(row) for row in rows)

    @staticmethod
    def _validate_scope(project_id: str, book_id: str, chapter: int) -> None:
        if not project_id.strip() or not book_id.strip() or chapter <= 0:
            raise ValueError("project_id, book_id and a positive chapter are required")


def _rebuild_as_of(
    events: Iterable[TemporalStateEvent], *, as_of_chapter: int
) -> dict[str, Any]:
    ordered = sorted(events, key=_event_order)
    state: dict[str, Any] | None = None
    index = 0
    while index < len(ordered):
        head = ordered[index]
        group: list[TemporalStateEvent] = []
        while index < len(ordered):
            candidate = ordered[index]
            if (
                candidate.accepted_chapter != head.accepted_chapter
                or candidate.chapter_outcome_asset_version_id
                != head.chapter_outcome_asset_version_id
            ):
                break
            group.append(candidate)
            index += 1
        outcome_id = str(group[0].event.provenance.get("chapter_outcome_id") or "")
        state = reduce_story_state_v2(
            previous=state,
            events=tuple(item.event for item in group),
            chapter_outcome_asset_version_id=head.chapter_outcome_asset_version_id,
            chapter_outcome_id=outcome_id,
        )
    if state is None:
        current_state = {kind.value: [] for kind in NarrativeStateKind}
        state = {
            "type": "TemporalNarrativeStateProjection",
            "contract_version": "temporal-narrative-state-v2",
            "project_id": "",
            "book_id": "",
            "current_state": current_state,
            "accepted_through_chapter": 0,
        }
    else:
        state = deepcopy(state)
        state["type"] = "TemporalNarrativeStateProjection"
        state["contract_version"] = "temporal-narrative-state-v2"
    state["layer"] = NarrativeLayer.TEMPORAL_PROJECTION.value
    state["as_of_chapter"] = as_of_chapter
    state["boundary"] = "INCLUSIVE"
    state["accepted_state_only"] = True
    return state


def _event_from_row(row: tuple[Any, ...]) -> TemporalStateEvent:
    return TemporalStateEvent(
        project_id=str(row[0]),
        book_id=str(row[1]),
        book_run_id=str(row[2]),
        acceptance_id=str(row[3]),
        acceptance_operation_id=str(row[4]),
        trace_id=str(row[5]),
        accepted_chapter=int(row[6]),
        chapter_outcome_asset_version_id=str(row[7]),
        event=NarrativeStateEvent.from_dict(dict(row[8])),
        event_ordinal=int(row[9]),
        recorded_at=str(row[10]),
    )


def _event_order(event: TemporalStateEvent) -> tuple[int, int, str, int]:
    return (
        event.accepted_chapter,
        event.event.coordinate.effective_from_chapter,
        event.chapter_outcome_asset_version_id,
        event.event_ordinal,
    )


__all__ = [
    "TemporalQueryService",
    "TemporalStateEvent",
    "changes_in_range",
    "reduce_entity_state",
]
