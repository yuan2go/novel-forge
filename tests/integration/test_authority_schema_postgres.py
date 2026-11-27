from __future__ import annotations

import unittest

from novel_forge.storage.migrations import LATEST_MIGRATION_ID, run_migrations
from tests.integration.authority_postgres_support import DATABASE_URL, connect


class AuthoritySchemaPostgresTests(unittest.TestCase):
    def test_authority_schema_migrates_and_enforces_active_attempt(self) -> None:
        status = run_migrations(DATABASE_URL)
        self.assertTrue(status["ok"])
        self.assertEqual(status["current"], LATEST_MIGRATION_ID)
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('authority_operation')")
            self.assertEqual(cursor.fetchone()[0], "authority_operation")
