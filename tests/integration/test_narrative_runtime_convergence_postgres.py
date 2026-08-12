from __future__ import annotations

import unittest

import psycopg

from novel_forge.modules.mkaos_authority import MkaosAuthorityQuery
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


class NarrativeRuntimeConvergencePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_replan_evidence_columns_and_usage_projections_are_live(self) -> None:
        with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema=current_schema()
                  AND table_name='authority_book_replan'
                  AND column_name IN (
                    'impact_scope', 'preserved_invariants', 'decision_evidence'
                  )
                ORDER BY column_name
                """
            )
            columns = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema=current_schema()
                  AND table_name IN (
                    'authority_context_runtime_usage_projection',
                    'authority_mkaos_runtime_usage_projection'
                  )
                ORDER BY table_name
                """
            )
            views = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM authority_context_runtime_usage_projection),
                  (SELECT COUNT(*) FROM authority_mkaos_runtime_usage_projection)
                """
            )
            counts = tuple(int(value) for value in cursor.fetchone())

        self.assertEqual(
            columns,
            ["decision_evidence", "impact_scope", "preserved_invariants"],
        )
        self.assertEqual(
            views,
            [
                "authority_context_runtime_usage_projection",
                "authority_mkaos_runtime_usage_projection",
            ],
        )
        self.assertGreaterEqual(counts[0], counts[1])
        self.assertGreaterEqual(counts[1], 0)
        self.assertEqual(
            MkaosAuthorityQuery(DATABASE_URL).list_runtime_usage(
                project_id="project-with-no-usage"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
