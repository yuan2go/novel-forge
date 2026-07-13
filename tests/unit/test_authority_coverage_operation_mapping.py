from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import build_manifest, operation_catalog


class AuthorityCoverageOperationMappingTests(unittest.TestCase):
    def test_asset_and_blob_protocol_definitions_have_typed_contracts(self) -> None:
        definitions = {item["name"]: item for item in operation_catalog([])}
        required = {
            "asset.create",
            "asset.version.create",
            "asset.version.activate",
            "asset.version.qualify",
            "blob.reserve",
            "blob.upload.request",
            "blob.upload.receipt",
            "blob.verify",
            "blob.fail",
            "blob.bind_to_asset_version",
            "blob.release",
            "blob.legal_hold.apply",
            "blob.legal_hold.release",
        }
        self.assertFalse(required - definitions.keys())
        for name in required:
            definition = definitions[name]
            self.assertEqual(definition["command_schema"]["$id"], f"{name}.command.v1")
            self.assertTrue(definition["handler_key"].endswith(name))
        self.assertEqual(
            definitions["blob.upload.request"]["external_capabilities"],
            ["object_store.put"],
        )

    def test_external_effect_definitions_have_typed_runtime_contracts(self) -> None:
        definitions = {item["name"]: item for item in operation_catalog([])}
        required = {
            "external_effect.plan",
            "external_effect.dispatch",
            "external_effect.receipt.accept",
            "external_effect.receipt.reject",
            "external_effect.mark_unknown",
            "external_effect.reconcile",
            "external_effect.compensate",
            "external_effect.cancel",
        }
        self.assertFalse(required - definitions.keys())
        for name in required:
            definition = definitions[name]
            self.assertEqual(definition["command_schema"]["$id"], f"{name}.command.v1")
            self.assertTrue(definition["command_schema"]["required"])
            self.assertEqual(definition["idempotency_scope"], "project:external_effect")
        self.assertEqual(definitions["external_effect.dispatch"]["execution_mode"], "external")
        self.assertEqual(
            definitions["external_effect.reconcile"]["external_capabilities"],
            ["provider.query_by_idempotency_key"],
        )

    def test_production_localstorage_and_side_effects_have_explicit_actions_and_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src/novel_forge/modules/publishing/service.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "\n".join(
                    [
                        "import requests",
                        "from novel_forge.storage.local import LocalStorage",
                        "",
                        "class PublishingService:",
                        "    def submit(self):",
                        "        storage = LocalStorage('.')",
                        "        storage.write_json('release.json', {})",
                        "        requests.post('https://publisher.test')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest = build_manifest(root, generated_at="2026-07-12T00:00:00+00:00")

        local_findings = [item for item in manifest["findings"] if item["current_authority"] == "localstorage"]
        self.assertTrue(local_findings)
        self.assertNotIn("retain", {item["legacy_action"] for item in local_findings})
        side_effects = [item for item in manifest["findings"] if item["side_effect"]]
        self.assertTrue(side_effects)
        for finding in side_effects:
            self.assertTrue(finding["target_operation_definition"])
            self.assertTrue(finding["target_handler"])
            self.assertIn(finding["legacy_action"], {"delete", "replace", "manual_review"})
            self.assertGreaterEqual(finding["mapping_confidence"], 0.5)
            self.assertTrue(finding["mapping_reason"])

    def test_catalog_has_versioned_business_specific_contracts(self) -> None:
        required = {
            "name",
            "definition_version",
            "family",
            "command_schema_version",
            "result_schema_version",
            "handler_key",
            "handler_contract_version",
            "execution_mode",
            "permissions",
            "approval_policy",
            "idempotency_scope",
            "concurrency_key_template",
            "retry_policy",
            "timeout_policy",
            "cancellation_policy",
            "compensation_policy",
            "irreversible_effect_policy",
            "external_capabilities",
            "completion_contract",
            "current_entrypoints",
            "migration_status",
        }
        catalog = operation_catalog()
        for definition in catalog:
            self.assertTrue(required.issubset(definition))
            self.assertNotEqual(definition["completion_contract"], "completion_contract.v1")
            self.assertNotEqual(definition["retry_policy"], "definition_default")
        publishing = next(item for item in catalog if item["name"] == "publishing.submit")
        self.assertEqual(publishing["execution_mode"], "external")
        self.assertIn("publisher.submit", publishing["external_capabilities"])
        self.assertTrue(publishing["approval_policy"]["required"])

    def test_generation_and_publishing_entrypoints_map_to_specific_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixtures = {
                "src/novel_forge/modules/topics/service.py": "from novel_forge.model_adapters import ModelAdapter\ndef develop_topic(model: ModelAdapter):\n model.generate('topic')\n",
                "src/novel_forge/modules/drafting/service.py": "from novel_forge.model_adapters import ModelAdapter\ndef generate_draft(model: ModelAdapter):\n model.generate('draft')\n",
                "src/novel_forge/modules/publishing/service.py": "import requests\ndef publish_release():\n requests.post('https://publisher.test')\n",
            }
            for relative, content in fixtures.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            manifest = build_manifest(root, generated_at="2026-07-12T00:00:00+00:00")

        targets = {
            item["qualified_symbol"]: item["target_operation_definition"]
            for item in manifest["findings"]
            if item["side_effect"]
        }
        self.assertEqual(
            targets["novel_forge.modules.topics.service.develop_topic"],
            "production.topic.generate",
        )
        self.assertEqual(
            targets["novel_forge.modules.drafting.service.generate_draft"],
            "production.draft.generate",
        )
        self.assertEqual(
            targets["novel_forge.modules.publishing.service.publish_release"],
            "publishing.submit",
        )


if __name__ == "__main__":
    unittest.main()
