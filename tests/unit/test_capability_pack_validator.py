from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.modules.capability_packs import (
    CapabilityPackLoadError,
    load_capability_pack,
    load_capability_pack_payload,
    validate_capability_pack,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.scheduler import _admission_dependencies


ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "config/capability_packs/chapter_generation_pack.json"


def _representative_json_paths(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            path = (*prefix, key)
            yield path
            yield from _representative_json_paths(item, path)
    elif isinstance(value, list) and value:
        path = (*prefix, 0)
        yield path
        yield from _representative_json_paths(value[0], path)


def _replace_json_path(payload, path, replacement) -> None:
    target = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = replacement


class CapabilityPackValidatorTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return json.loads(PACK_PATH.read_text(encoding="utf-8"))

    def _report(self, payload: dict[str, object]):
        return validate_capability_pack(load_capability_pack_payload(payload))

    def _codes(self, payload: dict[str, object]) -> set[str]:
        return {issue.code for issue in self._report(payload).errors}

    def test_valid_chapter_generation_pack_passes(self) -> None:
        manifest = load_capability_pack(PACK_PATH)
        report = validate_capability_pack(manifest)

        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.pack_id, "chapter_generation_pack")
        self.assertEqual(report.version, "2.1.1")
        node_ids = {node.node_id for node in manifest.workflow_template.nodes}
        self.assertEqual(len(node_ids), 22)
        self.assertTrue(
            {"execution_intent", "memo", "retrieval", "best_candidate"}.issubset(
                node_ids
            )
        )
        self.assertTrue(report.manifest_hash.startswith("sha256:"))

    def test_fixture_maps_current_chapter_authority_nodes(self) -> None:
        manifest = load_capability_pack(PACK_PATH)
        nodes = manifest.workflow_template.nodes

        self.assertEqual(
            tuple(node.node_id for node in nodes),
            tuple(node.value for node in ChapterNode),
        )
        self.assertEqual(
            tuple(node.operation_name for node in nodes),
            tuple(node.definition_name for node in ChapterNode),
        )
        self.assertEqual(
            tuple(node.handler_key for node in nodes),
            tuple(node.handler_key for node in ChapterNode),
        )
        self.assertEqual(
            tuple(node.output_asset_types[0] for node in nodes),
            tuple(node.asset_type for node in ChapterNode),
        )
        self.assertEqual(
            tuple(node.depends_on for node in nodes),
            tuple(
                tuple(dependency.value for dependency in _admission_dependencies(node))
                for node in ChapterNode
            ),
        )

    def test_validator_collects_multiple_configuration_errors(self) -> None:
        payload = self._payload()
        payload["identity"]["pack_id"] = "Invalid Pack"
        payload["tool_permissions"]["default"] = "ALLOW"
        payload["prompt_binding"]["template_hash"] = "bad"

        codes = self._codes(payload)

        self.assertTrue(
            {
                "CAPABILITY_PACK_IDENTITY_INVALID",
                "CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN",
                "CAPABILITY_PACK_HASH_INVALID",
            }.issubset(codes)
        )

    def test_json_type_fuzz_never_escapes_structured_validator(self) -> None:
        source = self._payload()
        for path in _representative_json_paths(source):
            for replacement in ({}, [], 1, True, None):
                with self.subTest(path=path, replacement=replacement):
                    payload = copy.deepcopy(source)
                    _replace_json_path(payload, path, replacement)

                    report = self._report(payload)
                    self.assertIsInstance(report.errors, tuple)

    def test_extension_outside_allowed_namespace_fails(self) -> None:
        payload = self._payload()
        payload["ext"]["custom"] = {}
        self.assertIn("CAPABILITY_PACK_EXTENSION_INVALID", self._codes(payload))

    def test_protocol_collection_with_wrong_type_fails_without_repair(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"] = {"node_id": "not-an-array"}

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_non_string_capability_reference_fails_closed(self) -> None:
        payload = self._payload()
        payload["compatibility"]["required_capabilities"] = [123]

        self.assertIn("CAPABILITY_PACK_CAPABILITY_UNKNOWN", self._codes(payload))

    def test_non_string_context_asset_type_fails_closed(self) -> None:
        payload = self._payload()
        payload["context_sources"]["allowed_asset_types"] = [123]

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_unknown_skill_binding_mode_fails_closed(self) -> None:
        payload = self._payload()
        payload["skill_binding"]["mode"] = "SURPRISE"

        self.assertIn("CAPABILITY_PACK_SKILL_POLICY_INVALID", self._codes(payload))

    def test_unknown_tool_risk_class_fails_closed(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["risk_class"] = "CRITCAL"

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_lowercase_tool_risk_class_is_not_repaired(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["risk_class"] = "high"

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_unknown_tool_permission_fails_closed(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["permission"] = "SUPERUSER"

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_tool_operations_require_strings(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["allowed_operations"] = [123]

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_parent_traversal_file_root_fails(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["files"]["allowed_roots"] = ["../secret"]

        self.assertIn("CAPABILITY_PACK_FILE_ROOT_INVALID", self._codes(payload))

    def test_production_pack_relative_file_root_fails(self) -> None:
        payload = self._payload()
        payload["identity"]["lifecycle"] = "PRODUCTION"
        payload["tool_permissions"]["files"]["allowed_roots"] = ["workspace"]

        self.assertIn("CAPABILITY_PACK_FILE_ROOT_INVALID", self._codes(payload))

    def test_inline_secret_fails(self) -> None:
        payload = self._payload()
        payload["ext"]["vendor"]["api_key"] = "not-allowed"

        self.assertIn("CAPABILITY_PACK_INLINE_SECRET_FORBIDDEN", self._codes(payload))

    def test_volatile_manifest_identity_inputs_fail(self) -> None:
        values = (
            ("generated_at", "2026-08-05T12:00:00Z"),
            ("run_result", {"status": "PASS"}),
            ("generated_uuid", "123e4567-e89b-42d3-a456-426614174000"),
            ("workspace", "/Users/example/projects/novel-forge"),
        )
        for key, value in values:
            with self.subTest(key=key):
                payload = self._payload()
                payload["ext"]["experiments"][key] = value
                self.assertIn(
                    "CAPABILITY_PACK_MANIFEST_IDENTITY_VOLATILE",
                    self._codes(payload),
                )

    def test_unknown_nested_core_field_fails_closed(self) -> None:
        payload = self._payload()
        payload["runtime_contract"]["execution"]["silent_fallback"] = True

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_missing_deep_required_field_is_reported(self) -> None:
        payload = self._payload()
        del payload["tool_permissions"]["database"]["read_allowed"]

        self.assertIn("CAPABILITY_PACK_REQUIRED_FIELD_MISSING", self._codes(payload))

    def test_all_referenced_capabilities_must_be_declared(self) -> None:
        payload = self._payload()
        payload["compatibility"]["required_capabilities"].remove("prose.chapter.draft")

        self.assertIn(
            "CAPABILITY_PACK_CAPABILITY_DECLARATION_MISSING",
            self._codes(payload),
        )

    def test_compatibility_version_range_fails_closed(self) -> None:
        payload = self._payload()
        payload["compatibility"]["novel_forge_min_version"] = "7.0.0"
        payload["compatibility"]["novel_forge_max_version"] = "6.0.0"

        self.assertIn("CAPABILITY_PACK_COMPATIBILITY_INVALID", self._codes(payload))

    def test_pack_cannot_declare_itself_incompatible(self) -> None:
        payload = self._payload()
        payload["compatibility"]["incompatible_packs"] = ["chapter_generation_pack"]

        self.assertIn("CAPABILITY_PACK_COMPATIBILITY_INVALID", self._codes(payload))

    def test_skill_dependency_cycle_fails(self) -> None:
        payload = self._payload()
        payload["skill_binding"]["skills"][0]["depends_on"] = ["canon-continuity-graph"]

        self.assertIn("CAPABILITY_PACK_SKILL_DEPENDENCY_CYCLE", self._codes(payload))

    def test_duplicate_tool_ref_fails(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"].append(
            copy.deepcopy(payload["tool_permissions"]["tools"][0])
        )

        self.assertIn("CAPABILITY_PACK_TOOL_DUPLICATE", self._codes(payload))

    def test_tool_operation_must_reference_workflow_node(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["allowed_operations"].append(
            "missing-node"
        )

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_database_table_allow_and_forbid_overlap_fails(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["database"]["allowed_tables"] = ["legacy_assets"]

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_model_tool_requires_external_model_permission(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["external_models"]["allowed"] = False

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_external_effect_tool_requires_runtime_permission(self) -> None:
        payload = self._payload()
        payload["runtime_contract"]["execution"]["external_effects_allowed"] = False

        self.assertIn("CAPABILITY_PACK_TOOL_POLICY_INVALID", self._codes(payload))

    def test_duplicate_evaluation_gate_fails(self) -> None:
        payload = self._payload()
        payload["evaluation"]["required_gates"].append(
            copy.deepcopy(payload["evaluation"]["required_gates"][0])
        )

        self.assertIn("CAPABILITY_PACK_EVALUATION_GATE_DUPLICATE", self._codes(payload))

    def test_evaluation_failure_classes_cannot_overlap(self) -> None:
        payload = self._payload()
        payload["evaluation"]["failure_policy"]["acceptable_failures"] = [
            "PROVIDER_TIMEOUT"
        ]

        self.assertIn("CAPABILITY_PACK_EVALUATION_INVALID", self._codes(payload))

    def test_invalid_governance_canary_percentage_fails(self) -> None:
        payload = self._payload()
        payload["governance"]["rollout"]["canary_percent"] = 101

        self.assertIn("CAPABILITY_PACK_GOVERNANCE_INVALID", self._codes(payload))

    def test_required_migration_needs_governed_policy(self) -> None:
        payload = self._payload()
        payload["governance"]["versioning"]["migration_required"] = True
        payload["governance"]["versioning"]["migration_policy_ref"] = None

        self.assertIn("CAPABILITY_PACK_GOVERNANCE_INVALID", self._codes(payload))

    def test_nested_extension_cannot_shadow_core_section(self) -> None:
        payload = self._payload()
        payload["ext"]["ui"]["panel"] = {"runtime_contract": {}}

        self.assertIn("CAPABILITY_PACK_EXTENSION_INVALID", self._codes(payload))

    def test_generation_audit_contract_cannot_disable_required_evidence(self) -> None:
        payload = self._payload()
        payload["audit"]["record_pack_manifest_hash"] = False

        self.assertIn("CAPABILITY_PACK_AUDIT_INVALID", self._codes(payload))

    def test_context_required_version_ref_rejects_latest_alias(self) -> None:
        payload = self._payload()
        payload["context_sources"]["required_version_refs"] = ["knowledge-pack:latest"]

        self.assertIn("CAPABILITY_PACK_CONTEXT_POLICY_INVALID", self._codes(payload))

    def test_duplicate_rule_asset_ref_fails(self) -> None:
        payload = self._payload()
        payload["assets"]["rules"].append(copy.deepcopy(payload["assets"]["rules"][0]))

        self.assertIn("CAPABILITY_PACK_ASSET_POLICY_INVALID", self._codes(payload))

    def test_manifest_hash_is_deterministic(self) -> None:
        payload = self._payload()
        reordered = dict(reversed(tuple(payload.items())))

        first = load_capability_pack_payload(payload)
        second = load_capability_pack_payload(reordered)

        self.assertEqual(first.manifest_hash, second.manifest_hash)

    def test_loaded_manifest_nested_state_is_immutable(self) -> None:
        manifest = load_capability_pack(PACK_PATH)
        original_hash = manifest.manifest_hash

        with self.assertRaises((AttributeError, TypeError)):
            manifest.tool_permissions.files["allowed_roots"] += ("../escape",)

        self.assertEqual(manifest.manifest_hash, original_hash)

    def test_unsupported_schema_version_fails(self) -> None:
        payload = self._payload()
        payload["schema_version"] = "novelos.capability_pack.v2"
        self.assertIn(
            "CAPABILITY_PACK_SCHEMA_VERSION_UNSUPPORTED", self._codes(payload)
        )

    def test_invalid_pack_id_fails(self) -> None:
        payload = self._payload()
        payload["identity"]["pack_id"] = "Invalid Pack"
        self.assertIn("CAPABILITY_PACK_IDENTITY_INVALID", self._codes(payload))

    def test_invalid_semver_fails(self) -> None:
        payload = self._payload()
        payload["identity"]["version"] = "v1"
        self.assertIn("CAPABILITY_PACK_IDENTITY_INVALID", self._codes(payload))

    def test_object_enum_values_return_structured_errors(self) -> None:
        cases = (
            (("identity", "status"), "CAPABILITY_PACK_IDENTITY_INVALID"),
            (("identity", "lifecycle"), "CAPABILITY_PACK_IDENTITY_INVALID"),
            (("role", "role_type"), "CAPABILITY_PACK_ROLE_INVALID"),
            (("skill_binding", "mode"), "CAPABILITY_PACK_SKILL_POLICY_INVALID"),
            (
                ("skill_binding", "skills", 0, "drift_policy"),
                "CAPABILITY_PACK_SKILL_POLICY_INVALID",
            ),
            (
                ("context_sources", "source_isolation"),
                "CAPABILITY_PACK_CONTEXT_POLICY_INVALID",
            ),
            (
                ("tool_permissions", "tools", 0, "permission"),
                "CAPABILITY_PACK_TOOL_POLICY_INVALID",
            ),
            (("governance", "release_channel"), "CAPABILITY_PACK_GOVERNANCE_INVALID"),
        )
        for path, expected_code in cases:
            with self.subTest(path=path):
                payload = self._payload()
                target = payload
                for segment in path[:-1]:
                    target = target[segment]
                target[path[-1]] = {}
                self.assertIn(expected_code, self._codes(payload))

    def test_unknown_capability_type_applies_generation_guards(self) -> None:
        payload = self._payload()
        payload["identity"]["capability_type"] = "custom"
        payload["context_sources"]["forbidden_asset_types"] = []
        payload["context_sources"]["allowed_asset_types"].append("raw_source_document")
        payload["assets"]["source_policy"]["requires_lineage"] = False
        payload["runtime_contract"]["execution"]["binds_authority_operation"] = False

        codes = self._codes(payload)
        self.assertTrue(
            {
                "CAPABILITY_PACK_IDENTITY_INVALID",
                "CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN",
                "CAPABILITY_PACK_SOURCE_LINEAGE_REQUIRED",
                "CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED",
            }.issubset(codes)
        )

    def test_unknown_capability_fails(self) -> None:
        payload = self._payload()
        payload["compatibility"]["required_capabilities"].append(
            "unknown.chapter.capability"
        )
        self.assertIn("CAPABILITY_PACK_CAPABILITY_UNKNOWN", self._codes(payload))

    def test_invalid_hash_fails(self) -> None:
        payload = self._payload()
        payload["skill_binding"]["skills"][0]["content_hash"] = "sha256:ABC"
        self.assertIn("CAPABILITY_PACK_HASH_INVALID", self._codes(payload))

    def test_duplicate_skill_fails(self) -> None:
        payload = self._payload()
        payload["skill_binding"]["skills"].append(
            copy.deepcopy(payload["skill_binding"]["skills"][0])
        )
        self.assertIn("CAPABILITY_PACK_SKILL_DUPLICATE", self._codes(payload))

    def test_unknown_skill_dependency_fails(self) -> None:
        payload = self._payload()
        payload["skill_binding"]["skills"][0]["depends_on"] = ["missing-skill"]
        self.assertIn("CAPABILITY_PACK_SKILL_DEPENDENCY_UNKNOWN", self._codes(payload))

    def test_non_string_skill_dependency_fails_without_crashing(self) -> None:
        payload = self._payload()
        payload["skill_binding"]["skills"][0]["depends_on"] = [{}]

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_duplicate_workflow_node_fails(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"].append(
            copy.deepcopy(payload["workflow_template"]["nodes"][0])
        )
        self.assertIn("CAPABILITY_PACK_WORKFLOW_NODE_DUPLICATE", self._codes(payload))

    def test_workflow_unknown_dependency_fails(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"][0]["depends_on"] = ["missing"]
        self.assertIn(
            "CAPABILITY_PACK_WORKFLOW_DEPENDENCY_UNKNOWN", self._codes(payload)
        )

    def test_workflow_cycle_fails(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"][0]["depends_on"] = ["final_release_gate"]
        self.assertIn("CAPABILITY_PACK_WORKFLOW_CYCLE", self._codes(payload))

    def test_chapter_workflow_unknown_operation_binding_fails(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"][0]["operation_name"] = "chapter.unknown"

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_workflow_unknown_operation_definition_fails(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"][0]["operation_definition_ref"] = (
            "chapter.unknown@1.0.0"
        )

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_pack_id_rename_cannot_bypass_governed_workflow_contract(self) -> None:
        payload = self._payload()
        payload["identity"]["pack_id"] = "alternate_generation_pack"
        node = payload["workflow_template"]["nodes"][0]
        node["operation_name"] = "alternate.plan.generate"
        node["operation_definition_ref"] = "alternate.plan.generate@1.0.0"
        node["handler_key"] = "novel_forge.alternate.plan"

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_generic_operation_ref_must_match_operation_name(self) -> None:
        payload = self._payload()
        payload["identity"]["pack_id"] = "alternate_generation_pack"
        payload["workflow_template"]["nodes"][0]["operation_definition_ref"] = (
            "alternate.plan.generate@1.0.0"
        )

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_workflow_timeout_must_match_capability_definition(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"][0]["timeout_policy_ref"] = (
            "timeout:unbound:v1"
        )

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_completion_node_must_be_a_real_terminal(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["completion"]["required_terminal_nodes"] = ["plan"]

        self.assertIn("CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN", self._codes(payload))

    def test_completion_output_must_be_produced(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["completion"][
            "required_output_asset_types"
        ].append("missing_asset")

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_required_node_approval_needs_policy(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["nodes"][-1]["approval"]["required"] = True
        payload["workflow_template"]["nodes"][-1]["approval"]["policy_ref"] = None

        self.assertIn("CAPABILITY_PACK_WORKFLOW_BINDING_INVALID", self._codes(payload))

    def test_completion_terminal_nodes_must_be_an_array(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["completion"]["required_terminal_nodes"] = (
            "final_release_gate"
        )

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_unknown_completion_terminal_node_fails(self) -> None:
        payload = self._payload()
        payload["workflow_template"]["completion"]["required_terminal_nodes"] = [
            "missing"
        ]
        self.assertIn("CAPABILITY_PACK_WORKFLOW_TERMINAL_UNKNOWN", self._codes(payload))

    def test_non_default_deny_tool_policy_fails(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["default"] = "ALLOW"
        self.assertIn(
            "CAPABILITY_PACK_TOOL_DEFAULT_ALLOW_FORBIDDEN", self._codes(payload)
        )

    def test_high_risk_tool_without_audit_fails(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["audit_required"] = False
        self.assertIn(
            "CAPABILITY_PACK_HIGH_RISK_TOOL_AUDIT_REQUIRED", self._codes(payload)
        )

    def test_critical_tool_without_approval_fails(self) -> None:
        payload = self._payload()
        payload["tool_permissions"]["tools"][0]["risk_class"] = "CRITICAL"
        payload["tool_permissions"]["tools"][0]["approval_required"] = False
        self.assertIn(
            "CAPABILITY_PACK_CRITICAL_TOOL_APPROVAL_REQUIRED", self._codes(payload)
        )

    def test_production_pack_with_raw_source_context_fails(self) -> None:
        payload = self._payload()
        payload["identity"]["lifecycle"] = "PRODUCTION"
        payload["context_sources"]["source_isolation"] = "RAW_ALLOWED_WITH_APPROVAL"
        payload["context_sources"]["forbidden_asset_types"] = []
        payload["context_sources"]["allowed_asset_types"].append("raw_source_document")
        self.assertIn(
            "CAPABILITY_PACK_RAW_SOURCE_PRODUCTION_FORBIDDEN", self._codes(payload)
        )

    def test_allowed_and_forbidden_asset_overlap_fails(self) -> None:
        payload = self._payload()
        payload["context_sources"]["allowed_asset_types"].append("raw_source_document")
        self.assertIn("CAPABILITY_PACK_CONTEXT_ASSET_OVERLAP", self._codes(payload))

    def test_unknown_judge_capability_fails(self) -> None:
        payload = self._payload()
        payload["evaluation"]["required_gates"][0]["judge_capability_id"] = (
            "unknown.quality.judge"
        )
        self.assertIn(
            "CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN", self._codes(payload)
        )

    def test_registered_non_judge_capability_cannot_be_an_evaluation_judge(
        self,
    ) -> None:
        payload = self._payload()
        payload["evaluation"]["required_gates"][0]["judge_capability_id"] = (
            "prose.chapter.draft"
        )

        self.assertIn(
            "CAPABILITY_PACK_EVALUATION_CAPABILITY_UNKNOWN", self._codes(payload)
        )

    def test_evaluation_gate_types_fail_closed(self) -> None:
        payload = self._payload()
        gate = payload["evaluation"]["required_gates"][0]
        gate["blocking"] = "yes"
        gate["required_evidence"] = [123]

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_prompt_contract_reference_must_be_a_string(self) -> None:
        payload = self._payload()
        payload["prompt_binding"]["input_schema_ref"] = None

        self.assertIn("CAPABILITY_PACK_PROTOCOL_INVALID", self._codes(payload))

    def test_runtime_contract_without_authority_binding_fails(self) -> None:
        payload = self._payload()
        payload["runtime_contract"]["execution"]["binds_authority_operation"] = False
        self.assertIn(
            "CAPABILITY_PACK_AUTHORITY_BINDING_REQUIRED", self._codes(payload)
        )

    def test_loader_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(CapabilityPackLoadError) as raised:
                load_capability_pack(path)
        self.assertEqual(raised.exception.issue.code, "CAPABILITY_PACK_JSON_INVALID")

    def test_loader_rejects_duplicate_json_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            path.write_text('{"identity": {}, "identity": {}}', encoding="utf-8")
            with self.assertRaises(CapabilityPackLoadError) as raised:
                load_capability_pack(path)

        self.assertEqual(
            raised.exception.issue.code, "CAPABILITY_PACK_JSON_DUPLICATE_KEY"
        )

    def test_loader_rejects_non_object_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(CapabilityPackLoadError) as raised:
                load_capability_pack(path)
        self.assertEqual(raised.exception.issue.code, "CAPABILITY_PACK_JSON_INVALID")

    def test_payload_loader_does_not_coerce_tuple_to_json_array(self) -> None:
        payload = self._payload()
        payload["compatibility"]["required_capabilities"] = ("prose.chapter.draft",)

        with self.assertRaises(CapabilityPackLoadError) as raised:
            load_capability_pack_payload(payload)

        self.assertEqual(raised.exception.issue.code, "CAPABILITY_PACK_JSON_INVALID")

    def test_payload_loader_does_not_coerce_non_string_object_key(self) -> None:
        payload = self._payload()
        payload["ext"]["ui"] = {1: "invalid"}

        with self.assertRaises(CapabilityPackLoadError) as raised:
            load_capability_pack_payload(payload)

        self.assertEqual(raised.exception.issue.code, "CAPABILITY_PACK_JSON_INVALID")

    def test_loader_rejects_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.json"
            path.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaises(CapabilityPackLoadError) as raised:
                load_capability_pack(path)
        self.assertEqual(raised.exception.issue.code, "CAPABILITY_PACK_FILE_TOO_LARGE")


if __name__ == "__main__":
    unittest.main()
