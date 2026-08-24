from __future__ import annotations

import json
from pathlib import Path
import unittest

from novel_forge.modules.provider_qualification import (
    D0ProbeConfig,
    D0QualificationAuthority,
    D0QualificationCommand,
    D0QualificationScheduler,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
    transaction,
)


ROOT = Path(__file__).resolve().parents[2]


class _RecordingObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_json(self, *, object_key: str, payload: dict) -> str:
        self.objects[object_key] = json.loads(json.dumps(payload))
        return f"fixture-object://authority-evidence/{object_key}"


class D0ProviderQualificationAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_fixture_protocol_is_persisted_but_real_gates_stay_false(self) -> None:
        project_id = identifier("d0-project")
        book_id = identifier("d0-book")
        workspace_id = f"workspace:{project_id}"
        seed_authority_project_book(project_id=project_id, book_id=book_id)
        store = _RecordingObjectStore()
        authority = D0QualificationAuthority(
            DATABASE_URL,
            evidence_store=store,
            application_build_id="d0-authority-integration",
            commit_sha="a" * 40,
        )
        command = D0QualificationCommand(
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id="d0-integration-operator",
            idempotency_key=f"{project_id}:openai:d0:v1",
            trace_id=identifier("d0-trace"),
            correlation_id=identifier("d0-correlation"),
            config=D0ProbeConfig.from_mapping(
                json.loads(
                    (ROOT / "config/provider/d0-openai-probe.json").read_text(
                        encoding="utf-8"
                    )
                )
            ),
        )

        admitted = authority.admit(command)
        scheduler = D0QualificationScheduler(authority)
        self.assertIn(
            (admitted["operation_id"], project_id), scheduler.pending_operations()
        )
        result = scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=project_id
        )
        restarted_store = _RecordingObjectStore()
        replay = D0QualificationScheduler(
            D0QualificationAuthority(
                DATABASE_URL,
                evidence_store=restarted_store,
                application_build_id="d0-authority-integration",
                commit_sha="a" * 40,
                worker_id="integration-worker:d0-restarted",
            )
        ).run_or_recover(operation_id=admitted["operation_id"], project_id=project_id)

        self.assertEqual(result["status"], "BLOCKED_MISSING_CREDENTIALS")
        self.assertEqual(
            replay["report_asset_version_id"], result["report_asset_version_id"]
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(store.objects), 2)
        self.assertEqual(restarted_store.objects, {})
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT effect.external_effect_id),
                       COUNT(DISTINCT receipt.external_receipt_id)
                FROM authority_operation AS operation
                LEFT JOIN authority_attempt AS attempt ON attempt.operation_id=operation.operation_id
                LEFT JOIN authority_external_effect AS effect ON effect.operation_id=operation.operation_id
                LEFT JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                LEFT JOIN authority_external_receipt AS receipt ON receipt.dispatch_id=dispatch.dispatch_id
                WHERE operation.operation_id=%s
                GROUP BY operation.status
                """,
                [result["operation_id"]],
            )
            row = cursor.fetchone()
            # The fixture protocol persists both the synchronous basic receipt and
            # the reconciled unknown-after-send receipt. The cancelled probe has
            # no provider receipt, so replay must preserve exactly two receipts.
            self.assertEqual(row, ("WAITING_GATE", 1, 3, 2))
            cursor.execute(
                """
                SELECT run.fixture_protocol_only, run.decision, run.sdk_max_retries,
                       COUNT(scenario.scenario), BOOL_AND(scenario.request_object_ref <> ''),
                       BOOL_AND(scenario.response_object_ref <> '')
                FROM authority_d0_qualification_run AS run
                JOIN authority_d0_scenario_evidence AS scenario
                  ON scenario.qualification_run_id=run.qualification_run_id
                WHERE run.qualification_run_id=%s
                GROUP BY run.fixture_protocol_only, run.decision, run.sdk_max_retries
                """,
                [result["qualification_run_id"]],
            )
            self.assertEqual(cursor.fetchone(), (True, "BLOCKED", 0, 6, True, True))
            cursor.execute(
                """
                SELECT content->'gates', content->>'status', schema_version
                FROM authority_asset_version WHERE asset_version_id=%s
                """,
                [result["report_asset_version_id"]],
            )
            gates, status, schema_version = cursor.fetchone()
            self.assertFalse(any(gates.values()))
            self.assertEqual(status, "BLOCKED_MISSING_CREDENTIALS")
            self.assertEqual(schema_version, "d0-provider-probe-report.v2")
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_effect_reconciliation_evidence AS evidence
                JOIN authority_external_effect AS effect
                  ON effect.external_effect_id=evidence.external_effect_id
                WHERE effect.operation_id=(
                    SELECT operation_id FROM authority_d0_qualification_run
                    WHERE qualification_run_id=%s
                ) AND evidence.evidence->>'recovered_without_resend'='true'
                """,
                [result["qualification_run_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
