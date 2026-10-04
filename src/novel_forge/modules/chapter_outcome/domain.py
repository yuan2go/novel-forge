from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.longform_narrative import normalize_arc_evidence
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
    expected_arc_contributions: tuple[dict[str, Any], ...] = (),
    work_requirements: bool = False,
) -> dict[str, Any]:

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
    if not state_events and not work_requirements:
        raise KernelError(
            "CHAPTER_OUTCOME_STATE_EVENT_REQUIRED",
            "accepted ChapterOutcome requires at least one governed Narrative State event",
        )
    declared_arcs: dict[str, dict[str, Any]] = {}
    for contribution in expected_arc_contributions:
        arc_plan_version_id = str(
            contribution.get("arc_plan_version_id")
            or contribution.get("arc_id")
            or ""
        )
        if not arc_plan_version_id or arc_plan_version_id in declared_arcs:
            raise KernelError(
                "CHAPTER_OUTCOME_ARC_PLAN_INVALID",
                "ChapterOutcome requires unique expected Arc contribution identities",
            )
        declared_arcs[arc_plan_version_id] = dict(contribution)
    raw_arc_evidence = canon_patch.get("arc_evidence") or ()
    if not isinstance(raw_arc_evidence, (list, tuple)):
        raise KernelError(
            "CHAPTER_OUTCOME_ARC_EVIDENCE_INVALID",
            "qualified Arc evidence must be a list",
        )
    normalized_arc_evidence = normalize_arc_evidence(
        declared=declared_arcs,
        raw_evidence=(dict(item) for item in raw_arc_evidence if isinstance(item, dict)),
    )
    event_payloads = event_dicts(state_events)
    scene_outcomes = canon_patch.get("scene_outcomes") or ()
    if not isinstance(scene_outcomes, (list, tuple)) or any(
        not isinstance(item, dict) for item in scene_outcomes
    ):
        raise KernelError(
            "CHAPTER_OUTCOME_SCENE_EVIDENCE_INVALID",
            "Scene outcomes must be typed objects",
        )
    realization_evidence = canon_patch.get("realization_evidence") or ()
    if not isinstance(realization_evidence, (list, tuple)) or any(
        not isinstance(item, dict) for item in realization_evidence
    ):
        raise KernelError(
            "CHAPTER_OUTCOME_REALIZATION_EVIDENCE_INVALID",
            "Narrative Realization evidence must be typed objects",
        )
    return {
        "type": "ChapterOutcome",
        "contract_version": "chapter-outcome-v4" if work_requirements else "chapter-outcome-v3",
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
        **({"grounding": dict(canon_patch["grounding"])} if canon_patch.get("grounding") else {}),
        "canon_decision_asset_version_ids": list(
            canon_patch.get("decision_asset_version_ids") or []
        ),
        "state_events": event_payloads,
        "arc_evidence": list(normalized_arc_evidence),
        "obligation_events": [
            event
            for event in event_payloads
            if event.get("state_kind") == "narrative_obligation"
        ],
        "scene_outcomes": [dict(item) for item in scene_outcomes],
        "realization_evidence": [dict(item) for item in realization_evidence],
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
        outcome_scope=chapter_outcome if chapter_outcome.get("contract_version") == "chapter-outcome-v4" else None,
    )


__all__ = ["build_chapter_outcome", "reduce_story_state"]
