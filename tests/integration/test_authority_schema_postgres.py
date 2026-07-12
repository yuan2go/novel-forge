from __future__ import annotations

import os
import unittest

from novel_forge.storage.migrations import run_migrations

URL = os.environ.get("NOVEL_FORGE_DATABASE_URL", "")


@unittest.skipUnless(URL, "NOVEL_FORGE_DATABASE_URL is required for PostgreSQL integration")
class AuthoritySchemaPostgresTests(unittest.TestCase):
    def test_authority_schema_migrates_and_enforces_active_attempt(self) -> None:
        status = run_migrations(URL)
        self.assertTrue(status["ok"])
        import psycopg
        with psycopg.connect(URL) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('authority_operation')")
            self.assertEqual(cursor.fetchone()[0], "authority_operation")
