from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobClaim
from novel_forge.modules.story_planning_runtime import (
    PlanningGenerationResult,
    PlanningGenerationStatus,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_recovery_postgres_support import (
    LegacyBookOpeningOrphan,
    create_legacy_book_opening_orphan,
)


@pytest.fixture(scope="module", autouse=True)
def _migrations() -> None:
    ensure_migrated()


@dataclass(frozen=True, slots=True)
class _LiveLegacyBranch:
    orphan: LegacyBookOpeningOrphan
    claim: RuntimeJobClaim
    search_id: str
    branch_key: str
    result: PlanningGenerationResult


def _prepare_live_legacy_branch() -> _LiveLegacyBranch:
    orphan = create_legacy_book_opening_orphan(
        evaluator_execution_class="SCRIPTED_FIXTURE",
        successful_search_branches_before_crash=1,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT membership.search_id,membership.branch_key,
                   membership.candidate_asset_version_id,
                   membership.generation_operation_id,generation.status
            FROM authority_story_narrative_search_candidate AS membership
            JOIN authority_story_planning_generation AS generation
              ON generation.operation_id=membership.generation_operation_id
            WHERE generation.project_id=%s AND membership.branch_key='future-1'
            """,
            [orphan.project_id],
        )
        row = uow.cursor.fetchone()
        assert row is not None
        uow.commit()

    # This is an upgrade fixture only: 0103 itself preserves pre-existing
    # membership as legacy-unbound.  Business recovery below uses only the
    # production coordinator and never rewrites this historical row.  Trigger
    # DDL and the fixture mutation use separate transactions because PostgreSQL
    # correctly refuses to re-enable a trigger while deferred trigger events
    # are pending.  The finally block guarantees the test cannot leave the
    # shared integration database with the guard disabled.
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            ALTER TABLE authority_story_narrative_search_candidate
            DISABLE TRIGGER authority_story_narrative_membership_identity_immutable
            """
        )
        uow.commit()
    try:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_story_narrative_search_candidate
                SET branch_evidence_contract_version='legacy-unbound',
                    branch_evidence_hash=''
                WHERE search_id=%s AND branch_key=%s
                """,
                [row[0], row[1]],
            )
            uow.commit()
    finally:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                ALTER TABLE authority_story_narrative_search_candidate
                ENABLE TRIGGER authority_story_narrative_membership_identity_immutable
                """
            )
            uow.commit()

    loss_key = f"branch-reconciliation-loss:{orphan.opening_run_id}"
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
        idempotency_key=f"branch-reconciliation-assess:{orphan.opening_run_id}",
        principal=orphan.principal,
    )
    orphan.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"branch-reconciliation-recover:{orphan.opening_run_id}",
        reason="create an exact live successor for branch reconciliation",
        principal=orphan.principal,
        expected_opening_run_id=orphan.opening_run_id,
    )
    claim = orphan.opening.claim_next_legacy_execution(
        worker_id=f"branch-reconciliation-worker:{orphan.opening_run_id}",
        lease_seconds=60,
        project_id=orphan.project_id,
    )
    assert claim is not None
    opening = orphan.opening.require(orphan.opening_run_id)
    orphan.opening._bind_running_execution(  # noqa: SLF001
        orphan.opening_run_id,
        expected_version=int(opening["version"]),
        runtime_claim=claim,
    )
    state = orphan.planning.story_design.require(
        project_id=orphan.project_id,
        asset_version_id=str(row[2]),
    )
    return _LiveLegacyBranch(
        orphan=orphan,
        claim=claim,
        search_id=str(row[0]),
        branch_key=str(row[1]),
        result=PlanningGenerationResult(
            generation_operation_id=str(row[3]),
            candidate_asset_version_id=str(row[2]),
            status=PlanningGenerationStatus(str(row[4])),
            story_design_state=state,
            replayed=True,
        ),
    )


def _commit_branch(fixture: _LiveLegacyBranch):
    orphan = fixture.orphan

    def commit_in_uow(uow: AuthorityUnitOfWork):
        try:
            return orphan.opening.narrative_search.register_qualified_branch_in_uow(
                uow,
                search_id=fixture.search_id,
                branch_key=fixture.branch_key,
                result=fixture.result,
            )
        except KernelError as exc:
            if exc.code != "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED":
                raise
        return orphan.opening.narrative_search.reconcile_legacy_qualified_branch_in_uow(
            uow,
            search_id=fixture.search_id,
            branch_key=fixture.branch_key,
            result=fixture.result,
            opening_run_id=orphan.opening_run_id,
            opening_execution_id=str(
                fixture.claim.input_snapshot["opening_execution_id"]
            ),
            execution_generation=int(
                fixture.claim.input_snapshot["execution_generation"]
            ),
        )

    return orphan.opening.recovery.commit_execution_narrative_search_branch(
        orphan.opening_run_id,
        runtime_claim=fixture.claim,
        search_id=fixture.search_id,
        branch_key=fixture.branch_key,
        branch_committer=commit_in_uow,
    )


def _projection(fixture: _LiveLegacyBranch) -> tuple[int, ...]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT
              (SELECT COUNT(*)
               FROM authority_story_narrative_branch_reconciliation_evidence
               WHERE membership_id=%s),
              (SELECT COUNT(*)
               FROM authority_book_opening_branch_reconciliation_assessment
               WHERE opening_run_id=%s),
              (SELECT COUNT(*)
               FROM authority_book_opening_branch_reconciliation_receipt
               WHERE opening_run_id=%s),
              (SELECT COUNT(*)
               FROM authority_book_opening_semantic_checkpoint
               WHERE opening_run_id=%s
                 AND semantic_work_key=%s),
              (SELECT COUNT(*) FROM state_event
               WHERE aggregate_id=%s
                 AND event_type='book.opening.branch_reconciled'),
              (SELECT COUNT(*) FROM outbox_event
               WHERE topic='book.opening.branch_reconciled'
                 AND payload->>'membership_id'=%s)
            """,
            [
                (
                    f"narrative-search-candidate:{fixture.search_id}:"
                    f"{fixture.branch_key}"
                ),
                fixture.orphan.opening_run_id,
                fixture.orphan.opening_run_id,
                fixture.orphan.opening_run_id,
                (f"narrative-search-branch:{fixture.search_id}:{fixture.branch_key}"),
                fixture.orphan.opening_run_id,
                (
                    f"narrative-search-candidate:{fixture.search_id}:"
                    f"{fixture.branch_key}"
                ),
            ],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return tuple(int(value) for value in row)


def test_legacy_branch_reconciliation_rolls_back_every_layer_then_retries() -> None:
    fixture = _prepare_live_legacy_branch()
    before_operations = _semantic_operation_count(fixture)

    def fail_after_event(point: str) -> None:
        if point == "after_branch_reconciliation_event":
            raise RuntimeError("simulated process loss before reconciliation receipt")

    fixture.orphan.opening.recovery.fault_injector = fail_after_event
    with pytest.raises(RuntimeError, match="simulated process loss"):
        _commit_branch(fixture)
    assert _projection(fixture) == (0, 0, 0, 0, 0, 0)

    fixture.orphan.opening.recovery.fault_injector = None
    first = _commit_branch(fixture)
    replay = _commit_branch(fixture)

    assert first.reconciliation_evidence_id == replay.reconciliation_evidence_id
    assert first.evidence_hash == replay.evidence_hash
    assert replay.replayed is True
    assert _projection(fixture) == (1, 1, 1, 1, 1, 1)
    assert _semantic_operation_count(fixture) == before_operations


def test_duplicate_concurrent_reconciliation_has_one_receipt_and_checkpoint() -> None:
    fixture = _prepare_live_legacy_branch()
    barrier = Barrier(2)

    def commit() -> tuple[str, str]:
        barrier.wait(timeout=10)
        evidence = _commit_branch(fixture)
        return evidence.reconciliation_evidence_id, evidence.evidence_hash

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: commit(), range(2)))

    assert results[0] == results[1]
    assert _projection(fixture) == (1, 1, 1, 1, 1, 1)


def _semantic_operation_count(fixture: _LiveLegacyBranch) -> int:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*) FROM authority_operation
            WHERE project_id=%s
              AND definition_name='story_design.semantic_evaluate'
            """,
            [fixture.orphan.project_id],
        )
        return int(uow.cursor.fetchone()[0])
