"""Fenced runtime for pure chapter handlers and authoritative outputs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterInputAsset,
    ChapterNode,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ChapterExecutionResult:
    operation_id: str
    asset_id: str
    asset_version_id: str
    content_hash: str
    output_key: str
    replayed: bool


def execute_chapter_handler(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    node: ChapterNode,
    registry: ChapterHandlerRegistry,
) -> ChapterExecutionResult:
    request = _load_request(database_url, command, node)
    output = registry.require(node).execute(request)
    _validate_output(node, output)
    content_hash = _content_hash(output.content)
    asset_id = f"chapter-output:{request.operation_id}:{output.output_key}"
    asset_version_id = f"chapter-output-version:{request.operation_id}:{output.output_key}:v1"
    qualification_id = f"chapter-output-qualification:{request.operation_id}:{output.output_key}:v1"

    with AuthorityUnitOfWork(database_url) as uow:
        attempt = _require_fence(uow, command)
        if attempt["operation_id"] != request.operation_id:
            raise KernelError(
                "CHAPTER_HANDLER_OPERATION_CONFLICT",
                "Attempt operation changed during handler execution",
            )
        created = uow.repositories.chapter_authority.materialize_output(
            operation_id=request.operation_id,
            project_id=request.project_id,
            asset_id=asset_id,
            asset_version_id=asset_version_id,
            qualification_id=qualification_id,
            asset_type=output.asset_type,
            output_key=output.output_key,
            role=output.role,
            content=output.content,
            content_hash=content_hash,
            qualification_policy=output.qualification_policy,
            qualification_evidence={
                "operation_id": request.operation_id,
                "trace_id": request.trace_id,
                "handler_key": node.handler_key,
                "policy": output.qualification_policy,
            },
        )
        if created:
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_operation",
                    "aggregate_id": request.operation_id,
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "event_type": node.completion_topic,
                    "correlation_id": request.correlation_id,
                    "causation_id": command.causation_id,
                    "payload": {
                        "operation_id": request.operation_id,
                        "asset_id": asset_id,
                        "asset_version_id": asset_version_id,
                        "content_hash": content_hash,
                        "output_key": output.output_key,
                        "role": output.role,
                        "trace_id": request.trace_id,
                        "worker_id": command.worker_id,
                        "fencing_token": command.fencing_token,
                    },
                }
            )
        uow.commit()
    return ChapterExecutionResult(
        operation_id=request.operation_id,
        asset_id=asset_id,
        asset_version_id=asset_version_id,
        content_hash=content_hash,
        output_key=output.output_key,
        replayed=not created,
    )


def _load_request(
    database_url: str,
    command: WorkerLeaseCommand,
    node: ChapterNode,
) -> ChapterHandlerRequest:
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = _require_fence(uow, command)
        operation = uow.repositories.chapter_authority.operation_execution(
            attempt["operation_id"],
            command.project_id,
        )
        if operation["definition_name"] != node.definition_name:
            raise KernelError(
                "CHAPTER_HANDLER_DEFINITION_CONFLICT",
                f"{node.value} handler cannot execute {operation['definition_name']}",
            )
        if operation["definition_snapshot"].get("handler_key") != node.handler_key:
            raise KernelError(
                "CHAPTER_HANDLER_DEFINITION_CONFLICT",
                "frozen handler key does not match the runtime node",
            )
        inputs = uow.repositories.chapter_authority.frozen_inputs(
            command.project_id,
            list(operation["input_asset_snapshot"] or []),
        )
    return ChapterHandlerRequest(
        operation_id=operation["operation_id"],
        project_id=operation["project_id"],
        workspace_id=operation["workspace_id"],
        trace_id=operation["trace_id"],
        correlation_id=operation["correlation_id"],
        command=dict(operation["command_payload"]),
        inputs=tuple(ChapterInputAsset(**item) for item in inputs),
    )


def _require_fence(uow: AuthorityUnitOfWork, command: WorkerLeaseCommand) -> dict[str, Any]:
    attempt = uow.repositories.attempt_runtime.get_for_update(
        command.attempt_id,
        command.project_id,
    )
    valid, _current_token = uow.repositories.attempt_runtime.current_fence(
        command.attempt_id,
        command.worker_id,
        command.fencing_token,
    )
    if not valid:
        raise KernelError(
            "ATTEMPT_FENCING_TOKEN_STALE",
            "chapter handler does not carry the current Attempt fencing token",
        )
    if attempt["status"] not in {"RUNNING", "CHECKPOINTED"}:
        raise KernelError(
            "ATTEMPT_STATUS_CONFLICT",
            f"chapter handler requires RUNNING/CHECKPOINTED Attempt, current {attempt['status']}",
        )
    if attempt["operation_status"] != "EXECUTING":
        raise KernelError(
            "OPERATION_STATUS_CONFLICT",
            f"chapter handler requires EXECUTING Operation, current {attempt['operation_status']}",
        )
    return attempt


def _validate_output(node: ChapterNode, output: Any) -> None:
    if (
        output.asset_type != node.asset_type
        or output.output_key != node.output_key
        or output.role != "primary"
        or not isinstance(output.content, dict)
    ):
        raise KernelError(
            "CHAPTER_HANDLER_OUTPUT_INVALID",
            f"{node.value} handler output violates its frozen contract",
        )


def _content_hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
