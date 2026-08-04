from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.maintenance import run_maintenance_cycle
from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
    DATABASE_URL,
)


class MaintenanceWorkerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_cycle_expires_attempt_and_outbox_leases_and_marks_timeout(self) -> None:
        project_id = identifier("maintenance-project")
        operation_id = identifier("maintenance-operation")
        attempt_id = identifier("maintenance-attempt")
        lease_id = identifier("maintenance-lease")
        event_id = identifier("maintenance-event")
        outbox_id = identifier("maintenance-outbox")
        definition = identifier("maintenance-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition,
                project_id=project_id,
                status="READY",
            )
            cursor.execute(
                "UPDATE authority_operation SET business_deadline_at=NOW()-INTERVAL '1 second' "
                "WHERE operation_id=%s",
                [operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_attempt(
                    attempt_id,operation_id,attempt_number,status,worker_id,started_at
                ) VALUES (%s,%s,1,'RUNNING','crashed-maintenance-worker',
                          NOW()-INTERVAL '2 minutes')
                """,
                [attempt_id, operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_lease_acquisition(
                    lease_id,attempt_id,owner,fencing_token,acquired_at,expires_at,status
                ) VALUES (%s,%s,'crashed-maintenance-worker',1,
                          NOW()-INTERVAL '2 minutes',NOW()-INTERVAL '1 minute','HELD')
                """,
                [lease_id, attempt_id],
            )
            cursor.execute(
                """
                INSERT INTO state_event(
                    event_id,aggregate_type,aggregate_id,project_id,event_type,
                    event_version,sequence_number,payload
                ) VALUES (%s,'maintenance',%s,%s,'maintenance.probe',1,1,'{}'::jsonb)
                """,
                [event_id, outbox_id, project_id],
            )
            cursor.execute(
                """
                INSERT INTO outbox_event(
                    outbox_id,event_id,project_id,topic,status,claimed_by,claimed_at,
                    lease_expires_at,payload,attempt_count,lease_id,fencing_token,
                    runtime_group
                ) VALUES (%s,%s,%s,'maintenance.probe','claimed','crashed-outbox',
                          NOW()-INTERVAL '2 minutes',NOW()-INTERVAL '1 minute',
                          '{}'::jsonb,1,%s,1,'outbox')
                """,
                [outbox_id, event_id, project_id, f"{outbox_id}:1"],
            )

        result = run_maintenance_cycle(
            DATABASE_URL, actor_id="maintenance-integration-worker", limit=10_000
        )
        self.assertIn(
            lease_id, [item["lease_id"] for item in result["expired_attempt_leases"]]
        )
        recovered = next(
            item for item in result["recovered_outbox"] if item["outbox_id"] == outbox_id
        )
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["fencing_token"], 1)
        self.assertIn(
            operation_id, result["deadline_recovery"]["cancellation_issued"]
        )
        self.assertEqual(result["external_effects_replayed"], 0)


if __name__ == "__main__":
    unittest.main()
