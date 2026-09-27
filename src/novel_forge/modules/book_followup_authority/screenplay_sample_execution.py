from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .screenplay import SOURCE_TYPE, CANDIDATE_TYPE, REVIEW_TYPE
from .screenplay_sampling import (SCREENPLAY_SAMPLE_TYPE, SCREENPLAY_SAMPLE_VERSION,
    sample_definition_name, sample_workflow, validate_screenplay_sample_origin)


def upstream_projection(stage: str, content: Mapping[str, Any]) -> dict[str, Any]:
    if stage == "screenplay_review" and content["stage"] in {"screenplay_generate", "screenplay_revision"}:
        return {CANDIDATE_TYPE: deepcopy(content["sampled_output"])}
    if stage == "screenplay_revision" and content["stage"] == "screenplay_review":
        return {CANDIDATE_TYPE: deepcopy(content["input_candidate"]), REVIEW_TYPE: deepcopy(content["sampled_output"])}
    raise KernelError("SCREENPLAY_SAMPLE_STAGE_INVALID", "The upstream native sample cannot supply this stage")


def expand_sample_inputs(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in selected:
        if item.get("asset_type") == SCREENPLAY_SAMPLE_TYPE:
            if set(item["projection"]) - {CANDIDATE_TYPE, REVIEW_TYPE}:
                raise KernelError("SCREENPLAY_SAMPLE_CONTEXT_INVALID", "Only typed candidate and review projections may enter the Provider")
            output.extend({**item, "asset_type": kind, "projection": content} for kind, content in item["projection"].items())
        else:
            output.append(item)
    return output


def projected_sample_context(stage: str, frozen: Mapping[str, Any]) -> dict[str, Any]:
    selected = [{**frozen["source_binding"], "asset_type": SOURCE_TYPE, "projection": frozen["source"]}]
    if frozen["upstream"]:
        upstream = frozen["upstream"]
        selected.append({"asset_version_id": upstream["asset_version_id"], "content_hash": upstream["content_hash"],
            "asset_type": SCREENPLAY_SAMPLE_TYPE, "projection": upstream_projection(stage, upstream["content"])})
    return {"schema_version": "novelos." + stage + "_context_bundle.v1", "selected_inputs": selected}


def sample_input_permitted(binder: Any, document: Any, *, project_id: str, operation_id: str) -> bool:
    from novel_forge.modules.command_kernel.routing_bootstrap import load_bootstrap_authorization
    with AuthorityUnitOfWork(binder.database_url) as uow:
        snapshot = load_bootstrap_authorization(uow.cursor, project_id=project_id, operation_id=operation_id, check_expiry=False)
        uow.cursor.execute("SELECT definition_name,command_payload->'payload' FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project_id, operation_id])
        row = uow.cursor.fetchone()
        if not snapshot or not row or row[0] != sample_definition_name(binder.stage_name):
            return False
        frozen = validate_screenplay_sample_origin(uow.cursor, project_id=project_id, payload=row[1])
        upstream = frozen["upstream"]
        return bool(upstream and document.eligibility == "INELIGIBLE" and document.lifecycle == "ACTIVE"
            and (document.asset_version_id, document.content_hash) == (upstream["asset_version_id"], upstream["content_hash"]))


def resolve_sample_pack(binder: Any, arguments: dict[str, Any]):
    from novel_forge.modules.capability_pack_authority.runtime import CapabilityPackResolutionRequest
    if not binder.capability_pack_id:
        raise KernelError("SCREENPLAY_SAMPLE_PACK_REQUIRED", "Install the separately approved sample Pack")
    return binder.pack_resolver.freeze_attempt_snapshot(CapabilityPackResolutionRequest(
        project_id=arguments["project_id"], workspace_id=arguments["workspace_id"], book_id=arguments["book_id"],
        workflow_definition_ref=sample_workflow(binder.stage_name), workflow_node_id=binder.stage_name,
        environment=binder.pack_environment, runtime_profile=binder.pack_runtime_profile,
        release_channel=binder.pack_release_channel, release_sha=arguments["route"].release_sha,
        operation_definition_ref=sample_definition_name(binder.stage_name) + "@" + SCREENPLAY_SAMPLE_VERSION,
        pack_id=binder.capability_pack_id + ".samples"),
        operation_id=arguments["operation_id"], attempt_id=arguments["attempt_id"],
        execution_fencing_token=arguments["execution_fencing_token"], worker_id=arguments["worker_id"],
        snapshot_creation_fencing_token=arguments["snapshot_creation_fencing_token"],
        snapshot_creation_worker_id=arguments["snapshot_creation_worker_id"])
