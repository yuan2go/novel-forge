"""Shared Narrative State v2 contracts, reducers, and read projections."""

from .contracts import (
    NarrativeCoordinate,
    NarrativeIdentity,
    NarrativeLayer,
    NarrativeScope,
    NarrativeStateEvent,
    NarrativeStateKind,
    ReducerSemantics,
    event_dicts,
    events_from_canon_patch,
    events_from_chapter_outcome,
)
from .reducers import (
    APPEND_ONLY_KINDS,
    LIFECYCLE_KINDS,
    STATE_KIND_REDUCER_SEMANTICS,
    compact_current_state_facts,
    materialize_canon_snapshot_v2,
    project_entity_state,
    rebuild_story_state,
    reduce_story_state_v2,
)
from .rebuild import NarrativeProjectionRebuildResult, NarrativeStateRebuildService

__all__ = [
    "NarrativeCoordinate",
    "NarrativeIdentity",
    "NarrativeLayer",
    "NarrativeScope",
    "NarrativeStateEvent",
    "NarrativeStateKind",
    "NarrativeProjectionRebuildResult",
    "NarrativeStateRebuildService",
    "ReducerSemantics",
    "APPEND_ONLY_KINDS",
    "LIFECYCLE_KINDS",
    "STATE_KIND_REDUCER_SEMANTICS",
    "compact_current_state_facts",
    "materialize_canon_snapshot_v2",
    "event_dicts",
    "events_from_canon_patch",
    "events_from_chapter_outcome",
    "project_entity_state",
    "rebuild_story_state",
    "reduce_story_state_v2",
]
