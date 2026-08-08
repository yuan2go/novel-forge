from __future__ import annotations

import psycopg
import pytest

from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import connect
from tests.integration.authority_postgres_support import (
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)
from tests.integration.capability_pack_postgres_support import (
    DATABASE_URL,
    CapabilityPackPostgresHarness,
)


def test_attempt_snapshot_is_frozen_once_and_shared_by_gateway_and_agent_binding() -> (
    None
):
    harness = CapabilityPackPostgresHarness("pack-attempt-snapshot")
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version_1)
    harness.activate(baseline)
    runtime = harness.run_draft_attempt()

    assert runtime["binding_snapshot_id"] == runtime["snapshot_id"]
    assert runtime["binding_snapshot_hash"] == runtime["snapshot_hash"]
    assert runtime["binding_deployment_id"] == runtime["deployment_id"]
    assert runtime["binding_binding_set_id"] == runtime["binding_set_id"]
    assert runtime["binding_binding_set_hash"] == runtime["binding_set_hash"]
    assert (
        runtime["snapshot_creation_fencing_token"] == runtime["execution_fencing_token"]
    )
    assert runtime["trace_id"] and runtime["span_id"]
    assert runtime["snapshot_payload"]["deployment_id"] == baseline.deployment_id
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*), MIN(resolution_count), MAX(resolution_count)
            FROM authority_attempt_capability_pack_snapshot
            WHERE attempt_id=%s
            """,
            [runtime["attempt_id"]],
        )
        assert uow.cursor.fetchone() == (1, 1, 1)
        uow.cursor.execute(
            """
            SELECT COUNT(*) FROM authority_capability_pack_assignment
            WHERE assignment_id=%s
            """,
            [runtime["snapshot_payload"]["assignment_ref"]],
        )
        assert int(uow.cursor.fetchone()[0]) <= 1
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM audit_log
               WHERE operation_id=%s
                 AND action='authority.capability_pack.attempt_snapshot.frozen'),
              (SELECT COUNT(*) FROM state_event
               WHERE aggregate_id=%s
                 AND event_type='authority.capability_pack.attempt_snapshot.frozen'),
              (SELECT COUNT(*) FROM outbox_event
               WHERE event_id IN (
                    SELECT event_id FROM state_event WHERE aggregate_id=%s
               ) AND topic='authority.capability_pack.attempt_snapshot.frozen')
            """,
            [runtime["operation_id"], runtime["snapshot_id"], runtime["snapshot_id"]],
        )
        assert uow.cursor.fetchone() == (1, 1, 1)
        uow.commit()

    # A restarted worker reuses the immutable record before inspecting the
    # current Activation or requiring the old Lease to remain held.
    reused = CapabilityPackRuntimeResolver(DATABASE_URL).freeze_attempt_snapshot(
        harness.resolution_request(),
        operation_id=runtime["operation_id"],
        attempt_id=runtime["attempt_id"],
        execution_fencing_token=runtime["execution_fencing_token"],
        worker_id="restarted-worker",
    )
    assert reused.snapshot_id == runtime["snapshot_id"]
    assert reused.snapshot_hash == runtime["snapshot_hash"]


def test_operation_retry_reuses_prior_attempt_snapshot_after_activation_changes() -> (
    None
):
    harness = CapabilityPackPostgresHarness("pack-attempt-retry-snapshot")
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version_1)
    harness.activate(baseline)
    definition_name = identifier("retry-snapshot-definition")
    operation_id = identifier("retry-snapshot-operation")
    with transaction() as connection, connection.cursor() as cursor:
        insert_definition(cursor, definition_name)
        insert_operation(
            cursor,
            operation_id=operation_id,
            definition_name=definition_name,
            project_id=harness.project_id,
            status="READY",
        )

    def start(number: int) -> WorkerLeaseCommand:
        created = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=harness.project_id,
            max_attempts=2,
            trace_id=f"trace:retry:{number}",
            correlation_id="correlation:retry",
        )
        attempt_id = str(created["attempt_id"])
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=harness.project_id,
            trace_id=f"trace:retry:{number}",
            correlation_id="correlation:retry",
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=harness.project_id,
            worker_id=f"retry-worker-{number}",
            lease_seconds=60,
            trace_id=f"trace:retry:{number}",
            correlation_id="correlation:retry",
        )
        command = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=harness.project_id,
            worker_id=f"retry-worker-{number}",
            fencing_token=int(lease["fencing_token"]),
            trace_id=f"trace:retry:{number}",
            correlation_id="correlation:retry",
            causation_id=operation_id,
        )
        start_attempt(DATABASE_URL, command)
        return command

    resolver = CapabilityPackRuntimeResolver(DATABASE_URL)
    first_worker = start(1)
    first = resolver.freeze_attempt_snapshot(
        harness.resolution_request(),
        operation_id=operation_id,
        attempt_id=first_worker.attempt_id,
        execution_fencing_token=first_worker.fencing_token,
        worker_id=first_worker.worker_id,
    )
    submit_attempt_failure(
        DATABASE_URL,
        first_worker,
        retryable=True,
        error_code="OUTPUT_SEMANTIC_FAILURE",
        error_message="retry with frozen capability",
        failure_class="retryable",
    )

    version_2 = harness.register_compile_approve("1.1.0", generation=2)
    candidate = harness.deploy(version_2)
    harness.activate(candidate, expected_activation_version=1)
    second_worker = start(2)
    second = resolver.freeze_attempt_snapshot(
        harness.resolution_request(),
        operation_id=operation_id,
        attempt_id=second_worker.attempt_id,
        execution_fencing_token=second_worker.fencing_token,
        worker_id=second_worker.worker_id,
    )

    assert second.snapshot_id != first.snapshot_id
    assert second.snapshot_hash == first.snapshot_hash
    assert second.execution_snapshot == first.execution_snapshot
    assert second.execution_snapshot.deployment_id == baseline.deployment_id
    assert second.execution_snapshot.deployment_id != candidate.deployment_id
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT payload->>'resolution_mode',
                   payload->>'reused_from_snapshot_id',
                   payload->>'reused_from_attempt_id'
            FROM audit_log
            WHERE operation_id=%s
              AND action='authority.capability_pack.attempt_snapshot.frozen'
            ORDER BY created_at DESC LIMIT 1
            """,
            [operation_id],
        )
        assert uow.cursor.fetchone() == (
            "REUSED_OPERATION_RETRY_SNAPSHOT",
            first.snapshot_id,
            first.attempt_id,
        )


def test_rollout_and_rollback_do_not_reassign_historical_runtime_evidence() -> None:
    harness = CapabilityPackPostgresHarness("pack-snapshot-history")
    version_1 = harness.register_compile_approve("1.0.0", generation=1)
    baseline = harness.deploy(version_1)
    harness.activate(baseline)
    historical = harness.run_draft_attempt()

    version_2 = harness.register_compile_approve("1.1.0", generation=2)
    candidate = harness.deploy(version_2)
    rollout_id = f"rollout:{harness.pack_id}"
    harness.execute(
        "capability_pack.rollout.start",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        rollout_id=rollout_id,
        payload={
            "environment": "development",
            "baseline_deployment_id": baseline.deployment_id,
            "candidate_deployment_id": candidate.deployment_id,
            "mode": "FULL",
            "percentage": 100,
            "assignment_key_policy": "BOOK",
        },
    )
    canary = CapabilityPackRuntimeResolver(DATABASE_URL).resolve_active_deployment(
        harness.resolution_request()
    )
    assert canary.deployment_id == candidate.deployment_id
    candidate_runtime = harness.run_draft_attempt(chapter_number=2)
    assert candidate_runtime["deployment_id"] == candidate.deployment_id
    assert candidate_runtime["binding_set_hash"] == candidate.binding_set_hash
    assert candidate_runtime["draft_content"] != historical["draft_content"]
    assert "@v1" in str(historical["draft_content"])
    assert "@v2" in str(candidate_runtime["draft_content"])
    harness.execute(
        "capability_pack.rollout.complete",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        rollout_id=rollout_id,
        expected_activation_version=1,
        payload={"environment": "development", "reason": "fixture promotion"},
    )
    harness.execute(
        "capability_pack.rollback",
        principal=harness.compiler,
        pack_version=version_1.pack_version,
        deployment_id=baseline.deployment_id,
        expected_activation_version=2,
        payload={"environment": "development", "reason": "fixture rollback"},
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT snapshot.deployment_id, snapshot.snapshot_hash,
                   binding.capability_pack_deployment_id,
                   binding.capability_pack_attempt_snapshot_hash
            FROM authority_attempt_capability_pack_snapshot AS snapshot
            JOIN authority_agent_runtime_binding AS binding
              ON binding.capability_pack_attempt_snapshot_id=snapshot.snapshot_id
            WHERE snapshot.snapshot_id=%s
            """,
            [historical["snapshot_id"]],
        )
        assert uow.cursor.fetchone() == (
            baseline.deployment_id,
            historical["snapshot_hash"],
            baseline.deployment_id,
            historical["snapshot_hash"],
        )
        uow.commit()

    metrics_v1 = CapabilityPackAuthorityQuery(DATABASE_URL).usage_metrics(
        baseline.deployment_id, project_id=harness.project_id
    )
    metrics_v2 = CapabilityPackAuthorityQuery(DATABASE_URL).usage_metrics(
        candidate.deployment_id, project_id=harness.project_id
    )
    assert metrics_v1["runtime_binding_count"] == 1
    assert metrics_v2["runtime_binding_count"] == 1
    assert metrics_v1["real_provider_call_evidence_count"] == 0
    assert metrics_v1["real_provider_call_evidence_present"] is False
    assert metrics_v1["provider_vertical_qualification_status"] == "NOT_STARTED"
    assert metrics_v1["production_verified"] is False


def test_postgres_rejects_historical_snapshot_and_runtime_binding_mutation() -> None:
    harness = CapabilityPackPostgresHarness("pack-snapshot-attack")
    version = harness.register_compile_approve("1.0.0", generation=1)
    deployment = harness.deploy(version)
    harness.activate(deployment)
    runtime = harness.run_draft_attempt()
    with connect() as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.IntegrityError):
            cursor.execute(
                """
                UPDATE authority_attempt_capability_pack_snapshot
                SET activation_version=activation_version + 1
                WHERE snapshot_id=%s
                """,
                [runtime["snapshot_id"]],
            )
            connection.commit()
        connection.rollback()
        with pytest.raises(psycopg.DatabaseError):
            cursor.execute(
                """
                UPDATE authority_agent_runtime_binding
                SET capability_pack_binding_set_id='wrong-binding-set'
                WHERE binding_id=%s
                """,
                [runtime["binding_id"]],
            )
            connection.commit()
        connection.rollback()
