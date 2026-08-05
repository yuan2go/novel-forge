"""Shared Agent-turn execution and exact Domain commit coordination.

The coordinator owns no lifecycle state.  It composes the existing Command
Kernel Attempt/Fence, PEP evidence, collaboration Candidate, and Domain
Authority AssetVersion facts for both embedded and standalone execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from novel_forge.modules.agent_collaboration.application import (
    AgentCollaborationApplication,
    TurnProcessingResult,
)
from novel_forge.modules.agent_collaboration.domain import (
    AgentOutputEnvelope,
    AgentWorkOrder,
    CollaborationDecision,
    CollaborationDecisionType,
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
    """Return one stable identity scheme shared by both scheduling modes."""

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
    """Validate and reference an AssetVersion already written by Domain Authority."""

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
    """One Agent-turn core shared by Chapter and standalone schedulers."""

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
                uow.commit()
            self.fault_injector("after_candidate_persist")
            return result
        except (TypeError, ValueError) as exc:
            raise KernelError("AGENT_CANDIDATE_VALIDATION_FAILED", str(exc)) from exc

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
            environment="production",
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
