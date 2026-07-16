"""PostgreSQL-authoritative Operation Graph and idempotent Saga coordination."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg

from novel_forge.modules.command_kernel.errors import KernelError
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
            operation = repository.operation(operation_id, context.project_id, lock=True)
            dependency = repository.operation(
                depends_on_operation_id,
                context.project_id,
                lock=True,
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


def coordinate_saga(
    database_url: str,
    context: GraphCommandContext,
    saga_id: str,
) -> dict[str, Any]:
    _validate_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        repository = uow.repositories.operation_graph
        saga = repository.saga_for_update(saga_id, context.project_id)
        steps = repository.saga_steps(saga_id)
        if saga["status"] in {"SUCCEEDED", "COMPENSATED", "COMPENSATION_FAILED", "CANCELLED"}:
            return _saga_result(saga["status"], steps)
        lease = repository.acquire_coordinator(
            saga,
            owner=context.actor_id,
            lease_id=str(uuid4()),
            lease_seconds=30,
        )

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
        elif steps and all(step["status"] == "SUCCEEDED" for step in steps):
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


def _validate_context(context: GraphCommandContext) -> None:
    if not all((context.project_id, context.actor_id, context.trace_id, context.correlation_id)):
        raise KernelError("KERNEL_COMMAND_INVALID", "graph command context is incomplete")
