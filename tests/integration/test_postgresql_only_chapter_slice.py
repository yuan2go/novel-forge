from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    run_single_chapter_slice,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    FakeDeterministicProvider,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class PostgreSQLOnlyChapterSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_one_chapter_uses_authority_handlers_recovery_and_verified_export(self) -> None:
        project_id = identifier("chapter-project")
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="chapter-slice-worker",
            chapter=1,
            title="The Cost of a Promise",
            premise="The protagonist must pay a visible cost to keep a promise.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="postgresql-only-chapter-test",
            commit_sha="c" * 40,
        )
        result = run_single_chapter_slice(
            DATABASE_URL,
            request=request,
            registry=build_chapter_handler_registry(
                DeterministicFixtureChapterProvider()
            ),
            object_store_adapter=FakeDeterministicProvider("ambiguous"),
            retry_once_at=ChapterNode.DRAFT,
            exercise_unknown_export_reconciliation=True,
        )

        self.assertEqual(result.root_status, "SUCCEEDED")
        self.assertEqual(result.saga_status, "SUCCEEDED")
        self.assertEqual(set(result.operation_ids), set(ChapterNode))
        self.assertEqual(set(result.outputs), set(ChapterNode))
        self.assertTrue(result.export_evidence.retry_blocked_before_reconciliation)
        self.assertTrue(result.export_evidence.stale_fencing_rejected)
        self.assertEqual(result.export_evidence.reconciliation_outcome, "ambiguous")
        self.assertTrue(result.export_evidence.duplicate_receipt_replayed)

        manifest = result.evidence_manifest
        self.assertEqual(manifest["root"]["status"], "SUCCEEDED")
        self.assertEqual(manifest["saga"]["status"], "SUCCEEDED")
        self.assertEqual(manifest["saga"]["forward_recovery_attempts"], 1)
        self.assertEqual(len(manifest["operations"]), 9)
        self.assertEqual(len(manifest["outputs"]), 8)
        self.assertEqual(manifest["attempt_counts"][ChapterNode.DRAFT.value], 2)
        for node in ChapterNode:
            self.assertEqual(manifest["operation_statuses"][node.value], "SUCCEEDED")
            self.assertEqual(manifest["attempt_terminal_statuses"][node.value], "SUCCEEDED")
            self.assertEqual(manifest["qualification_decisions"][node.value], "ELIGIBLE")
        self.assertEqual(manifest["export"]["blob_status"], "AVAILABLE")
        self.assertEqual(manifest["export"]["effect_status"], "SUCCEEDED")
        self.assertEqual(manifest["export"]["dispatch_status"], "SUCCEEDED")
        self.assertEqual(manifest["export"]["receipt_status"], "VERIFIED")
        self.assertGreaterEqual(manifest["evidence_counts"]["state_event"], 1)
        self.assertGreaterEqual(manifest["evidence_counts"]["audit_log"], 1)
        self.assertGreaterEqual(manifest["evidence_counts"]["outbox_event"], 1)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                WHERE operation.root_operation_id = %s
                  AND binding.content_hash <> ''
                """,
                [result.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 8)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation AS operation
                WHERE operation.root_operation_id = %s
                  AND operation.operation_id <> %s
                  AND jsonb_array_length(operation.input_asset_snapshot) > 0
                """,
                [result.root_operation_id, result.root_operation_id],
            )
            self.assertEqual(cursor.fetchone()[0], 7)

    def test_standard_success_adapter_completes_without_unknown_probe(self) -> None:
        project_id = identifier("chapter-project-success")
        request = SingleChapterRequest(
            project_id=project_id,
            workspace_id=f"workspace:{project_id}",
            actor_id="chapter-slice-worker",
            chapter=1,
            title="A Bounded Success",
            premise="A choice has an immediate and visible cost.",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            application_build_id="postgresql-only-chapter-test",
            commit_sha="c" * 40,
        )

        result = run_single_chapter_slice(
            DATABASE_URL,
            request=request,
            registry=build_chapter_handler_registry(
                DeterministicFixtureChapterProvider()
            ),
            object_store_adapter=FakeDeterministicProvider("success"),
        )

        self.assertEqual(result.root_status, "SUCCEEDED")
        self.assertEqual(result.export_evidence.reconciliation_outcome, "not_exercised")
        self.assertFalse(result.export_evidence.retry_blocked_before_reconciliation)
        self.assertEqual(result.evidence_manifest["export"]["blob_status"], "AVAILABLE")


if __name__ == "__main__":
    unittest.main()
