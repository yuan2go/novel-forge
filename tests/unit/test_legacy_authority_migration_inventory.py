from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.tools.legacy_authority_migration_inventory import build_inventory


class LegacyAuthorityMigrationInventoryTests(unittest.TestCase):
    def test_inventory_is_machine_executable_and_evidence_backed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        inventory = build_inventory(root)

        self.assertEqual(
            inventory["schema_version"], "legacy-authority-migration-inventory.v3"
        )
        self.assertGreater(inventory["summary"]["inventory_rows"], 0)
        required = {
            "domain",
            "file",
            "symbol",
            "entrypoint",
            "read_or_write",
            "current_authority",
            "target_authority",
            "production_reachable",
            "migration_strategy",
            "status",
            "remaining_action",
            "business_domain",
            "current_entrypoints",
            "current_authority_source",
            "current_write_points",
            "current_read_points",
            "target_authority_asset_type",
            "target_operation_definition",
            "target_repository",
            "transaction_boundary",
            "idempotency_key",
            "recovery_strategy",
            "migration_method",
            "deletion_condition",
            "test_requirements",
            "evidence",
            "allowed_runtime",
            "reason",
            "owner",
            "removal_condition",
            "transitive_paths",
            "production_transitive_paths",
        }
        for item in inventory["items"]:
            with self.subTest(item["inventory_id"]):
                self.assertTrue(required.issubset(item))
                self.assertTrue(item["evidence"])
                self.assertTrue(item["target_operation_definition"])
                self.assertEqual(
                    item["production_reachable"],
                    bool(item["production_transitive_paths"]),
                )

        self.assertGreaterEqual(inventory["summary"]["reachability"]["entrypoint_count"], 15)

    def test_inventory_statuses_are_exhaustive_and_summary_is_reconciled(self) -> None:
        root = Path(__file__).resolve().parents[2]
        inventory = build_inventory(root)
        allowed = {
            "MIGRATED_NATIVE",
            "MIGRATED_READ_ONLY",
            "IMPORT_CANDIDATE_ONLY",
            "REBUILDABLE",
            "DEVELOPMENT_ONLY",
            "TEST_FIXTURE_ONLY",
            "EXPLICIT_COMPATIBILITY",
            "LEGACY_PRODUCTION_BLOCKER",
            "UNCLASSIFIED",
        }

        observed = {item["status"] for item in inventory["items"]}
        self.assertTrue(observed <= allowed)
        self.assertEqual(
            sum(inventory["summary"]["status_counts"].values()),
            inventory["summary"]["inventory_rows"],
        )
        self.assertEqual(
            inventory["summary"]["legacy_production_blocker_count"],
            inventory["summary"]["status_counts"]["LEGACY_PRODUCTION_BLOCKER"],
        )
        self.assertEqual(
            inventory["summary"]["unclassified_count"],
            inventory["summary"]["status_counts"]["UNCLASSIFIED"],
        )
        self.assertGreater(inventory["summary"]["web_excluded_count"], 0)
        self.assertTrue(
            all(
                not item["production_reachable"]
                for item in inventory["items"]
                if item["file"].startswith("web/")
            )
        )

    def test_artifact_hash_excludes_generation_timestamp(self) -> None:
        root = Path(__file__).resolve().parents[2]

        first = build_inventory(root)
        second = build_inventory(root)

        self.assertNotEqual(first["generated_at"], second["generated_at"])
        self.assertEqual(first["artifact_hash"], second["artifact_hash"])


if __name__ == "__main__":
    unittest.main()
