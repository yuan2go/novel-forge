from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.book_opening_workflow_postgres_support import (
    OneShotFaultInjector,
    SimulatedWorkflowProcessLoss,
    as_mapping,
    build_workflow_fixture,
    claim_node_kind,
)


@pytest.fixture(scope="module", autouse=True)
def _migrations() -> None:
    ensure_migrated()


def _process_loss(point: str) -> SimulatedWorkflowProcessLoss:
    return SimulatedWorkflowProcessLoss(f"injected process loss at {point}")


def _expire_runtime_claim(lease_id: str) -> None:
    """Advance only the disposable PostgreSQL fixture's lease clock boundary."""

    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            UPDATE authority_runtime_job_lease
            SET lease_expires_at=clock_timestamp()-INTERVAL '1 second'
            WHERE lease_id=%s
            """,
            [lease_id],
        )
        assert uow.cursor.rowcount == 1
        uow.commit()


def _node_outbox_count(*, project_id: str, workflow_node_id: str) -> int:
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            """
            SELECT COUNT(*)
            FROM outbox_event
            WHERE project_id=%s
              AND topic='book.opening.transitioned'
              AND payload->>'workflow_node_id'=%s
            """,
            [project_id, workflow_node_id],
        )
        row = uow.cursor.fetchone()
    assert row is not None
    return int(row[0])


def test_node_completion_response_loss_replays_receipt_without_provider_send() -> None:
    fault = OneShotFaultInjector(
        "after_workflow_node_completion_commit",
        exception_factory=_process_loss,
    )
    fixture = build_workflow_fixture(fault_injector=fault)
    admission = fixture.admit()
    claim = fixture.claim("book-opening-response-loss:first")
    assert claim is not None
    assert claim_node_kind(claim) == "BOOK_PLAN"

    with pytest.raises(SimulatedWorkflowProcessLoss):
        fixture.execute(claim)
    assert fault.triggered is True
    provider_calls = tuple(fixture.binder.generator_calls)

    durable = fixture.progress(admission.opening_run_id)
    assert as_mapping(durable["furthest_completed_layer"])["node_kind"] == ("BOOK_PLAN")
    assert as_mapping(durable["persistent_checkpoint"])["status"] == "AVAILABLE"
    assert fixture.runtime_jobs.get(claim.runtime_job_id)["status"] == "SUCCEEDED"
    assert (
        _node_outbox_count(
            project_id=fixture.project_id,
            workflow_node_id=str(claim.input_snapshot["workflow_node_id"]),
        )
        == 1
    )

    replay = as_mapping(fixture.execute(claim))
    assert replay["workflow_node_id"] == claim.input_snapshot["workflow_node_id"]
    assert replay["node_kind"] == "BOOK_PLAN"
    assert replay["status"] == "SUCCEEDED"
    assert replay["replayed"] is True
    assert tuple(fixture.binder.generator_calls) == provider_calls
    assert (
        _node_outbox_count(
            project_id=fixture.project_id,
            workflow_node_id=str(claim.input_snapshot["workflow_node_id"]),
        )
        == 1
    )

    successor = fixture.claim("book-opening-response-loss:successor")
    assert successor is not None
    assert successor.runtime_job_id == replay["successor_runtime_job_id"]
    assert claim_node_kind(successor) == "VOLUME_PORTFOLIO"


def test_node_receipt_failpoint_rolls_back_outer_completion_as_one_unit() -> None:
    fault = OneShotFaultInjector(
        "after_workflow_node_receipt_insert",
        exception_factory=_process_loss,
    )
    fixture = build_workflow_fixture(fault_injector=fault)
    admission = fixture.admit()
    claim = fixture.claim("book-opening-transaction-loss:first")
    assert claim is not None

    with pytest.raises(SimulatedWorkflowProcessLoss):
        fixture.execute(claim)
    assert fault.triggered is True
    provider_calls = tuple(fixture.binder.generator_calls)

    rolled_back = fixture.progress(admission.opening_run_id)
    assert rolled_back["furthest_completed_layer"] is None
    assert as_mapping(rolled_back["reviewable_artifact"])["status"] != "AVAILABLE"
    assert as_mapping(rolled_back["persistent_checkpoint"])["status"] != "AVAILABLE"
    assert [as_mapping(node)["lifecycle"] for node in rolled_back["nodes"]] == [
        "RUNNING",
        "PENDING",
        "PENDING",
        "PENDING",
        "PENDING",
    ]
    assert fixture.runtime_jobs.get(claim.runtime_job_id)["status"] != "SUCCEEDED"
    assert (
        _node_outbox_count(
            project_id=fixture.project_id,
            workflow_node_id=str(claim.input_snapshot["workflow_node_id"]),
        )
        == 0
    )

    completed = as_mapping(fixture.execute(claim))
    assert completed["node_kind"] == "BOOK_PLAN"
    assert completed["status"] == "SUCCEEDED"
    assert tuple(fixture.binder.generator_calls) == provider_calls
    converged = fixture.progress(admission.opening_run_id)
    assert as_mapping(converged["furthest_completed_layer"])["node_kind"] == (
        "BOOK_PLAN"
    )
    assert as_mapping(converged["persistent_checkpoint"])["status"] == "AVAILABLE"
    assert (
        _node_outbox_count(
            project_id=fixture.project_id,
            workflow_node_id=str(claim.input_snapshot["workflow_node_id"]),
        )
        == 1
    )


def test_inner_search_success_before_outer_completion_recovers_without_resend() -> None:
    """The bounded inner/outer tear converges through the production recovery path."""

    fault = OneShotFaultInjector(
        "after_workflow_node_payload",
        exception_factory=_process_loss,
    )
    fixture = build_workflow_fixture(fault_injector=fault)
    admission = fixture.admit()
    claim = fixture.claim("book-opening-inner-outer-tear:lost-worker")
    assert claim is not None
    assert claim_node_kind(claim) == "BOOK_PLAN"

    with pytest.raises(SimulatedWorkflowProcessLoss):
        fixture.execute(claim)
    assert fault.triggered is True
    sent_before_recovery = tuple(fixture.binder.generator_calls)
    assert sent_before_recovery

    progress = fixture.progress(admission.opening_run_id)
    assert progress["furthest_completed_layer"] is None
    assert as_mapping(progress["current_execution_checkpoint"])["status"] == (
        "AVAILABLE"
    )
    assert (
        as_mapping(progress["current_execution_checkpoint"])["layer_completion"]
        is False
    )

    _expire_runtime_claim(claim.lease_id)
    loss_key = f"inner-outer-tear:{admission.opening_run_id}"
    loss = fixture.opening.recovery.assess_execution_loss(
        admission.opening_run_id,
        idempotency_key=loss_key,
        principal=fixture.principal,
    )
    fixture.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=fixture.principal,
        expected_opening_run_id=admission.opening_run_id,
    )
    assessment = fixture.opening.recovery.assess_recovery(
        admission.opening_run_id,
        idempotency_key=f"{loss_key}:assessment",
        principal=fixture.principal,
    )
    assert assessment.disposition not in {
        "UNKNOWN_AMBIGUOUS",
        "RECONCILIATION_REQUIRED",
    }
    fixture.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"{loss_key}:recover",
        reason="resume the durable selected Book Plan without Provider replay",
        principal=fixture.principal,
        expected_opening_run_id=admission.opening_run_id,
    )

    recovered = fixture.claim("book-opening-inner-outer-tear:replacement-worker")
    assert recovered is not None
    assert recovered.runtime_job_id != claim.runtime_job_id
    assert recovered.job_kind == "BOOK_OPENING_WORKFLOW_NODE_EXECUTE"
    assert recovered.runtime_group == "book_opening_workflow_v1"
    result = as_mapping(fixture.execute(recovered))
    assert result["node_kind"] == "BOOK_PLAN"
    assert result["status"] == "SUCCEEDED"
    assert tuple(fixture.binder.generator_calls) == sent_before_recovery
    converged = fixture.progress(admission.opening_run_id)
    assert as_mapping(converged["furthest_completed_layer"])["node_kind"] == (
        "BOOK_PLAN"
    )


def test_expired_node_execution_recovers_the_same_node_with_a_new_job() -> None:
    fixture = build_workflow_fixture()
    admission = fixture.admit()
    lost_claim = fixture.claim("book-opening-node-loss:lost-worker")
    assert lost_claim is not None
    assert claim_node_kind(lost_claim) == "BOOK_PLAN"
    _expire_runtime_claim(lost_claim.lease_id)

    loss_key = f"node-loss:{admission.opening_run_id}:book-plan"
    loss = fixture.opening.recovery.assess_execution_loss(
        admission.opening_run_id,
        idempotency_key=loss_key,
        principal=fixture.principal,
    )
    converged = fixture.opening.recovery.converge_execution_loss(
        loss.recovery_assessment_id,
        idempotency_key=loss_key,
        principal=fixture.principal,
        expected_opening_run_id=admission.opening_run_id,
    )
    assert converged.result["execution_lifecycle"] == "LOST"
    assert fixture.runtime_jobs.get(lost_claim.runtime_job_id)["status"] == "FAILED"

    assessment = fixture.opening.recovery.assess_recovery(
        admission.opening_run_id,
        idempotency_key=f"{loss_key}:assessment",
        principal=fixture.principal,
    )
    assert assessment.disposition == "PROVEN_NO_EFFECT"
    fixture.opening.recovery.recover(
        assessment.recovery_assessment_id,
        idempotency_key=f"{loss_key}:recover",
        reason="resume the exact lost Book Plan workflow node",
        principal=fixture.principal,
        expected_opening_run_id=admission.opening_run_id,
    )

    with pytest.raises(KernelError) as stale_heartbeat:
        fixture.runtime_jobs.heartbeat(lost_claim, lease_seconds=30)
    assert stale_heartbeat.value.code == "RUNTIME_JOB_FENCE_STALE"
    assert fixture.binder.generator_calls == []

    recovered_claim = fixture.claim("book-opening-node-loss:replacement-worker")
    assert recovered_claim is not None
    assert recovered_claim.runtime_job_id != lost_claim.runtime_job_id
    assert recovered_claim.job_kind == "BOOK_OPENING_WORKFLOW_NODE_EXECUTE"
    assert recovered_claim.runtime_group == "book_opening_workflow_v1"
    assert claim_node_kind(recovered_claim) == "BOOK_PLAN"
    assert (
        recovered_claim.input_snapshot["workflow_node_id"]
        == (lost_claim.input_snapshot["workflow_node_id"])
    )
    progress = fixture.progress(admission.opening_run_id)
    assert progress["furthest_completed_layer"] is None
    assert as_mapping(progress["current_layer"])["node_kind"] == "BOOK_PLAN"

    completed = as_mapping(fixture.execute(recovered_claim))
    assert completed["node_kind"] == "BOOK_PLAN"
    assert completed["status"] == "SUCCEEDED"
