from __future__ import annotations

import unittest
from pathlib import Path

from novel_forge.tools.legacy_authority_migration_inventory import build_inventory


class LegacyAuthorityMigrationInventoryTests(unittest.TestCase):
    def test_inventory_is_machine_executable_and_evidence_backed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        inventory = build_inventory(root)

        self.assertEqual(
            inventory["schema_version"], "legacy-authority-migration-inventory.v1"
        )
        self.assertGreater(inventory["summary"]["inventory_rows"], 0)
        required = {
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
        }
        for item in inventory["items"]:
            with self.subTest(item["inventory_id"]):
                self.assertTrue(required.issubset(item))
                self.assertTrue(item["evidence"])
                self.assertTrue(item["target_operation_definition"])

    def test_artifact_hash_excludes_generation_timestamp(self) -> None:
        root = Path(__file__).resolve().parents[2]

        first = build_inventory(root)
        second = build_inventory(root)

        self.assertNotEqual(first["generated_at"], second["generated_at"])
        self.assertEqual(first["artifact_hash"], second["artifact_hash"])


if __name__ == "__main__":
    unittest.main()
