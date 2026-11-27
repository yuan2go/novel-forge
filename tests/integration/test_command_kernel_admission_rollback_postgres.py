from __future__ import annotations

import unittest
from contextlib import contextmanager
from collections.abc import Iterator
from uuid import uuid4

from psycopg import sql

from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)
from tests.integration.test_command_kernel_definition_postgres import definition_payload


class CommandKernelAdmissionRollbackPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_failure_after_state_event_rolls_back_every_admission_write(self) -> None:
        self._assert_failure_rolls_back("audit_log", "BEFORE")

    def test_failure_after_audit_rolls_back_every_admission_write(self) -> None:
        self._assert_failure_rolls_back("outbox_event", "BEFORE")

    def test_failure_after_outbox_rolls_back_every_admission_write(self) -> None:
        self._assert_failure_rolls_back("outbox_event", "AFTER")

    def _assert_failure_rolls_back(self, table: str, timing: str) -> None:
        command, context = self._registered_command()
        with rejecting_trigger(table, timing):
            with self.assertRaisesRegex(Exception, "admission evidence failure"):
                admit_command(DATABASE_URL, command, context=context)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM authority_operation WHERE idempotency_key = %s),
                    (SELECT COUNT(*) FROM authority_idempotency_record WHERE idempotency_key = %s),
                    (SELECT COUNT(*) FROM state_event WHERE project_id = %s),
                    (SELECT COUNT(*) FROM audit_log WHERE project_id = %s),
                    (SELECT COUNT(*) FROM outbox_event WHERE project_id = %s)
                """,
                [
                    command["idempotency_key"],
                    command["idempotency_key"],
                    command["project_id"],
                    command["project_id"],
                    command["project_id"],
                ],
            )
            self.assertEqual(cursor.fetchone(), (0, 0, 0, 0, 0))

    def _registered_command(self) -> tuple[dict, AdmissionContext]:
        definition = definition_payload(identifier("definition"))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        project_id = identifier("rollback-project")
        command = {
            "definition_name": definition["name"],
            "definition_version": definition["definition_version"],
            "project_id": project_id,
            "workspace_id": f"workspace:{project_id}",
            "actor_id": "actor-rollback",
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": identifier("idempotency"),
            "trace_id": identifier("trace"),
            "span_id": identifier("span"),
            "correlation_id": identifier("correlation"),
            "causation_id": "",
            "input": {"value": "rollback"},
            "input_assets": [],
        }
        context = AdmissionContext(
            actor_id=command["actor_id"],
            permissions=frozenset(definition["permissions"]),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id="admission-rollback-test",
            commit_sha="f" * 40,
        )
        return command, context


@contextmanager
def rejecting_trigger(table: str, timing: str) -> Iterator[None]:
    suffix = uuid4().hex
    function_name = f"test_reject_admission_{suffix}"
    trigger_name = f"test_reject_admission_{suffix}"
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'admission evidence failure';
                END;
                $$ LANGUAGE plpgsql
                """
            ).format(sql.Identifier(function_name))
        )
        cursor.execute(
            sql.SQL("CREATE TRIGGER {} {} INSERT ON {} FOR EACH ROW EXECUTE FUNCTION {}()")
            .format(
                sql.Identifier(trigger_name),
                sql.SQL(timing),
                sql.Identifier(table),
                sql.Identifier(function_name),
            )
        )
    try:
        yield
    finally:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP TRIGGER {} ON {}")
                .format(sql.Identifier(trigger_name), sql.Identifier(table))
            )
            cursor.execute(
                sql.SQL("DROP FUNCTION {}()")
                .format(sql.Identifier(function_name))
            )


if __name__ == "__main__":
    unittest.main()
