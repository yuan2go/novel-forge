from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    ExplicitArtifactResolver,
    ResolvedArtifact,
    artifact_content_hash,
    canonical_artifact_json,
    default_chapter_artifact_resolver,
    exact_ref_version,
)
from novel_forge.modules.capability_packs.compiler import CapabilityPackCompiler
from novel_forge.modules.capability_packs.loader import load_capability_pack_payload
from novel_forge.modules.capability_packs.loader import load_capability_pack
from novel_forge.modules.capability_packs.operation_catalog import (
    InMemoryOperationDefinitionCatalog,
    RepositoryOperationDefinitionLoader,
    chapter_operation_definition_catalog,
    chapter_workflow_binding_catalog,
    governed_workflow_binding_catalog,
)
from novel_forge.modules.capability_packs.type_catalog import (
    default_capability_type_catalog,
    default_tool_definition_catalog,
)
from novel_forge.modules.capability_packs.validator import validate_capability_pack
from novel_forge.modules.capability_packs.versioning import (
    CapabilityPackVersionResolver,
    PackCatalogEntry,
    PackDependency,
    ReadOnlyPackCatalog,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
)
from novel_forge.modules.command_kernel.lifecycle import AttemptStatus, OperationStatus
from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.storage.authority_repositories import definition_hash


ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "config/capability_packs/chapter_generation_pack.json"
FIXTURE_RELEASE_SHA = "dcaf300057b997ac49099bcb4839f063774320ce"


class CapabilityPackP1ATests(unittest.TestCase):
    def test_final_quality_binding_is_deterministic_aggregate(self) -> None:
        manifest = self.manifest()
        quality = next(
            node
            for node in manifest.workflow_template.nodes
            if node.node_id == "quality"
        )

        self.assertEqual(
            chapter_workflow_binding_catalog().resolve("quality").capability_id,
            "quality.aggregate",
        )
        self.assertEqual(quality.capability_id, "quality.aggregate")
        self.assertEqual(quality.timeout_policy_ref, "timeout:quality-aggregate:v1")

    def test_reader_outcome_has_a_governed_workflow_binding(self) -> None:
        catalog = governed_workflow_binding_catalog(
            "book_followup_reader_outcome", "1.1.0"
        )

        binding = catalog.resolve("reader_outcome")

        self.assertEqual(binding.operation_name, "reader_outcome.evaluate")
        self.assertEqual(binding.stage, "reader_outcome")
        self.assertEqual(binding.capability_id, "quality.reader_outcome.judge")
        self.assertEqual(binding.primary_output_asset_type, "reader_outcome_report")

    def payload(self) -> dict:
        return json.loads(PACK_PATH.read_text(encoding="utf-8"))

    def manifest(self, payload: dict | None = None):
        return load_capability_pack_payload(payload or self.payload())

    def operation_rows(self) -> list[dict]:
        return [
            copy.deepcopy(item)
            for item in chapter_operation_definitions(
                application_build_id="novel-forge-capability-compiler",
                commit_sha=FIXTURE_RELEASE_SHA,
                model_effects_required=True,
                coordinated_contract=True,
            )
        ]

    def compiler(
        self,
        manifest=None,
        *,
        operation_catalog=None,
        artifact_resolver=None,
        pack_catalog=None,
    ) -> CapabilityPackCompiler:
        manifest = manifest or self.manifest()
        return CapabilityPackCompiler(
            capability_registry=default_capability_registry(),
            capability_type_catalog=default_capability_type_catalog(),
            operation_catalog=operation_catalog
            or chapter_operation_definition_catalog(release_sha=FIXTURE_RELEASE_SHA),
            workflow_catalog=chapter_workflow_binding_catalog(),
            artifact_resolver=artifact_resolver
            or default_chapter_artifact_resolver(ROOT),
            tool_catalog=default_tool_definition_catalog(),
            pack_catalog=pack_catalog
            or ReadOnlyPackCatalog((PackCatalogEntry(manifest),)),
        )

    def compile(self, manifest=None, **kwargs):
        manifest = manifest or self.manifest()
        return self.compiler(manifest, **kwargs).compile(
            manifest,
            target_runtime_profile="validation",
            novel_forge_version="6.0.0",
            release_sha=FIXTURE_RELEASE_SHA,
            release_channel="VALIDATION",
        )

    def codes(self, result) -> set[str]:
        return {item.code for item in result.report.errors}

    def test_chapter_pack_compiles_to_immutable_snapshot(self) -> None:
        result = self.compile()
        self.assertTrue(result.report.ok, result.report.errors)
        self.assertIsNotNone(result.compiled)
        compiled = result.compiled
        assert compiled is not None
        node_ids = {node.node_id for node in compiled.workflow_nodes}
        self.assertEqual(len(node_ids), 22)
        self.assertTrue(
            {"execution_intent", "memo", "best_candidate"}.issubset(node_ids)
        )
        with self.assertRaises(FrozenInstanceError):
            compiled.pack_id = "changed"  # type: ignore[misc]
        detached = compiled.to_dict()
        detached["resolved_artifacts"].clear()
        self.assertTrue(compiled.to_dict()["resolved_artifacts"])

    def test_compilation_hash_is_deterministic(self) -> None:
        first = self.compile().compiled
        second = self.compile().compiled
        self.assertIsNotNone(first)
        self.assertEqual(first.compilation_hash, second.compilation_hash)
        self.assertEqual(first.canonical_json, second.canonical_json)

    def test_catalog_input_order_does_not_change_compilation_hash(self) -> None:
        manifest = self.manifest()
        rows = self.operation_rows()
        normal = self.compile(
            manifest,
            operation_catalog=InMemoryOperationDefinitionCatalog(rows),
        ).compiled
        reversed_result = self.compile(
            manifest,
            operation_catalog=InMemoryOperationDefinitionCatalog(reversed(rows)),
        ).compiled
        self.assertEqual(normal.compilation_hash, reversed_result.compilation_hash)

    def test_artifact_catalog_order_does_not_change_compilation_hash(self) -> None:
        manifest = self.manifest()
        resolver = default_chapter_artifact_resolver(ROOT)
        normal = self.compile(
            manifest,
            artifact_resolver=ExplicitArtifactResolver(resolver.artifacts()),
        ).compiled
        reversed_result = self.compile(
            manifest,
            artifact_resolver=ExplicitArtifactResolver(reversed(resolver.artifacts())),
        ).compiled
        self.assertEqual(normal.compilation_hash, reversed_result.compilation_hash)

    def test_artifact_identity_rejects_different_provenance(self) -> None:
        content = {"contract": "same"}
        digest = artifact_content_hash(content)
        first = ResolvedArtifact(
            ArtifactKind.SCHEMA,
            "schema:identity:v1",
            "v1",
            digest,
            canonical_artifact_json(content),
            "catalog:first",
        )
        second = ResolvedArtifact(
            ArtifactKind.SCHEMA,
            "schema:identity:v1",
            "v1",
            digest,
            canonical_artifact_json(content),
            "catalog:second",
        )
        with self.assertRaisesRegex(ValueError, "content or provenance"):
            ExplicitArtifactResolver((first, second))

    def test_catalog_content_change_changes_compilation_hash(self) -> None:
        manifest = self.manifest()
        resolver = default_chapter_artifact_resolver(ROOT)
        content = {
            "policy_id": "budget:chapter-generation-pack:v1",
            "bounded": True,
            "receipt_required": True,
            "maximum_cost_units": 100,
        }
        changed_budget = ResolvedArtifact(
            ArtifactKind.BUDGET_POLICY,
            "budget:chapter-generation-pack:v1",
            "v1",
            artifact_content_hash(content),
            canonical_artifact_json(content),
            "test-catalog",
        )
        artifacts = tuple(
            changed_budget
            if item.kind is ArtifactKind.BUDGET_POLICY
            and item.ref == "budget:chapter-generation-pack:v1"
            else item
            for item in resolver.artifacts()
        )
        baseline = self.compile(manifest).compiled
        changed = self.compile(
            manifest,
            artifact_resolver=ExplicitArtifactResolver(artifacts),
        ).compiled
        self.assertNotEqual(baseline.compilation_hash, changed.compilation_hash)

    def test_current_chapter_operations_all_resolve(self) -> None:
        catalog = chapter_operation_definition_catalog(release_sha=FIXTURE_RELEASE_SHA)
        bindings = {binding.node_id: binding for binding in self.manifest().workflow_template.nodes}
        for node in ChapterNode:
            binding = bindings[node.value]
            definition = catalog.resolve(
                node.definition_name, binding.operation_definition_ref.rsplit("@", 1)[1]
            )
            self.assertEqual(definition.handler_key, node.handler_key)
            self.assertTrue(definition.definition_hash.startswith("sha256:"))

    def test_definition_hash_is_deterministic(self) -> None:
        row = self.operation_rows()[0]
        self.assertEqual(definition_hash(row), definition_hash(copy.deepcopy(row)))

    def test_postgres_repository_adapter_preloads_read_only_snapshot(self) -> None:
        row = self.operation_rows()[0]
        persisted = {**row, "definition_hash": definition_hash(row)}

        class Repository:
            def get(self, name: str, version: str):
                if (name, version) == (row["name"], row["definition_version"]):
                    return copy.deepcopy(persisted)
                return None

        catalog = RepositoryOperationDefinitionLoader(Repository()).load(
            ((row["name"], row["definition_version"]),)
        )
        resolved = catalog.resolve(row["name"], row["definition_version"])
        self.assertEqual(resolved.definition_hash, definition_hash(row))
        self.assertEqual(resolved.source_commit_sha, FIXTURE_RELEASE_SHA)

    def test_postgres_repository_adapter_rejects_persisted_hash_drift(self) -> None:
        row = self.operation_rows()[0]

        class Repository:
            def get(self, name: str, version: str):
                del name, version
                return {**row, "definition_hash": "sha256:" + "0" * 64}

        with self.assertRaisesRegex(ValueError, "persisted OperationDefinition hash"):
            RepositoryOperationDefinitionLoader(Repository()).load(
                ((row["name"], row["definition_version"]),)
            )

    def test_same_operation_identity_with_different_content_is_rejected(self) -> None:
        row = self.operation_rows()[0]
        changed = copy.deepcopy(row)
        changed["handler_key"] = "drifted.handler"
        with self.assertRaises(ValueError):
            InMemoryOperationDefinitionCatalog((row, changed))

    def test_same_operation_identity_rejects_governance_metadata_conflict(self) -> None:
        row = self.operation_rows()[0]
        changes = (
            {"enabled": False},
            {"application_build_id": "different-build"},
            {"commit_sha": "f" * 40},
        )
        for change in changes:
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "different full snapshot"),
            ):
                InMemoryOperationDefinitionCatalog((row, {**row, **change}))

    def test_operation_enabled_requires_exact_boolean(self) -> None:
        row = self.operation_rows()[0]
        for invalid in ("false", 0, None):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(TypeError, "exact boolean"),
            ):
                InMemoryOperationDefinitionCatalog(({**row, "enabled": invalid},))

    def test_handler_drift_is_rejected(self) -> None:
        payload = self.payload()
        payload["workflow_template"]["nodes"][0]["handler_key"] = "drifted.handler"
        self.assertIn(
            "CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_retry_drift_is_rejected(self) -> None:
        payload = self.payload()
        payload["workflow_template"]["nodes"][0]["retry_policy"]["max_attempts"] = 3
        self.assertIn(
            "CAPABILITY_PACK_OPERATION_POLICY_CONFLICT",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_completion_drift_is_rejected(self) -> None:
        rows = self.operation_rows()
        rows[0]["completion_contract"] = {
            **rows[0]["completion_contract"],
            "required_evidence": ["trace"],
        }
        result = self.compile(
            operation_catalog=InMemoryOperationDefinitionCatalog(rows)
        )
        self.assertIn("CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT", self.codes(result))

    def test_schema_drift_is_rejected(self) -> None:
        rows = self.operation_rows()
        rows[0]["command_schema"] = {"type": "object", "required": ["drift"]}
        result = self.compile(
            operation_catalog=InMemoryOperationDefinitionCatalog(rows)
        )
        self.assertIn("CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT", self.codes(result))

    def test_disabled_operation_definition_is_rejected(self) -> None:
        rows = self.operation_rows()
        rows[0]["enabled"] = False
        result = self.compile(
            operation_catalog=InMemoryOperationDefinitionCatalog(rows)
        )
        self.assertIn(
            "CAPABILITY_PACK_OPERATION_DEFINITION_DISABLED", self.codes(result)
        )

    def test_operation_snapshot_release_sha_mismatch_is_rejected(self) -> None:
        catalog = chapter_operation_definition_catalog(release_sha="f" * 40)
        result = self.compile(operation_catalog=catalog)
        self.assertIn("CAPABILITY_PACK_RELEASE_IDENTITY_CONFLICT", self.codes(result))

    def test_skill_real_content_hash_is_verified(self) -> None:
        manifest = self.manifest()
        skill = manifest.skill_binding.skills[0]
        artifact = default_chapter_artifact_resolver(ROOT).resolve(
            ArtifactKind.SKILL, str(skill.skill_ref), str(skill.version)
        )
        self.assertEqual(skill.content_hash, artifact.content_hash)
        self.assertEqual(artifact.source_identity, "skills/chapter-outline/legacy-narrative-intent-20261010.md")

    def test_skill_hash_drift_is_rejected(self) -> None:
        payload = self.payload()
        payload["skill_binding"]["skills"][0]["content_hash"] = "sha256:" + "0" * 64
        self.assertIn(
            "CAPABILITY_PACK_ARTIFACT_HASH_MISMATCH",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_prompt_hash_drift_is_rejected(self) -> None:
        payload = self.payload()
        payload["prompt_binding"]["template_hash"] = "sha256:" + "0" * 64
        self.assertIn(
            "CAPABILITY_PACK_ARTIFACT_HASH_MISMATCH",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_missing_artifact_is_rejected(self) -> None:
        payload = self.payload()
        payload["prompt_binding"]["template_ref"] = "prompt-template:missing"
        result = self.compile(self.manifest(payload))
        self.assertIn("CAPABILITY_PACK_ARTIFACT_NOT_FOUND", self.codes(result))

    def test_resolved_policy_drift_is_rejected(self) -> None:
        payload = self.payload()
        payload["context_sources"]["max_tokens"] = 5999
        result = self.compile(self.manifest(payload))
        self.assertIn("CAPABILITY_PACK_POLICY_BINDING_INVALID", self.codes(result))

    def test_state_schema_matches_command_kernel_lifecycle(self) -> None:
        schema = default_chapter_artifact_resolver(ROOT).resolve(
            ArtifactKind.SCHEMA,
            "operation-saga-attempt-state.v1",
            "v1",
        )
        properties = json.loads(schema.content_json)["properties"]
        self.assertEqual(
            set(properties["operation_status"]["enum"]),
            {item.value for item in OperationStatus},
        )
        self.assertEqual(
            set(properties["attempt_status"]["enum"]),
            {item.value for item in AttemptStatus},
        )
        self.assertEqual(
            set(properties["saga_status"]["enum"]),
            {
                "RUNNING",
                "FORWARD_RECOVERY",
                "WAITING_GATE",
                "COMPENSATING",
                "SUCCEEDED",
                "COMPENSATED",
                "COMPENSATION_FAILED",
                "MANUAL_INTERVENTION",
                "CANCELLED",
            },
        )

    def test_schema_hash_patterns_are_explicitly_string_typed(self) -> None:
        checked = 0

        def visit(value) -> None:
            nonlocal checked
            if isinstance(value, dict):
                if value.get("pattern") == "^sha256:[0-9a-f]{64}$":
                    checked += 1
                    self.assertEqual(value.get("type"), "string")
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for artifact in default_chapter_artifact_resolver(ROOT).artifacts():
            if artifact.kind is ArtifactKind.SCHEMA:
                visit(json.loads(artifact.content_json))
        self.assertGreater(checked, 0)

    def test_artifact_canonical_json_rejects_non_finite_numbers(self) -> None:
        with self.assertRaises(ValueError):
            artifact_content_hash({"value": float("nan")})
        with tempfile.TemporaryDirectory(
            dir=ROOT / "config/capability_packs/artifacts"
        ) as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(
                '{"schema_version":"novelos.capability_pack.artifact_catalog.v1",'
                '"artifacts":[{"kind":"SCHEMA","ref":"schema:x:v1",'
                '"version":"v1","content":{"value":NaN}}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "non-finite JSON number"):
                ExplicitArtifactResolver.from_catalog_file(ROOT, path)

    def test_floating_artifact_alias_is_rejected(self) -> None:
        for alias in ("latest", "stable", "main", "HEAD", "nightly"):
            payload = self.payload()
            payload["skill_binding"]["skills"][0]["version"] = alias
            result = self.compile(self.manifest(payload))
            with self.subTest(alias=alias):
                self.assertIn(
                    "CAPABILITY_PACK_FLOATING_VERSION_FORBIDDEN",
                    self.codes(result),
                )

    def test_resolution_does_not_use_network_or_environment(self) -> None:
        with (
            mock.patch("os.getenv", side_effect=AssertionError("environment read")),
            mock.patch(
                "urllib.request.urlopen", side_effect=AssertionError("network read")
            ),
        ):
            result = self.compile()
        self.assertTrue(result.report.ok, result.report.errors)

    def test_workflow_input_without_producer_is_rejected(self) -> None:
        payload = self.payload()
        payload["workflow_template"]["nodes"][2]["input_asset_types"].append(
            "missing_asset"
        )
        self.assertIn(
            "CAPABILITY_PACK_WORKFLOW_INPUT_UNSATISFIED",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_workflow_cycle_returns_structured_compilation_report(self) -> None:
        payload = self.payload()
        payload["workflow_template"]["nodes"][0]["depends_on"] = ["final_release_gate"]
        result = self.compile(self.manifest(payload))
        self.assertIsNone(result.compiled)
        self.assertIn("CAPABILITY_PACK_WORKFLOW_CYCLE", self.codes(result))

    def test_completion_output_without_producer_is_rejected(self) -> None:
        payload = self.payload()
        payload["workflow_template"]["completion"][
            "required_output_asset_types"
        ].append("missing_asset")
        self.assertIn(
            "CAPABILITY_PACK_COMPLETION_OUTPUT_UNPRODUCED",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_evaluation_evidence_without_producer_is_rejected(self) -> None:
        payload = self.payload()
        payload["evaluation"]["required_gates"][0]["required_evidence"] = [
            "missing_evidence"
        ]
        self.assertIn(
            "CAPABILITY_PACK_EVALUATION_EVIDENCE_UNPRODUCED",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_required_capability_coverage_is_enforced(self) -> None:
        payload = self.payload()
        payload["compatibility"]["required_capabilities"].remove("prose.chapter.draft")
        self.assertIn(
            "CAPABILITY_PACK_CAPABILITY_SET_INCOMPLETE",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_tool_operation_external_capability_conflict_is_rejected(self) -> None:
        payload = self.payload()
        payload["tool_permissions"]["tools"][0]["allowed_operations"] = ["context"]
        self.assertIn(
            "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_tool_permission_action_conflict_is_rejected(self) -> None:
        payload = self.payload()
        payload["tool_permissions"]["tools"][0]["permission"] = "READ"
        self.assertIn(
            "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_operation_external_capability_requires_tool_binding(self) -> None:
        payload = self.payload()
        payload["tool_permissions"]["tools"] = [
            tool
            for tool in payload["tool_permissions"]["tools"]
            if tool["tool_ref"] != "model.provider.invoke"
        ]
        self.assertIn(
            "CAPABILITY_PACK_TOOL_CAPABILITY_CONFLICT",
            self.codes(self.compile(self.manifest(payload))),
        )

    def test_manifest_hash_drift_is_rejected(self) -> None:
        manifest = self.manifest()
        result = self.compiler(manifest).compile(
            manifest,
            target_runtime_profile="validation",
            novel_forge_version="6.0.0",
            release_sha=FIXTURE_RELEASE_SHA,
            release_channel="VALIDATION",
            expected_manifest_hash="sha256:" + "0" * 64,
        )
        self.assertIn("CAPABILITY_PACK_MANIFEST_HASH_DRIFT", self.codes(result))

    def test_compile_rejects_root_pack_catalog_manifest_mismatch(self) -> None:
        manifest = self.manifest()
        catalog_payload = self.payload()
        catalog_payload["identity"]["description"] = "different catalog content"
        catalog_manifest = self.manifest(catalog_payload)
        result = self.compile(
            manifest,
            pack_catalog=ReadOnlyPackCatalog((PackCatalogEntry(catalog_manifest),)),
        )
        self.assertIn("CAPABILITY_PACK_CATALOG_IDENTITY_CONFLICT", self.codes(result))

    def test_compile_creates_no_authority_or_provider_state(self) -> None:
        with (
            mock.patch(
                "novel_forge.storage.authority_uow.AuthorityUnitOfWork",
                side_effect=AssertionError("database access"),
            ),
            mock.patch(
                "novel_forge.modules.production_execution.gateway.ProductionExecutionGateway.submit",
                side_effect=AssertionError("Provider execution"),
            ),
        ):
            result = self.compile()
        self.assertTrue(result.report.ok, result.report.errors)

    def test_version_resolver_rejects_runtime_profile(self) -> None:
        manifest = self.manifest()
        with self.assertRaises(ValueError):
            CapabilityPackVersionResolver().resolve(
                pack_id=str(manifest.identity.pack_id),
                pack_version=str(manifest.identity.version),
                protocol_version=str(manifest.schema_version),
                novel_forge_version="6.0.0",
                release_sha=FIXTURE_RELEASE_SHA,
                runtime_profile="unsupported",
                release_channel="VALIDATION",
                catalog=ReadOnlyPackCatalog((PackCatalogEntry(manifest),)),
            )

    def test_version_resolver_rejects_floating_dependency(self) -> None:
        payload = self.payload()
        payload["role"]["upstream_packs"] = ["dependency"]
        manifest = self.manifest(payload)
        catalog = ReadOnlyPackCatalog(
            (PackCatalogEntry(manifest, (PackDependency("dependency", "latest"),)),)
        )
        with self.assertRaises(ValueError):
            CapabilityPackVersionResolver().resolve(
                pack_id=str(manifest.identity.pack_id),
                pack_version=str(manifest.identity.version),
                protocol_version=str(manifest.schema_version),
                novel_forge_version="6.0.0",
                release_sha=FIXTURE_RELEASE_SHA,
                runtime_profile="validation",
                release_channel="VALIDATION",
                catalog=catalog,
            )

    def test_pack_identity_with_different_dependencies_is_rejected(self) -> None:
        manifest = self.manifest()
        with self.assertRaisesRegex(ValueError, "different manifest or dependencies"):
            ReadOnlyPackCatalog(
                (
                    PackCatalogEntry(manifest),
                    PackCatalogEntry(
                        manifest,
                        (PackDependency("governed-upstream", "1.0.0"),),
                    ),
                )
            )

    def test_exact_reference_version_parser_supports_governed_suffixes(self) -> None:
        self.assertEqual(exact_ref_version("authority-event.v1"), "v1")
        self.assertEqual(exact_ref_version("policy-name-v1"), "v1")
        self.assertEqual(exact_ref_version("schema:chapter-plan:1.2.3"), "1.2.3")

    def test_floating_reference_aliases_are_rejected(self) -> None:
        for alias in ("latest", "stable", "main", "HEAD", "nightly"):
            with (
                self.subTest(alias=alias),
                self.assertRaisesRegex(ValueError, "floating"),
            ):
                exact_ref_version(f"schema:chapter-plan:{alias}")

    def test_lifecycle_release_conflict_is_structured(self) -> None:
        payload = self.payload()
        payload["governance"]["release_channel"] = "PRODUCTION"
        report = validate_capability_pack(self.manifest(payload))
        self.assertIn(
            "CAPABILITY_PACK_LIFECYCLE_CONFLICT",
            {item.code for item in report.errors},
        )

    def test_enabled_empty_database_allowlist_is_rejected(self) -> None:
        payload = self.payload()
        payload["tool_permissions"]["database"]["read_allowed"] = True
        report = validate_capability_pack(self.manifest(payload))
        self.assertIn(
            "CAPABILITY_PACK_PERMISSION_ALLOWLIST_EMPTY",
            {item.code for item in report.errors},
        )

    def test_loader_rejects_non_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            path.write_bytes(b"{\xff}")
            with self.assertRaisesRegex(ValueError, "CAPABILITY_PACK_JSON_INVALID"):
                load_capability_pack(path)

    def test_loader_rejects_non_finite_float(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CAPABILITY_PACK_JSON_INVALID"):
                load_capability_pack(path)

    def test_version_resolver_rejects_dependency_cycle(self) -> None:
        payload = self.payload()
        payload["role"]["upstream_packs"] = [payload["identity"]["pack_id"]]
        manifest = self.manifest(payload)
        catalog = ReadOnlyPackCatalog(
            (
                PackCatalogEntry(
                    manifest,
                    (
                        PackDependency(
                            str(manifest.identity.pack_id),
                            str(manifest.identity.version),
                        ),
                    ),
                ),
            )
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            CapabilityPackVersionResolver().resolve(
                pack_id=str(manifest.identity.pack_id),
                pack_version=str(manifest.identity.version),
                protocol_version=str(manifest.schema_version),
                novel_forge_version="6.0.0",
                release_sha=FIXTURE_RELEASE_SHA,
                runtime_profile="validation",
                release_channel="VALIDATION",
                catalog=catalog,
            )

    def test_version_resolver_rejects_multiple_versions_of_one_pack(self) -> None:
        root_payload = self.payload()
        root_payload["role"]["upstream_packs"] = ["chapter.dependency"]
        root = self.manifest(root_payload)

        dependency_payload = self.payload()
        dependency_payload["identity"]["pack_id"] = "chapter.dependency"
        dependency_payload["identity"]["name"] = "Chapter Dependency"
        dependency_payload["identity"]["version"] = "1.0.0"
        dependency_payload["role"]["upstream_packs"] = []
        dependency_v1 = self.manifest(dependency_payload)
        dependency_payload_v2 = copy.deepcopy(dependency_payload)
        dependency_payload_v2["identity"]["version"] = "2.0.0"
        dependency_v2 = self.manifest(dependency_payload_v2)
        catalog = ReadOnlyPackCatalog(
            (
                PackCatalogEntry(
                    root,
                    (
                        PackDependency("chapter.dependency", "1.0.0"),
                        PackDependency("chapter.dependency", "2.0.0"),
                    ),
                ),
                PackCatalogEntry(dependency_v1),
                PackCatalogEntry(dependency_v2),
            )
        )
        with self.assertRaisesRegex(ValueError, "multiple versions"):
            CapabilityPackVersionResolver().resolve(
                pack_id=str(root.identity.pack_id),
                pack_version=str(root.identity.version),
                protocol_version=str(root.schema_version),
                novel_forge_version="6.0.0",
                release_sha=FIXTURE_RELEASE_SHA,
                runtime_profile="validation",
                release_channel="VALIDATION",
                catalog=catalog,
            )

    def test_unbounded_source_eligibility_is_rejected(self) -> None:
        payload = self.payload()
        payload["assets"]["source_policy"]["allowed_eligibility"] = ["ANY"]
        report = validate_capability_pack(self.manifest(payload))
        self.assertIn(
            "CAPABILITY_PACK_SOURCE_POLICY_INVALID",
            {item.code for item in report.errors},
        )

    def test_blocking_originality_gate_cannot_be_removed(self) -> None:
        payload = self.payload()
        payload["evaluation"]["required_gates"] = [
            gate
            for gate in payload["evaluation"]["required_gates"]
            if gate["judge_capability_id"] != "quality.originality.judge"
        ]
        report = validate_capability_pack(self.manifest(payload))
        self.assertIn(
            "CAPABILITY_PACK_SOURCE_ISOLATION_GATE_REQUIRED",
            {item.code for item in report.errors},
        )


if __name__ == "__main__":
    unittest.main()
