from pathlib import Path

from novel_forge.modules.capability_packs.longform_profiles import (
    build_reader_outcome_pack_profile,
    build_story_planning_pack_profile,
)


ROOT = Path(__file__).resolve().parents[2]


def test_story_planning_profile_is_domain_owned_and_five_stage() -> None:
    profile = build_story_planning_pack_profile(
        ROOT,
        operation_definition_hash="sha256:" + "a" * 64,
    )

    assert profile.pack_id == "story_planning_pack"
    assert profile.workflow_ref == "story_planning_generators@1.0.0"
    assert profile.manifest["identity"]["domain"] == "story_planning"
    assert profile.manifest["prompt_binding"]["system_instruction_ref"] == (
        "prompt-system:story-planning-pack"
    )
    assert {node["node_id"] for node in profile.manifest["workflow_template"]["nodes"]} == {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
    assert {item["skill_ref"] for item in profile.manifest["skill_binding"]["skills"]} == {
        "long-outline"
    }
    assert {
        item["ref"]
        for item in profile.artifact_catalog["artifacts"]
        if item["kind"] == "SCHEMA"
    }.issuperset(
        {
            "schema:story-planning-pack-input:v1",
            "schema:story-planning-pack-output:v1",
        }
    )


def test_reader_outcome_profile_is_independent_shadow_domain_pack() -> None:
    profile = build_reader_outcome_pack_profile(
        ROOT,
        operation_definition_hash="sha256:" + "b" * 64,
    )

    assert profile.pack_id == "reader_outcome_pack"
    assert profile.workflow_ref == "book_followup_reader_outcome@1.0.0"
    assert profile.manifest["identity"]["domain"] == "book_followup"
    assert profile.manifest["prompt_binding"]["system_instruction_ref"] == (
        "prompt-system:reader-outcome-pack"
    )
    assert [
        item["node_id"] for item in profile.manifest["workflow_template"]["nodes"]
    ] == ["reader_outcome"]
    assert {item["skill_ref"] for item in profile.manifest["skill_binding"]["skills"]} == {
        "reader-feedback"
    }
    assert profile.manifest["workflow_template"]["nodes"][0]["commit_authority"] == (
        "BOOK_FOLLOWUP_AUTHORITY"
    )
    assert {
        item["ref"]
        for item in profile.artifact_catalog["artifacts"]
        if item["kind"] == "SCHEMA"
    }.issuperset(
        {
            "schema:reader-outcome-pack-input:v1",
            "schema:reader-outcome-pack-output:v1",
        }
    )
