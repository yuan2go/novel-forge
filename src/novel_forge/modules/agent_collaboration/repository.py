from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from .domain import (
    AgentCollaborationSession,
    AgentConversationMessage,
    AgentOutputEnvelope,
    AgentWorkOrder,
    CandidateVersion,
    CollaborationDecision,
    ConflictRecord,
    ConflictStatus,
    ParticipantSnapshot,
    ScopeExpansionRequest,
    ScopeSnapshot,
)


class AgentCollaborationRepository(Protocol):
    def create_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession: ...

    def get_session(self, session_id: str) -> AgentCollaborationSession: ...

    def update_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession: ...

    def save_scope_snapshot(
        self, snapshot: ScopeSnapshot, *, project_id: str = ""
    ) -> ScopeSnapshot: ...

    def get_scope_snapshot(self, snapshot_id: str) -> ScopeSnapshot: ...

    def save_participant_snapshot(
        self, snapshot: ParticipantSnapshot, *, project_id: str = ""
    ) -> ParticipantSnapshot: ...

    def get_participant_snapshot(
        self, snapshot_id: str
    ) -> ParticipantSnapshot: ...

    def save_work_order(self, work_order: AgentWorkOrder) -> AgentWorkOrder: ...

    def get_work_order(self, work_order_id: str) -> AgentWorkOrder: ...

    def find_work_order_by_turn(self, turn_id: str) -> AgentWorkOrder | None: ...

    def save_output(
        self,
        envelope: AgentOutputEnvelope,
        *,
        schema_validation_status: str = "PASSED",
        scope_validation_status: str = "PASSED",
    ) -> AgentOutputEnvelope: ...

    def find_output_by_turn(self, turn_id: str) -> AgentOutputEnvelope | None: ...

    def save_message(
        self, message: AgentConversationMessage
    ) -> AgentConversationMessage: ...

    def messages(self, session_id: str) -> tuple[AgentConversationMessage, ...]: ...

    def save_candidate(self, candidate: CandidateVersion) -> CandidateVersion: ...

    def get_candidate(self, candidate_id: str) -> CandidateVersion: ...

    def candidates(self, session_id: str) -> tuple[CandidateVersion, ...]: ...

    def candidate_lineage(self, candidate_id: str) -> tuple[str, ...]: ...

    def save_conflict(self, conflict: ConflictRecord) -> ConflictRecord: ...

    def get_conflict(self, conflict_id: str) -> ConflictRecord: ...

    def conflicts(self, session_id: str) -> tuple[ConflictRecord, ...]: ...

    def resolve_conflicts(
        self, conflict_ids: tuple[str, ...], *, resolution_ref: str
    ) -> tuple[ConflictRecord, ...]: ...

    def apply_conflict_decision(
        self,
        session_id: str,
        *,
        decision_ref: str,
        status: ConflictStatus,
    ) -> tuple[ConflictRecord, ...]: ...

    def save_scope_expansion_request(
        self, request: ScopeExpansionRequest
    ) -> ScopeExpansionRequest: ...

    def scope_expansion_requests(
        self, session_id: str
    ) -> tuple[ScopeExpansionRequest, ...]: ...

    def resolve_scope_expansion_request(
        self,
        request_id: str,
        *,
        decision: str,
        decision_ref: str,
    ) -> ScopeExpansionRequest: ...

    def save_decision(
        self, decision: CollaborationDecision
    ) -> CollaborationDecision: ...

    def get_decision(self, decision_id: str) -> CollaborationDecision: ...

    def save_commit(self, commit: CollaborationCommit) -> CollaborationCommit: ...

    def find_commit(self, session_id: str) -> CollaborationCommit | None: ...

    def save_processing_result(
        self, turn_id: str, result: Any
    ) -> Any: ...

    def find_processing_result(self, turn_id: str) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class CollaborationCommit:
    commit_id: str
    session_id: str
    decision_id: str
    candidate_version_id: str
    operation_id: str
    asset_version_id: str
    stable_idempotency_key: str
    source_lineage: tuple[str, ...]
    receipt_ref: str
    attempt_id: str = ""
    fencing_token: int = 0
    content_hash: str = ""


class InMemoryAgentCollaborationRepository:

    production_authority = False

    def __init__(self) -> None:
        self._sessions: dict[str, AgentCollaborationSession] = {}
        self._scopes: dict[str, ScopeSnapshot] = {}
        self._participants: dict[str, ParticipantSnapshot] = {}
        self._work_orders: dict[str, AgentWorkOrder] = {}
        self._turn_work_orders: dict[str, str] = {}
        self._outputs: dict[str, AgentOutputEnvelope] = {}
        self._turn_outputs: dict[str, str] = {}
        self._messages: dict[str, AgentConversationMessage] = {}
        self._candidates: dict[str, CandidateVersion] = {}
        self._conflicts: dict[str, ConflictRecord] = {}
        self._expansions: dict[str, ScopeExpansionRequest] = {}
        self._decisions: dict[str, CollaborationDecision] = {}
        self._commits: dict[str, CollaborationCommit] = {}
        self._processing_results: dict[str, Any] = {}

    def create_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession:
        return self._put_immutable(self._sessions, session.session_id, session)

    def get_session(self, session_id: str) -> AgentCollaborationSession:
        return self._require(self._sessions, session_id, "session")

    def update_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession:
        current = self.get_session(session.session_id)
        if current.persistence_version != session.persistence_version:
            raise ValueError("collaboration session version is stale")
        updated = replace(
            session, persistence_version=session.persistence_version + 1
        )
        self._sessions[session.session_id] = updated
        return updated

    def save_scope_snapshot(
        self, snapshot: ScopeSnapshot, *, project_id: str = ""
    ) -> ScopeSnapshot:
        del project_id
        return self._put_immutable(
            self._scopes, snapshot.snapshot_id, snapshot
        )

    def get_scope_snapshot(self, snapshot_id: str) -> ScopeSnapshot:
        return self._require(self._scopes, snapshot_id, "scope snapshot")

    def save_participant_snapshot(
        self, snapshot: ParticipantSnapshot, *, project_id: str = ""
    ) -> ParticipantSnapshot:
        del project_id
        return self._put_immutable(
            self._participants, snapshot.snapshot_id, snapshot
        )

    def get_participant_snapshot(
        self, snapshot_id: str
    ) -> ParticipantSnapshot:
        return self._require(
            self._participants, snapshot_id, "participant snapshot"
        )

    def save_work_order(self, work_order: AgentWorkOrder) -> AgentWorkOrder:
        existing_id = self._turn_work_orders.get(work_order.turn_id)
        if existing_id:
            existing = self._work_orders[existing_id]
            if existing != work_order:
                raise ValueError("turn already has a different work order")
            return existing
        stored = self._put_immutable(
            self._work_orders, work_order.work_order_id, work_order
        )
        self._turn_work_orders[work_order.turn_id] = work_order.work_order_id
        return stored

    def get_work_order(self, work_order_id: str) -> AgentWorkOrder:
        return self._require(self._work_orders, work_order_id, "work order")

    def find_work_order_by_turn(self, turn_id: str) -> AgentWorkOrder | None:
        identity = self._turn_work_orders.get(turn_id)
        return None if identity is None else self._work_orders[identity]

    def save_output(
        self,
        envelope: AgentOutputEnvelope,
        *,
        schema_validation_status: str = "PASSED",
        scope_validation_status: str = "PASSED",
    ) -> AgentOutputEnvelope:
        del schema_validation_status, scope_validation_status
        existing_id = self._turn_outputs.get(envelope.turn_id)
        if existing_id:
            existing = self._outputs[existing_id]
            if existing != envelope:
                raise ValueError("turn output replay has different content")
            return existing
        stored = self._put_immutable(
            self._outputs, envelope.output_id, envelope
        )
        self._turn_outputs[envelope.turn_id] = envelope.output_id
        return stored

    def find_output_by_turn(self, turn_id: str) -> AgentOutputEnvelope | None:
        identity = self._turn_outputs.get(turn_id)
        return None if identity is None else self._outputs[identity]

    def save_message(
        self, message: AgentConversationMessage
    ) -> AgentConversationMessage:
        if any(item.turn_id == message.turn_id for item in self._messages.values()):
            existing = next(
                item
                for item in self._messages.values()
                if item.turn_id == message.turn_id
            )
            if existing != message:
                raise ValueError("turn already has a different message")
            return existing
        return self._put_immutable(
            self._messages, message.message_id, message
        )

    def messages(self, session_id: str) -> tuple[AgentConversationMessage, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._messages.values()
                    if item.session_id == session_id
                ),
                key=lambda item: item.turn_id,
            )
        )

    def save_candidate(self, candidate: CandidateVersion) -> CandidateVersion:
        for parent_id in candidate.parent_version_ids:
            if parent_id not in self._candidates:
                raise ValueError(
                    f"candidate parent does not exist: {parent_id}"
                )
            if (
                candidate.candidate_version_id
                in self.candidate_lineage(parent_id)
            ):
                raise ValueError("candidate graph cycle is forbidden")
        return self._put_immutable(
            self._candidates,
            candidate.candidate_version_id,
            candidate,
        )

    def get_candidate(self, candidate_id: str) -> CandidateVersion:
        return self._require(self._candidates, candidate_id, "candidate")

    def candidates(self, session_id: str) -> tuple[CandidateVersion, ...]:
        return tuple(
            item
            for item in self._candidates.values()
            if item.session_id == session_id
        )

    def candidate_lineage(self, candidate_id: str) -> tuple[str, ...]:
        candidate = self.get_candidate(candidate_id)
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(identity: str) -> None:
            if identity in visited:
                return
            node = self.get_candidate(identity)
            for parent_id in node.parent_version_ids:
                visit(parent_id)
            visited.add(identity)
            ordered.append(identity)

        visit(candidate.candidate_version_id)
        return tuple(ordered)

    def save_conflict(self, conflict: ConflictRecord) -> ConflictRecord:
        return self._put_immutable(
            self._conflicts, conflict.conflict_id, conflict
        )

    def get_conflict(self, conflict_id: str) -> ConflictRecord:
        return self._require(self._conflicts, conflict_id, "conflict")

    def conflicts(self, session_id: str) -> tuple[ConflictRecord, ...]:
        return tuple(
            item
            for item in self._conflicts.values()
            if item.session_id == session_id
        )

    def resolve_conflicts(
        self, conflict_ids: tuple[str, ...], *, resolution_ref: str
    ) -> tuple[ConflictRecord, ...]:
        from dataclasses import replace

        resolved = []
        for conflict_id in conflict_ids:
            conflict = self.get_conflict(conflict_id)
            updated = replace(
                conflict,
                status=ConflictStatus.RESOLVED,
                resolution_ref=resolution_ref,
            )
            self._conflicts[conflict_id] = updated
            resolved.append(updated)
        return tuple(resolved)

    def apply_conflict_decision(
        self,
        session_id: str,
        *,
        decision_ref: str,
        status: ConflictStatus,
    ) -> tuple[ConflictRecord, ...]:
        updated = []
        for conflict in self.conflicts(session_id):
            if conflict.status is not ConflictStatus.OPEN:
                continue
            resolved = replace(
                conflict,
                status=status,
                authority_decision_ref=decision_ref,
            )
            self._conflicts[conflict.conflict_id] = resolved
            updated.append(resolved)
        return tuple(updated)

    def save_scope_expansion_request(
        self, request: ScopeExpansionRequest
    ) -> ScopeExpansionRequest:
        return self._put_immutable(
            self._expansions, request.request_id, request
        )

    def scope_expansion_requests(
        self, session_id: str
    ) -> tuple[ScopeExpansionRequest, ...]:
        return tuple(
            item
            for item in self._expansions.values()
            if item.session_id == session_id
        )

    def resolve_scope_expansion_request(
        self,
        request_id: str,
        *,
        decision: str,
        decision_ref: str,
    ) -> ScopeExpansionRequest:
        request = self._require(
            self._expansions, request_id, "scope expansion request"
        )
        updated = replace(
            request,
            decision=decision,
            decision_ref=decision_ref,
        )
        if request.decision != "PENDING" and request != updated:
            raise ValueError(
                "scope expansion request already has a different decision"
            )
        self._expansions[request_id] = updated
        return updated

    def save_decision(
        self, decision: CollaborationDecision
    ) -> CollaborationDecision:
        return self._put_immutable(
            self._decisions, decision.decision_id, decision
        )

    def get_decision(self, decision_id: str) -> CollaborationDecision:
        return self._require(self._decisions, decision_id, "decision")

    def save_commit(self, commit: CollaborationCommit) -> CollaborationCommit:
        existing = self._commits.get(commit.session_id)
        if existing is not None:
            if existing != commit:
                raise ValueError("collaboration commit replay has different content")
            return existing
        self._commits[commit.session_id] = commit
        return commit

    def find_commit(self, session_id: str) -> CollaborationCommit | None:
        return self._commits.get(session_id)

    def save_processing_result(self, turn_id: str, result: Any) -> Any:
        existing = self._processing_results.get(turn_id)
        if existing is not None and existing != result:
            raise ValueError("turn processing result has different content")
        self._processing_results[turn_id] = result
        return result

    def find_processing_result(self, turn_id: str) -> Any | None:
        return self._processing_results.get(turn_id)

    @staticmethod
    def _put_immutable(
        target: dict[str, Any], identity: str, value: Any
    ) -> Any:
        existing = target.get(identity)
        if existing is not None:
            if existing != value:
                raise ValueError(f"{identity} replay has different content")
            return existing
        target[identity] = value
        return value

    @staticmethod
    def _require(target: dict[str, Any], identity: str, label: str) -> Any:
        try:
            return target[identity]
        except KeyError as exc:
            raise ValueError(f"{label} is not available: {identity}") from exc


__all__ = [
    "AgentCollaborationRepository",
    "CollaborationCommit",
    "InMemoryAgentCollaborationRepository",
]
