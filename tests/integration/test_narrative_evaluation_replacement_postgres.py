from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from unittest.mock import patch

import pytest

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
        "READY",
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


def test_replacement_runs_only_when_normal_governed_execution_is_invoked() -> None:
    orphan = create_legacy_book_opening_orphan()
    seeded = _seed_recovery_intent(orphan)
    admitted = _admit(orphan, seeded)

    with pytest.raises(SimulatedBookOpeningProcessLoss):
        orphan.planning.evaluate_candidate(
            orphan.evaluation_command,
            principal=orphan.evaluator,
            transition_principal=orphan.principal,
        )

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        with pytest.raises(
            KernelError, match="NARRATIVE_EVALUATION_REPLACEMENT_ACTIVE"
        ):
            orphan.planning.semantic_evaluation.cancel_unstarted_replacement_in_uow(
                uow,
                operation_id=str(admitted["operation_id"]),
                actor_id=orphan.principal.principal_id,
                trace_id=f"trace:abort:{orphan.opening_run_id}",
                correlation_id=f"correlation:abort:{orphan.opening_run_id}",
                reason="active replacement must fail closed",
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
    assert tuple(row) == ("CANCELLED", "EXECUTING", "RUNNING", 1, 0)


def test_replacement_scripted_fixture_executes_with_predecessor_evaluator() -> None:
    orphan = create_legacy_book_opening_orphan(
        evaluator_execution_class="SCRIPTED_FIXTURE"
    )
    seeded = _seed_recovery_intent(orphan)
    admitted = _admit(orphan, seeded)

    result = orphan.planning.evaluate_candidate(
        orphan.evaluation_command,
        principal=orphan.evaluator,
        transition_principal=orphan.principal,
    )

    assert (
        result.generation_operation_id
        == orphan.evaluation_command.generation_operation_id
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        terminal_replay = (
            orphan.planning.semantic_evaluation.cancel_unstarted_replacement_in_uow(
                uow,
                operation_id=str(admitted["operation_id"]),
                actor_id=orphan.principal.principal_id,
                trace_id=f"trace:abort:{orphan.opening_run_id}",
                correlation_id=f"correlation:abort:{orphan.opening_run_id}",
                reason="terminal execution is immutable",
            )
        )
    assert terminal_replay["operation_status"] == "SUCCEEDED"
    assert terminal_replay["lifecycle"] == "SUCCEEDED"
    assert terminal_replay["replayed"] is True
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT predecessor.status,successor.status,
                   successor.actor_id,successor_execution.lifecycle,
                   attempt.status,lease.status,
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
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=successor.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE predecessor.operation_id=%s
              AND successor.operation_id=%s
            """,
            [orphan.evaluation_operation_id, admitted["operation_id"]],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    assert tuple(row) == (
        "CANCELLED",
        "SUCCEEDED",
        orphan.evaluator.principal_id,
        "SUCCEEDED",
        "SUCCEEDED",
        "RELEASED",
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
