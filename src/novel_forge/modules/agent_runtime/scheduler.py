"""Persistent Agent candidate scheduler over the shared Command Kernel.

No lifecycle facts are owned here.  PostgreSQL Authority Operations, Attempts,
leases, fences, ExternalEffects and collaboration candidates remain the only
runtime facts.  The scheduler only coordinates them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg.types.json import Jsonb

from novel_forge.modules.agent_collaboration.application import (
    AgentCollaborationApplication,
)
from novel_forge.modules.agent_collaboration.domain import (
    AgentCollaborationSession,
    AgentMessageType,
    AgentWorkOrder,
    CollaborationStateMachine,
    SessionStatus,
)
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    checkpoint_attempt_for_external_reconciliation,
    create_attempt,
    heartbeat_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.cancellation import (
    acknowledge_worker_cancellation,
)
from novel_forge.modules.command_kernel.completion import (
    CompletionCommandContext,
    finalize_operation_completion,
)
from novel_forge.modules.command_kernel.deadline_runtime import (
    probe_operation_execution,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectRecoveryDisposition,
    EffectCommandContext,
    classify_external_effect_recovery,
    reconcile_external_effect,
    resume_operation_from_completed_effect,
)
from novel_forge.modules.command_kernel.lease_heartbeat import LeaseHeartbeatGuard
from novel_forge.modules.command_kernel.worker_execution import (
    WorkerFailureClass,
    WorkerFailureClassifier,
)
from novel_forge.modules.production_execution.domain_execution import (
    DomainExecutionPort,
)
from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import AgentRuntimeBinding
from .coordinator import AgentTurnExecutionCoordinator
from .harness import (
    AgentHarnessResult,
    AgentHarnessStatus,
    AgentTranscriptEventType,
    UnifiedAgentHarness,
)


AgentHarnessFactory = Callable[[str, str, str], UnifiedAgentHarness]


@dataclass(frozen=True, slots=True)
class PreparedAgentExecution:
    """Attempt-bound PEP contracts materialized before external execution."""

    execution_port: DomainExecutionPort
    route_snapshot_ref: str
    route_snapshot_hash: str
    input_manifest_ref: str
    input_manifest_hash: str
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_permission_snapshot_ref: str
    tool_permission_snapshot_hash: str
    context_policy_ref: str
    context_policy_hash: str

    def __post_init__(self) -> None:
        required = (
            self.route_snapshot_ref,
            self.input_manifest_ref,
            self.prompt_bundle_ref,
            self.skill_bundle_ref,
            self.tool_permission_snapshot_ref,
            self.context_policy_ref,
        )
        hashes = (
            self.route_snapshot_hash,
            self.input_manifest_hash,
            self.prompt_bundle_hash,
            self.skill_bundle_hash,
            self.tool_permission_snapshot_hash,
            self.context_policy_hash,
        )
        if any(not item.strip() for item in required):
            raise ValueError("prepared Agent execution references are incomplete")
        if any(not value.startswith("sha256:") or len(value) != 71 for value in hashes):
            raise ValueError("prepared Agent execution hashes must be SHA-256")
        if not getattr(self.execution_port, "external_effect_backed", False):
            raise ValueError("Agent execution port must be ExternalEffect-backed")
        if not getattr(
            self.execution_port, "production_execution_gateway_backed", False
        ):
            raise ValueError(
                "Agent execution port must use Production Execution Gateway"
            )


class AgentExecutionPreparer(Protocol):
    def prepare(
        self,
        *,
        operation: dict[str, Any],
        attempt_id: str,
        execution_fencing_token: int,
        recovery_fencing_token: int,
        worker_id: str,
    ) -> PreparedAgentExecution: ...


@dataclass(frozen=True, slots=True)
class AgentSchedulerTick:
    agent_run_id: str
    operation_id: str
    attempt_id: str
    operation_status: str
    candidate_version_id: str
    recovery_mode: str


class AgentAuthorityScheduler:
    """Advance one PostgreSQL Agent candidate Operation at a time."""

    def __init__(
        self,
        database_url: str,
        *,
        execution_preparer: AgentExecutionPreparer,
        worker_id: str,
        lease_seconds: int = 30,
        harness_factory: AgentHarnessFactory | None = None,
        harness_fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError("Agent scheduler requires database, worker, and lease")
        self.database_url = database_url
        self.execution_preparer = execution_preparer
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.harness_factory = harness_factory
        self.harness_fault_injector = harness_fault_injector or (lambda _point: None)
        self.turn_coordinator = AgentTurnExecutionCoordinator(database_url)

    def pending_runs(self, *, limit: int = 20) -> tuple[tuple[str, str], ...]:
        if limit <= 0 or limit > 500:
            raise ValueError("pending Agent run limit must be between 1 and 500")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, operation_id
                FROM authority_operation
                WHERE definition_name IN (
                    'agent.candidate.execute',
                    'agent.session.execute'
                )
                  AND status IN (
                    'READY', 'FAILED_RETRYABLE', 'EXECUTING',
                    'WAITING_EXTERNAL_RESULT', 'RECONCILIATION_REQUIRED',
                    'CANCELLATION_REQUESTED'
                  )
                ORDER BY created_at, operation_id
                LIMIT %s
                """,
                [limit],
            )
            return tuple((str(row[0]), str(row[1])) for row in uow.cursor.fetchall())

    def tick(self, *, project_id: str, agent_run_id: str) -> AgentSchedulerTick:
        operation = self._operation(project_id, agent_run_id)
        attempt_id, attempt_status, recovery_mode = self._attempt(operation)
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            trace_id=str(operation["trace_id"]),
            correlation_id=str(operation["correlation_id"]),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=str(operation["trace_id"]),
            correlation_id=str(operation["correlation_id"]),
            causation_id=agent_run_id,
        )
        if attempt_status in {"QUEUED", "LEASED"}:
            start_attempt(self.database_url, worker)
        if operation["definition_name"] == "agent.session.execute":
            return self._tick_harness(
                operation=operation,
                worker=worker,
                attempt_id=attempt_id,
                recovery_mode=recovery_mode,
            )
        try:
            collaboration_session_id = self._collaboration_session_for_attempt(
                operation=operation,
                attempt_id=attempt_id,
                recovery_mode=recovery_mode,
            )
            execution_operation = {
                **operation,
                "command_payload": {
                    **operation["command_payload"],
                    "collaboration_session_id": collaboration_session_id,
                },
            }
            frozen_binding = self._runtime_binding(attempt_id)
            execution_fence = (
                int(frozen_binding["fencing_token"])
                if frozen_binding is not None
                else worker.fencing_token
            )
            self._reconcile_required_effects(
                execution_operation,
                worker=worker,
                execution_fencing_token=execution_fence,
            )
            prepared = self.execution_preparer.prepare(
                operation=execution_operation,
                attempt_id=attempt_id,
                execution_fencing_token=execution_fence,
                recovery_fencing_token=worker.fencing_token,
                worker_id=self.worker_id,
            )
            work_order = build_agent_work_order(
                operation=execution_operation,
                attempt_id=attempt_id,
                fencing_token=worker.fencing_token,
                prepared=prepared,
            )
            runtime_binding = build_runtime_binding(
                operation=execution_operation,
                work_order=work_order,
                prepared=prepared,
                execution_fencing_token=execution_fence,
            )
            self._freeze_turn(work_order, runtime_binding)
            with LeaseHeartbeatGuard(
                lambda: heartbeat_attempt(
                    self.database_url, worker, self.lease_seconds
                ),
                lease_seconds=self.lease_seconds,
                label=f"agent-attempt:{attempt_id}",
                probe=lambda: probe_operation_execution(
                    self.database_url,
                    operation_id=agent_run_id,
                    project_id=project_id,
                ),
            ):
                result = self.turn_coordinator.execute_candidate(
                    work_order, prepared.execution_port
                )
            if not result.attempt_completion_allowed:
                raise KernelError(
                    "AGENT_CANDIDATE_REPAIR_REQUIRED",
                    "; ".join(result.violations) or "candidate requires repair",
                )
            self._record_candidate_completion(
                operation=operation,
                work_order=work_order,
                candidate_version_id=result.candidate_version_id,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(
                    agent_run_id, project_id
                )
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_status=str(state["status"]),
                    expected_operation_version=int(state["version"]),
                ),
                outcome="success",
                result={
                    "candidate_version_id": result.candidate_version_id,
                    "validation_status": result.domain_acceptance.value,
                    "execution_evidence_ref": work_order.input_manifest_ref,
                    "recovery_mode": recovery_mode,
                },
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                submitted = uow.repositories.attempt_runtime.operation_state(
                    agent_run_id, project_id
                )
            if str(submitted["status"]) == "WAITING_GATE":
                finalize_operation_completion(
                    self.database_url,
                    CompletionCommandContext(
                        project_id=project_id,
                        actor_id=self.worker_id,
                        trace_id=str(operation["trace_id"]),
                        correlation_id=str(operation["correlation_id"]),
                        causation_id=attempt_id,
                    ),
                    operation_id=agent_run_id,
                    expected_status="WAITING_GATE",
                    expected_version=int(submitted["version"]),
                )
        except Exception as exc:
            self._handle_failure(worker, exc)
            raise
        status = self._operation(project_id, agent_run_id)["status"]
        return AgentSchedulerTick(
            agent_run_id=agent_run_id,
            operation_id=agent_run_id,
            attempt_id=attempt_id,
            operation_status=str(status),
            candidate_version_id=result.candidate_version_id,
            recovery_mode=recovery_mode,
        )

    def _tick_harness(
        self,
        *,
        operation: dict[str, Any],
        worker: WorkerLeaseCommand,
        attempt_id: str,
        recovery_mode: str,
    ) -> AgentSchedulerTick:
        if self.harness_factory is None:
            raise KernelError(
                "AGENT_HARNESS_RUNTIME_UNBOUND",
                "Agent session worker has no governed Harness binding",
            )
        operation_id = str(operation["operation_id"])
        project_id = str(operation["project_id"])
        payload = dict(operation["command_payload"] or {})
        session_id = str(payload.get("agent_session_id") or "")
        instruction = str(payload.get("instruction") or "")
        try:
            with AuthorityUnitOfWork(self.database_url) as uow:
                session = uow.repositories.agent_runtime.require_harness_session(
                    session_id
                )
            if session.operation_id != operation_id or session.project_id != project_id:
                raise KernelError(
                    "AGENT_HARNESS_OPERATION_DRIFT",
                    "Harness session belongs to another durable Operation",
                )
            harness = self.harness_factory(
                project_id,
                attempt_id,
                str(operation["trace_id"]),
            )
            if session.status is AgentHarnessStatus.COMPLETED:
                committed = harness.transcript.committed_request_events(
                    agent_session_id=session.agent_session_id
                )
                response_events = [
                    item
                    for item in committed
                    if str(item.get("event_type") or "") == "REQUEST_COMMITTED"
                ]
                if not response_events:
                    raise KernelError(
                        "AGENT_HARNESS_COMMITTED_RESPONSE_MISSING",
                        "completed Harness session has no committed response",
                    )
                response = dict(response_events[-1].get("payload") or {}).get(
                    "response"
                )
                if not isinstance(response, dict) or not response:
                    raise KernelError(
                        "AGENT_HARNESS_COMMITTED_RESPONSE_INVALID",
                        "completed Harness response is not replayable",
                    )
                result = AgentHarnessResult(
                    session=session,
                    request_id=str(response_events[-1].get("request_id") or ""),
                    response=response,
                    observations=(),
                )
            else:
                if session.status in {
                    AgentHarnessStatus.FAILED,
                    AgentHarnessStatus.RUNNING,
                    AgentHarnessStatus.WAITING_TOOL,
                }:
                    session = harness.transcript.append_event(
                        session=session,
                        request_id=f"agent-session-recovery:{attempt_id}",
                        turn_number=0,
                        event_type=AgentTranscriptEventType.CHECKPOINT,
                        payload={
                            "reason": "durable_attempt_retry",
                            "prior_events_remain_non_committed": True,
                            "prior_status": session.status.value,
                        },
                        trace_id=str(operation["trace_id"]),
                        attempt_id=attempt_id,
                        target_status=AgentHarnessStatus.CHECKPOINTED,
                    )
                with LeaseHeartbeatGuard(
                    lambda: heartbeat_attempt(
                        self.database_url, worker, self.lease_seconds
                    ),
                    lease_seconds=self.lease_seconds,
                    label=f"agent-harness-attempt:{attempt_id}",
                    probe=lambda: probe_operation_execution(
                        self.database_url,
                        operation_id=operation_id,
                        project_id=project_id,
                    ),
                ):
                    result = harness.execute_request(
                        session=session,
                        request_id=f"agent-session-request:{attempt_id}",
                        instruction=instruction,
                        attempt_id=attempt_id,
                        trace_id=str(operation["trace_id"]),
                    )
                self.harness_fault_injector("after_harness_transcript_commit")
            self._record_harness_completion(
                operation=operation,
                result=result,
                attempt_id=attempt_id,
                fencing_token=worker.fencing_token,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_status=str(state["status"]),
                    expected_operation_version=int(state["version"]),
                ),
                outcome="success",
                result={
                    "agent_session_id": result.session.agent_session_id,
                    "response": dict(result.response),
                    "transcript_last_sequence": result.session.next_sequence - 1,
                },
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                submitted = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
            if str(submitted["status"]) == "WAITING_GATE":
                finalize_operation_completion(
                    self.database_url,
                    CompletionCommandContext(
                        project_id=project_id,
                        actor_id=self.worker_id,
                        trace_id=str(operation["trace_id"]),
                        correlation_id=str(operation["correlation_id"]),
                        causation_id=attempt_id,
                    ),
                    operation_id=operation_id,
                    expected_status="WAITING_GATE",
                    expected_version=int(submitted["version"]),
                )
        except Exception as exc:
            self._handle_failure(worker, exc)
            raise
        status = self._operation(project_id, operation_id)["status"]
        return AgentSchedulerTick(
            agent_run_id=operation_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            operation_status=str(status),
            candidate_version_id="",
            recovery_mode=recovery_mode,
        )

    def _record_harness_completion(
        self,
        *,
        operation: dict[str, Any],
        result: AgentHarnessResult,
        attempt_id: str,
        fencing_token: int,
    ) -> None:
        operation_id = str(operation["operation_id"])
        project_id = str(operation["project_id"])
        evidence = {
            "agent_session_id": result.session.agent_session_id,
            "attempt_id": attempt_id,
            "fencing_token": fencing_token,
            "transcript_last_sequence": result.session.next_sequence - 1,
            "provenance_only": True,
            "authority_mutation": False,
            "execution_contract_hash": result.session.execution_contract_hash,
            "aggregate_usage": asdict(result.session.usage),
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_completion_gate(
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (
                    %s, %s, 'agent_session_transcript_committed', 'PASSED', %s
                )
                ON CONFLICT(operation_id, gate_key) DO UPDATE
                SET status=EXCLUDED.status, evidence=EXCLUDED.evidence,
                    evaluated_at=NOW()
                """,
                [str(uuid4()), operation_id, Jsonb(evidence)],
            )
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_agent_harness_session",
                    "aggregate_id": result.session.agent_session_id,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "event_type": "authority.agent.session.completed",
                    "correlation_id": str(operation["correlation_id"]),
                    "causation_id": attempt_id,
                    "payload": {
                        **evidence,
                        "operation_id": operation_id,
                        "project_id": project_id,
                        "trace_id": str(operation["trace_id"]),
                    },
                }
            )
            uow.commit()

    def _attempt(self, operation: dict[str, Any]) -> tuple[str, str, str]:
        operation_id = str(operation["operation_id"])
        project_id = str(operation["project_id"])
        if operation["status"] in {"READY", "FAILED_RETRYABLE"}:
            recovery = (
                "retry_attempt"
                if operation["status"] == "FAILED_RETRYABLE"
                else "fresh_attempt"
            )
            created = create_attempt(
                self.database_url,
                operation_id=operation_id,
                project_id=project_id,
                max_attempts=int(operation["max_attempts"]),
                trace_id=str(operation["trace_id"]),
                correlation_id=str(operation["correlation_id"]),
            )
            if created["dead_letter"] or created["attempt_id"] is None:
                raise KernelError(
                    "AGENT_ATTEMPT_EXHAUSTED", "Agent Attempt policy is exhausted"
                )
            attempt_id = str(created["attempt_id"])
            queue_attempt(
                self.database_url,
                attempt_id=attempt_id,
                project_id=project_id,
                trace_id=str(operation["trace_id"]),
                correlation_id=str(operation["correlation_id"]),
            )
            return attempt_id, "QUEUED", recovery
        if operation["status"] in {
            "EXECUTING",
            "WAITING_EXTERNAL_RESULT",
            "RECONCILIATION_REQUIRED",
            "CANCELLATION_REQUESTED",
        }:
            active = self._active_attempt(operation_id, project_id)
            if active is None:
                raise KernelError(
                    "AGENT_ATTEMPT_MISSING",
                    "executing Agent Operation has no recoverable Attempt",
                )
            mode = (
                "frozen_binding_reconciliation"
                if self._runtime_binding_exists(str(active["attempt_id"]))
                else "lease_takeover"
            )
            return str(active["attempt_id"]), str(active["status"]), mode
        raise KernelError(
            "AGENT_OPERATION_NOT_RECOVERABLE",
            f"cannot execute Agent run from {operation['status']}",
        )

    def _freeze_turn(
        self, work_order: AgentWorkOrder, runtime_binding: AgentRuntimeBinding
    ) -> None:
        self.turn_coordinator.freeze_turn(work_order, runtime_binding)

    def _record_candidate_completion(
        self,
        *,
        operation: dict[str, Any],
        work_order: AgentWorkOrder,
        candidate_version_id: str,
    ) -> None:
        operation_id = str(operation["operation_id"])
        project_id = str(operation["project_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            evidence = {
                "candidate_version_id": candidate_version_id,
                "work_order_id": work_order.work_order_id,
                "attempt_id": work_order.attempt_id,
                "fencing_token": work_order.fencing_token,
                "candidate_only": True,
                "domain_commit_required": True,
            }
            uow.cursor.execute(
                """
                INSERT INTO authority_completion_gate(
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (%s, %s, 'agent_candidate_validated', 'PASSED', %s)
                ON CONFLICT(operation_id, gate_key) DO UPDATE
                SET status=EXCLUDED.status, evidence=EXCLUDED.evidence,
                    evaluated_at=NOW()
                """,
                [str(uuid4()), operation_id, Jsonb(evidence)],
            )
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_agent_candidate",
                    "aggregate_id": candidate_version_id,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "event_type": "authority.agent.candidate.validated",
                    "correlation_id": str(operation["correlation_id"]),
                    "causation_id": work_order.turn_id,
                    "payload": {
                        **evidence,
                        "operation_id": operation_id,
                        "project_id": project_id,
                        "trace_id": str(operation["trace_id"]),
                    },
                }
            )
            uow.commit()

    def _handle_failure(self, worker: WorkerLeaseCommand, exc: Exception) -> None:
        classification = WorkerFailureClassifier.classify(exc)
        if classification is WorkerFailureClass.CANCELLATION:
            with AuthorityUnitOfWork(self.database_url) as uow:
                current = uow.repositories.attempt_runtime.operation_state(
                    worker.causation_id, worker.project_id
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
                    "error_code": (
                        exc.code if isinstance(exc, KernelError) else "UNKNOWN"
                    ),
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
                error_code=(
                    exc.code if isinstance(exc, KernelError) else "PROGRAMMING_BUG"
                ),
                error_message=str(exc),
                failure_class=classification.value,
            )

    def _operation(self, project_id: str, operation_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id, project_id, workspace_id, status,
                       command_payload, definition_name, definition_version,
                       definition_snapshot, trace_id, correlation_id,
                       COALESCE((definition_snapshot->'retry_policy'
                           ->>'max_attempts')::int, 1)
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                  AND definition_name IN (
                    'agent.candidate.execute', 'agent.session.execute'
                  )
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("AGENT_RUN_NOT_FOUND", "Agent Operation does not exist")
        fields = (
            "operation_id",
            "project_id",
            "workspace_id",
            "status",
            "command_payload",
            "definition_name",
            "definition_version",
            "definition_snapshot",
            "trace_id",
            "correlation_id",
            "max_attempts",
        )
        result = dict(zip(fields, row, strict=True))
        result["command_payload"] = dict(result["command_payload"] or {})
        result["definition_snapshot"] = dict(result["definition_snapshot"] or {})
        return result

    def _active_attempt(
        self, operation_id: str, project_id: str
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT attempt_id, status FROM authority_attempt
                WHERE operation_id=%s
                  AND status IN ('QUEUED', 'LEASED', 'RUNNING', 'CHECKPOINTED')
                  AND EXISTS(
                    SELECT 1 FROM authority_operation
                    WHERE operation_id=%s AND project_id=%s
                  )
                ORDER BY attempt_number DESC LIMIT 1
                """,
                [operation_id, operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        return None if row is None else {"attempt_id": row[0], "status": row[1]}

    def _runtime_binding_exists(self, attempt_id: str) -> bool:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM authority_agent_runtime_binding
                    WHERE attempt_id=%s
                )
                """,
                [attempt_id],
            )
            return bool(uow.cursor.fetchone()[0])

    def _runtime_binding(self, attempt_id: str) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding_id, fencing_token, work_order_id
                FROM authority_agent_runtime_binding
                WHERE attempt_id=%s
                """,
                [attempt_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return {
            "binding_id": str(row[0]),
            "fencing_token": int(row[1]),
            "work_order_id": str(row[2]),
        }

    def _collaboration_session_for_attempt(
        self,
        *,
        operation: dict[str, Any],
        attempt_id: str,
        recovery_mode: str,
    ) -> str:
        operation_id = str(operation["operation_id"])
        base_session_id = str(operation["command_payload"]["collaboration_session_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = uow.repositories.agent_collaboration
            uow.cursor.execute(
                """
                SELECT session_id
                FROM authority_agent_collaboration_session
                WHERE attempt_id=%s AND created_operation_id=%s
                """,
                [attempt_id, operation_id],
            )
            row = uow.cursor.fetchone()
            if row is not None:
                return str(row[0])

            base = repository.get_session(base_session_id)
            if recovery_mode == "fresh_attempt" and not base.attempt_id:
                bound = repository.update_session(replace(base, attempt_id=attempt_id))
                uow.commit()
                return bound.session_id
            if base.attempt_id == attempt_id:
                return base.session_id

            uow.cursor.execute(
                """
                SELECT session_id
                FROM authority_agent_collaboration_session
                WHERE created_operation_id=%s AND attempt_id IS NOT NULL
                ORDER BY created_at DESC, session_id DESC
                LIMIT 1
                """,
                [operation_id],
            )
            prior_row = uow.cursor.fetchone()
            prior = (
                repository.get_session(str(prior_row[0]))
                if prior_row is not None
                else base
            )
            if prior.status not in {
                SessionStatus.COMMITTED,
                SessionStatus.REJECTED,
                SessionStatus.CANCELLED,
                SessionStatus.FAILED,
            }:
                repository.update_session(
                    CollaborationStateMachine.transition(prior, SessionStatus.FAILED)
                )
            session_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"novel-forge:agent-retry-session:{attempt_id}",
                )
            )
            application = AgentCollaborationApplication(repository)
            created = application.create_collaboration_session(
                AgentCollaborationSession(
                    session_id=session_id,
                    project_id=prior.project_id,
                    owner_authority=prior.owner_authority,
                    business_goal=prior.business_goal,
                    issue_type=prior.issue_type,
                    scope_snapshot_ref="",
                    participant_snapshot_ref="",
                    current_candidate_version_ref="",
                    status=SessionStatus.CREATED,
                    round_number=0,
                    turn_number=0,
                    execution_count=0,
                    spent_budget=0,
                    budget_ref=prior.budget_ref,
                    termination_policy_ref=prior.termination_policy_ref,
                    created_operation_id=operation_id,
                    saga_id=prior.saga_id,
                    authority_decision_ref="",
                    last_turn_id="",
                    attempt_id=attempt_id,
                )
            )
            application.freeze_scope(
                created.session_id,
                repository.get_scope_snapshot(prior.scope_snapshot_ref),
            )
            application.assign_participants(
                created.session_id,
                repository.get_participant_snapshot(prior.participant_snapshot_ref),
            )
            uow.commit()
            return created.session_id

    def _reconcile_required_effects(
        self,
        operation: dict[str, Any],
        *,
        worker: WorkerLeaseCommand,
        execution_fencing_token: int,
    ) -> None:
        adapter = getattr(self.execution_preparer, "adapter", None)
        if adapter is None:
            return
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT external_effect_id, status, request_payload,
                       provider_request_id
                FROM authority_external_effect
                WHERE operation_id=%s
                  AND effect_type='model.invoke'
                ORDER BY created_at, external_effect_id
                """,
                [operation["operation_id"]],
            )
            effects = tuple(uow.cursor.fetchall())
        context = EffectCommandContext(
            operation_id=str(operation["operation_id"]),
            project_id=str(operation["project_id"]),
            actor_id=self.worker_id,
            trace_id=str(operation["trace_id"]),
            correlation_id=str(operation["correlation_id"]),
        )
        for (
            effect_id_value,
            effect_status,
            request_payload,
            _provider_request_id,
        ) in effects:
            effect_id = str(effect_id_value)
            metadata = (
                request_payload.get("_production_execution")
                if isinstance(request_payload, dict)
                else None
            )
            if not isinstance(metadata, dict):
                raise KernelError(
                    "AGENT_EXECUTION_IDENTITY_INVALID",
                    "ExternalEffect lacks frozen execution identity",
                )
            if str(metadata.get("attempt_id") or "") != worker.attempt_id:
                continue
            disposition = classify_external_effect_recovery(str(effect_status))
            if disposition is EffectRecoveryDisposition.DISPATCH_PLANNED:
                continue
            if disposition is EffectRecoveryDisposition.CONSUME_SUCCEEDED:
                resume_operation_from_completed_effect(
                    self.database_url,
                    context,
                    effect_id=effect_id,
                )
                continue
            if disposition is EffectRecoveryDisposition.RETRY_POLICY:
                raise KernelError(
                    "AGENT_EXTERNAL_EFFECT_RETRY_REQUIRED",
                    "Provider retry requires a new Authority Attempt",
                )
            if disposition is EffectRecoveryDisposition.TERMINAL_FAILURE:
                raise KernelError(
                    "AGENT_EXTERNAL_EFFECT_FINAL_FAILURE",
                    "Provider Final Failure cannot be recovered as success",
                )
            if disposition is EffectRecoveryDisposition.TERMINAL_CANCELLED:
                raise KernelError(
                    "AGENT_EXTERNAL_EFFECT_CANCELLED",
                    "cancelled Provider execution cannot produce a Candidate",
                )
            if disposition is EffectRecoveryDisposition.OPERATOR_RECONCILIATION:
                raise KernelError(
                    "AGENT_EXTERNAL_EFFECT_OPERATOR_RECONCILIATION_REQUIRED",
                    "ExternalEffect status requires operator reconciliation",
                )
            frozen_fence = int(metadata.get("fencing_token") or execution_fencing_token)
            authorize = getattr(adapter, "for_recovery", None)
            if not callable(authorize):
                raise KernelError(
                    "AGENT_EXECUTION_RECOVERY_AUTHORIZATION_MISSING",
                    "ExternalEffect reconciliation requires a recovery-capable adapter",
                )
            recovery_adapter = authorize(
                execution_id=f"chapter-execution:{effect_id}",
                external_effect_id=effect_id,
                operation_id=str(operation["operation_id"]),
                attempt_id=worker.attempt_id,
                execution_fencing_token=frozen_fence,
                recovery_fencing_token=worker.fencing_token,
                recovery_worker_id=worker.worker_id,
                action=ExecutionRecoveryAction.QUERY,
                trace_id=str(operation["trace_id"]),
                correlation_id=str(operation["correlation_id"]),
            )
            result = reconcile_external_effect(
                self.database_url,
                context,
                effect_id=effect_id,
                adapter=recovery_adapter,
            )
            if result["outcome"] == "ambiguous":
                raise KernelError(
                    "AGENT_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED",
                    "Provider query remains ambiguous; operator reconciliation is required",
                )


def build_agent_work_order(
    *,
    operation: dict[str, Any],
    attempt_id: str,
    fencing_token: int,
    prepared: PreparedAgentExecution,
) -> AgentWorkOrder:
    command = dict(operation["command_payload"])
    operation_id = str(operation["operation_id"])
    turn_id = str(uuid5(NAMESPACE_URL, f"novel-forge:agent-turn:{attempt_id}"))
    return AgentWorkOrder(
        work_order_id=str(
            uuid5(NAMESPACE_URL, f"novel-forge:agent-work-order:{attempt_id}")
        ),
        collaboration_session_id=str(command["collaboration_session_id"]),
        turn_id=turn_id,
        operation_id=operation_id,
        attempt_id=attempt_id,
        fencing_token=fencing_token,
        agent_id=str(command["agent_id"]),
        agent_definition_version=int(command["agent_definition_version"]),
        capability=str(command["capability_id"]),
        message_type=AgentMessageType(str(command["message_type"])),
        business_goal=str(command["business_goal"]),
        current_issue=str(command["current_issue"]),
        scope_snapshot_ref=str(command["scope_snapshot_ref"]),
        participant_snapshot_ref=str(command["participant_snapshot_ref"]),
        input_asset_versions=tuple(command["input_asset_versions"]),
        candidate_version_ref=str(command.get("candidate_version_ref") or ""),
        context_bundle_ref=str(command["context_bundle_asset_version_id"]),
        evidence_refs=tuple(command["evidence_refs"]),
        must_preserve=tuple(command["must_preserve"]),
        must_change=tuple(command["must_change"]),
        forbidden_changes=tuple(command["forbidden_changes"]),
        acceptance_criteria=tuple(command["acceptance_criteria"]),
        risk_level=str(command["risk_level"]),
        budget_policy_ref=str(command["budget_policy_ref"]),
        timeout_policy_ref=str(command["timeout_policy_ref"]),
        approval_policy_ref=str(command["approval_policy_ref"]),
        failure_policy=str(command["failure_policy"]),
        continuation_policy=str(command["continuation_policy"]),
        project_id=str(operation["project_id"]),
        workspace_id=str(operation["workspace_id"]),
        book_id=str(command["book_id"]),
        route_snapshot_ref=prepared.route_snapshot_ref,
        input_manifest_ref=prepared.input_manifest_ref,
        capability_version=int(command["capability_version"]),
        execution_capability=str(command["execution_capability_id"]),
    )


def build_runtime_binding(
    *,
    operation: dict[str, Any],
    work_order: AgentWorkOrder,
    prepared: PreparedAgentExecution,
    execution_fencing_token: int | None = None,
) -> AgentRuntimeBinding:
    command = dict(operation["command_payload"])
    definition = dict(operation["definition_snapshot"])
    return AgentRuntimeBinding(
        binding_id=str(
            uuid5(
                NAMESPACE_URL,
                f"novel-forge:agent-runtime-binding:{work_order.attempt_id}",
            )
        ),
        project_id=work_order.project_id,
        workspace_id=work_order.workspace_id,
        book_id=work_order.book_id,
        workflow_definition_ref=str(command["workflow_definition_ref"]),
        workflow_node_id=str(command["workflow_node_id"]),
        operation_definition_ref=(
            f"{operation['definition_name']}@{operation['definition_version']}"
        ),
        operation_definition_hash=str(definition["definition_hash"]),
        operation_id=work_order.operation_id,
        attempt_id=work_order.attempt_id,
        fencing_token=(
            work_order.fencing_token
            if execution_fencing_token is None
            else execution_fencing_token
        ),
        work_order_id=work_order.work_order_id,
        agent_id=work_order.agent_id,
        agent_definition_version=work_order.agent_definition_version,
        agent_definition_hash=str(command["agent_definition_hash"]),
        capability_id=str(command["capability_id"]),
        capability_version=int(command["capability_version"]),
        capability_hash=str(command["capability_hash"]),
        execution_capability_id=work_order.execution_capability,
        chapter_node_binding_ref=str(command["chapter_node_binding_ref"]),
        capability_pack_ref=str(command["capability_pack_ref"]),
        capability_pack_compilation_hash=str(
            command["capability_pack_compilation_hash"]
        ),
        context_bundle_asset_version_id=str(command["context_bundle_asset_version_id"]),
        context_bundle_hash=str(command["context_bundle_hash"]),
        prompt_bundle_ref=prepared.prompt_bundle_ref,
        prompt_bundle_hash=prepared.prompt_bundle_hash,
        skill_bundle_ref=prepared.skill_bundle_ref,
        skill_bundle_hash=prepared.skill_bundle_hash,
        tool_policy_ref=str(command["tool_policy_ref"]),
        tool_policy_hash=str(command["tool_policy_hash"]),
        tool_permission_snapshot_ref=prepared.tool_permission_snapshot_ref,
        tool_permission_snapshot_hash=prepared.tool_permission_snapshot_hash,
        context_policy_ref=prepared.context_policy_ref,
        context_policy_hash=prepared.context_policy_hash,
        route_snapshot_ref=prepared.route_snapshot_ref,
        route_snapshot_hash=prepared.route_snapshot_hash,
        input_manifest_ref=prepared.input_manifest_ref,
        input_manifest_hash=prepared.input_manifest_hash,
        budget_policy_ref=str(command["budget_policy_ref"]),
        timeout_policy_ref=str(command["timeout_policy_ref"]),
        approval_policy_ref=str(command["approval_policy_ref"]),
        validation_policy_ref=str(command["validation_policy_ref"]),
        commit_policy_ref=str(command["commit_policy_ref"]),
        commit_authority=str(command["commit_authority"]),
        release_sha=str(command["release_sha"]),
        capability_pack_deployment_id=str(
            command.get("capability_pack_deployment_id") or ""
        ),
        capability_pack_activation_version=int(
            command.get("capability_pack_activation_version") or 0
        ),
        capability_pack_binding_set_id=str(
            command.get("capability_pack_binding_set_id") or ""
        ),
        capability_pack_binding_set_hash=str(
            command.get("capability_pack_binding_set_hash") or ""
        ),
        capability_pack_scope_type=str(command.get("capability_pack_scope_type") or ""),
        capability_pack_assignment_ref=str(
            command.get("capability_pack_assignment_ref") or ""
        ),
        capability_pack_attempt_snapshot_id=str(
            command.get("capability_pack_attempt_snapshot_id") or ""
        ),
        capability_pack_attempt_snapshot_hash=str(
            command.get("capability_pack_attempt_snapshot_hash") or ""
        ),
    )


__all__ = [
    "AgentAuthorityScheduler",
    "AgentExecutionPreparer",
    "AgentSchedulerTick",
    "PreparedAgentExecution",
    "build_agent_work_order",
    "build_runtime_binding",
]
