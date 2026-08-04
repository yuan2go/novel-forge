from __future__ import annotations

import unittest

from novel_forge.storage.migrations import MIGRATIONS


class AssetScopeMigrationTests(unittest.TestCase):
    def test_0052_is_explicit_forward_only_with_preflight_and_forward_fix(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260804_0052_asset_schema_and_scope_integrity"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertEqual(migration.strategy, "FORWARD_ONLY")
        self.assertTrue(migration.backup_required)
        self.assertTrue(migration.preflight_statements)
        self.assertTrue(migration.forward_fix)
        self.assertEqual(migration.downgrade_statements, ())
        self.assertIn("ALTER COLUMN schema_version DROP DEFAULT", sql)
        self.assertIn("authority_book_scope_guard", sql)
        self.assertIn("story_plan_binding_book_scope_fk", sql)

    def test_0054_indexes_every_scope_foreign_key_added_by_0052_and_0053(self) -> None:
        migration = next(
            item
            for item in MIGRATIONS
            if item.migration_id == "20260804_0054_scope_foreign_key_indexes"
        )
        sql = "\n".join(migration.upgrade_statements)

        self.assertEqual(migration.strategy, "FORWARD_ONLY")
        self.assertTrue(migration.forward_fix)
        for columns in (
            "authority_asset_activation(project_id, book_id)",
            "authority_asset_decision(project_id, book_id)",
            "authority_asset_dependency(project_id, book_id)",
            "authority_asset_evidence(project_id, book_id)",
            "authority_asset_supersession(project_id, book_id)",
            "authority_book_design_candidate(project_id, book_id, workspace_id)",
            "authority_d0_qualification_run(report_asset_version_id)",
            "authority_d0_qualification_run(workspace_id)",
        ):
            self.assertIn(columns, sql)


if __name__ == "__main__":
    unittest.main()
