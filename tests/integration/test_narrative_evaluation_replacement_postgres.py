from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from unittest.mock import patch

import psycopg
import pytest

from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    mark_external_effect_unknown,
    plan_external_effect,
    prepare_effect_dispatch,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
import tests.integration.book_opening_recovery_postgres_support as recovery_support
from tests.integration.book_opening_recovery_postgres_support import (
    LegacyBookOpeningOrphan,
    SimulatedBookOpeningProcessLoss,
    create_legacy_book_opening_orphan,
)


def _seed_recovery_intent(
    orphan: LegacyBookOpeningOrphan,
    *,
    disposition: str = "PROVEN_NO_EFFECT",
    semantic_drift: bool = False,
) -> dict[str, Any]:
    loss_key = f"replacement-loss:{orphan.opening_run_id}:generation-1"
    loss = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    orphan.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"replacement-assessment:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    assert assessment.disposition == disposition
    semantic = dict(assessment.snapshot["semantic_evaluation"])
    authoritative_semantic = dict(semantic)
    if semantic_drift:
        # The immutable assessment remains authoritative.  Corrupt only the
        # caller's expected CAS input so the primitive proves stale admission
        # fails closed without rewriting history for a test fixture.
        authoritative_semantic["head_version"] = int(semantic["head_version"]) + 1

    # The database intentionally rejects a standalone RecoveryIntent.  Admit
    # the outer successor through the canonical Recovery Application while a
    # test seam defers the semantic primitive under test.  Intent, receipt,
    # RuntimeJob, outer execution and Opening head therefore still commit as
    # one valid recovery UoW.
    with patch.object(
        orphan.opening.recovery,
        "_semantic_replacement_required",
        return_value=False,
    ):
        receipt = orphan.opening.recovery.recover(
            assessment.recovery_assessment_id,
            idempotency_key=f"replacement-recover:{orphan.opening_run_id}",
            reason="PostgreSQL replacement primitive regression",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
    intent_id = str(receipt.result["recovery_intent_id"])
    assert receipt.result["replacement_evaluation_operation_id"] == ""
    return {
        "recovery_intent_id": intent_id,
        "semantic": authoritative_semantic,
    }


def _admit(orphan: LegacyBookOpeningOrphan, seeded: dict[str, Any]) -> dict[str, Any]:
    semantic = dict(seeded["semantic"])
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        result = orphan.planning.semantic_evaluation.admit_replacement_in_uow(
            uow,
            predecessor_operation_id=orphan.evaluation_operation_id,
            recovery_intent_id=str(seeded["recovery_intent_id"]),
            actor_id=orphan.evaluator.principal_id,
            trace_id=f"trace:recover:{orphan.opening_run_id}",
            correlation_id=f"correlation:recover:{orphan.opening_run_id}",
            expected_head_generation=int(semantic["generation"]),
            expected_head_version=int(semantic["head_version"]),
        )
        uow.commit()
    return result


def _gate_is_open(*, operation_id: str, project_id: str) -> bool:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT authority_narrative_replacement_gate_is_open(%s,%s)",
            [operation_id, project_id],
        )
        row = uow.cursor.fetchone()
    return row is not None and bool(row[0])


def _recover_through_canonical_path(
    orphan: LegacyBookOpeningOrphan,
    *,
    suffix: str,
) -> Any:
    loss_key = f"replacement-gate-loss:{orphan.opening_run_id}:{suffix}"
    loss = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    orphan.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=(
            f"replacement-gate-assessment:{orphan.opening_run_id}:{suffix}"
        ),
        principal=orphan.principal,
    )
    return orphan.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=(f"replacement-gate-recover:{orphan.opening_run_id}:{suffix}"),
        reason=f"exercise exact replacement execution gate {suffix}",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )


def _create_ambiguous_effect_orphan() -> LegacyBookOpeningOrphan:
    def leave_ambiguous_effect(
        _port: object,
        request: Any,
        **_kwargs: object,
    ) -> object:
        context = EffectCommandContext(
            operation_id=str(request.operation_id),
            project_id=str(request.project_id),
            actor_id=str(request.worker_id),
            trace_id=str(request.trace_id),
            correlation_id=str(request.correlation_id),
            causation_id=str(request.operation_id),
        )
        effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider="fixture-ambiguous-semantic-evaluator",
            capability="model.narrative_semantic_evaluation",
            stable_idempotency_key=f"ambiguous:{request.operation_id}",
            request_payload={"candidate": "durably-dispatched-unknown"},
            max_attempts=1,
            reversible=False,
            reconciliation_mode="query",
        )
        dispatch = prepare_effect_dispatch(
            DATABASE_URL,
            context,
            effect_id=str(effect["external_effect_id"]),
        )
        mark_external_effect_unknown(
            DATABASE_URL,
            context,
            dispatch_id=str(dispatch["dispatch_id"]),
            evidence={
                "classification": "AMBIGUOUS",
                "provider_invocation_count": "UNKNOWN",
            },
        )
        raise SimulatedBookOpeningProcessLoss(
            "semantic provider outcome became ambiguous before materialization"
        )

    with patch.object(
        recovery_support._CrashBeforeExternalEffectPort,
        "evaluate",
        new=leave_ambiguous_effect,
    ):
        # UNKNOWN evidence may never be rewritten as ``no_external_effect``.
        # Leave the inner execution active and let formal loss/recovery
        # assessment classify its durable Effect evidence.
        return create_legacy_book_opening_orphan(terminalize_evaluation=False)


@pytest.fixture(scope="module", autouse=True)
def _migration() -> None:
    ensure_migrated()


def test_replacement_generation_is_atomic_admission_only_and_replay_safe() -> None:
    orphan = create_legacy_book_opening_orphan()
    seeded = _seed_recovery_intent(orphan)
    before = orphan.cross_layer_state()

    admitted = _admit(orphan, seeded)
    replayed = _admit(orphan, seeded)

    assert admitted["generation"] == 2
    assert admitted["replayed"] is False
    assert replayed == {**admitted, "replayed": True}
    assert orphan.cross_layer_state() == before
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT predecessor.operation_id,predecessor.status,
                   predecessor_execution.lifecycle,
                   successor.operation_id,successor.status,
                   successor_execution.generation,
                   successor_execution.predecessor_operation_id,
                   successor_execution.recovery_intent_id,
                   successor.idempotency_key,successor.concurrency_key,
                   head.current_execution_id,head.current_generation,head.version,
                   (SELECT COUNT(*) FROM authority_attempt
                    WHERE operation_id=successor.operation_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id IN (
                        predecessor.operation_id,successor.operation_id
                    ))
            FROM authority_narrative_evaluation_execution AS predecessor_execution
            JOIN authority_operation AS predecessor
              ON predecessor.operation_id=predecessor_execution.operation_id
            JOIN authority_narrative_evaluation_execution AS successor_execution
              ON successor_execution.predecessor_execution_id=
                 predecessor_execution.evaluation_execution_id
            JOIN authority_operation AS successor
              ON successor.operation_id=successor_execution.operation_id
            JOIN authority_narrative_evaluation_execution_head AS head
              ON head.current_execution_id=
                 successor_execution.evaluation_execution_id
            WHERE predecessor.operation_id=%s
            """,
            [orphan.evaluation_operation_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    assert tuple(row[:8]) == (
        orphan.evaluation_operation_id,
        "CANCELLED",
        "CANCELLED",
        admitted["operation_id"],
        "ADMITTED",
        2,
        orphan.evaluation_operation_id,
        seeded["recovery_intent_id"],
    )
    assert str(row[8]).endswith(":evaluation-generation:2")
    assert str(row[9]).endswith(":evaluation-generation:2")
    assert tuple(row[10:]) == (admitted["evaluation_execution_id"], 2, 1, 0, 0)


def test_replacement_same_intent_concurrency_converges_to_one_operation() -> None:
    orphan = create_legacy_book_opening_orphan()
    seeded = _seed_recovery_intent(orphan)
    barrier = Barrier(2)

    def concurrent_admit() -> dict[str, Any]:
        barrier.wait(timeout=10)
        return _admit(orphan, seeded)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: concurrent_admit(), range(2)))

    assert {item["operation_id"] for item in results} == {results[0]["operation_id"]}
    assert sorted(item["replayed"] for item in results) == [False, True]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_narrative_evaluation_execution
            WHERE recovery_intent_id=%s
            """,
            [seeded["recovery_intent_id"]],
        )
        assert int(uow.cursor.fetchone()[0]) == 1


def test_replacement_cannot_execute_before_outer_activation() -> None:
    orphan = create_legacy_book_opening_orphan()
    seeded = _seed_recovery_intent(orphan)
    admitted = _admit(orphan, seeded)

    with pytest.raises(KernelError) as blocked:
        orphan.planning.evaluate_candidate(
            orphan.evaluation_command,
            principal=orphan.evaluator,
            transition_principal=orphan.principal,
        )
    assert blocked.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED"
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT predecessor.status,successor.status,
                   successor_execution.lifecycle,
                   (SELECT COUNT(*) FROM authority_attempt
                    WHERE operation_id=successor.operation_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id IN (
                        predecessor.operation_id,successor.operation_id
                    ))
            FROM authority_operation AS predecessor
            JOIN authority_narrative_evaluation_execution AS successor_execution
              ON successor_execution.predecessor_operation_id=
                 predecessor.operation_id
            JOIN authority_operation AS successor
              ON successor.operation_id=successor_execution.operation_id
            WHERE predecessor.operation_id=%s
              AND successor.operation_id=%s
            """,
            [orphan.evaluation_operation_id, admitted["operation_id"]],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    assert tuple(row) == ("CANCELLED", "ADMITTED", "ADMITTED", 0, 0)


def test_scripted_replacement_is_also_blocked_before_outer_activation() -> None:
    orphan = create_legacy_book_opening_orphan(
        evaluator_execution_class="SCRIPTED_FIXTURE"
    )
    seeded = _seed_recovery_intent(orphan)
    admitted = _admit(orphan, seeded)

    with pytest.raises(KernelError) as blocked:
        orphan.planning.evaluate_candidate(
            orphan.evaluation_command,
            principal=orphan.evaluator,
            transition_principal=orphan.principal,
        )
    assert blocked.value.code == (
        "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED"
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT predecessor.status,successor.status,
                   successor.actor_id,successor_execution.lifecycle,
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id IN (
                        predecessor.operation_id,successor.operation_id
                    ))
            FROM authority_operation AS predecessor
            JOIN authority_narrative_evaluation_execution AS successor_execution
              ON successor_execution.predecessor_operation_id=
                 predecessor.operation_id
            JOIN authority_operation AS successor
              ON successor.operation_id=successor_execution.operation_id
            WHERE predecessor.operation_id=%s
              AND successor.operation_id=%s
            """,
            [orphan.evaluation_operation_id, admitted["operation_id"]],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    assert tuple(row) == (
        "CANCELLED",
        "ADMITTED",
        orphan.evaluator.principal_id,
        "ADMITTED",
        0,
    )


def test_unstarted_replacement_cancellation_is_atomic_and_idempotent() -> None:
    orphan = create_legacy_book_opening_orphan()
    seeded = _seed_recovery_intent(orphan)
    admitted = _admit(orphan, seeded)

    def cancel() -> dict[str, Any]:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            result = (
                orphan.planning.semantic_evaluation.cancel_unstarted_replacement_in_uow(
                    uow,
                    operation_id=str(admitted["operation_id"]),
                    actor_id=orphan.principal.principal_id,
                    trace_id=f"trace:abort:{orphan.opening_run_id}",
                    correlation_id=f"correlation:abort:{orphan.opening_run_id}",
                    reason="Book Opening aborted before replacement worker claim",
                )
            )
            uow.commit()
        return result

    cancelled = cancel()
    replayed = cancel()

    assert cancelled["operation_status"] == "CANCELLED"
    assert cancelled["lifecycle"] == "CANCELLED"
    assert cancelled["replayed"] is False
    assert replayed == {**cancelled, "replayed": True}
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT predecessor.status,successor.status,
                   successor_execution.lifecycle,
                   (SELECT COUNT(*) FROM authority_attempt
                    WHERE operation_id=successor.operation_id),
                   (SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id=successor.operation_id)
            FROM authority_operation AS predecessor
            JOIN authority_narrative_evaluation_execution AS successor_execution
              ON successor_execution.predecessor_operation_id=
                 predecessor.operation_id
            JOIN authority_operation AS successor
              ON successor.operation_id=successor_execution.operation_id
            WHERE predecessor.operation_id=%s
              AND successor.operation_id=%s
            """,
            [orphan.evaluation_operation_id, admitted["operation_id"]],
        )
        row = uow.cursor.fetchone()
    assert tuple(row) == ("CANCELLED", "CANCELLED", "CANCELLED", 0, 0)


def test_replacement_fails_closed_for_unknown_assessment() -> None:
    orphan = _create_ambiguous_effect_orphan()
    loss_key = f"replacement-loss:{orphan.opening_run_id}:unknown"
    loss = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    orphan.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assessment = orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"replacement-assessment:{orphan.opening_run_id}:unknown",
        principal=orphan.principal,
    )
    assert assessment.disposition == "UNKNOWN_AMBIGUOUS"

    with pytest.raises(KernelError) as rejected:
        orphan.opening.recovery.recover(
            assessment.recovery_assessment_id,
            idempotency_key=f"replacement-recover:{orphan.opening_run_id}:unknown",
            reason="UNKNOWN external state must remain reconciliation-only",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
    assert rejected.value.code == (
        "BOOK_OPENING_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED"
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_book_opening_recovery_intent
            WHERE opening_run_id=%s
            """,
            [orphan.opening_run_id],
        )
        assert int(uow.cursor.fetchone()[0]) == 0


def test_replacement_fails_closed_for_semantic_assessment_drift() -> None:
    orphan = create_legacy_book_opening_orphan()
    seeded = _seed_recovery_intent(orphan, semantic_drift=True)

    with pytest.raises(
        KernelError,
        match="NARRATIVE_EVALUATION_REPLACEMENT_STALE",
    ):
        _admit(orphan, seeded)

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_narrative_evaluation_execution
            WHERE recovery_intent_id=%s
            """,
            [seeded["recovery_intent_id"]],
        )
        assert int(uow.cursor.fetchone()[0]) == 0


def test_database_gate_missing_lineage_and_wrong_project_fail_closed() -> None:
    orphan = create_legacy_book_opening_orphan()

    assert not _gate_is_open(
        operation_id="operation:missing-semantic-execution",
        project_id=orphan.project_id,
    )
    assert not _gate_is_open(
        operation_id=orphan.evaluation_operation_id,
        project_id="project:wrong-scope",
    )


def test_database_gate_rejects_direct_semantic_execution_bypasses() -> None:
    orphan = create_legacy_book_opening_orphan()
    receipt = _recover_through_canonical_path(orphan, suffix="direct-db-bypass")
    operation_id = str(receipt.result["replacement_evaluation_operation_id"])
    evaluation_execution_id = str(receipt.result["replacement_evaluation_execution_id"])
    assert operation_id and evaluation_execution_id

    rejected_statements = (
        (
            """
            UPDATE authority_operation
            SET status='READY',version=version+1
            WHERE operation_id=%s AND status='ADMITTED'
            """,
            [operation_id],
        ),
        (
            """
            UPDATE authority_narrative_evaluation_execution
            SET lifecycle='RUNNING',version=version+1
            WHERE evaluation_execution_id=%s AND lifecycle='ADMITTED'
            """,
            [evaluation_execution_id],
        ),
        (
            """
            INSERT INTO authority_attempt(
                attempt_id,operation_id,attempt_number,status
            ) VALUES (%s,%s,1,'CREATED')
            """,
            [f"attempt:direct-bypass:{operation_id}", operation_id],
        ),
        (
            """
            INSERT INTO authority_external_effect(
                external_effect_id,operation_id,effect_type,
                stable_idempotency_key,status,request_hash,project_id
            ) VALUES (%s,%s,'model.invoke',%s,'READY',%s,%s)
            """,
            [
                f"effect:direct-bypass:{operation_id}",
                operation_id,
                f"direct-bypass:{operation_id}",
                "sha256:" + "0" * 64,
                orphan.project_id,
            ],
        ),
    )
    for statement, parameters in rejected_statements:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
        ):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(statement, parameters)
                uow.commit()

    terminal_effect_id = f"effect:terminal-bypass-probe:{operation_id}"
    terminal_dispatch_id = f"dispatch:terminal-bypass-probe:{operation_id}"
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            INSERT INTO authority_external_effect(
                external_effect_id,operation_id,effect_type,
                stable_idempotency_key,status,request_hash,project_id
            ) VALUES (%s,%s,'model.invoke',%s,'FAILED_FINAL',%s,%s)
            """,
            [
                terminal_effect_id,
                operation_id,
                f"terminal-bypass-probe:{operation_id}",
                "sha256:" + "1" * 64,
                orphan.project_id,
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_external_effect_dispatch(
                dispatch_id,external_effect_id,generation,status,payload_hash
            ) VALUES (%s,%s,1,'FAILED_FINAL',%s)
            """,
            [terminal_dispatch_id, terminal_effect_id, "sha256:" + "1" * 64],
        )
        uow.commit()
    with pytest.raises(
        psycopg.errors.CheckViolation,
        match="NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
    ):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_effect_dispatch_lease(
                    lease_id,dispatch_id,owner,fencing_token,
                    acquired_at,expires_at,heartbeat_at,status
                ) VALUES (
                    %s,%s,'direct-db-bypass-worker',1,
                    clock_timestamp(),
                    clock_timestamp()+INTERVAL '1 minute',
                    clock_timestamp(),'HELD'
                )
                """,
                [f"effect-lease:direct-bypass:{operation_id}", terminal_dispatch_id],
            )
            uow.commit()


def test_new_replacement_gate_opens_only_after_exact_outer_activation() -> None:
    orphan = create_legacy_book_opening_orphan()
    receipt = _recover_through_canonical_path(orphan, suffix="new")
    operation_id = str(receipt.result["replacement_evaluation_operation_id"])
    assert operation_id
    assert not _gate_is_open(
        operation_id=operation_id,
        project_id=orphan.project_id,
    )

    claim = orphan.opening.claim_next_legacy_execution(
        worker_id="replacement-gate-new-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert claim is not None
    assert claim.runtime_job_id == receipt.result["runtime_job_id"]
    # Claim owns no Provider permission.  Activation must atomically move the
    # RuntimeJob, Attempt, OpeningExecution and BookOpening to RUNNING first.
    assert not _gate_is_open(
        operation_id=operation_id,
        project_id=orphan.project_id,
    )
    orphan.opening._bind_running_execution(  # noqa: SLF001
        orphan.opening_run_id,
        expected_version=int(orphan.opening.require(orphan.opening_run_id)["version"]),
        runtime_claim=claim,
    )
    assert _gate_is_open(
        operation_id=operation_id,
        project_id=orphan.project_id,
    )
    assert (
        orphan.opening.claim_next_legacy_execution(
            worker_id="replacement-gate-double-claim-worker",
            lease_seconds=60,
            project_id=orphan.project_id,
        )
        is None
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=clock_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s AND status='HELD'
            """,
            [claim.lease_id],
        )
        assert uow.cursor.rowcount == 1
        uow.commit()
    assert not _gate_is_open(
        operation_id=operation_id,
        project_id=orphan.project_id,
    )


def test_resume_current_gate_uses_exact_current_assessment_and_fence() -> None:
    orphan = create_legacy_book_opening_orphan(terminalize_evaluation=False)
    receipt = _recover_through_canonical_path(orphan, suffix="resume")
    assert receipt.result["replacement_evaluation_operation_id"] == ""
    assert not _gate_is_open(
        operation_id=orphan.evaluation_operation_id,
        project_id=orphan.project_id,
    )

    claim = orphan.opening.claim_next_legacy_execution(
        worker_id="replacement-gate-resume-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert claim is not None
    assert claim.runtime_job_id == receipt.result["runtime_job_id"]
    assert not _gate_is_open(
        operation_id=orphan.evaluation_operation_id,
        project_id=orphan.project_id,
    )
    orphan.opening._bind_running_execution(  # noqa: SLF001
        orphan.opening_run_id,
        expected_version=int(orphan.opening.require(orphan.opening_run_id)["version"]),
        runtime_claim=claim,
    )
    assert _gate_is_open(
        operation_id=orphan.evaluation_operation_id,
        project_id=orphan.project_id,
    )


def test_resume_current_outer_abort_fences_and_terminalizes_semantic_execution() -> (
    None
):
    orphan = create_legacy_book_opening_orphan(terminalize_evaluation=False)
    receipt = _recover_through_canonical_path(orphan, suffix="resume-abort")
    assert receipt.result["replacement_evaluation_operation_id"] == ""

    outer_claim = orphan.opening.claim_next_legacy_execution(
        worker_id="replacement-gate-resume-abort-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert outer_claim is not None
    run = orphan.opening.require(orphan.opening_run_id)
    aborted = orphan.opening.abort(
        orphan.opening_run_id,
        expected_version=int(run["version"]),
        principal=orphan.principal,
    )
    assert aborted["lifecycle"] == "ABORTED"
    assert not _gate_is_open(
        operation_id=orphan.evaluation_operation_id,
        project_id=orphan.project_id,
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT job.status,runtime_attempt.status,runtime_lease.status,
                   operation.status,evaluation.lifecycle,attempt.status,
                   lease.status
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS runtime_attempt
              ON runtime_attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS runtime_lease
              ON runtime_lease.lease_id=runtime_attempt.lease_id
            JOIN authority_operation AS operation
              ON operation.operation_id=%s
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s
            """,
            [orphan.evaluation_operation_id, outer_claim.runtime_job_id],
        )
        state = uow.cursor.fetchone()
    assert state is not None
    assert tuple(state) == (
        "CANCELLED",
        "ABANDONED",
        "RELEASED",
        "CANCELLED",
        "CANCELLED",
        "CANCELLED",
        "RELEASED",
    )

    with pytest.raises(KernelError):
        orphan.opening.runtime_jobs.heartbeat(outer_claim, lease_seconds=60)


def test_resume_current_outer_abort_cancels_planned_never_sent_effect() -> None:
    orphan = create_legacy_book_opening_orphan(terminalize_evaluation=False)
    receipt = _recover_through_canonical_path(orphan, suffix="resume-planned-abort")
    assert receipt.result["replacement_evaluation_operation_id"] == ""

    outer_claim = orphan.opening.claim_next_legacy_execution(
        worker_id="replacement-gate-resume-planned-abort-worker",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert outer_claim is not None
    orphan.opening._bind_running_execution(  # noqa: SLF001
        orphan.opening_run_id,
        expected_version=int(orphan.opening.require(orphan.opening_run_id)["version"]),
        runtime_claim=outer_claim,
    )
    effect = plan_external_effect(
        DATABASE_URL,
        EffectCommandContext(
            operation_id=orphan.evaluation_operation_id,
            project_id=orphan.project_id,
            actor_id=orphan.evaluator.principal_id,
            trace_id=f"trace:planned-abort:{orphan.opening_run_id}",
            correlation_id=f"correlation:planned-abort:{orphan.opening_run_id}",
            causation_id=outer_claim.runtime_job_id,
        ),
        effect_type="model.invoke",
        provider="fixture-planned-never-sent",
        capability="model.narrative_semantic_evaluation",
        stable_idempotency_key=(f"planned-never-sent:{orphan.evaluation_operation_id}"),
        request_payload={"candidate": "must-not-reach-provider"},
        max_attempts=1,
        reversible=False,
        reconciliation_mode="query",
    )
    reservation = reserve_provider_budget(
        DATABASE_URL,
        BudgetReservationRequest(
            operation_id=orphan.evaluation_operation_id,
            external_effect_id=str(effect["external_effect_id"]),
            project_id=orphan.project_id,
            stable_idempotency_key=(
                f"budget:planned-never-sent:{orphan.evaluation_operation_id}"
            ),
            provider="fixture-planned-never-sent",
            currency="USD",
            estimated_amount="2",
            estimated_tokens=100_000,
        ),
    )
    assert reservation["status"] == "RESERVED"

    aborted = orphan.opening.abort(
        orphan.opening_run_id,
        expected_version=int(orphan.opening.require(orphan.opening_run_id)["version"]),
        principal=orphan.principal,
    )
    assert aborted["lifecycle"] == "ABORTED"
    assert not _gate_is_open(
        operation_id=orphan.evaluation_operation_id,
        project_id=orphan.project_id,
    )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT operation.status,evaluation.lifecycle,attempt.status,
                   lease.status,effect.status,budget.status,
                   (SELECT COUNT(*)
                    FROM authority_external_effect_dispatch AS dispatch
                    WHERE dispatch.external_effect_id=effect.external_effect_id),
                   (SELECT COUNT(*)
                    FROM state_event AS event
                    WHERE event.aggregate_type='authority_external_effect'
                      AND event.aggregate_id=effect.external_effect_id
                      AND event.event_type='external_effect.cancelled')
            FROM authority_operation AS operation
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=operation.operation_id
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
            JOIN authority_budget_reservation AS budget
              ON budget.external_effect_id=effect.external_effect_id
             AND budget.reservation_id=%s
            WHERE operation.operation_id=%s
              AND effect.external_effect_id=%s
            """,
            [
                reservation["reservation_id"],
                orphan.evaluation_operation_id,
                effect["external_effect_id"],
            ],
        )
        state = uow.cursor.fetchone()
    assert state is not None
    assert tuple(state) == (
        "CANCELLED",
        "CANCELLED",
        "CANCELLED",
        "RELEASED",
        "CANCELLED",
        "RELEASED",
        0,
        1,
    )
