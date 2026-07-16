from __future__ import annotations

import unittest

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.completion import (
    CompletionCommandContext,
    evaluate_completion_contract,
    finalize_operation_completion,
)
from novel_forge.modules.command_kernel.asset_runtime import (
    AssetCommandContext,
    bind_operation_output_asset,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class CompletionContractPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_frozen_gate_contract_blocks_success_despite_definition_drift(self) -> None:
        context, operation_id, definition = self._operation(
            {"required_gates": ["quality.release"]}
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation_definition SET completion_contract = '{}'::jsonb WHERE name = %s",
                [definition],
            )
        blocked = finalize_operation_completion(
            DATABASE_URL,
            context,
            operation_id=operation_id,
            expected_status="EXECUTING",
            expected_version=0,
        )
        self.assertEqual(blocked["status"], "WAITING_GATE")
        self.assertIn("gate:quality.release", blocked["missing"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_completion_gate (
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (%s, %s, 'quality.release', 'PASSED', '{}'::jsonb)
                """,
                [identifier("gate"), operation_id],
            )
        completed = finalize_operation_completion(
            DATABASE_URL,
            context,
            operation_id=operation_id,
            expected_status="WAITING_GATE",
            expected_version=1,
        )
        self.assertEqual(completed["status"], "SUCCEEDED")

    def test_contract_routes_children_effect_approval_and_failed_gate(self) -> None:
        context, operation_id, _ = self._operation(
            {
                "required_child_operations": [
                    {"definition_name": "child.review", "allowed_states": ["SUCCEEDED"]}
                ],
                "required_approvals": ["editor.approval"],
                "required_external_effects": [
                    {"capability": "publisher.submit", "allowed_states": ["SUCCEEDED"]}
                ],
                "required_gates": ["quality.release"],
            }
        )
        evaluation = evaluate_completion_contract(DATABASE_URL, operation_id, context.project_id)
        self.assertEqual(evaluation["target_status"], "WAITING_APPROVAL")
        self.assertIn("child:child.review", evaluation["missing"])
        self.assertIn("effect:publisher.submit", evaluation["missing"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_completion_gate (
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (%s, %s, 'quality.release', 'FAILED', '{}'::jsonb)
                """,
                [identifier("gate"), operation_id],
            )
        failed = evaluate_completion_contract(DATABASE_URL, operation_id, context.project_id)
        self.assertEqual(failed["target_status"], "FAILED_FINAL")

    def test_asset_blob_qualification_trace_audit_cost_and_outbox_contract(self) -> None:
        contract = {
            "required_asset_selectors": [
                {
                    "selector": "draft",
                    "output_key": "draft.primary",
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_qualifications": ["production_eligible"],
            "required_blobs": [{"status": "AVAILABLE", "role": "content", "min_count": 1}],
            "required_evidence": ["trace", "audit", "cost_when_provider_used"],
            "required_audit_actions": ["draft.completed"],
            "required_outbox_events": ["draft.completed"],
        }
        context, operation_id, _ = self._operation(contract)
        initial = evaluate_completion_contract(DATABASE_URL, operation_id, context.project_id)
        self.assertEqual(initial["target_status"], "WAITING_GATE")
        asset_id = identifier("asset")
        version_id = identifier("version")
        blob_id = identifier("blob")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, 'draft')",
                [asset_id, context.project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version (
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', '{}'::jsonb, 'sha256:draft')
                """,
                [version_id, asset_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_qualification (
                    qualification_id, asset_version_id, policy_version, decision, evidence
                ) VALUES (%s, %s, 'v1', 'ELIGIBLE', '{}'::jsonb)
                """,
                [identifier("qualification"), version_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_blob (
                    blob_id, object_key, expected_hash, expected_size, actual_hash,
                    actual_size, status, project_id, provider, media_type
                ) VALUES (%s, %s, 'sha256:draft', 1, 'sha256:draft', 1,
                          'AVAILABLE', %s, 'test', 'text/plain')
                """,
                [blob_id, identifier("key"), context.project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version_blob_reference (
                    reference_id, asset_version_id, blob_id, role, ordinal,
                    media_type, content_hash
                ) VALUES (%s, %s, %s, 'content', 0, 'text/plain', 'sha256:draft')
                """,
                [identifier("reference"), version_id, blob_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_operation_cost_evidence (
                    cost_evidence_id, operation_id, provider, model, amount, currency, evidence
                ) VALUES (%s, %s, 'test', 'model', 1, 'USD', '{}'::jsonb)
                """,
                [identifier("cost"), operation_id],
            )
            cursor.execute(
                """
                INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
                VALUES (%s, %s, %s, 'draft.completed', '{}'::jsonb)
                """,
                [identifier("audit"), context.project_id, operation_id],
            )
            event_id = identifier("event")
            cursor.execute(
                """
                INSERT INTO state_event (
                    event_id, aggregate_type, aggregate_id, project_id, event_type,
                    event_version, sequence_number, correlation_id, causation_id, payload
                ) VALUES (
                    %s, 'authority_operation', %s, %s, 'draft.completed',
                    1, 1, '', '', '{}'::jsonb
                )
                """,
                [event_id, operation_id, context.project_id],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event (outbox_id, event_id, project_id, topic, status, payload)
                VALUES (%s, %s, %s, 'draft.completed', 'PENDING', %s)
                """,
                [
                    identifier("outbox"),
                    event_id,
                    context.project_id,
                    Jsonb({"operation_id": operation_id}),
                ],
            )
        bind_operation_output_asset(
            DATABASE_URL,
            AssetCommandContext(
                operation_id=operation_id,
                project_id=context.project_id,
                actor_id="draft-handler",
                trace_id=context.trace_id,
                correlation_id=context.correlation_id,
            ),
            asset_version_id=version_id,
            output_key="draft.primary",
            role="primary",
        )
        passed = evaluate_completion_contract(DATABASE_URL, operation_id, context.project_id)
        self.assertTrue(passed["satisfied"])
        self.assertEqual(passed["target_status"], "SUCCEEDED")

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_asset_qualification (
                    qualification_id, asset_version_id, policy_version, decision, evidence
                ) VALUES (%s, %s, 'v2', 'REVOKED', '{}'::jsonb)
                """,
                [identifier("qualification-revoked"), version_id],
            )
        revoked = evaluate_completion_contract(DATABASE_URL, operation_id, context.project_id)
        self.assertFalse(revoked["satisfied"])
        self.assertIn("qualification:production_eligible", revoked["missing"])

    def test_project_asset_and_admission_audit_cannot_satisfy_operation_evidence(self) -> None:
        contract = {
            "required_asset_selectors": [{"selector": "draft"}],
            "required_evidence": ["audit"],
            "required_audit_actions": ["draft.generated"],
        }
        context, operation_id, _ = self._operation(contract)
        with transaction() as connection, connection.cursor() as cursor:
            asset_id = identifier("unrelated-asset")
            cursor.execute(
                "INSERT INTO authority_asset (asset_id, project_id, asset_type) VALUES (%s, %s, 'draft')",
                [asset_id, context.project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version (
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', '{}'::jsonb, 'sha256:old')
                """,
                [identifier("unrelated-version"), asset_id],
            )
            cursor.execute(
                """
                INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload)
                VALUES (%s, %s, %s, 'authority.operation.admitted', '{}'::jsonb)
                """,
                [identifier("admission-audit"), context.project_id, operation_id],
            )
        evaluation = evaluate_completion_contract(DATABASE_URL, operation_id, context.project_id)
        self.assertIn("asset:draft", evaluation["missing"])
        self.assertIn("evidence:audit", evaluation["missing"])
        self.assertIn("audit:draft.generated", evaluation["missing"])

    def test_worker_success_submits_result_but_cannot_bypass_completion_contract(self) -> None:
        context, operation_id, _ = self._operation({"required_gates": ["release"]})
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'READY' WHERE operation_id = %s",
                [operation_id],
            )
        attempt_id = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=context.project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )["attempt_id"]
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=context.project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=context.project_id,
            worker_id="worker",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=context.project_id,
            worker_id="worker",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, worker)
        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **worker.__dict__,
                expected_operation_version=1,
                expected_operation_status="EXECUTING",
            ),
            outcome="success",
            result={"draft": "accepted"},
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, operation.status
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                WHERE attempt.attempt_id = %s
                """,
                [attempt_id],
            )
            self.assertEqual(cursor.fetchone(), ("RESULT_SUBMITTED", "WAITING_GATE"))

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_completion_gate (
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (%s, %s, 'release', 'PASSED', '{}'::jsonb)
                """,
                [identifier("gate"), operation_id],
            )

        completed = finalize_operation_completion(
            DATABASE_URL,
            context,
            operation_id=operation_id,
            expected_status="WAITING_GATE",
            expected_version=2,
        )
        self.assertEqual(completed["status"], "SUCCEEDED")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempt.status, operation.status,
                       COUNT(lease.lease_id) FILTER (WHERE lease.status = 'HELD')
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                LEFT JOIN authority_lease_acquisition AS lease
                  ON lease.attempt_id = attempt.attempt_id
                WHERE attempt.attempt_id = %s
                GROUP BY attempt.status, operation.status
                """,
                [attempt_id],
            )
            self.assertEqual(cursor.fetchone(), ("SUCCEEDED", "SUCCEEDED", 0))

    def _operation(
        self,
        contract: dict[str, object],
    ) -> tuple[CompletionCommandContext, str, str]:
        project_id = identifier("project")
        definition = identifier("completion-definition")
        operation_id = identifier("operation")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition,
                project_id=project_id,
                status="EXECUTING",
            )
            cursor.execute(
                "UPDATE authority_operation SET completion_contract_snapshot = %s WHERE operation_id = %s",
                [Jsonb(contract), operation_id],
            )
            cursor.execute(
                """
                UPDATE authority_operation
                SET actor_id = 'worker', trace_id = %s, correlation_id = %s
                WHERE operation_id = %s
                """,
                [identifier("trace"), identifier("correlation"), operation_id],
            )
        return (
            CompletionCommandContext(
                project_id=project_id,
                actor_id="completion-evaluator",
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
            ),
            operation_id,
            definition,
        )


if __name__ == "__main__":
    unittest.main()
