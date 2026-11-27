from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_forge.modules.legacy_migration.approval import (
    LegacyMigrationDecisionCommand,
)
from novel_forge.modules.legacy_migration.state_machine import MigrationDecision
from novel_forge.modules.legacy_migration.validation import (
    LegacyMigrationValidationCommand,
    MigrationValidationStatus,
    validator_descriptor,
)


class LegacyMigrationValidationTests(unittest.TestCase):
    def test_validator_descriptor_is_versioned_and_implementation_bound(self) -> None:
        descriptor = validator_descriptor(
            "novel_forge.legacy_migration.book_design_authority.v1",
            application_build_id="test-build",
            commit_sha="a" * 40,
        )
        self.assertEqual(descriptor.adapter_version, "1")
        self.assertTrue(descriptor.validator_name)
        self.assertRegex(descriptor.validator_version, r"^\d+\.\d+\.\d+$")
        self.assertTrue(descriptor.validator_implementation_hash.startswith("sha256:"))
        self.assertEqual(
            descriptor,
            validator_descriptor(
                "novel_forge.legacy_migration.book_design_authority.v1",
                application_build_id="test-build",
                commit_sha="a" * 40,
            ),
        )
        changed_build = validator_descriptor(
            "novel_forge.legacy_migration.book_design_authority.v1",
            application_build_id="test-build",
            commit_sha="b" * 40,
        )
        self.assertEqual(
            descriptor.validator_implementation_hash,
            changed_build.validator_implementation_hash,
        )
        original_read_bytes = Path.read_bytes
        with patch.object(
            Path,
            "read_bytes",
            lambda path: original_read_bytes(path)
            + (b"dependency-change" if path.name == "domain.py" else b""),
        ):
            changed_dependency = validator_descriptor(
                "novel_forge.legacy_migration.book_design_authority.v1",
                application_build_id="test-build",
                commit_sha="a" * 40,
            )
        self.assertNotEqual(
            descriptor.validator_implementation_hash,
            changed_dependency.validator_implementation_hash,
        )

    def test_validation_command_requires_authoritative_snapshot_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_hash"):
            LegacyMigrationValidationCommand(
                migration_run_id="run-1",
                migration_item_id="item-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_id="validator-1",
                expected_item_version=2,
                source_hash="not-a-hash",
                target_asset_version_id="version-1",
                idempotency_key="validate:item-1:2",
                trace_id="trace-1",
                correlation_id="correlation-1",
            )

    def test_approval_contract_accepts_validation_id_not_client_evidence(self) -> None:
        fields = inspect.signature(LegacyMigrationDecisionCommand).parameters
        self.assertIn("migration_validation_id", fields)
        self.assertNotIn("domain_validation_evidence", fields)
        with self.assertRaisesRegex(ValueError, "migration_validation_id"):
            LegacyMigrationDecisionCommand(
                migration_run_id="run-1",
                migration_item_id="item-1",
                project_id="project-1",
                workspace_id="workspace-1",
                actor_id="approver-1",
                decision=MigrationDecision.APPROVE,
                reason="validated",
                expected_item_version=3,
                source_hash="sha256:" + "a" * 64,
                target_asset_version_id="version-1",
                migration_validation_id="",
                idempotency_key="approve:item-1:3",
                trace_id="trace-1",
                correlation_id="correlation-1",
            )

    def test_validation_status_is_fail_closed(self) -> None:
        self.assertEqual(
            {item.value for item in MigrationValidationStatus},
            {"PASS", "FAIL", "STALE", "REVOKED"},
        )


if __name__ == "__main__":
    unittest.main()
