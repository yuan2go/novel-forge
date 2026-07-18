"""Bounded PostgreSQL-only orchestration for one deterministic chapter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRegistry,
    ChapterNode,
    QUALITY_GROUP_NODES,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_SLICE_DEFINITION_VERSION,
    CHAPTER_SLICE_ROOT_DEFINITION_NAME,
    CHAPTER_SLICE_ROOT_HANDLER_KEY,
    chapter_operation_definitions,
    chapter_root_operation_definition,
    chapter_definition_version,
)
from novel_forge.modules.chapter_authority.evidence import (
    build_chapter_slice_evidence_manifest,
)
from novel_forge.modules.chapter_authority.export_delivery import (
    ExportDeliveryEvidence,
    ExportDeliveryRequest,
    deliver_export,
)
from novel_forge.modules.chapter_authority.runtime import (
    ChapterExecutionResult,
    execute_chapter_handler,
)
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
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    register_saga_step,
    start_saga,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class SingleChapterRequest:
    project_id: str
    workspace_id: str
    actor_id: str
    chapter: int
    title: str
    premise: str
    trace_id: str
    correlation_id: str
    application_build_id: str
    commit_sha: str
    chapter_plan_asset_version_id: str = ""
    chapter_plan_content_hash: str = ""
    context_candidates: tuple[dict[str, Any], ...] = ()
    context_version_refs: dict[str, Any] | None = None
    context_token_budget: int = 6000
    preparation_report: dict[str, Any] | None = None
    idempotency_key: str = ""


@dataclass(frozen=True, slots=True)
class ChapterSagaAdmission:
    root_operation_id: str
    saga_id: str
    first_operation_id: str
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class ChapterSliceResult:
    root_operation_id: str
    saga_id: str
    root_status: str
    saga_status: str
    operation_ids: dict[ChapterNode, str]
    outputs: dict[ChapterNode, ChapterExecutionResult]
    export_evidence: ExportDeliveryEvidence
    evidence_manifest: dict[str, Any]


def admit_single_chapter_saga(
    database_url: str,
    *,
    request: SingleChapterRequest,
    registry: ChapterHandlerRegistry,
    permissions: frozenset[str],
) -> ChapterSagaAdmission:
    """Persist a durable root Saga and first READY node without executing a handler."""
    _validate_request(request)
    plan_input = _chapter_plan_input(request)
    definition_version = chapter_definition_version(registry.model_effects_required)
    definitions = chapter_operation_definitions(
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
        model_effects_required=registry.model_effects_required,
    )
    root_definition = chapter_root_operation_definition(
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
        model_effects_required=registry.model_effects_required,
    )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(root_definition)
        for definition in definitions:
            uow.repositories.definitions.register(definition)
        uow.commit()
    admission = AdmissionContext(
        actor_id=request.actor_id,
        permissions=permissions,
        available_handlers=registry.available_handler_keys
        | frozenset({CHAPTER_SLICE_ROOT_HANDLER_KEY}),
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
    )
    stable_root_key = request.idempotency_key or (
        f"{request.project_id}:chapter:{request.chapter}:root"
    )
    admitted_root = admit_command(
        database_url,
        _command(
            request,
            definition_name=CHAPTER_SLICE_ROOT_DEFINITION_NAME,
            idempotency_key=stable_root_key,
            input_assets=[
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in request.context_candidates
            ],
            definition_version=definition_version,
        ),
        context=admission,
    )
    root = str(admitted_root["operation_id"])
    root_status, _ = _operation_state(database_url, root, request.project_id)
    if root_status == "ADMITTED":
        _transition_root_to_executing(database_url, request, root)
    graph_context = GraphCommandContext(
        project_id=request.project_id,
        actor_id=request.actor_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
    )
    saga_id = str(
        start_saga(database_url, graph_context, root_operation_id=root)["saga_id"]
    )
    plan = ChapterNode.PLAN
    admitted_plan = admit_command(
        database_url,
        _command(
            request,
            definition_name=plan.definition_name,
            idempotency_key=f"{stable_root_key}:{plan.value}",
            input_assets=[plan_input],
            root_operation_id=root,
            parent_operation_id=root,
            causation_operation_id=root,
            definition_version=definition_version,
        ),
        context=admission,
    )
    plan_id = str(admitted_plan["operation_id"])
    register_saga_step(database_url, graph_context, saga_id, plan_id, plan.value, 1, "")
    coordinate_saga(database_url, graph_context, saga_id)
    return ChapterSagaAdmission(
        root_operation_id=root,
        saga_id=saga_id,
        first_operation_id=plan_id,
        status="ACCEPTED",
        replayed=bool(admitted_root["replayed"]),
    )


def run_single_chapter_slice(
    database_url: str,
    *,
    request: SingleChapterRequest,
    registry: ChapterHandlerRegistry,
    object_store_adapter: ExternalEffectAdapter,
    retry_once_at: ChapterNode | None = None,
    exercise_unknown_export_reconciliation: bool = False,
) -> ChapterSliceResult:
    _validate_request(request)
    definition_version = chapter_definition_version(registry.model_effects_required)
    definitions = chapter_operation_definitions(
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
        model_effects_required=registry.model_effects_required,
    )
    root_definition = chapter_root_operation_definition(
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
        model_effects_required=registry.model_effects_required,
    )
    with AuthorityUnitOfWork(database_url) as uow:
        uow.repositories.definitions.register(root_definition)
        for definition in definitions:
            uow.repositories.definitions.register(definition)
        uow.commit()
    available_handlers = registry.available_handler_keys | frozenset(
        {CHAPTER_SLICE_ROOT_HANDLER_KEY}
    )
    admission = AdmissionContext(
        actor_id=request.actor_id,
        permissions=frozenset({"chapter.authority.execute"}),
        available_handlers=available_handlers,
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
    )
    root = admit_command(
        database_url,
        _command(
            request,
            definition_name=CHAPTER_SLICE_ROOT_DEFINITION_NAME,
            idempotency_key=f"{request.project_id}:chapter:{request.chapter}:root",
            input_assets=[
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in request.context_candidates
            ],
            definition_version=definition_version,
        ),
        context=admission,
    )["operation_id"]
    _transition_root_to_executing(database_url, request, root)
    graph_context = GraphCommandContext(
        project_id=request.project_id,
        actor_id=request.actor_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
    )
    saga_id = start_saga(database_url, graph_context, root_operation_id=root)["saga_id"]

    operation_ids: dict[ChapterNode, str] = {}
    outputs: dict[ChapterNode, ChapterExecutionResult] = {}
    previous_operation_id = ""
    export_evidence: ExportDeliveryEvidence | None = None
    for ordinal, node in enumerate(ChapterNode, start=1):
        input_assets = [
            {
                "asset_version_id": outputs[source].asset_version_id,
                "content_hash": outputs[source].content_hash,
            }
            for source in _input_nodes(node)
        ]
        if node is ChapterNode.PLAN:
            input_assets.append(_chapter_plan_input(request))
        if node is ChapterNode.CONTEXT:
            input_assets.append(
                _operation_output_by_key(
                    database_url,
                    operation_ids[ChapterNode.PLAN],
                    request.project_id,
                    "chapter.production_input_manifest",
                )
            )
            input_assets.extend(
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in request.context_candidates
            )
        operation_id = admit_command(
            database_url,
            _command(
                request,
                definition_name=node.definition_name,
                idempotency_key=f"{request.project_id}:chapter:{request.chapter}:{node.value}",
                input_assets=input_assets,
                root_operation_id=root,
                parent_operation_id=root,
                causation_operation_id=previous_operation_id or root,
                definition_version=definition_version,
            ),
            context=admission,
        )["operation_id"]
        operation_ids[node] = operation_id
        register_saga_step(
            database_url,
            graph_context,
            saga_id,
            operation_id,
            node.value,
            ordinal,
            "",
        )
        if previous_operation_id:
            add_operation_dependency(
                database_url,
                graph_context,
                operation_id,
                previous_operation_id,
                "ON_SUCCESS",
            )
        ready = coordinate_saga(database_url, graph_context, saga_id)
        if operation_id not in ready["ready"]:
            raise KernelError(
                "CHAPTER_SAGA_READINESS_INVALID",
                f"Saga did not make {node.value} ready after its dependencies completed",
            )
        if retry_once_at is node:
            _run_failed_attempt(database_url, request, operation_id, node)
            recovered = coordinate_saga(database_url, graph_context, saga_id)
            if recovered["status"] != "FORWARD_RECOVERY":
                raise KernelError(
                    "CHAPTER_FORWARD_RECOVERY_FAILED",
                    f"Saga did not recover retryable {node.value} failure",
                )
        output, delivery = _run_successful_attempt(
            database_url,
            request=request,
            operation_id=operation_id,
            node=node,
            registry=registry,
            object_store_adapter=object_store_adapter,
            exercise_unknown_export_reconciliation=exercise_unknown_export_reconciliation,
        )
        outputs[node] = output
        if delivery is not None:
            export_evidence = delivery
        previous_operation_id = operation_id

    final_saga = coordinate_saga(database_url, graph_context, saga_id)
    root_status, _root_version = _operation_state(database_url, root, request.project_id)
    if final_saga["status"] != "SUCCEEDED" or root_status != "SUCCEEDED":
        raise KernelError(
            "CHAPTER_SLICE_INCOMPLETE",
            "all chapter nodes completed but the root Saga did not succeed",
        )
    if export_evidence is None:
        raise KernelError("CHAPTER_EXPORT_EVIDENCE_MISSING", "Export delivery did not run")
    manifest = build_chapter_slice_evidence_manifest(
        database_url,
        project_id=request.project_id,
        root_operation_id=root,
    )
    return ChapterSliceResult(
        root_operation_id=root,
        saga_id=saga_id,
        root_status=root_status,
        saga_status=final_saga["status"],
        operation_ids=operation_ids,
        outputs=outputs,
        export_evidence=export_evidence,
        evidence_manifest=manifest,
    )


def _run_failed_attempt(
    database_url: str,
    request: SingleChapterRequest,
    operation_id: str,
    node: ChapterNode,
) -> None:
    worker = _start_attempt(database_url, request, operation_id, f"{node.value}-crash-worker")
    status, version = _operation_state(database_url, operation_id, request.project_id)
    submit_attempt_result(
        database_url,
        _result_command(worker, expected_status=status, expected_version=version),
        outcome="retryable_failure",
        result={"error_code": "INJECTED_RETRYABLE_CRASH", "before_output": True},
    )


def _run_successful_attempt(
    database_url: str,
    *,
    request: SingleChapterRequest,
    operation_id: str,
    node: ChapterNode,
    registry: ChapterHandlerRegistry,
    object_store_adapter: ExternalEffectAdapter,
    exercise_unknown_export_reconciliation: bool,
) -> tuple[ChapterExecutionResult, ExportDeliveryEvidence | None]:
    worker = _start_attempt(database_url, request, operation_id, f"{node.value}-worker")
    output = execute_chapter_handler(
        database_url,
        command=worker,
        node=node,
        registry=registry,
    )
    delivery = None
    if node is ChapterNode.EXPORT:
        delivery = deliver_export(
            database_url,
            request=ExportDeliveryRequest(
                operation_id=operation_id,
                asset_version_id=output.asset_version_id,
                project_id=request.project_id,
                actor_id=request.actor_id,
                chapter=request.chapter,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            ),
            adapter=object_store_adapter,
            exercise_unknown_reconciliation=exercise_unknown_export_reconciliation,
        )
    status, version = _operation_state(database_url, operation_id, request.project_id)
    submit_attempt_result(
        database_url,
        _result_command(worker, expected_status=status, expected_version=version),
        outcome="success",
        result={
            "asset_version_id": output.asset_version_id,
            "content_hash": output.content_hash,
        },
    )
    completed_status, _ = _operation_state(database_url, operation_id, request.project_id)
    if completed_status != "SUCCEEDED":
        raise KernelError(
            "CHAPTER_NODE_COMPLETION_FAILED",
            f"{node.value} Completion Contract remained {completed_status}",
        )
    return output, delivery


def _start_attempt(
    database_url: str,
    request: SingleChapterRequest,
    operation_id: str,
    worker_id: str,
) -> WorkerLeaseCommand:
    attempt_id = create_attempt(
        database_url,
        operation_id=operation_id,
        project_id=request.project_id,
        max_attempts=2,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
    )["attempt_id"]
    if attempt_id is None:
        raise KernelError("CHAPTER_ATTEMPT_EXHAUSTED", "chapter Attempt policy is exhausted")
    queue_attempt(
        database_url,
        attempt_id=attempt_id,
        project_id=request.project_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
    )
    lease = acquire_attempt_lease(
        database_url,
        attempt_id=attempt_id,
        project_id=request.project_id,
        worker_id=worker_id,
        lease_seconds=30,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
    )
    worker = WorkerLeaseCommand(
        attempt_id=attempt_id,
        project_id=request.project_id,
        worker_id=worker_id,
        fencing_token=lease["fencing_token"],
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
        causation_id=operation_id,
    )
    start_attempt(database_url, worker)
    return worker


def _operation_output_by_key(
    database_url: str,
    operation_id: str,
    project_id: str,
    output_key: str,
) -> dict[str, str]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT binding.asset_version_id, binding.content_hash
            FROM authority_operation_output_asset AS binding
            JOIN authority_operation AS operation
              ON operation.operation_id=binding.operation_id
            WHERE binding.operation_id=%s AND operation.project_id=%s
              AND binding.output_key=%s
            """,
            [operation_id, project_id, output_key],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("CHAPTER_INPUT_OUTPUT_MISSING", f"missing output {output_key}")
    return {"asset_version_id": str(row[0]), "content_hash": str(row[1])}


def _command(
    request: SingleChapterRequest,
    *,
    definition_name: str,
    idempotency_key: str,
    input_assets: list[dict[str, str]],
    root_operation_id: str | None = None,
    parent_operation_id: str | None = None,
    causation_operation_id: str | None = None,
    definition_version: str = CHAPTER_SLICE_DEFINITION_VERSION,
) -> dict[str, Any]:
    return {
        "definition_name": definition_name,
        "definition_version": definition_version,
        "project_id": request.project_id,
        "workspace_id": request.workspace_id,
        "actor_id": request.actor_id,
        "idempotency_scope": "project:chapter-slice",
        "idempotency_key": idempotency_key,
        "trace_id": request.trace_id,
        "span_id": str(uuid4()),
        "correlation_id": request.correlation_id,
        "causation_id": causation_operation_id or "",
        "input": {
            "chapter": request.chapter,
            "title": request.title,
            "premise": request.premise,
            "chapter_plan_asset_version_id": _chapter_plan_input(request)["asset_version_id"],
            "chapter_plan_content_hash": _chapter_plan_input(request)["content_hash"],
            "context_candidates": [dict(item) for item in request.context_candidates],
            "context_version_refs": dict(request.context_version_refs or {}),
            "context_token_budget": request.context_token_budget,
            "preparation_report": dict(request.preparation_report or {}),
            "chapter_idempotency_key": request.idempotency_key,
        },
        "input_assets": input_assets,
        "root_operation_id": root_operation_id,
        "parent_operation_id": parent_operation_id,
        "causation_operation_id": causation_operation_id,
    }


def _transition_root_to_executing(
    database_url: str,
    request: SingleChapterRequest,
    root_operation_id: str,
) -> None:
    for version, current, target in (
        (0, "ADMITTED", "READY"),
        (1, "READY", "EXECUTING"),
    ):
        transition_operation(
            database_url,
            OperationTransitionCommand(
                operation_id=root_operation_id,
                project_id=request.project_id,
                expected_version=version,
                expected_status=current,
                target_status=target,
                actor_id=request.actor_id,
                reason="start PostgreSQL-only chapter Saga",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                causation_id="",
            ),
        )


def _result_command(
    worker: WorkerLeaseCommand,
    *,
    expected_status: str,
    expected_version: int,
) -> WorkerResultCommand:
    return WorkerResultCommand(
        attempt_id=worker.attempt_id,
        project_id=worker.project_id,
        worker_id=worker.worker_id,
        fencing_token=worker.fencing_token,
        trace_id=worker.trace_id,
        correlation_id=worker.correlation_id,
        causation_id=worker.causation_id,
        expected_operation_status=expected_status,
        expected_operation_version=expected_version,
    )


def _operation_state(
    database_url: str,
    operation_id: str,
    project_id: str,
) -> tuple[str, int]:
    with AuthorityUnitOfWork(database_url) as uow:
        state = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
    return str(state["status"]), int(state["version"])


def _input_nodes(node: ChapterNode) -> tuple[ChapterNode, ...]:
    if node in QUALITY_GROUP_NODES:
        return (
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.CONTEXT,
        )
    return {
        ChapterNode.PLAN: (),
        ChapterNode.CONTEXT: (ChapterNode.PLAN,),
        ChapterNode.DRAFT: (ChapterNode.PLAN, ChapterNode.CONTEXT),
        ChapterNode.REVIEW: (ChapterNode.DRAFT, ChapterNode.CONTEXT),
        ChapterNode.REVISION: (ChapterNode.DRAFT, ChapterNode.REVIEW, ChapterNode.CONTEXT),
        ChapterNode.REREVIEW: (
            ChapterNode.DRAFT,
            ChapterNode.REVIEW,
            ChapterNode.REVISION,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.CANON_EXTRACTION: (
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.CANON_PROPOSAL: (ChapterNode.CANON_EXTRACTION,),
        ChapterNode.CANON: (
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.CANON_EXTRACTION,
            ChapterNode.CANON_PROPOSAL,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.QUALITY: (
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.CONTEXT,
            *QUALITY_GROUP_NODES,
        ),
        ChapterNode.PUBLISH_GATE: (
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.QUALITY,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.EXPORT: (ChapterNode.REVISION, ChapterNode.PUBLISH_GATE),
        ChapterNode.FINAL_RELEASE_GATE: (
            ChapterNode.EXPORT,
            ChapterNode.PUBLISH_GATE,
            ChapterNode.QUALITY,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.CONTEXT,
        ),
    }[node]


def _validate_request(request: SingleChapterRequest) -> None:
    required = (
        request.project_id,
        request.workspace_id,
        request.actor_id,
        request.title,
        request.premise,
        request.trace_id,
        request.correlation_id,
        request.application_build_id,
    )
    if (
        any(not value for value in required)
        or request.chapter <= 0
        or len(request.commit_sha) != 40
        or request.context_token_budget <= 0
    ):
        raise KernelError("CHAPTER_SLICE_REQUEST_INVALID", "single-chapter request is incomplete")
    _chapter_plan_input(request)


def _chapter_plan_input(request: SingleChapterRequest) -> dict[str, str]:
    candidates = [
        item for item in request.context_candidates if item.get("asset_type") == "chapter_plan"
    ]
    if len(candidates) != 1:
        raise KernelError(
            "CHAPTER_PLAN_AUTHORITY_INPUT_REQUIRED",
            f"exactly one frozen ChapterPlan AssetVersion is required, found {len(candidates)}",
        )
    candidate = candidates[0]
    asset_version_id = str(request.chapter_plan_asset_version_id or candidate.get("asset_version_id") or "")
    content_hash = str(request.chapter_plan_content_hash or candidate.get("content_hash") or "")
    if (
        not asset_version_id
        or not content_hash
        or asset_version_id != str(candidate.get("asset_version_id") or "")
        or content_hash != str(candidate.get("content_hash") or "")
    ):
        raise KernelError(
            "CHAPTER_PLAN_AUTHORITY_IDENTITY_INVALID",
            "ChapterPlan command identity must match its governed candidate",
        )
    return {"asset_version_id": asset_version_id, "content_hash": content_hash}
