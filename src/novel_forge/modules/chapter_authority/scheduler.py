"""Durable Chapter Saga scheduler over the shared Command Kernel primitives."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRegistry,
    ChapterNode,
    QUALITY_GROUP_NODES,
)
from novel_forge.modules.chapter_authority.export_delivery import (
    ExportDeliveryRequest,
    deliver_export,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    _command,
    _input_nodes,
)
from novel_forge.modules.chapter_authority.runtime import execute_chapter_handler
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
    submit_attempt_failure,
    checkpoint_attempt_for_external_reconciliation,
    heartbeat_attempt,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)
from novel_forge.modules.command_kernel.external_effect_adapters import ExternalEffectAdapter
from novel_forge.modules.command_kernel.cancellation import acknowledge_worker_cancellation
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decision_asset_versions,
    ensure_canon_approval_requests,
)
from novel_forge.modules.command_kernel.deadline_runtime import probe_operation_execution
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    register_saga_step,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class ChapterSchedulerTick:
    root_operation_id: str
    saga_id: str
    saga_status: str
    operation_id: str
    node: str
    operation_status: str
    recovery_mode: str


def _admission_dependencies(node: ChapterNode) -> tuple[ChapterNode, ...]:
    if node is ChapterNode.PLAN:
        return ()
    if node in QUALITY_GROUP_NODES:
        return (ChapterNode.CANON,)
    if node is ChapterNode.QUALITY:
        return QUALITY_GROUP_NODES
    nodes = list(ChapterNode)
    return (nodes[nodes.index(node) - 1],)


class ChapterAuthorityScheduler:
    """Advance at most one Chapter node using only PostgreSQL-rebuilt state."""

    def __init__(
        self,
        database_url: str,
        *,
        registry: ChapterHandlerRegistry,
        object_store_adapter: ExternalEffectAdapter,
        worker_id: str,
        permissions: frozenset[str],
        lease_seconds: int = 30,
    ) -> None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError("configured worker identity and positive lease are required")
        self.database_url = database_url
        self.registry = registry
        self.object_store_adapter = object_store_adapter
        self.worker_id = worker_id
        self.permissions = permissions
        self.lease_seconds = lease_seconds

    def tick(self, *, project_id: str, root_operation_id: str) -> ChapterSchedulerTick:
        root, saga, children = self._graph_state(project_id, root_operation_id)
        context = GraphCommandContext(
            project_id=project_id,
            actor_id=self.worker_id,
            trace_id=root["trace_id"],
            correlation_id=root["correlation_id"],
        )
        coordinated = coordinate_saga(self.database_url, context, saga["saga_id"])
        if coordinated["status"] in {
            "SUCCEEDED", "FAILED_FINAL", "DEAD_LETTER", "CANCELLED",
            "COMPENSATED", "COMPENSATION_FAILED",
        }:
            return ChapterSchedulerTick(
                root_operation_id=root_operation_id,
                saga_id=saga["saga_id"],
                saga_status=coordinated["status"],
                operation_id="",
                node="",
                operation_status=str(root["status"]),
                recovery_mode="terminal_replay",
            )
        request = self._request_from_root(root)
        if children.get(ChapterNode.CANON, {}).get("status") == "SUCCEEDED":
            admitted_fanout = False
            for quality_node in QUALITY_GROUP_NODES:
                if quality_node not in children:
                    child = self._admit_node(
                        request=request,
                        root=root,
                        saga_id=saga["saga_id"],
                        children=children,
                        node=quality_node,
                    )
                    children[quality_node] = child
                    admitted_fanout = True
            if admitted_fanout:
                coordinate_saga(self.database_url, context, saga["saga_id"])
                root, saga, children = self._graph_state(project_id, root_operation_id)
        node, operation = self._current_or_next(children)
        if node is ChapterNode.CANON and operation is None:
            proposal_operation = children[ChapterNode.CANON_PROPOSAL]
            proposal_ref = self._primary_output(
                str(proposal_operation["operation_id"]), project_id
            )
            proposal = self._asset_content(
                proposal_ref["asset_version_id"], project_id
            )
            gate = ensure_canon_approval_requests(
                self.database_url,
                CanonApprovalContext(
                    project_id=project_id,
                    principal_id=self.worker_id,
                    trace_id=str(root["trace_id"]),
                    correlation_id=str(root["correlation_id"]),
                ),
                root_operation_id=root_operation_id,
                saga_id=str(saga["saga_id"]),
                proposal_asset_version_id=proposal_ref["asset_version_id"],
                proposal=proposal,
            )
            if gate["waiting"]:
                return ChapterSchedulerTick(
                    root_operation_id=root_operation_id,
                    saga_id=str(saga["saga_id"]),
                    saga_status="WAITING_GATE",
                    operation_id=root_operation_id,
                    node=ChapterNode.CANON.value,
                    operation_status="WAITING_GATE",
                    recovery_mode="canon_approval_gate",
                )
        if operation is None:
            operation = self._admit_node(
                request=request,
                root=root,
                saga_id=saga["saga_id"],
                children=children,
                node=node,
            )
            coordinated = coordinate_saga(self.database_url, context, saga["saga_id"])
            operation = self._child(str(operation["operation_id"]), project_id)
        if operation["status"] == "SUCCEEDED":
            raise KernelError(
                "CHAPTER_SCHEDULER_STATE_RACE",
                "scheduler selected an already completed node",
            )
        recovery_mode = self._execute_node(request, node, operation)
        final = coordinate_saga(self.database_url, context, saga["saga_id"])
        status = self._operation_status(str(operation["operation_id"]), project_id)
        return ChapterSchedulerTick(
            root_operation_id=root_operation_id,
            saga_id=saga["saga_id"],
            saga_status=final["status"],
            operation_id=str(operation["operation_id"]),
            node=node.value,
            operation_status=status,
            recovery_mode=recovery_mode,
        )

    def pending_roots(self, *, limit: int = 20) -> tuple[tuple[str, str], ...]:
        if limit <= 0:
            raise ValueError("pending root limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation.project_id, operation.operation_id
                FROM authority_operation AS operation
                JOIN authority_saga AS saga
                  ON saga.root_operation_id = operation.operation_id
                WHERE operation.definition_name = 'chapter.slice.run'
                  AND operation.status IN (
                    'EXECUTING', 'WAITING_CHILDREN', 'FAILED_RETRYABLE',
                    'CANCELLATION_REQUESTED', 'WAITING_GATE'
                  )
                  AND saga.status NOT IN (
                    'SUCCEEDED', 'COMPENSATED', 'COMPENSATION_FAILED', 'CANCELLED'
                  )
                ORDER BY operation.created_at, operation.operation_id
                LIMIT %s
                """,
                [limit],
            )
            rows = uow.cursor.fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def _current_or_next(
        self, children: dict[ChapterNode, dict[str, Any]]
    ) -> tuple[ChapterNode, dict[str, Any] | None]:
        for node in ChapterNode:
            operation = children.get(node)
            if operation is None:
                dependencies = _admission_dependencies(node)
                if all(
                    children.get(item, {}).get("status") == "SUCCEEDED"
                    for item in dependencies
                ):
                    return node, None
                raise KernelError(
                    "CHAPTER_SAGA_GAP",
                    f"cannot admit {node.value} before predecessor Completion",
                )
            if operation["status"] != "SUCCEEDED":
                return node, operation
        # coordinate_saga should have made the Saga terminal after all children succeeded.
        raise KernelError("CHAPTER_SAGA_COORDINATION_LAG", "completed graph is not terminal")

    def _admit_node(
        self,
        *,
        request: SingleChapterRequest,
        root: dict[str, Any],
        saga_id: str,
        children: dict[ChapterNode, dict[str, Any]],
        node: ChapterNode,
    ) -> dict[str, Any]:
        inputs: list[dict[str, str]] = []
        for source in _input_nodes(node):
            source_operation = children.get(source)
            if source_operation is None or source_operation["status"] != "SUCCEEDED":
                raise KernelError(
                    "CHAPTER_INPUT_NOT_COMPLETE",
                    f"{node.value} input {source.value} has not completed",
                )
            inputs.append(self._primary_output(str(source_operation["operation_id"]), root["project_id"]))
            if node is ChapterNode.CONTEXT and source is ChapterNode.PLAN:
                inputs.append(
                    self._output_by_key(
                        str(source_operation["operation_id"]),
                        root["project_id"],
                        "chapter.production_input_manifest",
                    )
                )
        if node is ChapterNode.CONTEXT:
            inputs.extend(
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in request.context_candidates
            )
        if node is ChapterNode.CANON:
            inputs.extend(
                decision_asset_versions(
                    self.database_url,
                    project_id=root["project_id"],
                    root_operation_id=str(root["operation_id"]),
                )
            )
        admission = AdmissionContext(
            actor_id=root["actor_id"],
            permissions=self.permissions,
            available_handlers=self.registry.available_handler_keys,
            application_build_id=root["definition_snapshot"]["application_build_id"],
            commit_sha=root["definition_snapshot"]["commit_sha"],
        )
        root_key = request.idempotency_key or (
            f"{request.project_id}:chapter:{request.chapter}:root"
        )
        dependencies = _admission_dependencies(node)
        dependency_ids = [
            str(children[item]["operation_id"])
            for item in dependencies
        ]
        previous_id = dependency_ids[-1] if dependency_ids else root["operation_id"]
        admitted = admit_command(
            self.database_url,
            _command(
                request,
                definition_name=node.definition_name,
                idempotency_key=f"{root_key}:{node.value}",
                input_assets=inputs,
                root_operation_id=root["operation_id"],
                parent_operation_id=root["operation_id"],
                causation_operation_id=previous_id,
                definition_version=root["definition_version"],
            ),
            context=admission,
        )
        operation_id = str(admitted["operation_id"])
        graph_context = GraphCommandContext(
            project_id=root["project_id"],
            actor_id=self.worker_id,
            trace_id=root["trace_id"],
            correlation_id=root["correlation_id"],
        )
        register_saga_step(
            self.database_url,
            graph_context,
            saga_id,
            operation_id,
            node.value,
            list(ChapterNode).index(node) + 1,
            "",
        )
        for dependency_id in dependency_ids:
            add_operation_dependency(
                self.database_url,
                graph_context,
                operation_id,
                dependency_id,
                "ON_SUCCESS",
            )
        return self._child(operation_id, root["project_id"])

    def _execute_node(
        self,
        request: SingleChapterRequest,
        node: ChapterNode,
        operation: dict[str, Any],
    ) -> str:
        operation_id = str(operation["operation_id"])
        project_id = request.project_id
        active = self._active_attempt(operation_id, project_id)
        recovery_mode = "fresh_attempt"
        if operation["status"] in {"READY", "FAILED_RETRYABLE"}:
            recovery_mode = "retry_attempt" if operation["status"] == "FAILED_RETRYABLE" else recovery_mode
            created = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=int(operation["max_attempts"]),
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
            if created["dead_letter"] or created["attempt_id"] is None:
                raise KernelError("CHAPTER_ATTEMPT_EXHAUSTED", "chapter Attempt policy is exhausted")
            attempt_id = str(created["attempt_id"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
            attempt_status = "QUEUED"
        elif operation["status"] == "EXECUTING" and active is not None:
            attempt_id = active["attempt_id"]
            attempt_status = active["status"]
            recovery_mode = "lease_takeover"
        else:
            raise KernelError(
                "CHAPTER_OPERATION_NOT_RECOVERABLE",
                f"cannot execute Chapter node from {operation['status']}",
            )
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            causation_id=operation_id,
        )
        if attempt_status in {"QUEUED", "LEASED"}:
            start_attempt(self.database_url, worker)
        try:
            with LeaseHeartbeatGuard(
                lambda: heartbeat_attempt(self.database_url, worker, self.lease_seconds),
                lease_seconds=self.lease_seconds,
                label=f"attempt:{attempt_id}",
                probe=lambda: probe_operation_execution(
                    self.database_url,
                    operation_id=operation_id,
                    project_id=project_id,
                ),
            ):
                output = execute_chapter_handler(
                    self.database_url,
                    command=worker,
                    node=node,
                    registry=self.registry,
                )
                if node is ChapterNode.EXPORT:
                    deliver_export(
                        self.database_url,
                        request=ExportDeliveryRequest(
                            operation_id=operation_id,
                            asset_version_id=output.asset_version_id,
                            project_id=project_id,
                            actor_id=self.worker_id,
                            chapter=request.chapter,
                            trace_id=request.trace_id,
                            correlation_id=request.correlation_id,
                        ),
                        adapter=self.object_store_adapter,
                        exercise_unknown_reconciliation=False,
                    )
            with AuthorityUnitOfWork(self.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_status=state["status"],
                    expected_operation_version=state["version"],
                ),
                outcome="success",
                result={
                    "asset_version_id": output.asset_version_id,
                    "content_hash": output.content_hash,
                    "recovery_mode": recovery_mode,
                },
            )
        except BaseException as exc:
            classification = WorkerFailureClassifier.classify(exc)
            if classification is WorkerFailureClass.CANCELLATION:
                with AuthorityUnitOfWork(self.database_url) as uow:
                    current = uow.repositories.attempt_runtime.operation_state(
                        operation_id, project_id
                    )
                acknowledge_worker_cancellation(
                    self.database_url,
                    worker,
                    expected_operation_version=int(current["version"]),
                )
            elif classification is WorkerFailureClass.UNKNOWN_EXTERNAL_STATE:
                checkpoint_attempt_for_external_reconciliation(
                    self.database_url,
                    worker,
                    {
                        "reason": "external_state_unknown",
                        "error_code": exc.code if isinstance(exc, KernelError) else "UNKNOWN",
                        "error_message": str(exc),
                    },
                )
            elif classification not in {
                WorkerFailureClass.LEASE_CONFLICT,
                WorkerFailureClass.FENCING_CONFLICT,
            }:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=classification is WorkerFailureClass.RETRYABLE,
                    error_code=exc.code if isinstance(exc, KernelError) else "PROGRAMMING_BUG",
                    error_message=str(exc),
                    failure_class=classification.value,
                )
            raise
        return recovery_mode

    def _graph_state(
        self, project_id: str, root_operation_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[ChapterNode, dict[str, Any]]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, project_id, workspace_id, actor_id, status,
                       definition_version, definition_snapshot, command_payload,
                       trace_id, correlation_id
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                  AND root_operation_id = operation_id
                """,
                [root_operation_id, project_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError("CHAPTER_RUN_NOT_FOUND", "Chapter root Operation is missing")
            root = dict(
                zip(
                    (
                        "operation_id", "project_id", "workspace_id", "actor_id", "status",
                        "definition_version", "definition_snapshot", "command_payload",
                        "trace_id", "correlation_id",
                    ),
                    row,
                    strict=True,
                )
            )
            uow.cursor.execute(
                "SELECT saga_id, status FROM authority_saga WHERE root_operation_id = %s AND project_id = %s",
                [root_operation_id, project_id],
            )
            saga_row = uow.cursor.fetchone()
            if saga_row is None:
                raise KernelError("CHAPTER_SAGA_MISSING", "Chapter root has no durable Saga")
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, status,
                       COALESCE((definition_snapshot->'retry_policy'->>'max_attempts')::int, 1)
                FROM authority_operation
                WHERE root_operation_id = %s AND operation_id <> %s AND project_id = %s
                """,
                [root_operation_id, root_operation_id, project_id],
            )
            rows = uow.cursor.fetchall()
        by_definition = {node.definition_name: node for node in ChapterNode}
        children = {
            by_definition[str(item[1])]: {
                "operation_id": item[0],
                "definition_name": item[1],
                "status": item[2],
                "max_attempts": item[3],
            }
            for item in rows
            if str(item[1]) in by_definition
        }
        return root, {"saga_id": saga_row[0], "status": saga_row[1]}, children

    def _child(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, status,
                       COALESCE((definition_snapshot->'retry_policy'->>'max_attempts')::int, 1)
                FROM authority_operation WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        return {
            "operation_id": row[0], "definition_name": row[1],
            "status": row[2], "max_attempts": row[3],
        }

    def _primary_output(self, operation_id: str, project_id: str) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation ON operation.operation_id = binding.operation_id
                WHERE binding.operation_id = %s AND operation.project_id = %s
                  AND binding.role = 'primary'
                ORDER BY binding.output_key LIMIT 1
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("CHAPTER_INPUT_OUTPUT_MISSING", "completed predecessor has no primary output")
        return {"asset_version_id": str(row[0]), "content_hash": str(row[1])}

    def _output_by_key(
        self, operation_id: str, project_id: str, output_key: str
    ) -> dict[str, str]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id = binding.operation_id
                WHERE binding.operation_id=%s AND operation.project_id=%s
                  AND binding.output_key=%s
                """,
                [operation_id, project_id, output_key],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CHAPTER_INPUT_OUTPUT_MISSING",
                f"completed predecessor has no {output_key} output",
            )
        return {"asset_version_id": str(row[0]), "content_hash": str(row[1])}

    def _asset_content(self, asset_version_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                WHERE version.asset_version_id = %s AND asset.project_id = %s
                """,
                [asset_version_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("ASSET_VERSION_NOT_FOUND", "Canon proposal AssetVersion is missing")
        return dict(row[0])

    def _active_attempt(self, operation_id: str, project_id: str) -> dict[str, str] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT attempt.attempt_id, attempt.status
                FROM authority_attempt AS attempt
                JOIN authority_operation AS operation
                  ON operation.operation_id = attempt.operation_id
                WHERE attempt.operation_id = %s AND operation.project_id = %s
                  AND attempt.status IN ('CREATED','QUEUED','LEASED','RUNNING','CHECKPOINTED','RESULT_SUBMITTED')
                ORDER BY attempt.attempt_number DESC LIMIT 1
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        return None if row is None else {"attempt_id": str(row[0]), "status": str(row[1])}

    def _request_from_root(self, root: dict[str, Any]) -> SingleChapterRequest:
        payload = dict(root["command_payload"] or {})
        snapshot = dict(root["definition_snapshot"] or {})
        return SingleChapterRequest(
            project_id=str(root["project_id"]),
            workspace_id=str(root["workspace_id"]),
            actor_id=str(root["actor_id"]),
            chapter=int(payload["chapter"]),
            title=str(payload.get("title") or ""),
            premise=str(payload.get("premise") or ""),
            trace_id=str(root["trace_id"]),
            correlation_id=str(root["correlation_id"]),
            application_build_id=str(snapshot["application_build_id"]),
            commit_sha=str(snapshot["commit_sha"]),
            context_candidates=tuple(payload.get("context_candidates") or ()),
            context_version_refs=dict(payload.get("context_version_refs") or {}),
            context_token_budget=int(payload.get("context_token_budget") or 6000),
            preparation_report=dict(payload.get("preparation_report") or {}),
            idempotency_key=str(payload.get("chapter_idempotency_key") or ""),
        )

    def _operation_status(self, operation_id: str, project_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(operation_id, project_id)
        return str(state["status"])


__all__ = ["ChapterAuthorityScheduler", "ChapterSchedulerTick"]
