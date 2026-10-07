from copy import deepcopy
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    coordinate_saga,
    register_saga_step,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.command_kernel.step_successor import replace_failed_step
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)
from tests.integration.test_command_kernel_definition_postgres import definition_payload


@pytest.fixture
def failed_graph():
    ensure_migrated()
    project = identifier("step-successor")
    original = definition_payload(identifier("local-contract"))
    original["completion_contract"] = {}
    original["timeout_policy"] = {"operation_timeout_seconds": 300}
    target = {**deepcopy(original), "definition_version": "1.0.1"}
    root_definition = {**deepcopy(original), "name": identifier("successor-root")}
    context = AdmissionContext(
        "source-owner",
        frozenset(original["permissions"]),
        frozenset({original["handler_key"]}),
        "test-build-1",
        "a" * 40,
    )
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        for definition in (root_definition, original, target):
            uow.repositories.definitions.register(definition)
        uow.commit()

    def admit(definition, **relations):
        return admit_command(
            DATABASE_URL,
            {
                "definition_name": definition["name"],
                "definition_version": definition["definition_version"],
                "project_id": project,
                "workspace_id": "workspace:" + project,
                "actor_id": context.actor_id,
                "idempotency_scope": original["idempotency_scope"],
                "idempotency_key": identifier("command"),
                "trace_id": identifier("trace"),
                "span_id": identifier("span"),
                "correlation_id": project,
                "causation_id": "",
                "input": {"value": "frozen"},
                "input_assets": [],
                **relations,
            },
            context=context,
        )["operation_id"]

    root = admit(root_definition)
    for version, source, destination in (
        (0, "ADMITTED", "READY"),
        (1, "READY", "EXECUTING"),
        (2, "EXECUTING", "WAITING_CHILDREN"),
    ):
        transition_operation(
            DATABASE_URL,
            OperationTransitionCommand(
                root,
                project,
                version,
                source,
                destination,
                context.actor_id,
                "native root lifecycle",
                project,
                project,
                "",
            ),
        )
    child = admit(
        original,
        root_operation_id=root,
        parent_operation_id=root,
        causation_operation_id=root,
    )
    graph_context = GraphCommandContext(project, context.actor_id, project, project, "")
    saga = start_saga(DATABASE_URL, graph_context, root_operation_id=root)["saga_id"]
    register_saga_step(DATABASE_URL, graph_context, saga, child, "draft", 1, "")
    coordinate_saga(DATABASE_URL, graph_context, saga)
    attempt = create_attempt(
        DATABASE_URL,
        operation_id=child,
        project_id=project,
        max_attempts=1,
        trace_id=project,
        correlation_id=project,
    )["attempt_id"]
    queue_attempt(
        DATABASE_URL,
        attempt_id=attempt,
        project_id=project,
        trace_id=project,
        correlation_id=project,
    )
    lease = acquire_attempt_lease(
        DATABASE_URL,
        attempt_id=attempt,
        project_id=project,
        worker_id="worker",
        lease_seconds=30,
        trace_id=project,
        correlation_id=project,
    )
    worker = WorkerLeaseCommand(
        attempt, project, "worker", lease["fencing_token"], project, project
    )
    start_attempt(DATABASE_URL, worker)
    submit_attempt_result(
        DATABASE_URL,
        WorkerResultCommand(**worker.__dict__, expected_operation_version=2),
        result={"error_code": "LOCAL_CONTRACT_DEFECT"},
        outcome="final_failure",
    )
    assert (
        coordinate_saga(DATABASE_URL, graph_context, saga)["status"]
        == "MANUAL_INTERVENTION"
    )
    return project, root, child, saga, context


def test_native_step_successor_preserves_failure_and_manual_saga_history(failed_graph):
    project, root, child, saga, context = failed_graph
    options = dict(
        predecessor_id=child,
        target_version="1.0.1",
        context=context,
        policy_evidence={"contract": "controlled-local-contract"},
        expected_failure_code="LOCAL_CONTRACT_DEFECT",
    )
    first = replace_failed_step(DATABASE_URL, **options)
    assert replace_failed_step(DATABASE_URL, **options) == {
        "operation_id": first["operation_id"],
        "replayed": True,
    }
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id=%s", [child]
        )
        assert uow.cursor.fetchone()[0] == "FAILED_FINAL"
        uow.cursor.execute(
            "SELECT status,result->>'error_code' FROM authority_attempt WHERE operation_id=%s",
            [child],
        )
        assert uow.cursor.fetchone() == ("FAILED_FINAL", "LOCAL_CONTRACT_DEFECT")
        uow.cursor.execute("SELECT status FROM authority_saga WHERE saga_id=%s", [saga])
        assert uow.cursor.fetchone()[0] == "RUNNING"
        uow.cursor.execute(
            "SELECT source_saga_snapshot->>'status',successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s",
            [child],
        )
        assert uow.cursor.fetchone() == ("MANUAL_INTERVENTION", first["operation_id"])
        uow.cursor.execute(
            "SELECT input_asset_snapshot,command_payload,parent_operation_id,root_operation_id FROM authority_operation WHERE operation_id=ANY(%s) ORDER BY created_at",
            [[child, first["operation_id"]]],
        )
        before, after = uow.cursor.fetchall()
        assert before == after
    with pytest.raises(psycopg.errors.CheckViolation):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "DELETE FROM authority_saga_step_successor WHERE predecessor_operation_id=%s",
                [child],
            )
            uow.commit()


def _window_options(failed_graph):
    project, root, child, saga, context = failed_graph
    with AuthorityUnitOfWork(DATABASE_URL) as u:
        u.cursor.execute("SELECT definition_snapshot FROM authority_operation WHERE operation_id=%s", [child])
        target = deepcopy(u.cursor.fetchone()[0])
        target["definition_version"] = "1.0.2"
        target["policy"]["source_span_contract"] = "controlled-span.v1"
        u.repositories.definitions.register(target)
        u.cursor.execute("UPDATE authority_operation SET business_deadline_at=%s WHERE operation_id=%s", [datetime.now(timezone.utc)-timedelta(seconds=1), root])
        u.commit()
    return dict(predecessor_id=child, target_version="1.0.2", context=context,
        policy_evidence={"contract": "controlled-interface-correction"}, expected_failure_code="LOCAL_CONTRACT_DEFECT",
        window_successor={"contract_version": "kernel-corrected-contract-window.v1", "policy_key": "source_span_contract", "policy_value": "controlled-span.v1"})


def test_corrected_window_preserves_original_root_and_deadline_idempotently(failed_graph):
    project, root, child, saga, context = failed_graph
    options = _window_options(failed_graph)
    first = replace_failed_step(DATABASE_URL, **options)
    assert replace_failed_step(DATABASE_URL, **options)["replayed"]
    with AuthorityUnitOfWork(DATABASE_URL) as u:
        u.cursor.execute("SELECT source_failure_snapshot FROM authority_saga_step_successor WHERE predecessor_operation_id=%s", [child])
        record = u.cursor.fetchone()[0]
        u.cursor.execute("SELECT status,business_deadline_at,command_payload FROM authority_operation WHERE operation_id=%s", [root])
        status, deadline, payload = u.cursor.fetchone()
        assert status == "WAITING_CHILDREN"
        assert deadline > datetime.now(timezone.utc)
        assert record["root"]["command_payload"] == payload
        assert record["execution_window"]["duration_seconds"] == 300
        assert record["execution_window"]["original_deadline"] != deadline.isoformat()
        assert record["operation"]["status"] == "FAILED_FINAL"
        assert first["operation_id"] != child


@pytest.mark.parametrize("boundary", ["unchanged-policy", "author-deadline", "cancelled-root"])
def test_contract_window_cannot_bypass_author_deadline_cancel_or_unchanged_contract(failed_graph, boundary):
    project, root, child, saga, context = failed_graph
    options = _window_options(failed_graph)
    if boundary == "unchanged-policy":
        options["target_version"] = "1.0.1"
    else:
        with AuthorityUnitOfWork(DATABASE_URL) as u:
            if boundary == "author-deadline":
                u.cursor.execute("UPDATE authority_operation SET command_payload=command_payload || '{\"author_deadline_at\":\"2026-01-01\"}'::jsonb WHERE operation_id=%s", [root])
            else:
                u.cursor.execute("UPDATE authority_operation SET status='CANCELLED' WHERE operation_id=%s", [root])
            u.commit()
    with pytest.raises(KernelError) as failure:
        replace_failed_step(DATABASE_URL, **options)
    assert failure.value.code in {"STEP_SUCCESSOR_WINDOW_INVALID", "STEP_SUCCESSOR_SOURCE_INVALID"}


@pytest.mark.parametrize("boundary", ["failure", "permissions", "cancelled-root"])
def test_step_successor_rejects_unowned_cancelled_or_unproven_recovery(
    failed_graph, boundary
):
    project, root, child, saga, context = failed_graph
    if boundary == "permissions":
        context = AdmissionContext(
            context.actor_id,
            frozenset(),
            context.available_handlers,
            context.application_build_id,
            context.commit_sha,
        )
    if boundary == "cancelled-root":
        from novel_forge.modules.command_kernel.cancellation import (
            CancelCommand,
            request_cancellation,
        )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT version FROM authority_operation WHERE operation_id=%s", [root]
            )
            version = uow.cursor.fetchone()[0]
        request_cancellation(
            DATABASE_URL,
            CancelCommand(
                root,
                project,
                context.actor_id,
                "author cancel",
                version,
                identifier("cancel"),
                project,
                project,
            ),
            settle_undispatched=True,
        )
    with pytest.raises(KernelError):
        replace_failed_step(
            DATABASE_URL,
            predecessor_id=child,
            target_version="1.0.1",
            context=context,
            policy_evidence={"contract": "controlled-local-contract"},
            expected_failure_code="DIFFERENT_FAILURE"
            if boundary == "failure"
            else "LOCAL_CONTRACT_DEFECT",
        )


def test_known_receipt_successor_rejects_unproven_effects(failed_graph):
    project, root, child, saga, context = failed_graph
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_RECEIPT_UNSETTLED"):
        replace_failed_step(
            DATABASE_URL,
            predecessor_id=child,
            target_version="1.0.1",
            context=context,
            policy_evidence={"contract_version": "chapter-known-receipt.v1"},
            expected_failure_code="LOCAL_CONTRACT_DEFECT",
            known_receipt_effects=(("unproven-effect", "unproven-hash"),),
        )


def test_schema_rejection_successor_requires_exact_domain_and_kernel_evidence(failed_graph):
    project, root, child, saga, context = failed_graph
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_REJECTION_UNRECONCILED"):
        replace_failed_step(DATABASE_URL, predecessor_id=child, target_version="1.0.1", context=context,
            policy_evidence={"contract_version": "controlled-rejection"}, expected_failure_code="LOCAL_CONTRACT_DEFECT",
            known_rejected_effects=(("missing-effect", "missing-hash", "missing-receipt", "missing-hash"),))
