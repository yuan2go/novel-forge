from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_repositories import IdempotencyConflictError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class AdmissionContext:
    actor_id: str
    permissions: frozenset[str]
    available_handlers: frozenset[str]
    application_build_id: str
    commit_sha: str


TransactionCheckpoint = Callable[[str], None]
TransactionHandler = Callable[
    [AuthorityUnitOfWork, str, TransactionCheckpoint], dict[str, Any]
]


def execute_transaction_command(
    database_url: str,
    command: dict[str, Any],
    *,
    context: AdmissionContext,
    handler: TransactionHandler,
    fault_injector: TransactionCheckpoint | None = None,
) -> dict[str, Any]:
    """Execute a short, deterministic command in one PostgreSQL transaction.

    Transaction commands never create Attempts or Leases. Admission, business
    state, completion evidence, the replay result, and the terminal Operation
    transition are committed together. The one post-commit checkpoint models a
    lost HTTP response and is intentionally outside the transaction.
    """

    checkpoint = fault_injector or _noop_checkpoint
    checkpoint("before_admission")
    with AuthorityUnitOfWork(database_url) as uow:
        admitted = admit_command_in_uow(uow, command, context=context)
        operation_id = str(admitted["operation_id"])
        if admitted["replayed"]:
            replay = uow.repositories.operations.transaction_result(
                operation_id,
                str(command["project_id"]),
            )
            if replay["status"] != "SUCCEEDED":
                raise KernelError(
                    "TRANSACTION_COMMAND_INCOMPLETE",
                    "a persisted transaction command is not terminal; legacy hybrid recovery is required",
                )
            return {
                "operation_id": operation_id,
                "status": "SUCCEEDED",
                **dict(replay["result"]),
                "replayed": True,
            }

        checkpoint("after_admission")
        definition = uow.repositories.definitions.get(
            str(command["definition_name"]),
            str(command["definition_version"]),
        )
        if definition is None:  # admission already proves this; fail closed on drift
            raise KernelError(
                "OPERATION_DEFINITION_NOT_FOUND",
                "transaction command definition disappeared during execution",
            )
        if (
            definition["execution_mode"] != "transactional"
            or definition["policy"].get("execution_classification")
            != "transaction_command"
        ):
            raise KernelError(
                "EXECUTION_CLASSIFICATION_CONFLICT",
                "only transaction-classified definitions may execute inline atomically",
            )

        result = handler(uow, operation_id, checkpoint)
        _validate_json_schema(definition["result_schema"], result, "result")

        from novel_forge.modules.command_kernel.completion import (
            evaluate_completion_in_uow,
        )

        operation = uow.repositories.completion_contracts.operation(
            operation_id,
            str(command["project_id"]),
            lock=True,
        )
        completion = evaluate_completion_in_uow(uow, operation)
        if completion["target_status"] != "SUCCEEDED":
            raise KernelError(
                "TRANSACTION_COMPLETION_CONTRACT_UNSATISFIED",
                "transaction command completion contract is not satisfied: "
                + ", ".join(completion["missing"] + completion["failed"]),
            )

        checkpoint("before_operation_completion")
        completed = uow.repositories.operation_lifecycle.complete_transaction_command(
            {
                "operation_id": operation_id,
                "project_id": str(command["project_id"]),
                "expected_version": int(operation["version"]),
                "result": result,
            }
        )
        uow.repositories.runtime_evidence.record_operation_transition(
            {
                "operation_id": operation_id,
                "project_id": str(command["project_id"]),
                "expected_version": int(operation["version"]),
                "expected_status": "ADMITTED",
                "target_status": "SUCCEEDED",
                "actor_id": context.actor_id,
                "reason": "atomic transaction command committed",
                "trace_id": str(command["trace_id"]),
                "correlation_id": str(command["correlation_id"]),
                "causation_id": str(command.get("causation_id") or ""),
                "version": int(completed["version"]),
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
            }
        )
        uow.commit()

    checkpoint("after_operation_completion_before_response")
    return {
        "operation_id": operation_id,
        "status": "SUCCEEDED",
        **result,
        "replayed": False,
    }


def _noop_checkpoint(_name: str) -> None:
    return None


def admit_command(
    database_url: str,
    command: dict[str, Any],
    *,
    context: AdmissionContext | None = None,
) -> dict[str, Any]:
    if context is None:
        raise KernelError(
            "ADMISSION_CONTEXT_REQUIRED",
            "admission requires authenticated runtime context",
        )

    with AuthorityUnitOfWork(database_url) as uow:
        result = admit_command_in_uow(uow, command, context=context)
        if not result["replayed"]:
            uow.commit()
    return result


def admit_command_in_uow(
    uow: AuthorityUnitOfWork,
    command: dict[str, Any],
    *,
    context: AdmissionContext,
) -> dict[str, Any]:
    _validate_command_identity(command)
    definition = uow.repositories.definitions.get(
        str(command["definition_name"]),
        str(command["definition_version"]),
    )
    if definition is None:
        raise KernelError(
            "OPERATION_DEFINITION_NOT_FOUND",
            "operation definition was not registered",
        )
    _validate_definition_and_command(definition, command, context)
    input_asset_snapshot = uow.repositories.asset_references.resolve_for_admission(
        str(command["project_id"]),
        list(command.get("input_assets") or []),
    )
    concurrency_key = _resolve_concurrency_key(definition, command)
    digest = _request_digest(command, input_asset_snapshot)
    operation_id = str(uuid4())
    created = uow.repositories.operations.try_create(
        {
            **command,
            "operation_id": operation_id,
            "root_operation_id": command.get("root_operation_id") or operation_id,
            "parent_operation_id": command.get("parent_operation_id"),
            "causation_operation_id": command.get("causation_operation_id"),
            "request_digest": digest,
            "definition_snapshot": {
                **definition,
                "application_build_id": context.application_build_id,
                "commit_sha": context.commit_sha,
            },
            "completion_contract_snapshot": definition["completion_contract"],
            "policy_snapshot": definition["policy"],
            "approval_requirement_snapshot": {
                "policy": definition["approval_policy"],
                "evidence": command.get("approval") or {},
            },
            "input_asset_snapshot": input_asset_snapshot,
            "concurrency_key": concurrency_key,
            "command_payload": command.get("input", {}),
            "causation_id": command.get("causation_id") or "",
        }
    )
    if not created:
        existing = uow.repositories.operations.get_idempotency(
            str(command["idempotency_scope"]),
            str(command["idempotency_key"]),
        )
        if existing is None or existing[1] != digest:
            raise IdempotencyConflictError(
                "idempotency key belongs to a different request digest"
            )
        return {"operation_id": existing[0], "replayed": True}

    event_id = str(uuid4())
    evidence_payload = {
        "operation_id": operation_id,
        "definition_name": command["definition_name"],
        "definition_version": command["definition_version"],
        "request_digest": digest,
        "trace_id": command["trace_id"],
        "span_id": command["span_id"],
    }
    uow.repositories.admission_evidence.record(
        {
            **command,
            "operation_id": operation_id,
            "request_digest": digest,
            "event_id": event_id,
            "audit_id": str(uuid4()),
            "outbox_id": str(uuid4()),
            "causation_id": command.get("causation_id") or "",
            "event_payload": evidence_payload,
            "audit_payload": {
                **evidence_payload,
                "actor_id": context.actor_id,
                "approval": command.get("approval") or {},
            },
            "outbox_payload": evidence_payload,
        }
    )
    return {"operation_id": operation_id, "replayed": False}


def _validate_command_identity(command: dict[str, Any]) -> None:
    required = (
        "definition_name",
        "definition_version",
        "project_id",
        "workspace_id",
        "actor_id",
        "idempotency_scope",
        "idempotency_key",
        "trace_id",
        "span_id",
        "correlation_id",
    )
    missing = [key for key in required if not str(command.get(key, ""))]
    if missing:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID",
            f"missing command fields: {', '.join(missing)}",
        )
    if not isinstance(command.get("input", {}), dict):
        raise KernelError("COMMAND_SCHEMA_INVALID", "command input must be an object")
    if not isinstance(command.get("input_assets", []), list):
        raise KernelError("COMMAND_SCHEMA_INVALID", "input_assets must be an array")


def _validate_definition_and_command(
    definition: dict[str, Any],
    command: dict[str, Any],
    context: AdmissionContext,
) -> None:
    if not definition["enabled"]:
        raise KernelError(
            "OPERATION_DEFINITION_DISABLED",
            "operation definition is disabled",
        )
    if definition["handler_key"] not in context.available_handlers:
        raise KernelError(
            "HANDLER_NOT_AVAILABLE",
            f"handler is not available: {definition['handler_key']}",
        )
    required_permissions = set(definition["permissions"])
    if not required_permissions.issubset(context.permissions):
        raise KernelError(
            "PERMISSION_DENIED",
            "actor lacks one or more required permissions",
        )
    if command["actor_id"] != context.actor_id or not context.actor_id:
        raise KernelError(
            "ACTOR_IDENTITY_INVALID",
            "command actor does not match authenticated actor",
        )
    if command["idempotency_scope"] != definition["idempotency_scope"]:
        raise KernelError(
            "IDEMPOTENCY_SCOPE_INVALID",
            "command idempotency scope does not match the definition",
        )
    _validate_json_schema(definition["command_schema"], command.get("input", {}))
    approval_policy = definition["approval_policy"]
    if approval_policy.get("required"):
        approval = command.get("approval")
        if not isinstance(approval, dict) or approval.get("status") != "APPROVED":
            raise KernelError("APPROVAL_REQUIRED", "approved evidence is required")
        if approval.get("project_id") != command["project_id"]:
            raise KernelError(
                "CROSS_PROJECT_REFERENCE",
                "approval evidence belongs to another project",
            )


def _validate_json_schema(
    schema: dict[str, Any], value: Any, path: str = "input"
) -> None:
    expected_type = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    if expected_type in type_map and not isinstance(value, type_map[expected_type]):
        raise KernelError(
            "COMMAND_SCHEMA_INVALID",
            f"{path} must have type {expected_type}",
        )
    if expected_type != "object" or not isinstance(value, dict):
        return
    missing = [key for key in schema.get("required", []) if key not in value]
    if missing:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID",
            f"{path} is missing required fields: {', '.join(missing)}",
        )
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(value) - set(properties))
        if unknown:
            raise KernelError(
                "COMMAND_SCHEMA_INVALID",
                f"{path} has unknown fields: {', '.join(unknown)}",
            )
    for key, property_schema in properties.items():
        if key in value:
            _validate_json_schema(property_schema, value[key], f"{path}.{key}")


def _resolve_concurrency_key(
    definition: dict[str, Any],
    command: dict[str, Any],
) -> str:
    try:
        return str(definition["concurrency_key_template"]).format_map(command)
    except KeyError as exc:
        raise KernelError(
            "COMMAND_SCHEMA_INVALID",
            f"concurrency key is missing command field: {exc.args[0]}",
        ) from exc


def _request_digest(
    command: dict[str, Any],
    input_asset_snapshot: list[dict[str, str]],
) -> str:
    canonical_request = {
        "definition_name": command["definition_name"],
        "definition_version": command["definition_version"],
        "project_id": command["project_id"],
        "workspace_id": command["workspace_id"],
        "actor_id": command["actor_id"],
        "input": command.get("input", {}),
        "input_assets": input_asset_snapshot,
        "approval": command.get("approval") or {},
    }
    encoded = json.dumps(
        canonical_request,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
