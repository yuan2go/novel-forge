from __future__ import annotations

from collections.abc import Callable
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
    _measurement_evidence_inputs,
    _retrieval_admission_snapshot,
)
from novel_forge.modules.chapter_authority.runtime import execute_chapter_handler
from novel_forge.modules.chapter_authority.model_effects import (
    MODEL_CAPABILITY_STAGES,
    ChapterAgentBindingRecorder,
)
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
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectRecoveryDisposition,
    EffectCommandContext,
    classify_external_effect_recovery,
    reconcile_external_effect,
    resume_operation_from_completed_effect,
)
from novel_forge.modules.command_kernel.cancellation import (
    acknowledge_worker_cancellation,
)
from novel_forge.modules.canon_graph.approval_authority import (
    advance_canon_reextraction,
    CanonApprovalContext,
    decision_asset_versions,
    ensure_canon_approval_requests,
    pending_canon_reextraction,
)
from novel_forge.modules.command_kernel.deadline_runtime import (
    probe_operation_execution,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    register_saga_step,
    terminalize_saga_from_extension,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction
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

    def __init__(
        self,
        database_url: str,
        *,
        registry: ChapterHandlerRegistry,
        object_store_adapter: ExternalEffectAdapter,
        worker_id: str,
        permissions: frozenset[str],
        lease_seconds: int = 30,
        agent_binding_recorder: ChapterAgentBindingRecorder | None = None,
        fault_injector: Callable[[str], None] | None = None,
        model_effect_adapter: ExternalEffectAdapter | None = None,
    ) -> None:
        if not worker_id or lease_seconds <= 0:
            raise ValueError(
                "configured worker identity and positive lease are required"
            )
        self.database_url = database_url
        self.registry = registry
        self.object_store_adapter = object_store_adapter
        self.worker_id = worker_id
        self.permissions = permissions
        self.lease_seconds = lease_seconds
        self.agent_binding_recorder = agent_binding_recorder
        self.fault_injector = fault_injector or (lambda _checkpoint: None)
        self.model_effect_adapter = model_effect_adapter

    def tick(self, *, project_id: str, root_operation_id: str) -> ChapterSchedulerTick:
        root, saga, children = self._graph_state(project_id, root_operation_id)
        context = GraphCommandContext(
            project_id=project_id,
            actor_id=self.worker_id,
            trace_id=root["trace_id"],
            correlation_id=root["correlation_id"],
        )
        coordinated = coordinate_saga(self.database_url, context, saga["saga_id"])
        chapter_complete = all(
            children.get(node, {}).get("status") == "SUCCEEDED" for node in ChapterNode
        )
        if (coordinated["status"] == "SUCCEEDED" and chapter_complete) or coordinated[
            "status"
        ] in {
            "FAILED_FINAL",
            "DEAD_LETTER",
            "MANUAL_INTERVENTION",
            "CANCELLED",
            "COMPENSATED",
            "COMPENSATION_FAILED",
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
        reextraction_tick = self._advance_reextraction(
            request=request,
            root=root,
            saga=saga,
            children=children,
        )
        if reextraction_tick is not None:
            return reextraction_tick
        correction_tick = self._advance_quality_correction(
            request=request,
            root=root,
            saga=saga,
            children=children,
        )
        if correction_tick is not None:
            return correction_tick
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
            proposal = self._asset_content(proposal_ref["asset_version_id"], project_id)
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

    def _advance_quality_correction(
        self,
        *,
        request: SingleChapterRequest,
        root: dict[str, Any],
        saga: dict[str, Any],
        children: dict[ChapterNode, dict[str, Any]],
    ) -> ChapterSchedulerTick | None:
        root_key = request.idempotency_key or (
            f"{request.project_id}:chapter:{request.chapter}:root"
        )
        initial_quality = self._initial_operation(
            root_operation_id=str(root["operation_id"]),
            project_id=request.project_id,
            node=ChapterNode.QUALITY,
            idempotency_key=f"{root_key}:{ChapterNode.QUALITY.value}",
        )
        if initial_quality is None or initial_quality["status"] != "SUCCEEDED":
            return None
        tasks = self._operation_outputs(
            str(initial_quality["operation_id"]),
            request.project_id,
            role="required_action",
        )
        if not tasks:
            return None
        generation = 1
        correction = self._correction_operations(
            root_operation_id=str(root["operation_id"]),
            project_id=request.project_id,
            generation=generation,
            root_idempotency_key=root_key,
        )
        aggregate = correction.get(ChapterNode.QUALITY)
        if aggregate is not None and aggregate["status"] == "SUCCEEDED":
            children.update(correction)
            return None

        common = {
            ChapterNode.PLAN: self._initial_primary(root, request, ChapterNode.PLAN),
            ChapterNode.CONTEXT: self._initial_primary(
                root, request, ChapterNode.CONTEXT
            ),
            ChapterNode.DRAFT: self._initial_primary(root, request, ChapterNode.DRAFT),
            ChapterNode.REVIEW: self._initial_primary(
                root, request, ChapterNode.REVIEW
            ),
            ChapterNode.BEST_CANDIDATE: self._initial_primary(
                root, request, ChapterNode.BEST_CANDIDATE
            ),
        }
        sequence = (
            ChapterNode.REVISION,
            ChapterNode.REREVIEW,
            ChapterNode.BEST_CANDIDATE,
            ChapterNode.CANON_EXTRACTION,
            ChapterNode.CANON_PROPOSAL,
            ChapterNode.CANON,
            *QUALITY_GROUP_NODES,
            ChapterNode.QUALITY,
        )
        for ordinal, node in enumerate(sequence, start=1):
            operation = correction.get(node)
            if operation is not None and operation["status"] == "SUCCEEDED":
                continue
            if operation is not None and operation["status"] in {
                "FAILED_FINAL",
                "DEAD_LETTER",
                "CANCELLED",
            }:
                return self._terminal_quality_correction(root, saga, operation, node)
            if operation is None:
                inputs, dependencies = self._quality_correction_inputs(
                    request=request,
                    root=root,
                    node=node,
                    initial_quality=initial_quality,
                    tasks=tasks,
                    correction=correction,
                    common=common,
                )
                if node is ChapterNode.CANON:
                    proposal = correction[ChapterNode.CANON_PROPOSAL]
                    proposal_ref = self._primary_output(
                        str(proposal["operation_id"]), request.project_id
                    )
                    gate = ensure_canon_approval_requests(
                        self.database_url,
                        CanonApprovalContext(
                            project_id=request.project_id,
                            principal_id=self.worker_id,
                            trace_id=str(root["trace_id"]),
                            correlation_id=str(root["correlation_id"]),
                        ),
                        root_operation_id=str(root["operation_id"]),
                        saga_id=str(saga["saga_id"]),
                        proposal_asset_version_id=proposal_ref["asset_version_id"],
                        proposal=self._asset_content(
                            proposal_ref["asset_version_id"], request.project_id
                        ),
                    )
                    if gate["waiting"]:
                        return self._generation_tick(
                            root,
                            saga,
                            proposal,
                            ChapterNode.CANON,
                            "quality_correction_canon_gate",
                        )
                    inputs.extend(
                        decision_asset_versions(
                            self.database_url,
                            project_id=request.project_id,
                            root_operation_id=str(root["operation_id"]),
                        )
                    )
                operation = self._admit_node(
                    request=request,
                    root=root,
                    saga_id=str(saga["saga_id"]),
                    children=children,
                    node=node,
                    idempotency_suffix=f":quality-correction:{generation}",
                    register_step=False,
                    explicit_inputs=inputs,
                    dependency_operation_ids=dependencies,
                    input_overrides=(
                        {"correction_generation": generation}
                        if node is ChapterNode.BEST_CANDIDATE
                        else None
                    ),
                    timeline_step_key=f"quality-correction:{generation}:{node.value}",
                    timeline_ordinal=2000 + ordinal,
                    activate_immediately=True,
                )
                correction[node] = operation
            try:
                recovery = self._execute_node(request, node, operation)
            except Exception:
                current = self._child(
                    str(operation["operation_id"]), request.project_id
                )
                if current["status"] in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
                    return self._terminal_quality_correction(root, saga, current, node)
                raise
            current = self._child(str(operation["operation_id"]), request.project_id)
            if current["status"] in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}:
                return self._terminal_quality_correction(root, saga, current, node)
            final = coordinate_saga(
                self.database_url,
                GraphCommandContext(
                    project_id=request.project_id,
                    actor_id=self.worker_id,
                    trace_id=str(root["trace_id"]),
                    correlation_id=str(root["correlation_id"]),
                ),
                str(saga["saga_id"]),
            )
            return ChapterSchedulerTick(
                root_operation_id=str(root["operation_id"]),
                saga_id=str(saga["saga_id"]),
                saga_status=str(final["status"]),
                operation_id=str(operation["operation_id"]),
                node=node.value,
                operation_status=self._operation_status(
                    str(operation["operation_id"]), request.project_id
                ),
                recovery_mode=f"quality_correction_{recovery}",
            )
        return None

    def _terminal_quality_correction(
        self,
        root: dict[str, Any],
        saga: dict[str, Any],
        operation: dict[str, Any],
        node: ChapterNode,
    ) -> ChapterSchedulerTick:
        terminal = terminalize_saga_from_extension(
            self.database_url,
            GraphCommandContext(
                project_id=str(root["project_id"]),
                actor_id=self.worker_id,
                trace_id=str(root["trace_id"]),
                correlation_id=str(root["correlation_id"]),
                causation_id=str(operation["operation_id"]),
            ),
            str(saga["saga_id"]),
            operation_id=str(operation["operation_id"]),
        )
        return ChapterSchedulerTick(
            root_operation_id=str(root["operation_id"]),
            saga_id=str(saga["saga_id"]),
            saga_status=str(terminal["saga_status"]),
            operation_id=str(operation["operation_id"]),
            node=node.value,
            operation_status=str(operation["status"]),
            recovery_mode="quality_correction_terminal_replay",
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
                    'SUCCEEDED', 'COMPENSATED', 'COMPENSATION_FAILED',
                    'MANUAL_INTERVENTION', 'CANCELLED'
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
        # INVARIANT: coordinate_saga should have made the Saga terminal after all children succeeded.
        raise KernelError(
            "CHAPTER_SAGA_COORDINATION_LAG", "completed graph is not terminal"
        )

    def _admit_node(
        self,
        *,
        request: SingleChapterRequest,
        root: dict[str, Any],
        saga_id: str,
        children: dict[ChapterNode, dict[str, Any]],
        node: ChapterNode,
        idempotency_suffix: str = "",
        register_step: bool = True,
        input_overrides: dict[str, Any] | None = None,
        explicit_inputs: list[dict[str, str]] | None = None,
        dependency_operation_ids: list[str] | None = None,
        timeline_step_key: str = "",
        timeline_ordinal: int = 0,
        activate_immediately: bool = False,
    ) -> dict[str, Any]:
        inputs: list[dict[str, str]] = []
        effective_overrides = dict(input_overrides or {})
        for source in _input_nodes(node):
            source_operation = children.get(source)
            if source_operation is None or source_operation["status"] != "SUCCEEDED":
                raise KernelError(
                    "CHAPTER_INPUT_NOT_COMPLETE",
                    f"{node.value} input {source.value} has not completed",
                )
            if source is ChapterNode.REREVIEW and node is not ChapterNode.BEST_CANDIDATE:
                inputs.append(self._output_by_key(
                    str(children[ChapterNode.BEST_CANDIDATE]["operation_id"]),
                    root["project_id"], "chapter.best_candidate.selected_review",
                ))
            else:
                inputs.append(self._primary_output(str(source_operation["operation_id"]), root["project_id"]))
            if node is ChapterNode.CONTEXT and source is ChapterNode.PLAN:
                inputs.append(
                    self._output_by_key(
                        str(source_operation["operation_id"]),
                        root["project_id"],
                        "chapter.production_input_manifest",
                    )
                )
        if node is ChapterNode.RETRIEVAL:
            extra_inputs, snapshot = _retrieval_admission_snapshot(
                self.database_url,
                request=request,
                plan_asset_version_id=self._primary_output(
                    str(children[ChapterNode.PLAN]["operation_id"]),
                    root["project_id"],
                )["asset_version_id"],
                intent_asset_version_id=self._primary_output(
                    str(children[ChapterNode.EXECUTION_INTENT]["operation_id"]),
                    root["project_id"],
                )["asset_version_id"],
                memo_asset_version_id=self._primary_output(
                    str(children[ChapterNode.MEMO]["operation_id"]),
                    root["project_id"],
                )["asset_version_id"],
                semantic_provider_bound=self.registry.semantic_retrieval_available,
            )
            inputs.extend(extra_inputs)
            effective_overrides["retrieval_snapshot"] = snapshot
        if node in {ChapterNode.EXECUTION_INTENT, ChapterNode.CONTEXT}:
            candidates = request.context_candidates
            if node is ChapterNode.EXECUTION_INTENT:
                candidates = tuple(
                    item
                    for item in candidates
                    if str(item.get("asset_type") or "")
                    in {"story_state_snapshot", "canon_snapshot"}
                )
            else:
                # WHY: The typed PLAN output is the exact authoritative execution
                # plan.  The original planning candidate may remain in the
                # root input snapshot for lineage, but cannot become a second
                # chapter_plan input to Context compilation.
                candidates = tuple(
                    item
                    for item in candidates
                    if str(item.get("asset_type") or "") != "chapter_plan"
                )
                retrieval_ref = self._primary_output(
                    str(children[ChapterNode.RETRIEVAL]["operation_id"]),
                    root["project_id"],
                )
                retrieval = self._asset_content(
                    retrieval_ref["asset_version_id"], root["project_id"]
                )
                inputs.extend(
                    {
                        "asset_version_id": str(item["asset_version_id"]),
                        "content_hash": str(item["content_hash"]),
                    }
                    for item in retrieval.get("selected_source_asset_versions", ())
                )
            inputs.extend(
                {
                    "asset_version_id": str(item["asset_version_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in candidates
            )
        if node is ChapterNode.QUALITY:
            context_operation = children[ChapterNode.CONTEXT]
            context_output = self._primary_output(
                str(context_operation["operation_id"]), root["project_id"]
            )
            inputs.extend(
                _measurement_evidence_inputs(
                    self.database_url,
                    project_id=root["project_id"],
                    root_operation_id=str(root["operation_id"]),
                    context_bundle_asset_version_id=context_output["asset_version_id"],
                )
            )
        if node is ChapterNode.CANON:
            inputs.extend(
                decision_asset_versions(
                    self.database_url,
                    project_id=root["project_id"],
                    root_operation_id=str(root["operation_id"]),
                )
            )
        if explicit_inputs is not None:
            inputs = list(explicit_inputs)
        inputs = list(
            {str(item["asset_version_id"]): dict(item) for item in inputs}.values()
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
        dependency_ids = [str(children[item]["operation_id"]) for item in dependencies]
        if dependency_operation_ids is not None:
            dependency_ids = list(dependency_operation_ids)
        previous_id = dependency_ids[-1] if dependency_ids else root["operation_id"]
        admitted = admit_command(
            self.database_url,
            _command(
                request,
                definition_name=node.definition_name,
                idempotency_key=f"{root_key}:{node.value}{idempotency_suffix}",
                input_assets=inputs,
                root_operation_id=root["operation_id"],
                parent_operation_id=root["operation_id"],
                causation_operation_id=previous_id,
                definition_version=root["definition_version"],
                input_overrides=effective_overrides,
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
        if register_step:
            register_saga_step(
                self.database_url,
                graph_context,
                saga_id,
                operation_id,
                timeline_step_key or node.value,
                timeline_ordinal or list(ChapterNode).index(node) + 1,
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
        if not register_step or activate_immediately:
            with AuthorityUnitOfWork(self.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(
                    operation_id, root["project_id"]
                )
            if state["status"] == "ADMITTED":
                transition_operation(
                    self.database_url,
                    OperationTransitionCommand(
                        operation_id=operation_id,
                        project_id=root["project_id"],
                        expected_version=int(state["version"]),
                        expected_status="ADMITTED",
                        target_status="READY",
                        actor_id=self.worker_id,
                        reason=(
                            "additional governed Chapter generation dependencies "
                            "are satisfied"
                        ),
                        trace_id=root["trace_id"],
                        correlation_id=root["correlation_id"],
                        causation_id=root["operation_id"],
                    ),
                )
        return self._child(operation_id, root["project_id"])

    def _quality_correction_inputs(
        self,
        *,
        request: SingleChapterRequest,
        root: dict[str, Any],
        node: ChapterNode,
        initial_quality: dict[str, Any],
        tasks: list[dict[str, str]],
        correction: dict[ChapterNode, dict[str, Any]],
        common: dict[ChapterNode, dict[str, str]],
    ) -> tuple[list[dict[str, str]], list[str]]:
        quality_ref = self._primary_output(
            str(initial_quality["operation_id"]), request.project_id
        )
        if node is ChapterNode.REVISION:
            return (
                [
                    common[ChapterNode.BEST_CANDIDATE],
                    quality_ref,
                    common[ChapterNode.CONTEXT],
                    *tasks,
                ],
                [str(initial_quality["operation_id"])],
            )
        revision_operation = correction[ChapterNode.REVISION]
        revision_ref = self._primary_output(
            str(revision_operation["operation_id"]), request.project_id
        )
        if node is ChapterNode.REREVIEW:
            return (
                [
                    common[ChapterNode.DRAFT],
                    common[ChapterNode.REVIEW],
                    revision_ref,
                    common[ChapterNode.CONTEXT],
                ],
                [str(revision_operation["operation_id"])],
            )
        rereview_operation = correction[ChapterNode.REREVIEW]
        rereview_ref = self._primary_output(
            str(rereview_operation["operation_id"]), request.project_id
        )
        if node is ChapterNode.BEST_CANDIDATE:
            return (
                [
                    common[ChapterNode.BEST_CANDIDATE],
                    revision_ref,
                    rereview_ref,
                    quality_ref,
                    *tasks,
                ],
                [str(rereview_operation["operation_id"])],
            )
        best_operation = correction[ChapterNode.BEST_CANDIDATE]
        best_ref = self._primary_output(
            str(best_operation["operation_id"]), request.project_id
        )
        if node is ChapterNode.CANON_EXTRACTION:
            return (
                [
                    best_ref,
                    rereview_ref,
                    common[ChapterNode.CONTEXT],
                ],
                [str(best_operation["operation_id"])],
            )
        extraction_operation = correction[ChapterNode.CANON_EXTRACTION]
        extraction_ref = self._primary_output(
            str(extraction_operation["operation_id"]), request.project_id
        )
        if node is ChapterNode.CANON_PROPOSAL:
            return (
                [extraction_ref],
                [str(extraction_operation["operation_id"])],
            )
        proposal_operation = correction[ChapterNode.CANON_PROPOSAL]
        proposal_ref = self._primary_output(
            str(proposal_operation["operation_id"]), request.project_id
        )
        if node is ChapterNode.CANON:
            return (
                [
                    best_ref,
                    rereview_ref,
                    extraction_ref,
                    proposal_ref,
                    common[ChapterNode.CONTEXT],
                ],
                [str(proposal_operation["operation_id"])],
            )
        canon_operation = correction[ChapterNode.CANON]
        canon_ref = self._primary_output(
            str(canon_operation["operation_id"]), request.project_id
        )
        if node in QUALITY_GROUP_NODES:
            return (
                [
                    common[ChapterNode.PLAN],
                    best_ref,
                    rereview_ref,
                    canon_ref,
                    common[ChapterNode.CONTEXT],
                ],
                [str(canon_operation["operation_id"])],
            )
        group_refs = [
            self._primary_output(
                str(correction[group]["operation_id"]), request.project_id
            )
            for group in QUALITY_GROUP_NODES
        ]
        measurement = _measurement_evidence_inputs(
            self.database_url,
            project_id=request.project_id,
            root_operation_id=str(root["operation_id"]),
            context_bundle_asset_version_id=common[ChapterNode.CONTEXT][
                "asset_version_id"
            ],
        )
        return (
            [
                common[ChapterNode.PLAN],
                best_ref,
                revision_ref,
                rereview_ref,
                canon_ref,
                common[ChapterNode.CONTEXT],
                *group_refs,
                *tasks,
                *measurement,
            ],
            [str(correction[group]["operation_id"]) for group in QUALITY_GROUP_NODES],
        )

    def _initial_primary(
        self,
        root: dict[str, Any],
        request: SingleChapterRequest,
        node: ChapterNode,
    ) -> dict[str, str]:
        root_key = request.idempotency_key or (
            f"{request.project_id}:chapter:{request.chapter}:root"
        )
        operation = self._initial_operation(
            root_operation_id=str(root["operation_id"]),
            project_id=request.project_id,
            node=node,
            idempotency_key=f"{root_key}:{node.value}",
        )
        if operation is None or operation["status"] != "SUCCEEDED":
            raise KernelError(
                "QUALITY_CORRECTION_INPUT_MISSING",
                f"Quality correction requires completed initial {node.value}",
            )
        return self._primary_output(str(operation["operation_id"]), request.project_id)

    def _initial_operation(
        self,
        *,
        root_operation_id: str,
        project_id: str,
        node: ChapterNode,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, status,
                       COALESCE(
                         (definition_snapshot->'retry_policy'->>'max_attempts')::int,
                         1
                       )
                FROM authority_operation
                WHERE root_operation_id=%s AND project_id=%s
                  AND definition_name=%s
                  AND idempotency_key=%s
                LIMIT 1
                """,
                [
                    root_operation_id,
                    project_id,
                    node.definition_name,
                    idempotency_key,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return dict(
            zip(
                ("operation_id", "definition_name", "status", "max_attempts"),
                row,
                strict=True,
            )
        )

    def _correction_operations(
        self,
        *,
        root_operation_id: str,
        project_id: str,
        generation: int,
        root_idempotency_key: str,
    ) -> dict[ChapterNode, dict[str, Any]]:
        expected_keys = [
            f"{root_idempotency_key}:{node.value}:quality-correction:{generation}"
            for node in ChapterNode
        ]
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, status,
                       COALESCE(
                         (definition_snapshot->'retry_policy'->>'max_attempts')::int,
                         1
                       )
                FROM authority_operation
                WHERE root_operation_id=%s AND project_id=%s
                  AND idempotency_key=ANY(%s)
                ORDER BY created_at, operation_id
                """,
                [root_operation_id, project_id, expected_keys],
            )
            rows = uow.cursor.fetchall()
        by_definition = {node.definition_name: node for node in ChapterNode}
        return {
            by_definition[str(row[1])]: dict(
                zip(
                    ("operation_id", "definition_name", "status", "max_attempts"),
                    row,
                    strict=True,
                )
            )
            for row in rows
            if str(row[1]) in by_definition
        }

    def _operation_outputs(
        self, operation_id: str, project_id: str, *, role: str
    ) -> list[dict[str, str]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_version_id, binding.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_operation AS operation
                  ON operation.operation_id=binding.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=binding.asset_version_id
                WHERE binding.operation_id=%s AND operation.project_id=%s
                  AND binding.role=%s
                  AND version.lifecycle='ACTIVE'
                ORDER BY binding.output_key
                """,
                [operation_id, project_id, role],
            )
            return [
                {"asset_version_id": str(row[0]), "content_hash": str(row[1])}
                for row in uow.cursor.fetchall()
            ]

    def _advance_reextraction(
        self,
        *,
        request: SingleChapterRequest,
        root: dict[str, Any],
        saga: dict[str, Any],
        children: dict[ChapterNode, dict[str, Any]],
    ) -> ChapterSchedulerTick | None:
        generation = pending_canon_reextraction(
            self.database_url,
            project_id=request.project_id,
            root_operation_id=str(root["operation_id"]),
        )
        if generation is None or generation["status"] in {
            "WAITING_APPROVAL",
            "WAITING_OPERATOR",
        }:
            return None
        context = CanonApprovalContext(
            project_id=request.project_id,
            principal_id=self.worker_id,
            trace_id=str(root["trace_id"]),
            correlation_id=str(root["correlation_id"]),
        )
        generation_id = str(generation["reextraction_generation_id"])
        number = int(generation["generation"])
        if generation["status"] == "REEXTRACTION_PENDING":
            operation = self._admit_node(
                request=request,
                root=root,
                saga_id=str(saga["saga_id"]),
                children=children,
                node=ChapterNode.CANON_EXTRACTION,
                idempotency_suffix=f":generation:{number}",
                input_overrides={"canon_reextraction_generation": number},
                timeline_step_key=f"canon_extraction:g{number}",
                timeline_ordinal=1000 + number * 2,
                activate_immediately=True,
            )
            advance_canon_reextraction(
                self.database_url,
                context,
                generation_id=generation_id,
                expected_status="REEXTRACTION_PENDING",
                target_status="EXTRACTION_RUNNING",
                extraction_operation_id=str(operation["operation_id"]),
            )
            return self._generation_tick(
                root,
                saga,
                operation,
                ChapterNode.CANON_EXTRACTION,
                "reextraction_admitted",
            )
        if generation["status"] == "EXTRACTION_RUNNING":
            operation = self._child(
                str(generation["extraction_operation_id"]), request.project_id
            )
            if operation["status"] != "SUCCEEDED":
                recovery = self._execute_node(
                    request, ChapterNode.CANON_EXTRACTION, operation
                )
                operation = self._child(
                    str(operation["operation_id"]), request.project_id
                )
                return self._generation_tick(
                    root, saga, operation, ChapterNode.CANON_EXTRACTION, recovery
                )
            output = self._primary_output(
                str(operation["operation_id"]), request.project_id
            )
            advance_canon_reextraction(
                self.database_url,
                context,
                generation_id=generation_id,
                expected_status="EXTRACTION_RUNNING",
                target_status="PROPOSAL_PENDING",
                extraction_asset_version_id=output["asset_version_id"],
            )
            return self._generation_tick(
                root,
                saga,
                operation,
                ChapterNode.CANON_EXTRACTION,
                "reextraction_completed",
            )
        if generation["status"] == "PROPOSAL_PENDING":
            _, _, refreshed = self._graph_state(
                request.project_id, str(root["operation_id"])
            )
            operation = self._admit_node(
                request=request,
                root=root,
                saga_id=str(saga["saga_id"]),
                children=refreshed,
                node=ChapterNode.CANON_PROPOSAL,
                idempotency_suffix=f":generation:{number}",
                input_overrides={
                    "canon_reextraction_generation": number,
                    "supersedes_proposal_asset_version_id": generation[
                        "supersedes_proposal_asset_version_id"
                    ],
                },
                explicit_inputs=[
                    self._primary_output(
                        str(generation["extraction_operation_id"]), request.project_id
                    )
                ],
                dependency_operation_ids=[str(generation["extraction_operation_id"])],
                timeline_step_key=f"canon_proposal:g{number}",
                timeline_ordinal=1001 + number * 2,
                activate_immediately=True,
            )
            advance_canon_reextraction(
                self.database_url,
                context,
                generation_id=generation_id,
                expected_status="PROPOSAL_PENDING",
                target_status="PROPOSAL_RUNNING",
                proposal_operation_id=str(operation["operation_id"]),
            )
            return self._generation_tick(
                root, saga, operation, ChapterNode.CANON_PROPOSAL, "reproposal_admitted"
            )
        if generation["status"] == "PROPOSAL_RUNNING":
            operation = self._child(
                str(generation["proposal_operation_id"]), request.project_id
            )
            if operation["status"] != "SUCCEEDED":
                recovery = self._execute_node(
                    request, ChapterNode.CANON_PROPOSAL, operation
                )
                operation = self._child(
                    str(operation["operation_id"]), request.project_id
                )
                return self._generation_tick(
                    root, saga, operation, ChapterNode.CANON_PROPOSAL, recovery
                )
            output = self._primary_output(
                str(operation["operation_id"]), request.project_id
            )
            proposal = self._asset_content(
                output["asset_version_id"], request.project_id
            )
            progress_status = advance_canon_reextraction(
                self.database_url,
                context,
                generation_id=generation_id,
                expected_status="PROPOSAL_RUNNING",
                target_status="WAITING_APPROVAL",
                proposal_asset_version_id=output["asset_version_id"],
            )
            if progress_status == "WAITING_OPERATOR":
                return self._generation_tick(
                    root,
                    saga,
                    operation,
                    ChapterNode.CANON_PROPOSAL,
                    "reproposal_waiting_operator",
                )
            ensure_canon_approval_requests(
                self.database_url,
                context,
                root_operation_id=str(root["operation_id"]),
                saga_id=str(saga["saga_id"]),
                proposal_asset_version_id=output["asset_version_id"],
                proposal=proposal,
            )
            return self._generation_tick(
                root,
                saga,
                operation,
                ChapterNode.CANON_PROPOSAL,
                "reproposal_waiting_gate",
            )
        raise KernelError(
            "CANON_REEXTRACTION_STATE_CONFLICT", "unknown re-extraction state"
        )

    @staticmethod
    def _generation_tick(
        root: dict[str, Any],
        saga: dict[str, Any],
        operation: dict[str, Any],
        node: ChapterNode,
        recovery: str,
    ) -> ChapterSchedulerTick:
        return ChapterSchedulerTick(
            root_operation_id=str(root["operation_id"]),
            saga_id=str(saga["saga_id"]),
            saga_status="WAITING_GATE",
            operation_id=str(operation["operation_id"]),
            node=node.value,
            operation_status=str(operation["status"]),
            recovery_mode=recovery,
        )

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
            recovery_mode = (
                "retry_attempt"
                if operation["status"] == "FAILED_RETRYABLE"
                else recovery_mode
            )
            created = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=int(operation["max_attempts"]),
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
            if created["dead_letter"] or created["attempt_id"] is None:
                raise KernelError(
                    "CHAPTER_ATTEMPT_EXHAUSTED", "chapter Attempt policy is exhausted"
                )
            attempt_id = str(created["attempt_id"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
            attempt_status = "QUEUED"
        elif (
            operation["status"]
            in {
                "EXECUTING",
                "WAITING_EXTERNAL_RESULT",
                "RECONCILIATION_REQUIRED",
                "CANCELLATION_REQUESTED",
            }
            and active is not None
        ):
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
            if operation["status"] == "CANCELLATION_REQUESTED":
                raise KernelError(
                    "CHAPTER_OPERATION_CANCELLED",
                    "Chapter correction was cancelled before recovery execution",
                )
            if (
                operation["status"]
                in {"WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"}
                and node.value in MODEL_CAPABILITY_STAGES
            ):
                recovery_mode = self._reconcile_agent_effects(
                    request,
                    operation,
                    worker=worker,
                )
                recovered = self._child(operation_id, project_id)
                if recovered["status"] == "RECONCILIATION_REQUIRED":
                    checkpoint_attempt_for_external_reconciliation(
                        self.database_url,
                        worker,
                        {
                            "reason": "provider_query_remains_ambiguous",
                            "recovery_mode": recovery_mode,
                        },
                    )
                    return recovery_mode
                if recovered["status"] in {
                    "FAILED_RETRYABLE",
                    "FAILED_FINAL",
                    "CANCELLED",
                    "DEAD_LETTER",
                }:
                    return recovery_mode
            with LeaseHeartbeatGuard(
                lambda: heartbeat_attempt(
                    self.database_url, worker, self.lease_seconds
                ),
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
                    execution_probe=lambda: probe_operation_execution(
                        self.database_url,
                        operation_id=operation_id,
                        project_id=project_id,
                    ),
                )
                self.fault_injector("after_domain_asset_materialized")
                if (
                    self.agent_binding_recorder is not None
                    and node.value in MODEL_CAPABILITY_STAGES
                ):
                    self.agent_binding_recorder.finalize_domain_commit(
                        project_id=project_id,
                        operation_id=operation_id,
                        attempt_id=attempt_id,
                        fencing_token=worker.fencing_token,
                        asset_version_id=output.asset_version_id,
                        content_hash=output.content_hash,
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
                state = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
            self.fault_injector("before_attempt_result_submission")
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
        except Exception as exc:
            classification = WorkerFailureClassifier.classify(exc)
            if (
                self.agent_binding_recorder is not None
                and isinstance(exc, KernelError)
                and _is_domain_validation_failure(exc.code)
                and node.value in MODEL_CAPABILITY_STAGES
            ):
                self.agent_binding_recorder.record_domain_rejection(
                    project_id=project_id,
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    error_code=exc.code,
                )
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
                        "error_code": exc.code
                        if isinstance(exc, KernelError)
                        else "UNKNOWN",
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
                    error_code=exc.code
                    if isinstance(exc, KernelError)
                    else "PROGRAMMING_BUG",
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
                       trace_id, correlation_id, idempotency_key
                FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                  AND root_operation_id = operation_id
                """,
                [root_operation_id, project_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "CHAPTER_RUN_NOT_FOUND", "Chapter root Operation is missing"
                )
            root = dict(
                zip(
                    (
                        "operation_id",
                        "project_id",
                        "workspace_id",
                        "actor_id",
                        "status",
                        "definition_version",
                        "definition_snapshot",
                        "command_payload",
                        "trace_id",
                        "correlation_id",
                        "idempotency_key",
                    ),
                    row,
                    strict=True,
                )
            )
            initial_child_keys = [
                f"{root['idempotency_key']}:{node.value}" for node in ChapterNode
            ]
            uow.cursor.execute(
                "SELECT saga_id, status FROM authority_saga WHERE root_operation_id = %s AND project_id = %s",
                [root_operation_id, project_id],
            )
            saga_row = uow.cursor.fetchone()
            if saga_row is None:
                raise KernelError(
                    "CHAPTER_SAGA_MISSING", "Chapter root has no durable Saga"
                )
            uow.cursor.execute(
                """
                SELECT operation_id, definition_name, status,
                       COALESCE((definition_snapshot->'retry_policy'->>'max_attempts')::int, 1)
                FROM authority_operation
                WHERE root_operation_id = %s AND operation_id <> %s AND project_id = %s
                  AND idempotency_key=ANY(%s)
                ORDER BY created_at, operation_id
                """,
                [
                    root_operation_id,
                    root_operation_id,
                    project_id,
                    initial_child_keys,
                ],
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
            "operation_id": row[0],
            "definition_name": row[1],
            "status": row[2],
            "max_attempts": row[3],
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
            raise KernelError(
                "CHAPTER_INPUT_OUTPUT_MISSING",
                "completed predecessor has no primary output",
            )
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
            raise KernelError(
                "ASSET_VERSION_NOT_FOUND", "Canon proposal AssetVersion is missing"
            )
        return dict(row[0])

    def _active_attempt(
        self, operation_id: str, project_id: str
    ) -> dict[str, str] | None:
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
        return (
            None if row is None else {"attempt_id": str(row[0]), "status": str(row[1])}
        )

    def _request_from_root(self, root: dict[str, Any]) -> SingleChapterRequest:
        payload = dict(root["command_payload"] or {})
        snapshot = dict(root["definition_snapshot"] or {})
        return SingleChapterRequest(
            project_id=str(root["project_id"]),
            workspace_id=str(root["workspace_id"]),
            book_id=str(payload.get("book_id") or ""),
            actor_id=str(root["actor_id"]),
            chapter=int(payload["chapter"]),
            title=str(payload.get("title") or ""),
            premise=str(payload.get("premise") or ""),
            trace_id=str(root["trace_id"]),
            correlation_id=str(root["correlation_id"]),
            application_build_id=str(snapshot["application_build_id"]),
            commit_sha=str(snapshot["commit_sha"]),
            chapter_plan_asset_version_id=str(
                payload.get("chapter_plan_asset_version_id") or ""
            ),
            chapter_plan_content_hash=str(
                payload.get("chapter_plan_content_hash") or ""
            ),
            context_candidates=tuple(payload.get("context_candidates") or ()),
            context_version_refs=dict(payload.get("context_version_refs") or {}),
            context_token_budget=int(payload.get("context_token_budget") or 6000),
            preparation_report=dict(payload.get("preparation_report") or {}),
            idempotency_key=str(payload.get("chapter_idempotency_key") or ""),
        )

    def _operation_status(self, operation_id: str, project_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        return str(state["status"])

    def _reconcile_agent_effects(
        self,
        request: SingleChapterRequest,
        operation: dict[str, Any],
        *,
        worker: WorkerLeaseCommand,
    ) -> str:
        if self.model_effect_adapter is None:
            raise KernelError(
                "CHAPTER_AGENT_RECONCILER_MISSING",
                "Agent-bound Chapter recovery requires its model effect adapter",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT external_effect_id, status, request_payload
                FROM authority_external_effect
                WHERE operation_id=%s
                  AND effect_type='model.invoke'
                ORDER BY created_at, external_effect_id
                """,
                [operation["operation_id"]],
            )
            effects = tuple(uow.cursor.fetchall())
        if not effects:
            raise KernelError(
                "CHAPTER_AGENT_RECONCILIATION_EVIDENCE_MISSING",
                "reconciliation-required Chapter Operation has no uncertain ExternalEffect",
            )
        context = EffectCommandContext(
            operation_id=str(operation["operation_id"]),
            project_id=request.project_id,
            actor_id=self.worker_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        outcomes = []
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
                    "CHAPTER_EXECUTION_IDENTITY_INVALID",
                    "uncertain ExternalEffect has no frozen execution identity",
                )
            execution_fence = int(metadata.get("fencing_token") or 0)
            attempt_id = str(metadata.get("attempt_id") or "")
            if attempt_id != worker.attempt_id:
                continue
            matched_attempt = True
            if execution_fence <= 0:
                raise KernelError(
                    "CHAPTER_EXECUTION_IDENTITY_CONFLICT",
                    "uncertain ExternalEffect differs from the active Attempt",
                )
            disposition = classify_external_effect_recovery(str(effect_status))
            if disposition is EffectRecoveryDisposition.DISPATCH_PLANNED:
                continue
            if disposition is EffectRecoveryDisposition.CONSUME_SUCCEEDED:
                resume_operation_from_completed_effect(
                    self.database_url,
                    context,
                    effect_id=effect_id,
                )
                outcomes.append("success")
                continue
            if disposition is EffectRecoveryDisposition.RETRY_POLICY:
                raise KernelError(
                    "CHAPTER_EXTERNAL_EFFECT_RETRY_REQUIRED",
                    "Provider retry requires a new Chapter Attempt",
                )
            if disposition is EffectRecoveryDisposition.TERMINAL_FAILURE:
                raise KernelError(
                    "CHAPTER_EXTERNAL_EFFECT_FINAL_FAILURE",
                    "Provider Final Failure cannot be recovered as success",
                )
            if disposition is EffectRecoveryDisposition.TERMINAL_CANCELLED:
                raise KernelError(
                    "CHAPTER_EXTERNAL_EFFECT_CANCELLED",
                    "cancelled Provider execution cannot produce a Chapter candidate",
                )
            if disposition is EffectRecoveryDisposition.OPERATOR_RECONCILIATION:
                raise KernelError(
                    "CHAPTER_EXTERNAL_EFFECT_OPERATOR_RECONCILIATION_REQUIRED",
                    "ExternalEffect status requires operator reconciliation",
                )
            authorize = getattr(self.model_effect_adapter, "for_recovery", None)
            if not callable(authorize):
                raise KernelError(
                    "CHAPTER_EXECUTION_RECOVERY_AUTHORIZATION_MISSING",
                    "Chapter reconciliation requires a recovery-capable PEP adapter",
                )
            recovery_adapter = authorize(
                execution_id=f"chapter-execution:{effect_id}",
                external_effect_id=effect_id,
                operation_id=str(operation["operation_id"]),
                attempt_id=attempt_id,
                execution_fencing_token=execution_fence,
                recovery_fencing_token=worker.fencing_token,
                recovery_worker_id=worker.worker_id,
                action=ExecutionRecoveryAction.QUERY,
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
            outcomes.append(
                str(
                    reconcile_external_effect(
                        self.database_url,
                        context,
                        effect_id=effect_id,
                        adapter=recovery_adapter,
                        attempt_command=worker,
                    )["outcome"]
                )
            )
        if not matched_attempt:
            raise KernelError(
                "CHAPTER_AGENT_RECONCILIATION_EVIDENCE_MISSING",
                "current Chapter Attempt has no uncertain ExternalEffect",
            )
        if "ambiguous" in outcomes:
            return "external_effect_reconciliation_required"
        return "external_effect_reconciled:" + ",".join(outcomes)


def _is_domain_validation_failure(error_code: str) -> bool:
    return error_code.startswith(
        (
            "CHAPTER_HANDLER_",
            "PUBLISH_GATE_",
            "QUALITY_",
            "CANON_",
            "REVISION_",
            "REVIEW_",
            "REALIZATION_",
        )
    )


__all__ = ["ChapterAuthorityScheduler", "ChapterSchedulerTick"]
