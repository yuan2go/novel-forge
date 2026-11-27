from __future__ import annotations

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    expire_attempt_lease,
)
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
    resolve_cancellation,
)
from novel_forge.modules.command_kernel.recovery import (
    RecoverOperationCommand,
    recover_operation,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


def test_abandoned_executing_operation_closes_through_governed_recovery() -> None:
    ensure_migrated()
    project_id = identifier("recovery-project")
    operation_id = identifier("recovery-operation")
    attempt_id = identifier("recovery-attempt")
    lease_id = identifier("recovery-lease")
    definition = identifier("recovery-definition")
    worker_id = "crashed-recovery-worker"
    trace_id = identifier("recovery-trace")
    correlation_id = identifier("recovery-correlation")
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
            "UPDATE authority_operation SET version=2 WHERE operation_id=%s",
            [operation_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_attempt(
                attempt_id,operation_id,attempt_number,status,worker_id,started_at
            ) VALUES (%s,%s,1,'RUNNING',%s,NOW()-INTERVAL '2 minutes')
            """,
            [attempt_id, operation_id, worker_id],
        )
        cursor.execute(
            """
            INSERT INTO authority_lease_acquisition(
                lease_id,attempt_id,owner,fencing_token,acquired_at,
                expires_at,heartbeat_at,status
            ) VALUES (%s,%s,%s,1,NOW()-INTERVAL '2 minutes',
                      NOW()-INTERVAL '1 minute',NOW()-INTERVAL '2 minutes','HELD')
            """,
            [lease_id, attempt_id, worker_id],
        )

    lease_command = WorkerLeaseCommand(
        attempt_id=attempt_id,
        project_id=project_id,
        worker_id=worker_id,
        fencing_token=1,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    expire_attempt_lease(DATABASE_URL, lease_command)

    recovery = RecoverOperationCommand(
        operation_id=operation_id,
        project_id=project_id,
        actor_id="quality-correctness-operator",
        expected_version=2,
        idempotency_key=f"close-abandoned:{operation_id}",
        reason="abandoned worker; expired lease; no ExternalEffect",
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    recovered = recover_operation(DATABASE_URL, recovery)
    assert recovered["action"] == "LEASE_TAKEOVER_VISIBLE"
    assert recovered["replayed"] is False

    cancellation = CancelCommand(
        operation_id=operation_id,
        project_id=project_id,
        actor_id="quality-correctness-operator",
        reason="bounded campaign process ended before Provider dispatch",
        expected_version=2,
        idempotency_key=f"cancel-abandoned:{operation_id}",
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    requested = request_cancellation(DATABASE_URL, cancellation)
    assert requested["status"] == "CANCELLATION_REQUESTED"
    resolved = resolve_cancellation(
        DATABASE_URL,
        operation_id=operation_id,
        project_id=project_id,
        expected_version=3,
        resolution="no_external_effect",
        actor_id="quality-correctness-operator",
        reason="no ExternalEffect exists for the abandoned attempt",
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    assert resolved["status"] == "CANCELLED"
    assert recover_operation(DATABASE_URL, recovery)["replayed"] is True
    assert request_cancellation(DATABASE_URL, cancellation)["replayed"] is True

    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operation.status, operation.version, attempt.status, lease.status,
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id=operation.operation_id),
                   (SELECT COUNT(*) FROM authority_recovery_command
                    WHERE operation_id=operation.operation_id),
                   (SELECT COUNT(*) FROM authority_cancellation_command
                    WHERE operation_id=operation.operation_id)
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE operation.operation_id=%s
            """,
            [operation_id],
        )
        assert cursor.fetchone() == (
            "CANCELLED",
            4,
            "LEASE_LOST",
            "EXPIRED",
            0,
            1,
            1,
        )
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM state_event
            WHERE aggregate_type='authority_operation' AND aggregate_id=%s
              AND event_type='authority.operation.recovery_requested'
            """,
            [operation_id],
        )
        assert cursor.fetchone()[0] == 1
