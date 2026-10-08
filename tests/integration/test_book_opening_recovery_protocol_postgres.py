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


class SimulatedRecoveryResponseLoss(BaseException):
    """The recovery commit succeeded but its caller never received the receipt."""


def _converge_loss(orphan: LegacyBookOpeningOrphan) -> None:
    loss_key = f"protocol-loss:{orphan.opening_run_id}:generation-1"
    loss = orphan.opening.recovery.assess_execution_loss(
        orphan.opening_run_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
    )
    receipt = orphan.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert receipt.result["opening_lifecycle"] == "FAILED"
    assert receipt.result["execution_lifecycle"] == "LOST"
    assert receipt.result["recovery_intent_created"] is False
    assert receipt.result["provider_invoked"] is False


def _assess_recovery(orphan: LegacyBookOpeningOrphan, *, suffix: str) -> Any:
    return orphan.opening.recovery.assess_recovery(
        orphan.opening_run_id,
        idempotency_key=f"protocol-recovery-assessment:{orphan.opening_run_id}:{suffix}",
        principal=orphan.principal,
    )


def _effect_count(orphan: LegacyBookOpeningOrphan) -> int:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM authority_external_effect AS effect
            JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.operation_id=effect.operation_id
            WHERE evaluation.project_id=%s
              AND evaluation.candidate_asset_version_id=%s
            """,
            [
                orphan.project_id,
                orphan.evaluation_command.candidate_asset_version_id,
            ],
        )
        return int(uow.cursor.fetchone()[0])


def test_recovery_vs_recovery_serializes_to_one_successor_generation() -> None:
    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()
    _converge_loss(orphan)
    assessment = _assess_recovery(orphan, suffix="race")
    assert assessment.disposition == "PROVEN_NO_EFFECT"
    barrier = Barrier(2)

    def recover(ordinal: int) -> tuple[str, object]:
        barrier.wait(timeout=10)
        try:
            receipt = orphan.opening.recovery.recover(
                assessment.recovery_assessment_id,
                idempotency_key=(
                    f"protocol-recovery-race:{orphan.opening_run_id}:{ordinal}"
                ),
                reason=f"concurrent recovery contender {ordinal}",
                principal=orphan.principal,
                expected_opening_run_id=orphan.opening_run_id,
            )
            return "admitted", receipt
        except KernelError as exc:
            return "rejected", exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(recover, (1, 2)))

    assert sorted(status for status, _ in outcomes) == ["admitted", "rejected"]
    admitted = next(value for status, value in outcomes if status == "admitted")
    rejected = next(value for status, value in outcomes if status == "rejected")
    assert getattr(admitted, "result")["execution_generation"] == 2
    assert rejected == "BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED"

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   COUNT(DISTINCT intent.recovery_intent_id),
                   COUNT(DISTINCT successor.opening_execution_id),
                   COUNT(DISTINCT replacement.evaluation_execution_id),
                   COUNT(DISTINCT receipt.recovery_receipt_id)
            FROM authority_book_opening_run AS opening
            LEFT JOIN authority_book_opening_recovery_intent AS intent
              ON intent.opening_run_id=opening.opening_run_id
            LEFT JOIN authority_book_opening_execution AS successor
              ON successor.opening_run_id=opening.opening_run_id
             AND successor.generation=2
            LEFT JOIN authority_narrative_evaluation_execution AS replacement
              ON replacement.recovery_intent_id=intent.recovery_intent_id
             AND replacement.generation=2
            LEFT JOIN authority_book_opening_recovery_receipt AS receipt
              ON receipt.opening_run_id=opening.opening_run_id
             AND receipt.receipt_kind='RECOVERY_ADMISSION'
            WHERE opening.opening_run_id=%s
            GROUP BY opening.lifecycle,opening.current_execution_generation
            """,
            [orphan.opening_run_id],
        )
        row = uow.cursor.fetchone()
    assert row == ("ADMITTED", 2, 1, 1, 1, 1)
    assert _effect_count(orphan) == 0


def test_checkpoint_drift_rejects_stale_assessment_and_fresh_assessment_converges() -> (
    None
):
    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()
    _converge_loss(orphan)
    stale_assessment = _assess_recovery(orphan, suffix="before-checkpoint")
    generation = orphan.planning.require_generation(
        orphan.evaluation_command.generation_operation_id
    )

    checkpoint_assessment = orphan.opening.recovery.assess_checkpoint_reconciliation(
        orphan.opening_run_id,
        semantic_work_key=f"planning-generation:{generation['generation_id']}",
        owning_authority="STORY_PLANNING",
        evidence_type="PLANNING_GENERATION",
        evidence_id=str(generation["generation_id"]),
        evidence_version=int(generation["version"]),
        evidence_hash=str(generation["input_snapshot_hash"]),
        idempotency_key=f"protocol-checkpoint-assessment:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    checkpoint_receipt = orphan.opening.recovery.reconcile_checkpoint(
        checkpoint_assessment.recovery_assessment_id,
        idempotency_key=f"protocol-checkpoint-reconcile:{orphan.opening_run_id}",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    checkpoint = checkpoint_receipt.result
    assert checkpoint["sequence"] == 1
    assert checkpoint["replayed"] is False

    with pytest.raises(KernelError) as stale:
        orphan.opening.recovery.recover(
            stale_assessment.recovery_assessment_id,
            idempotency_key=f"protocol-stale-recovery:{orphan.opening_run_id}",
            reason="stale checkpoint must not authorize a successor",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
    assert stale.value.code == "BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED"

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   opening.current_checkpoint_id,
                   opening.current_checkpoint_sequence,
                   COUNT(intent.recovery_intent_id)
            FROM authority_book_opening_run AS opening
            LEFT JOIN authority_book_opening_recovery_intent AS intent
              ON intent.opening_run_id=opening.opening_run_id
            WHERE opening.opening_run_id=%s
            GROUP BY opening.lifecycle,opening.current_execution_generation,
                     opening.current_checkpoint_id,
                     opening.current_checkpoint_sequence
            """,
            [orphan.opening_run_id],
        )
        before_reassessment = uow.cursor.fetchone()
    assert before_reassessment == (
        "FAILED",
        1,
        checkpoint["checkpoint_id"],
        1,
        0,
    )

    fresh = _assess_recovery(orphan, suffix="after-checkpoint")
    admitted = orphan.opening.recovery.recover(
        fresh.recovery_assessment_id,
        idempotency_key=f"protocol-fresh-recovery:{orphan.opening_run_id}",
        reason="fresh assessment binds the durable checkpoint cursor",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    assert admitted.result["execution_generation"] == 2
    assert admitted.result["provider_invoked"] is False
    assert _effect_count(orphan) == 0


def test_live_checkpoint_requires_current_claim_and_rejects_stale_writer() -> None:
    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()
    generation = orphan.planning.require_generation(
        orphan.evaluation_command.generation_operation_id
    )
    arguments = {
        "semantic_work_key": f"planning-generation:{generation['generation_id']}",
        "owning_authority": "STORY_PLANNING",
        "evidence_type": "PLANNING_GENERATION",
        "evidence_id": str(generation["generation_id"]),
        "evidence_version": int(generation["version"]),
        "evidence_hash": str(generation["input_snapshot_hash"]),
    }
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

    checkpoint = orphan.opening.recovery.append_execution_checkpoint(
        orphan.opening_run_id,
        runtime_claim=orphan.outer_claim,
        **arguments,
    )
    assert checkpoint["sequence"] == 1
    assert checkpoint["replayed"] is False

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [orphan.outer_claim.lease_id],
        )
        uow.commit()
    _converge_loss(orphan)

    with pytest.raises(KernelError) as stale:
        orphan.opening.recovery.append_execution_checkpoint(
            orphan.opening_run_id,
            runtime_claim=orphan.outer_claim,
            **arguments,
        )
    assert stale.value.code == "BOOK_OPENING_CHECKPOINT_EXECUTION_STALE"
    run = orphan.opening.require(orphan.opening_run_id)
    assert run["current_checkpoint_id"] == checkpoint["checkpoint_id"]
    assert run["current_checkpoint_sequence"] == 1


def test_unknown_ambiguous_external_effect_fails_closed_without_intent() -> None:
    ensure_migrated()
    effect_ids: list[str] = []

    def leave_ambiguous_effect(
        _port: object,
        request: Any,
        **_kwargs: object,
    ) -> object:
        context = EffectCommandContext(
            operation_id=str(request.operation_id),
            project_id=str(request.project_id),
            actor_id=str(request.actor_id),
            trace_id=str(request.trace_id),
            correlation_id=str(request.correlation_id),
            causation_id=str(request.operation_id),
        )
        planned = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.narrative_semantic_evaluation",
            provider="fixture-ambiguous-provider",
            capability="model.narrative_semantic_evaluation",
            stable_idempotency_key=f"ambiguous:{request.operation_id}",
            request_payload={"candidate": "durably-dispatched-unknown"},
            max_attempts=1,
            reversible=False,
            reconciliation_mode="query",
        )
        effect_ids.append(str(planned["external_effect_id"]))
        dispatch = prepare_effect_dispatch(
            DATABASE_URL,
            context,
            effect_id=str(planned["external_effect_id"]),
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
            "response disappeared after dispatch outcome became ambiguous"
        )

    with patch.object(
        recovery_support._CrashBeforeExternalEffectPort,
        "evaluate",
        new=leave_ambiguous_effect,
    ):
        orphan = create_legacy_book_opening_orphan()
    assert len(effect_ids) == 1
    _converge_loss(orphan)
    assessment = _assess_recovery(orphan, suffix="ambiguous-effect")
    assert assessment.disposition == "UNKNOWN_AMBIGUOUS"

    with pytest.raises(KernelError) as blocked:
        orphan.opening.recovery.recover(
            assessment.recovery_assessment_id,
            idempotency_key=f"protocol-ambiguous-recovery:{orphan.opening_run_id}",
            reason="operator authorization cannot override ambiguous effects",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
    assert blocked.value.code == "BOOK_OPENING_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED"

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT effect.status,dispatch.status,
                   COUNT(DISTINCT intent.recovery_intent_id),
                   COUNT(DISTINCT successor.opening_execution_id),
                   COUNT(DISTINCT receipt.recovery_receipt_id)
            FROM authority_external_effect AS effect
            JOIN authority_external_effect_dispatch AS dispatch
              ON dispatch.external_effect_id=effect.external_effect_id
            LEFT JOIN authority_book_opening_recovery_intent AS intent
              ON intent.opening_run_id=%s
            LEFT JOIN authority_book_opening_execution AS successor
              ON successor.opening_run_id=%s AND successor.generation=2
            LEFT JOIN authority_book_opening_recovery_receipt AS receipt
              ON receipt.opening_run_id=%s
             AND receipt.receipt_kind='RECOVERY_ADMISSION'
            WHERE effect.external_effect_id=%s
            GROUP BY effect.status,dispatch.status
            """,
            [
                orphan.opening_run_id,
                orphan.opening_run_id,
                orphan.opening_run_id,
                effect_ids[0],
            ],
        )
        row = uow.cursor.fetchone()
    assert row == ("RECONCILIATION_REQUIRED", "UNKNOWN", 0, 0, 0)
    assert _effect_count(orphan) == 1


def test_commit_response_loss_and_duplicate_recovery_replay_one_receipt() -> None:
    ensure_migrated()
    orphan = create_legacy_book_opening_orphan()
    _converge_loss(orphan)
    assessment = _assess_recovery(orphan, suffix="response-loss")
    recovery_key = f"protocol-response-loss:{orphan.opening_run_id}"

    def commit_then_lose_response() -> None:
        orphan.opening.recovery.recover(
            assessment.recovery_assessment_id,
            idempotency_key=recovery_key,
            reason="commit succeeds before response disappears",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )
        raise SimulatedRecoveryResponseLoss("recovery response was lost")

    with pytest.raises(SimulatedRecoveryResponseLoss):
        commit_then_lose_response()

    barrier = Barrier(2)

    def replay(_ordinal: int) -> Any:
        barrier.wait(timeout=10)
        return orphan.opening.recovery.recover(
            assessment.recovery_assessment_id,
            idempotency_key=recovery_key,
            reason="commit succeeds before response disappears",
            principal=orphan.principal,
            expected_opening_run_id=orphan.opening_run_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(replay, (1, 2)))

    assert all(receipt.replayed for receipt in receipts)
    assert len({receipt.recovery_receipt_id for receipt in receipts}) == 1
    assert len({receipt.result_hash for receipt in receipts}) == 1
    assert all(receipt.result["execution_generation"] == 2 for receipt in receipts)

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT opening.lifecycle,opening.current_execution_generation,
                   COUNT(DISTINCT intent.recovery_intent_id),
                   COUNT(DISTINCT execution.opening_execution_id),
                   COUNT(DISTINCT evaluation.evaluation_execution_id),
                   COUNT(DISTINCT receipt.recovery_receipt_id),
                   COUNT(DISTINCT job.runtime_job_id)
            FROM authority_book_opening_run AS opening
            LEFT JOIN authority_book_opening_recovery_intent AS intent
              ON intent.opening_run_id=opening.opening_run_id
            LEFT JOIN authority_book_opening_execution AS execution
              ON execution.opening_run_id=opening.opening_run_id
             AND execution.generation=2
            LEFT JOIN authority_narrative_evaluation_execution AS evaluation
              ON evaluation.recovery_intent_id=intent.recovery_intent_id
             AND evaluation.generation=2
            LEFT JOIN authority_book_opening_recovery_receipt AS receipt
              ON receipt.opening_run_id=opening.opening_run_id
             AND receipt.receipt_kind='RECOVERY_ADMISSION'
            LEFT JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
            WHERE opening.opening_run_id=%s
            GROUP BY opening.lifecycle,opening.current_execution_generation
            """,
            [orphan.opening_run_id],
        )
        row = uow.cursor.fetchone()
    assert row == ("ADMITTED", 2, 1, 1, 1, 1, 1)
    assert _effect_count(orphan) == 0


@pytest.mark.parametrize("bound", [True, False])
def test_search_recovery_retains_only_registered_continuation_frontier(
    bound: bool,
) -> None:
    from novel_forge.modules.book_authority.recovery import (
        PostgresBookOpeningRecoveryApplication,
    )
    from tests.integration.authority_postgres_support import (
        identifier,
        insert_definition,
        insert_operation,
        seed_authority_project_book,
    )

    ensure_migrated()
    project, workspace, book = (
        identifier("project"),
        identifier("workspace"),
        identifier("book"),
    )
    seed_authority_project_book(
        project_id=project, workspace_id=workspace, book_id=book
    )
    source, successor, registration = (
        identifier("preflight"),
        identifier("successor"),
        identifier("registration"),
    )
    search, branch, definition = (
        identifier("search"),
        "future-3",
        identifier("definition"),
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        insert_definition(uow.cursor, definition)
        uow.cursor.execute(
            """
            INSERT INTO authority_story_narrative_search(
                search_id,project_id,workspace_id,book_id,generator_operation_name,
                planning_scope,logical_key,accepted_through_chapter,planning_horizon,
                desired_transformation,hard_constraints,input_snapshot_hash,
                strategy_directives,candidate_target,status,stable_idempotency_key
            ) VALUES (%s,%s,%s,%s,'book_plan.generate','BOOK','book:main',0,
                '{}','{}','[]',%s,'["future one","future two","future three"]',
                3,'GENERATING',%s)
            """,
            [search, project, workspace, book, "sha256:" + "a" * 64, search],
        )
        for identity in (source, successor, registration):
            insert_operation(
                uow.cursor,
                operation_id=identity,
                definition_name=definition,
                project_id=project,
                workspace_id=workspace,
                status="FAILED_FINAL",
                command_payload={"payload": {"book_id": book}},
            )
        for identity in (source, successor):
            uow.cursor.execute(
                """INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,book_id,
                generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status,narrative_search_id,narrative_search_branch_key)
                VALUES (%s,%s,%s,%s,%s,'book_plan.generate','BOOK','book:main','[]',%s,'ADMITTED',%s,%s)""",
                [
                    identifier("generation"),
                    identity,
                    project,
                    workspace,
                    book,
                    "sha256:" + "a" * 64,
                    search,
                    branch,
                ],
            )
        if bound:
            uow.cursor.execute(
                """INSERT INTO authority_story_planning_runtime_continuation(continuation_id,project_id,workspace_id,book_id,source_operation_id,
                source_evidence_asset_version_id,registered_by_operation_id,successor_operation_id,source_command,successor_command,target_runtime,decision_evidence,source_release_sha,target_release_sha,chain_depth)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'{}','{}','{}','{}',%s,%s,1)""",
                [
                    identifier("continuation"),
                    project,
                    workspace,
                    book,
                    source,
                    f"scope-fixture:book:{book}:v1",
                    registration,
                    successor,
                    "a" * 40,
                    "b" * 40,
                ],
            )
        uow.commit()
    owner = object.__new__(PostgresBookOpeningRecoveryApplication)
    owner._current_search_branch = lambda *args, **kwargs: (search, branch)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        if bound:
            current = owner._pending_planning_generation(
                uow,
                {"project_id": project, "workspace_id": workspace, "book_id": book},
                checkpoint={},
            )
            assert current["operation_id"] == successor
            assert current["operation_status"] == "FAILED_FINAL"
        else:
            with pytest.raises(
                KernelError, match="BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED"
            ):
                owner._pending_planning_generation(
                    uow,
                    {"project_id": project, "workspace_id": workspace, "book_id": book},
                    checkpoint={},
                )
        uow.cursor.execute(
            "SELECT count(*) FROM authority_story_planning_generation WHERE project_id=%s",
            [project],
        )
        assert uow.cursor.fetchone()[0] == 2
