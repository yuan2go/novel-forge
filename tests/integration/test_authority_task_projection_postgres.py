from __future__ import annotations

import unittest

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.recovery import (
    RecoverOperationCommand,
    recover_operation,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.task_authority import (
    AuthorityTaskQuery,
    OutboxRecoveryCommand,
    requeue_outbox_dead_letter,
)
from novel_forge.storage.production_uow import ProductionUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class AuthorityTaskProjectionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_task_center_and_health_project_command_kernel_state(self) -> None:
        project_id = identifier("task-projection-project")
        workspace_id = identifier("task-projection-workspace")
        result = ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="task-projection-integration",
            commit_sha="c" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id="task-projection-operator",
                idempotency_key=f"task-projection:{project_id}",
                trace_id=f"trace:{project_id}",
                correlation_id=f"correlation:{project_id}",
                payload={"title": "Task Projection"},
            )
        )
        query = AuthorityTaskQuery(DATABASE_URL)
        center = query.list_tasks(project_id=project_id)
        detail = query.require_task(
            project_id=project_id, operation_id=result["operation_id"]
        )
        timeline = query.timeline(
            project_id=project_id, operation_id=result["operation_id"]
        )
        health = query.system_health(project_id=project_id)

        self.assertEqual(center["authority"], "postgresql")
        self.assertEqual(center["summary"]["task_count"], 1)
        self.assertEqual(detail["status"], "SUCCEEDED")
        self.assertEqual(detail["attempt"]["status"], "SUCCEEDED")
        self.assertGreaterEqual(len(timeline), 1)
        self.assertEqual(health["storage_authority"], "postgresql")
        self.assertFalse(health["filesystem_authority"])
        self.assertFalse(health["legacy_task_authority"])

    def test_retryable_operation_recovery_is_versioned_idempotent_and_projected(
        self,
    ) -> None:
        project_id = identifier("task-recovery-project")
        operation_id = identifier("task-recovery-operation")
        definition_name = identifier("task.recovery")
        with transaction() as connection:
            insert_definition(connection.cursor(), definition_name)
            insert_operation(
                connection.cursor(),
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="FAILED_RETRYABLE",
            )

        command = RecoverOperationCommand(
            operation_id=operation_id,
            project_id=project_id,
            actor_id="task-recovery-operator",
            expected_version=0,
            idempotency_key=f"recover:{operation_id}:0",
            reason="retry the failed generation",
            trace_id=f"trace:{operation_id}",
            correlation_id=f"correlation:{operation_id}",
        )
        result = recover_operation(DATABASE_URL, command)
        replay = recover_operation(DATABASE_URL, command)

        self.assertEqual(result["action"], "READY_FOR_RETRY")
        self.assertFalse(result["replayed"])
        self.assertTrue(replay["replayed"])
        task = AuthorityTaskQuery(DATABASE_URL).require_task(
            project_id=project_id, operation_id=operation_id
        )
        workbench = AuthorityTaskQuery(DATABASE_URL).recovery_workbench(
            project_id=project_id
        )
        self.assertEqual(task["status"], "READY")
        self.assertEqual(task["version"], 1)
        self.assertEqual(
            workbench["operation_recovery_commands"][0]["operation_id"],
            operation_id,
        )

    def test_outbox_recovery_preserves_dead_letter_and_creates_claimable_generation(
        self,
    ) -> None:
        project_id = identifier("outbox-recovery-project")
        operation_id = identifier("outbox-recovery-operation")
        definition_name = identifier("outbox.recovery")
        event_id = identifier("outbox-source-event")
        outbox_id = identifier("outbox-dead-letter")
        with transaction() as connection:
            cursor = connection.cursor()
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="SUCCEEDED",
            )
            cursor.execute(
                """
                INSERT INTO state_event (
                    event_id, aggregate_type, aggregate_id, project_id,
                    event_type, event_version, sequence_number,
                    correlation_id, payload
                ) VALUES (%s, 'authority_operation', %s, %s,
                          'test.outbox.created', 1, 1, %s, %s)
                """,
                [
                    event_id,
                    operation_id,
                    project_id,
                    f"correlation:{operation_id}",
                    Jsonb({"operation_id": operation_id, "value": "original"}),
                ],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event (
                    outbox_id, event_id, project_id, topic, status,
                    attempt_count, replay_count, last_error, dead_letter_at, payload
                ) VALUES (%s, %s, %s, 'test.delivery', 'dead_letter',
                          3, 0, 'exhausted', NOW(), %s)
                """,
                [
                    outbox_id,
                    event_id,
                    project_id,
                    Jsonb({"operation_id": operation_id, "value": "original"}),
                ],
            )
        principal = Principal(
            principal_id="authority-recovery-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"task.authority.recover"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )
        command = OutboxRecoveryCommand(
            outbox_id=outbox_id,
            project_id=project_id,
            actor_id="untrusted-payload-actor",
            expected_attempt_count=3,
            idempotency_key=f"outbox-recover:{outbox_id}:3",
            reason="operator approved a new delivery generation",
            trace_id=f"trace:{outbox_id}",
            correlation_id=f"correlation:{outbox_id}",
        )

        result = requeue_outbox_dead_letter(
            DATABASE_URL, command, principal=principal
        )
        replay = requeue_outbox_dead_letter(
            DATABASE_URL, command, principal=principal
        )

        self.assertEqual(result["action"], "REQUEUE_NEW_GENERATION")
        self.assertFalse(result["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            replay["replacement_outbox_id"], result["replacement_outbox_id"]
        )
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT status, attempt_count, replay_count, last_error,
                       dead_letter_at IS NOT NULL
                FROM outbox_event WHERE outbox_id = %s
                """,
                [outbox_id],
            )
            self.assertEqual(
                cursor.fetchone(), ("dead_letter", 3, 0, "exhausted", True)
            )
            cursor.execute(
                """
                SELECT status, attempt_count, replay_count, payload
                FROM outbox_event WHERE outbox_id = %s
                """,
                [result["replacement_outbox_id"]],
            )
            replacement = cursor.fetchone()
            self.assertEqual(replacement[:3], ("pending", 0, 1))
            self.assertEqual(replacement[3]["value"], "original")
            cursor.execute(
                """
                SELECT actor_id, replacement_outbox_id
                FROM authority_outbox_recovery_command
                WHERE recovery_command_id = %s
                """,
                [result["recovery_command_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("authority-recovery-operator", result["replacement_outbox_id"]),
            )

        with ProductionUnitOfWork(DATABASE_URL) as uow:
            claimed = uow.outbox.claim(
                "authority-outbox-integration", project_id, 10, 30
            )
        self.assertIn(
            result["replacement_outbox_id"],
            {item["outbox_id"] for item in claimed},
        )
        workbench = AuthorityTaskQuery(DATABASE_URL).recovery_workbench(
            project_id=project_id
        )
        self.assertEqual(
            workbench["outbox_recovery_commands"][0]["replacement_outbox_id"],
            result["replacement_outbox_id"],
        )


if __name__ == "__main__":
    unittest.main()
