from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class CommandKernelLifecyclePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_cas_transition_persists_event_audit_and_outbox_atomically(self) -> None:
        project_id, operation_id = self._operation()
        command = OperationTransitionCommand(
            operation_id=operation_id,
            project_id=project_id,
            expected_version=0,
            expected_status="ADMITTED",
            target_status="READY",
            actor_id="scheduler",
            reason="admission is dispatchable",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            causation_id="",
        )

        result = transition_operation(DATABASE_URL, command)

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["version"], 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    status,
                    version,
                    (
                        SELECT COUNT(*)
                        FROM state_event
                        WHERE aggregate_type = 'authority_operation'
                          AND aggregate_id = %s
                    ),
                    (
                        SELECT COUNT(*)
                        FROM audit_log
                        WHERE operation_id = %s
                          AND action = 'authority.operation.status_changed'
                    ),
                    (
                        SELECT COUNT(*)
                        FROM outbox_event AS outbox
                        JOIN state_event AS event ON event.event_id = outbox.event_id
                        WHERE event.aggregate_type = 'authority_operation'
                          AND event.aggregate_id = %s
                          AND outbox.topic = 'authority.operation.status_changed'
                    )
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, operation_id, operation_id, operation_id, project_id],
            )
            self.assertEqual(cursor.fetchone(), ("READY", 1, 1, 1, 1))

    def test_cas_distinguishes_version_and_status_conflicts(self) -> None:
        project_id, operation_id = self._operation()
        transition_operation(
            DATABASE_URL,
            self._command(operation_id, project_id, 0, "ADMITTED", "READY"),
        )

        with self.assertRaises(KernelError) as version_conflict:
            transition_operation(
                DATABASE_URL,
                self._command(operation_id, project_id, 0, "READY", "EXECUTING"),
            )
        self.assertEqual(version_conflict.exception.code, "OPERATION_VERSION_CONFLICT")

        with self.assertRaises(KernelError) as status_conflict:
            transition_operation(
                DATABASE_URL,
                self._command(operation_id, project_id, 1, "ADMITTED", "READY"),
            )
        self.assertEqual(status_conflict.exception.code, "OPERATION_STATUS_CONFLICT")

    def test_repository_applies_transition_guard_before_update(self) -> None:
        project_id, operation_id = self._operation(status="COMPENSATION_REQUIRED")

        with self.assertRaises(KernelError) as caught:
            transition_operation(
                DATABASE_URL,
                self._command(
                    operation_id,
                    project_id,
                    0,
                    "COMPENSATION_REQUIRED",
                    "SUCCEEDED",
                ),
            )

        self.assertEqual(caught.exception.code, "OPERATION_TRANSITION_INVALID")

    def _operation(self, status: str = "ADMITTED") -> tuple[str, str]:
        project_id = identifier("project")
        operation_id = identifier("operation")
        definition_name = identifier("definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status=status,
            )
        return project_id, operation_id

    @staticmethod
    def _command(
        operation_id: str,
        project_id: str,
        version: int,
        status: str,
        target: str,
    ) -> OperationTransitionCommand:
        return OperationTransitionCommand(
            operation_id=operation_id,
            project_id=project_id,
            expected_version=version,
            expected_status=status,
            target_status=target,
            actor_id="kernel-test",
            reason="test transition",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            causation_id="",
        )


if __name__ == "__main__":
    unittest.main()
