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
        checkpoint = dispatcher.checkpoint(
            claims[0], {"stage": "INTERNAL_DELIVERY_STARTED"}
        )
        self.assertTrue(checkpoint["checkpoint_hash"].startswith("sha256:"))
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
            cursor.execute(
                """
                SELECT status, checkpoint_sequence, result_hash
                FROM authority_outbox_delivery_execution
                WHERE outbox_id=%s AND fencing_token=1
                """,
                [outbox_id],
            )
            execution = cursor.fetchone()
            self.assertEqual(execution[:2], ("SUCCEEDED", 1))
            self.assertTrue(str(execution[2]).startswith("sha256:"))

    def test_expiry_takeover_failure_retry_and_stale_claim_are_fenced(self) -> None:
        project_id = identifier("outbox-recovery-project")
        event_id = identifier("outbox-recovery-event")
        outbox_id = identifier("outbox-recovery")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO state_event(
                    event_id, aggregate_type, aggregate_id, project_id,
                    event_type, event_version, sequence_number, payload
                ) VALUES (%s,'probe',%s,%s,'probe.recovery',1,1,'{}'::jsonb)
                """,
                [event_id, outbox_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event(
                    outbox_id,event_id,project_id,topic,status,payload
                ) VALUES (%s,%s,%s,'probe.recovery','PENDING','{}'::jsonb)
                """,
                [outbox_id, event_id, project_id],
            )

        stale_dispatcher = PostgresOutboxDispatcher(
            DATABASE_URL, worker_id="outbox-stale-worker"
        )
        stale = stale_dispatcher.claim(limit=1, project_id=project_id)[0]
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_event
                SET lease_expires_at=NOW()-INTERVAL '1 second'
                WHERE outbox_id=%s
                """,
                [outbox_id],
            )
        with self.assertRaisesRegex(RuntimeError, "stale"):
            stale_dispatcher.heartbeat(stale)
        recovered = stale_dispatcher.recover_expired_claims(limit=10)
        self.assertEqual(recovered[0]["outbox_id"], outbox_id)

        replacement_dispatcher = PostgresOutboxDispatcher(
            DATABASE_URL, worker_id="outbox-replacement-worker"
        )
        replacement = replacement_dispatcher.claim(limit=1, project_id=project_id)[0]
        self.assertGreater(replacement.fencing_token, stale.fencing_token)
        with self.assertRaisesRegex(RuntimeError, "stale|owned|fencing"):
            stale_dispatcher.deliver(stale)
        failed = replacement_dispatcher.fail(
            replacement,
            {"code": "INTERNAL_CONSUMER_TRANSIENT"},
        )
        self.assertEqual(failed["status"], "failed")

        final_dispatcher = PostgresOutboxDispatcher(
            DATABASE_URL, worker_id="outbox-final-worker"
        )
        final_claim = final_dispatcher.claim(limit=1, project_id=project_id)[0]
        self.assertGreater(final_claim.fencing_token, replacement.fencing_token)
        self.assertTrue(final_dispatcher.deliver(final_claim))

    def test_poison_delivery_dead_letters_at_attempt_limit(self) -> None:
        project_id = identifier("outbox-poison-project")
        event_id = identifier("outbox-poison-event")
        outbox_id = identifier("outbox-poison")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO state_event(
                    event_id, aggregate_type, aggregate_id, project_id,
                    event_type, event_version, sequence_number, payload
                ) VALUES (%s,'probe',%s,%s,'probe.poison',1,1,'{}'::jsonb)
                """,
                [event_id, outbox_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event(
                    outbox_id,event_id,project_id,topic,status,payload,attempt_count
                ) VALUES (%s,%s,%s,'probe.poison','PENDING','{}'::jsonb,4)
                """,
                [outbox_id, event_id, project_id],
            )
        dispatcher = PostgresOutboxDispatcher(
            DATABASE_URL, worker_id="outbox-poison-worker"
        )
        claim = dispatcher.claim(limit=1, project_id=project_id)[0]
        result = dispatcher.fail(claim, {"code": "POISON"})
        self.assertEqual(result["status"], "dead_letter")


if __name__ == "__main__":
    unittest.main()
