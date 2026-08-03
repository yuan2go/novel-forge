from __future__ import annotations

import unittest

from novel_forge.storage.migrations import MIGRATIONS


class ProjectAuthorityMigrationTests(unittest.TestCase):
    def test_project_workspace_and_import_ledger_are_constrained(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id
            == "20260801_0043_project_workspace_and_legacy_migration_authority"
        )
        sql = "\n".join(migration.upgrade_statements)

        for table in (
            "authority_project",
            "authority_workspace",
            "authority_project_binding",
            "authority_legacy_migration_item",
        ):
            self.assertIn(f"CREATE TABLE {table}", sql)
        self.assertIn("authority_project_binding_one_active_idx", sql)
        self.assertIn("UNIQUE(migration_run_id, stable_business_key, source_hash)", sql)
        self.assertIn("REFERENCES authority_asset_version(asset_version_id)", sql)
        self.assertIn("REFERENCES authority_operation(operation_id)", sql)
        self.assertIn("'QUARANTINED'", sql)
        self.assertIn("'SKIPPED_DUPLICATE'", sql)
        self.assertNotIn("DROP TABLE", sql.upper())

    def test_binding_decision_has_an_asset_version_foreign_key(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0044_project_binding_authority"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertIn("binding_asset_version_id TEXT NOT NULL UNIQUE", sql)
        self.assertIn("REFERENCES authority_asset_version(asset_version_id)", sql)
        self.assertIn("authority_project_binding_asset_version_fk_idx", sql)
        self.assertNotIn("DROP TABLE", sql.upper())

    def test_task_recovery_command_is_an_audit_ledger_not_a_task_state(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0045_task_recovery_authority"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertIn("CREATE TABLE authority_outbox_recovery_command", sql)
        self.assertIn("REFERENCES outbox_event(outbox_id)", sql)
        self.assertIn("UNIQUE(project_id, outbox_id, idempotency_key)", sql)
        self.assertIn("replacement_outbox_id TEXT NOT NULL UNIQUE", sql)
        self.assertIn("REQUEUE_NEW_GENERATION", sql)
        self.assertNotIn("create table task", sql.lower())

    def test_source_document_projection_reuses_asset_blob_and_operation_authority(
        self,
    ) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0046_source_document_authority"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertIn("CREATE TABLE authority_source_document", sql)
        self.assertIn("REFERENCES authority_asset(asset_id)", sql)
        self.assertIn("REFERENCES authority_asset_version(asset_version_id)", sql)
        self.assertIn("REFERENCES authority_blob(blob_id)", sql)
        self.assertIn("REFERENCES authority_operation(operation_id)", sql)
        self.assertIn("UNIQUE(project_id, source_content_hash)", sql)
        self.assertNotIn("raw_text", sql)
        self.assertNotIn("CREATE TABLE source_operation", sql)

    def test_candidate_lifecycle_is_database_constrained(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0047_candidate_asset_lifecycle"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertIn("'CANDIDATE'", sql)
        self.assertIn("authority_asset_version_lifecycle_check", sql)
        self.assertNotIn("CREATE TABLE authority_asset_version", sql)

    def test_source_transform_reuses_asset_versions_and_stores_no_raw_text(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0048_source_transform_authority"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertIn("CREATE TABLE authority_source_transform", sql)
        self.assertIn("CREATE TABLE authority_source_chunk", sql)
        self.assertIn("REFERENCES authority_asset_version(asset_version_id)", sql)
        self.assertIn("REFERENCES authority_blob(blob_id)", sql)
        self.assertIn("authority_source_transform_one_active_idx", sql)
        self.assertNotIn("raw_text", sql)
        self.assertNotIn("clean_text", sql)

        index_migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0049_source_transform_fk_indexes"
        )
        index_sql = "\n".join(index_migration.upgrade_statements)
        self.assertIn("authority_source_transform_workspace_idx", index_sql)
        self.assertIn("authority_source_chunk_project_idx", index_sql)
        self.assertIn("authority_source_chunk_workspace_idx", index_sql)

    def test_mkaos_authority_separates_candidate_decision_card_and_pack(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260801_0050_mkaos_authority"
        )
        sql = "\n".join(migration.upgrade_statements)

        for table in (
            "authority_mkaos_knowledge_candidate",
            "authority_mkaos_evidence_span",
            "authority_mkaos_governance_decision",
            "authority_mkaos_knowledge_card",
            "authority_mkaos_knowledge_pack",
            "authority_mkaos_knowledge_pack_item",
        ):
            self.assertIn(f"CREATE TABLE {table}", sql)
        self.assertIn("REFERENCES authority_asset_version(asset_version_id)", sql)
        self.assertIn("REFERENCES authority_operation(operation_id)", sql)
        self.assertIn("authority_mkaos_pack_one_active_target_idx", sql)
        self.assertNotIn("raw_text", sql)
        self.assertNotIn("clean_text", sql)
        self.assertNotIn("CREATE TABLE mkaos_operation", sql)


if __name__ == "__main__":
    unittest.main()
