from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Barrier, Event
from typing import Any, Callable
from unittest.mock import patch

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobClaim
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_recovery_postgres_support import (
    LegacyBookOpeningOrphan,
    create_legacy_book_opening_orphan,
)


class SimulatedRecoveryCrash(BaseException):
    """Cross a recovery transaction boundary without running exception recovery."""


class SimulatedRecoveryResponseLoss(BaseException):
    """The transaction committed, but its caller did not receive the receipt."""


@dataclass(frozen=True, slots=True)
class RecoveryReadyOpening:
    orphan: LegacyBookOpeningOrphan
    assessment_id: str
    recovery_key: str
    reason: str


@pytest.fixture(scope="module", autouse=True)
def _migrations() -> None:
    ensure_migrated()


def _ready_for_recovery(*, suffix: str) -> RecoveryReadyOpening:
    orphan = create_legacy_book_opening_orphan()
    loss_key = f"crash-boundary-loss:{orphan.opening_run_id}:{suffix}"
    loss = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    converged = orphan.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert converged.result["opening_lifecycle"] == "FAILED"
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=(f"crash-boundary-assessment:{orphan.opening_run_id}:{suffix}"),
        principal=orphan.principal,
    )
    assert assessment.disposition == "PROVEN_NO_EFFECT"
    return RecoveryReadyOpening(
        orphan=orphan,
        assessment_id=assessment.recovery_assessment_id,
        recovery_key=f"crash-boundary-recover:{orphan.opening_run_id}:{suffix}",
        reason=f"crash-boundary recovery {suffix}",
    )


def _recover(ready: RecoveryReadyOpening) -> Any:
    orphan = ready.orphan
    return orphan.opening.recovery.recover(
        ready.assessment_id,
        idempotency_key=ready.recovery_key,
        reason=ready.reason,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )


def _claim(
    orphan: LegacyBookOpeningOrphan, *, worker_id: str
) -> RuntimeJobClaim | None:
    return orphan.opening.claim_next_execution(
        worker_id=worker_id,
        lease_seconds=30,
        project_id=orphan.project_id,
    )


def _capture(call: Callable[[], Any]) -> tuple[str, Any]:
    try:
        return "ok", call()
    except KernelError as exc:
        return "error", exc.code


def _recovery_projection(orphan: LegacyBookOpeningOrphan) -> tuple[Any, ...]:
    """Read the durable admission projection, including orphan-job detection."""

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   (SELECT COUNT(*)
                    FROM authority_book_opening_recovery_intent AS intent
                    WHERE intent.opening_run_id=opening.opening_run_id),
                   (SELECT COUNT(*)
                    FROM authority_book_opening_execution AS execution
                    WHERE execution.opening_run_id=opening.opening_run_id
                      AND execution.generation=2),
                   (SELECT COUNT(*)
                    FROM authority_narrative_evaluation_execution AS evaluation
                    WHERE evaluation.project_id=opening.project_id
                      AND evaluation.recovery_intent_id IS NOT NULL),
                   (SELECT COUNT(*)
                    FROM authority_runtime_job AS job
                    WHERE job.subject_kind='BOOK_OPENING_RUN'
                      AND job.subject_id=opening.opening_run_id
                      AND job.dedupe_key=(
                          opening.opening_run_id || ':execution-generation:2'
                      )),
                   (SELECT COUNT(*)
                    FROM authority_book_opening_recovery_receipt AS receipt
                    WHERE receipt.opening_run_id=opening.opening_run_id
                      AND receipt.receipt_kind='RECOVERY_ADMISSION'),
                   (SELECT COUNT(*)
                    FROM authority_external_effect AS effect
                    JOIN authority_narrative_evaluation_execution AS evaluation
                      ON evaluation.operation_id=effect.operation_id
                    WHERE evaluation.project_id=opening.project_id)
            FROM authority_book_opening_run AS opening
            WHERE opening.opening_run_id=%s
            """,
            [orphan.opening_run_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(row)


def _old_runtime_state(orphan: LegacyBookOpeningOrphan) -> tuple[Any, ...]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT job.status,attempt.status,lease.status,
                   execution.lifecycle,opening.lifecycle,
                   COUNT(result.result_id) FILTER (WHERE result.status='SUCCEEDED'),
                   COUNT(result.result_id) FILTER (WHERE result.status='FAILED')
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
            JOIN authority_book_opening_execution AS execution
              ON execution.runtime_job_id=job.runtime_job_id
            JOIN authority_book_opening_run AS opening
              ON opening.current_execution_id=execution.opening_execution_id
            LEFT JOIN authority_runtime_job_result AS result
              ON result.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s
            GROUP BY job.status,attempt.status,lease.status,
                     execution.lifecycle,opening.lifecycle
            """,
            [orphan.runtime_job_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(row)


def _loss_projection(orphan: LegacyBookOpeningOrphan) -> tuple[Any, ...]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,execution.lifecycle,job.status,
                   attempt.status,lease.status,
                   (SELECT COUNT(*)
                    FROM authority_book_opening_recovery_receipt AS receipt
                    WHERE receipt.opening_run_id=opening.opening_run_id
                      AND receipt.receipt_kind='EXECUTION_LOSS_CONVERGENCE'),
                   (SELECT COUNT(*)
                    FROM authority_runtime_job_result AS result
                    WHERE result.runtime_job_id=job.runtime_job_id
                      AND result.status='FAILED'),
                   (SELECT COUNT(*)
                    FROM authority_runtime_job_event AS event
                    WHERE event.runtime_job_id=job.runtime_job_id
                      AND event.event_type='runtime_job.execution_lost')
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=attempt.lease_id
            WHERE opening.opening_run_id=%s
            """,
            [orphan.opening_run_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(row)


def _checkpoint_arguments(orphan: LegacyBookOpeningOrphan) -> dict[str, Any]:
    generation = orphan.planning.require_generation(
        orphan.evaluation_command.generation_operation_id
    )
    return {
        "opening_run_id": orphan.opening_run_id,
        "semantic_work_key": f"planning-generation:{generation['generation_id']}",
        "owning_authority": "STORY_PLANNING",
        "evidence_type": "PLANNING_GENERATION",
        "evidence_id": str(generation["generation_id"]),
        "evidence_version": int(generation["version"]),
        "evidence_hash": str(generation["input_snapshot_hash"]),
    }


def _checkpoint_assessment(orphan: LegacyBookOpeningOrphan, *, suffix: str) -> Any:
    arguments = _checkpoint_arguments(orphan)
    arguments.pop("opening_run_id")
    return orphan.opening.recovery.assess_checkpoint_reconciliation(
        orphan.opening_run_id,
        **arguments,
        idempotency_key=(
            f"crash-boundary-checkpoint-assessment:{orphan.opening_run_id}:{suffix}"
        ),
        principal=orphan.principal,
    )


def _reconcile_checkpoint(
    orphan: LegacyBookOpeningOrphan,
    *,
    assessment_id: str,
    suffix: str,
) -> Any:
    return orphan.opening.recovery.reconcile_checkpoint(
        assessment_id,
        idempotency_key=(
            f"crash-boundary-checkpoint-reconcile:{orphan.opening_run_id}:{suffix}"
        ),
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )


def _checkpoint_projection(orphan: LegacyBookOpeningOrphan) -> tuple[Any, ...]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT current_checkpoint_id,current_checkpoint_sequence,
                   current_checkpoint_hash,
                   (SELECT COUNT(*)
                    FROM authority_book_opening_semantic_checkpoint AS checkpoint
                    WHERE checkpoint.opening_run_id=opening.opening_run_id)
            FROM authority_book_opening_run AS opening
            WHERE opening.opening_run_id=%s
            """,
            [orphan.opening_run_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(row)


def _raise_at_checkpoint(
    expected: str,
    exception_type: type[BaseException] = SimulatedRecoveryCrash,
) -> Callable[[str], None]:
    def inject(actual: str) -> None:
        if actual == expected:
            raise exception_type(f"injected {expected}")

    return inject


def test_expired_heartbeat_vs_execution_loss_has_one_fenced_terminal_winner() -> None:
    orphan = create_legacy_book_opening_orphan()
    loss_key = f"heartbeat-loss-race:{orphan.opening_run_id}"
    assessment = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    barrier = Barrier(2)

    def heartbeat() -> tuple[str, Any]:
        barrier.wait(timeout=10)
        return _capture(
            lambda: RuntimeJobAuthority(DATABASE_URL).heartbeat(
                orphan.outer_claim, lease_seconds=30
            )
        )

    def converge_loss() -> tuple[str, Any]:
        barrier.wait(timeout=10)
        return _capture(
            lambda: orphan.opening.recovery.converge_execution_loss(
                assessment.recovery_assessment_id,
                idempotency_key=loss_key,
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        heartbeat_future = executor.submit(heartbeat)
        loss_future = executor.submit(converge_loss)
        heartbeat_outcome = heartbeat_future.result(timeout=20)
        loss_outcome = loss_future.result(timeout=20)

    assert heartbeat_outcome == ("error", "RUNTIME_JOB_FENCE_STALE")
    assert loss_outcome[0] == "ok"
    assert loss_outcome[1].result["execution_lifecycle"] == "LOST"
    assert _old_runtime_state(orphan) == (
        "FAILED",
        "ABANDONED",
        "EXPIRED",
        "LOST",
        "FAILED",
        0,
        1,
    )


def test_stale_executor_probe_blocks_all_semantic_work_after_loss_convergence() -> None:
    orphan = create_legacy_book_opening_orphan()
    runtime_jobs = RuntimeJobAuthority(DATABASE_URL)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()+INTERVAL '30 seconds'
            WHERE lease_id=%s
            """,
            [orphan.outer_claim.lease_id],
        )
        uow.commit()
    expected_version = int(orphan.opening.require(orphan.opening_run_id)["version"])
    invoked = False

    def lose_fence_before_next_semantic_stage() -> None:
        nonlocal invoked
        if not invoked:
            invoked = True
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    UPDATE authority_runtime_job_lease
                    SET lease_expires_at=
                        transaction_timestamp()-INTERVAL '1 second'
                    WHERE lease_id=%s
                    """,
                    [orphan.outer_claim.lease_id],
                )
                uow.commit()
            loss_key = f"stale-executor-probe:{orphan.opening_run_id}"
            assessment = orphan.opening.recovery.assess_execution_loss(
                orphan.opening_run_id,
                idempotency_key=loss_key,
                principal=orphan.principal,
            )
            orphan.opening.recovery.converge_execution_loss(
                assessment.recovery_assessment_id,
                idempotency_key=loss_key,
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )
        runtime_jobs.assert_live(orphan.outer_claim)

    before = _recovery_projection(orphan)
    with pytest.raises(KernelError) as stale:
        orphan.opening.execute_run(
            orphan.opening_run_id,
            expected_version=expected_version,
            runtime_claim=orphan.outer_claim,
            principal=orphan.principal,
            execution_probe=lose_fence_before_next_semantic_stage,
        )
    assert stale.value.code == "RUNTIME_JOB_FENCE_STALE"
    after = _recovery_projection(orphan)
    assert invoked is True
    assert before[-1] == after[-1] == 0
    assert after[:2] == ("FAILED", 1)


def test_loss_sweeper_continues_after_one_candidate_wins_a_heartbeat_race() -> None:
    raced = create_legacy_book_opening_orphan()
    expired = create_legacy_book_opening_orphan()
    recovery = raced.opening.recovery
    original_assess = recovery.assess_execution_loss

    def assess_or_simulate_race(opening_run_id: str, **kwargs: object) -> Any:
        if opening_run_id == expired.opening_run_id:
            return original_assess(opening_run_id, **kwargs)
        raise KernelError(
            "BOOK_OPENING_EXECUTION_STILL_VALID",
            "simulated heartbeat won after the bounded sweep scan",
        )

    sweeper = Principal(
        principal_id="book-opening-loss-sweeper",
        principal_type=PrincipalType.SYSTEM_SCHEDULER,
        permissions=frozenset({"book.authority.execute"}),
        project_scope=frozenset({"*"}),
        authentication_source="postgres-recovery-fixture",
    )
    with patch.object(recovery, "assess_execution_loss", new=assess_or_simulate_race):
        results = recovery.scan_expired_executions(principal=sweeper, limit=100)

    assert [item["opening_run_id"] for item in results] == [expired.opening_run_id]
    assert raced.opening.require(raced.opening_run_id)["lifecycle"] == "RUNNING"
    assert expired.opening.require(expired.opening_run_id)["lifecycle"] == "FAILED"


def test_completion_vs_execution_loss_cannot_publish_a_stale_success() -> None:
    orphan = create_legacy_book_opening_orphan()
    loss_key = f"completion-loss-race:{orphan.opening_run_id}"
    assessment = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    barrier = Barrier(2)

    def complete() -> tuple[str, Any]:
        barrier.wait(timeout=10)
        return _capture(
            lambda: RuntimeJobAuthority(DATABASE_URL).complete(
                orphan.outer_claim, {"opening_run_id": orphan.opening_run_id}
            )
        )

    def converge_loss() -> tuple[str, Any]:
        barrier.wait(timeout=10)
        return _capture(
            lambda: orphan.opening.recovery.converge_execution_loss(
                assessment.recovery_assessment_id,
                idempotency_key=loss_key,
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion_future = executor.submit(complete)
        loss_future = executor.submit(converge_loss)
        completion_outcome = completion_future.result(timeout=20)
        loss_outcome = loss_future.result(timeout=20)

    assert completion_outcome == (
        "error",
        "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED",
    )
    assert loss_outcome[0] == "ok"
    assert _old_runtime_state(orphan) == (
        "FAILED",
        "ABANDONED",
        "EXPIRED",
        "LOST",
        "FAILED",
        0,
        1,
    )


def test_recovered_runtime_job_claim_vs_claim_admits_one_attempt() -> None:
    ready = _ready_for_recovery(suffix="claim-claim")
    admitted = _recover(ready)
    barrier = Barrier(2)

    def claim(ordinal: int) -> RuntimeJobClaim | None:
        barrier.wait(timeout=10)
        return _claim(
            ready.orphan,
            worker_id=f"recovered-opening-claim-worker-{ordinal}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(executor.map(claim, (1, 2)))

    winners = tuple(item for item in claims if item is not None)
    assert len(winners) == 1
    assert winners[0].runtime_job_id == admitted.result["runtime_job_id"]
    job = RuntimeJobAuthority(DATABASE_URL).get(admitted.result["runtime_job_id"])
    assert (job["status"], job["attempt_count"], job["lease_loss_policy"]) == (
        "CLAIMED",
        1,
        "AUTHORITY_CONVERGENCE_REQUIRED",
    )


def test_process_loss_after_coordinated_claim_before_start_converges_bound_execution() -> (
    None
):
    ready = _ready_for_recovery(suffix="bound-before-start-loss")
    admitted = _recover(ready)
    orphan = ready.orphan
    claim = _claim(orphan, worker_id="bound-before-start-worker")
    assert claim is not None
    assert claim.runtime_job_id == admitted.result["runtime_job_id"]

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,execution.lifecycle,job.status,
                   attempt.status,lease.status
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=execution.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=execution.current_lease_id
            WHERE opening.opening_run_id=%s
            """,
            [orphan.opening_run_id],
        )
        assert uow.cursor.fetchone() == (
            "ADMITTED",
            "BOUND",
            "CLAIMED",
            "CLAIMED",
            "HELD",
        )
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [claim.lease_id],
        )
        uow.commit()

    loss_key = f"bound-before-start-loss:{orphan.opening_run_id}"
    assessment = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    converged = orphan.opening.recovery.converge_execution_loss(
        assessment.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert converged.result["opening_lifecycle"] == "FAILED"
    assert converged.result["execution_lifecycle"] == "LOST"
    assert converged.result["recovery_intent_created"] is False
    assert _loss_projection(orphan) == (
        "FAILED",
        "LOST",
        "FAILED",
        "ABANDONED",
        "EXPIRED",
        2,
        1,
        1,
    )
    assert _recovery_projection(orphan)[-1] == 0


def test_recovery_vs_claim_never_exposes_a_partial_successor() -> None:
    ready = _ready_for_recovery(suffix="recovery-claim")
    barrier = Barrier(2)

    def recover() -> Any:
        barrier.wait(timeout=10)
        return _recover(ready)

    def claim() -> RuntimeJobClaim | None:
        barrier.wait(timeout=10)
        return _claim(ready.orphan, worker_id="recovery-race-worker")

    with ThreadPoolExecutor(max_workers=2) as executor:
        recover_future = executor.submit(recover)
        claim_future = executor.submit(claim)
        receipt = recover_future.result(timeout=20)
        raced_claim = claim_future.result(timeout=20)

    winner = raced_claim or _claim(
        ready.orphan, worker_id="recovery-race-worker-after-commit"
    )
    assert winner is not None
    assert winner.runtime_job_id == receipt.result["runtime_job_id"]
    run = ready.orphan.opening.require(ready.orphan.opening_run_id)
    assert (run["lifecycle"], run["current_execution_generation"]) == (
        "ADMITTED",
        2,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT execution.opening_execution_id,execution.generation,
                   execution.runtime_job_id,job.status,job.current_attempt_id,
                   job.current_fencing_token
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_execution_id=opening.current_execution_id
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            WHERE opening.opening_run_id=%s
            """,
            [ready.orphan.opening_run_id],
        )
        binding = uow.cursor.fetchone()
    assert binding is not None
    assert tuple(binding[:4]) == (
        receipt.result["opening_execution_id"],
        2,
        receipt.result["runtime_job_id"],
        "CLAIMED",
    )
    assert tuple(binding[4:]) == (winner.attempt_id, winner.fencing_token)


@pytest.mark.parametrize("drift", ("assessment", "reason", "principal"))
def test_recovery_replay_rejects_changed_authorization_inputs(drift: str) -> None:
    ready = _ready_for_recovery(suffix=f"replay-drift-{drift}")
    orphan = ready.orphan
    alternate_assessment = None
    if drift == "assessment":
        alternate_assessment = orphan.opening.recovery.assess_recovery(
            orphan.opening_run_id,
            idempotency_key=(
                f"crash-boundary-assessment:{orphan.opening_run_id}:alternate"
            ),
            principal=orphan.principal,
        )

    committed = _recover(ready)
    assert committed.replayed is False
    changed_assessment_id = (
        alternate_assessment.recovery_assessment_id
        if alternate_assessment is not None
        else ready.assessment_id
    )
    changed_reason = f"{ready.reason}:changed" if drift == "reason" else ready.reason
    changed_principal = (
        replace(
            orphan.principal,
            principal_id=f"{orphan.principal.principal_id}:alternate-authorizer",
        )
        if drift == "principal"
        else orphan.principal
    )

    with pytest.raises(KernelError) as conflict:
        orphan.opening.recovery.recover(
            changed_assessment_id,
            idempotency_key=ready.recovery_key,
            reason=changed_reason,
            principal=changed_principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
    assert conflict.value.code == "BOOK_OPENING_RECOVERY_IDEMPOTENCY_CONFLICT"

    exact_replay = _recover(ready)
    assert exact_replay.replayed is True
    assert exact_replay.recovery_receipt_id == committed.recovery_receipt_id
    assert _recovery_projection(orphan) == (
        "ADMITTED",
        2,
        1,
        1,
        1,
        1,
        1,
        0,
    )


def test_claim_vs_abort_leaves_no_executable_opening_job() -> None:
    ready = _ready_for_recovery(suffix="claim-abort")
    admitted = _recover(ready)
    opening_version = int(
        ready.orphan.opening.require(ready.orphan.opening_run_id)["version"]
    )
    barrier = Barrier(2)
    claim_committed = Event()

    def claim() -> tuple[str, Any]:
        barrier.wait(timeout=10)
        outcome = _capture(lambda: _claim(ready.orphan, worker_id="claim-abort-worker"))
        claim_committed.set()
        return outcome

    def abort() -> tuple[str, Any]:
        barrier.wait(timeout=10)
        assert claim_committed.wait(timeout=10)
        return _capture(
            lambda: ready.orphan.opening.abort(
                ready.orphan.opening_run_id,
                expected_version=opening_version,
                principal=ready.orphan.principal,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_future = executor.submit(claim)
        abort_future = executor.submit(abort)
        claim_outcome = claim_future.result(timeout=20)
        abort_outcome = abort_future.result(timeout=20)

    assert abort_outcome[0] == "ok"
    assert (
        ready.orphan.opening.require(ready.orphan.opening_run_id)["lifecycle"]
        == "ABORTED"
    )
    job = RuntimeJobAuthority(DATABASE_URL).get(admitted.result["runtime_job_id"])
    assert job["status"] == "CANCELLED"
    assert claim_outcome[0] == "ok" and claim_outcome[1] is not None
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT execution.lifecycle,attempt.status,lease.status,
                   operation.status,evaluation.lifecycle,
                   (SELECT COUNT(*) FROM authority_external_effect AS effect
                    WHERE effect.operation_id=operation.operation_id)
            FROM authority_book_opening_execution AS execution
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=execution.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.lease_id=execution.current_lease_id
            JOIN authority_operation AS operation
              ON operation.operation_id=%s
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            WHERE execution.opening_execution_id=%s
            """,
            [
                admitted.result["replacement_evaluation_operation_id"],
                admitted.result["opening_execution_id"],
            ],
        )
        terminal = uow.cursor.fetchone()
    assert terminal == (
        "ABORTED",
        "ABANDONED",
        "RELEASED",
        "CANCELLED",
        "CANCELLED",
        0,
    )
    with pytest.raises(KernelError, match="RUNTIME_JOB_FENCE_STALE"):
        RuntimeJobAuthority(DATABASE_URL).heartbeat(claim_outcome[1], lease_seconds=30)


@pytest.mark.parametrize(
    "checkpoint",
    (
        "after_recovery_intent",
        "after_replacement_generation",
        "after_recovery_runtime_job_creation",
        "after_recovery_execution_creation",
        "after_recovery_opening_transition",
        "before_recovery_receipt",
        "after_recovery_receipt",
        "after_recovery_outbox",
    ),
)
def test_recovery_admission_rolls_back_every_pure_database_write(
    checkpoint: str,
) -> None:
    ready = _ready_for_recovery(suffix=checkpoint)
    recovery = ready.orphan.opening.recovery

    with patch.object(
        recovery,
        "fault_injector",
        new=_raise_at_checkpoint(checkpoint),
    ):
        with pytest.raises(SimulatedRecoveryCrash, match=checkpoint):
            _recover(ready)

    assert _recovery_projection(ready.orphan) == (
        "FAILED",
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    admitted = _recover(ready)
    assert admitted.result["execution_generation"] == 2
    assert admitted.result["provider_invoked"] is False
    assert _recovery_projection(ready.orphan) == (
        "ADMITTED",
        2,
        1,
        1,
        1,
        1,
        1,
        0,
    )


@pytest.mark.parametrize(
    "checkpoint",
    (
        "after_execution_loss_runtime_terminalization",
        "after_execution_loss_transition",
        "after_execution_loss_opening_failure",
        "after_execution_loss_receipt",
        "after_execution_loss_outbox",
    ),
)
def test_execution_loss_convergence_rolls_back_as_one_authority_unit(
    checkpoint: str,
) -> None:
    orphan = create_legacy_book_opening_orphan()
    recovery = orphan.opening.recovery
    loss_key = f"loss-crash-boundary:{orphan.opening_run_id}:{checkpoint}"
    assessment = recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )

    with patch.object(
        recovery,
        "fault_injector",
        new=_raise_at_checkpoint(checkpoint),
    ):
        with pytest.raises(SimulatedRecoveryCrash, match=checkpoint):
            recovery.converge_execution_loss(
                assessment.recovery_assessment_id,
                idempotency_key=loss_key,
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )

    assert _loss_projection(orphan) == (
        "RUNNING",
        "RUNNING",
        "RUNNING",
        "RUNNING",
        "HELD",
        0,
        0,
        0,
    )

    converged = recovery.converge_execution_loss(
        assessment.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert converged.result["provider_invoked"] is False
    assert _loss_projection(orphan) == (
        "FAILED",
        "LOST",
        "FAILED",
        "ABANDONED",
        "EXPIRED",
        1,
        1,
        1,
    )


@pytest.mark.parametrize(
    "checkpoint",
    ("after_checkpoint_append", "after_checkpoint_projection"),
)
def test_checkpoint_append_and_projection_share_one_rollback_boundary(
    checkpoint: str,
) -> None:
    ready = _ready_for_recovery(suffix=checkpoint)
    orphan = ready.orphan
    assessment = _checkpoint_assessment(orphan, suffix=checkpoint)

    with patch.object(
        orphan.opening.recovery,
        "fault_injector",
        new=_raise_at_checkpoint(checkpoint),
    ):
        with pytest.raises(SimulatedRecoveryCrash, match=checkpoint):
            _reconcile_checkpoint(
                orphan,
                assessment_id=assessment.recovery_assessment_id,
                suffix=checkpoint,
            )

    assert _checkpoint_projection(orphan) == (None, 0, "", 0)
    receipt = _reconcile_checkpoint(
        orphan,
        assessment_id=assessment.recovery_assessment_id,
        suffix=checkpoint,
    )
    checkpoint_result = receipt.result
    assert receipt.replayed is False
    assert checkpoint_result["replayed"] is False
    assert _checkpoint_projection(orphan) == (
        checkpoint_result["checkpoint_id"],
        1,
        checkpoint_result["checkpoint_hash"],
        1,
    )
    replay = _reconcile_checkpoint(
        orphan,
        assessment_id=assessment.recovery_assessment_id,
        suffix=checkpoint,
    )
    assert replay.replayed is True
    assert replay.result == checkpoint_result


def test_recovery_commit_then_response_loss_replays_the_single_durable_receipt() -> (
    None
):
    ready = _ready_for_recovery(suffix="commit-response-loss")
    with patch.object(
        ready.orphan.opening.recovery,
        "fault_injector",
        new=_raise_at_checkpoint(
            "after_recovery_commit_before_response",
            SimulatedRecoveryResponseLoss,
        ),
    ):
        with pytest.raises(
            SimulatedRecoveryResponseLoss,
            match="after_recovery_commit_before_response",
        ):
            _recover(ready)

    replay = _recover(ready)
    assert replay.replayed is True
    assert replay.result["execution_generation"] == 2
    assert replay.result["provider_invoked"] is False
    assert _recovery_projection(ready.orphan) == (
        "ADMITTED",
        2,
        1,
        1,
        1,
        1,
        1,
        0,
    )


def test_loss_commit_then_response_loss_replays_the_single_durable_receipt() -> None:
    orphan = create_legacy_book_opening_orphan()
    recovery = orphan.opening.recovery
    loss_key = f"loss-commit-response-loss:{orphan.opening_run_id}"
    assessment = recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    with patch.object(
        recovery,
        "fault_injector",
        new=_raise_at_checkpoint(
            "after_execution_loss_commit_before_response",
            SimulatedRecoveryResponseLoss,
        ),
    ):
        with pytest.raises(
            SimulatedRecoveryResponseLoss,
            match="after_execution_loss_commit_before_response",
        ):
            recovery.converge_execution_loss(
                assessment.recovery_assessment_id,
                idempotency_key=loss_key,
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )

    replay = recovery.converge_execution_loss(
        assessment.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert replay.replayed is True
    assert replay.result["provider_invoked"] is False
    assert _loss_projection(orphan) == (
        "FAILED",
        "LOST",
        "FAILED",
        "ABANDONED",
        "EXPIRED",
        1,
        1,
        1,
    )


def test_checkpoint_commit_then_response_loss_replays_the_durable_cursor() -> None:
    ready = _ready_for_recovery(suffix="checkpoint-commit-response-loss")
    orphan = ready.orphan
    suffix = "checkpoint-commit-response-loss"
    assessment = _checkpoint_assessment(orphan, suffix=suffix)
    with patch.object(
        orphan.opening.recovery,
        "fault_injector",
        new=_raise_at_checkpoint(
            "after_checkpoint_commit_before_response",
            SimulatedRecoveryResponseLoss,
        ),
    ):
        with pytest.raises(
            SimulatedRecoveryResponseLoss,
            match="after_checkpoint_commit_before_response",
        ):
            _reconcile_checkpoint(
                orphan,
                assessment_id=assessment.recovery_assessment_id,
                suffix=suffix,
            )

    replay = _reconcile_checkpoint(
        orphan,
        assessment_id=assessment.recovery_assessment_id,
        suffix=suffix,
    )
    assert replay.replayed is True
    assert _checkpoint_projection(orphan) == (
        replay.result["checkpoint_id"],
        1,
        replay.result["checkpoint_hash"],
        1,
    )
