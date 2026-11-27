from __future__ import annotations

import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_outcome import (
    ChapterOutcomeAuthorityApplication,
    ChapterOutcomeCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import NarrativeStateRebuildService
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration import (
    test_chapter_outcome_story_state_postgres as outcome_fixture,
)


class NarrativeStateV2PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_successful_outcome_is_not_visible_before_book_acceptance(self) -> None:
        project_id = identifier("narrative-v2-unaccepted")
        book_id = f"book:{project_id}"
        inputs = outcome_fixture.ChapterOutcomeStoryStatePostgresTests._seed_inputs(
            project_id
        )
        application = ChapterOutcomeAuthorityApplication(
            DATABASE_URL,
            application_build_id="narrative-state-v2-postgres",
            commit_sha="8" * 40,
        )
        principal = Principal(
            principal_id="narrative-state-v2-worker",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )
        admission = application.admit(
            ChapterOutcomeCommand(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                actor_id=principal.principal_id,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                idempotency_key=f"{project_id}:chapter:1:outcome",
                payload={
                    "book_id": book_id,
                    "chapter_number": 1,
                    "parent_group_version_id": "group:v1",
                    "cost_receipt_refs": [],
                },
                input_assets=tuple(inputs),
            ),
            principal=principal,
        )
        application.run_or_recover(admission)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT asset.asset_type, version.content->>'contract_version'
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE binding.operation_id=%s
                ORDER BY asset.asset_type
                """,
                [admission.operation_id],
            )
            contracts = dict(uow.cursor.fetchall())
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_story_state_reducer_application
                WHERE project_id=%s
                """,
                [project_id],
            )
            reducer_receipts = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM authority_narrative_state_event_projection
                   WHERE project_id=%s AND book_id=%s),
                  (SELECT COUNT(*) FROM authority_narrative_current_state_projection
                   WHERE project_id=%s AND book_id=%s),
                  (SELECT COUNT(*) FROM authority_narrative_state_rebuild_source
                   WHERE project_id=%s AND book_id=%s)
                """,
                [project_id, book_id, project_id, book_id, project_id, book_id],
            )
            accepted_projection_counts = tuple(
                int(value) for value in uow.cursor.fetchone()
            )

        self.assertEqual(
            contracts,
            {
                "canon_snapshot": "canon-snapshot-v2",
                "chapter_outcome": "chapter-outcome-v3",
                "story_state_snapshot": "story-state-snapshot-v2",
            },
        )
        self.assertEqual(reducer_receipts, 2)
        self.assertEqual(accepted_projection_counts, (0, 0, 0))
        with self.assertRaises(KernelError) as error:
            NarrativeStateRebuildService(DATABASE_URL).rebuild(
                project_id=project_id, book_id=book_id
            )
        self.assertEqual(error.exception.code, "NARRATIVE_REBUILD_SOURCE_MISSING")


if __name__ == "__main__":
    unittest.main()
