from copy import deepcopy

from novel_forge.modules.book_followup_authority.contracts import BOOK_FOLLOWUP_DEFINITION_VERSION
from novel_forge.modules.book_followup_authority.memory_execution import memory_output_schema
from novel_forge.modules.production_execution import default_capability_registry, CapabilityId
from .artifacts import ArtifactKind
from .longform_profiles import (LongformCapabilityPackProfile, _base, _require_hash, _bind_domain_artifacts,
    _update_policy_artifacts, _append_capability_schemas, _append_artifact, _catalog)


def build_working_memory_pack_profile(repository_root, *, operation_definition_hash, pack_id="working_memory_pack"):
    stage = "working_memory_extract"
    root, manifest, artifacts = _base(repository_root, pack_id, complete_request_capacity=True)
    _require_hash(operation_definition_hash)
    capability = default_capability_registry().resolve(CapabilityId.CANON_EXTRACT)
    node = deepcopy(next(item for item in manifest["workflow_template"]["nodes"] if item["node_id"] == "draft"))
    node.update(node_id=stage, stage=stage, operation_name=stage,
        operation_definition_ref=stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION,
        operation_definition_hash=operation_definition_hash, handler_key="novel_forge.book_followup_authority." + stage,
        capability_id=capability.capability_id.value, input_asset_types=["working_memory_task"], output_asset_types=["working_memory_result"],
        depends_on=[], commit_authority="BOOK_FOLLOWUP_AUTHORITY", timeout_policy_ref=capability.timeout_policy_ref)
    manifest["identity"].update(version="1.0.0", name="Working Memory Extraction", domain="book_followup",
        description="Located fallible working observations with native receipts; no Canon or prose mutation.")
    manifest["compatibility"]["required_capabilities"] = [capability.capability_id.value, "quality.originality.judge"]
    manifest["workflow_template"].update(workflow_id="book_followup_" + stage, workflow_version=BOOK_FOLLOWUP_DEFINITION_VERSION,
        nodes=[node], completion={"required_terminal_nodes": [stage], "required_evidence": ["trace", "audit"], "required_output_asset_types": ["working_memory_result"]})
    manifest["context_sources"]["allowed_asset_types"] = ["working_memory_task", "context_bundle"]
    manifest["tool_permissions"]["tools"] = [{**manifest["tool_permissions"]["tools"][0], "allowed_operations": [stage]}]
    manifest["evaluation"]["required_gates"] = [{"gate_id": "working_memory_source_isolation", "judge_capability_id": "quality.originality.judge",
        "blocking": True, "threshold": 1, "required_evidence": ["working_memory_result"]}]
    manifest["evaluation"]["metrics"] = []
    artifacts = _bind_domain_artifacts(root, manifest, artifacts,
        skill_ref="context-builder-source-isolation", skill_version="context-builder-source-isolation-memory-v1",
        skill_path="skills/context-builder-source-isolation/SKILL.md",
        system_ref="prompt-system:working-memory-pack", system_path="config/capability_packs/artifacts/working_memory_system_instruction_v1.md",
        template_ref="prompt-template:working-memory-pack", template_path="config/capability_packs/artifacts/working_memory_template_v1.md",
        input_schema_ref="schema:working-memory-pack-input:v1", output_schema_ref="schema:working-memory-pack-output:v1", system_version="v1", template_version="v1")
    _append_artifact(artifacts, ArtifactKind.SCHEMA, "schema:working-memory-pack-output:v1", "v1", memory_output_schema(), "generated:working-memory-contract")
    _update_policy_artifacts(manifest, artifacts)
    _append_capability_schemas(artifacts, capability.capability_id.value)
    _append_artifact(artifacts, ArtifactKind.TIMEOUT_POLICY, capability.timeout_policy_ref, "v1",
        {"policy_id": capability.timeout_policy_ref, "operation_timeout_seconds": 180, "timeout_action": "FAIL_ATTEMPT",
         "authority_binding": stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION}, "generated:working-memory-profile")
    return LongformCapabilityPackProfile(pack_id, "book_followup_" + stage + "@" + BOOK_FOLLOWUP_DEFINITION_VERSION,
        manifest, _catalog(artifacts), "context-builder-source-isolation")
