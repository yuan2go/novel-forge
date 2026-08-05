from __future__ import annotations

import unittest

from tests.integration.authority_postgres_support import connect, ensure_migrated


class UnifiedAgentRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_runtime_projection_reuses_kernel_attempt_and_lease_tables(self) -> None:
        with connect() as connection:
            tables = connection.execute(
                """
                SELECT
                    to_regclass('authority_agent_definition_activation'),
                    to_regclass('authority_chapter_node_agent_binding'),
                    to_regclass('authority_agent_runtime_binding'),
                    to_regclass('authority_attempt'),
                    to_regclass('authority_lease_acquisition'),
                    to_regclass('authority_agent_attempt'),
                    to_regclass('authority_agent_lease')
                """
            ).fetchone()

        self.assertEqual(
            tuple("" if value is None else str(value) for value in tables),
            (
                "authority_agent_definition_activation",
                "authority_chapter_node_agent_binding",
                "authority_agent_runtime_binding",
                "authority_attempt",
                "authority_lease_acquisition",
                "",
                "",
            ),
        )

    def test_runtime_binding_has_no_duplicate_status_column(self) -> None:
        with connect() as connection:
            columns = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='authority_agent_runtime_binding'
                    """
                ).fetchall()
            }

        self.assertIn("operation_id", columns)
        self.assertIn("attempt_id", columns)
        self.assertIn("fencing_token", columns)
        self.assertNotIn("run_status", columns)
        self.assertNotIn("attempt_status", columns)


if __name__ == "__main__":
    unittest.main()
