from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import (
    build_manifest,
    operation_catalog,
    validate_head_binding,
)
from novel_forge.tools.authority_architecture_contract import (
    load_contract,
    validate_contract,
)
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)


class AuthorityCoverageBaselineTests(unittest.TestCase):
    def test_stable_contract_accepts_current_implementation(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = load_contract(root)
        current = build_manifest(root, generated_at="2026-08-04T00:00:00+00:00")
        validate_head_binding(current, root)
        report = validate_contract(contract, current, root)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(
            current["implementation_tree_identity"],
            build_implementation_tree_identity(root),
        )
        self.assertNotIn("implementation_tree_sha", contract)
        self.assertNotIn("commit_sha", contract)
        self.assertNotIn("generated_at", contract)

    def test_contract_and_dynamic_run_evidence_have_distinct_semantics(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = load_contract(root)
        current = build_manifest(root, generated_at="2026-08-04T00:00:00+00:00")
        self.assertEqual(
            contract["schema_version"],
            "postgresql-authority-architecture-contract.v1",
        )
        self.assertEqual(current["schema_version"], "postgresql-authority-run-evidence.v1")
        self.assertEqual(current["evidence_class"], "dynamic_run_evidence")
        self.assertEqual(current["architecture_contract_id"], contract["contract_id"])
        self.assertEqual(
            current["tested_repository_sha"], current["repository_head_at_generation"]
        )

    def test_ci_persists_every_run_evidence_class_outside_the_source_tree(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = load_contract(root)
        workflow = (root / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")
        artifact_tokens = {
            "coverage_manifest": "postgresql-authority-coverage-${{ github.sha }}",
            "test_result": "test-result-${{ github.sha }}",
            "migration_result": "migration-${{ github.sha }}",
            "compose_evidence": "authority-compose-${{ github.sha }}",
            "query_plan_evidence": "query-plan-${{ github.sha }}",
            "worker_fleet_evidence": "worker-fleet-summary-${{ github.sha }}",
            "docker_image_digest": "docker-image-digest-${{ github.sha }}",
            "environment_metadata": "environment-metadata-${{ github.sha }}",
        }
        required = contract["run_evidence_contract"]["required_artifact_classes"]
        self.assertEqual(set(required), set(artifact_tokens))
        for evidence_class in required:
            self.assertIn(artifact_tokens[evidence_class], workflow)
        self.assertIn("release-qualification-${{ github.sha }}", workflow)

    def test_side_effect_coverage_is_fully_owned_and_mapped(self) -> None:
        root = Path(__file__).resolve().parents[2]
        current = build_manifest(root, generated_at="2026-08-04T00:00:00+00:00")
        side_effects = [item for item in current["findings"] if item["side_effect"]]
        definitions = {item["name"] for item in operation_catalog(current["findings"])}
        self.assertFalse([item for item in side_effects if not item["qualified_symbol"]])
        self.assertFalse([item for item in side_effects if not item["legacy_action"]])
        self.assertFalse([item for item in side_effects if not item["target_operation_definition"]])
        self.assertFalse(
            [item for item in side_effects if item["target_operation_definition"] not in definitions]
        )
        self.assertFalse(
            [
                item
                for item in current["findings"]
                if item["current_authority"] == "localstorage"
                and not item["path"].startswith("tests/")
                and item["legacy_action"] == "retain"
            ]
        )

    def test_external_effect_population_has_no_known_receiver_false_positives(self) -> None:
        root = Path(__file__).resolve().parents[2]
        current = build_manifest(root, generated_at="2026-08-04T00:00:00+00:00")
        effects = [item for item in current["findings"] if item["usage_type"] == "external_effect"]
        forbidden = ("fastapi.", ".get", "mock", "fixture", "local_rules")
        self.assertFalse(
            [item for item in effects if any(token in item["called_symbol"].lower() for token in forbidden)]
        )
        self.assertLessEqual(current["quality_metrics"]["false_positive_sample_rate"], 0.05)
