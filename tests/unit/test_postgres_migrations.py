from pathlib import Path
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, downgrade_migrations, downgrade_plan, pending_migrations, validate_migration_chain
from novel_forge.storage.migrations.versions import v20260909_0124_corpus_fk_indexes


class PostgresMigrationTests(unittest.TestCase):
    def test_migration_connection_respects_positive_dsn_timeout(self):
        from novel_forge.storage.migrations.runner import _connect
        try:
            import psycopg
        except ModuleNotFoundError:
            self.skipTest("requires optional psycopg")
        for dsn, timeout in (
            ("postgresql:///test", 5),
            ("postgresql:///test?connect_timeout=12", 12),
            ("dbname=test connect_timeout=3", 3),
        ):
            with self.subTest(dsn=dsn), patch.object(psycopg, "connect") as connect:
                _connect(dsn)
                connect.assert_called_once_with(dsn, connect_timeout=timeout)
        for value in ("0", "-1", "invalid", "", "1_0"):
            with self.subTest(value=value), patch.object(psycopg, "connect") as connect:
                with self.assertRaises(ValueError):
                    _connect("postgresql:///test?connect_timeout=" + value)
                connect.assert_not_called()

    def test_forward_opening_delete_fix_cannot_be_rolled_back_silently(self):
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (migration.migration_id, "2026-09-20T00:00:00Z")
            for migration in MIGRATIONS
        ]
        with patch("novel_forge.storage.migrations.runner._connect", return_value=connection):
            with self.assertRaisesRegex(
                ValueError, "missing downgrade statements for: .*20260920_0137_opening_delete_fence"
            ):
                downgrade_migrations(
                    "unused-test-connection",
                    target_revision="20260916_0136_provider_routing_policy",
                    execute=True,
                )
        statements = [call.args[0].strip() for call in cursor.execute.call_args_list]
        self.assertEqual(len(statements), 2)
        self.assertTrue(statements[0].startswith("CREATE TABLE IF NOT EXISTS nf_schema_migrations"))
        self.assertTrue(statements[1].startswith("SELECT migration_id, applied_at"))

    def test_corpus_foreign_key_repair_indexes_every_missing_key_shape(self):
        expected = {
            ("authority_corpus_source", ("workspace_id",)),
            (
                "authority_corpus_rights",
                ("project_id", "source_id", "previous_rights_id"),
            ),
            (
                "authority_corpus_snapshot",
                ("project_id", "source_id", "rights_id"),
            ),
            (
                "authority_corpus_snapshot",
                ("project_id", "source_id", "previous_snapshot_id"),
            ),
            (
                "authority_corpus_edition",
                ("project_id", "source_id", "snapshot_id"),
            ),
            (
                "authority_corpus_edition",
                ("project_id", "source_id", "book_source_id"),
            ),
            (
                "authority_corpus_membership",
                ("project_id", "edition_id", "purpose", "decision_id", "decision"),
            ),
            ("authority_corpus_retirement", ("project_id", "source_id")),
        }
        index_pattern = re.compile(
            r"^CREATE INDEX IF NOT EXISTS \S+ ON (\w+)\(([^)]+)\)"
        )
        actual = set()
        for statement in v20260909_0124_corpus_fk_indexes.UPGRADE_STATEMENTS:
            match = index_pattern.match(statement)
            self.assertIsNotNone(match, statement)
            assert match is not None
            actual.add(
                (
                    match.group(1),
                    tuple(column.strip() for column in match.group(2).split(",")),
                )
            )

        self.assertTrue(v20260909_0124_corpus_fk_indexes.FORWARD_ONLY)
        self.assertEqual(
            v20260909_0124_corpus_fk_indexes.DOWN_REVISION,
            "20260908_0123_source_analysis_dimensions",
        )
        self.assertEqual(actual, expected)

    def test_migration_chain_is_ordered_and_pending_is_deterministic(self):
        validate_migration_chain()
        self.assertGreaterEqual(len(MIGRATIONS), 2)
        self.assertEqual(LATEST_MIGRATION_ID, MIGRATIONS[-1].migration_id)

        pending = pending_migrations({MIGRATIONS[0].migration_id})
        self.assertEqual([item.migration_id for item in pending], [migration.migration_id for migration in MIGRATIONS[1:]])
        self.assertEqual(pending_migrations({migration.migration_id for migration in MIGRATIONS}), [])

    def test_downgrade_plan_targets_revisions_without_database(self):
        applied = {migration.migration_id for migration in MIGRATIONS}
        plan_to_initial = downgrade_plan(MIGRATIONS[0].migration_id, applied)
        self.assertEqual([item.migration_id for item in plan_to_initial], [migration.migration_id for migration in reversed(MIGRATIONS[1:])])
        self.assertFalse(any("DROP TABLE" in statement.upper() for migration in plan_to_initial for statement in migration.downgrade_statements))

        plan_to_empty = downgrade_plan(None, applied)
        self.assertEqual([item.migration_id for item in plan_to_empty], [migration.migration_id for migration in reversed(MIGRATIONS)])
        self.assertTrue(any("DROP TABLE" in statement.upper() for migration in plan_to_empty for statement in migration.downgrade_statements))


if __name__ == "__main__":
    unittest.main()
