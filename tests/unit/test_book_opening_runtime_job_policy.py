from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.opening import (
    PostgresBookOpeningApplication,
)
from novel_forge.modules.runtime_job import (
    AUTHORITY_CONVERGENCE_REQUIRED,
    BOOK_OPENING_LEGACY_JOB_KIND,
    BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    BOOK_OPENING_WORKFLOW_JOB_KIND,
    BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.workers import book_authority as book_authority_worker
from novel_forge.workers.book_authority import (
    claim_next_book_opening_execution,
    execute_book_opening_node_claim,
    execute_claimed_book_opening_execution,
)


def _book_opening_spec(*, max_attempts: int = 1) -> RuntimeJobSpec:
    return RuntimeJobSpec(
        job_kind="BOOK_OPENING_EXECUTE",
        runtime_group="book_opening",
        subject_kind="BOOK_OPENING_RUN",
        subject_id="book-opening:policy-test",
        project_id="project:policy-test",
        dedupe_key="book-opening:policy-test:generation:1",
        input_snapshot={"execution_generation": 1},
        max_attempts=max_attempts,
        lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
    )


def test_book_opening_runtime_job_allows_only_one_attempt() -> None:
    assert _book_opening_spec().max_attempts == 1

    with pytest.raises(ValueError, match="exactly one RuntimeJob attempt"):
        _book_opening_spec(max_attempts=2)


def test_workflow_node_runtime_identity_is_not_claimable_by_legacy_workers() -> None:
    legacy = _book_opening_spec()
    workflow = RuntimeJobSpec(
        job_kind=BOOK_OPENING_WORKFLOW_JOB_KIND,
        runtime_group=BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
        subject_kind="BOOK_OPENING_RUN",
        subject_id="book-opening:workflow-policy-test",
        project_id="project:policy-test",
        dedupe_key="book-opening:workflow-policy-test:node:1",
        input_snapshot={
            "execution_generation": 1,
            "workflow_contract_version": "book-opening-workflow-v1",
        },
        max_attempts=1,
        lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
    )

    assert (legacy.job_kind, legacy.runtime_group) == (
        BOOK_OPENING_LEGACY_JOB_KIND,
        BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    )
    assert (workflow.job_kind, workflow.runtime_group) == (
        "BOOK_OPENING_WORKFLOW_NODE_EXECUTE",
        "book_opening_workflow_v1",
    )
    assert workflow.runtime_job_id != legacy.runtime_job_id


def test_book_opening_claim_seams_select_exact_versioned_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def capture_contract(
        _application: PostgresBookOpeningApplication, **arguments: object
    ) -> None:
        observed.append(str(arguments["workflow_contract_version"]))

    monkeypatch.setattr(
        PostgresBookOpeningApplication,
        "_claim_next_execution_for_contract",
        capture_contract,
    )
    application = object.__new__(PostgresBookOpeningApplication)

    application.claim_next_execution(worker_id="v3-alias", lease_seconds=30)
    application.claim_next_node_execution(worker_id="v3-worker", lease_seconds=30)
    application.claim_next_legacy_execution(
        worker_id="legacy-drain-worker", lease_seconds=30
    )

    assert observed == [
        "book-opening-workflow-v1",
        "book-opening-workflow-v1",
        "legacy-monolithic-v2",
    ]


def test_workflow_node_execute_seam_rejects_a_legacy_claim() -> None:
    legacy_claim = RuntimeJobClaim(
        runtime_job_id="runtime-job:legacy",
        job_kind=BOOK_OPENING_LEGACY_JOB_KIND,
        runtime_group=BOOK_OPENING_LEGACY_RUNTIME_GROUP,
        subject_kind="BOOK_OPENING_RUN",
        subject_id="book-opening:legacy",
        project_id="project:legacy",
        attempt_id="runtime-attempt:legacy",
        attempt_number=1,
        worker_id="legacy-worker",
        lease_id="runtime-lease:legacy",
        fencing_token=1,
        lease_expires_at=datetime.now(timezone.utc),
        input_snapshot={},
    )

    with pytest.raises(RuntimeError, match="workflow-v1"):
        execute_book_opening_node_claim(  # type: ignore[arg-type]
            object(), object(), object(), legacy_claim
        )


@pytest.mark.parametrize(
    ("job_kind", "runtime_group"),
    [
        (BOOK_OPENING_WORKFLOW_JOB_KIND, BOOK_OPENING_LEGACY_RUNTIME_GROUP),
        (BOOK_OPENING_LEGACY_JOB_KIND, BOOK_OPENING_WORKFLOW_RUNTIME_GROUP),
    ],
)
def test_book_opening_runtime_identity_rejects_cross_version_pairs(
    job_kind: str, runtime_group: str
) -> None:
    with pytest.raises(ValueError, match="operational contract"):
        RuntimeJobSpec(
            job_kind=job_kind,
            runtime_group=runtime_group,
            subject_kind="BOOK_OPENING_RUN",
            subject_id="book-opening:cross-version",
            project_id="project:policy-test",
            dedupe_key="book-opening:cross-version",
            input_snapshot={"execution_generation": 1},
            max_attempts=1,
            lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
        )


def _claim(
    *,
    job_kind: str,
    runtime_group: str,
    workflow_contract_version: str = "",
) -> RuntimeJobClaim:
    return RuntimeJobClaim(
        runtime_job_id=f"runtime-job:{runtime_group}",
        job_kind=job_kind,
        runtime_group=runtime_group,
        subject_kind="BOOK_OPENING_RUN",
        subject_id="book-opening:runtime-drain",
        project_id="project:runtime-drain",
        attempt_id=f"runtime-attempt:{runtime_group}",
        attempt_number=1,
        worker_id="book-worker",
        lease_id=f"runtime-lease:{runtime_group}",
        fencing_token=1,
        lease_expires_at=datetime.now(timezone.utc),
        input_snapshot={
            **(
                {"workflow_contract_version": workflow_contract_version}
                if workflow_contract_version
                else {}
            ),
            "observed_version": 1,
        },
    )


def test_production_claim_falls_through_to_exact_legacy_drain_after_v3_is_empty() -> (
    None
):
    calls: list[str] = []
    legacy = _claim(
        job_kind=BOOK_OPENING_LEGACY_JOB_KIND,
        runtime_group=BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    )
    opening = SimpleNamespace(
        claim_next_node_execution=lambda **_kwargs: calls.append("v3") or None,
        claim_next_legacy_execution=lambda **_kwargs: calls.append("legacy") or legacy,
    )

    claimed = claim_next_book_opening_execution(
        opening,  # type: ignore[arg-type]
        worker_id="book-worker",
        lease_seconds=30,
    )

    assert claimed is legacy
    assert calls == ["v3", "legacy"]


def test_production_claim_never_crosses_to_legacy_when_v3_is_available() -> None:
    workflow = _claim(
        job_kind=BOOK_OPENING_WORKFLOW_JOB_KIND,
        runtime_group=BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
        workflow_contract_version="book-opening-workflow-v1",
    )
    opening = SimpleNamespace(
        claim_next_node_execution=lambda **_kwargs: workflow,
        claim_next_legacy_execution=lambda **_kwargs: pytest.fail(
            "legacy drain must not run while v3 work is claimable"
        ),
    )

    claimed = claim_next_book_opening_execution(
        opening,  # type: ignore[arg-type]
        worker_id="book-worker",
        lease_seconds=30,
    )

    assert claimed is workflow


def test_production_dispatch_executes_legacy_successor_only_via_legacy_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = _claim(
        job_kind=BOOK_OPENING_LEGACY_JOB_KIND,
        runtime_group=BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    )
    calls: list[RuntimeJobClaim] = []
    monkeypatch.setattr(
        book_authority_worker,
        "execute_legacy_book_opening_claim",
        lambda *_args, **_kwargs: calls.append(legacy) or {"lifecycle": "COMPLETE"},
    )
    monkeypatch.setattr(
        book_authority_worker,
        "execute_book_opening_node_claim",
        lambda *_args, **_kwargs: pytest.fail("legacy work crossed into v3 executor"),
    )

    result = execute_claimed_book_opening_execution(  # type: ignore[arg-type]
        object(), object(), object(), legacy
    )

    assert result == {"lifecycle": "COMPLETE"}
    assert calls == [legacy]


def test_production_dispatch_rejects_cross_pair_before_any_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crossed = _claim(
        job_kind=BOOK_OPENING_WORKFLOW_JOB_KIND,
        runtime_group=BOOK_OPENING_LEGACY_RUNTIME_GROUP,
        workflow_contract_version="book-opening-workflow-v1",
    )
    monkeypatch.setattr(
        book_authority_worker,
        "execute_legacy_book_opening_claim",
        lambda *_args, **_kwargs: pytest.fail("cross pair reached legacy executor"),
    )
    monkeypatch.setattr(
        book_authority_worker,
        "execute_book_opening_node_claim",
        lambda *_args, **_kwargs: pytest.fail("cross pair reached v3 executor"),
    )

    with pytest.raises(RuntimeError, match="unsupported contract pair"):
        execute_claimed_book_opening_execution(  # type: ignore[arg-type]
            object(), object(), object(), crossed
        )
