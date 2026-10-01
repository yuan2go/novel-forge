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
    CHAPTER_REFERENCE_TASKS,
    CHAPTER_SAMPLE_DEFINITION_VERSION,
    CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
    chapter_sample_source_version_supported,
    chapter_sample_definition_supported,
    CHAPTER_REFERENCE_SAMPLE_VERSION,
    CHAPTER_REFERENCE_SAMPLE_SOURCES,
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
from novel_forge.storage.authority_repositories import definition_hash

from .definitions import (
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
    reference_evaluation: dict[str, Any] | None = None
    generation_sample: dict[str, str] | None = None
    reference_stage: str = ""


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
        or not chapter_sample_source_version_supported(source[1])
    ):
        raise KernelError(
            "CHAPTER_SAMPLE_TASK_UNSUPPORTED",
            "sampling requires a frozen native Chapter Provider task",
        )
    stage = command.reference_stage if command.generation_sample is not None else CHAPTER_BOOTSTRAP_TASKS[source[0]]
    if command.generation_sample is not None:
        if CHAPTER_REFERENCE_SAMPLE_SOURCES.get(stage) != source[0]:
            raise KernelError("CHAPTER_SAMPLE_TASK_UNSUPPORTED", "reference stage must match its original native generator")
    elif command.reference_stage:
        raise KernelError("CHAPTER_SAMPLE_TASK_UNSUPPORTED", "reference stage selection requires an exact generator sample")
    inputs = [*source[3], command.generation_sample] if command.generation_sample is not None else source[3]
    reference = stage in CHAPTER_REFERENCE_TASKS.values()
    if not reference and command.reference_evaluation is not None:
        raise KernelError("QUALITY_REFERENCE_TASK_UNSUPPORTED", "generator samples cannot consume reviewer labels")
    payload = {
        **source[2],
        "project_id": command.project_id,
        "generator_operation_name": stage,
        "logical_key": command.source_operation_id,
        "idempotency_key": command.idempotency_key,
        "input_versions": inputs,
        "chapter_predecessor_operation_id": command.predecessor_operation_id,
        "chapter_sampling": {
            "source_operation_id": command.source_operation_id,
            "source_command_hash": authorization_hash(source[2]),
            **({"generation_sample": command.generation_sample} if command.generation_sample is not None else {}),
        },
        "routing_bootstrap_authorization_id": command.authorization_id,
        **({"reference_evaluation": command.reference_evaluation} if reference else {}),
    }
    validate_chapter_sample_origin(payload, source[:4], project_id=command.project_id)
    if stage == "canon_support" and command.reference_evaluation is None:
        from novel_forge.modules.chapter_quality_authority.canon_support_reference import source_contract
        with AuthorityUnitOfWork(app.database_url) as uow:
            contract = source_contract(uow.cursor, project_id=command.project_id, input_versions=inputs)
        return {"status": "REFERENCE_LABELS_REQUIRED_NO_PROVIDER_CALL", "provider_calls": 0,
            "source_operation_id": command.source_operation_id, "reference_contract": contract}
    if reference:
        from novel_forge.modules.chapter_quality_authority.reference_sampling import require_chapter_reference
        from novel_forge.modules.chapter_quality_authority.reference_subject import require_chapter_sample_target

        with AuthorityUnitOfWork(app.database_url) as uow:
            subject = require_chapter_sample_target(uow.cursor, project_id=command.project_id, payload=payload) if command.generation_sample else None
            require_chapter_reference(uow.cursor, project_id=command.project_id, stage=stage,
                input_versions=inputs, binding=command.reference_evaluation,
                evaluator_actor_id=command.actor_id, chapter=source[2]["chapter"], generation_sample=subject)
    definition_name = chapter_sample_definition_name(stage)
    definition_version = CHAPTER_REFERENCE_SAMPLE_VERSION if command.generation_sample else CHAPTER_SAMPLE_DEFINITION_VERSION
    with AuthorityUnitOfWork(app.database_url) as uow:
        existing_definition = _existing_sample_definition(uow, project_id=command.project_id,
            idempotency_key=command.idempotency_key, definition_name=definition_name,
            reference_samples=command.generation_sample is not None)
    if existing_definition is not None:
        definition_version = existing_definition["definition_version"]
    producer = reference_sample_producer_identity(app, payload=payload, workspace_id=source[4]) if command.generation_sample else None
    generator_evaluation = None
    if not reference:
        from novel_forge.modules.chapter_quality_authority.generator_reference import generator_reference_contract
        with AuthorityUnitOfWork(app.database_url) as uow:
            uow.cursor.execute("""SELECT request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,producer_contract_hash}'
                FROM authority_external_effect WHERE project_id=%s AND operation_id=%s
                ORDER BY created_at DESC LIMIT 1""", [command.project_id, command.source_operation_id])
            original_contract = uow.cursor.fetchone()
        if original_contract and original_contract[0]:
            generator_evaluation = generator_reference_contract(stage, original_contract[0])
    return {
        "status": "PREPARED_NO_PROVIDER_CALL",
        "provider_calls": 0,
        "definition_name": definition_name,
        "definition_version": definition_version,
        "workspace_id": source[4],
        "book_id": payload["book_id"],
        "command_payload": payload,
        "input_assets": inputs,
        "command_hash": bootstrap_command_hash(payload),
        "input_versions_hash": authorization_hash(inputs),
        **({"producer_contract": producer, "producer_contract_hash": authorization_hash(producer)} if producer else {}),
        "required_workflow_ref": ("chapter_reference_sampling" if reference else "chapter_provider_sampling") + "@" + definition_version,
        "production_eligible": False,
        **({"generator_evaluation_contract": generator_evaluation} if generator_evaluation else {}),
    }


def _existing_sample_definition(uow: Any, *, project_id: str, idempotency_key: str,
    definition_name: str, reference_samples: bool) -> dict[str, Any] | None:
    uow.cursor.execute("""SELECT definition_name,definition_version,definition_snapshot FROM authority_operation
        WHERE project_id=%s AND idempotency_scope=%s AND idempotency_key=%s""",
        [project_id, CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE, idempotency_key])
    row = uow.cursor.fetchone()
    if row is None:
        return None
    if row[0] != definition_name or not chapter_sample_definition_supported(row[0], row[1], reference_samples=reference_samples):
        raise KernelError("AUTHORITY_HANDLER_CONTRACT_STALE", "sample replay requires its published handler contract")
    definition = uow.repositories.definitions.get(row[0], row[1])
    if (definition is None or definition_hash(definition) != definition["definition_hash"]
        or row[2].get("definition_hash") != definition["definition_hash"]
        or row[2].get("handler_key") != definition["handler_key"]):
        raise KernelError("AUTHORITY_HANDLER_CONTRACT_STALE", "sample replay requires its unchanged registered definition")
    return definition


def reference_sample_producer_identity(app: Any, *, payload: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    from copy import deepcopy
    import json
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from novel_forge.modules.capability_pack_authority.runtime import CapabilityPackResolutionRequest, materialize_registered_pack_version
    from .contracts import ChapterHandlerRequest, ChapterInputAsset
    from .execution_gateway import (
        PostgresChapterExecutionContractBinder, _materialize_production_codex_prompt, chapter_producer_contract_identity,
        _stage_tool_permissions,
    )
    from .review_window import prepare_native_review

    database_url = app.database_url
    binder = app._model_port.capability_binder
    query = AuthorityAssetQuery(database_url)
    documents = [query.require(project_id=payload["project_id"], asset_version_id=item["asset_version_id"])
                 for item in payload["input_versions"]]
    for document, binding in zip(documents, payload["input_versions"], strict=True):
        if document.content_hash != binding["content_hash"] or document.content_hash != authorization_hash(document.content):
            raise KernelError("CHAPTER_SAMPLE_INPUT_DRIFT", "reference preflight requires its unchanged native inputs")
    request = ChapterHandlerRequest(operation_id=payload["logical_key"], project_id=payload["project_id"], workspace_id=workspace_id,
        trace_id="reference-preflight", correlation_id="reference-preflight", command=payload, database_url=database_url,
        inputs=tuple(ChapterInputAsset(asset_version_id=item.asset_version_id, asset_type=item.asset_type,
            content_hash=item.content_hash, content=item.content) for item in documents))
    stage = payload["generator_operation_name"]
    _, context, _, _, provider_input = prepare_native_review(request, stage=stage)
    schema, schema_ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage=stage, request_payload={"input": provider_input})
    with AuthorityUnitOfWork(database_url) as uow:
        existing_definition = _existing_sample_definition(uow, project_id=payload["project_id"],
            idempotency_key=payload["idempotency_key"], definition_name=chapter_sample_definition_name(stage), reference_samples=True)
        definition_version = existing_definition["definition_version"] if existing_definition else CHAPTER_REFERENCE_SAMPLE_VERSION
        uow.cursor.execute("""SELECT operation.operation_id,operation.command_payload->'payload',attempt.attempt_id,operation.definition_version
            FROM authority_operation operation LEFT JOIN authority_attempt attempt USING(operation_id)
            WHERE operation.project_id=%s AND operation.idempotency_scope=%s AND operation.idempotency_key=%s
            ORDER BY attempt.attempt_number DESC LIMIT 1""",
            [payload["project_id"], CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE, payload["idempotency_key"]])
        existing = uow.cursor.fetchone()
        stored = None
        if existing:
            if (existing_definition is None or existing[3] != definition_version
                or {key: value for key, value in existing[1].items() if key != "routing_bootstrap_authorization"} != payload):
                raise KernelError("CHAPTER_SAMPLE_INPUT_DRIFT", "reference replay requires its original admitted command and definition")
            if existing[2]:
                stored = uow.repositories.capability_packs.find_attempt_snapshot(existing[2])
                if stored is None:
                    stored = uow.repositories.capability_packs.find_latest_operation_attempt_snapshot(
                        existing[0], excluding_attempt_id=existing[2])
        elif existing_definition is not None:
            raise KernelError("CHAPTER_SAMPLE_INPUT_DRIFT", "reference operation changed after its definition was read")
        operation_ref = chapter_sample_definition_name(stage) + "@" + definition_version
        workflow_ref = "chapter_reference_sampling@" + definition_version
        if stored is not None:
            snapshot = stored["snapshot"]
            if (stored["operation_id"] != existing[0] or snapshot.operation_definition_ref != operation_ref
                or snapshot.workflow_definition_ref != workflow_ref or snapshot.workflow_node_id != stage):
                raise KernelError("CHAPTER_SAMPLE_PRODUCER_DRIFT", "reference replay Pack does not match its original operation contract")
        else:
            snapshot = binder.pack_resolver.resolve_in_uow(uow, CapabilityPackResolutionRequest(
                project_id=payload["project_id"], workspace_id=workspace_id, book_id=payload["book_id"],
                workflow_definition_ref=workflow_ref,
                workflow_node_id=stage, environment=binder.pack_environment, runtime_profile=binder.pack_runtime_profile,
                release_channel=binder.pack_release_channel, release_sha=binder.routes[stage].release_sha,
                operation_definition_ref=operation_ref, pack_id=binder.capability_pack_id + ".reference_samples"))
        version = uow.repositories.capability_packs.require_version(snapshot.pack_id, snapshot.pack_version)
        artifacts = materialize_registered_pack_version(snapshot, version)
        uow.cursor.execute("""SELECT version.content,version.content_hash FROM authority_operation_output_asset output
            JOIN authority_asset_version version USING(asset_version_id) JOIN authority_asset asset ON asset.asset_id=version.asset_id
            WHERE output.operation_id=%s AND asset.project_id=%s AND asset.asset_type='capability_materialization_manifest'
              AND output.content_hash=version.content_hash""", [payload["logical_key"], payload["project_id"]])
        rows = uow.cursor.fetchall()
    producers = {}
    for content, digest in rows:
        materialization = deepcopy(content.get("contract") or {})
        selection = materialization.get("context_selection") or []
        if (authorization_hash(content) != digest or len(selection) != 1
            or selection[0].get("asset_version_id") != context.asset_version_id
            or selection[0].get("content_hash") != context.content_hash
            or materialization.get("stage") != {"review": "draft", "rereview": "revision"}[stage]):
            raise KernelError("CHAPTER_SAMPLE_PRODUCER_DRIFT", "reference sampling must retain its original approved producer artifacts and Context")
        materialization.update(stage=stage, output_schema={"ref": schema_ref, "content_hash": authorization_hash(schema), "content": schema})
        materialization["pack_artifacts"] = artifacts.to_dict(include_content=True)
        tool_payload = json.loads(snapshot.tool_policy_payload_json)
        allowed, denied = _stage_tool_permissions(tool_payload, stage)
        materialization["tool_permissions"] = {"default": str(tool_payload.get("default") or ""),
            "allowed": list(allowed), "denied": list(denied), "invoked": ["model.provider.invoke"],
            "governing_policy_ref": snapshot.tool_policy_ref, "governing_policy_hash": snapshot.tool_policy_hash}
        _, evidence = _materialize_production_codex_prompt(target_scope={"scope_kind": "chapter", "scope_id": str(payload["chapter"]),
            "project_id": payload["project_id"], "book_id": payload["book_id"]}, stage=stage, inputs=provider_input, materialization=materialization)
        producer = chapter_producer_contract_identity(evidence, materialization)
        producers[authorization_hash(producer)] = producer
    if len(producers) != 1:
        raise KernelError("CHAPTER_SAMPLE_PRODUCER_REQUIRED", "reference sampling requires one compatible native generation materialization")
    return next(iter(producers.values()))


def admit_provider_sample(
    app: Any, command: ChapterProviderSampleCommand, *, principal: Principal
) -> dict[str, Any]:
    prepared = prepare_provider_sample(app, command, principal=principal)
    if prepared["status"] != "PREPARED_NO_PROVIDER_CALL":
        raise KernelError("QUALITY_REFERENCE_REQUIRED", "complete the exact independent reference contract before sample admission")
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
    purpose = "REFERENCE_EVALUATION" if command.reference_evaluation is not None else "BENCHMARK_CHALLENGER"
    if grant["purpose"] != purpose or not grant.get("campaign"):
        raise KernelError(
            "CHAPTER_SAMPLE_CAMPAIGN_REQUIRED",
            "Chapter sampling requires a frozen campaign grant",
        )
    definitions = chapter_provider_sample_definitions(
        application_build_id=app.application_build_id, commit_sha=app.commit_sha,
        reference_samples=command.generation_sample is not None,
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
        existing_definition = _existing_sample_definition(uow, project_id=command.project_id,
            idempotency_key=command.idempotency_key, definition_name=prepared["definition_name"],
            reference_samples=command.generation_sample is not None)
        if existing_definition is None:
            if definition["definition_version"] != prepared["definition_version"]:
                raise KernelError("AUTHORITY_HANDLER_CONTRACT_STALE", "sample admission contract changed after preflight")
            uow.repositories.definitions.register(definition)
        else:
            definition = existing_definition
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
                "definition_version": definition["definition_version"],
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
        or previous.get("reference_evaluation") != payload.get("reference_evaluation")
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
