"""Typed execution-time artifacts between an authoritative ChapterPlan and Context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def _hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_chapter_execution_intent(
    *,
    project_id: str,
    operation_id: str,
    chapter_plan_asset_version_id: str,
    chapter_plan_content_hash: str,
    chapter_plan: Mapping[str, Any],
    accepted_inputs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compile a locked execution intent from Plan plus accepted state only."""

    chapter = int(chapter_plan.get("chapter") or chapter_plan.get("chapter_number") or 0)
    if chapter <= 0 or not chapter_plan_asset_version_id or not chapter_plan_content_hash:
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_PLAN_INVALID",
            "ExecutionIntent requires an exact authoritative ChapterPlan version",
        )
    accepted_by_type = {
        str(item.get("asset_type") or ""): dict(item) for item in accepted_inputs
    }
    story = accepted_by_type.get("story_state_snapshot")
    canon = accepted_by_type.get("canon_snapshot")
    expected_boundary = chapter - 1
    if bool(story) != bool(canon):
        raise KernelError(
            "CHAPTER_EXECUTION_INTENT_BOUNDARY_INCOMPLETE",
            "accepted Story State and Canon inputs must be present together",
        )
    if story and canon:
        story_boundary = int(story.get("accepted_through_chapter") or 0)
        canon_boundary = int(canon.get("accepted_through_chapter") or 0)
        if story_boundary != expected_boundary or canon_boundary != expected_boundary:
            raise KernelError(
                "CHAPTER_EXECUTION_INTENT_BOUNDARY_MISMATCH",
                "ExecutionIntent can only use the immediately preceding Accepted Chapter",
            )
    scenes = []
    for ordinal, raw in enumerate(chapter_plan.get("scene_plan") or (), start=1):
        if not isinstance(raw, Mapping) or not str(raw.get("scene_id") or ""):
            raise KernelError(
                "CHAPTER_EXECUTION_INTENT_SCENE_INVALID",
                "ExecutionIntent requires addressable ScenePlan children",
            )
        beats = []
        for beat_ordinal, raw_beat in enumerate(raw.get("beats") or (), start=1):
            beat = (
                dict(raw_beat)
                if isinstance(raw_beat, Mapping)
                else {
                    "beat_id": f"{raw['scene_id']}:beat:{beat_ordinal}",
                    "function": str(raw_beat),
                    "expected_reader_effect": "",
                }
            )
            beats.append(
                {
                    "beat_id": str(
                        beat.get("beat_id")
                        or f"{raw['scene_id']}:beat:{beat_ordinal}"
                    ),
                    "ordinal": beat_ordinal,
                    "function": str(beat.get("function") or ""),
                    "expected_reader_effect": str(
                        beat.get("expected_reader_effect") or ""
                    ),
                }
            )
        scenes.append(
            {
                "scene_id": str(raw["scene_id"]),
                "scene_version": int(raw.get("scene_version") or 1),
                "ordinal": ordinal,
                "goal": str(raw.get("goal") or ""),
                "entry_state": str(raw.get("entry_state") or ""),
                "exit_state": str(raw.get("exit_state") or ""),
                "beats": beats,
            }
        )
    intent = {
        "type": "ChapterExecutionIntent",
        "contract_version": "chapter-execution-intent-v1",
        "project_id": project_id,
        "chapter": chapter,
        "source_chapter_plan": {
            "asset_version_id": chapter_plan_asset_version_id,
            "content_hash": chapter_plan_content_hash,
            "locked": True,
        },
        "accepted_boundary": {
            "accepted_through_chapter": expected_boundary,
            "story_state_asset_version_id": str(
                (story or {}).get("asset_version_id") or ""
            ),
            "canon_snapshot_asset_version_id": str(
                (canon or {}).get("asset_version_id") or ""
            ),
        },
        "chapter_objective": str(
            chapter_plan.get("objective")
            or chapter_plan.get("primary_function")
            or ""
        ),
        "required_arc_contributions": list(
            chapter_plan.get("required_arc_contributions") or ()
        ),
        "active_obligations": list(
            ((story or {}).get("current_state") or {}).get(
                "narrative_obligation", ()
            )
        ),
        "previous_ending": str((story or {}).get("previous_ending") or ""),
        "reader_tension": dict((story or {}).get("reader_tension") or {}),
        "scene_plans": scenes,
        "created_by_operation_id": operation_id,
    }
    intent["intent_fingerprint"] = _hash(intent)
    return intent


def qualify_chapter_memo(
    *,
    intent: Mapping[str, Any],
    intent_asset_version_id: str,
    result: Mapping[str, Any],
    execution_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a qualified working memo to Intent without changing its Plan."""

    required = (
        "execution_strategy",
        "tension_strategy",
        "scene_directives",
        "retrieval_queries",
        "obligation_actions",
        "arc_actions",
    )
    if any(key not in result for key in required):
        raise KernelError(
            "CHAPTER_MEMO_UNQUALIFIED",
            "ChapterMemo provider output is incomplete",
        )
    source_plan = dict(intent.get("source_chapter_plan") or {})
    if not source_plan.get("locked") or not intent_asset_version_id:
        raise KernelError(
            "CHAPTER_MEMO_INTENT_INVALID",
            "ChapterMemo requires a locked, materialized ExecutionIntent",
        )
    memo = {
        "type": "ChapterMemo",
        "contract_version": "chapter-memo-v1",
        "chapter": int(intent.get("chapter") or 0),
        "source_chapter_execution_intent_asset_version_id": intent_asset_version_id,
        "source_chapter_plan": source_plan,
        "accepted_boundary": dict(intent.get("accepted_boundary") or {}),
        "execution_strategy": str(result.get("execution_strategy") or ""),
        "tension_strategy": str(result.get("tension_strategy") or ""),
        "scene_directives": [dict(item) for item in result["scene_directives"]],
        "retrieval_queries": [str(item) for item in result["retrieval_queries"]],
        "obligation_actions": [dict(item) for item in result["obligation_actions"]],
        "arc_actions": [dict(item) for item in result["arc_actions"]],
        "stop_conditions": [str(item) for item in result.get("stop_conditions") or ()],
        "execution_evidence": dict(execution_evidence),
        "qualification": "QUALIFIED",
    }
    memo["memo_fingerprint"] = _hash(memo)
    return memo


__all__ = ["build_chapter_execution_intent", "qualify_chapter_memo"]
