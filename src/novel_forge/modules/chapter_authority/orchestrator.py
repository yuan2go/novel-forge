from __future__ import annotations
from dataclasses import dataclass, replace
import json
from typing import Any
from uuid import uuid4
from novel_forge.modules.chapter_authority.contracts import (
    QUALITY_GROUP_NODES,
    ChapterHandlerRegistry,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_SLICE_DEFINITION_VERSION,
    CHAPTER_SLICE_ROOT_DEFINITION_NAME,
    CHAPTER_SLICE_ROOT_HANDLER_KEY,
    chapter_definition_version,
    chapter_operation_definitions,
    chapter_root_operation_definition,
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
from novel_forge.modules.context_builder.production_retrieval import (
    build_retrieval_query_plan,
    discover_accepted_retrieval_candidates,
)


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
    book_id: str = ""
    chapter_plan_asset_version_id: str = ""
    chapter_plan_content_hash: str = ""
    context_candidates: tuple[dict[str, Any], ...] = ()
    context_version_refs: dict[str, Any] | None = None
    context_token_budget: int = 6000
    preparation_report: dict[str, Any] | None = None
    accepted_prose_snapshot: dict[str, Any] | None = None
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


def recover_single_chapter_admission(
    database_url: str, *, request: SingleChapterRequest,
) -> ChapterSagaAdmission | None:
    request = _bind_context_candidate_scope(request)
    _validate_request(request)
    if not request.idempotency_key:
        raise KernelError("CHAPTER_ADMISSION_RECOVERY_KEY_REQUIRED", "Recovery requires the frozen Chapter key")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT to_jsonb(root),to_jsonb(saga),to_jsonb(step),to_jsonb(plan)
            FROM authority_operation root
            LEFT JOIN authority_saga saga ON saga.root_operation_id=root.operation_id
            LEFT JOIN authority_saga_step step ON step.saga_id=saga.saga_id AND step.step_key=%s
            LEFT JOIN authority_operation plan ON plan.operation_id=step.operation_id
            WHERE root.project_id=%s AND root.idempotency_scope='project:chapter-slice'
              AND root.idempotency_key=%s""",
            [ChapterNode.PLAN.value, request.project_id, request.idempotency_key],
        )
        row = uow.cursor.fetchone()
    if row is None:
        return None
    root, saga, step, plan = row
    if (root["definition_name"] != CHAPTER_SLICE_ROOT_DEFINITION_NAME
        or root["workspace_id"] != request.workspace_id
        or root["root_operation_id"] != root["operation_id"]
        or root.get("parent_operation_id") or root.get("causation_operation_id")):
        raise KernelError("CHAPTER_ADMISSION_RECOVERY_SCOPE_DRIFT", "Frozen Chapter root belongs to another request scope")
    if not saga or not step or not plan or root["status"] == "ADMITTED":
        raise KernelError("CHAPTER_ADMISSION_REQUIRES_RECOVERY", "Existing Chapter admission has an incomplete native saga or PLAN step")
    root_id, saga_id = root["operation_id"], saga["saga_id"]
    if (saga["project_id"] != request.project_id or root.get("saga_id") != saga_id
        or saga["root_operation_id"] != root_id or step["ordinal"] != 1
        or plan["project_id"] != request.project_id or plan["workspace_id"] != request.workspace_id
        or plan["definition_name"] != ChapterNode.PLAN.definition_name
        or plan["root_operation_id"] != root_id or plan["parent_operation_id"] != root_id
        or plan.get("causation_operation_id") != root_id or plan.get("saga_id") != saga_id
        or plan.get("step_key") != ChapterNode.PLAN.value or plan["actor_id"] != root["actor_id"]
        or plan["idempotency_scope"] != "project:chapter-slice"
        or plan["idempotency_key"] != request.idempotency_key + ":" + ChapterNode.PLAN.value):
        raise KernelError("CHAPTER_ADMISSION_RECOVERY_SCOPE_DRIFT", "Frozen Chapter saga and PLAN lineage disagree")
    for operation, parent, refs in (
        (root, None, [{"asset_version_id": str(item["asset_version_id"]), "content_hash": str(item["content_hash"])} for item in request.context_candidates]),
        (plan, root_id, [_chapter_plan_input(request)]),
    ):
        expected = _command(request, definition_name=operation["definition_name"],
            definition_version=operation["definition_version"], idempotency_key=operation["idempotency_key"],
            input_assets=refs, root_operation_id=parent, parent_operation_id=parent, causation_operation_id=parent)
        actual_refs = operation.get("input_asset_snapshot") or []
        if (operation["command_payload"] != json.loads(json.dumps(expected["input"]))
            or [(item.get("asset_version_id"), item.get("content_hash")) for item in actual_refs]
                != [(item["asset_version_id"], item["content_hash"]) for item in refs]
            or any(item.get("project_id", request.project_id) != request.project_id for item in actual_refs)):
            raise KernelError("CHAPTER_ADMISSION_RECOVERY_INPUT_DRIFT", "Recovery must match the complete frozen Chapter payload and input hashes")
    return ChapterSagaAdmission(root_id, saga_id, plan["operation_id"], "ACCEPTED", True)


def admit_single_chapter_saga(
    database_url: str,
    *,
    request: SingleChapterRequest,
    registry: ChapterHandlerRegistry,
    permissions: frozenset[str],
) -> ChapterSagaAdmission:
    request = _bind_context_candidate_scope(request)
    _validate_request(request)
    plan_input = _chapter_plan_input(request)
    definition_version = chapter_definition_version(registry.model_effects_required)
    definitions = chapter_operation_definitions(
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
        model_effects_required=registry.model_effects_required,
        semantic_retrieval_available=registry.semantic_retrieval_available,
        author_input=bool((request.preparation_report or {}).get("author_draft_adoption")),
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
    request = _bind_context_candidate_scope(request)
    _validate_request(request)
    definition_version = chapter_definition_version(registry.model_effects_required)
    definitions = chapter_operation_definitions(
        application_build_id=request.application_build_id,
        commit_sha=request.commit_sha,
        model_effects_required=registry.model_effects_required,
        author_input=bool((request.preparation_report or {}).get("author_draft_adoption")),
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
    if (request.preparation_report or {}).get("author_book_replacement"):
        from novel_forge.modules.book_authority.author_revision import (
            require_author_replacement_dispatch,
        )

        require_author_replacement_dispatch(
            database_url,
            command_payload={
                "book_id": request.book_id,
                "chapter": request.chapter,
                "preparation_report": dict(request.preparation_report or {}),
            },
            root_operation_id=root,
        )
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
            (
                _operation_output_by_key(
                    database_url,
                    operation_ids[ChapterNode.BEST_CANDIDATE],
                    request.project_id,
                    "chapter.best_candidate.selected_review",
                )
                if source is ChapterNode.REREVIEW
                and node is not ChapterNode.BEST_CANDIDATE
                else {
                    "asset_version_id": outputs[source].asset_version_id,
                    "content_hash": outputs[source].content_hash,
                }
            )
            for source in _input_nodes(node)
        ]
        if node is ChapterNode.PLAN:
            input_assets.append(_chapter_plan_input(request))
        input_overrides: dict[str, Any] = {}
        if node is ChapterNode.RETRIEVAL:
            extra_inputs, snapshot = _retrieval_admission_snapshot(
                database_url,
                request=request,
                plan_asset_version_id=outputs[ChapterNode.PLAN].asset_version_id,
                intent_asset_version_id=outputs[
                    ChapterNode.EXECUTION_INTENT
                ].asset_version_id,
                memo_asset_version_id=outputs[ChapterNode.MEMO].asset_version_id,
                semantic_provider_bound=registry.semantic_retrieval_available,
            )
            input_assets.extend(extra_inputs)
            input_overrides["retrieval_snapshot"] = snapshot
        if node in {ChapterNode.EXECUTION_INTENT, ChapterNode.CONTEXT}:
            if node is ChapterNode.CONTEXT:
                input_assets.append(
                    _operation_output_by_key(
                        database_url,
                        operation_ids[ChapterNode.PLAN],
                        request.project_id,
                        "chapter.production_input_manifest",
                    )
                )
            candidates = request.context_candidates
            if node is ChapterNode.EXECUTION_INTENT:
                candidates = tuple(
                    item
                    for item in candidates
                    if str(item.get("asset_type") or "")
                    in (
                        {"story_state_snapshot", "canon_snapshot", "style_policy"}
                        if definition_version in {"3.6.0", "3.7.0", "3.8.0"}
                        else {"story_state_snapshot", "canon_snapshot"}
                    )
                )
            else:
                candidates = tuple(
                    item
                    for item in candidates
                    if str(item.get("asset_type") or "") != "chapter_plan"
                )
                retrieval = _asset_content(
                    database_url,
                    project_id=request.project_id,
                    asset_version_id=outputs[ChapterNode.RETRIEVAL].asset_version_id,
                )
                input_assets.extend(
                    {
                        "asset_version_id": str(item["asset_version_id"]),
                        "content_hash": str(item["content_hash"]),
                    }
                    for item in retrieval.get("selected_source_asset_versions", ())
                )
            input_assets.extend(
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in candidates
            )
        if node is ChapterNode.QUALITY:
            input_assets.extend(
                _measurement_evidence_inputs(
                    database_url,
                    project_id=request.project_id,
                    root_operation_id=str(root),
                    context_bundle_asset_version_id=outputs[
                        ChapterNode.CONTEXT
                    ].asset_version_id,
                )
            )
        input_assets = list(
            {
                str(item["asset_version_id"]): dict(item) for item in input_assets
            }.values()
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
                input_overrides=input_overrides,
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
    root_status, _root_version = _operation_state(
        database_url, root, request.project_id
    )
    if final_saga["status"] != "SUCCEEDED" or root_status != "SUCCEEDED":
        raise KernelError(
            "CHAPTER_SLICE_INCOMPLETE",
            "all chapter nodes completed but the root Saga did not succeed",
        )
    if export_evidence is None:
        raise KernelError(
            "CHAPTER_EXPORT_EVIDENCE_MISSING", "Export delivery did not run"
        )
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
    worker = _start_attempt(
        database_url, request, operation_id, f"{node.value}-crash-worker"
    )
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
        author_input=bool((request.preparation_report or {}).get("author_draft_adoption")),
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
    completed_status, _ = _operation_state(
        database_url, operation_id, request.project_id
    )
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
        raise KernelError(
            "CHAPTER_ATTEMPT_EXHAUSTED", "chapter Attempt policy is exhausted"
        )
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
        raise KernelError(
            "CHAPTER_INPUT_OUTPUT_MISSING", f"missing output {output_key}"
        )
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
    input_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if definition_name == ChapterNode.DRAFT.definition_name and (request.preparation_report or {}).get("author_draft_adoption"):
        from .definitions import CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION, CHAPTER_LEGACY_AUTHOR_INPUT_DEFINITION_VERSION, CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS
        definition_version = (definition_version + "-author-input.v2" if definition_version in {"3.6.0", "3.7.0"} else CHAPTER_LEGACY_AUTHOR_INPUT_DEFINITION_VERSION if definition_version in CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS else CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION)
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
            "book_id": request.book_id,
            "title": request.title,
            "premise": request.premise,
            "chapter_plan_asset_version_id": _chapter_plan_input(request)[
                "asset_version_id"
            ],
            "chapter_plan_content_hash": _chapter_plan_input(request)["content_hash"],
            "context_candidates": [dict(item) for item in request.context_candidates],
            "context_version_refs": dict(request.context_version_refs or {}),
            "context_token_budget": request.context_token_budget,
            "preparation_report": {**dict(request.preparation_report or {}),
                **({"accepted_prose_snapshot": request.accepted_prose_snapshot} if request.accepted_prose_snapshot is not None else {})},
            "chapter_idempotency_key": request.idempotency_key,
            "chapter_root_operation_id": root_operation_id or "",
            **dict(input_overrides or {}),
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
        state = uow.repositories.attempt_runtime.operation_state(
            operation_id, project_id
        )
    return str(state["status"]), int(state["version"])


def _input_nodes(node: ChapterNode) -> tuple[ChapterNode, ...]:
    if node in QUALITY_GROUP_NODES:
        return (
            ChapterNode.PLAN,
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.CONTEXT,
        )
    return {
        ChapterNode.PLAN: (),
        ChapterNode.EXECUTION_INTENT: (ChapterNode.PLAN,),
        ChapterNode.MEMO: (
            ChapterNode.PLAN,
            ChapterNode.EXECUTION_INTENT,
        ),
        ChapterNode.RETRIEVAL: (
            ChapterNode.PLAN,
            ChapterNode.EXECUTION_INTENT,
            ChapterNode.MEMO,
        ),
        ChapterNode.CONTEXT: (
            ChapterNode.PLAN,
            ChapterNode.EXECUTION_INTENT,
            ChapterNode.MEMO,
            ChapterNode.RETRIEVAL,
        ),
        ChapterNode.DRAFT: (
            ChapterNode.PLAN,
            ChapterNode.EXECUTION_INTENT,
            ChapterNode.MEMO,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.REVIEW: (ChapterNode.DRAFT, ChapterNode.CONTEXT),
        ChapterNode.REVISION: (
            ChapterNode.DRAFT,
            ChapterNode.REVIEW,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.REREVIEW: (
            ChapterNode.DRAFT,
            ChapterNode.REVIEW,
            ChapterNode.REVISION,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.BEST_CANDIDATE: (
            ChapterNode.DRAFT,
            ChapterNode.REVIEW,
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
        ),
        ChapterNode.CANON_EXTRACTION: (
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.REREVIEW,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.CANON_PROPOSAL: (ChapterNode.CANON_EXTRACTION, ChapterNode.BEST_CANDIDATE, ChapterNode.CONTEXT),
        ChapterNode.CANON: (
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.REREVIEW,
            ChapterNode.CANON_EXTRACTION,
            ChapterNode.CANON_PROPOSAL,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.QUALITY: (
            ChapterNode.PLAN,
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.CONTEXT,
            *QUALITY_GROUP_NODES,
        ),
        ChapterNode.PUBLISH_GATE: (
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.QUALITY,
            ChapterNode.CONTEXT,
        ),
        ChapterNode.EXPORT: (ChapterNode.BEST_CANDIDATE, ChapterNode.PUBLISH_GATE),
        ChapterNode.FINAL_RELEASE_GATE: (
            ChapterNode.EXPORT,
            ChapterNode.PUBLISH_GATE,
            ChapterNode.QUALITY,
            ChapterNode.REREVIEW,
            ChapterNode.CANON,
            ChapterNode.CONTEXT,
        ),
    }[node]


def _retrieval_admission_snapshot(
    database_url: str,
    *,
    request: SingleChapterRequest,
    plan_asset_version_id: str,
    intent_asset_version_id: str,
    memo_asset_version_id: str,
    semantic_provider_bound: bool = False,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    plan = _asset_content(
        database_url,
        project_id=request.project_id,
        asset_version_id=plan_asset_version_id,
    )
    intent = _asset_content(
        database_url,
        project_id=request.project_id,
        asset_version_id=intent_asset_version_id,
    )
    memo = _asset_content(
        database_url,
        project_id=request.project_id,
        asset_version_id=memo_asset_version_id,
    )
    semantic_policy = str(
        dict(request.context_version_refs or {}).get("semantic_retrieval_policy")
        or "FALLBACK_ALLOWED"
    )
    dependencies = None
    if str(dict(dict(request.preparation_report or {}).get("stage_context_profile_versions") or {}).get("draft") or "") == "draft-context-profile-v4":
        from novel_forge.modules.context_builder.production_retrieval import build_task_dependency_refs

        from .context_compression_provider import compression_boundary_identity

        current_candidates = [
            dict(item) for item in request.context_candidates
            if item.get("asset_type") in {"canon_snapshot", "story_state_snapshot", "creative_foundation", "world_bible", "character_cards", "character_cast"}
        ]
        with AuthorityUnitOfWork(database_url) as uow:
            for candidate in current_candidates:
                uow.cursor.execute(
                    """SELECT version.content_hash, version.lifecycle,
                              version.eligibility, version.governance
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s""",
                    [candidate["asset_version_id"], request.project_id],
                )
                row = uow.cursor.fetchone()
                if (row is None or str(row[0]) != str(candidate.get("content_hash") or "")
                    or str(row[1]) not in {"ACTIVE", "SUPERSEDED"}
                    or str(row[2]) != "ELIGIBLE" or str(row[3]) != "CLEAR"
                    or candidate.get("project_id") != request.project_id
                    or candidate.get("book_id") != request.book_id
                    or compression_boundary_identity(candidate.get("accepted_boundary") or {}, strict=True) != compression_boundary_identity(intent.get("accepted_boundary") or {}, strict=True)):
                    raise KernelError("RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "task dependency facts require eligible frozen sources at the task boundary")
                candidate["accepted_boundary"] = compression_boundary_identity(candidate["accepted_boundary"], strict=True)
        dependencies = build_task_dependency_refs(plan=plan, current_candidates=current_candidates)
    query_plan = build_retrieval_query_plan(
        intent=intent,
        memo=memo,
        semantic_policy=semantic_policy,
        task_dependency_refs=dependencies,
    )
    if query_plan["semantic_policy"] == "REQUIRED" and not semantic_provider_bound:
        raise KernelError(
            "RETRIEVAL_QUERY_EMBEDDING_BINDING_REQUIRED",
            "semantic-required retrieval has no governed Provider binding",
        )
    discovery = discover_accepted_retrieval_candidates(
        database_url,
        project_id=request.project_id,
        book_id=str(plan.get("book_id") or f"book:{request.project_id}"),
        query_plan=query_plan,
    )
    return list(discovery.candidate_inputs), {
        "query_plan": discovery.query_plan,
        "documents": [dict(item) for item in discovery.documents],
        "rejected_documents": [dict(item) for item in discovery.rejected_documents],
        "semantic_status": dict(discovery.semantic_status),
    }


def _asset_content(
    database_url: str, *, project_id: str, asset_version_id: str
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT version.content
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE version.asset_version_id=%s AND asset.project_id=%s
            """,
            [asset_version_id, project_id],
        )
        row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "CHAPTER_FROZEN_ASSET_MISSING",
            "Chapter admission source AssetVersion is missing",
        )
    return dict(row[0] or {})


def _measurement_evidence_inputs(
    database_url: str,
    *,
    project_id: str,
    root_operation_id: str,
    context_bundle_asset_version_id: str,
) -> list[dict[str, str]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT binding.asset_version_id, binding.content_hash
            FROM authority_operation AS operation
            JOIN authority_operation_output_asset AS binding
              ON binding.operation_id=operation.operation_id
            JOIN authority_asset AS asset ON asset.asset_id=binding.asset_id
            WHERE operation.project_id=%s
              AND operation.root_operation_id=%s
              AND operation.status='SUCCEEDED'
              AND asset.asset_type IN ('model_call_log','cost_ledger')
              AND (EXISTS (
                SELECT 1
                FROM jsonb_array_elements(operation.input_asset_snapshot) AS input(value)
                WHERE input.value->>'asset_version_id'=%s
              ) OR EXISTS (
                SELECT 1 FROM authority_operation_output_asset AS source
                JOIN authority_asset_version AS context ON context.asset_version_id=%s
                WHERE source.operation_id=operation.operation_id
                  AND context.content->'selected_asset_version_ids' ? source.asset_version_id
              ))
            ORDER BY operation.created_at, asset.asset_type, binding.output_key
            """,
            [project_id, root_operation_id, context_bundle_asset_version_id, context_bundle_asset_version_id],
        )
        return [
            {"asset_version_id": str(row[0]), "content_hash": str(row[1])}
            for row in uow.cursor.fetchall()
        ]


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
        raise KernelError(
            "CHAPTER_SLICE_REQUEST_INVALID", "single-chapter request is incomplete"
        )
    _chapter_plan_input(request)


def _bind_context_candidate_scope(request: SingleChapterRequest) -> SingleChapterRequest:
    declared_books = {
        str(item.get("book_id") or "").strip()
        for item in request.context_candidates
        if str(item.get("book_id") or "").strip()
    }
    if request.book_id.strip():
        declared_books.add(request.book_id.strip())
    if len(declared_books) > 1:
        raise KernelError(
            "CHAPTER_CONTEXT_BOOK_CONFLICT",
            "Chapter Context candidates disagree on their Book scope",
        )
    book_id = next(iter(declared_books), f"book:{request.project_id}")
    expected_chapter = max(0, request.chapter - 1)
    declared_boundaries = {
        json.dumps(
            dict(item.get("accepted_boundary") or {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in request.context_candidates
        if dict(item.get("accepted_boundary") or {})
    }
    if len(declared_boundaries) > 1:
        raise KernelError(
            "CHAPTER_CONTEXT_BOUNDARY_CONFLICT",
            "Chapter Context candidates disagree on their accepted boundary",
        )
    refs = dict(request.context_version_refs or {})
    boundary = (
        json.loads(next(iter(declared_boundaries)))
        if declared_boundaries
        else {
            "accepted_through_chapter": expected_chapter,
            "story_state_snapshot_version": refs.get(
                "story_state_snapshot_version",
                refs.get("story_state_snapshot_versions", ""),
            ),
            "canon_snapshot_version": refs.get("canon_snapshot_version", ""),
        }
    )
    accepted = boundary.get("accepted_through_chapter")
    if (
        not isinstance(accepted, int)
        or isinstance(accepted, bool)
        or accepted != expected_chapter
    ):
        raise KernelError(
            "CHAPTER_CONTEXT_BOUNDARY_INVALID",
            "Chapter Context accepted boundary differs from the requested chapter",
        )
    for key in ("story_state_snapshot_version", "canon_snapshot_version"):
        expected = refs.get(
            key,
            refs.get("story_state_snapshot_versions", "")
            if key == "story_state_snapshot_version"
            else "",
        )
        if expected and boundary.get(key) != expected:
            raise KernelError(
                "CHAPTER_CONTEXT_BOUNDARY_INVALID",
                "Chapter Context boundary differs from its frozen version refs",
            )
    candidates = tuple(
        {
            **dict(item),
            "book_id": book_id,
            "accepted_boundary": dict(boundary),
        }
        for item in request.context_candidates
    )
    return replace(request, book_id=book_id, context_candidates=candidates)


def _chapter_plan_input(request: SingleChapterRequest) -> dict[str, str]:
    candidates = [
        item
        for item in request.context_candidates
        if item.get("asset_type") == "chapter_plan"
    ]
    if len(candidates) != 1:
        raise KernelError(
            "CHAPTER_PLAN_AUTHORITY_INPUT_REQUIRED",
            f"exactly one frozen ChapterPlan AssetVersion is required, found {len(candidates)}",
        )
    candidate = candidates[0]
    asset_version_id = str(
        request.chapter_plan_asset_version_id or candidate.get("asset_version_id") or ""
    )
    content_hash = str(
        request.chapter_plan_content_hash or candidate.get("content_hash") or ""
    )
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
