from pathlib import Path

from novel_forge.modules.capability_packs.longform_profiles import (
    NARRATIVE_EVALUATION_PROMPT_VERSION,
    STORY_PLANNING_PROMPT_VERSION,
    build_narrative_evaluation_pack_profile,
    build_reader_outcome_pack_profile,
    build_story_planning_pack_profile,
)
from novel_forge.modules.capability_packs.operation_catalog import (
    narrative_evaluation_workflow_binding_catalog,
)
from novel_forge.modules.capability_packs.operation_catalog import (
    story_planning_workflow_binding_catalog,
)
from novel_forge.modules.production_execution.capability_registry import (
    PLANNING_TIMEOUT_POLICY_VERSION,
)
from novel_forge.modules.story_planning_runtime import (
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    STORY_PLANNING_WORKFLOW_DEFINITION_REF,
)


ROOT = Path(__file__).resolve().parents[2]


def test_narrative_evaluation_profile_is_independent_provider_pack() -> None:
    profile = build_narrative_evaluation_pack_profile(
        ROOT,
        operation_definition_hash="sha256:" + "c" * 64,
    )

    assert profile.pack_id == "narrative_semantic_evaluation_pack"
    assert profile.workflow_ref == "story_design_semantic_evaluation@1.0.0"
    assert profile.manifest["identity"]["domain"] == "story_design"
    assert profile.agent_skill_ref == "quality-review"
    assert [
        item["node_id"] for item in profile.manifest["workflow_template"]["nodes"]
    ] == ["narrative_semantic_evaluation"]
    assert profile.manifest["tool_permissions"]["tools"][0]["allowed_operations"] == [
        "narrative_semantic_evaluation"
    ]
    binding = narrative_evaluation_workflow_binding_catalog().resolve(
        "narrative_semantic_evaluation"
    )
    assert binding.operation_name == "story_design.semantic_evaluate"
    assert binding.primary_output_asset_type == "narrative_design_evaluation"
    assert profile.manifest["prompt_binding"]["system_instruction_version"] == (
        NARRATIVE_EVALUATION_PROMPT_VERSION
    )
    instruction = next(
        item
        for item in profile.artifact_catalog["artifacts"]
        if item["kind"] == "PROMPT_SYSTEM_INSTRUCTION"
        and item["ref"] == "prompt-system:narrative-semantic-evaluation-pack"
    )
    assert instruction["version"] == NARRATIVE_EVALUATION_PROMPT_VERSION
    assert "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES" in instruction["content"][
        "text"
    ]
    assert "do not mistake a reference-only BookDesign field" in instruction[
        "content"
    ]["text"]
    assert "`semantic_payload`" in instruction["content"]["text"]


def test_story_planning_profile_owns_typed_plans_and_foundation_generators() -> None:
    profile = build_story_planning_pack_profile(
        ROOT,
        operation_definition_hash="sha256:" + "a" * 64,
    )

    assert profile.pack_id == "story_planning_pack"
    assert profile.workflow_ref == STORY_PLANNING_WORKFLOW_DEFINITION_REF
    assert (
        story_planning_workflow_binding_catalog().workflow_version
        == profile.workflow_ref.rpartition("@")[2]
    )
    assert profile.manifest["identity"]["domain"] == "story_planning"
    assert profile.manifest["prompt_binding"]["system_instruction_ref"] == (
        "prompt-system:story-planning-pack"
    )
    assert profile.manifest["prompt_binding"]["system_instruction_version"] == (
        STORY_PLANNING_PROMPT_VERSION
    )
    planning_instruction = next(
        item
        for item in profile.artifact_catalog["artifacts"]
        if item["kind"] == "PROMPT_SYSTEM_INSTRUCTION"
        and item["ref"] == "prompt-system:story-planning-pack"
    )
    assert planning_instruction["version"] == STORY_PLANNING_PROMPT_VERSION
    assert "publish-metadata inputs" in planning_instruction["content"]["text"]
    assert "ANCHOR < DEFINED < DETAILED < ACTIVE" in planning_instruction[
        "content"
    ]["text"]
    assert "obligation_windows[].obligation_id" in planning_instruction["content"][
        "text"
    ]
    assert {
        node["node_id"] for node in profile.manifest["workflow_template"]["nodes"]
    } == {
        "creative.candidates.generate",
        "world.design.generate",
        "character.cast.generate",
        "theme.candidates.generate",
        "reader.promise.generate",
        "ending.intent.generate",
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
    assert {
        node["operation_definition_ref"]
        for node in profile.manifest["workflow_template"]["nodes"]
    } == {STORY_PLANNING_OPERATION_DEFINITION_REF}
    assert {
        node["timeout_policy_ref"].rpartition(":")[2]
        for node in profile.manifest["workflow_template"]["nodes"]
    } == {PLANNING_TIMEOUT_POLICY_VERSION}
    timeout_policies = [
        item
        for item in profile.artifact_catalog["artifacts"]
        if item["kind"] == "TIMEOUT_POLICY"
        and item["content"].get("authority_binding")
        == STORY_PLANNING_OPERATION_DEFINITION_REF
    ]
    assert len(timeout_policies) == 11
    assert {
        item["content"]["operation_timeout_seconds"] for item in timeout_policies
    } == {STORY_PLANNING_OPERATION_TIMEOUT_SECONDS}
    assert {item["content"]["authority_binding"] for item in timeout_policies} == {
        STORY_PLANNING_OPERATION_DEFINITION_REF
    }
    assert {
        item["skill_ref"] for item in profile.manifest["skill_binding"]["skills"]
    } == {
        "worldbuilding",
        "topic-development",
        "hot-novel-business-deconstruction",
        "canon-continuity-graph",
        "chapter-outline",
        "character-design",
        "long-outline",
        "narrative-beat-design",
    }
    assert all(
        "narrative_qualification_profiles" not in node
        for node in profile.manifest["workflow_template"]["nodes"]
    )
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
    assert profile.workflow_ref == "book_followup_reader_outcome@1.1.0"
    assert profile.manifest["identity"]["version"] == "1.1.0"
    assert profile.manifest["prompt_binding"]["template_version"] == "v2"
    assert profile.manifest["identity"]["domain"] == "book_followup"
    assert profile.manifest["prompt_binding"]["system_instruction_ref"] == (
        "prompt-system:reader-outcome-pack"
    )
    assert [
        item["node_id"] for item in profile.manifest["workflow_template"]["nodes"]
    ] == ["reader_outcome"]
    assert {
        item["skill_ref"] for item in profile.manifest["skill_binding"]["skills"]
    } == {"reader-feedback"}
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
