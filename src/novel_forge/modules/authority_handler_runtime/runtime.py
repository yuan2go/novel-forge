"""Generic fenced execution envelope for storage-free authority handlers."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.contracts import (
    AuthorityExecutionResult,
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def execute_authority_handler(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    registration: AuthorityHandlerRegistration,
) -> AuthorityExecutionResult:
    request = _load_request(database_url, command, registration)
    output = registration.handler.execute(request)
    _validate_output(registration, output)
    content_hash = _content_hash(output.content)
    identity = _stable_identity(request.operation_id, output.output_key)

    with AuthorityUnitOfWork(database_url) as uow:
        attempt = require_current_fence(uow, command)
        if attempt["operation_id"] != request.operation_id:
            raise KernelError(
                "AUTHORITY_HANDLER_OPERATION_CONFLICT",
                "Attempt operation changed during handler execution",
            )
        created = uow.repositories.chapter_authority.materialize_output(
            operation_id=request.operation_id,
            project_id=request.project_id,
            asset_id=identity[0],
            asset_version_id=identity[1],
            qualification_id=identity[2],
            asset_type=output.asset_type,
            output_key=output.output_key,
            role=output.role,
            content=output.content,
            content_hash=content_hash,
            qualification_policy=output.qualification_policy,
            qualification_evidence={
                "operation_id": request.operation_id,
                "project_id": request.project_id,
                "trace_id": request.trace_id,
                "correlation_id": request.correlation_id,
                "definition_name": request.definition_name,
                "definition_version": request.definition_version,
                "handler_key": registration.handler_key,
                "handler_contract_version": registration.handler_contract_version,
                "input_asset_version_ids": [item.asset_version_id for item in request.inputs],
                "reference_asset_version_ids": list(output.reference_asset_version_ids),
                "policy": output.qualification_policy,
                "evidence": output.evidence,
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
                    "event_type": registration.completion_topic,
                    "correlation_id": request.correlation_id,
                    "causation_id": command.causation_id,
                    "payload": {
                        "operation_id": request.operation_id,
                        "asset_id": identity[0],
                        "asset_version_id": identity[1],
                        "content_hash": content_hash,
                        "output_key": output.output_key,
                        "role": output.role,
                        "trace_id": request.trace_id,
                        "worker_id": command.worker_id,
                        "fencing_token": command.fencing_token,
                        "input_asset_version_ids": [
                            item.asset_version_id for item in request.inputs
                        ],
                    },
                }
            )
        uow.commit()
    return AuthorityExecutionResult(
        operation_id=request.operation_id,
        asset_id=identity[0],
        asset_version_id=identity[1],
        content_hash=content_hash,
        output_key=output.output_key,
        replayed=not created,
    )


def _load_request(
    database_url: str,
    command: WorkerLeaseCommand,
    registration: AuthorityHandlerRegistration,
) -> AuthorityHandlerRequest:
    with AuthorityUnitOfWork(database_url) as uow:
        attempt = require_current_fence(uow, command)
        operation = uow.repositories.chapter_authority.operation_execution(
            attempt["operation_id"], command.project_id
        )
        if operation["definition_name"] != registration.definition_name:
            raise KernelError(
                "AUTHORITY_HANDLER_DEFINITION_CONFLICT",
                f"handler cannot execute {operation['definition_name']}",
            )
        snapshot = operation["definition_snapshot"] or {}
        if snapshot.get("handler_key") != registration.handler_key:
            raise KernelError(
                "AUTHORITY_HANDLER_DEFINITION_CONFLICT",
                "frozen handler key does not match the runtime registration",
            )
        if str(operation["definition_version"]) != registration.definition_version:
            raise KernelError(
                "AUTHORITY_HANDLER_CONTRACT_STALE",
                "frozen definition version does not match the runtime codec",
            )
        frozen = uow.repositories.chapter_authority.frozen_inputs(
            command.project_id, list(operation["input_asset_snapshot"] or [])
        )
    return AuthorityHandlerRequest(
        operation_id=operation["operation_id"],
        project_id=operation["project_id"],
        workspace_id=operation["workspace_id"],
        actor_id=operation["actor_id"],
        trace_id=operation["trace_id"],
        correlation_id=operation["correlation_id"],
        definition_name=operation["definition_name"],
        definition_version=operation["definition_version"],
        command=dict(operation["command_payload"]),
        inputs=tuple(AuthorityInputAsset(**item) for item in frozen),
    )


def require_current_fence(uow: AuthorityUnitOfWork, command: WorkerLeaseCommand) -> dict[str, Any]:
    attempt = uow.repositories.attempt_runtime.get_for_update(
        command.attempt_id, command.project_id
    )
    valid, _current_token = uow.repositories.attempt_runtime.current_fence(
        command.attempt_id, command.worker_id, command.fencing_token
    )
    if not valid:
        raise KernelError(
            "ATTEMPT_FENCING_TOKEN_STALE",
            "authority handler does not carry the current Attempt fencing token",
        )
    if attempt["status"] not in {"RUNNING", "CHECKPOINTED"}:
        raise KernelError(
            "ATTEMPT_STATUS_CONFLICT",
            f"authority handler requires RUNNING/CHECKPOINTED Attempt, current {attempt['status']}",
        )
    if attempt["operation_status"] != "EXECUTING":
        raise KernelError(
            "OPERATION_STATUS_CONFLICT",
            f"authority handler requires EXECUTING Operation, current {attempt['operation_status']}",
        )
    return attempt


def _validate_output(
    registration: AuthorityHandlerRegistration, output: AuthorityHandlerOutput
) -> None:
    if (
        not isinstance(output, AuthorityHandlerOutput)
        or output.asset_type != registration.output_asset_type
        or output.output_key != registration.output_key
        or output.role != registration.role
        or not isinstance(output.content, dict)
    ):
        raise KernelError(
            "AUTHORITY_HANDLER_OUTPUT_INVALID",
            f"{registration.definition_name} output violates its frozen contract",
        )


def _stable_identity(operation_id: str, output_key: str) -> tuple[str, str, str]:
    prefix = f"authority-output:{operation_id}:{output_key}"
    return prefix, f"{prefix}:v1", f"{prefix}:qualification:v1"


def _content_hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(
        content, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
