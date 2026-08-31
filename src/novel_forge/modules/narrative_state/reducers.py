from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Iterable, Sequence

from novel_forge.modules.command_kernel.errors import KernelError

from .contracts import (
    NarrativeLayer,
    NarrativeStateEvent,
    NarrativeStateKind,
    ReducerSemantics,
    events_from_chapter_outcome,
)


APPEND_ONLY_KINDS = frozenset(
    {
        NarrativeStateKind.TIMELINE_EVENT,
        NarrativeStateKind.REWARD_EVENT,
        NarrativeStateKind.THEME_MOVEMENT,
        NarrativeStateKind.PAYOFF_EVENT,
        NarrativeStateKind.DISCLOSURE_EVENT,
    }
)

LIFECYCLE_KINDS = frozenset(
    {
        NarrativeStateKind.FORESHADOW_STATE,
        NarrativeStateKind.READER_PROMISE,
        NarrativeStateKind.PLOT_THREAD,
        NarrativeStateKind.NARRATIVE_DEBT,
        NarrativeStateKind.MYSTERY_STATE,
        NarrativeStateKind.ARC_STATE,
        NarrativeStateKind.CHARACTER_ARC,
        NarrativeStateKind.CONFLICT_STATE,
        NarrativeStateKind.NARRATIVE_OBLIGATION,
    }
)

TERMINAL_STATUSES = frozenset(
    {
        "PAID",
        "CLOSED",
        "RESOLVED",
        "FULFILLED",
        "CANCELLED",
        "ABANDONED",
        "DEAD",
        "INACTIVE",
    }
)

# INVARIANT: extraction metadata is not narrative truth; Context carries source
# event identity and an evidence digest rather than duplicating it per fact.
CONTEXT_OMITTED_OPERATIONAL_STATE_FIELDS = frozenset(
    {
        "approval_resolution",
        "approval_requirement",
        "change_reasons",
        "evidence_end",
        "evidence_start",
        "extractor_type",
        "model_id",
        "prompt_version",
        "provider_id",
        "source_revision_asset_version_id",
    }
)

STATE_KIND_REDUCER_SEMANTICS: dict[NarrativeStateKind, str] = {
    NarrativeStateKind.CANON_FACT: "supersession-aware-upsert",
    NarrativeStateKind.TIMELINE_EVENT: "append-only-event",
    NarrativeStateKind.CHARACTER_STATE: "entity-aware-attribute-upsert",
    NarrativeStateKind.RELATIONSHIP_STATE: "entity-aware-lifecycle-transition",
    NarrativeStateKind.WORLD_RULE: "activate-or-explicitly-supersede",
    NarrativeStateKind.RESOURCE_STATE: "validated-balance-transition",
    NarrativeStateKind.POWER_STATE: "entity-aware-tier-transition",
    NarrativeStateKind.FORESHADOW_STATE: "open-close-lifecycle",
    NarrativeStateKind.READER_PROMISE: "open-close-lifecycle",
    NarrativeStateKind.PLOT_THREAD: "open-close-lifecycle",
    NarrativeStateKind.NARRATIVE_DEBT: "open-resolved-lifecycle",
    NarrativeStateKind.MYSTERY_STATE: "open-close-lifecycle",
    NarrativeStateKind.ANTAGONIST_STATE: "entity-aware-upsert",
    NarrativeStateKind.ARC_STATE: "open-close-lifecycle",
    NarrativeStateKind.REWARD_EVENT: "append-only-event",
    NarrativeStateKind.THEME_MOVEMENT: "append-only-event",
    NarrativeStateKind.CHARACTER_KNOWLEDGE: "fact-bound-knowledge-transition",
    NarrativeStateKind.CHARACTER_BELIEF: "proposition-bound-belief-transition",
    NarrativeStateKind.CHARACTER_ARC: "character-arc-lifecycle-transition",
    NarrativeStateKind.READER_KNOWLEDGE: "reader-epistemic-transition",
    NarrativeStateKind.DISCLOSURE_EVENT: "append-only-presentation-evidence",
    NarrativeStateKind.WORLD_STATE: "world-entity-aware-upsert",
    NarrativeStateKind.FACTION_STATE: "faction-entity-aware-transition",
    NarrativeStateKind.LOCATION_STATE: "location-entity-aware-transition",
    NarrativeStateKind.CONSEQUENCE_STATE: "event-consequence-lifecycle-transition",
    NarrativeStateKind.CONFLICT_STATE: "conflict-lifecycle-transition",
    NarrativeStateKind.NARRATIVE_OBLIGATION: "unified-obligation-lifecycle",
    NarrativeStateKind.PAYOFF_EVENT: "append-only-payoff-evidence",
}


def reduce_story_state_v2(
    *,
    previous: dict[str, Any] | None,
    events: Sequence[NarrativeStateEvent],
    chapter_outcome_asset_version_id: str,
    chapter_outcome_id: str,
    previous_story_state_asset_version_id: str = "",
) -> dict[str, Any]:
    """INVARIANT: Apply one accepted ChapterOutcome event set to the current projection.

    The reducer never mutates evidence. It is strict about chapter order and the
    Project/Book scope, so replay and live acceptance use the same semantics.
    """
    if not chapter_outcome_asset_version_id or not chapter_outcome_id:
        raise KernelError(
            "NARRATIVE_OUTCOME_LINEAGE_REQUIRED",
            "Story State reduction requires ChapterOutcome identity and AssetVersion",
        )
    if not events:
        raise KernelError(
            "NARRATIVE_EVENT_SET_REQUIRED",
            "accepted ChapterOutcome must contain at least one Narrative State event",
        )

    source_chapter = events[0].coordinate.source_chapter
    project_id = events[0].scope.project_id
    book_id = events[0].scope.book_id
    for event in events:
        if (
            event.coordinate.source_chapter != source_chapter
            or event.scope.project_id != project_id
            or event.scope.book_id != book_id
            or event.provenance.get("chapter_outcome_id") != chapter_outcome_id
        ):
            raise KernelError(
                "NARRATIVE_EVENT_SET_INCONSISTENT",
                "one reducer application must contain one Outcome, chapter, Project and Book",
            )

    prior = deepcopy(previous) if previous else None
    if prior:
        _validate_previous_snapshot(prior, project_id=project_id, book_id=book_id)
        latest_version = str(prior.get("based_on_chapter_outcome_asset_version_id") or "")
        if latest_version == chapter_outcome_asset_version_id:
            expected_event_ids = {
                str(item.get("event_id") or "")
                for item in prior.get("reducer_applications") or ()
            }
            actual_event_ids = {event.event_id for event in events}
            if (
                prior.get("based_on_chapter_outcome_id") != chapter_outcome_id
                or int(prior.get("accepted_through_chapter") or 0)
                != source_chapter
                or expected_event_ids != actual_event_ids
            ):
                raise KernelError(
                    "NARRATIVE_IDEMPOTENT_REPLAY_MISMATCH",
                    "replayed ChapterOutcome identity or event set differs from current head",
                )
            return prior
        accepted_through = int(prior.get("accepted_through_chapter") or 0)
        if source_chapter <= accepted_through:
            raise KernelError(
                "NARRATIVE_REPLAY_OUT_OF_ORDER",
                "Story State accepts strictly increasing accepted ChapterOutcome chapters",
            )
    else:
        accepted_through = 0

    current = _indexed_current_state(prior)
    _expire_effective_ranges(current, at_chapter=source_chapter)
    applications: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    for event in events:
        if event.event_id in seen_event_ids:
            raise KernelError(
                "NARRATIVE_EVENT_DUPLICATE",
                f"duplicate event in ChapterOutcome: {event.event_id}",
            )
        seen_event_ids.add(event.event_id)
        kind_state = current[event.state_kind]
        old = kind_state.get(event.identity.entity_key)
        new = _apply_event(old, event)
        kind_state[event.identity.entity_key] = new
        if event.state_kind in {
            NarrativeStateKind.FORESHADOW_STATE,
            NarrativeStateKind.READER_PROMISE,
        }:
            _synchronize_narrative_debt(current, event, new)
        applications.append(
            {
                "event_id": event.event_id,
                "state_kind": event.state_kind.value,
                "entity_key": event.identity.entity_key,
                "reducer_semantics": STATE_KIND_REDUCER_SEMANTICS[event.state_kind],
                "transition_hash": _transition_hash(old, event, new),
                "chapter_outcome_asset_version_id": chapter_outcome_asset_version_id,
                "reducer_key": f"{event.state_kind.value}:{event.identity.entity_key}",
                "input_contract_version": (
                    "narrative-state-event-v3"
                    if event.event_version >= 3
                    else "narrative-state-event-v2"
                ),
                "output_state_type": event.state_kind.value,
                "idempotency_key": event.event_id,
                "validation_policy": "narrative-state-reducer-v2",
                "dependencies": [],
                "accepted_chapter": source_chapter,
            }
        )

    state_version = int((prior or {}).get("state_version") or 0) + 1
    for application in applications:
        application["current_state_version"] = state_version
    snapshot: dict[str, Any] = {
        "type": "StoryStateSnapshot",
        "contract_version": "story-state-snapshot-v2",
        "layer": NarrativeLayer.CURRENT_STATE.value,
        "project_id": project_id,
        "book_id": book_id,
        "scope": {"project_id": project_id, "book_id": book_id},
        "accepted_through_chapter": source_chapter,
        "chapter": source_chapter,
        "chapter_number": source_chapter,
        "state_version": state_version,
        "based_on_chapter_outcome_asset_version_id": chapter_outcome_asset_version_id,
        "based_on_chapter_outcome_id": chapter_outcome_id,
        "previous_story_state_asset_version_id": previous_story_state_asset_version_id,
        "current_state": _serialized_current_state(current),
        "reducer_applications": applications,
        "accepted_state_only": True,
        "replayable_from": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
    }
    snapshot["state_hash"] = _state_hash(snapshot)
    return snapshot


def rebuild_story_state(
    accepted_outcomes: Iterable[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:

    state: dict[str, Any] | None = None
    previous_chapter = 0
    for asset_version_id, outcome in accepted_outcomes:
        chapter = int(outcome.get("chapter_number") or 0)
        if chapter <= previous_chapter:
            raise KernelError(
                "NARRATIVE_REPLAY_OUT_OF_ORDER",
                "accepted ChapterOutcome replay input must be strictly chapter ordered",
            )
        events = events_from_chapter_outcome(asset_version_id, outcome)
        state = reduce_story_state_v2(
            previous=state,
            events=events,
            chapter_outcome_asset_version_id=asset_version_id,
            chapter_outcome_id=str(outcome.get("chapter_outcome_id") or ""),
        )
        previous_chapter = chapter
    return state or _empty_snapshot()


def project_entity_state(
    snapshot: dict[str, Any], state_kind: str, entity_key: str
) -> dict[str, Any]:

    try:
        kind = NarrativeStateKind(state_kind)
    except ValueError as exc:
        raise KernelError(
            "NARRATIVE_STATE_KIND_UNSUPPORTED", f"unsupported state kind: {state_kind}"
        ) from exc
    for entry in (snapshot.get("current_state") or {}).get(kind.value) or ():
        if isinstance(entry, dict) and entry.get("entity_key") == entity_key:
            return {"status": "FOUND", **deepcopy(entry)}
    return {
        "status": "NOT_FOUND",
        "state_kind": kind.value,
        "entity_key": entity_key,
        "accepted_through_chapter": int(snapshot.get("accepted_through_chapter") or 0),
        "missing_reason": "NO_ACCEPTED_STATE_AT_BOUNDARY",
        "state": None,
    }


def compact_current_state_facts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:

    if snapshot.get("contract_version") != "story-state-snapshot-v2":
        raise KernelError(
            "STORY_STATE_CONTRACT_UNSUPPORTED",
            "execution context accepts only compact Story State snapshot v2",
        )
    facts: list[dict[str, Any]] = []
    current = snapshot.get("current_state") or {}
    for kind in NarrativeStateKind:
        # INVARIANT: Canon has its own accepted snapshot in every continuing Context, and
        # event-ledger dimensions are requested explicitly through Temporal
        # Query.  Repeating either here would reintroduce unbounded history and
        # duplicate truth into the normal generation context.
        if kind is NarrativeStateKind.CANON_FACT or kind in APPEND_ONLY_KINDS:
            continue
        for entry in current.get(kind.value) or ():
            if not isinstance(entry, dict):
                raise KernelError(
                    "STORY_STATE_SNAPSHOT_INVALID",
                    "current state entries must be objects",
                )
            facts.append(
                _compact_context_fact(
                    entry,
                    state_kind=kind.value,
                )
            )
    return facts


def compact_canon_facts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:

    if snapshot.get("contract_version") != "canon-snapshot-v2":
        raise KernelError(
            "CANON_SNAPSHOT_CONTRACT_UNSUPPORTED",
            "execution context accepts only compact Canon snapshot v2",
        )
    facts: list[dict[str, Any]] = []
    for entry in snapshot.get("current_facts") or ():
        if not isinstance(entry, dict):
            raise KernelError(
                "CANON_SNAPSHOT_INVALID",
                "current Canon facts must be objects",
            )
        facts.append(_compact_context_fact(entry))
    return facts


def _compact_context_fact(
    entry: dict[str, Any], *, state_kind: str = ""
) -> dict[str, Any]:
    state = {
        str(key): deepcopy(value)
        for key, value in (entry.get("state") or {}).items()
        if key not in CONTEXT_OMITTED_OPERATIONAL_STATE_FIELDS
    }
    evidence = deepcopy(entry.get("evidence") or {})
    fact = {
        "entity_key": str(entry.get("entity_key") or ""),
        "entity_version": int(entry.get("entity_version") or 0),
        "state": state,
        "effective_from_chapter": int(entry.get("effective_from_chapter") or 0),
        "effective_to_chapter": int(entry.get("effective_to_chapter") or 0),
        "narrative_position": deepcopy(entry.get("narrative_position") or {}),
        "source_chapter": int(entry.get("source_chapter") or 0),
        "source_event_id": str(entry.get("source_event_id") or ""),
        "confidence": float(entry.get("confidence", 0.0)),
        "coverage": str(entry.get("coverage") or ""),
        "evidence_digest": "sha256:"
        + hashlib.sha256(_canonical_json(evidence).encode()).hexdigest(),
        "canon_status": str(entry.get("canon_status") or ""),
    }
    if state_kind:
        fact = {"state_kind": state_kind, **fact}
    return fact


def materialize_canon_snapshot_v2(
    *,
    story_state: dict[str, Any],
    chapter_outcome_asset_version_id: str,
    previous_canon_asset_version_id: str = "",
) -> dict[str, Any]:

    if story_state.get("contract_version") != "story-state-snapshot-v2":
        raise KernelError(
            "STORY_STATE_CONTRACT_UNSUPPORTED",
            "Canon v2 materialization requires Story State snapshot v2",
        )
    if (
        story_state.get("based_on_chapter_outcome_asset_version_id")
        != chapter_outcome_asset_version_id
    ):
        raise KernelError(
            "CANON_OUTCOME_LINEAGE_MISMATCH",
            "Canon and Story State must derive from the same ChapterOutcome",
        )
    current_facts = deepcopy(
        (story_state.get("current_state") or {}).get(
            NarrativeStateKind.CANON_FACT.value
        )
        or []
    )
    snapshot: dict[str, Any] = {
        "type": "CanonSnapshot",
        "contract_version": "canon-snapshot-v2",
        "layer": NarrativeLayer.TRUTH.value,
        "authority": {
            "status": "PENDING_BOOK_ACCEPTANCE",
            "required_boundary": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
        },
        "project_id": str(story_state.get("project_id") or ""),
        "book_id": str(story_state.get("book_id") or ""),
        "scope": deepcopy(story_state.get("scope") or {}),
        "accepted_through_chapter": int(
            story_state.get("accepted_through_chapter") or 0
        ),
        "chapter": int(story_state.get("accepted_through_chapter") or 0),
        "current_facts": current_facts,
        "based_on_chapter_outcome_asset_version_id": chapter_outcome_asset_version_id,
        "previous_canon_asset_version_id": previous_canon_asset_version_id,
        "story_state_hash": str(story_state.get("state_hash") or ""),
        "accepted_state_only": True,
        "rebuildable_from": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
    }
    snapshot["canon_hash"] = _state_hash(snapshot)
    return snapshot


def _apply_event(
    previous: dict[str, Any] | None, event: NarrativeStateEvent
) -> dict[str, Any]:
    if event.supersedes_event_id:
        if not previous or previous.get("source_event_id") != event.supersedes_event_id:
            raise KernelError(
                "NARRATIVE_SUPERSESSION_TARGET_INVALID",
                "supersession must name the current event for the same Narrative identity",
            )
    elif event.semantics is ReducerSemantics.SUPERSEDE:
        raise KernelError(
            "NARRATIVE_SUPERSESSION_TARGET_INVALID",
            "SUPERSEDE mutation requires supersedes_event_id",
        )

    old_state = deepcopy((previous or {}).get("state") or {})
    payload = deepcopy(event.payload)
    _resolve_legacy_active_obligation(old_state, payload, event)
    expected_entity_version = int((previous or {}).get("entity_version") or 0) + 1
    if event.event_version >= 2 and event.entity_version != expected_entity_version:
        raise KernelError(
            "NARRATIVE_ENTITY_VERSION_CONFLICT",
            "Narrative entity version must advance exactly once from accepted state",
        )
    if event.state_kind in APPEND_ONLY_KINDS:
        if previous:
            raise KernelError(
                "NARRATIVE_APPEND_EVENT_ID_COLLISION",
                "append-only Narrative events require unique event identity",
            )
        new_state = payload
    elif event.state_kind is NarrativeStateKind.RESOURCE_STATE:
        new_state = _reduce_resource(old_state, payload)
    else:
        _validate_transition(old_state, payload, event)
        _validate_character_lifecycle(old_state, payload, event)
        _validate_immutable_definition(old_state, payload, event)
        _validate_obligation_transition(old_state, payload, event)
        new_state = _merge_state(old_state, payload, event.state_kind)

    return {
        "identity": event.identity.to_dict(),
        "entity_key": event.identity.entity_key,
        "entity_version": expected_entity_version,
        "state": new_state,
        "source_event_id": event.event_id,
        "source_chapter": event.coordinate.source_chapter,
        "effective_from_chapter": event.coordinate.effective_from_chapter,
        "effective_to_chapter": event.coordinate.effective_to_chapter,
        "narrative_position": (
            event.coordinate.position.to_dict()
            if event.coordinate.position is not None
            else {"chapter": event.coordinate.source_chapter}
        ),
        "supersedes_event_id": event.supersedes_event_id,
        "provenance": deepcopy(event.provenance),
        "confidence": event.confidence,
        "coverage": event.coverage,
        "evidence": deepcopy(event.evidence),
        "canon_status": event.canon_status,
    }


def _reduce_resource(old: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("delta") is None:
        if "balance" not in payload:
            raise KernelError(
                "NARRATIVE_RESOURCE_BALANCE_REQUIRED",
                "initial Resource State requires balance",
            )
        new = {**old, **payload}
        new["balance"] = _number(payload["balance"])
        return new
    if "balance" not in old:
        raise KernelError(
            "NARRATIVE_RESOURCE_STATE_MISSING",
            "resource delta cannot apply before an accepted balance exists",
        )
    before = _number(payload.get("balance_before"))
    current = _number(old["balance"])
    delta = _number(payload["delta"])
    after = _number(payload.get("balance_after"))
    if before != current or before + delta != after:
        raise KernelError(
            "NARRATIVE_RESOURCE_BALANCE_INVALID",
            "resource before, delta and after must reconcile with current accepted state",
        )
    new = {**old, **payload, "balance": after}
    return new


def _validate_transition(
    old: dict[str, Any], payload: dict[str, Any], event: NarrativeStateEvent
) -> None:
    for from_key, current_key in (
        ("from_status", "status"),
        ("from_state", "state"),
        ("from_tier", "tier"),
    ):
        if from_key in payload:
            if current_key not in old or str(payload[from_key]) != str(old[current_key]):
                raise KernelError(
                    "NARRATIVE_TRANSITION_PRECONDITION_FAILED",
                    f"{event.state_kind.value} {from_key} does not match current state",
                )
    if event.state_kind in LIFECYCLE_KINDS:
        previous_status = str(old.get("status") or "").upper()
        next_status = str(payload.get("status") or previous_status).upper()
        if previous_status in TERMINAL_STATUSES and next_status != previous_status:
            raise KernelError(
                "NARRATIVE_TERMINAL_STATE_REOPEN_FORBIDDEN",
                f"{event.state_kind.value} terminal state cannot reopen without new identity",
            )


def _validate_immutable_definition(
    old: dict[str, Any], payload: dict[str, Any], event: NarrativeStateEvent
) -> None:
    if not old or event.supersedes_event_id:
        return
    immutable_fields: tuple[str, ...] = ()
    if event.state_kind is NarrativeStateKind.CANON_FACT:
        immutable_fields = ("object",)
    elif event.state_kind is NarrativeStateKind.WORLD_RULE:
        immutable_fields = ("definition",)
    for field in immutable_fields:
        if field in old and field in payload and old[field] != payload[field]:
            raise KernelError(
                "NARRATIVE_EXPLICIT_SUPERSESSION_REQUIRED",
                f"changing {event.state_kind.value}.{field} requires explicit supersession",
            )


def _validate_character_lifecycle(
    old: dict[str, Any], payload: dict[str, Any], event: NarrativeStateEvent
) -> None:
    """INVARIANT: Keep death/invalidation terminal unless Authority explicitly corrects it.

    A superseding event means the prior accepted assertion itself was replaced.
    An ordinary later upsert cannot silently turn a dead character alive again;
    an in-story return must be modeled as an explicit, reviewable transition on
    a new semantic identity rather than erasing accepted history.
    """
    if event.state_kind is not NarrativeStateKind.CHARACTER_STATE:
        return
    previous = str(old.get("life_status") or old.get("status") or "").upper()
    following = str(
        payload.get("life_status") or payload.get("status") or previous
    ).upper()
    if previous in {"DEAD", "INVALIDATED"} and following != previous:
        if not event.supersedes_event_id:
            raise KernelError(
                "NARRATIVE_CHARACTER_TERMINAL_STATE_REOPEN_FORBIDDEN",
                "dead or invalidated character state requires explicit supersession",
            )


def _validate_obligation_transition(
    old: dict[str, Any], payload: dict[str, Any], event: NarrativeStateEvent
) -> None:
    if event.state_kind is not NarrativeStateKind.NARRATIVE_OBLIGATION:
        return
    previous = str(old.get("status") or "").upper()
    following = str(payload.get("status") or previous).upper()
    if not previous:
        if following not in {"PROPOSED", "OPEN"}:
            raise KernelError(
                "NARRATIVE_OBLIGATION_INITIAL_STATUS_INVALID",
                "new Narrative obligation must start as PROPOSED or OPEN",
            )
        return
    allowed = {
        "PROPOSED": {"PROPOSED", "OPEN", "CANCELLED"},
        "OPEN": {"OPEN", "DEVELOPING", "DUE", "FULFILLED", "CANCELLED"},
        "DEVELOPING": {"DEVELOPING", "DUE", "FULFILLED", "CANCELLED"},
        "DUE": {"DUE", "FULFILLED", "CANCELLED"},
        "FULFILLED": {"FULFILLED"},
        "CANCELLED": {"CANCELLED"},
    }
    if following not in allowed.get(previous, set()):
        raise KernelError(
            "NARRATIVE_OBLIGATION_TRANSITION_INVALID",
            f"Narrative obligation cannot transition from {previous} to {following}",
        )


def _resolve_legacy_active_obligation(
    old: dict[str, Any], payload: dict[str, Any], event: NarrativeStateEvent
) -> None:

    if event.state_kind is not NarrativeStateKind.NARRATIVE_OBLIGATION:
        return
    migration = payload.get("lifecycle_migration")
    if (
        not isinstance(migration, dict)
        or not migration.get("legacy_adapter")
        or str(migration.get("source_status") or "").upper() != "ACTIVE"
    ):
        return
    previous = str(old.get("status") or "").upper()
    progress_vocabulary = " ".join(
        str(payload.get(key) or "").upper() for key in ("state", "transition_kind")
    )
    explicit_progress = any(
        marker in progress_vocabulary for marker in ("DEVELOP", "PROGRESS", "ADVANC")
    )
    if explicit_progress:
        payload["status"] = "DEVELOPING"
    elif previous:
        payload["status"] = previous
    else:
        payload["status"] = "OPEN"
    if previous and str(migration.get("source_from_status") or "").upper() == "ACTIVE":
        payload["from_status"] = previous


def _merge_state(
    old: dict[str, Any], payload: dict[str, Any], kind: NarrativeStateKind
) -> dict[str, Any]:
    new = {**old, **payload}
    for key in ("from_status", "from_state", "from_tier"):
        new.pop(key, None)
    if kind is NarrativeStateKind.CHARACTER_STATE:
        known = {str(item) for item in old.get("known_fact_ids") or ()}
        known.update(str(item) for item in payload.get("acquired_fact_ids") or ())
        known.difference_update(str(item) for item in payload.get("forgotten_fact_ids") or ())
        if known or "known_fact_ids" in old or "acquired_fact_ids" in payload:
            new["known_fact_ids"] = sorted(known)
        new.pop("acquired_fact_ids", None)
        new.pop("forgotten_fact_ids", None)
    if kind is NarrativeStateKind.NARRATIVE_OBLIGATION:
        history = [dict(item) for item in old.get("development_history") or ()]
        seen = {
            (
                int(item.get("chapter") or 0),
                str(item.get("status") or ""),
                str(item.get("development") or ""),
            )
            for item in history
        }
        for item in payload.get("development_history") or ():
            normalized = dict(item)
            identity = (
                int(normalized.get("chapter") or 0),
                str(normalized.get("status") or ""),
                str(normalized.get("development") or ""),
            )
            if identity not in seen:
                history.append(normalized)
                seen.add(identity)
        new["development_history"] = history
    return new


def _synchronize_narrative_debt(
    current: dict[NarrativeStateKind, dict[str, dict[str, Any]]],
    event: NarrativeStateEvent,
    source_entry: dict[str, Any],
) -> None:
    source_status = str(source_entry["state"].get("status") or "OPEN").upper()
    debt_key = (
        f"source_kind={event.state_kind.value}|source_entity_key="
        f"{event.identity.entity_key}"
    )
    previous = current[NarrativeStateKind.NARRATIVE_DEBT].get(debt_key)
    status = "RESOLVED" if source_status in TERMINAL_STATUSES else "OPEN"
    current[NarrativeStateKind.NARRATIVE_DEBT][debt_key] = {
        "identity": {
            "identity_kind": NarrativeStateKind.NARRATIVE_DEBT.value,
            "entity_key": debt_key,
            "components": {
                "source_kind": event.state_kind.value,
                "source_entity_key": event.identity.entity_key,
            },
        },
        "entity_key": debt_key,
        "entity_version": int((previous or {}).get("entity_version") or 0) + 1,
        "state": {
            "source_kind": event.state_kind.value,
            "source_entity_key": event.identity.entity_key,
            "status": status,
        },
        "source_event_id": event.event_id,
        "source_chapter": event.coordinate.source_chapter,
        "effective_from_chapter": event.coordinate.effective_from_chapter,
        "supersedes_event_id": str((previous or {}).get("source_event_id") or ""),
        "provenance": deepcopy(event.provenance),
        "confidence": event.confidence,
        "coverage": event.coverage,
        "evidence": deepcopy(event.evidence),
        "derived_from_lifecycle": True,
    }


def _validate_previous_snapshot(
    previous: dict[str, Any], *, project_id: str, book_id: str
) -> None:
    if previous.get("contract_version") != "story-state-snapshot-v2":
        raise KernelError(
            "STORY_STATE_CONTRACT_UNSUPPORTED",
            "production reduction accepts only Story State snapshot v2",
        )
    if previous.get("project_id") != project_id or previous.get("book_id") != book_id:
        raise KernelError(
            "NARRATIVE_SCOPE_MISMATCH",
            "Story State Project/Book scope must match every accepted event",
        )
    expected_hash = str(previous.get("state_hash") or "")
    if not expected_hash or expected_hash != _state_hash(previous):
        raise KernelError(
            "STORY_STATE_INTEGRITY_FAILED",
            "previous Story State content hash does not verify",
        )


def _indexed_current_state(
    previous: dict[str, Any] | None,
) -> dict[NarrativeStateKind, dict[str, dict[str, Any]]]:
    result: dict[NarrativeStateKind, dict[str, dict[str, Any]]] = {
        kind: {} for kind in NarrativeStateKind
    }
    for kind in NarrativeStateKind:
        entries = ((previous or {}).get("current_state") or {}).get(kind.value) or ()
        for raw in entries:
            if not isinstance(raw, dict) or not raw.get("entity_key"):
                raise KernelError(
                    "STORY_STATE_SNAPSHOT_INVALID",
                    f"invalid current entry for {kind.value}",
                )
            key = str(raw["entity_key"])
            if key in result[kind]:
                raise KernelError(
                    "STORY_STATE_SNAPSHOT_INVALID",
                    f"duplicate materialized entity for {kind.value}: {key}",
                )
            result[kind][key] = deepcopy(raw)
    return result


def _serialized_current_state(
    current: dict[NarrativeStateKind, dict[str, dict[str, Any]]]
) -> dict[str, list[dict[str, Any]]]:
    return {
        kind.value: [deepcopy(entries[key]) for key in sorted(entries)]
        for kind, entries in current.items()
    }


def expire_effective_ranges(
    snapshot: dict[str, Any], *, at_chapter: int
) -> dict[str, Any]:

    if at_chapter <= 0:
        raise ValueError("positive narrative chapter is required")
    projected = deepcopy(snapshot)
    current = projected.get("current_state")
    if not isinstance(current, dict):
        raise KernelError(
            "STORY_STATE_SNAPSHOT_INVALID", "current_state must be an object"
        )
    for kind in NarrativeStateKind:
        if kind in APPEND_ONLY_KINDS:
            continue
        current[kind.value] = [
            item
            for item in current.get(kind.value) or ()
            if not int(item.get("effective_to_chapter") or 0)
            or int(item.get("effective_to_chapter") or 0) >= at_chapter
        ]
    return projected


def _expire_effective_ranges(
    current: dict[NarrativeStateKind, dict[str, dict[str, Any]]],
    *,
    at_chapter: int,
) -> None:
    for kind, entries in current.items():
        if kind in APPEND_ONLY_KINDS:
            continue
        expired = [
            key
            for key, item in entries.items()
            if int(item.get("effective_to_chapter") or 0)
            and int(item.get("effective_to_chapter") or 0) < at_chapter
        ]
        for key in expired:
            del entries[key]


def _transition_hash(
    previous: dict[str, Any] | None,
    event: NarrativeStateEvent,
    current: dict[str, Any],
) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(
            {"previous": previous, "event": event.to_dict(), "current": current}
        ).encode()
    ).hexdigest()


def _state_hash(snapshot: dict[str, Any]) -> str:
    payload = {key: value for key, value in snapshot.items() if key != "state_hash"}
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KernelError(
            "NARRATIVE_RESOURCE_BALANCE_INVALID",
            "resource balances and deltas must be numeric",
        )
    return value


def _empty_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "type": "StoryStateSnapshot",
        "contract_version": "story-state-snapshot-v2",
        "layer": NarrativeLayer.CURRENT_STATE.value,
        "project_id": "",
        "book_id": "",
        "scope": {"project_id": "", "book_id": ""},
        "accepted_through_chapter": 0,
        "chapter": 0,
        "chapter_number": 0,
        "state_version": 0,
        "based_on_chapter_outcome_asset_version_id": "",
        "based_on_chapter_outcome_id": "",
        "previous_story_state_asset_version_id": "",
        "current_state": {kind.value: [] for kind in NarrativeStateKind},
        "reducer_applications": [],
        "accepted_state_only": True,
        "replayable_from": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
    }
    snapshot["state_hash"] = _state_hash(snapshot)
    return snapshot


__all__ = [
    "APPEND_ONLY_KINDS",
    "LIFECYCLE_KINDS",
    "STATE_KIND_REDUCER_SEMANTICS",
    "compact_canon_facts",
    "compact_current_state_facts",
    "expire_effective_ranges",
    "materialize_canon_snapshot_v2",
    "project_entity_state",
    "rebuild_story_state",
    "reduce_story_state_v2",
]
