from __future__ import annotations

import time
import unittest

import psycopg

from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


ACTIVE_ATTEMPT_STATES = (
    "CREATED",
    "QUEUED",
    "LEASED",
    "RUNNING",
    "CHECKPOINTED",
    "RESULT_SUBMITTED",
)


def insert_attempt(
    cursor: psycopg.Cursor,
    *,
    attempt_id: str,
    operation_id: str,
    attempt_number: int,
    status: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO authority_attempt (
            attempt_id,
            operation_id,
            attempt_number,
            status
        )
        VALUES (%s, %s, %s, %s)
        """,
        [attempt_id, operation_id, attempt_number, status],
    )


class AuthorityAttemptLeaseSchemaPostgresTests(unittest.TestCase):
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
                status="READY",
            )
        return operation

    def test_invalid_attempt_status_is_rejected(self) -> None:
        operation = self._operation()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_attempt(
                    cursor,
                    attempt_id=identifier("attempt"),
                    operation_id=operation,
                    attempt_number=1,
                    status="NOT_AN_ATTEMPT_STATE",
                )

    def test_attempt_number_must_be_next_monotonic_value(self) -> None:
        operation = self._operation()
        with transaction() as connection, connection.cursor() as cursor:
            insert_attempt(
                cursor,
                attempt_id=identifier("attempt-1"),
                operation_id=operation,
                attempt_number=1,
                status="SUCCEEDED",
            )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_attempt(
                    cursor,
                    attempt_id=identifier("attempt-3"),
                    operation_id=operation,
                    attempt_number=3,
                    status="CREATED",
                )

    def test_operation_has_at_most_one_active_attempt(self) -> None:
        for first_status in ACTIVE_ATTEMPT_STATES:
            with self.subTest(first_status=first_status):
                operation = self._operation()
                with transaction() as connection, connection.cursor() as cursor:
                    insert_attempt(
                        cursor,
                        attempt_id=identifier("attempt-1"),
                        operation_id=operation,
                        attempt_number=1,
                        status=first_status,
                    )
                with self.assertRaises(psycopg.errors.UniqueViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        insert_attempt(
                            cursor,
                            attempt_id=identifier("attempt-2"),
                            operation_id=operation,
                            attempt_number=2,
                            status="CREATED",
                        )

    def test_active_lease_blocks_second_acquisition(self) -> None:
        operation = self._operation()
        attempt = identifier("attempt")
        with transaction() as connection, connection.cursor() as cursor:
            insert_attempt(
                cursor,
                attempt_id=attempt,
                operation_id=operation,
                attempt_number=1,
                status="QUEUED",
            )
            cursor.execute(
                "SELECT fencing_token FROM authority_acquire_attempt_lease(%s, %s, %s, %s)",
                [identifier("lease-1"), attempt, "worker-a", 30],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM authority_acquire_attempt_lease(%s, %s, %s, %s)",
                    [identifier("lease-2"), attempt, "worker-b", 30],
                )

    def test_expired_lease_is_taken_over_with_next_fencing_token_and_history(self) -> None:
        operation = self._operation()
        attempt = identifier("attempt")
        first_lease = identifier("lease-1")
        second_lease = identifier("lease-2")
        with transaction() as connection, connection.cursor() as cursor:
            insert_attempt(
                cursor,
                attempt_id=attempt,
                operation_id=operation,
                attempt_number=1,
                status="QUEUED",
            )
            cursor.execute(
                "SELECT fencing_token FROM authority_acquire_attempt_lease(%s, %s, %s, %s)",
                [first_lease, attempt, "worker-a", 1],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
        time.sleep(1.05)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT fencing_token FROM authority_acquire_attempt_lease(%s, %s, %s, %s)",
                [second_lease, attempt, "worker-b", 30],
            )
            self.assertEqual(cursor.fetchone()[0], 2)
            cursor.execute(
                """
                SELECT lease_id, fencing_token, status
                FROM authority_lease_acquisition
                WHERE attempt_id = %s
                ORDER BY fencing_token
                """,
                [attempt],
            )
            self.assertEqual(
                cursor.fetchall(),
                [(first_lease, 1, "EXPIRED"), (second_lease, 2, "HELD")],
            )

    def test_non_monotonic_fencing_token_is_rejected(self) -> None:
        operation = self._operation()
        attempt = identifier("attempt")
        with transaction() as connection, connection.cursor() as cursor:
            insert_attempt(
                cursor,
                attempt_id=attempt,
                operation_id=operation,
                attempt_number=1,
                status="QUEUED",
            )
            cursor.execute(
                "SELECT * FROM authority_acquire_attempt_lease(%s, %s, %s, %s)",
                [identifier("lease-1"), attempt, "worker-a", 30],
            )
            cursor.execute(
                """
                UPDATE authority_lease_acquisition
                SET status = 'RELEASED', released_at = NOW(), release_reason = 'test'
                WHERE attempt_id = %s
                """,
                [attempt],
            )
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO authority_lease_acquisition (
                        lease_id,
                        attempt_id,
                        owner,
                        fencing_token,
                        expires_at,
                        status
                    )
                    VALUES (%s, %s, 'worker-b', 3, NOW() + INTERVAL '30 seconds', 'HELD')
                    """,
                    [identifier("lease-3"), attempt],
                )


if __name__ == "__main__":
    unittest.main()
