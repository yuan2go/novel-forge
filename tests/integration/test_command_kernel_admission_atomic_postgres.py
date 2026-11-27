from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, transaction
from tests.integration.test_authority_asset_blob_schema_postgres import (
    insert_asset,
    insert_asset_version,
)
from tests.integration.test_command_kernel_definition_postgres import definition_payload


class CommandKernelAdmissionAtomicPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_admission_atomically_persists_all_frozen_evidence(self) -> None:
        project_id = identifier("project")
        definition = {
            **definition_payload(identifier("definition")),
            "approval_policy": {
                "required": True,
                "policy_key": "ops.approval.v1",
            },
        }
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()

        asset_id = identifier("asset")
        asset_version_id = identifier("asset-version")
        with transaction() as connection, connection.cursor() as cursor:
            insert_asset(cursor, asset_id=asset_id, project_id=project_id)
            insert_asset_version(
                cursor,
                asset_version_id=asset_version_id,
                asset_id=asset_id,
            )

        approval = {
            "approval_id": identifier("approval"),
            "status": "APPROVED",
            "project_id": project_id,
            "policy_key": "ops.approval.v1",
        }
        command = {
            "definition_name": definition["name"],
            "definition_version": definition["definition_version"],
            "project_id": project_id,
            "workspace_id": f"workspace:{project_id}",
            "actor_id": "actor-atomic",
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": identifier("idempotency"),
            "trace_id": identifier("trace"),
            "span_id": identifier("span"),
            "correlation_id": identifier("correlation"),
            "causation_id": identifier("causation"),
            "input": {"value": "atomic"},
            "input_assets": [
                {
                    "asset_version_id": asset_version_id,
                    "content_hash": f"hash:{asset_version_id}",
                }
            ],
            "approval": approval,
            "metadata": {"source_task": "task-2-admission"},
        }
        context = AdmissionContext(
            actor_id="actor-atomic",
            permissions=frozenset(definition["permissions"]),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id="admission-build-atomic",
            commit_sha="c" * 40,
        )

        result = admit_command(DATABASE_URL, command, context=context)

        self.assertFalse(result["replayed"])
        operation_id = result["operation_id"]
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    status,
                    actor_id,
                    workspace_id,
                    concurrency_key,
                    trace_id,
                    span_id,
                    correlation_id,
                    causation_id,
                    command_payload,
                    definition_snapshot,
                    completion_contract_snapshot,
                    policy_snapshot,
                    approval_requirement_snapshot,
                    input_asset_snapshot
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            operation = cursor.fetchone()
            self.assertEqual(operation[0], "ADMITTED")
            self.assertEqual(operation[1], context.actor_id)
            self.assertEqual(operation[2], command["workspace_id"])
            self.assertEqual(
                operation[3],
                f"project:{project_id}:ops.echo",
            )
            self.assertEqual(operation[4:8], (
                command["trace_id"],
                command["span_id"],
                command["correlation_id"],
                command["causation_id"],
            ))
            self.assertEqual(operation[8], command["input"])
            self.assertEqual(
                operation[9]["application_build_id"],
                context.application_build_id,
            )
            self.assertEqual(operation[9]["commit_sha"], context.commit_sha)
            self.assertEqual(
                operation[10],
                definition["completion_contract"],
            )
            self.assertEqual(operation[11], definition["policy"])
            self.assertEqual(operation[12]["evidence"], approval)
            self.assertEqual(
                operation[13],
                [
                    {
                        "asset_version_id": asset_version_id,
                        "content_hash": f"hash:{asset_version_id}",
                        "project_id": project_id,
                    }
                ],
            )
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM authority_idempotency_record WHERE operation_id = %s),
                    (SELECT COUNT(*) FROM state_event WHERE aggregate_type = 'authority_operation' AND aggregate_id = %s),
                    (SELECT COUNT(*) FROM audit_log WHERE operation_id = %s AND action = 'authority.operation.admitted'),
                    (
                        SELECT COUNT(*)
                        FROM outbox_event AS outbox
                        JOIN state_event AS event ON event.event_id = outbox.event_id
                        WHERE event.aggregate_type = 'authority_operation'
                          AND event.aggregate_id = %s
                          AND outbox.topic = 'authority.operation.admitted'
                    )
                """,
                [operation_id, operation_id, operation_id, operation_id],
            )
            self.assertEqual(cursor.fetchone(), (1, 1, 1, 1))

    def test_registry_disable_does_not_mutate_frozen_definition_snapshot(self) -> None:
        definition = definition_payload(identifier("definition"))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        project_id = identifier("project")
        command = {
            "definition_name": definition["name"],
            "definition_version": definition["definition_version"],
            "project_id": project_id,
            "workspace_id": f"workspace:{project_id}",
            "actor_id": "actor-frozen",
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": identifier("idempotency"),
            "trace_id": identifier("trace"),
            "span_id": identifier("span"),
            "correlation_id": identifier("correlation"),
            "causation_id": "",
            "input": {"value": "frozen"},
            "input_assets": [],
        }
        context = AdmissionContext(
            actor_id="actor-frozen",
            permissions=frozenset(definition["permissions"]),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id="admission-build-frozen",
            commit_sha="d" * 40,
        )
        result = admit_command(DATABASE_URL, command, context=context)

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_operation_definition
                SET enabled = FALSE
                WHERE name = %s AND definition_version = %s
                """,
                [definition["name"], definition["definition_version"]],
            )
            cursor.execute(
                """
                SELECT definition_snapshot->>'enabled'
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [result["operation_id"], project_id],
            )
            self.assertEqual(cursor.fetchone()[0], "true")


if __name__ == "__main__":
    unittest.main()
