"""INVARIANT: the diagnostic Pack compiles through the governed workflow catalog."""

import json
from pathlib import Path

from novel_forge.modules.capability_packs.artifacts import (
    ExplicitArtifactResolver, ResolvedArtifact, artifact_content_hash,
    canonical_artifact_json, default_chapter_artifact_resolver,
)
from novel_forge.modules.capability_packs.compiler import CapabilityPackCompiler
from novel_forge.modules.capability_packs.operation_catalog import (
    chapter_operation_definition_catalog, governed_workflow_binding_catalog,
)
from novel_forge.modules.capability_packs.schema import CapabilityPackManifest
from novel_forge.modules.capability_packs.type_catalog import (
    default_capability_type_catalog, default_tool_definition_catalog,
)
from novel_forge.modules.capability_packs.validation_deployment import model_reference_creation_manifest
from novel_forge.modules.capability_packs.versioning import PackCatalogEntry, ReadOnlyPackCatalog
from novel_forge.modules.production_execution.capability_registry import default_capability_registry


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
BUILD = "novel-forge-capability-compiler"


def test_model_reference_derivative_compiles_with_exact_new_workflow_and_artifacts():
    source = json.loads((ROOT / "config/capability_packs/chapter_generation_pack.json").read_text())
    original = json.loads(json.dumps(source))
    manifest = CapabilityPackManifest.from_dict(model_reference_creation_manifest(source,
        application_build_id=BUILD, commit_sha=SHA))
    assert source == original
    artifacts = []
    for item in default_chapter_artifact_resolver(ROOT).artifacts():
        content = json.loads(item.content_json)
        if item.ref == manifest.context_sources.policy_id:
            content["allowed_asset_types"] = list(manifest.context_sources.allowed_asset_types)
            content["required_version_refs"] = list(manifest.context_sources.required_version_refs)
        elif item.ref == manifest.tool_permissions.policy_id:
            content["explicit_tool_refs"] = ["model.provider.invoke"]
        artifacts.append(ResolvedArtifact(item.kind, item.ref, item.version,
            artifact_content_hash(content), canonical_artifact_json(content), item.source_identity))
    compiled = CapabilityPackCompiler(capability_registry=default_capability_registry(),
        capability_type_catalog=default_capability_type_catalog(),
        operation_catalog=chapter_operation_definition_catalog(release_sha=SHA),
        workflow_catalog=governed_workflow_binding_catalog("model_reference_creation", "1.0.0"),
        artifact_resolver=ExplicitArtifactResolver(artifacts),
        tool_catalog=default_tool_definition_catalog(),
        pack_catalog=ReadOnlyPackCatalog((PackCatalogEntry(manifest),))).compile(
            manifest, target_runtime_profile="validation", novel_forge_version="6.0.0",
            release_sha=SHA, release_channel="VALIDATION")
    assert compiled.report.ok, compiled.report.errors
    assert {node.node_id for node in compiled.compiled.workflow_nodes} == {
        "model_reference_evaluate", "model_reference_adjudicate"}
    assert all(json.loads(node.authoritative_completion_contract_json)[
        "required_asset_selectors"][0]["selector"] == "model_reference_provider_result"
        for node in compiled.compiled.workflow_nodes)
