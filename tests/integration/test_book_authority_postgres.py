from __future__ import annotations

import unittest

from novel_forge.modules.book_authority import (
    BookAuthorityScheduler, BookProductionPolicy, BookProductionRequest,
    admit_book_production, pause_book_production, resume_book_production,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, transaction


class BookAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_three_fixture_chapters_recap_and_plan_adjustment_use_one_saga(self) -> None:
        project_id = identifier("book-authority-project")
        admission = admit_book_production(
            DATABASE_URL,
            BookProductionRequest(
                project_id=project_id, workspace_id=f"workspace:{project_id}",
                actor_id="trusted-book-scheduler", trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                idempotency_key=f"{project_id}:book:fixture",
                application_build_id="book-authority-fixture", commit_sha="b" * 40,
                policy=BookProductionPolicy(
                    target_chapter_count=3, light_recap_cadence=2,
                    formal_recap_cadence=3, book_budget="3.00",
                    chapter_budget="1.00", provider_budget="0",
                ),
            ),
        )
        scheduler = BookAuthorityScheduler(DATABASE_URL)
        pause_book_production(
            DATABASE_URL, project_id=project_id, saga_id=admission.saga_id,
            actor_id="trusted-book-scheduler", trace_id="pause-trace",
            correlation_id="pause-correlation", reason="operator fixture pause",
        )
        paused = scheduler.tick(
            project_id=project_id, root_operation_id=admission.root_operation_id
        )
        self.assertEqual(paused.saga_status, "WAITING_GATE")
        self.assertFalse(paused.executed_operation_id)
        resume_book_production(
            DATABASE_URL, project_id=project_id, saga_id=admission.saga_id,
            actor_id="trusted-book-scheduler", trace_id="resume-trace",
            correlation_id="resume-correlation", reason="operator fixture resume",
        )
        for _ in range(20):
            tick = scheduler.tick(
                project_id=project_id, root_operation_id=admission.root_operation_id
            )
            if tick.saga_status == "SUCCEEDED":
                break
        self.assertEqual(tick.saga_status, "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT step_key FROM authority_saga_step WHERE saga_id=%s ORDER BY ordinal",
                [admission.saga_id],
            )
            steps = [row[0] for row in cursor.fetchall()]
            self.assertEqual(
                steps,
                ["book_prepare", "chapter:1", "chapter:2", "recap:light:2", "plan_adjustment:2", "chapter:3", "recap:formal:3", "plan_adjustment:3"],
            )
            cursor.execute(
                "SELECT asset.asset_type, version.content FROM authority_operation_output_asset binding JOIN authority_asset asset ON asset.asset_id=binding.asset_id JOIN authority_asset_version version ON version.asset_version_id=binding.asset_version_id JOIN authority_operation operation ON operation.operation_id=binding.operation_id WHERE operation.root_operation_id=%s",
                [admission.root_operation_id],
            )
            outputs = cursor.fetchall()
        acceptance = [dict(content) for asset_type, content in outputs if asset_type == "chapter_acceptance_record"]
        self.assertEqual(sorted(item["chapter"] for item in acceptance), [1, 2, 3])
        self.assertTrue(all(item["fixture_protocol_only"] for item in acceptance))
        self.assertTrue(all(not item["production_verified"] for item in acceptance))
        self.assertEqual(len([1 for kind, _ in outputs if kind == "plan_adjustment_proposal"]), 2)


if __name__ == "__main__":
    unittest.main()
