from __future__ import annotations

import unittest

from novel_forge.workers.outbox_authority import PostgresOutboxDispatcher
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class OutboxAuthorityWorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_claim_delivery_and_replay_have_one_durable_receipt(self) -> None:
        project_id = identifier("outbox-project")
        event_id = identifier("outbox-event")
        outbox_id = identifier("outbox")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO state_event(
                    event_id, aggregate_type, aggregate_id, project_id,
                    event_type, event_version, sequence_number,
                    correlation_id, causation_id, payload
                ) VALUES (%s,'probe',%s,%s,'probe.created',1,1,'','','{}'::jsonb)
                """,
                [event_id, outbox_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event(
                    outbox_id,event_id,project_id,topic,status,payload
                ) VALUES (%s,%s,%s,'probe.created','PENDING','{}'::jsonb)
                """,
                [outbox_id, event_id, project_id],
            )

        dispatcher = PostgresOutboxDispatcher(
            DATABASE_URL, worker_id="outbox-integration-worker"
        )
        claims = dispatcher.claim(limit=10, project_id=project_id)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].runtime_group, "outbox")
        self.assertEqual(claims[0].fencing_token, 1)
        self.assertTrue(claims[0].lease_id.endswith(":1"))
        self.assertTrue(dispatcher.deliver(claims[0]))
        self.assertFalse(dispatcher.deliver(claims[0]))

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, published_at IS NOT NULL, acked_at IS NOT NULL,
                       lease_id, fencing_token, runtime_group
                FROM outbox_event WHERE outbox_id=%s
                """,
                [outbox_id],
            )
            row = cursor.fetchone()
            self.assertEqual(row[:3], ("acked", True, True))
            self.assertEqual(row[3:], (claims[0].lease_id, 1, "outbox"))
            cursor.execute(
                """
                SELECT COUNT(*) FROM outbox_consumer_delivery
                WHERE consumer_name='authority-internal-event-bus' AND event_id=%s
                """,
                [event_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
