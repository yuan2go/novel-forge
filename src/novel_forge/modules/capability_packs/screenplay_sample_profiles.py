from __future__ import annotations

from copy import deepcopy

from novel_forge.modules.book_followup_authority.screenplay import SOURCE_TYPE
from novel_forge.modules.book_followup_authority.screenplay_sampling import (
    SCREENPLAY_SAMPLE_TYPE, SCREENPLAY_SAMPLE_VERSION, sample_definition_name, sample_workflow,
)
from .longform_profiles import LongformCapabilityPackProfile, _require_hash
from .artifacts import artifact_content_hash


def build_screenplay_sampling_profile(source: LongformCapabilityPackProfile, *, stage: str,
                                      operation_definition_hash: str) -> LongformCapabilityPackProfile:
    _require_hash(operation_definition_hash)
    name = sample_definition_name(stage)
    manifest = deepcopy(source.manifest)
    nodes = manifest["workflow_template"]["nodes"]
    if len(nodes) != 1 or nodes[0]["operation_name"] != stage:
        raise ValueError("A sample Pack must retain its exact formal screenplay stage producer")
    node = nodes[0]
    node.update(operation_name=name, operation_definition_ref=name + "@" + SCREENPLAY_SAMPLE_VERSION,
        operation_definition_hash=operation_definition_hash, handler_key="novel_forge.book_followup_authority." + name,
        input_asset_types=[SOURCE_TYPE, *([SCREENPLAY_SAMPLE_TYPE] if stage != "screenplay_generate" else [])],
        output_asset_types=[SCREENPLAY_SAMPLE_TYPE])
    manifest["context_sources"]["allowed_asset_types"] = sorted(set(manifest["context_sources"]["allowed_asset_types"]) | {SCREENPLAY_SAMPLE_TYPE})
    pack_id = source.pack_id + ".samples"
    manifest["identity"].update(pack_id=pack_id, version=source.manifest["identity"]["version"],
        name="Independent Screenplay Sample " + stage, description="Exact source adaptation benchmark; samples cannot become accepted screenplay or novel facts.")
    manifest["workflow_template"].update(workflow_id=sample_workflow(stage).split("@")[0], workflow_version=SCREENPLAY_SAMPLE_VERSION)
    manifest["workflow_template"]["completion"]["required_output_asset_types"] = [SCREENPLAY_SAMPLE_TYPE]
    for gate in manifest["evaluation"]["required_gates"]:
        gate["required_evidence"] = [SCREENPLAY_SAMPLE_TYPE]
    artifacts = deepcopy(source.artifact_catalog)
    context_policy_id = manifest["context_sources"]["policy_id"]
    # WHY: Both paths consume ContextBundle; retain physical producer identity while permitting exact experimental upstream inputs.
    for artifact in artifacts["artifacts"]:
        if artifact["ref"] == context_policy_id:
            artifact["content"]["allowed_asset_types"] = manifest["context_sources"]["allowed_asset_types"]
            artifact["content_hash"] = artifact_content_hash(artifact["content"])
    return LongformCapabilityPackProfile(pack_id, sample_workflow(stage), manifest, artifacts, source.agent_skill_ref)

