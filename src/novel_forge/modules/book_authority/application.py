from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any
from uuid import uuid4

from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    register_saga_step,
    start_saga,
    transition_saga_gate,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .definitions import (
    BOOK_DEFINITION_VERSION,
    BOOK_ROOT_DEFINITION,
    BOOK_ROOT_HANDLER,
    book_definitions,
)
from .registry import BookHandlerRegistry


@dataclass(frozen=True, slots=True)
class BookProductionPolicy:
    target_chapter_count: int
    chapter_batch_size: int = 1
    light_recap_cadence: int = 5
    formal_recap_cadence: int = 10
    maximum_failed_chapters: int = 0
    book_budget: str = "0"
    chapter_budget: str = "0"
    provider_budget: str = "0"
    book_deadline_seconds: int = 86400
    pause_policy: str = "operator_command"
    no_progress_policy: str = "pause_after_two_unchanged_windows"

    def validate(self) -> None:
        if self.target_chapter_count <= 0 or self.chapter_batch_size <= 0:
            raise ValueError("book production counts must be positive")
        if self.light_recap_cadence <= 0 or self.formal_recap_cadence <= 0:
            raise ValueError("book recap cadence must be positive")


@dataclass(frozen=True, slots=True)
class BookProductionRequest:
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    application_build_id: str
    commit_sha: str
    policy: BookProductionPolicy


@dataclass(frozen=True, slots=True)
class BookProductionAdmission:
    root_operation_id: str
    saga_id: str
    step_operation_ids: tuple[str, ...]
    replayed: bool


def admit_book_production(
    database_url: str, request: BookProductionRequest
) -> BookProductionAdmission:
    if os.environ.get("NOVEL_FORGE_ENVIRONMENT", "development").lower() in {
        "production",
        "staging",
        "production_like",
    }:
        raise RuntimeError(
            "LEGACY_BOOK_AUTHORITY_PRODUCTION_DISABLED: "
            "use PostgresBookAuthority through the Book command port"
        )
    request.policy.validate()
    definitions = book_definitions(
        application_build_id=request.application_build_id, commit_sha=request.commit_sha
    )
    registry = BookHandlerRegistry()
    with AuthorityUnitOfWork(database_url) as uow:
        for definition in definitions:
            uow.repositories.definitions.register(definition)
        uow.commit()
    context = AdmissionContext(
        actor_id=request.actor_id,
        permissions=frozenset({"book.authority.execute"}),
        available_handlers=registry.available_handler_keys
        | frozenset({BOOK_ROOT_HANDLER}),
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
    )
    root_command = _command(request, BOOK_ROOT_DEFINITION, request.idempotency_key, {})
    admitted = admit_command(database_url, root_command, context=context)
    root_id = str(admitted["operation_id"])
    with AuthorityUnitOfWork(database_url) as uow:
        state = uow.repositories.attempt_runtime.operation_state(
            root_id, request.project_id
        )
    if state["status"] == "ADMITTED":
        for expected, target in (("ADMITTED", "READY"), ("READY", "EXECUTING")):
            with AuthorityUnitOfWork(database_url) as uow:
                current = uow.repositories.attempt_runtime.operation_state(
                    root_id, request.project_id
                )
            transition_operation(
                database_url,
                OperationTransitionCommand(
                    operation_id=root_id,
                    project_id=request.project_id,
                    expected_version=int(current["version"]),
                    expected_status=expected,
                    target_status=target,
                    actor_id=request.actor_id,
                    reason="start deterministic Book Authority Saga",
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                    causation_id="",
                ),
            )
    graph = GraphCommandContext(
        request.project_id, request.actor_id, request.trace_id, request.correlation_id
    )
    saga_id = str(start_saga(database_url, graph, root_operation_id=root_id)["saga_id"])
    steps = _steps(request.policy)
    operation_ids: list[str] = []
    previous_id = root_id
    for ordinal, (definition_name, step_key, payload) in enumerate(steps, start=1):
        child = admit_command(
            database_url,
            _command(
                request,
                definition_name,
                f"{request.idempotency_key}:{step_key}",
                payload,
                root_operation_id=root_id,
                parent_operation_id=root_id,
                causation_operation_id=previous_id,
            ),
            context=context,
        )
        operation_id = str(child["operation_id"])
        register_saga_step(
            database_url, graph, saga_id, operation_id, step_key, ordinal, ""
        )
        if previous_id != root_id:
            add_operation_dependency(
                database_url, graph, operation_id, previous_id, "ON_SUCCESS"
            )
        operation_ids.append(operation_id)
        previous_id = operation_id
    coordinate_saga(database_url, graph, saga_id)
    return BookProductionAdmission(
        root_id, saga_id, tuple(operation_ids), bool(admitted["replayed"])
    )


def _steps(policy: BookProductionPolicy) -> list[tuple[str, str, dict[str, Any]]]:
    frozen = asdict(policy)
    steps: list[tuple[str, str, dict[str, Any]]] = [
        (
            "book.production.prepare",
            "book_prepare",
            {"target_chapter_count": policy.target_chapter_count, "policy": frozen},
        )
    ]
    for chapter in range(1, policy.target_chapter_count + 1):
        steps.append(
            (
                "book.chapter.dispatch",
                f"chapter:{chapter}",
                {"chapter": chapter, "policy": frozen},
            )
        )
        cadence = ""
        if chapter % policy.formal_recap_cadence == 0:
            cadence = "formal"
        elif chapter % policy.light_recap_cadence == 0:
            cadence = "light"
        if cadence:
            steps.append(
                (
                    f"book.recap.{cadence}",
                    f"recap:{cadence}:{chapter}",
                    {"through_chapter": chapter, "cadence": cadence, "policy": frozen},
                )
            )
            steps.append(
                (
                    "book.plan_adjustment.propose",
                    f"plan_adjustment:{chapter}",
                    {"through_chapter": chapter, "policy": frozen},
                )
            )
    return steps


def pause_book_production(
    database_url: str,
    *,
    project_id: str,
    saga_id: str,
    actor_id: str,
    trace_id: str,
    correlation_id: str,
    reason: str,
) -> dict[str, Any]:
    return transition_saga_gate(
        database_url,
        GraphCommandContext(project_id, actor_id, trace_id, correlation_id),
        saga_id,
        target_status="WAITING_GATE",
        reason=reason,
    )


def resume_book_production(
    database_url: str,
    *,
    project_id: str,
    saga_id: str,
    actor_id: str,
    trace_id: str,
    correlation_id: str,
    reason: str,
) -> dict[str, Any]:
    return transition_saga_gate(
        database_url,
        GraphCommandContext(project_id, actor_id, trace_id, correlation_id),
        saga_id,
        target_status="RUNNING",
        reason=reason,
    )


def _command(
    request: BookProductionRequest,
    definition_name: str,
    idempotency_key: str,
    payload: dict[str, Any],
    *,
    root_operation_id: str | None = None,
    parent_operation_id: str | None = None,
    causation_operation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "definition_name": definition_name,
        "definition_version": BOOK_DEFINITION_VERSION,
        "project_id": request.project_id,
        "workspace_id": request.workspace_id,
        "actor_id": request.actor_id,
        "idempotency_scope": "project:book-production",
        "idempotency_key": idempotency_key,
        "trace_id": request.trace_id,
        "span_id": str(uuid4()),
        "correlation_id": request.correlation_id,
        "causation_id": causation_operation_id or "",
        "input": {
            "project_id": request.project_id,
            "input_asset_version_ids": [],
            "payload": payload,
        },
        "input_assets": [],
        "root_operation_id": root_operation_id,
        "parent_operation_id": parent_operation_id,
        "causation_operation_id": causation_operation_id,
    }


__all__ = [
    "BookProductionAdmission",
    "BookProductionPolicy",
    "BookProductionRequest",
    "admit_book_production",
    "pause_book_production",
    "resume_book_production",
]
