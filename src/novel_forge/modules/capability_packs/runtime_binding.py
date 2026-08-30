"""INVARIANT: Authority admission binding for a compiled Capability Pack.

Capability Packs freeze configuration only.  The returned contract references
the existing OperationDefinition and Chapter Agent Binding; it owns no run,
attempt, lease, fence, retry, timeout, approval, or completion state.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from novel_forge.modules.agent_runtime.contracts import (
    ChapterNodeExecutionBinding,
)
from novel_forge.modules.command_kernel.errors import KernelError

from .compiler import CompiledCapabilityPack, CompiledWorkflowNode


@dataclass(frozen=True, slots=True)
class CapabilityPackAuthorityBinding:
    capability_pack_ref: str
    capability_pack_compilation_hash: str
    workflow_node_id: str
    operation_definition_ref: str
    operation_definition_hash: str
    agent_definition_ref: str
    agent_definition_hash: str
    capability_id: str
    capability_hash: str
    chapter_node_binding_ref: str
    release_sha: str


def compiled_capability_pack_from_payload(
    payload: Mapping[str, Any],
) -> CompiledCapabilityPack:

    try:
        nodes = tuple(
            CompiledWorkflowNode(
                ordinal=int(node["ordinal"]),
                node_id=str(node["node_id"]),
                definition_name=str(node["definition_name"]),
                definition_version=str(node["definition_version"]),
                definition_hash=str(node["definition_hash"]),
                handler_key=str(node["handler_key"]),
                handler_contract_version=str(node["handler_contract_version"]),
                capability_id=str(node["capability_id"]),
                capability_contract_hash=str(node["capability_contract_hash"]),
                agent_definition_ref=str(node.get("agent_definition_ref") or ""),
                depends_on=tuple(str(item) for item in node["depends_on"]),
                authoritative_retry_policy_json=_json(
                    node["authoritative_retry_policy"]
                ),
                authoritative_timeout_policy_json=_json(
                    node["authoritative_timeout_policy"]
                ),
                authoritative_approval_policy_json=_json(
                    node["authoritative_approval_policy"]
                ),
                authoritative_compensation_policy_json=_json(
                    node["authoritative_compensation_policy"]
                ),
                authoritative_completion_contract_json=_json(
                    node["authoritative_completion_contract"]
                ),
                commit_authority=str(
                    node.get("commit_authority") or "CHAPTER_AUTHORITY"
                ),
            )
            for node in payload["workflow_nodes"]
        )
        compiled = CompiledCapabilityPack(
            schema_version=str(payload["schema_version"]),
            pack_id=str(payload["pack_id"]),
            pack_version=str(payload["pack_version"]),
            manifest_hash=str(payload["manifest_hash"]),
            protocol_version=str(payload["protocol_version"]),
            target_runtime_profile=str(payload["target_runtime_profile"]),
            novel_forge_version=str(payload["novel_forge_version"]),
            release_channel=str(payload["release_channel"]),
            release_sha=str(payload["release_sha"]),
            catalog_snapshot_hash=str(payload["catalog_snapshot_hash"]),
            compilation_hash=str(payload["compilation_hash"]),
            capability_type_policy_json=_json(payload["capability_type_policy"]),
            resolved_capabilities_json=_json(payload["resolved_capabilities"]),
            resolved_operations_json=_json(payload["resolved_operations"]),
            resolved_artifacts_json=_json(payload["resolved_artifacts"]),
            workflow_nodes=nodes,
            external_input_asset_contract=tuple(
                str(item) for item in payload["external_input_asset_contract"]
            ),
            completion_contract_json=_json(payload["completion_contract"]),
            tool_permission_snapshot_json=_json(payload["tool_permission_snapshot"]),
            context_source_snapshot_json=_json(payload["context_source_snapshot"]),
            evaluation_gate_snapshot_json=_json(payload["evaluation_gate_snapshot"]),
            audit_requirement_snapshot_json=_json(
                payload["audit_requirement_snapshot"]
            ),
            version_resolution_snapshot_json=_json(
                payload["version_resolution_snapshot"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise KernelError(
            "CAPABILITY_PACK_COMPILED_PAYLOAD_INVALID",
            f"compiled Capability Pack payload is invalid: {exc}",
        ) from exc
    canonical = compiled.to_dict()
    claimed_hash = str(canonical.pop("compilation_hash"))
    actual_hash = (
        "sha256:" + hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()
    )
    if claimed_hash != actual_hash:
        raise KernelError(
            "CAPABILITY_PACK_COMPILATION_HASH_DRIFT",
            "compiled Capability Pack content differs from its compilation hash",
        )
    return compiled


def bind_compiled_pack_for_admission(
    *,
    compiled: CompiledCapabilityPack,
    workflow_node_id: str,
    chapter_binding: ChapterNodeExecutionBinding,
    authority_operation_definition: Mapping[str, Any],
) -> CapabilityPackAuthorityBinding:

    node = next(
        (item for item in compiled.workflow_nodes if item.node_id == workflow_node_id),
        None,
    )
    if node is None:
        raise KernelError(
            "CAPABILITY_PACK_NODE_NOT_FOUND",
            f"compiled Pack has no node: {workflow_node_id}",
        )
    expected_pack_ref = f"{compiled.pack_id}@{compiled.pack_version}"
    expected_operation_ref = f"{node.definition_name}@{node.definition_version}"
    checks = {
        "capability_pack_ref": (
            chapter_binding.capability_pack_ref,
            expected_pack_ref,
        ),
        "capability_pack_compilation_hash": (
            chapter_binding.capability_pack_compilation_hash,
            compiled.compilation_hash,
        ),
        "workflow_node_id": (chapter_binding.workflow_node_id, node.node_id),
        "operation_definition_ref": (
            chapter_binding.operation_definition_ref,
            expected_operation_ref,
        ),
        "operation_definition_hash": (
            chapter_binding.operation_definition_hash,
            node.definition_hash,
        ),
        "agent_definition_ref": (
            chapter_binding.agent_definition_ref,
            node.agent_definition_ref,
        ),
        "capability_id": (
            chapter_binding.capability_ref.rpartition("@")[0],
            node.capability_id,
        ),
        "capability_hash": (
            chapter_binding.capability_hash,
            node.capability_contract_hash,
        ),
        "release_sha": (chapter_binding.release_sha, compiled.release_sha),
    }
    drift = [name for name, values in checks.items() if values[0] != values[1]]
    if drift:
        raise KernelError(
            "CAPABILITY_PACK_AUTHORITY_BINDING_DRIFT",
            "compiled Pack differs from Chapter Agent Binding: " + ", ".join(drift),
        )
    _validate_operation_definition(node, authority_operation_definition)
    return CapabilityPackAuthorityBinding(
        capability_pack_ref=expected_pack_ref,
        capability_pack_compilation_hash=compiled.compilation_hash,
        workflow_node_id=node.node_id,
        operation_definition_ref=expected_operation_ref,
        operation_definition_hash=node.definition_hash,
        agent_definition_ref=node.agent_definition_ref,
        agent_definition_hash=chapter_binding.agent_definition_hash,
        capability_id=node.capability_id,
        capability_hash=node.capability_contract_hash,
        chapter_node_binding_ref=(
            f"{chapter_binding.binding_id}@{chapter_binding.binding_version}"
        ),
        release_sha=compiled.release_sha,
    )


def _validate_operation_definition(
    node: CompiledWorkflowNode, authority: Mapping[str, Any]
) -> None:
    expected = {
        "name": node.definition_name,
        "definition_version": node.definition_version,
        "definition_hash": node.definition_hash,
        "handler_key": node.handler_key,
        "handler_contract_version": node.handler_contract_version,
        "retry_policy": json.loads(node.authoritative_retry_policy_json),
        "timeout_policy": json.loads(node.authoritative_timeout_policy_json),
        "approval_policy": json.loads(node.authoritative_approval_policy_json),
        "compensation_policy": json.loads(node.authoritative_compensation_policy_json),
        "completion_contract": json.loads(node.authoritative_completion_contract_json),
    }
    drift = [name for name, value in expected.items() if authority.get(name) != value]
    if drift:
        raise KernelError(
            "CAPABILITY_PACK_OPERATION_AUTHORITY_CONFLICT",
            "Capability Pack cannot override OperationDefinition: " + ", ".join(drift),
        )


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "CapabilityPackAuthorityBinding",
    "bind_compiled_pack_for_admission",
    "compiled_capability_pack_from_payload",
]
