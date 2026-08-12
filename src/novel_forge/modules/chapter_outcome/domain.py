"""Accepted ChapterOutcome and deterministic Narrative State v2 reduction."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    event_dicts,
    events_from_canon_patch,
    events_from_chapter_outcome,
    reduce_story_state_v2,
)


def build_chapter_outcome(
    *,
    project_id: str,
    book_id: str,
    chapter_number: int,
    chapter_plan_version_id: str,
    parent_group_version_id: str,
    accepted_draft_version_id: str,
    final_release_gate_version_id: str,
    quality_aggregate_version_id: str,
    canon_patch_asset_version_id: str,
    canon_patch: dict[str, Any],
    cost_receipt_refs: tuple[str, ...],
    created_by_operation_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Build immutable accepted-actual evidence before Book acceptance commits it."""

    if (
        not project_id
        or not book_id
        or chapter_number <= 0
        or not chapter_plan_version_id
        or not accepted_draft_version_id
        or not final_release_gate_version_id
        or not quality_aggregate_version_id
        or not canon_patch_asset_version_id
        or not created_by_operation_id
        or not trace_id
        or canon_patch.get("gate") != "PASSED"
        or canon_patch.get("conflicts")
    ):
        raise KernelError(
            "CHAPTER_OUTCOME_PRECONDITION_FAILED",
            "ChapterOutcome requires accepted release, frozen plan, quality, lineage, and clear Canon",
        )
    chapter_outcome_id = (
        f"chapter-outcome:{book_id}:{chapter_number}:{chapter_plan_version_id}"
    )
    state_events = events_from_canon_patch(
        project_id=project_id,
        book_id=book_id,
        source_chapter=chapter_number,
        chapter_outcome_id=chapter_outcome_id,
        canon_patch_asset_version_id=canon_patch_asset_version_id,
        accepted_draft_asset_version_id=accepted_draft_version_id,
        source_operation_id=created_by_operation_id,
        trace_id=trace_id,
        canon_patch=canon_patch,
    )
    if not state_events:
        raise KernelError(
            "CHAPTER_OUTCOME_STATE_EVENT_REQUIRED",
            "accepted ChapterOutcome requires at least one governed Narrative State event",
        )
    return {
        "type": "ChapterOutcome",
        "contract_version": "chapter-outcome-v2",
        "layer": "ACCEPTED_ACTUAL",
        "authority": {
            "status": "PENDING_BOOK_ACCEPTANCE",
            "required_boundary": "COMMITTED_BOOK_CHAPTER_ACCEPTANCE",
        },
        "chapter_outcome_id": chapter_outcome_id,
        "project_id": project_id,
        "book_id": book_id,
        "chapter_number": chapter_number,
        "chapter_plan_version_id": chapter_plan_version_id,
        "parent_group_version_id": parent_group_version_id,
        "accepted_draft_asset_version_id": accepted_draft_version_id,
        "final_release_gate_asset_version_id": final_release_gate_version_id,
        "quality_aggregate_asset_version_id": quality_aggregate_version_id,
        "canon_patch_asset_version_id": canon_patch_asset_version_id,
        "canon_decision_asset_version_ids": list(
            canon_patch.get("decision_asset_version_ids") or []
        ),
        "state_events": event_dicts(state_events),
        "reader_state_observations": list(
            canon_patch.get("reader_state_signals") or []
        ),
        "cost_receipt_refs": list(cost_receipt_refs),
        "source_operation_id": created_by_operation_id,
        "trace_id": trace_id,
    }


def reduce_story_state(
    *,
    previous: dict[str, Any] | None,
    chapter_outcome: dict[str, Any],
    chapter_outcome_asset_version_id: str,
    previous_story_state_asset_version_id: str = "",
) -> dict[str, Any]:
    """Canonical production reduction using Narrative State v2 semantics."""

    events = events_from_chapter_outcome(
        chapter_outcome_asset_version_id,
        chapter_outcome,
        trace_id=str(chapter_outcome.get("trace_id") or ""),
    )
    return reduce_story_state_v2(
        previous=previous,
        events=events,
        chapter_outcome_asset_version_id=chapter_outcome_asset_version_id,
        chapter_outcome_id=str(chapter_outcome.get("chapter_outcome_id") or ""),
        previous_story_state_asset_version_id=previous_story_state_asset_version_id,
    )


__all__ = ["build_chapter_outcome", "reduce_story_state"]
