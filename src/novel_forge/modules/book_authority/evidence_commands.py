from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def book_editorial_command_schema(name: str) -> dict[str, Any]:
    fields = {
        "book.prose_review.start": ("policy", "evidence_ranges"),
        "book.prose_review.advance": ("run_id", "expected_version"),
        "book.prose_review.control": ("run_id", "expected_version", "paused", "reason"),
        "book.prose_review.disposition": (
            "run_id",
            "expected_version",
            "lineage_id",
            "finding_digest",
            "decision",
            "rationale",
            "consumer_asset_version_id",
        ),
        "book.editorial.policy": ("expected_version", "kind", "content"),
        "book.editorial.signature": ("expected_version", "kind", "content"),
        "book.editorial.revocation": ("expected_version", "kind", "content"),
    }[name]
    properties = {
        key: {
            "type": "string",
            "minLength": 0 if key == "consumer_asset_version_id" else 1,
        }
        for key in ("project_id", "workspace_id", "book_run_id", *fields)
    }
    for key in ("policy", "content"):
        if key in properties:
            properties[key] = {"type": "object"}
    if "expected_version" in properties:
        properties["expected_version"] = {"type": "integer", "minimum": 0}
    if "paused" in properties:
        properties["paused"] = {"type": "boolean"}
    if "evidence_ranges" in properties:
        properties["evidence_ranges"] = {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": ["asset_version_id", "start", "end"],
                "additionalProperties": False,
                "properties": {
                    "asset_version_id": {"type": "string", "minLength": 1},
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 1},
                },
            },
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def execute_book_evidence_command(
    *,
    database_url: str,
    application_build_id: str,
    commit_sha: str,
    name: str,
    payload: dict[str, Any],
    principal: Principal,
    idempotency_key: str,
    trace_id: str,
    correlation_id: str,
    handler: Callable[..., dict[str, Any]],
    fault_injector: TransactionCheckpoint | None = None,
) -> dict[str, Any]:
    from .completion import book_completion_definitions

    principal.require("book.authority.execute", payload["project_id"])
    definition = deepcopy(
        book_completion_definitions(
            application_build_id=application_build_id, commit_sha=commit_sha
        )[0]
    )
    command_schema = book_editorial_command_schema(name)
    definition.update(
        name=name,
        handler_key="novel_forge." + name,
        command_schema=command_schema,
        result_schema={"type": "object"},
        input_contract=command_schema,
        output_contract={"type": "BookEditorialEvidence"},
        command_schema_version=name + ".command.v1",
        result_schema_version=name + ".result.v1",
        idempotency_scope="project:" + name,
        completion_contract={
            "version": "book-editorial-evidence.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [name],
        },
    )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(definition)
        uow.commit()

    def execute(
        uow: AuthorityUnitOfWork, operation_id: str, checkpoint: TransactionCheckpoint
    ) -> dict[str, Any]:
        uow.cursor.execute(
            "SELECT book_run_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s FOR UPDATE",
            [payload["book_run_id"], payload["project_id"], payload["workspace_id"]],
        )
        if not uow.cursor.fetchone():
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError(
                "BOOK_EDITORIAL_SCOPE_MISMATCH",
                "exact Project/Workspace/Book production scope is required",
            )
        result = handler(uow, operation_id, checkpoint)
        checkpoint("after_book_editorial_evidence")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_editorial",
                "aggregate_id": payload["book_run_id"],
                "operation_id": operation_id,
                "project_id": payload["project_id"],
                "event_type": name,
                "correlation_id": correlation_id,
                "causation_id": operation_id,
                "payload": {
                    "operation_id": operation_id,
                    "book_run_id": payload["book_run_id"],
                },
            }
        )
        return result

    return execute_transaction_command(
        database_url,
        {
            "definition_name": name,
            "definition_version": definition["definition_version"],
            "project_id": payload["project_id"],
            "workspace_id": payload["workspace_id"],
            "actor_id": principal.principal_id,
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": idempotency_key,
            "trace_id": trace_id,
            "span_id": str(uuid4()),
            "correlation_id": correlation_id,
            "causation_id": "",
            "input": payload,
            "input_assets": [],
        },
        context=AdmissionContext(
            actor_id=principal.principal_id,
            permissions=frozenset({"book.authority.execute"}),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        ),
        handler=execute,
        fault_injector=fault_injector,
    )
