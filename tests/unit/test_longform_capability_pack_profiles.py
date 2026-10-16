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


def test_event_first_pack_is_explicit_and_freezes_only_the_planning_method():
    from novel_forge.modules.chapter_authority.prompt_methods import project_skill_method
    from novel_forge.modules.capability_packs.artifacts import artifact_content_hash

    legacy = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64)
    current = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64,
                                              event_first_planning=True)
    assert legacy.manifest["identity"]["version"] == "2.18.0"
    assert current.manifest["identity"]["version"] == "2.19.0"
    old = next(row for row in legacy.artifact_catalog["artifacts"] if row["kind"] == "SKILL" and row["ref"] == "long-outline")
    new = next(row for row in current.artifact_catalog["artifacts"] if row["kind"] == "SKILL" and row["ref"] == "long-outline")
    assert old["version"] == "long-outline-v4"
    assert new["version"] == "long-outline-v5"
    assert old["content_hash"] == artifact_content_hash({"text": (ROOT / "skills/long-outline/legacy-event-planning-20261011.md").read_text()})
    assert new["content_hash"] != old["content_hash"]
    assert current.manifest["workflow_template"] == legacy.manifest["workflow_template"]
    assert current.manifest["evaluation"] == legacy.manifest["evaluation"]
    assert current.manifest["context_sources"] == legacy.manifest["context_sources"]
    rendered = project_skill_method(new["content"]["text"], ref="long-outline", version=new["version"],
                                    stage="chapter_group_plan.generate", targeted=False)
    assert "## Chapter-group planning" in rendered
    assert "## Volume planning" not in rendered
    assert "## Ending intent" not in rendered
    assert "existing Plan Change" in rendered


def test_event_first_pack_rejects_incompatible_historical_input_contract():
    import pytest

    with pytest.raises(ValueError, match="current narrative intent contract"):
        build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64,
                                         event_first_planning=True, narrative_intent_boundary=False)


def test_world_sampling_pack_preserves_native_producer_artifacts():
    from novel_forge.modules.capability_packs.longform_profiles import build_world_sampling_pack_profile
    from novel_forge.modules.capability_packs.operation_catalog import governed_workflow_binding_catalog

    source = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64)
    sampled = build_world_sampling_pack_profile(source, application_build_id="test", commit_sha="a" * 40)
    assert sampled.artifact_catalog == source.artifact_catalog
    for key in ("prompt_binding", "context_sources", "output_contract"):
        if key in source.manifest:
            assert sampled.manifest[key] == source.manifest[key]
    source_tool = source.manifest["tool_permissions"]["tools"][0]
    sample_tool = sampled.manifest["tool_permissions"]["tools"][0]
    assert {key: value for key, value in source_tool.items() if key != "allowed_operations"} == {
        key: value for key, value in sample_tool.items() if key != "allowed_operations"}
    assert source.workflow_ref != sampled.workflow_ref
    assert {item["output_asset_types"][0] for item in sampled.manifest["workflow_template"]["nodes"]} == {"world_provider_sample"}
    catalog = governed_workflow_binding_catalog("world_provider_sampling", "1.0.0")
    assert catalog.resolve("world_candidates.generate").capability_id == "planning.story_chapter.generate"
    reference = build_world_sampling_pack_profile(source, application_build_id="test", commit_sha="a" * 40, reference_samples=True)
    assert reference.artifact_catalog == source.artifact_catalog
    assert reference.workflow_ref == "world_provider_sampling@1.1.0"
    assert [node["operation_definition_ref"] for node in reference.manifest["workflow_template"]["nodes"]] == ["world.provider.sample.evaluate@1.1.0"]
    assert governed_workflow_binding_catalog("world_provider_sampling", "1.1.0").resolve("world_candidates.evaluate").capability_id == "planning.story_chapter.generate"


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
            "schema:story-planning-pack-input:v2",
            "schema:story-planning-pack-output:v2",
        }
    )


def test_reader_outcome_profile_is_independent_shadow_domain_pack() -> None:
    profile = build_reader_outcome_pack_profile(
        ROOT,
        operation_definition_hash="sha256:" + "b" * 64,
    )

    assert profile.pack_id == "reader_outcome_pack"
    assert profile.workflow_ref == "book_followup_reader_outcome@1.1.0"
    assert profile.manifest["identity"]["version"] == "1.2.0"
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


def test_creative_json_format_example_matches_native_schema_without_replacing_default():
    import json
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    from novel_forge.modules.story_planning_runtime.foundation_generation import foundation_output_schema

    template = (ROOT / "config/capability_packs/artifacts/story_planning_creative_json_template.md").read_text()
    example = json.loads(template.split("<creative_json_output_example>\n", 1)[1].split("\n</creative_json_output_example>", 1)[0])
    assert validate_chapter_provider_output_against_schema(
        "creative.candidates.generate", foundation_output_schema("creative.candidates.generate"), example
    ) == example
    profile = build_story_planning_pack_profile(ROOT, operation_definition_hash="sha256:" + "a" * 64)
    assert profile.manifest["prompt_binding"]["template_ref"] == "prompt-template:story-planning-pack"
    assert profile.manifest["prompt_binding"]["template_version"] == "v3"
    bound = next(item for item in profile.artifact_catalog["artifacts"] if item["ref"] == "prompt-template:story-planning-pack" and item["version"] == "v3")
    assert bound["content"]["text"] == (ROOT / "config/capability_packs/artifacts/story_planning_template_v3.md").read_text()


def test_planning_context_target_is_frozen_in_manifest_and_resolved_policy():
    import pytest
    from novel_forge.modules.story_planning_runtime.preflight_continuation import require_capacity_target
    import json
    profile=build_story_planning_pack_profile(ROOT,operation_definition_hash="sha256:"+"a"*64,planning_task_token_budget=239232)
    context=profile.manifest["context_sources"]
    assert context["planning_task_token_budget"]==239232
    artifact=next(a for a in profile.artifact_catalog["artifacts"] if a["ref"]==context["policy_id"])
    assert artifact["content"]["planning_task_token_budget"]==239232
    old=build_story_planning_pack_profile(ROOT,operation_definition_hash="sha256:"+"a"*64,execution_contract_version="1.19.0").manifest["context_sources"]
    assert "planning_task_token_budget" not in old
    source={"snapshot":{"context_policy_payload_json":json.dumps(old)},"original_context_target":64000}
    target={"pack_snapshot":{"context_policy_payload_json":json.dumps(context)}}
    assert require_capacity_target(source,target)["successor_target"]==239232
    changed={**context,"source_isolation":"UNRESTRICTED"}
    with pytest.raises(Exception,match="PLANNING_RUNTIME_CONTINUATION_CAPACITY_DRIFT"):
        require_capacity_target(source,{"pack_snapshot":{"context_policy_payload_json":json.dumps(changed)}})
    for invalid in (0,True,512001):
        with pytest.raises(ValueError,match="ceiling"):
            build_story_planning_pack_profile(ROOT,operation_definition_hash="sha256:"+"a"*64,planning_task_token_budget=invalid)


def test_capacity_continuation_cannot_change_authentication_billing_or_reasoning():
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.story_planning_runtime.runtime_continuation import require_route_evidence
    source={"preflight_failure":{"effect_count":0},"source_auth_profile_ref":"auth:frozen",
        "source_backend_id":"codex-cli","source_reasoning_effort":"medium","route_evidence_operation_id":"original:op"}
    target={"auth_profile_ref":"auth:frozen","model_backend_id":"codex-cli","reasoning_effort":"medium",
        "cost_accounting_basis":"ACCOUNT_ENTITLEMENT","account":{"observed_account":"native"}}
    assert require_route_evidence(None,source=source,target=target,authorized_reasoning_effort="medium")["account_evidence_source"]=="ORIGINAL_SETTLED_NATIVE_RESULT_ROUTE"
    for change in ({"auth_profile_ref":"auth:another"},{"model_backend_id":"api"},{"cost_accounting_basis":"PRICED"},{"account":{}}):
        with pytest.raises(KernelError,match="ACCOUNT_DRIFT"):
            require_route_evidence(None,source=source,target={**target,**change},authorized_reasoning_effort="medium")
    with pytest.raises(KernelError,match="ACCOUNT_DRIFT"):
        require_route_evidence(None,source=source,target={**target,"reasoning_effort":"high"},authorized_reasoning_effort="high")
