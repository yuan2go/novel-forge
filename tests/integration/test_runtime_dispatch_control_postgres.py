from uuid import uuid4

import psycopg
import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.dispatch_control import change_dispatch_control, dispatch_control_status, assert_dispatch_enabled
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, plan_external_effect, prepare_effect_dispatch
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, seed_authority_project_book, insert_definition, insert_operation


def _scope():
    ensure_migrated()
    project = "dispatch-control:" + uuid4().hex
    seed_authority_project_book(project_id=project, book_id="book:" + project)
    principal = Principal("operator", PrincipalType.LOCAL_OPERATOR, frozenset({"book.authority.execute"}), frozenset({project}), "test")
    return project, principal


def _change(project, principal, state, version, key):
    return change_dispatch_control(DATABASE_URL, project_id=project, principal=principal, state=state,
        expected_version=version, idempotency_key=key, reason="controlled restart",
        release_identity={"commit_sha": "a" * 40, "application_build_id": "test"})


def test_pause_resume_are_scoped_versioned_replayable_and_never_grant_eligibility(monkeypatch):
    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, principal = _scope()
    other, _ = _scope()
    with pytest.raises(KernelError, match="RUNTIME_CONTROL_PAUSE_REQUIRED"):
        _change(project, principal, "RUNNING", 0, "unsafe-initial-resume")
    first = _change(project, principal, "PAUSED", 0, "pause-1")
    assert first["version"] == 1
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        assert_dispatch_enabled(DATABASE_URL, project)
    assert_dispatch_enabled(DATABASE_URL, other)
    assert _change(project, principal, "PAUSED", 0, "pause-1")["replayed"]
    with pytest.raises(KernelError, match="RUNTIME_CONTROL_VERSION_CONFLICT"):
        _change(project, principal, "RUNNING", 0, "stale-resume")
    with pytest.raises(KernelError, match="RUNTIME_CONTROL_IDEMPOTENCY_CONFLICT"):
        _change(project, principal, "RUNNING", 0, "pause-1")
    resumed = _change(project, principal, "RUNNING", 1, "resume-1")
    assert resumed["version"] == 2
    assert resumed["authorization"] == "CONTROL_IS_NOT_BUDGET_OR_TASK_ADMISSION"
    assert_dispatch_enabled(DATABASE_URL, project)
    assert [event["state"] for event in dispatch_control_status(DATABASE_URL, project_id=project)["events"]] == ["PAUSED", "RUNNING"]
    with psycopg.connect(DATABASE_URL) as c:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            c.execute("DELETE FROM authority_runtime_dispatch_event WHERE project_id=%s", [project])


def test_paused_effect_keeps_intent_and_allocates_no_dispatch_generation(monkeypatch):
    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, principal = _scope()
    operation = "operation:" + uuid4().hex
    with psycopg.connect(DATABASE_URL) as c:
        name = "definition:" + uuid4().hex
        insert_definition(c.cursor(), name)
        insert_operation(c.cursor(), operation_id=operation, definition_name=name, project_id=project, status="EXECUTING")
    context = EffectCommandContext(operation, project, "operator", "trace", "correlation")
    effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke", provider="fake_deterministic_provider",
        capability="provider.test", stable_idempotency_key="effect:" + uuid4().hex,
        request_payload={"scenario": "success"}, max_attempts=3, reversible=False)
    _change(project, principal, "PAUSED", 0, "pause")
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect["external_effect_id"])
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s", [effect["external_effect_id"]]).fetchone() == ("READY",)
        assert c.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect["external_effect_id"]]).fetchone() == (0,)
    _change(project, principal, "RUNNING", 1, "resume")
    prepared = prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect["external_effect_id"])
    assert prepared["generation"] == 1


def test_project_pause_checkpoints_same_attempt_without_failure_or_unknown(monkeypatch):
    from psycopg.types.json import Jsonb
    from novel_forge.modules.command_kernel.attempt_runtime import (
        WorkerLeaseCommand, create_attempt, queue_attempt, acquire_attempt_lease, start_attempt, checkpoint_attempt_for_dispatch_pause,
    )
    from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClassifier, WorkerFailureClass
    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, principal = _scope()
    operation = "operation:" + uuid4().hex
    with psycopg.connect(DATABASE_URL) as c:
        name = "definition:" + uuid4().hex
        insert_definition(c.cursor(), name)
        c.execute("UPDATE authority_operation_definition SET external_capabilities=%s WHERE name=%s", [Jsonb(["model.test"]), name])
        insert_operation(c.cursor(), operation_id=operation, definition_name=name, project_id=project, status="READY")
    _change(project, principal, "PAUSED", 0, "initial-pause")
    arguments = dict(operation_id=operation, project_id=project, max_attempts=1, trace_id="pause-test", correlation_id="pause-test")
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        create_attempt(DATABASE_URL, **arguments)
    _change(project, principal, "RUNNING", 1, "initial-resume")
    attempt = create_attempt(DATABASE_URL, **arguments)
    queue_attempt(DATABASE_URL, attempt_id=attempt["attempt_id"], project_id=project, trace_id="pause-test", correlation_id="pause-test")
    lease_args = dict(attempt_id=attempt["attempt_id"], project_id=project, worker_id="pause-worker", lease_seconds=60, trace_id="pause-test", correlation_id="pause-test")
    lease = acquire_attempt_lease(DATABASE_URL, **lease_args)
    worker = WorkerLeaseCommand(attempt["attempt_id"], project, "pause-worker", lease["fencing_token"], "pause-test", "pause-test")
    start_attempt(DATABASE_URL, worker)
    _change(project, principal, "PAUSED", 2, "running-pause")
    assert WorkerFailureClassifier.classify(KernelError("RUNTIME_DISPATCH_PAUSED", "paused")) is WorkerFailureClass.DISPATCH_PAUSED
    checkpoint_attempt_for_dispatch_pause(DATABASE_URL, worker)
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        acquire_attempt_lease(DATABASE_URL, **lease_args)
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [operation]).fetchone() == ("EXECUTING",)
        assert c.execute("SELECT status,attempt_number FROM authority_attempt WHERE operation_id=%s", [operation]).fetchall() == [("CHECKPOINTED", 1)]
    _change(project, principal, "RUNNING", 3, "running-resume")
    resumed = acquire_attempt_lease(DATABASE_URL, **lease_args)
    assert resumed["fencing_token"] > lease["fencing_token"]
    start_attempt(DATABASE_URL, WorkerLeaseCommand(attempt["attempt_id"], project, "pause-worker", resumed["fencing_token"], "pause-test", "pause-test"))


def test_repeated_known_unsent_pause_does_not_exhaust_provider_retry_generation(monkeypatch):
    from novel_forge.modules.command_kernel.external_effect_runtime import dispatch_external_effect
    from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, principal = _scope()
    operation = "operation:" + uuid4().hex
    with psycopg.connect(DATABASE_URL) as c:
        name = "definition:" + uuid4().hex
        insert_definition(c.cursor(), name)
        insert_operation(c.cursor(), operation_id=operation, definition_name=name, project_id=project, status="EXECUTING")
    context = EffectCommandContext(operation, project, "operator", "trace", "correlation")
    effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke", provider="fake_deterministic_provider",
        capability="provider.test", stable_idempotency_key="late-pause:" + uuid4().hex,
        request_payload={"scenario": "success"}, max_attempts=1, reversible=False)
    from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, settle_provider_budget
    reservation_request = BudgetReservationRequest(operation_id=operation, external_effect_id=effect["external_effect_id"], project_id=project,
        stable_idempotency_key="pause-budget:" + effect["external_effect_id"], provider="fake_deterministic_provider",
        currency="USD", estimated_amount="1", estimated_tokens=1000, caps={"project_total": "1"})
    reservation = reserve_provider_budget(DATABASE_URL, reservation_request)
    class CountingProvider(FakeDeterministicProvider):
        count = 0
        def execute(self, **kwargs):
            self.count += 1
            return super().execute(**kwargs)
    provider = CountingProvider("success")
    for round_number in range(4):
        with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
            dispatch_external_effect(DATABASE_URL, context, effect_id=effect["external_effect_id"], worker_id="pause-worker", lease_seconds=30,
                adapter=provider, pre_send_assertion=lambda: _change(project, principal, "PAUSED", round_number * 2, "pause:" + str(round_number)))
        assert provider.count == 0
        replayed_reservation = reserve_provider_budget(DATABASE_URL, reservation_request)
        assert replayed_reservation["reservation_id"] == reservation["reservation_id"]
        assert replayed_reservation["execution_authorized"] and replayed_reservation["status"] == "RESERVED"
        _change(project, principal, "RUNNING", round_number * 2 + 1, "resume:" + str(round_number))
    result = dispatch_external_effect(DATABASE_URL, context, effect_id=effect["external_effect_id"], worker_id="pause-worker", lease_seconds=30, adapter=provider)
    assert result["outcome"] == "success" and provider.count == 1
    settle_provider_budget(DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=project,
        actual_amount="0.2", actual_tokens=100, evidence={"fixture": True, "real_model_call": False})
    with psycopg.connect(DATABASE_URL) as c:
        rows = c.execute("SELECT generation,status,evidence FROM authority_external_effect_dispatch WHERE external_effect_id=%s ORDER BY generation", [effect["external_effect_id"]]).fetchall()
        assert len(rows) == 5 and [row[0] for row in rows] == [1, 2, 3, 4, 5]
        assert all(row[1] == "FAILED_RETRYABLE" and row[2]["request_sent"] is False for row in rows[:4])


def test_project_pause_allows_unknown_receipt_reconciliation_without_new_send(monkeypatch):
    from novel_forge.modules.command_kernel.external_effect_runtime import dispatch_external_effect, reconcile_external_effect
    from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, principal = _scope()
    operation = "operation:" + uuid4().hex
    with psycopg.connect(DATABASE_URL) as c:
        name = "definition:" + uuid4().hex
        insert_definition(c.cursor(), name)
        insert_operation(c.cursor(), operation_id=operation, definition_name=name, project_id=project, status="EXECUTING")
    context = EffectCommandContext(operation, project, "operator", "trace", "correlation")
    effect = plan_external_effect(DATABASE_URL, context, effect_type="model.invoke", provider="fake_deterministic_provider",
        capability="provider.test", stable_idempotency_key="unknown-pause:" + uuid4().hex,
        request_payload={"scenario": "timeout_after"}, max_attempts=1, reversible=False)
    provider = FakeDeterministicProvider("timeout_after")
    dispatched = dispatch_external_effect(DATABASE_URL, context, effect_id=effect["external_effect_id"], worker_id="worker", lease_seconds=30, adapter=provider)
    assert dispatched["outcome"] == "unknown"
    _change(project, principal, "PAUSED", 0, "reconcile-paused")
    with pytest.raises(KernelError, match="RUNTIME_DISPATCH_PAUSED"):
        prepare_effect_dispatch(DATABASE_URL, context, effect_id=effect["external_effect_id"])
    reconciled = reconcile_external_effect(DATABASE_URL, context, effect_id=effect["external_effect_id"], adapter=provider)
    assert reconciled["outcome"] == "success" and reconciled["receipt_id"]
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT status FROM authority_external_effect WHERE external_effect_id=%s", [effect["external_effect_id"]]).fetchone() == ("SUCCEEDED",)
        assert c.execute("SELECT count(*) FROM authority_external_effect_dispatch WHERE external_effect_id=%s", [effect["external_effect_id"]]).fetchone() == (1,)


def test_runtime_job_pause_preserves_monotonic_history_without_exhausting_limit(monkeypatch):
    from novel_forge.modules.command_kernel.dispatch_control import RuntimeDispatchPaused
    from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec

    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, principal = _scope()
    jobs = RuntimeJobAuthority(DATABASE_URL)
    spec = RuntimeJobSpec(job_kind="BOOK_COORDINATION_TICK", runtime_group="book", subject_kind="BOOK_RUN",
        subject_id="pause-subject", project_id=project, dedupe_key="pause-max-one", input_snapshot={}, max_attempts=1)
    jobs.schedule(spec)
    claim_args = dict(runtime_group="book", worker_id="pause-worker", lease_seconds=60, project_id=project)
    _change(project, principal, "PAUSED", 0, "pause-initial")
    assert jobs.claim(**claim_args) is None
    assert jobs.get(spec.runtime_job_id)["attempt_count"] == 0
    for index in range(3):
        _change(project, principal, "RUNNING", index * 2 + 1, f"resume-{index}")
        claim = jobs.claim(**claim_args)
        assert claim is not None and claim.attempt_number == index + 1
        jobs.start(claim)
        _change(project, principal, "PAUSED", index * 2 + 2, f"pause-{index}")
        with pytest.raises(RuntimeDispatchPaused) as paused:
            assert_dispatch_enabled(DATABASE_URL, project)
        result = jobs.fail(claim, {"code": "error-wrapper"}, cause=paused.value)
        assert result["status"] == "RETRY_WAIT"
        waiting = dispatch_control_status(DATABASE_URL, project_id=project)["waiting_for_dispatch_control"]
        assert [(row["runtime_job_id"], row["disposition"], row["attempt_count"]) for row in waiting] == [
            (spec.runtime_job_id, "PAUSED_AWAITING_CONTROL", index + 1)]
        assert jobs.claim(**claim_args) is None
    _change(project, principal, "RUNNING", 7, "resume-final")
    claim = jobs.claim(**claim_args)
    assert claim is not None and claim.attempt_number == 4
    jobs.start(claim)
    assert jobs.complete(claim, {"resumed": True})["status"] == "SUCCEEDED"
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute("SELECT attempt_number,status,error FROM authority_runtime_job_attempt WHERE runtime_job_id=%s ORDER BY attempt_number", [spec.runtime_job_id]).fetchall()
    assert [(row[0], row[1]) for row in rows] == [(1, "FAILED"), (2, "FAILED"), (3, "FAILED"), (4, "SUCCEEDED")]
    assert all(row[2]["request_sent"] is False and row[2]["control_evidence"]["scope"] == "PROJECT" for row in rows[:3])
    assert dispatch_control_status(DATABASE_URL, project_id=project)["waiting_for_dispatch_control"] == []
    for invalid_count in (2, 4):
        with psycopg.connect(DATABASE_URL) as connection:
            with pytest.raises(psycopg.errors.CheckViolation, match="Runtime dispatch pause"):
                connection.execute("UPDATE authority_runtime_job SET paused_attempt_count=%s WHERE runtime_job_id=%s", [invalid_count, spec.runtime_job_id])


def test_runtime_job_plain_or_forged_pause_failure_consumes_normal_retry_limit(monkeypatch):
    from novel_forge.modules.runtime_job import RuntimeJobAuthority, RuntimeJobSpec

    monkeypatch.delenv("NOVEL_FORGE_NO_MODEL_DISPATCH", raising=False)
    project, _ = _scope()
    jobs = RuntimeJobAuthority(DATABASE_URL)
    for label, error in (("ordinary", {"code": "PROVIDER_UNKNOWN"}), ("forged", {
        "code": "RUNTIME_DISPATCH_PAUSED", "dispatch_pause_contract": "runtime-dispatch-control.v1",
        "control_evidence": {"scope": "PROJECT", "version": 1}, "disposition": "PAUSED_AWAITING_CONTROL", "request_sent": False})):
        spec = RuntimeJobSpec(job_kind="BOOK_COORDINATION_TICK", runtime_group="book", subject_kind="BOOK_RUN",
            subject_id=label, project_id=project, dedupe_key=label, input_snapshot={}, max_attempts=1)
        jobs.schedule(spec)
        claim = jobs.claim(runtime_group="book", worker_id="failure-worker", lease_seconds=60, project_id=project)
        assert claim is not None
        jobs.start(claim)
        assert jobs.fail(claim, error, cause=KernelError(error["code"], label))["status"] == "DEAD_LETTER"
        stored = jobs.get(spec.runtime_job_id)
        assert "dispatch_pause_contract" not in stored["last_error"]
        assert "disposition" not in stored["last_error"]
    assert dispatch_control_status(DATABASE_URL, project_id=project)["waiting_for_dispatch_control"] == []
