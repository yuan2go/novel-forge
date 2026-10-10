from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from novel_forge.modules.book_followup_authority.contracts import BOOK_FOLLOWUP_DEFINITION_VERSION
from novel_forge.modules.book_followup_authority.screenplay import SCREENPLAY_STAGES, SOURCE_TYPE, CANDIDATE_TYPE, REVIEW_TYPE, screenplay_output_schema
from novel_forge.modules.chapter_authority.execution_gateway import chapter_stage_capability
from novel_forge.modules.production_execution import default_capability_registry

from .artifacts import ArtifactKind
from .longform_profiles import (LongformCapabilityPackProfile, _base, _require_hash, _bind_domain_artifacts,
    _update_policy_artifacts, _append_capability_schemas, _append_artifact, _catalog)


def build_screenplay_pack_profile(repository_root: str | Path, *, stage: str,
                                  operation_definition_hash: str, pack_id: str = "") -> LongformCapabilityPackProfile:
    if stage not in SCREENPLAY_STAGES:
        raise ValueError("A supported screenplay stage is required")
    pack_id = pack_id or stage + "_pack"
    root, manifest, artifacts = _base(repository_root, pack_id)
    _require_hash(operation_definition_hash)
    capability = default_capability_registry().resolve(chapter_stage_capability(stage))
    inputs = [SOURCE_TYPE] + ([CANDIDATE_TYPE] if stage != "screenplay_generate" else []) + ([REVIEW_TYPE] if stage == "screenplay_revision" else [])
    output = REVIEW_TYPE if stage == "screenplay_review" else CANDIDATE_TYPE
    node = deepcopy(next(item for item in manifest["workflow_template"]["nodes"] if item["node_id"] == "draft"))
    node.update(node_id=stage, stage=stage, operation_name=stage,
        operation_definition_ref=stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION,
        operation_definition_hash=operation_definition_hash, handler_key="novel_forge.book_followup_authority." + stage,
        capability_id=capability.capability_id.value, input_asset_types=inputs, output_asset_types=[output],
        depends_on=[], commit_authority="BOOK_FOLLOWUP_AUTHORITY", timeout_policy_ref=capability.timeout_policy_ref)
    manifest["identity"].update(version="1.2.0" if stage == "screenplay_review" else "1.1.0", name="Scene Screenplay " + stage, domain="book_followup",
        description="Exact-edition scene, action and dialogue adaptation with separate review and acceptance.")
    manifest["compatibility"]["required_capabilities"] = [capability.capability_id.value, "quality.originality.judge"]
    manifest["workflow_template"].update(workflow_id="book_followup_" + stage, workflow_version=BOOK_FOLLOWUP_DEFINITION_VERSION,
        nodes=[node], completion={"required_terminal_nodes": [stage], "required_evidence": ["trace", "audit"], "required_output_asset_types": [output]})
    manifest["context_sources"]["allowed_asset_types"] = inputs + ["context_bundle"]
    manifest["tool_permissions"]["tools"] = [{**manifest["tool_permissions"]["tools"][0], "allowed_operations": [stage]}]
    manifest["evaluation"]["required_gates"] = [{"gate_id": "screenplay_source_isolation", "judge_capability_id": "quality.originality.judge",
        "blocking": True, "threshold": 1, "required_evidence": [output]}]
    manifest["evaluation"]["metrics"] = []
    skill = "quality-review" if stage == "screenplay_review" else "prose-generation"
    artifacts = _bind_domain_artifacts(root, manifest, artifacts, skill_ref=skill, skill_version="quality-review-v5" if stage == "screenplay_review" else "prose-generation-v4",
        skill_path="skills/" + skill + ("/SKILL.md" if stage == "screenplay_review" else "/legacy-v4.md"), system_ref="prompt-system:scene-screenplay-pack",
        system_path="config/capability_packs/artifacts/scene_screenplay_system_instruction.md",
        template_ref="prompt-template:scene-screenplay-pack", template_path="config/capability_packs/artifacts/scene_screenplay_template.md",
        input_schema_ref="schema:" + stage + "-pack-input:v1", output_schema_ref="schema:" + stage + "-pack-output:v1", system_version="v2")
    _append_artifact(artifacts, ArtifactKind.SCHEMA, "schema:" + stage + "-pack-output:v1", "v1", screenplay_output_schema(stage), "generated:scene-screenplay-contract")
    _update_policy_artifacts(manifest, artifacts)
    _append_capability_schemas(artifacts, capability.capability_id.value)
    _append_artifact(artifacts, ArtifactKind.TIMEOUT_POLICY, capability.timeout_policy_ref, "v1",
        {"policy_id": capability.timeout_policy_ref, "operation_timeout_seconds": 300, "timeout_action": "FAIL_ATTEMPT",
         "authority_binding": stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION}, "generated:scene-screenplay-profile")
    return LongformCapabilityPackProfile(pack_id, "book_followup_" + stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION,
        manifest, _catalog(artifacts), skill)
