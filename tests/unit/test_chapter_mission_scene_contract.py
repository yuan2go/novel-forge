from copy import deepcopy

import pytest

from novel_forge.modules.chapter_authority.chapter_plan_views import normalize_authoritative_chapter_plan, build_draft_plan_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.chapter_contracts import compile_chapter_contracts


def _plan() -> dict:
    return {
        "chapter": 2, "project_id": "p", "title": "Choice", "premise": "A debt falls due",
        "chapter_objective": "Accept a cost", "chapter_hook": "An ally demands repayment",
        "narrative_architecture_version": "canonical-narrative-v1",
        "chapter_intent": "Trust changes through costly action",
        "required_state_transitions": [{"entity_key": "trust", "state_kind": "relationship_state", "from_state": "hostile", "to_state": "allied"}],
        "arc_schedule": [{"arc_plan_version_id": "arc:v1", "role": "PRIMARY"}],
        "reader_experience": {"exit_question": "What did the alliance cost?"},
        "expected_exit_state": {"trust": "allied"},
        "setups": [{"obligation_id": "debt", "action": "PLANT"}],
        "scene_plan": [{"scene_id": "s1", "state_transitions": ["trust"], "arc_progress": ["arc:v1"], "beats": [{"beat_id": "b1", "ordinal": 1, "function": "choice"}]}],
        "scene_sequence": [{"scene_id": "s1"}],
    }


def test_scene_cannot_descend_without_complete_mission_coverage() -> None:
    plan = _plan()
    for field in ("state_transitions", "arc_progress"):
        broken = deepcopy(plan)
        broken["scene_plan"][0][field] = []
        with pytest.raises(KernelError, match="SCENE_MISSION_COVERAGE_INVALID"):
            compile_chapter_contracts(broken, asset_version_id="plan:v1", content_hash="sha256:" + "a" * 64)
    broken = deepcopy(plan)
    broken["chapter_intent"] = ""
    with pytest.raises(KernelError, match="CHAPTER_MISSION_INCOMPLETE"):
        compile_chapter_contracts(broken, asset_version_id="plan:v1", content_hash="sha256:" + "a" * 64)


def test_mission_and_scene_share_immutable_source_and_separate_fingerprints() -> None:
    plan = _plan()
    mission, scenes = compile_chapter_contracts(plan, asset_version_id="plan:v1", content_hash="sha256:" + "a" * 64)
    original = mission.digest
    plan["chapter_intent"] = "A different future decision"
    assert mission.digest == original
    assert scenes.mission_digest == original
    replacement, replacement_scenes = compile_chapter_contracts(plan, asset_version_id="plan:v2", content_hash="sha256:" + "b" * 64)
    assert replacement.digest != original
    assert replacement_scenes.digest != scenes.digest
    assert scenes.to_dict()["source_asset_version_id"] == "plan:v1"


def test_normalization_and_provider_projection_preserve_planning_authority_binding() -> None:
    normalized, _ = normalize_authoritative_chapter_plan(
        project_id="p", expected_chapter=2, content=_plan(),
        asset_version_id="plan:v1", content_hash="sha256:" + "a" * 64,
    )
    boundaries = normalized["narrative_contracts"]
    assert boundaries["chapter_mission"]["owner"] == "hierarchical-planning"
    assert boundaries["accepted_fact_mutation"] is False
    assert build_draft_plan_view(normalized)["narrative_contracts"] == boundaries


def test_scene_coverage_rejects_ambiguous_entity_only_transition_references() -> None:
    plan = _plan()
    plan["required_state_transitions"].append({
        "entity_key": "trust", "state_kind": "character_state", "from_state": "fear", "to_state": "hope"
    })
    with pytest.raises(KernelError, match="SCENE_MISSION_TRANSITION_AMBIGUOUS"):
        compile_chapter_contracts(plan, asset_version_id="plan:v1", content_hash="sha256:" + "a" * 64)


def test_held_trajectory_does_not_force_unplanned_scene_progress() -> None:
    plan = _plan()
    plan["arc_schedule"].append({"arc_plan_version_id": "arc:held", "role": "HOLD"})
    mission, scenes = compile_chapter_contracts(plan, asset_version_id="plan:v1", content_hash="sha256:" + "a" * 64)
    assert scenes.mission_digest == mission.digest
    assert "arc:held" in mission.payload_json
    assert "arc:held" not in scenes.scenes_json
