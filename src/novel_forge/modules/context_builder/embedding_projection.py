from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
    execute_authority_handler,
)
from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
)
from novel_forge.modules.chapter_authority.model_effects import ChapterModelPort
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    checkpoint_attempt_for_external_reconciliation,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.cancellation import (
    acknowledge_worker_cancellation,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    EffectRecoveryDisposition,
    classify_external_effect_recovery,
    reconcile_external_effect,
    resume_operation_from_completed_effect,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    coordinate_saga,
    register_saga_step,
    start_saga,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)
from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction
from novel_forge.modules.context_builder.embedding_contracts import (
    EMBEDDING_DEFINITION_NAME,
    EMBEDDING_DEFINITION_VERSION,
    EMBEDDING_HANDLER_KEY,
    EMBEDDING_PROJECTION_VERSION,
    embedding_projection_operation_definition,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


EMBEDDING_PROVIDER_TOKEN_CEILING = 32_768


@dataclass(frozen=True, slots=True)
class EmbeddingProjectionTick:
    operation_id: str
    retrieval_document_id: str
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _EmbeddingHandler:
    provider: ChapterModelPort

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        if len(request.inputs) != 1:
            raise KernelError(
                "RETRIEVAL_EMBEDDING_SOURCE_INVALID",
                "embedding projection requires one frozen accepted source",
            )
        payload = dict(request.command.get("payload") or {})
        source = request.inputs[0]
        if (
            payload.get("source_asset_version_id") != source.asset_version_id
            or payload.get("source_content_hash") != source.content_hash
        ):
            raise KernelError(
                "RETRIEVAL_EMBEDDING_SOURCE_MISMATCH",
                "embedding command source differs from frozen AssetVersion",
            )
        chapter_request = ChapterHandlerRequest(
            operation_id=request.operation_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            command={
                **request.command,
                "payload": {
                    **payload,
                    "chapter_number": int(payload.get("accepted_from_chapter") or 0),
                    "context_token_budget": max(
                        int(payload.get("token_budget") or 0),
                        EMBEDDING_PROVIDER_TOKEN_CEILING,
                    ),
                },
            },
            inputs=(
                ChapterInputAsset(
                    asset_version_id=source.asset_version_id,
                    asset_type=source.asset_type,
                    content_hash=source.content_hash,
                    content=source.content,
                    blobs=source.blobs,
                ),
            ),
            attempt_id=request.attempt_id,
            fencing_token=request.fencing_token,
            worker_id=request.worker_id,
        )
        provider_result = self.provider.invoke(
            chapter_request,
            stage="retrieval",
            payload={
                "texts": [str(payload.get("content_text") or "")],
                "purpose": "accepted_document_embedding_projection",
                "query_plan_fingerprint": str(
                    payload.get("retrieval_document_projection_hash") or ""
                ),
            },
        )
        vectors = provider_result.output.get("vectors")
        dimensions = int(provider_result.output.get("embedding_dimensions") or 0)
        if (
            not isinstance(vectors, list)
            or len(vectors) != 1
            or not isinstance(vectors[0], list)
            or len(vectors[0]) != dimensions
        ):
            raise KernelError(
                "RETRIEVAL_DOCUMENT_EMBEDDING_INVALID",
                "document embedding Provider returned an invalid batch",
            )
        return AuthorityHandlerOutput(
            asset_type="retrieval_embedding_candidate",
            output_key="retrieval.embedding.candidate",
            role="derived_projection_candidate",
            content={
                "type": "RetrievalEmbeddingCandidate",
                "contract_version": "retrieval-embedding-candidate-v1",
                "retrieval_document_id": str(payload["retrieval_document_id"]),
                "source_asset_version_id": source.asset_version_id,
                "source_content_hash": source.content_hash,
                "retrieval_document_projection_hash": str(
                    payload["retrieval_document_projection_hash"]
                ),
                "projection_version": EMBEDDING_PROJECTION_VERSION,
                "embedding": [float(item) for item in vectors[0]],
                "embedding_model": str(
                    provider_result.output.get("embedding_model") or ""
                ),
                "embedding_dimensions": dimensions,
                "provider_evidence": provider_result.to_evidence(),
            },
            qualification_policy="retrieval-embedding-candidate-v1",
        )


class RetrievalEmbeddingProjectionRuntime:

    def __init__(
        self,
        database_url: str,
        *,
        provider: ChapterModelPort,
        worker_id: str,
        application_build_id: str,
        commit_sha: str,
        lease_seconds: int = 60,
    ) -> None:
        self.database_url = database_url
        self.provider = provider
        self.worker_id = worker_id
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.lease_seconds = lease_seconds

    def schedule_pending(
        self, *, limit: int = 20, project_id: str = ""
    ) -> tuple[str, ...]:
        if limit <= 0:
            raise ValueError("embedding projection limit must be positive")
        self._register_definition()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT document.project_id, document.book_id,
                       document.retrieval_document_id,
                       document.source_asset_version_id,
                       version.content_hash, document.content_text,
                       document.accepted_from_chapter, document.projection_hash,
                       source_operation.workspace_id
                FROM authority_narrative_retrieval_document AS document
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=document.source_asset_version_id
                JOIN authority_operation AS source_operation
                  ON source_operation.operation_id=document.created_by_operation_id
                WHERE (%s='' OR document.project_id=%s)
                  AND NOT EXISTS (
                    SELECT 1
                    FROM authority_retrieval_embedding_projection AS projection
                    WHERE projection.retrieval_document_id=
                          document.retrieval_document_id
                      AND projection.projection_version=%s
                      AND projection.source_content_hash=version.content_hash
                )
                ORDER BY document.created_at, document.retrieval_document_id
                LIMIT %s
                """,
                [
                    project_id,
                    project_id,
                    EMBEDDING_PROJECTION_VERSION,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        admitted_ids: list[str] = []
        for row in rows:
            project_id = str(row[0])
            document_id = str(row[2])
            admission = admit_command(
                self.database_url,
                {
                    "definition_name": EMBEDDING_DEFINITION_NAME,
                    "definition_version": EMBEDDING_DEFINITION_VERSION,
                    "project_id": project_id,
                    "workspace_id": str(row[8]),
                    "book_id": str(row[1]),
                    "actor_id": self.worker_id,
                    "idempotency_scope": "retrieval:embedding-projection",
                    "idempotency_key": (
                        f"{document_id}:{EMBEDDING_PROJECTION_VERSION}:{row[4]}"
                    ),
                    "trace_id": f"retrieval-embedding:{document_id}",
                    "span_id": str(uuid4()),
                    "correlation_id": document_id,
                    "causation_id": str(row[7]),
                    "input": {
                        "project_id": project_id,
                        "input_asset_version_ids": [str(row[3])],
                        "payload": {
                            "book_id": str(row[1]),
                            "retrieval_document_id": document_id,
                            "source_asset_version_id": str(row[3]),
                            "source_content_hash": str(row[4]),
                            "content_text": str(row[5]),
                            "accepted_from_chapter": int(row[6]),
                            "retrieval_document_projection_hash": str(row[7]),
                            "projection_version": EMBEDDING_PROJECTION_VERSION,
                            "token_budget": max(1, len(str(row[5])) // 4),
                        },
                    },
                    "input_assets": [
                        {
                            "asset_version_id": str(row[3]),
                            "content_hash": str(row[4]),
                        }
                    ],
                },
                context=AdmissionContext(
                    actor_id=self.worker_id,
                    permissions=frozenset({"chapter.authority.execute"}),
                    available_handlers=frozenset({EMBEDDING_HANDLER_KEY}),
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                ),
            )
            projection_operation_id = str(admission["operation_id"])
            saga = start_saga(
                self.database_url,
                GraphCommandContext(
                    project_id=project_id,
                    actor_id=self.worker_id,
                    trace_id=f"retrieval-embedding:{document_id}",
                    correlation_id=document_id,
                ),
                root_operation_id=projection_operation_id,
            )
            register_saga_step(
                self.database_url,
                GraphCommandContext(
                    project_id=project_id,
                    actor_id=self.worker_id,
                    trace_id=f"retrieval-embedding:{document_id}",
                    correlation_id=document_id,
                ),
                str(saga["saga_id"]),
                projection_operation_id,
                "accepted_document_embedding",
                1,
                "",
            )
            self._persist_projection_status(
                project_id=project_id,
                operation_id=projection_operation_id,
                status="PENDING",
                evidence={
                    "reason": "embedding_projection_admitted",
                    "admission_replayed": bool(admission.get("replayed")),
                },
            )
            admitted_ids.append(projection_operation_id)
        return tuple(admitted_ids)

    def pending_operations(self, *, limit: int = 20) -> tuple[tuple[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, operation_id
                FROM authority_operation
                WHERE definition_name=%s
                  AND status IN (
                      'ADMITTED','READY','EXECUTING','FAILED_RETRYABLE',
                      'WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED',
                      'CANCELLATION_REQUESTED'
                  )
                ORDER BY created_at, operation_id
                LIMIT %s
                """,
                [EMBEDDING_DEFINITION_NAME, limit],
            )
            rows = uow.cursor.fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def tick(self, *, project_id: str, operation_id: str) -> EmbeddingProjectionTick:
        self._register_definition()
        state = self._operation_state(project_id, operation_id)
        payload = dict(state["command_payload"].get("payload") or {})
        document_id = str(payload.get("retrieval_document_id") or "")
        if state["status"] == "SUCCEEDED":
            self._coordinate_terminal_saga(state, project_id, document_id)
            return EmbeddingProjectionTick(operation_id, document_id, "SUCCEEDED", True)
        if state["status"] in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
            terminal_projection_status = _projection_status_for_operation(
                str(state["status"])
            )
            assert terminal_projection_status is not None
            self._persist_projection_status(
                project_id=project_id,
                operation_id=operation_id,
                status=terminal_projection_status,
                evidence={"operation_status": str(state["status"])},
            )
            self._coordinate_terminal_saga(state, project_id, document_id)
            return EmbeddingProjectionTick(
                operation_id, document_id, str(state["status"]), True
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=self.worker_id,
                    reason="accepted embedding source frozen",
                    trace_id=str(state["trace_id"]),
                    correlation_id=document_id,
                    causation_id=document_id,
                ),
            )
            state = self._operation_state(project_id, operation_id)
        if state["status"] in {"READY", "FAILED_RETRYABLE"}:
            attempt = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=3,
                trace_id=str(state["trace_id"]),
                correlation_id=document_id,
            )
            if attempt["dead_letter"] or not attempt["attempt_id"]:
                state = self._operation_state(project_id, operation_id)
                self._persist_projection_status(
                    project_id=project_id,
                    operation_id=operation_id,
                    status="DEAD_LETTER",
                    evidence={
                        "operation_status": str(state["status"]),
                        "reason": "embedding_projection_retry_exhausted",
                    },
                )
                self._coordinate_terminal_saga(state, project_id, document_id)
                return EmbeddingProjectionTick(
                    operation_id, document_id, "DEAD_LETTER", False
                )
            attempt_id = str(attempt["attempt_id"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=str(state["trace_id"]),
                correlation_id=document_id,
            )
            attempt_status = "QUEUED"
        elif (
            state["status"]
            in {
                "EXECUTING",
                "WAITING_EXTERNAL_RESULT",
                "RECONCILIATION_REQUIRED",
                "CANCELLATION_REQUESTED",
            }
            and state["attempt_id"]
        ):
            attempt_id = str(state["attempt_id"])
            attempt_status = str(state["attempt_status"])
        else:
            raise KernelError(
                "RETRIEVAL_EMBEDDING_OPERATION_STATE_INVALID",
                f"embedding projection Operation is {state['status']}",
            )
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            trace_id=str(state["trace_id"]),
            correlation_id=document_id,
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=str(state["trace_id"]),
            correlation_id=document_id,
            causation_id=operation_id,
        )
        if attempt_status in {"QUEUED", "LEASED"}:
            start_attempt(self.database_url, worker)
        self._persist_projection_status(
            project_id=project_id,
            operation_id=operation_id,
            status=(
                "RECONCILIATION_REQUIRED"
                if str(state["status"])
                in {"WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"}
                else "RUNNING"
            ),
            evidence={
                "attempt_id": attempt_id,
                "fencing_token": worker.fencing_token,
                "operation_status": str(state["status"]),
            },
            worker=worker,
        )
        try:
            if str(state["status"]) in {
                "WAITING_EXTERNAL_RESULT",
                "RECONCILIATION_REQUIRED",
                "CANCELLATION_REQUESTED",
            }:
                self._reconcile_external_effects(state, worker)
                state = self._operation_state(project_id, operation_id)
                if state["status"] != "EXECUTING":
                    projection_status = _projection_status_for_operation(
                        str(state["status"])
                    ) or (
                        "RECONCILIATION_REQUIRED"
                        if state["status"]
                        in {
                            "WAITING_EXTERNAL_RESULT",
                            "RECONCILIATION_REQUIRED",
                            "COMPENSATION_REQUIRED",
                        }
                        else "RUNNING"
                    )
                    self._persist_projection_status(
                        project_id=project_id,
                        operation_id=operation_id,
                        status=projection_status,
                        evidence={
                            "attempt_id": attempt_id,
                            "operation_status": str(state["status"]),
                            "reason": "external_effect_reconciled",
                        },
                    )
                    if projection_status in {
                        "FAILED_FINAL",
                        "DEAD_LETTER",
                        "CANCELLED",
                    }:
                        self._coordinate_terminal_saga(state, project_id, document_id)
                    return EmbeddingProjectionTick(
                        operation_id, document_id, str(state["status"]), False
                    )
            result = execute_authority_handler(
                self.database_url,
                command=worker,
                registration=AuthorityHandlerRegistration(
                    definition_name=EMBEDDING_DEFINITION_NAME,
                    definition_version=EMBEDDING_DEFINITION_VERSION,
                    handler_key=EMBEDDING_HANDLER_KEY,
                    handler_contract_version="retrieval-embedding-handler-v1",
                    output_asset_type="retrieval_embedding_candidate",
                    output_key="retrieval.embedding.candidate",
                    role="derived_projection_candidate",
                    completion_topic="retrieval.embedding.candidate.materialized",
                    handler=_EmbeddingHandler(self.provider),
                ),
            )
            self._persist_ready_projection(
                worker, operation_id, result.asset_version_id
            )
            current = self._operation_state(project_id, operation_id)
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_status=str(current["status"]),
                    expected_operation_version=int(current["version"]),
                ),
                outcome="success",
                result={
                    "retrieval_document_id": document_id,
                    "embedding_projection_status": "READY",
                },
            )
            self._coordinate_terminal_saga(
                self._operation_state(project_id, operation_id),
                project_id,
                document_id,
            )
            return EmbeddingProjectionTick(
                operation_id, document_id, "SUCCEEDED", result.replayed
            )
        except Exception as exc:
            self._handle_failure(
                worker=worker,
                operation_id=operation_id,
                document_id=document_id,
                error=exc,
            )
            raise

    def _handle_failure(
        self,
        *,
        worker: WorkerLeaseCommand,
        operation_id: str,
        document_id: str,
        error: Exception,
    ) -> None:
        classification = WorkerFailureClassifier.classify(error)
        error_code = (
            error.code if isinstance(error, KernelError) else type(error).__name__
        )
        if classification is WorkerFailureClass.UNKNOWN_EXTERNAL_STATE:
            self._persist_projection_status(
                project_id=worker.project_id,
                operation_id=operation_id,
                status="RECONCILIATION_REQUIRED",
                evidence={
                    "attempt_id": worker.attempt_id,
                    "error_code": error_code,
                    "reason": "external_state_unknown",
                },
                worker=worker,
            )
            checkpoint_attempt_for_external_reconciliation(
                self.database_url,
                worker,
                {
                    "reason": "external_state_unknown",
                    "error_code": error_code,
                    "error_message": str(error),
                },
            )
            return
        if classification is WorkerFailureClass.CANCELLATION:
            current = self._operation_state(worker.project_id, operation_id)
            acknowledge_worker_cancellation(
                self.database_url,
                worker,
                expected_operation_version=int(current["version"]),
            )
        elif classification in {
            WorkerFailureClass.LEASE_CONFLICT,
            WorkerFailureClass.FENCING_CONFLICT,
        }:
            return
        else:
            submit_attempt_failure(
                self.database_url,
                worker,
                retryable=classification is WorkerFailureClass.RETRYABLE,
                error_code=error_code,
                error_message=str(error),
                failure_class=classification.value,
            )
        current = self._operation_state(worker.project_id, operation_id)
        projection_status = _projection_status_for_operation(str(current["status"]))
        if projection_status is None:
            projection_status = (
                "RECONCILIATION_REQUIRED"
                if current["status"] == "RECONCILIATION_REQUIRED"
                else "FAILED_FINAL"
            )
        self._persist_projection_status(
            project_id=worker.project_id,
            operation_id=operation_id,
            status=projection_status,
            evidence={
                "attempt_id": worker.attempt_id,
                "operation_status": str(current["status"]),
                "error_code": error_code,
                "failure_class": classification.value,
            },
        )
        if projection_status in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
            self._coordinate_terminal_saga(current, worker.project_id, document_id)

    def _reconcile_external_effects(
        self,
        state: dict[str, Any],
        worker: WorkerLeaseCommand,
    ) -> None:
        operation_id = str(state["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT external_effect_id, status, request_payload
                FROM authority_external_effect
                WHERE operation_id=%s AND project_id=%s
                  AND capability='model.retrieval'
                ORDER BY created_at, external_effect_id
                """,
                [operation_id, worker.project_id],
            )
            effects = tuple(uow.cursor.fetchall())
        if not effects:
            if state["status"] == "CANCELLATION_REQUESTED":
                acknowledge_worker_cancellation(
                    self.database_url,
                    worker,
                    expected_operation_version=int(state["version"]),
                )
                return
            raise KernelError(
                "RETRIEVAL_EMBEDDING_RECONCILIATION_EVIDENCE_MISSING",
                "embedding reconciliation has no ExternalEffect evidence",
            )
        adapter = getattr(self.provider, "adapter", None)
        context = EffectCommandContext(
            operation_id=operation_id,
            project_id=worker.project_id,
            actor_id=worker.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
        )
        matched_attempt = False
        for effect_id_value, effect_status, request_payload in effects:
            effect_id = str(effect_id_value)
            metadata = (
                request_payload.get("_production_execution")
                if isinstance(request_payload, dict)
                else None
            )
            if not isinstance(metadata, dict):
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_EXECUTION_IDENTITY_INVALID",
                    "embedding ExternalEffect has no frozen execution identity",
                )
            if str(metadata.get("attempt_id") or "") != worker.attempt_id:
                continue
            matched_attempt = True
            disposition = classify_external_effect_recovery(str(effect_status))
            current = self._operation_state(worker.project_id, operation_id)
            if disposition is EffectRecoveryDisposition.DISPATCH_PLANNED:
                if current["status"] == "CANCELLATION_REQUESTED":
                    acknowledge_worker_cancellation(
                        self.database_url,
                        worker,
                        expected_operation_version=int(current["version"]),
                    )
                    return
                transition_operation(
                    self.database_url,
                    OperationTransitionCommand(
                        operation_id=operation_id,
                        project_id=worker.project_id,
                        expected_version=int(current["version"]),
                        expected_status=str(current["status"]),
                        target_status="EXECUTING",
                        actor_id=worker.worker_id,
                        reason="planned embedding effect is confirmed undispatched",
                        trace_id=worker.trace_id,
                        correlation_id=worker.correlation_id,
                        causation_id=effect_id,
                    ),
                )
                continue
            if disposition is EffectRecoveryDisposition.CONSUME_SUCCEEDED:
                if current["status"] == "CANCELLATION_REQUESTED":
                    acknowledge_worker_cancellation(
                        self.database_url,
                        worker,
                        expected_operation_version=int(current["version"]),
                    )
                    return
                resume_operation_from_completed_effect(
                    self.database_url,
                    context,
                    effect_id=effect_id,
                )
                continue
            if disposition is EffectRecoveryDisposition.RETRY_POLICY:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=True,
                    error_code="RETRIEVAL_EMBEDDING_EXTERNAL_EFFECT_RETRY_REQUIRED",
                    error_message="Provider recorded a definitive retryable failure",
                    failure_class=WorkerFailureClass.RETRYABLE.value,
                )
                return
            if disposition is EffectRecoveryDisposition.TERMINAL_FAILURE:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=False,
                    error_code="RETRIEVAL_EMBEDDING_EXTERNAL_EFFECT_FINAL_FAILURE",
                    error_message="Provider recorded a terminal embedding failure",
                    failure_class=WorkerFailureClass.FINAL_FAILURE.value,
                )
                return
            if disposition is EffectRecoveryDisposition.TERMINAL_CANCELLED:
                if current["status"] != "CANCELLATION_REQUESTED":
                    transition_operation(
                        self.database_url,
                        OperationTransitionCommand(
                            operation_id=operation_id,
                            project_id=worker.project_id,
                            expected_version=int(current["version"]),
                            expected_status=str(current["status"]),
                            target_status="CANCELLATION_REQUESTED",
                            actor_id=worker.worker_id,
                            reason="Provider confirms embedding effect cancellation",
                            trace_id=worker.trace_id,
                            correlation_id=worker.correlation_id,
                            causation_id=effect_id,
                        ),
                    )
                    current = self._operation_state(worker.project_id, operation_id)
                acknowledge_worker_cancellation(
                    self.database_url,
                    worker,
                    expected_operation_version=int(current["version"]),
                )
                return
            if disposition is EffectRecoveryDisposition.OPERATOR_RECONCILIATION:
                if current["status"] == "WAITING_EXTERNAL_RESULT":
                    transition_operation(
                        self.database_url,
                        OperationTransitionCommand(
                            operation_id=operation_id,
                            project_id=worker.project_id,
                            expected_version=int(current["version"]),
                            expected_status="WAITING_EXTERNAL_RESULT",
                            target_status="RECONCILIATION_REQUIRED",
                            actor_id=worker.worker_id,
                            reason="embedding effect requires operator reconciliation",
                            trace_id=worker.trace_id,
                            correlation_id=worker.correlation_id,
                            causation_id=effect_id,
                        ),
                    )
                self._persist_projection_status(
                    project_id=worker.project_id,
                    operation_id=operation_id,
                    status="RECONCILIATION_REQUIRED",
                    evidence={
                        "attempt_id": worker.attempt_id,
                        "external_effect_id": effect_id,
                        "reason": "operator_reconciliation_required",
                    },
                    worker=worker,
                )
                checkpoint_attempt_for_external_reconciliation(
                    self.database_url,
                    worker,
                    {"reason": "operator_reconciliation_required"},
                )
                return
            authorize = getattr(adapter, "for_recovery", None)
            if not callable(authorize):
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_RECOVERY_AUTHORIZATION_MISSING",
                    "embedding reconciliation requires a recovery-capable PEP adapter",
                )
            try:
                execution_fence = int(metadata.get("fencing_token") or 0)
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_EXECUTION_IDENTITY_INVALID",
                    "embedding ExternalEffect has an invalid execution fence",
                ) from exc
            if execution_fence <= 0:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_EXECUTION_IDENTITY_INVALID",
                    "embedding ExternalEffect has no frozen execution fence",
                )
            recovery_adapter = authorize(
                execution_id=f"chapter-execution:{effect_id}",
                external_effect_id=effect_id,
                operation_id=operation_id,
                attempt_id=worker.attempt_id,
                execution_fencing_token=execution_fence,
                recovery_fencing_token=worker.fencing_token,
                recovery_worker_id=worker.worker_id,
                action=ExecutionRecoveryAction.QUERY,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
            outcome = str(
                reconcile_external_effect(
                    self.database_url,
                    context,
                    effect_id=effect_id,
                    adapter=recovery_adapter,
                    attempt_command=worker,
                )["outcome"]
            )
            if outcome == "ambiguous":
                self._persist_projection_status(
                    project_id=worker.project_id,
                    operation_id=operation_id,
                    status="RECONCILIATION_REQUIRED",
                    evidence={
                        "attempt_id": worker.attempt_id,
                        "external_effect_id": effect_id,
                        "reconciliation_outcome": outcome,
                    },
                    worker=worker,
                )
                checkpoint_attempt_for_external_reconciliation(
                    self.database_url,
                    worker,
                    {
                        "reason": "provider_query_remains_ambiguous",
                        "external_effect_id": effect_id,
                    },
                )
                return
            if outcome in {"not_found", "failed_final", "cancelled"}:
                return
        if not matched_attempt:
            raise KernelError(
                "RETRIEVAL_EMBEDDING_RECONCILIATION_EVIDENCE_MISSING",
                "current embedding Attempt has no matching ExternalEffect",
            )

    def _persist_projection_status(
        self,
        *,
        project_id: str,
        operation_id: str,
        status: str,
        evidence: dict[str, Any],
        worker: WorkerLeaseCommand | None = None,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            if worker is not None:
                attempt = uow.repositories.attempt_runtime.get_for_update(
                    worker.attempt_id, worker.project_id
                )
                valid, _current_token = uow.repositories.attempt_runtime.current_fence(
                    worker.attempt_id,
                    worker.worker_id,
                    worker.fencing_token,
                )
                if not valid:
                    raise KernelError(
                        "ATTEMPT_FENCING_TOKEN_STALE",
                        "embedding projection status carries a stale Attempt fence",
                    )
                if attempt["status"] not in {"RUNNING", "CHECKPOINTED"}:
                    raise KernelError(
                        "ATTEMPT_STATUS_CONFLICT",
                        "embedding projection status requires an active Attempt",
                    )
            uow.cursor.execute(
                """
                SELECT operation.command_payload, document.project_id,
                       document.book_id
                FROM authority_operation AS operation
                JOIN authority_narrative_retrieval_document AS document
                  ON document.retrieval_document_id=
                     operation.command_payload->'payload'->>'retrieval_document_id'
                WHERE operation.operation_id=%s AND operation.project_id=%s
                  AND operation.definition_name=%s
                """,
                [operation_id, project_id, EMBEDDING_DEFINITION_NAME],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_OPERATION_MISSING",
                    "embedding projection Operation is missing",
                )
            payload = dict(dict(row[0] or {}).get("payload") or {})
            document_id = str(payload.get("retrieval_document_id") or "")
            source_version_id = str(payload.get("source_asset_version_id") or "")
            source_hash = str(payload.get("source_content_hash") or "")
            projection_version = str(payload.get("projection_version") or "")
            projection_id = _projection_id(document_id, projection_version)
            uow.cursor.execute(
                """
                SELECT source_asset_version_id, source_content_hash,
                       projection_version, operation_id, status
                FROM authority_retrieval_embedding_projection
                WHERE retrieval_document_id=%s AND projection_version=%s
                FOR UPDATE
                """,
                [document_id, projection_version],
            )
            current = uow.cursor.fetchone()
            if current is None:
                uow.cursor.execute(
                    """
                    INSERT INTO authority_retrieval_embedding_projection(
                        embedding_projection_id, project_id, book_id,
                        retrieval_document_id, source_asset_version_id,
                        source_content_hash, projection_version, status,
                        operation_id, evidence
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    [
                        projection_id,
                        project_id,
                        str(row[2]),
                        document_id,
                        source_version_id,
                        source_hash,
                        projection_version,
                        status,
                        operation_id,
                        Jsonb(evidence),
                    ],
                )
            else:
                identity = (
                    str(current[0]),
                    str(current[1]),
                    str(current[2]),
                    str(current[3]),
                )
                expected_identity = (
                    source_version_id,
                    source_hash,
                    projection_version,
                    operation_id,
                )
                if identity != expected_identity:
                    raise KernelError(
                        "RETRIEVAL_EMBEDDING_IDEMPOTENCY_CONFLICT",
                        "embedding projection identity differs from its frozen source",
                    )
                if str(current[4]) != "READY":
                    uow.cursor.execute(
                        """
                        UPDATE authority_retrieval_embedding_projection
                        SET status=%s, evidence=evidence || %s,
                            version=version+1, updated_at=NOW()
                        WHERE embedding_projection_id=%s
                        """,
                        [status, Jsonb(evidence), projection_id],
                    )
            uow.commit()

    def _persist_ready_projection(
        self, worker: WorkerLeaseCommand, operation_id: str, candidate_version_id: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                """,
                [candidate_version_id, worker.project_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_CANDIDATE_MISSING",
                    "materialized embedding candidate is missing",
                )
            candidate = dict(row[0] or {})
            uow.cursor.execute(
                """
                SELECT effect.external_effect_id,
                       COALESCE(receipt.receipt_id, ''),
                       effect.provider, effect.request_hash
                FROM authority_external_effect AS effect
                LEFT JOIN LATERAL (
                    SELECT receipt.receipt_id
                    FROM authority_external_effect_dispatch AS dispatch
                    JOIN authority_external_receipt AS receipt
                      ON receipt.dispatch_id=dispatch.dispatch_id
                    WHERE dispatch.external_effect_id=effect.external_effect_id
                    ORDER BY receipt.received_at DESC LIMIT 1
                ) AS receipt ON TRUE
                WHERE effect.operation_id=%s AND effect.project_id=%s
                  AND effect.capability='model.retrieval'
                  AND effect.status='SUCCEEDED'
                ORDER BY effect.created_at DESC LIMIT 1
                """,
                [operation_id, worker.project_id],
            )
            effect = uow.cursor.fetchone()
            if effect is None or not str(effect[1] or ""):
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_RECEIPT_MISSING",
                    "ready embedding projection requires a durable ExternalEffect receipt",
                )
            evidence = {
                "candidate_asset_version_id": candidate_version_id,
                "provider_evidence": dict(candidate.get("provider_evidence") or {}),
                "retrieval_document_projection_hash": str(
                    candidate["retrieval_document_projection_hash"]
                ),
                "external_effect_request_hash": str(effect[3]),
            }
            projection = {
                "retrieval_document_id": str(candidate["retrieval_document_id"]),
                "source_asset_version_id": str(candidate["source_asset_version_id"]),
                "source_content_hash": str(candidate["source_content_hash"]),
                "projection_version": str(candidate["projection_version"]),
                "embedding": list(candidate["embedding"]),
                "embedding_model": str(candidate["embedding_model"]),
                "embedding_provider": str(effect[2]),
                "embedding_dimensions": int(candidate["embedding_dimensions"]),
                "route_snapshot_id": str(
                    dict(candidate.get("provider_evidence") or {})
                    .get("production_execution", {})
                    .get("route_snapshot", {})
                    .get("route_snapshot_id", "")
                ),
                "external_effect_id": str(effect[0]),
                "receipt_id": str(effect[1]),
                "operation_id": operation_id,
                "evidence": evidence,
            }
            if not projection["route_snapshot_id"]:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_ROUTE_EVIDENCE_MISSING",
                    "ready embedding projection requires the exact PEP route snapshot",
                )
            projection_hash = _hash(projection)
            projection_id = _projection_id(
                projection["retrieval_document_id"],
                projection["projection_version"],
            )
            uow.cursor.execute(
                """
                SELECT project_id, book_id
                FROM authority_narrative_retrieval_document
                WHERE retrieval_document_id=%s
                """,
                [projection["retrieval_document_id"]],
            )
            scope = uow.cursor.fetchone()
            if scope is None:
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_DOCUMENT_MISSING",
                    "embedding source retrieval document is missing",
                )
            uow.cursor.execute(
                """
                INSERT INTO authority_retrieval_embedding_projection AS current(
                    embedding_projection_id, project_id, book_id,
                    retrieval_document_id, source_asset_version_id,
                    source_content_hash, projection_version, status,
                    embedding, embedding_vector,
                    embedding_model, embedding_provider,
                    embedding_dimensions, route_snapshot_id, external_effect_id,
                    receipt_id, operation_id, projection_hash, evidence
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'READY',%s,%s::vector,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(retrieval_document_id, projection_version) DO UPDATE
                SET status='READY', embedding=EXCLUDED.embedding,
                    embedding_vector=EXCLUDED.embedding_vector,
                    embedding_model=EXCLUDED.embedding_model,
                    embedding_provider=EXCLUDED.embedding_provider,
                    embedding_dimensions=EXCLUDED.embedding_dimensions,
                    route_snapshot_id=EXCLUDED.route_snapshot_id,
                    external_effect_id=EXCLUDED.external_effect_id,
                    receipt_id=EXCLUDED.receipt_id,
                    operation_id=EXCLUDED.operation_id,
                    projection_hash=EXCLUDED.projection_hash,
                    evidence=EXCLUDED.evidence,
                    version=current.version+1, updated_at=NOW()
                WHERE current.status<>'READY'
                  AND current.source_asset_version_id=
                      EXCLUDED.source_asset_version_id
                  AND current.source_content_hash=EXCLUDED.source_content_hash
                  AND current.operation_id=EXCLUDED.operation_id
                """,
                [
                    projection_id,
                    str(scope[0]),
                    str(scope[1]),
                    projection["retrieval_document_id"],
                    projection["source_asset_version_id"],
                    projection["source_content_hash"],
                    projection["projection_version"],
                    Jsonb(projection["embedding"]),
                    _pgvector_literal(projection["embedding"]),
                    projection["embedding_model"],
                    projection["embedding_provider"],
                    projection["embedding_dimensions"],
                    projection["route_snapshot_id"],
                    projection["external_effect_id"],
                    projection["receipt_id"],
                    projection["operation_id"],
                    projection_hash,
                    Jsonb(evidence),
                ],
            )
            uow.cursor.execute(
                """
                SELECT source_content_hash, status, embedding, embedding_model,
                       embedding_dimensions, external_effect_id, receipt_id,
                       projection_hash
                FROM authority_retrieval_embedding_projection
                WHERE retrieval_document_id=%s AND projection_version=%s
                """,
                [
                    projection["retrieval_document_id"],
                    projection["projection_version"],
                ],
            )
            persisted = uow.cursor.fetchone()
            if persisted is None or (
                str(persisted[0]),
                str(persisted[1]),
                list(persisted[2] or ()),
                str(persisted[3]),
                int(persisted[4] or 0),
                str(persisted[5]),
                str(persisted[6]),
                str(persisted[7]),
            ) != (
                projection["source_content_hash"],
                "READY",
                projection["embedding"],
                projection["embedding_model"],
                projection["embedding_dimensions"],
                projection["external_effect_id"],
                projection["receipt_id"],
                projection_hash,
            ):
                raise KernelError(
                    "RETRIEVAL_EMBEDDING_IDEMPOTENCY_CONFLICT",
                    "existing embedding projection differs from Provider evidence",
                )
            uow.commit()

    def _register_definition(self) -> None:
        definition = embedding_projection_operation_definition(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()

    def _coordinate_terminal_saga(
        self,
        state: dict[str, Any],
        project_id: str,
        document_id: str,
    ) -> None:
        saga_id = str(state.get("saga_id") or "")
        if not saga_id:
            raise KernelError(
                "RETRIEVAL_EMBEDDING_SAGA_MISSING",
                "embedding projection Operation has no durable execution Saga",
            )
        coordinate_saga(
            self.database_url,
            GraphCommandContext(
                project_id=project_id,
                actor_id=self.worker_id,
                trace_id=str(state["trace_id"]),
                correlation_id=document_id,
                causation_id=str(state["operation_id"]),
            ),
            saga_id,
        )

    def _operation_state(self, project_id: str, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, operation.version, operation.trace_id,
                       operation.command_payload, attempt.attempt_id, attempt.status,
                       saga.saga_id
                FROM authority_operation AS operation
                LEFT JOIN LATERAL (
                    SELECT attempt_id, status
                    FROM authority_attempt
                    WHERE operation_id=operation.operation_id
                    ORDER BY attempt_number DESC LIMIT 1
                ) AS attempt ON TRUE
                LEFT JOIN authority_saga AS saga
                  ON saga.root_operation_id=operation.root_operation_id
                 AND saga.project_id=operation.project_id
                WHERE operation.operation_id=%s AND operation.project_id=%s
                  AND operation.definition_name=%s
                """,
                [operation_id, project_id, EMBEDDING_DEFINITION_NAME],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "RETRIEVAL_EMBEDDING_OPERATION_MISSING",
                "embedding projection Operation is missing",
            )
        return {
            "status": str(row[0]),
            "version": int(row[1]),
            "trace_id": str(row[2]),
            "command_payload": dict(row[3] or {}),
            "attempt_id": str(row[4] or ""),
            "attempt_status": str(row[5] or ""),
            "saga_id": str(row[6] or ""),
            "operation_id": operation_id,
        }


def _hash(value: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _projection_id(document_id: str, projection_version: str) -> str:
    return (
        "retrieval-embedding:"
        + hashlib.sha256(f"{document_id}:{projection_version}".encode()).hexdigest()
    )


def _pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(float(item), ".17g") for item in vector) + "]"


def _projection_status_for_operation(operation_status: str) -> str | None:
    return {
        "FAILED_RETRYABLE": "FAILED_RETRYABLE",
        "FAILED_FINAL": "FAILED_FINAL",
        "DEAD_LETTER": "DEAD_LETTER",
        "CANCELLED": "CANCELLED",
        "WAITING_EXTERNAL_RESULT": "RECONCILIATION_REQUIRED",
        "RECONCILIATION_REQUIRED": "RECONCILIATION_REQUIRED",
        "COMPENSATION_REQUIRED": "RECONCILIATION_REQUIRED",
    }.get(operation_status)


__all__ = [
    "EMBEDDING_DEFINITION_NAME",
    "embedding_projection_operation_definition",
    "EMBEDDING_PROJECTION_VERSION",
    "EmbeddingProjectionTick",
    "RetrievalEmbeddingProjectionRuntime",
]
