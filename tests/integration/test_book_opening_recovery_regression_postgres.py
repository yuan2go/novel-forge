from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_recovery_postgres_support import (
    create_legacy_book_opening_orphan,
)


def test_book_opening_process_loss_converges_and_admits_one_replacement() -> None:
    """The exact pre-closure orphan now converges through formal Authority paths."""

    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()

    assert orphan.cross_layer_state() == (
        "RUNNING",
        "RUNNING",
        "RUNNING",
        "HELD",
        True,
        "CANCELLED",
        "LEASE_LOST",
        "EXPIRED",
        0,
    )

    with pytest.raises(KernelError, match="BOOK_OPENING_RECOVERY_ASSESSMENT_REQUIRED"):
        orphan.opening.resume(
            orphan.opening_run_id,
            expected_version=0,
            principal=orphan.principal,
        )

    takeover = RuntimeJobAuthority(DATABASE_URL).claim(
        runtime_group="book_opening",
        worker_id="legacy-silent-takeover-worker",
        lease_seconds=30,
        job_kinds=("BOOK_OPENING_EXECUTE",),
        project_id=orphan.project_id,
    )
    assert takeover is None

    recovery = orphan.opening.recovery
    loss = recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=f"loss:{orphan.opening_run_id}:1",
        principal=orphan.principal,
    )
    assert loss.disposition == "EXECUTION_LOST"
    converged = recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=f"loss:{orphan.opening_run_id}:1",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert converged.result["opening_lifecycle"] == "FAILED"
    assert converged.result["execution_lifecycle"] == "LOST"
    assert converged.result["recovery_intent_created"] is False
    assert converged.result["provider_invoked"] is False
    assert recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=f"loss:{orphan.opening_run_id}:1",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    ).replayed

    assessed = recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"recover-assess:{orphan.opening_run_id}:1",
        principal=orphan.principal,
    )
    assert assessed.disposition == "PROVEN_NO_EFFECT"
    admitted = recovery.recover(
        assessed.recovery_assessment_id,
        idempotency_key=f"recover:{orphan.opening_run_id}:2",
        reason="replace terminal no-effect semantic evaluation",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert admitted.result["execution_generation"] == 2
    assert admitted.result["replacement_evaluation_operation_id"]
    assert admitted.result["provider_invoked"] is False
    replay = recovery.recover(
        assessed.recovery_assessment_id,
        idempotency_key=f"recover:{orphan.opening_run_id}:2",
        reason="replace terminal no-effect semantic evaluation",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert replay.replayed
    assert replay.result == admitted.result

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   old_execution.lifecycle,old_job.status,old_attempt.status,
                   old_lease.status,old_operation.status,
                   replacement.generation,replacement.predecessor_operation_id,
                   replacement.operation_id,new_job.status,
                   (SELECT COUNT(*) FROM authority_book_opening_recovery_intent
                    WHERE opening_run_id=opening.opening_run_id),
                   (SELECT COUNT(*) FROM authority_external_effect AS effect
                    WHERE effect.operation_id IN (
                        old_operation.operation_id,replacement.operation_id
                    ))
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS old_execution
              ON old_execution.opening_run_id=opening.opening_run_id
             AND old_execution.generation=1
            JOIN authority_runtime_job AS old_job
              ON old_job.runtime_job_id=old_execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS old_attempt
              ON old_attempt.attempt_id=old_execution.current_attempt_id
            JOIN authority_runtime_job_lease AS old_lease
              ON old_lease.lease_id=old_execution.current_lease_id
            JOIN authority_operation AS old_operation
              ON old_operation.operation_id=%s
            JOIN authority_narrative_evaluation_execution AS replacement
              ON replacement.predecessor_operation_id=old_operation.operation_id
             AND replacement.generation=2
            JOIN authority_book_opening_execution AS new_execution
              ON new_execution.opening_execution_id=opening.current_execution_id
             AND new_execution.generation=2
            JOIN authority_runtime_job AS new_job
              ON new_job.runtime_job_id=new_execution.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [orphan.evaluation_operation_id, orphan.opening_run_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    assert tuple(row[:8]) == (
        "ADMITTED",
        2,
        "LOST",
        "FAILED",
        "ABANDONED",
        "EXPIRED",
        "CANCELLED",
        2,
    )
    assert str(row[8]) == orphan.evaluation_operation_id
    assert str(row[9]) == admitted.result["replacement_evaluation_operation_id"]
    assert str(row[10]) == "READY"
    assert int(row[11]) == 1
    # Recovery admission does not execute the replacement worker or Provider.
    assert int(row[12]) == 0
