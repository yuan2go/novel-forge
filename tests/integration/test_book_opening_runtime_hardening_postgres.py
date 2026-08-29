from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import (
    AUTHORITY_CONVERGENCE_REQUIRED,
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration.book_opening_recovery_postgres_support import (
    create_legacy_book_opening_orphan,
)


@pytest.fixture(scope="module", autouse=True)
def _migrations() -> None:
    ensure_migrated()


def _schedule_opening_job(
    *, authority: RuntimeJobAuthority, suffix: str
) -> dict[str, object]:
    subject_id = identifier(f"book-opening-{suffix}")
    project_id = identifier(f"book-opening-project-{suffix}")
    return authority.schedule(
        RuntimeJobSpec(
            job_kind="BOOK_OPENING_EXECUTE",
            runtime_group="book_opening",
            subject_kind="BOOK_OPENING_RUN",
            subject_id=subject_id,
            project_id=project_id,
            dedupe_key=f"{subject_id}:execution-generation:1",
            input_snapshot={
                "opening_run_id": subject_id,
                "execution_generation": 1,
            },
            max_attempts=1,
            lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
        )
    )


def _authority_claim(
    authority: RuntimeJobAuthority, runtime_job_id: str, *, worker_id: str
) -> RuntimeJobClaim:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        claim = authority.claim_ready_in_uow(
            uow,
            runtime_job_id=runtime_job_id,
            worker_id=worker_id,
            lease_seconds=30,
        )
        uow.commit()
    return claim


def _start_authority_claim(
    authority: RuntimeJobAuthority, claim: RuntimeJobClaim
) -> dict[str, object]:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        started = authority.start_authority_owned_in_uow(uow, claim)
        uow.commit()
    return started


def test_book_opening_job_requires_authority_coordinated_first_claim() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="claim-plane")
    runtime_job_id = str(scheduled["runtime_job_id"])

    generic = authority.claim(
        runtime_group="book_opening",
        worker_id="generic-book-opening-worker",
        lease_seconds=30,
        job_kinds=("BOOK_OPENING_EXECUTE",),
    )
    assert generic is None

    claim = _authority_claim(
        authority,
        runtime_job_id,
        worker_id="authority-coordinated-book-opening-worker",
    )
    assert claim.runtime_job_id == runtime_job_id
    assert claim.attempt_number == 1
    assert claim.fencing_token == 1
    assert authority.get(runtime_job_id)["status"] == "CLAIMED"
    with pytest.raises(KernelError) as blocked:
        authority.start(claim)
    assert blocked.value.code == "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED"
    assert authority.get(runtime_job_id)["status"] == "CLAIMED"


def test_runtime_job_start_replays_the_exact_live_claim_after_response_loss() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="start-replay")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-start-replay-worker",
    )

    started = _start_authority_claim(authority, claim)
    replayed = _start_authority_claim(authority, claim)

    assert started == {
        "runtime_job_id": claim.runtime_job_id,
        "attempt_id": claim.attempt_id,
        "status": "RUNNING",
        "replayed": False,
    }
    assert replayed == {**started, "replayed": True}


def test_assert_live_rechecks_the_exact_claim_against_database_time() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="assert-live")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-live-probe-worker",
    )
    _start_authority_claim(authority, claim)

    live = authority.assert_live(claim)
    assert live == {
        "runtime_job_id": claim.runtime_job_id,
        "attempt_id": claim.attempt_id,
        "status": "RUNNING",
        "fencing_token": claim.fencing_token,
        "lease_expires_at": claim.lease_expires_at,
    }

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [claim.lease_id],
        )
        uow.commit()
    with pytest.raises(KernelError) as stale:
        authority.assert_live(claim)
    assert stale.value.code == "RUNTIME_JOB_FENCE_STALE"


@pytest.mark.parametrize(
    "field,value",
    (
        ("attempt_id", "runtime-attempt:forged"),
        ("lease_id", "runtime-lease:forged"),
        ("worker_id", "forged-worker"),
        ("fencing_token", 999),
    ),
)
def test_assert_live_rejects_any_relational_claim_drift(
    field: str, value: str | int
) -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(
        authority=authority,
        suffix=f"assert-exact-{field}",
    )
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id=f"book-opening-exact-{field}-worker",
    )
    _start_authority_claim(authority, claim)

    with pytest.raises(KernelError) as stale:
        authority.assert_live(replace(claim, **{field: value}))
    assert stale.value.code == "RUNTIME_JOB_FENCE_STALE"
    assert authority.assert_live(claim)["status"] == "RUNNING"


def test_generic_completion_cannot_terminalize_a_book_opening_job() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="generic-complete")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-generic-complete-worker",
    )
    _start_authority_claim(authority, claim)

    with pytest.raises(KernelError) as blocked:
        authority.complete(claim, {"forbidden": "generic completion"})
    assert blocked.value.code == "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED"
    assert authority.assert_live(claim)["status"] == "RUNNING"


def test_internal_completion_cannot_bypass_the_frozen_checkpoint_graph() -> None:
    orphan = create_legacy_book_opening_orphan()
    run = orphan.opening.require(orphan.opening_run_id)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        authoritative_run = orphan.opening.recovery._opening(
            uow, orphan.opening_run_id, lock=False
        )
        expected_search_ids = list(
            orphan.opening.recovery._expected_search_graph(
                authoritative_run
            ).values()
        )

    forged_result = {
        "book_design_version": "asset-version:forged-book-design",
        "book_plan_version": "asset-version:forged-book-plan",
        "volume_plan_version": "asset-version:forged-volume-plan",
        "arc_plan_versions": ["asset-version:forged-arc-plan"],
        "input_snapshot_id": "book-input-snapshot:forged",
        "search_ids": expected_search_ids,
    }
    with pytest.raises(KernelError) as blocked:
        orphan.opening._control(
            run=run,
            principal=orphan.principal,
            definition_name="book.opening.complete",
            idempotency_key=f"{orphan.opening_run_id}:forged-completion",
            payload={
                "expected_version": int(run["version"]),
                "result": forged_result,
                "runtime_claim": orphan.opening._runtime_claim_payload(
                    orphan.outer_claim
                ),
            },
        )
    assert blocked.value.code == "BOOK_OPENING_COMPLETION_CHECKPOINT_REQUIRED"
    assert orphan.opening.require(orphan.opening_run_id)["lifecycle"] == "RUNNING"


def test_generic_failure_cannot_retry_or_terminalize_a_book_opening_job() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="generic-fail")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-generic-fail-worker",
    )
    _start_authority_claim(authority, claim)

    with pytest.raises(KernelError) as blocked:
        authority.fail(claim, {"forbidden": "generic failure"})
    assert blocked.value.code == "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED"
    assert authority.assert_live(claim)["status"] == "RUNNING"


def test_generic_continuation_cannot_replace_a_book_opening_execution() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="continuation")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-continuation-worker",
    )
    _start_authority_claim(authority, claim)
    continuation = RuntimeJobSpec(
        job_kind="BOOK_OPENING_EXECUTE",
        runtime_group="book_opening",
        subject_kind="BOOK_OPENING_RUN",
        subject_id=claim.subject_id,
        project_id=claim.project_id,
        dedupe_key=f"{claim.subject_id}:execution-generation:2",
        input_snapshot={"opening_run_id": claim.subject_id, "execution_generation": 2},
        max_attempts=1,
        lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
    )

    with pytest.raises(KernelError) as blocked:
        authority.complete_and_schedule_continuation(
            claim,
            {"forbidden": "generic continuation"},
            continuation,
        )
    assert blocked.value.code == "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED"
    assert authority.assert_live(claim)["status"] == "RUNNING"
    with pytest.raises(KernelError) as missing:
        authority.get(continuation.runtime_job_id)
    assert missing.value.code == "RUNTIME_JOB_NOT_FOUND"


def test_generic_pending_cancel_cannot_supersede_a_book_opening_execution() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="pending-cancel")
    job = authority.get(str(scheduled["runtime_job_id"]))

    with pytest.raises(KernelError) as blocked:
        authority.cancel_pending_for_subject(
            job_kind="BOOK_OPENING_EXECUTE",
            runtime_group="book_opening",
            subject_kind="BOOK_OPENING_RUN",
            subject_id=str(job["subject_id"]),
            project_id=str(job["project_id"]),
            reason="forbidden generic cancel",
        )
    assert blocked.value.code == "RUNTIME_JOB_AUTHORITY_COORDINATOR_REQUIRED"
    assert authority.get(str(scheduled["runtime_job_id"]))["status"] == "READY"


def test_execution_loss_replay_is_bound_to_the_exact_terminal_reason() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="loss-replay")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-loss-replay-worker",
    )
    _start_authority_claim(authority, claim)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [claim.lease_id],
        )
        uow.commit()

    def terminalize(reason: dict[str, object]) -> dict[str, object]:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            result = authority.terminalize_execution_loss_in_uow(
                uow,
                runtime_job_id=claim.runtime_job_id,
                expected_attempt_id=claim.attempt_id,
                expected_lease_id=claim.lease_id,
                expected_fencing_token=claim.fencing_token,
                reason=reason,
            )
            uow.commit()
        return result

    reason = {"code": "OUTER_LEASE_EXPIRED", "assessment_id": "assessment:one"}
    first = terminalize(reason)
    replay = terminalize(reason)
    assert first["replayed"] is False
    assert replay == {**first, "replayed": True}

    with pytest.raises(KernelError) as conflict:
        terminalize({**reason, "assessment_id": "assessment:different"})
    assert conflict.value.code == "RUNTIME_JOB_LOSS_IDEMPOTENCY_CONFLICT"


def test_authority_failure_replay_is_bound_to_the_exact_terminal_error() -> None:
    authority = RuntimeJobAuthority(DATABASE_URL)
    scheduled = _schedule_opening_job(authority=authority, suffix="failure-replay")
    claim = _authority_claim(
        authority,
        str(scheduled["runtime_job_id"]),
        worker_id="book-opening-failure-replay-worker",
    )
    _start_authority_claim(authority, claim)

    def terminalize(error: dict[str, object]) -> dict[str, object]:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            result = authority.terminalize_authority_failure_in_uow(
                uow,
                claim,
                error,
            )
            uow.commit()
        return result

    error = {"code": "PLANNING_FAILED", "message": "durable failure"}
    first = terminalize(error)
    replay = terminalize(error)
    assert first["replayed"] is False
    assert replay == {**first, "replayed": True}

    with pytest.raises(KernelError) as conflict:
        terminalize({**error, "message": "different failure"})
    assert conflict.value.code == "RUNTIME_JOB_FAILURE_IDEMPOTENCY_CONFLICT"


def test_book_opening_failure_commit_response_loss_replays_exactly() -> None:
    orphan = create_legacy_book_opening_orphan(terminalize_evaluation=False)
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=transaction_timestamp()+INTERVAL '30 seconds'
            WHERE lease_id=%s
            """,
            [orphan.outer_claim.lease_id],
        )
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_attempt
            SET lease_expires_at=transaction_timestamp()+INTERVAL '30 seconds'
            WHERE attempt_id=%s
            """,
            [orphan.outer_claim.attempt_id],
        )
        uow.commit()
    expected_version = int(orphan.opening.require(orphan.opening_run_id)["version"])
    error = {"code": "PLANNING_FAILED", "message": "durable opening failure"}

    orphan.opening.record_failure(
        orphan.opening_run_id,
        expected_version=expected_version,
        runtime_claim=orphan.outer_claim,
        error=error,
    )
    orphan.opening.record_failure(
        orphan.opening_run_id,
        expected_version=expected_version,
        runtime_claim=orphan.outer_claim,
        error=error,
    )

    failed = orphan.opening.require(orphan.opening_run_id)
    assert failed["lifecycle"] == "FAILED"
    assert failed["version"] == expected_version + 1
    assert failed["failure"] == error
    with pytest.raises(KernelError) as conflict:
        orphan.opening.record_failure(
            orphan.opening_run_id,
            expected_version=expected_version,
            runtime_claim=orphan.outer_claim,
            error={**error, "message": "different durable opening failure"},
        )
    assert conflict.value.code == "BOOK_OPENING_FAILURE_IDEMPOTENCY_CONFLICT"
