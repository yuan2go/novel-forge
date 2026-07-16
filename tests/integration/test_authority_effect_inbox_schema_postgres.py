from __future__ import annotations

import unittest

import psycopg

from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


def insert_effect(
    cursor: psycopg.Cursor,
    *,
    external_effect_id: str,
    operation_id: str,
    status: str = "READY",
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_external_effect (
            external_effect_id,
            operation_id,
            project_id,
            effect_type,
            stable_idempotency_key,
            status,
            request_hash
        )
        SELECT %s, %s, operation.project_id, 'publisher.submit', %s, %s, %s
        FROM authority_operation AS operation
        WHERE operation.operation_id = %s
        """,
        [
            external_effect_id,
            operation_id,
            external_effect_id,
            status,
            f"hash:{external_effect_id}",
            operation_id,
        ],
    )


def insert_dispatch(
    cursor: psycopg.Cursor,
    *,
    dispatch_id: str,
    external_effect_id: str,
    generation: int = 1,
    status: str = "CREATED",
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_external_effect_dispatch (
            dispatch_id,
            external_effect_id,
            generation,
            status,
            payload_hash
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        [dispatch_id, external_effect_id, generation, status, f"hash:{dispatch_id}"],
    )


class AuthorityEffectInboxSchemaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def _operation(self) -> str:
        definition = identifier("definition")
        operation = identifier("operation")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation,
                definition_name=definition,
                project_id=identifier("project"),
            )
        return operation

    def test_effect_dispatch_and_migration_statuses_reject_unknown_values(self) -> None:
        operation = self._operation()
        cases = ("effect", "dispatch", "migration")
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        if case == "effect":
                            insert_effect(
                                cursor,
                                external_effect_id=identifier("effect"),
                                operation_id=operation,
                                status="UNKNOWN_EFFECT_STATE",
                            )
                        elif case == "dispatch":
                            effect = identifier("effect")
                            insert_effect(
                                cursor,
                                external_effect_id=effect,
                                operation_id=operation,
                            )
                            insert_dispatch(
                                cursor,
                                dispatch_id=identifier("dispatch"),
                                external_effect_id=effect,
                                status="UNKNOWN_DISPATCH_STATE",
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO authority_migration_run (
                                    migration_run_id,
                                    source_kind,
                                    source_hash,
                                    status,
                                    report
                                )
                                VALUES (%s, 'frozen_json', %s, 'UNKNOWN_MIGRATION_STATE', '{}'::jsonb)
                                """,
                                [identifier("migration"), identifier("hash")],
                            )

    def test_dispatch_generation_is_unique_per_effect(self) -> None:
        operation = self._operation()
        effect = identifier("effect")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_effect(cursor, external_effect_id=effect, operation_id=operation)
                insert_dispatch(
                    cursor,
                    dispatch_id=identifier("dispatch-1"),
                    external_effect_id=effect,
                )
                insert_dispatch(
                    cursor,
                    dispatch_id=identifier("dispatch-2"),
                    external_effect_id=effect,
                )

    def test_inbox_same_hash_replays_and_different_hash_records_conflict_alert(self) -> None:
        consumer = identifier("consumer")
        message = identifier("message")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT disposition FROM authority_record_inbox_message(%s, %s, %s, %s::jsonb)",
                [consumer, message, "hash:one", '{"accepted":true}'],
            )
            self.assertEqual(cursor.fetchone()[0], "RECORDED")
            cursor.execute(
                "SELECT disposition FROM authority_record_inbox_message(%s, %s, %s, %s::jsonb)",
                [consumer, message, "hash:one", '{"ignored":true}'],
            )
            self.assertEqual(cursor.fetchone()[0], "REPLAY")
            cursor.execute(
                "SELECT disposition FROM authority_record_inbox_message(%s, %s, %s, %s::jsonb)",
                [consumer, message, "hash:two", '{"ignored":true}'],
            )
            self.assertEqual(cursor.fetchone()[0], "CONFLICT")
            cursor.execute(
                """
                SELECT inbox.payload_hash, inbox.outcome, COUNT(conflict.conflict_id)
                FROM authority_inbox_message AS inbox
                LEFT JOIN authority_inbox_conflict AS conflict
                  ON conflict.consumer_name = inbox.consumer_name
                 AND conflict.message_id = inbox.message_id
                WHERE inbox.consumer_name = %s AND inbox.message_id = %s
                GROUP BY inbox.payload_hash, inbox.outcome
                """,
                [consumer, message],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("hash:one", {"accepted": True}, 1),
            )

    def test_receipt_is_unique_within_provider_scope_and_preserves_evidence(self) -> None:
        operation = self._operation()
        effect = identifier("effect")
        first_dispatch = identifier("dispatch-1")
        second_dispatch = identifier("dispatch-2")
        receipt = identifier("receipt")
        with transaction() as connection, connection.cursor() as cursor:
            insert_effect(cursor, external_effect_id=effect, operation_id=operation)
            insert_dispatch(
                cursor,
                dispatch_id=first_dispatch,
                external_effect_id=effect,
                generation=1,
            )
            insert_dispatch(
                cursor,
                dispatch_id=second_dispatch,
                external_effect_id=effect,
                generation=2,
            )
            cursor.execute(
                """
                INSERT INTO authority_external_receipt (
                    provider,
                    receipt_id,
                    dispatch_id,
                    payload_hash
                )
                VALUES ('publisher-a', %s, %s, 'hash:receipt')
                RETURNING provider, receipt_id, dispatch_id, payload_hash, received_at
                """,
                [receipt, first_dispatch],
            )
            row = cursor.fetchone()
            self.assertEqual(row[:4], ("publisher-a", receipt, first_dispatch, "hash:receipt"))
            self.assertIsNotNone(row[4])
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO authority_external_receipt (
                        provider,
                        receipt_id,
                        dispatch_id,
                        payload_hash
                    )
                    VALUES ('publisher-a', %s, %s, 'hash:conflict')
                    """,
                    [receipt, second_dispatch],
                )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_external_receipt (
                    provider,
                    receipt_id,
                    dispatch_id,
                    payload_hash
                )
                VALUES ('publisher-b', %s, %s, 'hash:other-provider')
                """,
                [receipt, second_dispatch],
            )


if __name__ == "__main__":
    unittest.main()
