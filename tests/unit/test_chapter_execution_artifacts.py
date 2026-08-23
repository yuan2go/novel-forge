from __future__ import annotations

from copy import deepcopy

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
        "chapter_intent": "Make trust costly enough to require a public choice.",
        "entry_state_ref": "story-state-v4",
        "required_state_delta": {"summary": "trust becomes conditional"},
        "required_state_transitions": [
            {
                "state_kind": "relationship_state",
                "entity_key": "witness-trust",
                "from_state": "silent",
                "to_state": "conditional trust",
            }
        ],
        "knowledge_boundaries": [
            {"layer": "READER_KNOWLEDGE", "fact_id": "cost", "status": "HINTED"}
        ],
        "disclosures": [{"fact_id": "cost", "audience": "READER", "mode": "HINT"}],
        "reader_experience": {
            "target_emotion": "dread",
            "reward_mode": "DISCOVERY",
            "exit_question": "Who will exploit the clue?",
        },
        "expected_exit_state": {"summary": "trust is conditional and exposed"},
        "ending_hook": "the clue identifies a hidden observer",
        "required_arc_contributions": [
            {"arc_plan_version_id": "arc-v2", "contribution_kind": "ESCALATE"}
        ],
        "scene_plan": [
            {
                "scene_id": "chapter-5:scene-1",
                "scene_version": 2,
                "goal": "obtain the witness testimony",
                "conflict": "testimony costs the witness their safety",
                "participants": ["protagonist", "witness"],
                "arc_progress": ["arc-v2"],
                "information_gain": ["cost"],
                "state_transitions": ["witness-trust"],
                "entry_state": "the witness is silent",
                "exit_state": "the witness gives one costly clue",
                "reader_effect": "dread converts into implicated curiosity",
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
    mission = intent["chapter_mission"]
    assert mission["why_this_chapter_exists"].startswith("Make trust costly")
    assert mission["narrative_composition"]["events"][0]["narrative_functions"] == [
        "CHARACTER",
        "MYSTERY_DISCLOSURE",
        "PLOT",
        "READER_EXPERIENCE",
        "RELATIONSHIP",
    ]
    assert mission["hook_intent"]["unresolved_exit_question"] == (
        "Who will exploit the clue?"
    )


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
            "scene_directives": [
                {"scene_id": "chapter-5:scene-1", "approach": "pressure"}
            ],
            "retrieval_queries": ["witness relationship history"],
            "obligation_actions": [{"obligation_id": "promise-1", "action": "DEVELOP"}],
            "arc_actions": [{"arc_plan_version_id": "arc-v2", "action": "ESCALATE"}],
        },
        execution_evidence={"domain_service": "chapter-memo-v1"},
    )

    assert memo["source_chapter_plan"] == intent["source_chapter_plan"]
    assert memo["qualification"] == "QUALIFIED"
    assert (
        memo["mission_fingerprint"] == intent["chapter_mission"]["mission_fingerprint"]
    )
    assert memo["event_directives"][0]["event_id"] == "chapter-5:scene-1"
    assert "chapter_plan_patch" not in memo
    assert memo["execution_evidence"]["domain_service"] == "chapter-memo-v1"


def test_multi_arc_mission_requires_one_shared_causal_event() -> None:
    plan = _plan()
    plan["required_arc_contributions"].append(
        {"arc_plan_version_id": "arc-v3", "contribution_kind": "TOUCH"}
    )
    second_scene = deepcopy(plan["scene_plan"][0])
    second_scene["scene_id"] = "chapter-5:scene-2"
    second_scene["arc_progress"] = ["arc-v3"]
    second_scene["beats"][0]["beat_id"] = "chapter-5:scene-2:beat-1"
    plan["scene_plan"].append(second_scene)
    with pytest.raises(KernelError, match="shared causal Scene event"):
        build_chapter_execution_intent(
            project_id="project-1",
            operation_id="operation-intent",
            chapter_plan_asset_version_id="chapter-plan-v5",
            chapter_plan_content_hash="sha256:" + "a" * 64,
            chapter_plan=plan,
            accepted_inputs=(
                _accepted("story_state_snapshot", "state-v4"),
                _accepted("canon_snapshot", "canon-v4"),
            ),
        )

    plan["scene_plan"][0]["arc_progress"] = ["arc-v2", "arc-v3"]
    intent = build_chapter_execution_intent(
        project_id="project-1",
        operation_id="operation-intent",
        chapter_plan_asset_version_id="chapter-plan-v5",
        chapter_plan_content_hash="sha256:" + "a" * 64,
        chapter_plan=plan,
        accepted_inputs=(
            _accepted("story_state_snapshot", "state-v4"),
            _accepted("canon_snapshot", "canon-v4"),
        ),
    )
    assert (
        intent["chapter_mission"]["narrative_composition"]["multi_arc_event_count"] == 1
    )
