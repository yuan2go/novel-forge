from __future__ import annotations

import json
import unittest
from pathlib import Path

from novel_forge.tools.authority_coverage_manifest import (
    build_manifest,
    operation_catalog,
    validate_head_binding,
)


class AuthorityCoverageBaselineTests(unittest.TestCase):
    def test_checked_in_baseline_matches_current_head_scan(self) -> None:
        root = Path(__file__).resolve().parents[2]
        baseline = json.loads((root / "docs/reports/postgresql-authority-coverage-baseline.json").read_text(encoding="utf-8"))
        current = build_manifest(root, generated_at=baseline["generated_at"])
        validate_head_binding(current, root)
        self.assertIn("commit_sha", baseline)
        self.assertEqual(
            baseline["binding_semantics"],
            "latest-commit-affecting-src/novel_forge-plus-working-tree-hash-v1",
        )
        self.assertIn("source_tree_sha", baseline)
        self.assertIn("scan_rule_version", baseline)
        self.assertEqual(current["source_tree_sha"], baseline["source_tree_sha"])
        self.assertEqual(current["coverage_hash"], baseline["coverage_hash"])

    def test_side_effect_coverage_is_fully_owned_and_mapped(self) -> None:
        root = Path(__file__).resolve().parents[2]
        baseline = json.loads((root / "docs/reports/postgresql-authority-coverage-baseline.json").read_text(encoding="utf-8"))
        side_effects = [item for item in baseline["findings"] if item["side_effect"]]
        definitions = {item["name"] for item in operation_catalog(baseline["findings"])}
        self.assertFalse([item for item in side_effects if not item["qualified_symbol"]])
        self.assertFalse([item for item in side_effects if not item["legacy_action"]])
        self.assertFalse([item for item in side_effects if not item["target_operation_definition"]])
        self.assertFalse(
            [item for item in side_effects if item["target_operation_definition"] not in definitions]
        )
        self.assertFalse(
            [
                item
                for item in baseline["findings"]
                if item["current_authority"] == "localstorage"
                and not item["path"].startswith("tests/")
                and item["legacy_action"] == "retain"
            ]
        )

    def test_external_effect_population_has_no_known_receiver_false_positives(self) -> None:
        root = Path(__file__).resolve().parents[2]
        baseline = json.loads((root / "docs/reports/postgresql-authority-coverage-baseline.json").read_text(encoding="utf-8"))
        effects = [item for item in baseline["findings"] if item["usage_type"] == "external_effect"]
        forbidden = ("fastapi.", ".get", "mock", "fixture", "local_rules")
        self.assertFalse(
            [item for item in effects if any(token in item["called_symbol"].lower() for token in forbidden)]
        )
        self.assertLessEqual(baseline["quality_metrics"]["false_positive_sample_rate"], 0.05)
