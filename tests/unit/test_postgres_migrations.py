from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, downgrade_plan, pending_migrations, validate_migration_chain


class PostgresMigrationTests(unittest.TestCase):
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
