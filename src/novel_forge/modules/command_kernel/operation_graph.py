from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


TERMINAL_STATUSES = {
    "SUCCEEDED",
    "FAILED_FINAL",
    "COMPENSATED",
    "COMPENSATION_FAILED",
    "CANCELLED",
    "DEAD_LETTER",
}
FAILURE_STATUSES = {"FAILED_FINAL", "COMPENSATION_FAILED", "DEAD_LETTER"}


@dataclass(frozen=True)
class GraphCommandContext:
    project_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""


def add_operation_dependency(
    database_url: str,
    context: GraphCommandContext,
    operation_id: str,
    depends_on_operation_id: str,
    condition: str,
) -> dict[str, Any]:
    _validate_context(context)
    if condition not in {
        "ON_SUCCESS",
        "ON_COMPLETION",
        "ON_FAILURE",
        "ON_COMPENSATED",
        "MANUAL_GATE",
    }:
        raise KernelError("DEPENDENCY_CONDITION_INVALID", "unknown dependency condition")
    try:
        with AuthorityUnitOfWork(database_url) as uow:
            repository = uow.repositories.operation_graph
            source = repository.operation(operation_id, context.project_id)
            uow.cursor.execute(
                "SELECT saga_id FROM authority_saga WHERE root_operation_id=%s AND project_id=%s FOR UPDATE",
                [source["root_operation_id"], context.project_id],
            )
            uow.cursor.fetchone()
            for identity in sorted({operation_id, depends_on_operation_id}):
                repository.operation(identity, context.project_id, lock=True)
            operation = repository.operation(operation_id, context.project_id)
            dependency = repository.operation(
                depends_on_operation_id,
                context.project_id,
            )
            if operation["root_operation_id"] != dependency["root_operation_id"]:
                raise KernelError(
                    "DEPENDENCY_ROOT_CONFLICT",
                    "dependency operations do not belong to the same root graph",
                )
            created = repository.add_dependency(
                operation_id,
                depends_on_operation_id,
                condition,
            )
            if created:
                _record(
                    repository,
                    context,
                    operation_id,
                    "authority.operation.dependency_added",
                    {
                        "depends_on_operation_id": depends_on_operation_id,
                        "condition": condition,
                    },
                )
            uow.commit()
        return {"created": created}
    except psycopg.errors.CheckViolation as exc:
        constraint = exc.diag.constraint_name or ""
        if "acyclic" in constraint or "not_self" in constraint:
            raise KernelError("DEPENDENCY_CYCLE", "operation dependency creates a cycle") from exc
        raise


def operation_graph(database_url: str, project_id: str, root_operation_id: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        root = repository.operation(root_operation_id, project_id)
        if root["root_operation_id"] != root_operation_id:
            raise KernelError("OPERATION_GRAPH_ROOT_INVALID", "operation is not a root")
        return _build_graph(repository, project_id, root_operation_id)


def start_saga(
    database_url: str,
    context: GraphCommandContext,
    *,
    root_operation_id: str,
) -> dict[str, Any]:
    _validate_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        root = repository.operation(root_operation_id, context.project_id, lock=True)
        if root["root_operation_id"] != root_operation_id:
            raise KernelError("SAGA_ROOT_INVALID", "saga root is not a root operation")
        result = repository.start_saga(
            str(uuid4()),
            root_operation_id,
            context.project_id,
            context.trace_id,
            context.correlation_id,
        )
        if not result["replayed"]:
            _record(
                repository,
                context,
                root_operation_id,
                "authority.saga.started",
                {"saga_id": result["saga_id"]},
                aggregate_type="authority_saga",
                aggregate_id=result["saga_id"],
            )
        uow.commit()
    return result


def transition_saga_gate(
    database_url: str,
    context: GraphCommandContext,
    saga_id: str,
    *,
    target_status: str,
    reason: str,
) -> dict[str, Any]:
    """INVARIANT: Fence and audit a business-gate transition on a Saga.

    Gate owners use this command instead of updating ``authority_saga`` directly.
    The coordinator lease, state mutation, StateEvent, AuditLog, and Outbox write are
    committed in one transaction.
    """
    _validate_context(context)
    if target_status not in {"WAITING_GATE", "RUNNING"} or not reason.strip():
        raise KernelError("SAGA_GATE_COMMAND_INVALID", "valid gate status and reason are required")
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        saga = repository.saga_for_update(saga_id, context.project_id)
        if saga["status"] == target_status:
            return {"status": target_status, "version": int(saga["version"]), "replayed": True}
        allowed = {
            ("RUNNING", "WAITING_GATE"),
            ("FORWARD_RECOVERY", "WAITING_GATE"),
            ("WAITING_GATE", "RUNNING"),
        }
        if (str(saga["status"]), target_status) not in allowed:
            raise KernelError("SAGA_STATUS_CONFLICT", "Saga cannot perform the requested gate transition")
        lease = repository.acquire_coordinator(
            saga, owner=context.actor_id, lease_id=str(uuid4()), lease_seconds=30
        )
        repository.update_saga(saga_id, int(saga["version"]), target_status)
        _record(
            repository,
            context,
            str(saga["root_operation_id"]),
            "authority.saga.gate_transitioned",
            {
                "saga_id": saga_id,
                "previous_status": saga["status"],
                "target_status": target_status,
                "reason": reason,
                "coordinator_fencing_token": lease["fencing_token"],
            },
            aggregate_type="authority_saga",
            aggregate_id=saga_id,
        )
        repository.release_coordinator(saga_id, context.actor_id, lease["fencing_token"])
        uow.commit()
        return {"status": target_status, "version": int(saga["version"]) + 1, "replayed": False}


def register_saga_step(
    database_url: str,
    context: GraphCommandContext,
    saga_id: str,
    operation_id: str,
    step_key: str,
    ordinal: int,
    compensation_definition: str,
) -> dict[str, Any]:
    _validate_context(context)
    if not step_key or ordinal <= 0:
        raise KernelError("SAGA_STEP_INVALID", "saga step identity is invalid")
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        saga = repository.saga_for_update(saga_id, context.project_id)
        operation = repository.operation(operation_id, context.project_id, lock=True)
        if operation["root_operation_id"] != saga["root_operation_id"]:
            raise KernelError("SAGA_STEP_ROOT_CONFLICT", "saga step belongs to another root")
        created = repository.register_step(
            saga_id,
            operation_id,
            step_key,
            ordinal,
            compensation_definition,
        )
        if created:
            _record(
                repository,
                context,
                saga["root_operation_id"],
                "authority.saga.step_registered",
                {
                    "saga_id": saga_id,
                    "operation_id": operation_id,
                    "step_key": step_key,
                    "ordinal": ordinal,
                },
                aggregate_type="authority_saga",
                aggregate_id=saga_id,
            )
        uow.commit()
    return {"created": created}


def terminalize_saga_from_extension(
    database_url: str,
    context: GraphCommandContext,
    saga_id: str,
    *,
    operation_id: str,
) -> dict[str, Any]:
    _validate_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        saga = repository.saga_for_update(saga_id, context.project_id)
        operation = repository.operation(operation_id, context.project_id, lock=True)
        if operation["root_operation_id"] != saga["root_operation_id"]:
            raise KernelError(
                "SAGA_EXTENSION_ROOT_CONFLICT",
                "terminal extension Operation belongs to another root",
            )
        operation_status = str(operation["status"])
        if operation_status not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
            raise KernelError(
                "SAGA_EXTENSION_NOT_TERMINAL",
                "extension Operation has no terminal failure or cancellation",
            )
        saga_status = (
            "CANCELLED" if operation_status == "CANCELLED" else "MANUAL_INTERVENTION"
        )
        root_status = "CANCELLED" if operation_status == "CANCELLED" else "FAILED_FINAL"
        root = repository.operation(
            str(saga["root_operation_id"]),
            context.project_id,
            lock=True,
        )
        current_root_status = str(root["status"])
        if str(saga["status"]) == saga_status and current_root_status == root_status:
            return {
                "saga_status": saga_status,
                "root_status": root_status,
                "replayed": True,
            }
        if (
            str(saga["status"])
            not in {"RUNNING", "FORWARD_RECOVERY", "WAITING_GATE"}
            or current_root_status in TERMINAL_STATUSES
        ):
            raise KernelError(
                "SAGA_EXTENSION_TERMINAL_CONFLICT",
                "extension cannot overwrite an existing terminal Saga outcome",
            )
        lease = repository.acquire_coordinator(
            saga,
            owner=context.actor_id,
            lease_id=str(uuid4()),
            lease_seconds=30,
        )
        if str(saga["status"]) != saga_status:
            repository.update_saga(saga_id, int(saga["version"]), saga_status)
        if repository.complete_root(str(saga["root_operation_id"]), root_status):
            _record_operation_transition(
                repository,
                context,
                str(saga["root_operation_id"]),
                root_status,
                lease["fencing_token"],
            )
        _record(
            repository,
            context,
            str(saga["root_operation_id"]),
            "authority.saga.extension_terminal_propagated",
            {
                "saga_id": saga_id,
                "extension_operation_id": operation_id,
                "extension_operation_status": operation_status,
                "saga_status": saga_status,
                "root_status": root_status,
                "coordinator_fencing_token": lease["fencing_token"],
            },
            aggregate_type="authority_saga",
            aggregate_id=saga_id,
        )
        repository.release_coordinator(
            saga_id,
            context.actor_id,
            lease["fencing_token"],
        )
        uow.commit()
    return {"saga_status": saga_status, "root_status": root_status, "replayed": False}


def _root_completion_satisfied(uow, root_operation_id, project_id):
    from .completion import evaluate_completion_in_uow
    root = uow.repositories.completion_contracts.operation(root_operation_id, project_id, lock=True)
    return evaluate_completion_in_uow(uow, root)["satisfied"]


def coordinate_saga(
    database_url: str,
    context: GraphCommandContext,
    saga_id: str,
    *,
    admission_context: AdmissionContext | None = None,
) -> dict[str, Any]:
    _validate_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        saga = repository.saga_for_update(saga_id, context.project_id)
        repository.synchronize_compensation_statuses(saga_id)
        steps = repository.saga_steps(saga_id)
        if saga["status"] in {
            "SUCCEEDED",
            "COMPENSATED",
            "COMPENSATION_FAILED",
            "MANUAL_INTERVENTION",
            "CANCELLED",
        }:
            return _saga_result(saga["status"], steps)
        lease = repository.acquire_coordinator(
            saga,
            owner=context.actor_id,
            lease_id=str(uuid4()),
            lease_seconds=30,
        )
        uow.cursor.execute(
            "SELECT status FROM authority_operation WHERE operation_id = %s",
            [saga["root_operation_id"]],
        )
        root_status = str(uow.cursor.fetchone()[0])
        if root_status == "WAITING_GATE":
            repository.release_coordinator(
                saga_id,
                context.actor_id,
                lease["fencing_token"],
            )
            uow.commit()
            return _saga_result("WAITING_GATE", steps)

        failed_compensations = [
            step["operation_id"]
            for step in steps
            if step["compensation_status"] == "COMPENSATION_FAILED"
        ]
        target_status = saga["status"]
        changed = False
        if failed_compensations:
            target_status = "COMPENSATION_FAILED"
            repository.update_saga(saga_id, saga["version"], target_status)
            if repository.complete_root(saga["root_operation_id"], target_status):
                _record_operation_transition(
                    repository,
                    context,
                    saga["root_operation_id"],
                    target_status,
                    lease["fencing_token"],
                )
            changed = True
        elif saga["status"] == "COMPENSATING":
            required = [
                step
                for step in steps
                if step["compensation_status"] != "NOT_REQUIRED"
            ]
            if required and all(
                step["compensation_status"] == "COMPENSATED" for step in required
            ):
                target_status = "COMPENSATED"
                repository.update_saga(saga_id, saga["version"], target_status)
                if repository.complete_root(saga["root_operation_id"], target_status):
                    _record_operation_transition(
                        repository,
                        context,
                        saga["root_operation_id"],
                        target_status,
                        lease["fencing_token"],
                    )
                changed = True
            else:
                graph = _build_graph(
                    repository,
                    context.project_id,
                    saga["root_operation_id"],
                )
                for operation_id in repository.set_ready(graph["ready"]):
                    _record_operation_transition(
                        repository,
                        context,
                        operation_id,
                        "READY",
                        lease["fencing_token"],
                    )
                steps = repository.saga_steps(saga_id)
        elif any(step["status"] == "FAILED_RETRYABLE" for step in steps):
            recovered = repository.recover_forward(
                [step["operation_id"] for step in steps if step["status"] == "FAILED_RETRYABLE"]
            )
            target_status = "FORWARD_RECOVERY"
            repository.update_saga(saga_id, saga["version"], target_status)
            for operation_id in recovered:
                _record_operation_transition(
                    repository,
                    context,
                    operation_id,
                    "READY",
                    lease["fencing_token"],
                )
            changed = True
        elif any(step["status"] == "CANCELLED" for step in steps):
            target_status = "CANCELLED"
            repository.update_saga(saga_id, saga["version"], target_status)
            if repository.complete_root(saga["root_operation_id"], target_status):
                _record_operation_transition(
                    repository,
                    context,
                    saga["root_operation_id"],
                    target_status,
                    lease["fencing_token"],
                )
            changed = True
        elif any(step["status"] in FAILURE_STATUSES for step in steps):
            compensatable = [
                step["operation_id"]
                for step in reversed(steps)
                if step["status"] == "SUCCEEDED" and step["compensation_definition"]
            ]
            if compensatable:
                repository.mark_compensation_required(compensatable)
                target_status = "COMPENSATING"
            else:
                target_status = "MANUAL_INTERVENTION"
            repository.update_saga(saga_id, saga["version"], target_status)
            changed = True
            steps = repository.saga_steps(saga_id)
            if compensatable and admission_context is not None:
                _admit_saga_compensation_children(
                    uow,
                    repository,
                    context,
                    saga,
                    steps,
                    admission_context,
                )
                steps = repository.saga_steps(saga_id)
        elif (
            steps
            and all(step["status"] == "SUCCEEDED" for step in steps)
            and _root_completion_satisfied(uow, saga["root_operation_id"], context.project_id)
            and (
                repository.expected_saga_step_count(saga["root_operation_id"]) == 0
                or len(steps)
                >= repository.expected_saga_step_count(saga["root_operation_id"])
            )
        ):
            target_status = "SUCCEEDED"
            repository.update_saga(saga_id, saga["version"], target_status)
            if repository.complete_root(saga["root_operation_id"], target_status):
                _record_operation_transition(
                    repository,
                    context,
                    saga["root_operation_id"],
                    target_status,
                    lease["fencing_token"],
                )
            changed = True
        else:
            graph = _build_graph(repository, context.project_id, saga["root_operation_id"])
            for operation_id in repository.set_ready(graph["ready"]):
                _record_operation_transition(
                    repository,
                    context,
                    operation_id,
                    "READY",
                    lease["fencing_token"],
                )
            if repository.complete_root(saga["root_operation_id"], "WAITING_CHILDREN"):
                _record_operation_transition(
                    repository,
                    context,
                    saga["root_operation_id"],
                    "WAITING_CHILDREN",
                    lease["fencing_token"],
                )
            steps = repository.saga_steps(saga_id)

        if changed:
            _record(
                repository,
                context,
                saga["root_operation_id"],
                "authority.saga.coordinated",
                {
                    "saga_id": saga_id,
                    "status": target_status,
                    "coordinator_fencing_token": lease["fencing_token"],
                },
                aggregate_type="authority_saga",
                aggregate_id=saga_id,
            )
        repository.release_coordinator(
            saga_id,
            context.actor_id,
            lease["fencing_token"],
        )
        uow.commit()
    return _saga_result(target_status, steps)


def _build_graph(repository: Any, project_id: str, root_operation_id: str) -> dict[str, Any]:
    rows = repository.graph_rows(root_operation_id, project_id)
    children = [row for row in rows if row["operation_id"] != root_operation_id]
    by_id = {row["operation_id"]: row for row in rows}
    dependencies = repository.dependency_rows([row["operation_id"] for row in children])
    grouped: dict[str, list[dict[str, str]]] = {}
    for dependency in dependencies:
        grouped.setdefault(dependency["operation_id"], []).append(dependency)
    gates = repository.passed_manual_gates([row["operation_id"] for row in children])
    ready: list[str] = []
    blocked: list[str] = []
    terminal: list[str] = []
    failed: list[str] = []
    for child in children:
        operation_id = child["operation_id"]
        if child["status"] in TERMINAL_STATUSES:
            terminal.append(operation_id)
            if child["status"] in FAILURE_STATUSES:
                failed.append(operation_id)
            continue
        conditions = grouped.get(operation_id, [])
        if all(_condition_satisfied(item, by_id, gates) for item in conditions):
            ready.append(operation_id)
        else:
            blocked.append(operation_id)
    return {
        "root_operation_id": root_operation_id,
        "nodes": rows,
        "dependencies": dependencies,
        "ready": sorted(ready),
        "blocked": sorted(blocked),
        "terminal": sorted(terminal),
        "failed": sorted(failed),
    }


def _condition_satisfied(
    dependency: dict[str, str],
    by_id: dict[str, dict[str, Any]],
    gates: set[tuple[str, str]],
) -> bool:
    prerequisite = by_id.get(dependency["depends_on"])
    if prerequisite is None:
        return False
    status = prerequisite["status"]
    condition = dependency["condition"]
    if condition == "ON_SUCCESS":
        return status == "SUCCEEDED"
    if condition == "ON_COMPLETION":
        return status in TERMINAL_STATUSES
    if condition == "ON_FAILURE":
        return status in FAILURE_STATUSES
    if condition == "ON_COMPENSATED":
        return status == "COMPENSATED"
    return (
        dependency["operation_id"],
        f"dependency:{dependency['depends_on']}",
    ) in gates


def _saga_result(status: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    compensation_order = [
        step["operation_id"]
        for step in reversed(steps)
        if step["compensation_status"] in {"REQUIRED", "COMPENSATING"}
    ]
    manual = [
        step["operation_id"]
        for step in steps
        if step["compensation_status"] == "COMPENSATION_FAILED"
    ]
    return {
        "status": status,
        "compensation_order": compensation_order,
        "manual_intervention": manual,
        "ready": [step["operation_id"] for step in steps if step["status"] == "READY"],
    }


def _record(
    repository: Any,
    context: GraphCommandContext,
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    aggregate_type: str = "authority_operation",
    aggregate_id: str | None = None,
) -> None:
    repository.record_event(
        {
            "event_id": str(uuid4()),
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id or operation_id,
            "operation_id": operation_id,
            "project_id": context.project_id,
            "event_type": event_type,
            "correlation_id": context.correlation_id,
            "causation_id": context.causation_id,
            "payload": {
                **payload,
                "actor_id": context.actor_id,
                "trace_id": context.trace_id,
                "operation_id": operation_id,
            },
        }
    )


def _record_operation_transition(
    repository: Any,
    context: GraphCommandContext,
    operation_id: str,
    target_status: str,
    fencing_token: int,
) -> None:
    _record(
        repository,
        context,
        operation_id,
        "authority.operation.saga_transitioned",
        {
            "target_status": target_status,
            "coordinator_fencing_token": fencing_token,
        },
    )


def _admit_saga_compensation_children(
    uow: AuthorityUnitOfWork,
    repository: Any,
    context: GraphCommandContext,
    saga: dict[str, Any],
    steps: list[dict[str, Any]],
    admission_context: AdmissionContext,
) -> None:
    previous_compensation_id = ""
    for step in reversed(steps):
        if step["compensation_status"] not in {"REQUIRED", "COMPENSATING"}:
            continue
        if step["compensation_operation_id"]:
            previous_compensation_id = str(step["compensation_operation_id"])
            continue
        definition_name = str(step["compensation_definition"])
        definition_version = repository.latest_definition_version(definition_name)
        definition = uow.repositories.definitions.get(definition_name, definition_version)
        if definition is None:
            raise KernelError(
                "OPERATION_DEFINITION_NOT_FOUND",
                "saga compensation definition disappeared during admission",
            )
        command = {
            "definition_name": definition_name,
            "definition_version": definition_version,
            "project_id": context.project_id,
            "workspace_id": f"workspace:{context.project_id}",
            "actor_id": admission_context.actor_id,
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": f"saga:{saga['saga_id']}:compensate:{step['step_key']}",
            "trace_id": context.trace_id,
            "span_id": str(uuid4()),
            "correlation_id": context.correlation_id,
            "causation_id": step["operation_id"],
            "parent_operation_id": step["operation_id"],
            "root_operation_id": saga["root_operation_id"],
            "causation_operation_id": step["operation_id"],
            "input": {"value": f"compensate:{step['step_key']}"},
            "input_assets": [],
            "metadata": {
                "operation_role": "saga_compensation",
                "saga_id": saga["saga_id"],
                "step_key": step["step_key"],
            },
        }
        admitted = admit_command_in_uow(uow, command, context=admission_context)
        compensation_id = str(admitted["operation_id"])
        repository.attach_compensation_operation(step["operation_id"], compensation_id)
        if previous_compensation_id:
            repository.add_dependency(
                compensation_id,
                previous_compensation_id,
                "ON_SUCCESS",
            )
        _record(
            repository,
            context,
            saga["root_operation_id"],
            "authority.saga.compensation_child_admitted",
            {
                "saga_id": saga["saga_id"],
                "step_operation_id": step["operation_id"],
                "compensation_operation_id": compensation_id,
                "replayed": admitted["replayed"],
            },
            aggregate_type="authority_saga",
            aggregate_id=saga["saga_id"],
        )
        previous_compensation_id = compensation_id


def _validate_context(context: GraphCommandContext) -> None:
    if not all((context.project_id, context.actor_id, context.trace_id, context.correlation_id)):
        raise KernelError("KERNEL_COMMAND_INVALID", "graph command context is incomplete")
