"""Pure, deterministic Capability Pack compiler. It creates no runtime state."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from novel_forge.modules.production_execution.capability_registry import CapabilityRegistry

from .artifacts import ArtifactResolver
from .errors import (
    CapabilityPackCompilationIssue,
    CapabilityPackCompilationReport,
)
from .operation_catalog import OperationDefinitionCatalog, WorkflowBindingCatalog
from .schema import CAPABILITY_PACK_SCHEMA_VERSION, CapabilityPackManifest
from .semantic import validate_capability_pack_semantics
from .type_catalog import CapabilityTypePolicyCatalog, ToolDefinitionCatalog
from .validator import validate_capability_pack
from .versioning import CapabilityPackVersionResolver, ReadOnlyPackCatalog


COMPILED_CAPABILITY_PACK_SCHEMA_VERSION = "novelos.capability_pack.compiled.v1"


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CompiledWorkflowNode:
    ordinal: int
    node_id: str
    definition_name: str
    definition_version: str
    definition_hash: str
    handler_key: str
    handler_contract_version: str
    capability_id: str
    capability_contract_hash: str
    agent_definition_ref: str
    depends_on: tuple[str, ...]
    authoritative_retry_policy_json: str
    authoritative_timeout_policy_json: str
    authoritative_approval_policy_json: str
    authoritative_compensation_policy_json: str
    authoritative_completion_contract_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "node_id": self.node_id,
            "definition_name": self.definition_name,
            "definition_version": self.definition_version,
            "definition_hash": self.definition_hash,
            "handler_key": self.handler_key,
            "handler_contract_version": self.handler_contract_version,
            "capability_id": self.capability_id,
            "capability_contract_hash": self.capability_contract_hash,
            "agent_definition_ref": self.agent_definition_ref,
            "depends_on": list(self.depends_on),
            "authoritative_retry_policy": json.loads(self.authoritative_retry_policy_json),
            "authoritative_timeout_policy": json.loads(self.authoritative_timeout_policy_json),
            "authoritative_approval_policy": json.loads(self.authoritative_approval_policy_json),
            "authoritative_compensation_policy": json.loads(self.authoritative_compensation_policy_json),
            "authoritative_completion_contract": json.loads(self.authoritative_completion_contract_json),
        }


@dataclass(frozen=True, slots=True)
class CompiledCapabilityPack:
    schema_version: str
    pack_id: str
    pack_version: str
    manifest_hash: str
    protocol_version: str
    target_runtime_profile: str
    novel_forge_version: str
    release_channel: str
    release_sha: str
    catalog_snapshot_hash: str
    compilation_hash: str
    capability_type_policy_json: str
    resolved_capabilities_json: str
    resolved_operations_json: str
    resolved_artifacts_json: str
    workflow_nodes: tuple[CompiledWorkflowNode, ...]
    external_input_asset_contract: tuple[str, ...]
    completion_contract_json: str
    tool_permission_snapshot_json: str
    context_source_snapshot_json: str
    evaluation_gate_snapshot_json: str
    audit_requirement_snapshot_json: str
    version_resolution_snapshot_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "manifest_hash": self.manifest_hash,
            "protocol_version": self.protocol_version,
            "target_runtime_profile": self.target_runtime_profile,
            "novel_forge_version": self.novel_forge_version,
            "release_channel": self.release_channel,
            "release_sha": self.release_sha,
            "catalog_snapshot_hash": self.catalog_snapshot_hash,
            "compilation_hash": self.compilation_hash,
            "capability_type_policy": json.loads(self.capability_type_policy_json),
            "resolved_capabilities": json.loads(self.resolved_capabilities_json),
            "resolved_operations": json.loads(self.resolved_operations_json),
            "resolved_artifacts": json.loads(self.resolved_artifacts_json),
            "workflow_nodes": [item.to_dict() for item in self.workflow_nodes],
            "external_input_asset_contract": list(self.external_input_asset_contract),
            "completion_contract": json.loads(self.completion_contract_json),
            "tool_permission_snapshot": json.loads(self.tool_permission_snapshot_json),
            "context_source_snapshot": json.loads(self.context_source_snapshot_json),
            "evaluation_gate_snapshot": json.loads(self.evaluation_gate_snapshot_json),
            "audit_requirement_snapshot": json.loads(self.audit_requirement_snapshot_json),
            "version_resolution_snapshot": json.loads(self.version_resolution_snapshot_json),
        }

    @property
    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class CapabilityPackCompilationResult:
    compiled: CompiledCapabilityPack | None
    report: CapabilityPackCompilationReport


class CapabilityPackCompiler:
    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        capability_type_catalog: CapabilityTypePolicyCatalog,
        operation_catalog: OperationDefinitionCatalog,
        workflow_catalog: WorkflowBindingCatalog,
        artifact_resolver: ArtifactResolver,
        tool_catalog: ToolDefinitionCatalog,
        pack_catalog: ReadOnlyPackCatalog,
        version_resolver: CapabilityPackVersionResolver | None = None,
    ) -> None:
        self.capability_registry = capability_registry
        self.capability_type_catalog = capability_type_catalog
        self.operation_catalog = operation_catalog
        self.workflow_catalog = workflow_catalog
        self.artifact_resolver = artifact_resolver
        self.tool_catalog = tool_catalog
        self.pack_catalog = pack_catalog
        self.version_resolver = version_resolver or CapabilityPackVersionResolver()

    def compile(
        self,
        manifest: CapabilityPackManifest,
        *,
        target_runtime_profile: str,
        novel_forge_version: str,
        release_sha: str,
        release_channel: str,
        expected_manifest_hash: str | None = None,
    ) -> CapabilityPackCompilationResult:
        errors: list[CapabilityPackCompilationIssue] = []
        warnings: list[CapabilityPackCompilationIssue] = []
        if expected_manifest_hash is not None and expected_manifest_hash != manifest.manifest_hash:
            errors.append(CapabilityPackCompilationIssue("CAPABILITY_PACK_MANIFEST_HASH_DRIFT", "$", "Manifest hash differs from the caller-bound identity"))
        static = validate_capability_pack(
            manifest, capability_registry=self.capability_registry
        )
        errors.extend(
            CapabilityPackCompilationIssue(item.code, item.path, item.message, item.severity)
            for item in static.errors
        )
        warnings.extend(
            CapabilityPackCompilationIssue(item.code, item.path, item.message, item.severity)
            for item in static.warnings
        )
        try:
            version_set = self.version_resolver.resolve(
                pack_id=str(manifest.identity.pack_id),
                pack_version=str(manifest.identity.version),
                protocol_version=str(manifest.schema_version),
                novel_forge_version=novel_forge_version,
                release_sha=release_sha,
                runtime_profile=target_runtime_profile,
                release_channel=release_channel,
                catalog=self.pack_catalog,
            )
        except (KeyError, ValueError) as exc:
            errors.append(CapabilityPackCompilationIssue("CAPABILITY_PACK_VERSION_RESOLUTION_FAILED", "$.compatibility", str(exc)))
            version_set = None
        if version_set is not None:
            root_identity = (
                f"{manifest.identity.pack_id}@{manifest.identity.version}"
            )
            resolved_manifest_hashes = dict(version_set.manifest_hashes)
            if resolved_manifest_hashes.get(root_identity) != manifest.manifest_hash:
                errors.append(
                    CapabilityPackCompilationIssue(
                        "CAPABILITY_PACK_CATALOG_IDENTITY_CONFLICT",
                        "$.identity",
                        "compiled Manifest differs from the exact root Pack Catalog entry",
                    )
                )

        semantic = validate_capability_pack_semantics(
            manifest,
            capability_registry=self.capability_registry,
            capability_type_catalog=self.capability_type_catalog,
            operation_catalog=self.operation_catalog,
            workflow_catalog=self.workflow_catalog,
            artifact_resolver=self.artifact_resolver,
            tool_catalog=self.tool_catalog,
        )
        errors.extend(semantic.report.errors)
        warnings.extend(semantic.report.warnings)
        for operation in semantic.operations:
            if operation.source_commit_sha != release_sha:
                errors.append(
                    CapabilityPackCompilationIssue(
                        "CAPABILITY_PACK_RELEASE_IDENTITY_CONFLICT",
                        f"operation:{operation.definition_name}",
                        "OperationDefinition snapshot belongs to a different release SHA",
                    )
                )
        if errors or version_set is None:
            return CapabilityPackCompilationResult(
                None,
                CapabilityPackCompilationReport(
                    False,
                    str(manifest.identity.pack_id),
                    str(manifest.identity.version),
                    manifest.manifest_hash,
                    "",
                    tuple(errors),
                    tuple(warnings),
                ),
            )

        type_policy = self.capability_type_catalog.resolve(
            str(manifest.identity.capability_type)
        )
        capability_definitions = {
            capability_id: self.capability_registry.resolve(capability_id)
            for capability_id in semantic.capability_ids
        }
        operation_by_identity = {
            (item.definition_name, item.definition_version): item
            for item in semantic.operations
        }
        order = _topological_order(manifest)
        node_by_id = {
            str(node.node_id): node for node in manifest.workflow_template.nodes
        }
        compiled_nodes: list[CompiledWorkflowNode] = []
        for ordinal, node_id in enumerate(order, start=1):
            node = node_by_id[node_id]
            definition_name, separator, definition_version = str(
                node.operation_definition_ref
            ).rpartition("@")
            if not separator:  # guarded by semantic validation
                raise ValueError("compiled node has no exact OperationDefinition ref")
            operation = operation_by_identity[
                (definition_name, definition_version)
            ]
            capability = capability_definitions[str(node.capability_id)]
            compiled_nodes.append(
                CompiledWorkflowNode(
                    ordinal=ordinal,
                    node_id=node_id,
                    definition_name=operation.definition_name,
                    definition_version=operation.definition_version,
                    definition_hash=operation.definition_hash,
                    handler_key=operation.handler_key,
                    handler_contract_version=operation.handler_contract_version,
                    capability_id=str(node.capability_id),
                    capability_contract_hash="sha256:" + capability.contract_hash,
                    agent_definition_ref=str(node.agent_definition_ref or ""),
                    depends_on=tuple(sorted(str(item) for item in node.depends_on)),
                    authoritative_retry_policy_json=operation.retry_policy_json,
                    authoritative_timeout_policy_json=operation.timeout_policy_json,
                    authoritative_approval_policy_json=operation.approval_policy_json,
                    authoritative_compensation_policy_json=operation.compensation_policy_json,
                    authoritative_completion_contract_json=operation.completion_contract_json,
                )
            )

        capabilities_snapshot = [
            {
                "capability_id": key,
                "contract_hash": "sha256:" + capability_definitions[key].contract_hash,
                "definition": capability_definitions[key].to_dict(),
            }
            for key in sorted(capability_definitions)
        ]
        operations_snapshot = [item.to_dict() for item in sorted(semantic.operations, key=lambda value: (value.definition_name, value.definition_version))]
        artifacts_snapshot = [
            {
                "kind": item.kind.value,
                "ref": item.ref,
                "version": item.version,
                "content_hash": item.content_hash,
                "source_identity": item.source_identity,
            }
            for item in semantic.artifacts
        ]
        catalog_snapshot = {
            "capability_type_policy": type_policy.to_dict(),
            "capability_registry": capabilities_snapshot,
            "operation_definitions": operations_snapshot,
            "workflow_bindings": [
                {
                    "node_id": item.node_id,
                    "operation_name": item.operation_name,
                    "stage": item.stage,
                    "handler_key": item.handler_key,
                    "capability_id": item.capability_id,
                    "depends_on": list(item.depends_on),
                    "primary_output_asset_type": item.primary_output_asset_type,
                }
                for item in self.workflow_catalog.bindings()
            ],
            "tool_definitions": [
                self.tool_catalog.resolve(str(tool.tool_ref)).to_dict()
                for tool in sorted(
                    manifest.tool_permissions.tools,
                    key=lambda item: str(item.tool_ref),
                )
            ],
            "resolved_artifacts": artifacts_snapshot,
            "resolved_pack_set": list(version_set.manifest_hashes),
        }
        catalog_snapshot_hash = _hash(catalog_snapshot)
        payload_without_hash = {
            "schema_version": COMPILED_CAPABILITY_PACK_SCHEMA_VERSION,
            "pack_id": str(manifest.identity.pack_id),
            "pack_version": str(manifest.identity.version),
            "manifest_hash": manifest.manifest_hash,
            "protocol_version": CAPABILITY_PACK_SCHEMA_VERSION,
            "target_runtime_profile": target_runtime_profile,
            "novel_forge_version": novel_forge_version,
            "release_channel": release_channel,
            "release_sha": release_sha,
            "catalog_snapshot_hash": catalog_snapshot_hash,
            "capability_type_policy": type_policy.to_dict(),
            "resolved_capabilities": capabilities_snapshot,
            "resolved_operations": operations_snapshot,
            "resolved_artifacts": artifacts_snapshot,
            "workflow_nodes": [item.to_dict() for item in compiled_nodes],
            "external_input_asset_contract": sorted(str(item) for item in manifest.context_sources.allowed_asset_types),
            "completion_contract": manifest.to_dict()["workflow_template"]["completion"],
            "tool_permission_snapshot": manifest.to_dict()["tool_permissions"],
            "context_source_snapshot": manifest.to_dict()["context_sources"],
            "evaluation_gate_snapshot": manifest.to_dict()["evaluation"],
            "audit_requirement_snapshot": manifest.to_dict()["audit"],
            "version_resolution_snapshot": {
                "dependency_order": list(version_set.dependency_order),
                "manifest_hashes": [list(item) for item in version_set.manifest_hashes],
                "dependency_edges": [list(item) for item in version_set.dependency_edges],
                "novel_forge_version": novel_forge_version,
                "release_channel": release_channel,
                "runtime_profile": target_runtime_profile,
            },
        }
        compilation_hash = _hash(payload_without_hash)
        compiled = CompiledCapabilityPack(
            schema_version=COMPILED_CAPABILITY_PACK_SCHEMA_VERSION,
            pack_id=str(manifest.identity.pack_id),
            pack_version=str(manifest.identity.version),
            manifest_hash=manifest.manifest_hash,
            protocol_version=CAPABILITY_PACK_SCHEMA_VERSION,
            target_runtime_profile=target_runtime_profile,
            novel_forge_version=novel_forge_version,
            release_channel=release_channel,
            release_sha=release_sha,
            catalog_snapshot_hash=catalog_snapshot_hash,
            compilation_hash=compilation_hash,
            capability_type_policy_json=_canonical(type_policy.to_dict()),
            resolved_capabilities_json=_canonical(capabilities_snapshot),
            resolved_operations_json=_canonical(operations_snapshot),
            resolved_artifacts_json=_canonical(artifacts_snapshot),
            workflow_nodes=tuple(compiled_nodes),
            external_input_asset_contract=tuple(sorted(str(item) for item in manifest.context_sources.allowed_asset_types)),
            completion_contract_json=_canonical(manifest.to_dict()["workflow_template"]["completion"]),
            tool_permission_snapshot_json=_canonical(manifest.to_dict()["tool_permissions"]),
            context_source_snapshot_json=_canonical(manifest.to_dict()["context_sources"]),
            evaluation_gate_snapshot_json=_canonical(manifest.to_dict()["evaluation"]),
            audit_requirement_snapshot_json=_canonical(manifest.to_dict()["audit"]),
            version_resolution_snapshot_json=_canonical(payload_without_hash["version_resolution_snapshot"]),
        )
        return CapabilityPackCompilationResult(
            compiled,
            CapabilityPackCompilationReport(
                True,
                compiled.pack_id,
                compiled.pack_version,
                compiled.manifest_hash,
                compiled.compilation_hash,
                (),
                tuple(warnings),
            ),
        )


def _topological_order(manifest: CapabilityPackManifest) -> tuple[str, ...]:
    graph = {
        str(node.node_id): tuple(str(item) for item in node.depends_on)
        for node in manifest.workflow_template.nodes
    }
    indegree = {key: len(value) for key, value in graph.items()}
    outgoing = {key: [] for key in graph}
    for node, dependencies in graph.items():
        for dependency in dependencies:
            outgoing[dependency].append(node)
    ready = sorted(key for key, value in indegree.items() if value == 0)
    result: list[str] = []
    while ready:
        node = ready.pop(0)
        result.append(node)
        for child in sorted(outgoing[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(result) != len(graph):
        raise ValueError("workflow graph contains a cycle")
    return tuple(result)


__all__ = [
    "COMPILED_CAPABILITY_PACK_SCHEMA_VERSION",
    "CapabilityPackCompilationResult",
    "CapabilityPackCompiler",
    "CompiledCapabilityPack",
    "CompiledWorkflowNode",
]
