"""INVARIANT: Shared Agent-turn execution and exact Domain commit coordination.

The coordinator owns no lifecycle state.  It composes the existing Command
Kernel Attempt/Fence, PEP evidence, collaboration Candidate, and Domain
Authority AssetVersion facts for both embedded and standalone execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from novel_forge.modules.agent_collaboration.application import (
    AgentCollaborationApplication,
    TurnProcessingResult,
)
from novel_forge.modules.agent_collaboration.domain import (
    AgentOutputEnvelope,
    AgentWorkOrder,
    CollaborationDecision,
    CollaborationDecisionType,
    CollaborationStateMachine,
    SessionStatus,
)
from novel_forge.modules.agent_collaboration.repository import CollaborationCommit
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionEvidence,
    DomainExecutionPort,
    execute_domain_candidate,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import AgentRuntimeBinding


def agent_turn_identity(kind: str, attempt_id: str) -> str:

    return str(uuid5(NAMESPACE_URL, f"novel-forge:{kind}:{attempt_id}"))


@dataclass(frozen=True, slots=True)
class ExistingDomainAssetCommit:
    project_id: str
    session_id: str
    candidate_version_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    asset_version_id: str
    content_hash: str
    commit_policy_ref: str
    authority_type: str
    receipt_ref: str
    decision_evidence: tuple[str, ...]


class ExistingDomainAssetCommitPort:

    def __init__(self, cursor: Any, expected: ExistingDomainAssetCommit) -> None:
        self.cursor = cursor
        self.expected = expected

    def commit_candidate(self, **values: Any) -> dict[str, str | int]:
        candidate = values["candidate"]
        decision = values["decision"]
        operation_id = str(values["operation_id"])
        expected = self.expected
        if (
            candidate.candidate_version_id != expected.candidate_version_id
            or decision.candidate_version_id != expected.candidate_version_id
            or operation_id != expected.operation_id
        ):
            raise KernelError(
                "AGENT_DOMAIN_COMMIT_IDENTITY_DRIFT",
                "Candidate, Decision, and Domain Operation identities differ",
            )
        self.cursor.execute(
            """
            SELECT output.content_hash, attempt.operation_id,
                   EXISTS(
                       SELECT 1 FROM authority_lease_acquisition AS lease
                       WHERE lease.attempt_id=%s AND lease.fencing_token=%s
                         AND lease.status='HELD'
                   )
            FROM authority_operation_output_asset AS output
            JOIN authority_attempt AS attempt ON attempt.attempt_id=%s
            JOIN authority_operation AS operation
              ON operation.operation_id=output.operation_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=output.asset_version_id
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE output.operation_id=%s AND output.asset_version_id=%s
              AND output.content_hash=%s
              AND operation.project_id=%s AND asset.project_id=%s
            """,
            [
                expected.attempt_id,
                expected.fencing_token,
                expected.attempt_id,
                expected.operation_id,
                expected.asset_version_id,
                expected.content_hash,
                expected.project_id,
                expected.project_id,
            ],
        )
        row = self.cursor.fetchone()
        if row is None or str(row[1]) != expected.operation_id or not bool(row[2]):
            raise KernelError(
                "AGENT_DOMAIN_ASSET_LINEAGE_INVALID",
                "existing Domain AssetVersion is not bound to the exact Attempt/Fence",
            )
        return {
            "commit_id": agent_turn_identity("domain-commit", expected.session_id),
            "asset_version_id": expected.asset_version_id,
            "content_hash": expected.content_hash,
            "attempt_id": expected.attempt_id,
            "fencing_token": expected.fencing_token,
            "receipt_ref": expected.receipt_ref,
        }


class AgentTurnExecutionCoordinator:

    def __init__(
        self,
        database_url: str,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("Agent turn coordinator requires PostgreSQL")
        self.database_url = database_url
        self.fault_injector = fault_injector or (lambda _checkpoint: None)

    def freeze_turn(
        self, work_order: AgentWorkOrder, runtime_binding: AgentRuntimeBinding
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            self.freeze_turn_in_uow(uow, work_order, runtime_binding)
            uow.commit()
        self.fault_injector("after_runtime_binding_freeze")

    def freeze_turn_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        work_order: AgentWorkOrder,
        runtime_binding: AgentRuntimeBinding,
    ) -> None:
        collaboration = AgentCollaborationApplication(
            uow.repositories.agent_collaboration
        )
        collaboration.schedule_next_turn(work_order)
        self.fault_injector("after_work_order_freeze")
        uow.repositories.agent_runtime.save_runtime_binding(runtime_binding)

    def accept_envelope(
        self,
        work_order: AgentWorkOrder,
        envelope: AgentOutputEnvelope,
        evidence: DomainExecutionEvidence,
    ) -> TurnProcessingResult:
        try:
            AgentCollaborationApplication.validate_execution_evidence(
                work_order, evidence
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                result = AgentCollaborationApplication(
                    uow.repositories.agent_collaboration
                ).accept_agent_output(
                    work_order,
                    envelope,
                    execution_evidence=evidence,
                )
                if result.candidate_version_id:
                    self._record_candidate_supersession(
                        uow,
                        work_order=work_order,
                        superseding_candidate_version_id=(result.candidate_version_id),
                    )
                uow.commit()
            self.fault_injector("after_candidate_persist")
            return result
        except (TypeError, ValueError) as exc:
            raise KernelError("AGENT_CANDIDATE_VALIDATION_FAILED", str(exc)) from exc

    @staticmethod
    def _record_candidate_supersession(
        uow: AuthorityUnitOfWork,
        *,
        work_order: AgentWorkOrder,
        superseding_candidate_version_id: str,
    ) -> None:
        uow.cursor.execute(
            """
            SELECT candidate.candidate_version_id, turn.attempt_id,
                   attempt.error, attempt.result,
                   current_lease.fencing_token, current_lease.owner,
                   candidate.session_id
            FROM authority_agent_candidate_version AS candidate
            JOIN authority_agent_collaboration_turn AS turn
              ON turn.turn_id=candidate.originating_turn_id
            JOIN authority_attempt AS attempt
              ON attempt.attempt_id=turn.attempt_id
            JOIN authority_attempt AS current_attempt
              ON current_attempt.attempt_id=%s
            JOIN authority_lease_acquisition AS current_lease
              ON current_lease.attempt_id=current_attempt.attempt_id
             AND current_lease.status='HELD'
             AND current_lease.expires_at > NOW()
            LEFT JOIN authority_agent_candidate_supersession AS supersession
              ON supersession.superseded_candidate_version_id=
                 candidate.candidate_version_id
            LEFT JOIN authority_agent_collaboration_commit AS collaboration_commit
              ON collaboration_commit.candidate_version_id=
                 candidate.candidate_version_id
            WHERE turn.operation_id=%s
              AND attempt.attempt_number < current_attempt.attempt_number
              AND supersession.supersession_id IS NULL
              AND collaboration_commit.commit_id IS NULL
            ORDER BY attempt.attempt_number DESC, candidate.created_at DESC
            LIMIT 1
            """,
            [work_order.attempt_id, work_order.operation_id],
        )
        prior = uow.cursor.fetchone()
        if prior is None:
            return
        superseded_candidate_id = str(prior[0])
        superseded_attempt_id = str(prior[1])
        supersession_id = agent_turn_identity(
            "candidate-supersession",
            f"{superseded_candidate_id}:{superseding_candidate_version_id}",
        )
        failure_reason = {
            "attempt_id": superseded_attempt_id,
            "error": dict(prior[2] or {}),
            "result": dict(prior[3] or {}),
        }
        recovery_fencing_token = int(prior[4])
        recovery_worker_id = str(prior[5])
        superseded_session_id = str(prior[6])
        uow.cursor.execute(
            """
            INSERT INTO authority_agent_candidate_supersession(
                supersession_id, project_id, operation_id,
                superseded_attempt_id, superseding_attempt_id,
                superseded_candidate_version_id,
                superseding_candidate_version_id,
                recovery_fencing_token, created_by_worker,
                failure_reason, retry_policy_ref
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(supersession_id) DO NOTHING
            """,
            [
                supersession_id,
                work_order.project_id,
                work_order.operation_id,
                superseded_attempt_id,
                work_order.attempt_id,
                superseded_candidate_id,
                superseding_candidate_version_id,
                recovery_fencing_token,
                recovery_worker_id,
                Jsonb(failure_reason),
                work_order.failure_policy,
            ],
        )
        event_id = agent_turn_identity("candidate-supersession-event", supersession_id)
        uow.repositories.operation_graph.record_event(
            {
                "event_id": event_id,
                "audit_id": agent_turn_identity(
                    "candidate-supersession-audit", supersession_id
                ),
                "outbox_id": agent_turn_identity(
                    "candidate-supersession-outbox", supersession_id
                ),
                "aggregate_type": "authority_agent_candidate_supersession",
                "aggregate_id": supersession_id,
                "operation_id": work_order.operation_id,
                "project_id": work_order.project_id,
                "event_type": "authority.agent.candidate.superseded",
                "correlation_id": work_order.operation_id,
                "causation_id": work_order.turn_id,
                "payload": {
                    "supersession_id": supersession_id,
                    "superseded_attempt_id": superseded_attempt_id,
                    "superseding_attempt_id": work_order.attempt_id,
                    "superseded_candidate_version_id": (superseded_candidate_id),
                    "superseding_candidate_version_id": (
                        superseding_candidate_version_id
                    ),
                    "failure_reason": failure_reason,
                    "retry_policy_ref": work_order.failure_policy,
                },
            }
        )
        superseded_session = uow.repositories.agent_collaboration.get_session(
            superseded_session_id
        )
        if superseded_session.status not in {
            SessionStatus.COMMITTED,
            SessionStatus.REJECTED,
            SessionStatus.CANCELLED,
            SessionStatus.FAILED,
        }:
            uow.repositories.agent_collaboration.update_session(
                CollaborationStateMachine.transition(
                    superseded_session,
                    SessionStatus.FAILED,
                )
            )

    def execute_candidate(
        self, work_order: AgentWorkOrder, execution_port: DomainExecutionPort
    ) -> TurnProcessingResult:
        candidate = execute_domain_candidate(
            capability=work_order.execution_capability,
            operation="analyze",
            candidate_kind=CandidateKind.AGENT_RESULT,
            prompt=(
                "Execute the frozen Agent work order and return only a candidate "
                "AgentOutputEnvelope. Domain Authority owns commit."
            ),
            context={
                "agent_work_order": work_order.to_context(),
                "commit_authority": "domain_authority_only",
            },
            execution_port=execution_port,
        )
        try:
            envelope = AgentOutputEnvelope.from_mapping(
                candidate.raw_output,
                execution_evidence_ref=candidate.evidence.validation_manifest_ref,
            )
        except (TypeError, ValueError) as exc:
            raise KernelError("AGENT_OUTPUT_SCHEMA_INVALID", str(exc)) from exc
        return self.accept_envelope(work_order, envelope, candidate.evidence)

    def record_existing_domain_commit(
        self, commit: ExistingDomainAssetCommit
    ) -> CollaborationCommit:
        existing = self._ensure_authority_decision(commit)
        if existing is not None:
            return existing
        self.fault_injector("after_authority_decision")
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = uow.repositories.agent_collaboration
            application = AgentCollaborationApplication(repository)
            recovered = application.recover_collaboration_session(commit.session_id)
            existing = recovered.commit
            if existing is not None:
                self._validate_existing_commit(existing, commit)
                uow.commit()
                return existing
            application = AgentCollaborationApplication(
                repository,
                authority_committer=ExistingDomainAssetCommitPort(uow.cursor, commit),
            )
            result = application.commit_accepted_candidate(
                commit.session_id,
                operation_id=commit.operation_id,
                idempotency_key=f"agent-domain-commit:{commit.candidate_version_id}",
            )
            uow.commit()
        self.fault_injector("after_collaboration_commit")
        return result

    def _ensure_authority_decision(
        self, commit: ExistingDomainAssetCommit
    ) -> CollaborationCommit | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = uow.repositories.agent_collaboration
            application = AgentCollaborationApplication(repository)
            recovered = application.recover_collaboration_session(commit.session_id)
            if recovered.commit is not None:
                self._validate_existing_commit(recovered.commit, commit)
                uow.commit()
                return recovered.commit
            if (
                recovered.session.current_candidate_version_ref
                != commit.candidate_version_id
            ):
                raise KernelError(
                    "AGENT_DOMAIN_CANDIDATE_DRIFT",
                    "Domain Handler result does not match the current CandidateVersion",
                )
            if not recovered.session.authority_decision_ref:
                application.request_authority_decision(
                    commit.session_id, domain_candidate_validated=True
                )
                application.apply_authority_decision(
                    CollaborationDecision(
                        decision_id=agent_turn_identity(
                            "authority-decision", commit.session_id
                        ),
                        decision=CollaborationDecisionType.ACCEPTED,
                        authority_type=commit.authority_type,
                        authority_version=1,
                        session_id=commit.session_id,
                        candidate_version_id=commit.candidate_version_id,
                        accepted_changes=("domain handler validated candidate",),
                        rejected_changes=(),
                        deferred_changes=(),
                        accepted_with_objections=(),
                        unresolved_objections=(),
                        required_followup=(),
                        affected_asset_versions=(commit.asset_version_id,),
                        commit_policy_ref=commit.commit_policy_ref,
                        decision_evidence=commit.decision_evidence,
                    )
                )
            uow.commit()
        return None

    @staticmethod
    def _validate_existing_commit(
        existing: CollaborationCommit, expected: ExistingDomainAssetCommit
    ) -> None:
        actual_lineage = (
            existing.candidate_version_id,
            existing.operation_id,
            existing.attempt_id,
            existing.fencing_token,
            existing.asset_version_id,
            existing.content_hash,
        )
        expected_lineage = (
            expected.candidate_version_id,
            expected.operation_id,
            expected.attempt_id,
            expected.fencing_token,
            expected.asset_version_id,
            expected.content_hash,
        )
        if actual_lineage != expected_lineage:
            raise KernelError(
                "AGENT_DOMAIN_COMMIT_REPLAY_CONFLICT",
                "existing exact collaboration commit has different lineage",
            )


__all__ = [
    "AgentTurnExecutionCoordinator",
    "ExistingDomainAssetCommit",
    "ExistingDomainAssetCommitPort",
    "agent_turn_identity",
]
