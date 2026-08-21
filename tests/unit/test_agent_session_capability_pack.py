from __future__ import annotations

from pathlib import Path
import json

from novel_forge.modules.agent_runtime.definitions import (
    agent_runtime_operation_definitions,
)
from novel_forge.modules.capability_packs import (
    load_capability_pack,
    validate_capability_pack,
)
from novel_forge.modules.capability_packs.artifacts import (
    default_chapter_artifact_resolver,
)
from novel_forge.modules.capability_packs.compiler import CapabilityPackCompiler
from novel_forge.modules.capability_packs.operation_catalog import (
    InMemoryOperationDefinitionCatalog,
    agent_session_workflow_binding_catalog,
)
from novel_forge.modules.capability_packs.type_catalog import (
    default_capability_type_catalog,
    default_tool_definition_catalog,
)
from novel_forge.modules.capability_packs.versioning import (
    PackCatalogEntry,
    ReadOnlyPackCatalog,
)
from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "config/capability_packs/agent_session_pack.json"
RELEASE_SHA = "e" * 40


def test_agent_session_pack_validates_and_compiles_against_runtime_contract() -> None:
    manifest = load_capability_pack(PACK)
    validation = validate_capability_pack(manifest)
    assert validation.ok, validation.to_dict()

    compiled = CapabilityPackCompiler(
        capability_registry=default_capability_registry(),
        capability_type_catalog=default_capability_type_catalog(),
        operation_catalog=InMemoryOperationDefinitionCatalog(
            agent_runtime_operation_definitions(
                application_build_id="agent-session-pack-test",
                commit_sha=RELEASE_SHA,
            )
        ),
        workflow_catalog=agent_session_workflow_binding_catalog(),
        artifact_resolver=default_chapter_artifact_resolver(ROOT),
        tool_catalog=default_tool_definition_catalog(),
        pack_catalog=ReadOnlyPackCatalog((PackCatalogEntry(manifest),)),
    ).compile(
        manifest,
        target_runtime_profile="test",
        novel_forge_version="6.0.0",
        release_sha=RELEASE_SHA,
        release_channel="VALIDATION",
        expected_manifest_hash=manifest.manifest_hash,
    )

    assert compiled.report.ok, compiled.report.to_dict()
    assert compiled.compiled is not None
    node = compiled.compiled.workflow_nodes[0]
    assert node.node_id == "agent_session"
    assert node.agent_definition_ref == "studio-director@1"
    assert node.commit_authority == "AGENT_RUNTIME_AUTHORITY"
    assert json.loads(compiled.compiled.tool_permission_snapshot_json)["default"] == (
        "DENY"
    )
