"""Deterministic application service for scoped Agent deliberation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Mapping, Protocol

from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionEvidence,
    DomainExecutionPort,
    execute_domain_candidate,
)

from .domain import (
    AgentCollaborationSession,
    AgentConversationMessage,
    AgentMessageType,
    AgentOutputEnvelope,
    AgentWorkOrder,
    CandidateVersion,
    CollaborationDecision,
    CollaborationDecisionType,
    CollaborationStateMachine,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    DomainAcceptance,
    ParticipantSnapshot,
    ScopeExpansionRequest,
    ScopePolicy,
    ScopeSnapshot,
    SessionStatus,
    TerminationContext,
    TerminationEvaluation,
    TerminationPolicy,
)
from .repository import (
    AgentCollaborationRepository,
    CollaborationCommit,
)


class AuthorityAssetCommitPort(Protocol):
    def commit_candidate(
        self,
        *,
        session: AgentCollaborationSession,
        candidate: CandidateVersion,
        decision: CollaborationDecision,
        operation_id: str,
        idempotency_key: str,
    ) -> Mapping[str, str]: ...


@dataclass(frozen=True, slots=True)
class TurnProcessingResult:
    turn_id: str
    backend_success: bool
    output_received: bool
    schema_validation_passed: bool
    scope_validation_passed: bool
    domain_acceptance: DomainAcceptance
    conversation_message_accepted: bool
    message_id: str
    candidate_version_id: str
    conflict_ids: tuple[str, ...]
    authority_decision_ref: str
    authority_commit_ref: str
    attempt_completion_allowed: bool
    violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveredCollaborationSession:
    session: AgentCollaborationSession
    scope_snapshot: ScopeSnapshot
    participant_snapshot: ParticipantSnapshot
    messages: tuple[AgentConversationMessage, ...]
    candidates: tuple[CandidateVersion, ...]
    conflicts: tuple[ConflictRecord, ...]
    decision: CollaborationDecision | None
    commit: CollaborationCommit | None


class AgentCollaborationApplication:
    def __init__(
        self,
        repository: AgentCollaborationRepository,
        *,
        authority_committer: AuthorityAssetCommitPort | None = None,
    ) -> None:
        self.repository = repository
        self.authority_committer = authority_committer

    def create_collaboration_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession:
        if session.status is not SessionStatus.CREATED:
            raise ValueError("new collaboration session must be CREATED")
        return self.repository.create_session(session)

    def freeze_scope(
        self, session_id: str, snapshot: ScopeSnapshot
    ) -> AgentCollaborationSession:
        session = self.repository.get_session(session_id)
        if session.status is not SessionStatus.CREATED:
            if session.scope_snapshot_ref == snapshot.snapshot_id:
                return session
            raise ValueError("scope can only be frozen from CREATED")
        self.repository.save_scope_snapshot(
            snapshot, project_id=session.project_id
        )
        updated = replace(
            CollaborationStateMachine.transition(
                session, SessionStatus.SCOPE_FROZEN
            ),
            scope_snapshot_ref=snapshot.snapshot_id,
        )
        return self.repository.update_session(updated)

    def assign_participants(
        self, session_id: str, snapshot: ParticipantSnapshot
    ) -> AgentCollaborationSession:
        session = self.repository.get_session(session_id)
        if session.status is not SessionStatus.SCOPE_FROZEN:
            if session.participant_snapshot_ref == snapshot.snapshot_id:
                return session
            raise ValueError("participants require a frozen scope")
        self.repository.save_participant_snapshot(
            snapshot, project_id=session.project_id
        )
        updated = replace(
            CollaborationStateMachine.transition(
                session, SessionStatus.PARTICIPANTS_ASSIGNED
            ),
            participant_snapshot_ref=snapshot.snapshot_id,
        )
        return self.repository.update_session(updated)

    def schedule_next_turn(self, work_order: AgentWorkOrder) -> AgentWorkOrder:
        existing = self.repository.find_work_order_by_turn(work_order.turn_id)
        if existing is not None:
            if existing != work_order:
                raise ValueError("turn replay differs from frozen work order")
            return existing
        session = self.repository.get_session(
            work_order.collaboration_session_id
        )
        if work_order.project_id != session.project_id:
            raise ValueError("work order belongs to another project")
        if (
            work_order.scope_snapshot_ref != session.scope_snapshot_ref
            or work_order.participant_snapshot_ref
            != session.participant_snapshot_ref
        ):
            raise ValueError("work order differs from frozen session snapshots")
        scope = self.repository.get_scope_snapshot(
            work_order.scope_snapshot_ref
        )
        if work_order.book_id != scope.contract.narrative.book_id:
            raise ValueError("work order belongs to another book")
        if any(
            not scope.contract.asset_read.allows_version(version_id)
            for version_id in work_order.input_asset_versions
        ):
            raise ValueError("work order input escaped frozen Asset Read Scope")
        participants = self.repository.get_participant_snapshot(
            session.participant_snapshot_ref
        )
        if work_order.agent_id not in {
            item.agent_id for item in participants.participants
        }:
            raise ValueError("work order agent is not a frozen participant")
        if (
            work_order.message_type is AgentMessageType.PROPOSAL
            and session.status is SessionStatus.PARTICIPANTS_ASSIGNED
        ):
            session = CollaborationStateMachine.transition(
                session, SessionStatus.INITIAL_PROPOSAL_PENDING
            )
            self.repository.update_session(session)
        return self.repository.save_work_order(work_order)

    def submit_initial_proposal(
        self, work_order: AgentWorkOrder, envelope: AgentOutputEnvelope
    ) -> TurnProcessingResult:
        if work_order.message_type is not AgentMessageType.PROPOSAL:
            raise ValueError("initial proposal requires PROPOSAL work order")
        self.schedule_next_turn(work_order)
        return self.accept_agent_output(work_order, envelope)

    def execute_turn(
        self,
        work_order: AgentWorkOrder,
        execution_port: DomainExecutionPort,
    ) -> TurnProcessingResult:
        """Execute one frozen turn through PEP before domain acceptance."""

        replay = self.repository.find_processing_result(work_order.turn_id)
        if replay is not None:
            return replay
        self.schedule_next_turn(work_order)
        candidate = execute_domain_candidate(
            capability=work_order.execution_capability,
            operation="analyze",
            candidate_kind=CandidateKind.AGENT_RESULT,
            prompt=(
                "Execute the frozen Agent collaboration work order. Return only "
                "an AgentOutputEnvelope candidate; do not claim Authority commit."
            ),
            context={
                "agent_work_order": work_order.to_context(),
                "commit_authority": "domain_authority_only",
                "scope_is_frozen": True,
                "participant_set_is_frozen": True,
            },
            execution_port=execution_port,
            environment="production",
        )
        if candidate.candidate_kind is not CandidateKind.AGENT_RESULT:
            raise ValueError("PEP returned the wrong candidate kind for Agent turn")
        self._validate_execution_evidence(work_order, candidate.evidence)
        try:
            envelope = AgentOutputEnvelope.from_mapping(
                candidate.raw_output,
                execution_evidence_ref=candidate.evidence.validation_manifest_ref,
            )
        except (TypeError, ValueError) as exc:
            result = TurnProcessingResult(
                turn_id=work_order.turn_id,
                backend_success=True,
                output_received=True,
                schema_validation_passed=False,
                scope_validation_passed=False,
                domain_acceptance=DomainAcceptance.REPAIR_REQUIRED,
                conversation_message_accepted=False,
                message_id="",
                candidate_version_id="",
                conflict_ids=(),
                authority_decision_ref="",
                authority_commit_ref="",
                attempt_completion_allowed=False,
                violations=(f"output_schema:{exc}",),
            )
            return self.repository.save_processing_result(
                work_order.turn_id, result
            )
        return self.accept_agent_output(
            work_order,
            envelope,
            execution_evidence=candidate.evidence,
        )

    def accept_agent_output(
        self,
        work_order: AgentWorkOrder,
        envelope: AgentOutputEnvelope,
        *,
        execution_evidence: DomainExecutionEvidence | None = None,
    ) -> TurnProcessingResult:
        replay = self.repository.find_processing_result(work_order.turn_id)
        if replay is not None:
            existing = self.repository.find_output_by_turn(work_order.turn_id)
            if existing != envelope:
                raise ValueError("duplicate output has different content")
            return replay
        if (
            getattr(self.repository, "production_authority", False)
            and execution_evidence is None
        ):
            raise ValueError(
                "production collaboration output requires PEP execution evidence"
            )
        if execution_evidence is not None:
            self._validate_execution_evidence(work_order, execution_evidence)
            if (
                envelope.execution_evidence_ref
                != execution_evidence.validation_manifest_ref
            ):
                raise ValueError(
                    "Agent output does not reference its PEP validation evidence"
                )
        self._validate_output_identity(work_order, envelope)
        if self.repository.find_work_order_by_turn(work_order.turn_id) is None:
            raise ValueError("Agent output has no scheduled work order")
        session = self.repository.get_session(
            work_order.collaboration_session_id
        )
        scope = self.repository.get_scope_snapshot(
            work_order.scope_snapshot_ref
        )
        validation = ScopePolicy.validate_output(scope, envelope)
        self.repository.save_output(
            envelope,
            schema_validation_status="PASSED",
            scope_validation_status=(
                "PASSED" if validation.compliant else "FAILED"
            ),
        )
        if not validation.compliant:
            session = session.advance_turn(work_order.turn_id)
            session = CollaborationStateMachine.transition(
                session, SessionStatus.SCOPE_VIOLATION
            )
            self.repository.update_session(session)
            result = TurnProcessingResult(
                turn_id=work_order.turn_id,
                backend_success=True,
                output_received=True,
                schema_validation_passed=True,
                scope_validation_passed=False,
                domain_acceptance=DomainAcceptance.REPLAN_REQUIRED,
                conversation_message_accepted=False,
                message_id="",
                candidate_version_id="",
                conflict_ids=(),
                authority_decision_ref="",
                authority_commit_ref="",
                attempt_completion_allowed=False,
                violations=validation.violations,
            )
            return self.repository.save_processing_result(
                work_order.turn_id, result
            )

        message = self._message(work_order, envelope)
        self.repository.save_message(message)
        candidate = self._candidate(work_order, envelope, message)
        if candidate is not None:
            self.repository.save_candidate(candidate)
            if candidate.resolved_conflicts:
                self.repository.resolve_conflicts(
                    candidate.resolved_conflicts,
                    resolution_ref=candidate.candidate_version_id,
                )
        conflicts = self._conflicts(work_order, envelope)
        for conflict in conflicts:
            self.repository.save_conflict(conflict)

        session = session.advance_turn(work_order.turn_id)
        session = self._advance_after_message(
            session, envelope, candidate
        )
        self.repository.update_session(session)
        result = TurnProcessingResult(
            turn_id=work_order.turn_id,
            backend_success=True,
            output_received=True,
            schema_validation_passed=True,
            scope_validation_passed=True,
            domain_acceptance=DomainAcceptance.ACCEPTED,
            conversation_message_accepted=True,
            message_id=message.message_id,
            candidate_version_id=(
                "" if candidate is None else candidate.candidate_version_id
            ),
            conflict_ids=tuple(item.conflict_id for item in conflicts),
            authority_decision_ref="",
            authority_commit_ref="",
            attempt_completion_allowed=True,
        )
        return self.repository.save_processing_result(
            work_order.turn_id, result
        )

    def raise_challenge(
        self, work_order: AgentWorkOrder, envelope: AgentOutputEnvelope
    ) -> TurnProcessingResult:
        if work_order.message_type not in {
            AgentMessageType.CHALLENGE,
            AgentMessageType.OBJECTION,
            AgentMessageType.COUNTER_PROPOSAL,
        }:
            raise ValueError("challenge service requires a challenge message")
        self.schedule_next_turn(work_order)
        return self.accept_agent_output(work_order, envelope)

    def create_candidate_revision(
        self, work_order: AgentWorkOrder, envelope: AgentOutputEnvelope
    ) -> TurnProcessingResult:
        if work_order.message_type is not AgentMessageType.REVISION:
            raise ValueError("candidate revision requires REVISION")
        self.schedule_next_turn(work_order)
        return self.accept_agent_output(work_order, envelope)

    def record_conflict(self, conflict: ConflictRecord) -> ConflictRecord:
        return self.repository.save_conflict(conflict)

    def request_scope_expansion(
        self, request: ScopeExpansionRequest
    ) -> ScopeExpansionRequest:
        session = self.repository.get_session(request.session_id)
        if request.current_scope_snapshot_ref != session.scope_snapshot_ref:
            raise ValueError("scope expansion does not bind current snapshot")
        current = self.repository.get_scope_snapshot(
            session.scope_snapshot_ref
        ).contract.narrative
        if (
            request.requested_scope == current
            or not request.requested_scope.contains(current)
        ):
            raise ValueError(
                "scope expansion must request a strict containing narrative scope"
            )
        participants = self.repository.get_participant_snapshot(
            session.participant_snapshot_ref
        )
        if request.requesting_agent not in {
            item.agent_id for item in participants.participants
        }:
            raise PermissionError(
                "scope expansion requester is not a frozen participant"
            )
        if request.decision != "PENDING" or request.decision_ref:
            raise ValueError("new scope expansion request must be pending")
        stored = self.repository.save_scope_expansion_request(request)
        self.repository.update_session(
            CollaborationStateMachine.transition(
                session, SessionStatus.ESCALATED
            )
        )
        return stored

    def decide_scope_expansion(
        self,
        request_id: str,
        decision: CollaborationDecision,
        *,
        approved_scope_snapshot: ScopeSnapshot | None = None,
    ) -> ScopeExpansionRequest:
        requests = self.repository.scope_expansion_requests(
            decision.session_id
        )
        request = next(
            (item for item in requests if item.request_id == request_id),
            None,
        )
        if request is None:
            raise ValueError("scope expansion request is not available")
        session = self.repository.get_session(request.session_id)
        if session.status is not SessionStatus.ESCALATED:
            raise ValueError("scope expansion session is not escalated")
        if decision.session_id != request.session_id:
            raise ValueError("scope expansion decision belongs to another session")
        if decision.authority_type != request.required_authority:
            raise PermissionError(
                "scope expansion decision uses the wrong Authority"
            )
        allowed = {
            CollaborationDecisionType.SCOPE_EXPANSION_APPROVED,
            CollaborationDecisionType.SCOPE_EXPANSION_REJECTED,
        }
        if decision.decision not in allowed:
            raise ValueError("scope expansion requires an expansion decision")
        if (
            decision.decision
            is CollaborationDecisionType.SCOPE_EXPANSION_APPROVED
        ):
            if approved_scope_snapshot is None:
                raise ValueError(
                    "approved scope expansion requires a new ScopeSnapshot"
                )
            contract = approved_scope_snapshot.contract
            if (
                contract.narrative != request.requested_scope
                or contract.authority.authority_type
                != request.required_authority
            ):
                raise ValueError(
                    "approved ScopeSnapshot differs from the reviewed request"
                )
            self.repository.save_scope_snapshot(
                approved_scope_snapshot,
                project_id=session.project_id,
            )
        elif approved_scope_snapshot is not None:
            raise ValueError(
                "rejected scope expansion cannot create a new ScopeSnapshot"
            )
        self.repository.save_decision(decision)
        resolved = self.repository.resolve_scope_expansion_request(
            request_id,
            decision=decision.decision.value,
            decision_ref=decision.decision_id,
        )
        updated = replace(
            session,
            authority_decision_ref=decision.decision_id,
        )
        if (
            decision.decision
            is CollaborationDecisionType.SCOPE_EXPANSION_REJECTED
        ):
            updated = CollaborationStateMachine.transition(
                updated, SessionStatus.REJECTED
            )
        self.repository.update_session(updated)
        return resolved

    def evaluate_termination(
        self, session_id: str, policy: TerminationPolicy
    ) -> TerminationEvaluation:
        session = self.repository.get_session(session_id)
        participants = self.repository.get_participant_snapshot(
            session.participant_snapshot_ref
        )
        messages = self.repository.messages(session_id)
        roles = frozenset(item.role for item in participants.participants)
        agent_roles = {
            item.agent_id: item.role for item in participants.participants
        }
        evaluation_roles = frozenset(
            agent_roles.get(message.sender_id, "")
            for message in messages
            if message.message_type is AgentMessageType.EVALUATION
        )
        conflicts = self.repository.conflicts(session_id)
        evaluation = policy.evaluate(
            TerminationContext(
                round_number=session.round_number,
                turn_number=session.turn_number,
                execution_count=session.execution_count,
                spent_budget=session.spent_budget,
                participant_roles=roles,
                evaluation_roles=evaluation_roles,
                blocking_conflicts=sum(item.is_blocking for item in conflicts),
                major_issues=sum(
                    item.severity is ConflictSeverity.MAJOR
                    and item.status is ConflictStatus.OPEN
                    for item in conflicts
                ),
                scope_violations=(
                    1 if session.status is SessionStatus.SCOPE_VIOLATION else 0
                ),
                human_decision_required=(
                    session.status is SessionStatus.HUMAN_DECISION_REQUIRED
                ),
            )
        )
        if evaluation.must_stop and evaluation.recommended_status is not None:
            self.repository.update_session(
                CollaborationStateMachine.transition(
                    session, evaluation.recommended_status
                )
            )
        return evaluation

    def request_authority_decision(
        self, session_id: str
    ) -> AgentCollaborationSession:
        session = self.repository.get_session(session_id)
        if any(item.is_blocking for item in self.repository.conflicts(session_id)):
            raise ValueError("blocking conflict prevents Authority decision request")
        updated = CollaborationStateMachine.transition(
            session, SessionStatus.AUTHORITY_DECISION_PENDING
        )
        return self.repository.update_session(updated)

    def apply_authority_decision(
        self, decision: CollaborationDecision
    ) -> AgentCollaborationSession:
        session = self.repository.get_session(decision.session_id)
        if session.status is not SessionStatus.AUTHORITY_DECISION_PENDING:
            raise ValueError("session is not waiting for Authority decision")
        scope = self.repository.get_scope_snapshot(
            session.scope_snapshot_ref
        )
        if (
            decision.authority_type
            != scope.contract.authority.authority_type
        ):
            raise PermissionError("decision Authority is outside frozen scope")
        self.repository.get_candidate(decision.candidate_version_id)
        decision.validate_against(self.repository.conflicts(decision.session_id))
        self.repository.save_decision(decision)
        conflict_status = {
            CollaborationDecisionType.ACCEPTED:
                ConflictStatus.ACCEPTED_NON_BLOCKING,
            CollaborationDecisionType.REJECTED: ConflictStatus.REJECTED,
            CollaborationDecisionType.REPAIR_REQUIRED: ConflictStatus.DEFERRED,
            CollaborationDecisionType.REPLAN_REQUIRED: ConflictStatus.DEFERRED,
            CollaborationDecisionType.HUMAN_DECISION_REQUIRED:
                ConflictStatus.DEFERRED,
            CollaborationDecisionType.DEFERRED: ConflictStatus.DEFERRED,
        }.get(decision.decision)
        if conflict_status is not None:
            self.repository.apply_conflict_decision(
                decision.session_id,
                decision_ref=decision.decision_id,
                status=conflict_status,
            )
        target = {
            CollaborationDecisionType.ACCEPTED: SessionStatus.ACCEPTED,
            CollaborationDecisionType.REJECTED: SessionStatus.REJECTED,
            CollaborationDecisionType.REPAIR_REQUIRED: SessionStatus.REVISION_PENDING,
            CollaborationDecisionType.REPLAN_REQUIRED: SessionStatus.ESCALATED,
            CollaborationDecisionType.HUMAN_DECISION_REQUIRED:
                SessionStatus.HUMAN_DECISION_REQUIRED,
            CollaborationDecisionType.DEFERRED: SessionStatus.ESCALATED,
            CollaborationDecisionType.SCOPE_EXPANSION_APPROVED:
                SessionStatus.ESCALATED,
            CollaborationDecisionType.SCOPE_EXPANSION_REJECTED:
                SessionStatus.REJECTED,
        }[decision.decision]
        updated = replace(
            CollaborationStateMachine.transition(session, target),
            authority_decision_ref=decision.decision_id,
        )
        return self.repository.update_session(updated)

    def commit_accepted_candidate(
        self,
        session_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> CollaborationCommit:
        existing = self.repository.find_commit(session_id)
        if existing is not None:
            if (
                existing.operation_id != operation_id
                or existing.stable_idempotency_key != idempotency_key
            ):
                raise ValueError("commit replay differs from accepted commit")
            return existing
        session = self.repository.get_session(session_id)
        if session.status is not SessionStatus.ACCEPTED:
            raise ValueError("only an accepted session can commit")
        if self.authority_committer is None:
            raise RuntimeError("Authority Asset commit port is required")
        decision = self.repository.get_decision(
            session.authority_decision_ref
        )
        candidate = self.repository.get_candidate(
            decision.candidate_version_id
        )
        if any(item.is_blocking for item in self.repository.conflicts(session_id)):
            raise ValueError("blocking conflict prevents Authority commit")
        external = self.authority_committer.commit_candidate(
            session=session,
            candidate=candidate,
            decision=decision,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
        )
        commit = CollaborationCommit(
            commit_id=str(external.get("commit_id") or ""),
            session_id=session_id,
            decision_id=decision.decision_id,
            candidate_version_id=candidate.candidate_version_id,
            operation_id=operation_id,
            asset_version_id=str(external.get("asset_version_id") or ""),
            stable_idempotency_key=idempotency_key,
            source_lineage=self.repository.candidate_lineage(
                candidate.candidate_version_id
            ),
            receipt_ref=str(external.get("receipt_ref") or ""),
        )
        if not commit.commit_id or not commit.asset_version_id:
            raise ValueError("Authority commit did not return versioned asset evidence")
        stored = self.repository.save_commit(commit)
        self.repository.update_session(
            CollaborationStateMachine.transition(
                session, SessionStatus.COMMITTED
            )
        )
        return stored

    def recover_collaboration_session(
        self, session_id: str
    ) -> RecoveredCollaborationSession:
        session = self.repository.get_session(session_id)
        decision = (
            None
            if not session.authority_decision_ref
            else self.repository.get_decision(session.authority_decision_ref)
        )
        return RecoveredCollaborationSession(
            session=session,
            scope_snapshot=self.repository.get_scope_snapshot(
                session.scope_snapshot_ref
            ),
            participant_snapshot=self.repository.get_participant_snapshot(
                session.participant_snapshot_ref
            ),
            messages=self.repository.messages(session_id),
            candidates=self.repository.candidates(session_id),
            conflicts=self.repository.conflicts(session_id),
            decision=decision,
            commit=self.repository.find_commit(session_id),
        )

    def cancel_collaboration_session(
        self, session_id: str
    ) -> AgentCollaborationSession:
        session = self.repository.get_session(session_id)
        updated = CollaborationStateMachine.transition(
            session, SessionStatus.CANCELLED
        )
        return self.repository.update_session(updated)

    def _message(
        self,
        work_order: AgentWorkOrder,
        envelope: AgentOutputEnvelope,
    ) -> AgentConversationMessage:
        payload = envelope.structured_payload
        participants = self.repository.get_participant_snapshot(
            work_order.participant_snapshot_ref
        )
        previous = self.repository.messages(
            work_order.collaboration_session_id
        )
        return AgentConversationMessage(
            message_id=str(
                payload.get("message_id")
                or f"message:{work_order.turn_id.split(':')[-1]}"
            ),
            session_id=work_order.collaboration_session_id,
            turn_id=work_order.turn_id,
            message_type=envelope.message_type,
            sender_id=envelope.agent_id,
            recipient_ids=tuple(
                item.agent_id
                for item in participants.participants
                if item.agent_id != envelope.agent_id
            ),
            target_proposal_id=str(payload.get("target_proposal_id") or ""),
            target_candidate_version_id=str(
                payload.get("target_candidate_version_id")
                or work_order.candidate_version_ref
                or ""
            ),
            scope_snapshot_ref=work_order.scope_snapshot_ref,
            evidence_refs=envelope.evidence_refs,
            parent_message_id=(
                str(payload.get("parent_message_id") or "")
                or (previous[-1].message_id if previous else "")
            ),
            structured_payload=envelope.structured_payload,
            natural_language=envelope.natural_language_explanation,
        )

    @staticmethod
    def _candidate(
        work_order: AgentWorkOrder,
        envelope: AgentOutputEnvelope,
        message: AgentConversationMessage,
    ) -> CandidateVersion | None:
        if envelope.message_type not in {
            AgentMessageType.PROPOSAL,
            AgentMessageType.COUNTER_PROPOSAL,
            AgentMessageType.REVISION,
        }:
            return None
        payload = envelope.structured_payload
        parent: tuple[str, ...] = (
            str(
                payload.get("target_candidate_version_id")
                or work_order.candidate_version_ref
                or ""
            ),
        )
        if not parent[0]:
            parent = ()
        raw_diff = payload.get("structured_diff")
        return CandidateVersion(
            candidate_version_id=str(payload.get("candidate_version_id") or ""),
            session_id=work_order.collaboration_session_id,
            candidate_type=str(payload.get("candidate_type") or ""),
            parent_version_ids=parent,
            originating_message_id=message.message_id,
            originating_turn_id=work_order.turn_id,
            created_by_agent=envelope.agent_id,
            scope_snapshot_ref=work_order.scope_snapshot_ref,
            content_ref=str(payload.get("content_ref") or ""),
            structured_diff=(
                dict(raw_diff) if isinstance(raw_diff, Mapping) else {}
            ),
            change_reason_refs=tuple(
                str(item)
                for item in payload.get("change_reason_refs") or ()
            ),
            preserved_constraints=envelope.preserved_constraints,
            resolved_conflicts=tuple(
                str(item) for item in payload.get("resolved_conflicts") or ()
            ),
            unresolved_conflicts=tuple(
                str(item) for item in payload.get("unresolved_conflicts") or ()
            ),
            validation_status="VALID",
        )

    @staticmethod
    def _conflicts(
        work_order: AgentWorkOrder,
        envelope: AgentOutputEnvelope,
    ) -> tuple[ConflictRecord, ...]:
        payload = envelope.structured_payload.get("conflict")
        if not isinstance(payload, Mapping) or not payload:
            return ()
        target = str(
            envelope.structured_payload.get("target_candidate_version_id")
            or work_order.candidate_version_ref
            or ""
        )
        return (
            ConflictRecord(
                conflict_id=str(payload.get("conflict_id") or ""),
                session_id=work_order.collaboration_session_id,
                conflict_type=str(payload.get("conflict_type") or ""),
                severity=ConflictSeverity(
                    str(payload.get("severity") or "")
                ),
                raised_by=envelope.agent_id,
                target_candidate_version=target,
                conflicting_asset_versions=tuple(
                    str(item)
                    for item in payload.get("conflicting_asset_versions") or ()
                ),
                claim=str(payload.get("claim") or ""),
                evidence_refs=envelope.evidence_refs,
                affected_scopes=tuple(
                    str(item) for item in payload.get("affected_scopes") or ()
                ),
                affected_assets=tuple(
                    str(item) for item in payload.get("affected_assets") or ()
                ),
                reader_outcome_impact=str(
                    payload.get("reader_outcome_impact") or ""
                ),
                continuity_impact=str(payload.get("continuity_impact") or ""),
                ending_reachability_impact=str(
                    payload.get("ending_reachability_impact") or ""
                ),
                requested_resolution=str(
                    payload.get("requested_resolution") or ""
                ),
                status=ConflictStatus.OPEN,
                resolution_ref="",
                authority_decision_ref="",
            ),
        )

    def _advance_after_message(
        self,
        session: AgentCollaborationSession,
        envelope: AgentOutputEnvelope,
        candidate: CandidateVersion | None,
    ) -> AgentCollaborationSession:
        message_type = envelope.message_type
        if message_type is AgentMessageType.PROPOSAL:
            session = replace(
                session,
                round_number=max(1, session.round_number),
                current_candidate_version_ref=candidate.candidate_version_id
                if candidate
                else session.current_candidate_version_ref,
            )
            return CollaborationStateMachine.transition(
                session, SessionStatus.DELIBERATING
            )
        if message_type in {
            AgentMessageType.CHALLENGE,
            AgentMessageType.OBJECTION,
        }:
            return CollaborationStateMachine.transition(
                session, SessionStatus.REVISION_PENDING
            )
        if message_type is AgentMessageType.COUNTER_PROPOSAL:
            session = replace(
                session,
                current_candidate_version_ref=candidate.candidate_version_id
                if candidate
                else session.current_candidate_version_ref,
            )
            return CollaborationStateMachine.transition(
                session, SessionStatus.REVISION_PENDING
            )
        if message_type is AgentMessageType.REVISION:
            session = replace(
                session,
                current_candidate_version_ref=candidate.candidate_version_id
                if candidate
                else session.current_candidate_version_ref,
            )
            return CollaborationStateMachine.transition(
                session, SessionStatus.EVALUATING
            )
        if message_type is AgentMessageType.EVALUATION:
            recommendation = str(
                envelope.structured_payload.get("recommendation") or ""
            )
            blocking = any(
                item.is_blocking
                for item in self.repository.conflicts(session.session_id)
            )
            target = (
                SessionStatus.CONSENSUS_REACHED
                if recommendation.startswith("ACCEPT") and not blocking
                else SessionStatus.REVISION_PENDING
            )
            return CollaborationStateMachine.transition(session, target)
        return session

    @staticmethod
    def _validate_execution_evidence(
        work_order: AgentWorkOrder,
        evidence: DomainExecutionEvidence,
    ) -> None:
        expected = (
            work_order.operation_id,
            work_order.attempt_id,
            work_order.fencing_token,
            work_order.execution_capability,
        )
        actual = (
            evidence.operation_id,
            evidence.attempt_id,
            evidence.fencing_token,
            evidence.capability,
        )
        if actual != expected:
            raise ValueError(
                "PEP execution evidence differs from the frozen Agent work order"
            )
        if not all(
            (
                evidence.execution_id,
                evidence.route_snapshot_id,
                evidence.output_manifest_ref,
                evidence.validation_manifest_ref,
                evidence.usage_receipt_ref,
                evidence.cost_receipt_ref,
            )
        ):
            raise ValueError("PEP execution evidence is incomplete")
        if (
            evidence.route_snapshot_id != work_order.route_snapshot_ref
            or evidence.input_manifest_ref != work_order.input_manifest_ref
        ):
            raise ValueError(
                "PEP route or input manifest differs from frozen Agent work order"
            )

    @staticmethod
    def _validate_output_identity(
        work_order: AgentWorkOrder, envelope: AgentOutputEnvelope
    ) -> None:
        expected = (
            work_order.collaboration_session_id,
            work_order.turn_id,
            work_order.agent_id,
            work_order.message_type,
        )
        actual = (
            envelope.session_id,
            envelope.turn_id,
            envelope.agent_id,
            envelope.message_type,
        )
        if actual != expected:
            raise ValueError("Agent output identity differs from frozen work order")


__all__ = [
    "AgentCollaborationApplication",
    "AuthorityAssetCommitPort",
    "RecoveredCollaborationSession",
    "TurnProcessingResult",
]
