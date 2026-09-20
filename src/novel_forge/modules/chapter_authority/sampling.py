from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.routing_bootstrap import (
    freeze_bootstrap_authorization,
)
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    register_saga_step,
    start_saga,
)
from novel_forge.modules.command_kernel.routing_bootstrap import (
    CHAPTER_BOOTSTRAP_TASKS,
    CHAPTER_SAMPLE_DEFINITION_VERSION,
    CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
    CHAPTER_SAMPLE_SOURCE_VERSION,
    authorization_hash,
    bootstrap_command_hash,
    chapter_sample_definition_name,
    validate_chapter_sample_origin,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation_in_uow,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .definitions import (
    CHAPTER_SAMPLE_WORKFLOW_REF,
    chapter_provider_sample_definitions,
)


@dataclass(frozen=True, slots=True)
class ChapterProviderSampleCommand:
    project_id: str
    actor_id: str
    source_operation_id: str
    authorization_id: str
    idempotency_key: str
    predecessor_operation_id: str = ""


def prepare_provider_sample(
    app: Any, command: ChapterProviderSampleCommand, *, principal: Principal
) -> dict[str, Any]:
    principal.require("chapter.authority.execute", command.project_id)
    if (
        principal.principal_type is not PrincipalType.LOCAL_OPERATOR
        or principal.principal_id != command.actor_id
    ):
        raise PermissionError(
            "Chapter sampling requires its authenticated local operator"
        )
    if not all(
        isinstance(value, str) and value.strip()
        for value in (
            command.project_id,
            command.source_operation_id,
            command.authorization_id,
            command.idempotency_key,
        )
    ) or not isinstance(command.predecessor_operation_id, str):
        raise ValueError(
            "Chapter sampling requires exact task, authorization and request identities"
        )
    with AuthorityUnitOfWork(app.database_url) as uow:
        uow.cursor.execute(
            "SELECT definition_name,definition_version,command_payload,input_asset_snapshot,workspace_id FROM authority_operation WHERE project_id=%s AND operation_id=%s",
            [command.project_id, command.source_operation_id],
        )
        source = uow.cursor.fetchone()
    if (
        not source
        or source[0] not in CHAPTER_BOOTSTRAP_TASKS
        or source[1] != CHAPTER_SAMPLE_SOURCE_VERSION
    ):
        raise KernelError(
            "CHAPTER_SAMPLE_TASK_UNSUPPORTED",
            "sampling requires a frozen native Chapter Provider task",
        )
    stage = CHAPTER_BOOTSTRAP_TASKS[source[0]]
    payload = {
        **source[2],
        "project_id": command.project_id,
        "generator_operation_name": stage,
        "logical_key": command.source_operation_id,
        "idempotency_key": command.idempotency_key,
        "input_versions": source[3],
        "chapter_predecessor_operation_id": command.predecessor_operation_id,
        "chapter_sampling": {
            "source_operation_id": command.source_operation_id,
            "source_command_hash": authorization_hash(source[2]),
        },
        "routing_bootstrap_authorization_id": command.authorization_id,
    }
    validate_chapter_sample_origin(payload, source[:4], project_id=command.project_id)
    return {
        "status": "PREPARED_NO_PROVIDER_CALL",
        "provider_calls": 0,
        "definition_name": chapter_sample_definition_name(stage),
        "definition_version": CHAPTER_SAMPLE_DEFINITION_VERSION,
        "workspace_id": source[4],
        "book_id": payload["book_id"],
        "command_payload": payload,
        "input_assets": source[3],
        "command_hash": bootstrap_command_hash(payload),
        "input_versions_hash": authorization_hash(source[3]),
        "required_workflow_ref": CHAPTER_SAMPLE_WORKFLOW_REF,
        "production_eligible": False,
    }


def admit_provider_sample(
    app: Any, command: ChapterProviderSampleCommand, *, principal: Principal
) -> dict[str, Any]:
    prepared = prepare_provider_sample(app, command, principal=principal)
    binder = app._model_port.capability_binder
    snapshot = freeze_bootstrap_authorization(
        database_url=app.database_url,
        command_payload=prepared["command_payload"],
        principal=principal,
        environment=str(getattr(binder, "pack_environment", "")),
        permission="chapter.authority.execute",
        idempotency_scope=CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
    )
    grant = snapshot["authorization"]
    if grant["purpose"] != "BENCHMARK_CHALLENGER" or not grant.get("campaign"):
        raise KernelError(
            "CHAPTER_SAMPLE_CAMPAIGN_REQUIRED",
            "Chapter sampling requires a frozen campaign grant",
        )
    definitions = chapter_provider_sample_definitions(
        application_build_id=app.application_build_id, commit_sha=app.commit_sha
    )
    definition = next(
        item for item in definitions if item["name"] == prepared["definition_name"]
    )
    trace = "chapter-sample:" + command.idempotency_key
    payload = {
        **prepared["command_payload"],
        "routing_bootstrap_authorization": snapshot,
    }
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        uow.repositories.definitions.register(definition)
        identity = authorization_hash(
            [
                command.project_id,
                grant["campaign"]["campaign_id"],
                grant["campaign"]["sample_id"],
                grant["candidate_id"],
                grant["model_revision"],
            ]
        )
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [identity]
        )
        _require_predecessor(uow, command, payload)
        admitted = admit_command_in_uow(
            uow,
            {
                "definition_name": definition["name"],
                "definition_version": CHAPTER_SAMPLE_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": prepared["workspace_id"],
                "book_id": prepared["book_id"],
                "logical_key": command.source_operation_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
                "idempotency_key": command.idempotency_key,
                "trace_id": trace,
                "span_id": str(uuid4()),
                "correlation_id": trace,
                "causation_id": command.predecessor_operation_id
                or command.source_operation_id,
                "causation_operation_id": command.predecessor_operation_id
                or command.source_operation_id,
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in prepared["input_assets"]
                    ],
                    "payload": payload,
                },
                "input_assets": prepared["input_assets"],
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=principal.permissions,
                available_handlers=frozenset({definition["handler_key"]}),
                application_build_id=app.application_build_id,
                commit_sha=app.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        operation = uow.repositories.attempt_runtime.operation_state(
            operation_id, command.project_id
        )
        if operation["status"] == "ADMITTED":
            transition_operation_in_uow(
                uow,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(operation["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=principal.principal_id,
                    reason="authorized Chapter sample inputs frozen",
                    trace_id=trace,
                    correlation_id=trace,
                    causation_id=command.source_operation_id,
                ),
            )
        graph_context = GraphCommandContext(
            command.project_id, principal.principal_id, trace, trace
        )
        saga = start_saga(
            app.database_url, graph_context, root_operation_id=operation_id
        )
        register_saga_step(
            app.database_url,
            graph_context,
            str(saga["saga_id"]),
            operation_id,
            "provider_sample",
            1,
            "",
        )
        uow.commit()
    return {
        "operation_id": operation_id,
        "replayed": bool(admitted["replayed"]),
        "production_eligible": False,
        "campaign_id": grant["campaign"]["campaign_id"],
        "authorization_id": command.authorization_id,
    }


def _require_predecessor(
    uow: AuthorityUnitOfWork,
    command: ChapterProviderSampleCommand,
    payload: dict[str, Any],
) -> None:
    grant = payload["routing_bootstrap_authorization"]["authorization"]
    uow.cursor.execute(
        """SELECT operation_id,status,actor_id,idempotency_key,command_payload->'payload'
           FROM authority_operation WHERE project_id=%s
             AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,campaign_id}'=%s
             AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,campaign,sample_id}'=%s
             AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,candidate_id}'=%s
             AND command_payload #>> '{payload,routing_bootstrap_authorization,authorization,model_revision}'=%s
           ORDER BY created_at,operation_id FOR UPDATE""",
        [
            command.project_id,
            grant["campaign"]["campaign_id"],
            grant["campaign"]["sample_id"],
            grant["candidate_id"],
            grant["model_revision"],
        ],
    )
    rows = uow.cursor.fetchall()
    if any(row[3] == command.idempotency_key for row in rows):
        return
    if not rows:
        if command.predecessor_operation_id:
            raise KernelError(
                "CHAPTER_SAMPLE_PREDECESSOR_INVALID",
                "predecessor must belong to this sample model arm",
            )
        return
    prior = rows[-1]
    if command.predecessor_operation_id != prior[0]:
        raise KernelError(
            "CHAPTER_SAMPLE_PREDECESSOR_REQUIRED",
            "sample replacement must retain its latest Operation lineage",
        )
    previous = prior[4]
    if (
        prior[2] != command.actor_id
        or previous.get("chapter_sampling") != payload["chapter_sampling"]
        or previous.get("input_versions") != payload["input_versions"]
        or previous["routing_bootstrap_authorization"]["authorization"]["campaign"]
        != grant["campaign"]
    ):
        raise KernelError(
            "CHAPTER_SAMPLE_PREDECESSOR_INVALID",
            "replacement must preserve operator, task, inputs and campaign sample",
        )
    uow.cursor.execute(
        "SELECT external_effect_id,status FROM authority_external_effect WHERE project_id=%s AND operation_id=%s FOR UPDATE",
        [command.project_id, prior[0]],
    )
    effects = uow.cursor.fetchall()
    replaceable = not effects
    if len(effects) == 1 and effects[0][1] in {"FAILED_FINAL", "DEAD_LETTER"}:
        uow.cursor.execute(
            "SELECT status FROM authority_external_effect_dispatch WHERE external_effect_id=%s ORDER BY generation FOR UPDATE",
            [effects[0][0]],
        )
        dispatches = uow.cursor.fetchall()
        replaceable = bool(dispatches) and all(
            item[0] in {"FAILED_FINAL", "DEAD_LETTER"} for item in dispatches
        )
    if prior[1] not in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"} or not replaceable:
        raise KernelError(
            "CHAPTER_SAMPLE_PREDECESSOR_NOT_REPLACEABLE",
            "recover existing success and reconcile unknown outcomes without resending",
        )
