from __future__ import annotations

import unittest
import hashlib
import json

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

    @staticmethod
    def release_evidence(project_id: str):
        candidates = (
            {
                "asset_version_id": f"{project_id}:checklist-v1", "asset_type": "operator_checklist",
                "project_id": project_id, "estimated_tokens": 20,
                "safe_summary": "Operator checklist completed.",
                "structured_facts": [{"key": "completed", "value": True}],
                "narrative_function": "release_evidence",
            },
            {
                "asset_version_id": f"{project_id}:approval-v1", "asset_type": "operator_approval",
                "project_id": project_id, "estimated_tokens": 20,
                "safe_summary": "Operator approved fixture release evidence.",
                "structured_facts": [{"key": "approved", "value": True}],
                "narrative_function": "release_evidence",
            },
        )
        with transaction() as connection, connection.cursor() as cursor:
            for candidate in candidates:
                content = {
                    "safe_summary": candidate["safe_summary"],
                    "structured_facts": candidate["structured_facts"],
                }
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                candidate["content_hash"] = content_hash
                asset_id = f"{candidate['asset_version_id']}:asset"
                cursor.execute(
                    "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, %s)",
                    [asset_id, project_id, candidate["asset_type"]],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version (
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                    """,
                    [candidate["asset_version_id"], asset_id, json.dumps(content), content_hash],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_qualification (
                        qualification_id, asset_version_id, policy_version, decision, evidence
                    ) VALUES (%s, %s, 'fixture-release-evidence-v1', 'ELIGIBLE', '{}'::jsonb)
                    """,
                    [f"{candidate['asset_version_id']}:qualification", candidate["asset_version_id"]],
                )
        return candidates

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
            context_candidates=self.release_evidence(project_id),
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
        self.assertEqual(len(manifest["operations"]), 13)
        self.assertEqual(len(manifest["outputs"]), 36)
        self.assertEqual(
            len(
                [
                    item
                    for item in manifest["outputs"]
                    if item["asset_type"] == "chapter_quality_evidence"
                ]
            ),
            15,
        )
        self.assertEqual(manifest["attempt_counts"][ChapterNode.DRAFT.value], 2)
        for node in ChapterNode:
            self.assertEqual(manifest["operation_statuses"][node.value], "SUCCEEDED")
            self.assertEqual(manifest["attempt_terminal_statuses"][node.value], "SUCCEEDED")
            self.assertEqual(manifest["qualification_decisions"][node.value], "ELIGIBLE")
        self.assertEqual(manifest["export"]["blob_status"], "AVAILABLE")
        self.assertEqual(manifest["export"]["effect_status"], "SUCCEEDED")
        self.assertEqual(manifest["export"]["dispatch_status"], "SUCCEEDED")
        self.assertEqual(manifest["export"]["receipt_status"], "VERIFIED")
        final_gate = next(
            item
            for item in manifest["outputs"]
            if item["asset_type"] == "final_release_gate_report"
        )
        self.assertEqual(final_gate["node"], ChapterNode.FINAL_RELEASE_GATE.value)
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
            self.assertEqual(cursor.fetchone()[0], 36)
            cursor.execute(
                """
                SELECT asset.asset_type, binding.role, version.content->>'state_kind'
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                WHERE operation.root_operation_id = %s
                  AND operation.definition_name = %s
                  AND binding.role = 'state_snapshot'
                ORDER BY asset.asset_type
                """,
                [result.root_operation_id, ChapterNode.CANON.definition_name],
            )
            snapshots = cursor.fetchall()
            self.assertEqual(len(snapshots), 9)
            self.assertEqual({row[2] for row in snapshots}, {
                "canon_snapshot", "character_state", "relationship_state",
                "timeline_snapshot", "foreshadow_state", "reader_promise",
                "reward_ledger", "world_rule", "power_state",
            })
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
            self.assertEqual(cursor.fetchone()[0], 11)

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
            context_candidates=self.release_evidence(project_id),
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
