from __future__ import annotations

import pytest

from novel_forge.modules.chapter_authority.execution_artifacts import (
    build_chapter_execution_intent,
    qualify_chapter_memo,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _plan() -> dict:
    return {
        "chapter": 5,
        "objective": "Force the protagonist to choose between trust and control.",
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc-v2", "contribution_kind": "ESCALATE"}
        ],
        "scene_plan": [
            {
                "scene_id": "chapter-5:scene-1",
                "scene_version": 2,
                "goal": "obtain the witness testimony",
                "entry_state": "the witness is silent",
                "exit_state": "the witness gives one costly clue",
                "beats": [
                    {
                        "beat_id": "chapter-5:scene-1:beat-1",
                        "function": "apply relationship pressure",
                        "expected_reader_effect": "dread",
                    }
                ],
            }
        ],
    }


def _accepted(asset_type: str, asset_id: str) -> dict:
    return {
        "asset_type": asset_type,
        "asset_version_id": asset_id,
        "accepted_through_chapter": 4,
        "current_state": {
            "narrative_obligation": [{"obligation_id": "promise-1", "status": "OPEN"}]
        },
    }


def test_intent_locks_plan_scene_children_and_immediate_accepted_boundary() -> None:
    intent = build_chapter_execution_intent(
        project_id="project-1",
        operation_id="operation-intent",
        chapter_plan_asset_version_id="chapter-plan-v5",
        chapter_plan_content_hash="sha256:" + "a" * 64,
        chapter_plan=_plan(),
        accepted_inputs=(
            _accepted("story_state_snapshot", "state-v4"),
            _accepted("canon_snapshot", "canon-v4"),
        ),
    )

    assert intent["source_chapter_plan"]["locked"] is True
    assert intent["accepted_boundary"] == {
        "accepted_through_chapter": 4,
        "story_state_asset_version_id": "state-v4",
        "canon_snapshot_asset_version_id": "canon-v4",
    }
    assert intent["scene_plans"][0]["scene_version"] == 2
    assert intent["scene_plans"][0]["beats"][0]["ordinal"] == 1
    assert intent["active_obligations"][0]["obligation_id"] == "promise-1"


def test_intent_rejects_latest_generated_state_beyond_accepted_boundary() -> None:
    state = _accepted("story_state_snapshot", "state-v5-unaccepted")
    canon = _accepted("canon_snapshot", "canon-v5-unaccepted")
    state["accepted_through_chapter"] = 5
    canon["accepted_through_chapter"] = 5
    with pytest.raises(KernelError, match="immediately preceding"):
        build_chapter_execution_intent(
            project_id="project-1",
            operation_id="operation-intent",
            chapter_plan_asset_version_id="chapter-plan-v5",
            chapter_plan_content_hash="sha256:" + "a" * 64,
            chapter_plan=_plan(),
            accepted_inputs=(state, canon),
        )


def test_memo_is_working_strategy_and_cannot_rewrite_locked_plan() -> None:
    intent = build_chapter_execution_intent(
        project_id="project-1",
        operation_id="operation-intent",
        chapter_plan_asset_version_id="chapter-plan-v5",
        chapter_plan_content_hash="sha256:" + "a" * 64,
        chapter_plan=_plan(),
        accepted_inputs=(
            _accepted("story_state_snapshot", "state-v4"),
            _accepted("canon_snapshot", "canon-v4"),
        ),
    )
    memo = qualify_chapter_memo(
        intent=intent,
        intent_asset_version_id="intent-v1",
        result={
            "execution_strategy": "make one clue cost the relationship",
            "tension_strategy": "delay the witness answer",
            "scene_directives": [{"scene_id": "chapter-5:scene-1", "approach": "pressure"}],
            "retrieval_queries": ["witness relationship history"],
            "obligation_actions": [{"obligation_id": "promise-1", "action": "DEVELOP"}],
            "arc_actions": [{"arc_plan_version_id": "arc-v2", "action": "ESCALATE"}],
        },
        execution_evidence={"domain_service": "chapter-memo-v1"},
    )

    assert memo["source_chapter_plan"] == intent["source_chapter_plan"]
    assert memo["qualification"] == "QUALIFIED"
    assert "chapter_plan_patch" not in memo
    assert memo["execution_evidence"]["domain_service"] == "chapter-memo-v1"
