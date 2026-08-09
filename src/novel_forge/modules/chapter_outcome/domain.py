"""Pure ChapterOutcome extraction and deterministic Story State reduction."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


STATE_FIELDS = (
    "timeline",
    "characters",
    "relationships",
    "world",
    "resources",
    "power",
    "foreshadows",
    "mysteries",
    "promises",
    "rewards",
    "narrative_debt",
    "theme",
    "antagonist",
    "arc_state",
)


@dataclass(frozen=True, slots=True)
class StoryStateReducerDefinition:
    reducer_key: str
    outcome_field: str
    output_state_type: str
    dependencies: tuple[str, ...] = ()
    input_contract_version: str = "chapter-outcome-v1"
    validation_policy: str = "append-only-deterministic-v1"


STORY_STATE_REDUCERS = (
    StoryStateReducerDefinition("timeline_event", "occurred_events", "timeline"),
    StoryStateReducerDefinition("character_state", "character_deltas", "characters"),
    StoryStateReducerDefinition(
        "relationship_state", "relationship_deltas", "relationships"
    ),
    StoryStateReducerDefinition("world_state", "world_deltas", "world"),
    StoryStateReducerDefinition("resource_state", "resource_deltas", "resources"),
    StoryStateReducerDefinition("power_state", "power_deltas", "power"),
    StoryStateReducerDefinition(
        "foreshadow_state", "foreshadow_actions", "foreshadows"
    ),
    StoryStateReducerDefinition("mystery_state", "mystery_actions", "mysteries"),
    StoryStateReducerDefinition(
        "reader_promise", "promise_actions", "promises"
    ),
    StoryStateReducerDefinition("reward", "reward_actions", "rewards"),
    StoryStateReducerDefinition(
        "narrative_debt",
        "narrative_debt_actions",
        "narrative_debt",
        ("foreshadow_state", "reader_promise"),
    ),
    StoryStateReducerDefinition("theme_movement", "theme_movements", "theme"),
    StoryStateReducerDefinition(
        "antagonist_adaptation", "antagonist_actions", "antagonist"
    ),
    StoryStateReducerDefinition(
        "arc_contribution", "arc_contributions", "arc_state"
    ),
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
    canon_patch: dict[str, Any],
    cost_receipt_refs: tuple[str, ...],
    created_by_operation_id: str,
) -> dict[str, Any]:
    if (
        not project_id
        or not book_id
        or chapter_number <= 0
        or not chapter_plan_version_id
        or not accepted_draft_version_id
        or not final_release_gate_version_id
        or not quality_aggregate_version_id
        or canon_patch.get("gate") != "PASSED"
        or canon_patch.get("conflicts")
    ):
        raise KernelError(
            "CHAPTER_OUTCOME_PRECONDITION_FAILED",
            "ChapterOutcome requires accepted release, frozen plan, quality, and clear Canon",
        )
    snapshots = {
        str(item.get("state_kind")): list(item.get("changes") or [])
        for item in canon_patch.get("snapshot_candidates") or []
        if isinstance(item, dict)
    }
    foreshadow_actions = list(
        snapshots.get("foreshadow_state")
        or canon_patch.get("foreshadow_actions")
        or []
    )
    promise_actions = list(
        snapshots.get("reader_promise")
        or canon_patch.get("reader_promise_actions")
        or []
    )
    narrative_debt = [
        {
            "debt_type": debt_type,
            "source": dict(item),
            "status": str(item.get("status") or "OPEN"),
        }
        for debt_type, actions in (
            ("FORESHADOW", foreshadow_actions),
            ("READER_PROMISE", promise_actions),
        )
        for item in actions
        if str(item.get("status") or "OPEN")
        not in {"PAID", "CLOSED", "RESOLVED"}
    ]
    return {
        "type": "ChapterOutcome",
        "contract_version": "chapter-outcome-v1",
        "chapter_outcome_id": (
            f"chapter-outcome:{book_id}:{chapter_number}:"
            f"{chapter_plan_version_id}"
        ),
        "project_id": project_id,
        "book_id": book_id,
        "chapter_number": chapter_number,
        "chapter_plan_version_id": chapter_plan_version_id,
        "parent_group_version_id": parent_group_version_id,
        "accepted_draft_version_id": accepted_draft_version_id,
        "final_release_gate_version_id": final_release_gate_version_id,
        "quality_aggregate_version_id": quality_aggregate_version_id,
        "canon_decision_refs": list(canon_patch.get("decision_asset_version_ids") or []),
        "occurred_events": list(
            snapshots.get("timeline_snapshot")
            or canon_patch.get("events")
            or []
        ),
        "character_deltas": list(
            snapshots.get("character_state")
            or canon_patch.get("character_state_changes")
            or []
        ),
        "relationship_deltas": list(
            snapshots.get("relationship_state")
            or canon_patch.get("relationship_changes")
            or []
        ),
        "world_deltas": list(
            snapshots.get("world_rule")
            or canon_patch.get("world_state_changes")
            or []
        ),
        "resource_deltas": list(canon_patch.get("resource_changes") or []),
        "power_deltas": list(
            snapshots.get("power_state")
            or canon_patch.get("power_state_changes")
            or []
        ),
        "foreshadow_actions": foreshadow_actions,
        "promise_actions": promise_actions,
        "reward_actions": list(
            snapshots.get("reward_ledger")
            or canon_patch.get("reward_actions")
            or []
        ),
        "mystery_actions": list(canon_patch.get("mystery_actions") or []),
        "theme_movements": list(canon_patch.get("theme_movements") or []),
        "antagonist_actions": list(canon_patch.get("antagonist_actions") or []),
        "arc_contributions": list(canon_patch.get("arc_contributions") or []),
        "narrative_debt_actions": narrative_debt,
        "reader_state_signals": list(canon_patch.get("reader_state_signals") or []),
        "cost_receipt_refs": list(cost_receipt_refs),
        "created_by_operation_id": created_by_operation_id,
    }


def reduce_story_state(
    *,
    previous: dict[str, Any] | None,
    chapter_outcome: dict[str, Any],
    chapter_outcome_asset_version_id: str,
) -> dict[str, Any]:
    """Apply one outcome without model calls or in-place mutation."""
    if not chapter_outcome_asset_version_id:
        raise ValueError("ChapterOutcome AssetVersion is required")
    state = deepcopy(previous or {})
    applied = list(state.get("applied_chapter_outcome_versions") or [])
    if chapter_outcome_asset_version_id in applied:
        return state
    for field in STATE_FIELDS:
        state[field] = deepcopy(state.get(field) or [])
    applications: list[dict[str, Any]] = []
    current_version = len(applied)
    for definition in STORY_STATE_REDUCERS:
        changes = deepcopy(chapter_outcome.get(definition.outcome_field) or [])
        previous_dimension = deepcopy(state[definition.output_state_type])
        transition_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                {
                    "reducer_key": definition.reducer_key,
                    "chapter_outcome_asset_version_id": (
                        chapter_outcome_asset_version_id
                    ),
                    "previous": previous_dimension,
                    "changes": changes,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        state[definition.output_state_type].extend(changes)
        applications.append(
            {
                "reducer_key": definition.reducer_key,
                "input_contract_version": definition.input_contract_version,
                "output_state_type": definition.output_state_type,
                "current_state_version": current_version,
                "chapter_outcome_id": chapter_outcome[
                    "chapter_outcome_id"
                ],
                "chapter_outcome_asset_version_id": (
                    chapter_outcome_asset_version_id
                ),
                "transition_hash": transition_hash,
                "idempotency_key": (
                    f"{chapter_outcome_asset_version_id}:"
                    f"{definition.reducer_key}"
                ),
                "validation_policy": definition.validation_policy,
                "dependencies": list(definition.dependencies),
            }
        )
    applied.append(chapter_outcome_asset_version_id)
    state.update(
        {
            "type": "StoryStateSnapshot",
            "contract_version": "story-state-snapshot-v1",
            "project_id": chapter_outcome["project_id"],
            "book_id": chapter_outcome["book_id"],
            "chapter": int(chapter_outcome["chapter_number"]),
            "chapter_number": int(chapter_outcome["chapter_number"]),
            "state_version": len(applied),
            "based_on_chapter_outcome": chapter_outcome_asset_version_id,
            "applied_chapter_outcome_versions": applied,
            "reducer_applications": applications,
        }
    )
    return state


__all__ = [
    "STATE_FIELDS",
    "STORY_STATE_REDUCERS",
    "StoryStateReducerDefinition",
    "build_chapter_outcome",
    "reduce_story_state",
]
