from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS, pending_migrations, validate_migration_chain


class PostgresMigrationTests(unittest.TestCase):
    def test_migration_chain_is_ordered_and_pending_is_deterministic(self):
        validate_migration_chain()
        self.assertGreaterEqual(len(MIGRATIONS), 2)
        self.assertEqual(LATEST_MIGRATION_ID, MIGRATIONS[-1].migration_id)

        pending = pending_migrations({MIGRATIONS[0].migration_id})
        self.assertEqual([item.migration_id for item in pending], [migration.migration_id for migration in MIGRATIONS[1:]])
        self.assertEqual(pending_migrations({migration.migration_id for migration in MIGRATIONS}), [])


if __name__ == "__main__":
    unittest.main()
