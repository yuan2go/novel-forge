from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.execution_artifacts import (
    build_chapter_execution_intent,
    validate_chapter_execution_intent,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.chapter_contracts import (
    CHAPTER_CONTRACT_SCHEMA_VERSION,
    require_chapter_contracts,
)
from novel_forge.modules.plan_change_authority.domain import (
    PlanChangeRisk,
    classify_plan_change_risk,
    semantic_plan_diff,
)


def chapter_contract() -> dict:
    return {
        "chapter": 2,
        "chapter_number": 2,
        "chapter_contract_schema_version": CHAPTER_CONTRACT_SCHEMA_VERSION,
        "chapter_intent": "A public choice makes the ally's trust conditional",
        "primary_function": "REVERSAL",
        "arc_schedule": [{"arc_plan_version_id": "arc:v1", "role": "PRIMARY"}],
        "required_arc_contributions": [{"arc_plan_version_id": "arc:v1"}],
        "character_participation": [{"trajectory_refs": ["character:trust"]}],
        "obligation_actions": [{"obligation_id": "promise:trust", "action": "ADVANCE"}],
        "required_state_transitions": [
            {
                "state_kind": "relationship_state",
                "entity_key": "ally:protagonist",
                "from_state": "PRIVATE",
                "to_state": "CONDITIONAL",
            }
        ],
        "narrative_realization_slice": {
            "chapter_number": 2,
            "accepted_through_chapter": 1,
            "contract_digest": "sha256:" + "a" * 64,
            "events": [{"event_id": "event:choice"}],
        },
        "scene_plan": [
            {
                "scene_id": "scene:choice",
                "arc_progress": ["arc:v1"],
                "trajectory_refs": ["character:trust"],
                "obligation_refs": ["promise:trust"],
                "state_transitions": ["ally:protagonist"],
                "realization_event_ids": ["event:choice"],
                "beats": [
                    {
                        "beat_id": "beat:choice",
                        "ordinal": 1,
                        "function": "public choice",
                    }
                ],
            }
        ],
    }


def test_mission_scene_and_realization_contract_compiles_without_new_authority() -> (
    None
):
    content = chapter_contract()
    before = deepcopy(content)
    architecture = require_chapter_contracts(content)
    assert architecture.mission.obligation_refs == {"promise:trust"}
    assert architecture.mission.realization_event_ids == {"event:choice"}
    intent = build_chapter_execution_intent(
        project_id="project:one",
        operation_id="operation:plan",
        chapter_plan_asset_version_id="plan:v2",
        chapter_plan_content_hash="sha256:" + "b" * 64,
        chapter_plan=content,
        accepted_inputs=(),
    )
    assert validate_chapter_execution_intent(intent) == intent
    assert intent["contract_version"] == "chapter-execution-intent-v3"
    assert "required_beats" not in intent["chapter_mission"]
    assert intent["required_beats"][0]["scene_id"] == "scene:choice"
    assert intent["scene_plans"][0]["obligation_refs"] == ["promise:trust"]
    assert content == before


@pytest.mark.parametrize(
    "field",
    [
        "trajectory_refs",
        "obligation_refs",
        "arc_progress",
        "state_transitions",
        "realization_event_ids",
    ],
)
def test_scene_cannot_omit_any_mission_commitment(field: str) -> None:
    content = chapter_contract()
    content["scene_plan"][0][field] = []
    with pytest.raises(KernelError, match="SCENE_MISSION_COVERAGE_INCOMPLETE"):
        require_chapter_contracts(content)


@pytest.mark.parametrize(
    "field", ["trajectory_refs", "obligation_refs", "realization_event_ids"]
)
def test_scene_cannot_invent_commitment_identity(field: str) -> None:
    content = chapter_contract()
    content["scene_plan"][0][field] = ["invented:reference"]
    with pytest.raises(KernelError, match="SCENE_MISSION_REFERENCE_INVALID"):
        require_chapter_contracts(content)


def test_new_contract_cannot_target_accepted_history_or_downgrade_version() -> None:
    content = chapter_contract()
    content["narrative_realization_slice"]["accepted_through_chapter"] = 2
    with pytest.raises(KernelError, match="CHAPTER_MISSION_INCOMPLETE"):
        require_chapter_contracts(content)
    content.pop("chapter_contract_schema_version")
    with pytest.raises(KernelError, match="CHAPTER_CONTRACT_VERSION_REQUIRED"):
        require_chapter_contracts(content)


@pytest.mark.parametrize(
    "field",
    [
        "chapter_intent",
        "arc_schedule",
        "character_participation",
        "obligation_actions",
        "required_state_transitions",
        "narrative_realization_slice",
        "scene_plan",
    ],
)
def test_mission_and_scene_replan_changes_require_recorded_impact(field: str) -> None:
    before = chapter_contract()
    after = deepcopy(before)
    after[field] = "replacement"
    changes = semantic_plan_diff(before, after)
    assert [change.field for change in changes] == [field]
    assert (
        classify_plan_change_risk(changes, target_execution_scope="PLANNED")
        is PlanChangeRisk.MEDIUM
    )
    assert (
        classify_plan_change_risk(changes, target_execution_scope="EXECUTED")
        is PlanChangeRisk.HIGH
    )
