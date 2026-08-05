"""PostgreSQL Authority repository for scoped Agent collaboration."""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from psycopg.types.json import Jsonb

from novel_forge.modules.agent_collaboration.domain import (
    AgentCapability,
    AgentCollaborationSession,
    AgentConversationMessage,
    AgentDefinition,
    AgentOutputEnvelope,
    AgentScopeContract,
    AgentWorkOrder,
    AssetReadScope,
    AuthorityScope,
    CandidateVersion,
    CollaborationDecision,
    ConflictRecord,
    ConflictStatus,
    DomainAcceptance,
    KnowledgeVisibilityScope,
    NarrativeScope,
    Participant,
    ParticipantSnapshot,
    ProposalScope,
    ProposedAssetChange,
    ScopeExpansionRequest,
    ScopeSnapshot,
    TemporalScope,
)
from novel_forge.modules.agent_collaboration.repository import CollaborationCommit
from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocumentRepository,
)


class PostgresAgentCollaborationRepository:
    """Cursor-bound repository intended for an existing AuthorityUnitOfWork."""

    production_authority = True

    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def register_capability(
        self, capability: AgentCapability
    ) -> AgentCapability:
        payload = _plain(capability)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_capability (
                capability_id, capability_version, domain,
                input_schema_ref, output_schema_ref,
                supported_message_types, supported_scope_types,
                risk_class, execution_requirements, qualification_status,
                capability_hash
            ) VALUES (
                %(capability_id)s, %(version)s, %(domain)s,
                %(input_schema_ref)s, %(output_schema_ref)s,
                %(supported_message_types)s, %(supported_scope_types)s,
                %(risk_class)s, %(execution_requirements)s,
                %(qualification_status)s, %(capability_hash)s
            )
            ON CONFLICT (capability_id, capability_version) DO NOTHING
            """,
            {
                **payload,
                "execution_requirements": Jsonb(
                    payload["execution_requirements"]
                ),
                "capability_hash": capability.capability_hash,
            },
        )
        self.cursor.execute(
            """
            SELECT capability_hash
            FROM authority_agent_capability
            WHERE capability_id = %s AND capability_version = %s
            """,
            [capability.capability_id, capability.version],
        )
        if self.cursor.fetchone()[0] != capability.capability_hash:
            raise ValueError("AgentCapability version has different content")
        return capability

    def register_definition(
        self, definition: AgentDefinition
    ) -> AgentDefinition:
        payload = _plain(definition)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_definition (
                agent_id, definition_version, agent_type, domain, role,
                input_contract_ref, output_contract_ref, authority_scope_ref,
                default_scope_policy_ref, allowed_tools, allowed_context_types,
                execution_policy_ref, approval_policy_ref, quality_policy_ref,
                status, definition_hash
            ) VALUES (
                %(agent_id)s, %(version)s, %(agent_type)s, %(domain)s, %(role)s,
                %(input_contract_ref)s, %(output_contract_ref)s,
                %(authority_scope_ref)s, %(default_scope_policy_ref)s,
                %(allowed_tools)s, %(allowed_context_types)s,
                %(execution_policy_ref)s, %(approval_policy_ref)s,
                %(quality_policy_ref)s, %(status)s, %(definition_hash)s
            )
            ON CONFLICT (agent_id, definition_version) DO NOTHING
            """,
            {**payload, "definition_hash": definition.definition_hash},
        )
        self.cursor.execute(
            """
            SELECT definition_hash
            FROM authority_agent_definition
            WHERE agent_id = %s AND definition_version = %s
            """,
            [definition.agent_id, definition.version],
        )
        if self.cursor.fetchone()[0] != definition.definition_hash:
            raise ValueError("AgentDefinition version has different content")
        for capability_ref in definition.capability_refs:
            capability_id, capability_version = _version_ref(capability_ref)
            self.cursor.execute(
                """
                INSERT INTO authority_agent_definition_capability (
                    agent_id, definition_version,
                    capability_id, capability_version
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [
                    definition.agent_id,
                    definition.version,
                    capability_id,
                    capability_version,
                ],
            )
        return definition

    def create_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession:
        self.cursor.execute(
            """
            INSERT INTO authority_agent_collaboration_session (
                session_id, project_id, owner_authority, business_goal,
                issue_type, scope_snapshot_id, participant_snapshot_id,
                current_candidate_version_id, status, round_number,
                turn_number, execution_count, spent_budget, budget_ref,
                termination_policy_ref, created_operation_id, saga_id,
                authority_decision_id, last_turn_id, version
            ) VALUES (
                %(session_id)s, %(project_id)s, %(owner_authority)s,
                %(business_goal)s, %(issue_type)s, %(scope_snapshot_ref)s,
                %(participant_snapshot_ref)s, %(current_candidate_version_ref)s,
                %(status)s, %(round_number)s, %(turn_number)s,
                %(execution_count)s, %(spent_budget)s, %(budget_ref)s,
                %(termination_policy_ref)s, %(created_operation_id)s,
                %(saga_id)s, %(authority_decision_ref)s, %(last_turn_id)s,
                %(persistence_version)s
            )
            ON CONFLICT (session_id) DO NOTHING
            """,
            _session_parameters(session),
        )
        existing = self.get_session(session.session_id)
        if existing != session:
            raise ValueError("collaboration session replay has different content")
        return existing

    def get_session(self, session_id: str) -> AgentCollaborationSession:
        self.cursor.execute(
            """
            SELECT session_id, project_id, owner_authority, business_goal,
                   issue_type, COALESCE(scope_snapshot_id, ''),
                   COALESCE(participant_snapshot_id, ''),
                   COALESCE(current_candidate_version_id, ''), status,
                   round_number, turn_number, execution_count, spent_budget,
                   budget_ref, termination_policy_ref, created_operation_id,
                   saga_id, COALESCE(authority_decision_id, ''),
                   COALESCE(last_turn_id, ''), version
            FROM authority_agent_collaboration_session
            WHERE session_id = %s
            """,
            [session_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(
                f"collaboration session is not available: {session_id}"
            )
        return AgentCollaborationSession(*row)

    def update_session(
        self, session: AgentCollaborationSession
    ) -> AgentCollaborationSession:
        parameters = _session_parameters(session)
        self.cursor.execute(
            """
            UPDATE authority_agent_collaboration_session
            SET scope_snapshot_id = %(scope_snapshot_ref)s,
                participant_snapshot_id = %(participant_snapshot_ref)s,
                current_candidate_version_id = %(current_candidate_version_ref)s,
                status = %(status)s,
                round_number = %(round_number)s,
                turn_number = %(turn_number)s,
                execution_count = %(execution_count)s,
                spent_budget = %(spent_budget)s,
                authority_decision_id = %(authority_decision_ref)s,
                last_turn_id = %(last_turn_id)s,
                cancelled_at = CASE
                    WHEN %(status)s = 'CANCELLED' THEN NOW()
                    ELSE cancelled_at
                END,
                version = version + 1,
                updated_at = NOW()
            WHERE session_id = %(session_id)s
              AND version = %(persistence_version)s
            """,
            parameters,
        )
        if self.cursor.rowcount != 1:
            raise ValueError("collaboration session version is stale")
        return replace(
            session, persistence_version=session.persistence_version + 1
        )

    def save_scope_snapshot(
        self, snapshot: ScopeSnapshot, *, project_id: str = ""
    ) -> ScopeSnapshot:
        if not project_id:
            raise ValueError("scope snapshot requires project_id")
        contract = snapshot.contract
        narrative = contract.narrative
        self.cursor.execute(
            """
            INSERT INTO authority_agent_scope_snapshot (
                scope_snapshot_id, project_id, scope_contract_id,
                scope_contract_version, owner_authority,
                narrative_scope_type, book_id, volume_id, arc_id,
                chapter_group_id, chapter_id, scene_id,
                past_locked_through, active_range_start, active_range_end,
                forecast_horizon, published_boundary, authority_type,
                contract, scope_hash
            )
            VALUES (
                %(snapshot_id)s, %(project_id)s, %(scope_contract_id)s,
                %(scope_contract_version)s, %(authority_id)s,
                %(narrative_scope_type)s, %(book_id)s, %(volume_id)s,
                %(arc_id)s, %(chapter_group_id)s, %(chapter_id)s, %(scene_id)s,
                %(past_locked_through)s, %(active_range_start)s,
                %(active_range_end)s, %(forecast_horizon)s,
                %(published_boundary)s, %(authority_type)s,
                %(contract)s, %(scope_hash)s
            )
            ON CONFLICT (scope_snapshot_id) DO NOTHING
            """,
            {
                "snapshot_id": snapshot.snapshot_id,
                "project_id": project_id,
                "scope_contract_id": snapshot.scope_contract_id,
                "scope_contract_version": snapshot.scope_contract_version,
                "authority_id": snapshot.authority_id,
                "narrative_scope_type": narrative.kind.value,
                "book_id": narrative.book_id,
                "volume_id": narrative.volume_id,
                "arc_id": narrative.arc_id,
                "chapter_group_id": narrative.chapter_group_id,
                "chapter_id": narrative.chapter_id,
                "scene_id": narrative.scene_id,
                "past_locked_through": contract.temporal.past_locked_through,
                "active_range_start": contract.temporal.active_range[0],
                "active_range_end": contract.temporal.active_range[1],
                "forecast_horizon": contract.temporal.forecast_horizon,
                "published_boundary": contract.temporal.published_boundary,
                "authority_type": contract.authority.authority_type,
                "contract": Jsonb(_plain(contract)),
                "scope_hash": snapshot.scope_hash,
            },
        )
        existing = self.get_scope_snapshot(snapshot.snapshot_id)
        if existing != snapshot:
            raise ValueError("scope snapshot replay has different content")
        return existing

    def get_scope_snapshot(self, snapshot_id: str) -> ScopeSnapshot:
        self.cursor.execute(
            """
            SELECT scope_snapshot_id, scope_contract_id,
                   scope_contract_version, owner_authority, contract, scope_hash
            FROM authority_agent_scope_snapshot
            WHERE scope_snapshot_id = %s
            """,
            [snapshot_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"scope snapshot is not available: {snapshot_id}")
        return ScopeSnapshot(
            snapshot_id=row[0],
            scope_contract_id=row[1],
            scope_contract_version=int(row[2]),
            authority_id=row[3],
            contract=_scope_contract(row[4]),
            scope_hash=row[5],
        )

    def save_participant_snapshot(
        self, snapshot: ParticipantSnapshot, *, project_id: str = ""
    ) -> ParticipantSnapshot:
        if not project_id:
            raise ValueError("participant snapshot requires project_id")
        self.cursor.execute(
            """
            INSERT INTO authority_agent_participant_snapshot (
                participant_snapshot_id, project_id, participant_hash
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (participant_snapshot_id) DO NOTHING
            """,
            [snapshot.snapshot_id, project_id, snapshot.participant_hash],
        )
        for ordinal, participant in enumerate(snapshot.participants, 1):
            self.cursor.execute(
                """
                INSERT INTO authority_agent_participant (
                    participant_snapshot_id, ordinal, agent_id,
                    agent_definition_version, participant_role
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (participant_snapshot_id, agent_id) DO NOTHING
                """,
                [
                    snapshot.snapshot_id,
                    ordinal,
                    participant.agent_id,
                    participant.agent_definition_version,
                    participant.role,
                ],
            )
        existing = self.get_participant_snapshot(snapshot.snapshot_id)
        if existing != snapshot:
            raise ValueError("participant snapshot replay has different content")
        return existing

    def get_participant_snapshot(
        self, snapshot_id: str
    ) -> ParticipantSnapshot:
        self.cursor.execute(
            """
            SELECT participant_hash
            FROM authority_agent_participant_snapshot
            WHERE participant_snapshot_id = %s
            """,
            [snapshot_id],
        )
        header = self.cursor.fetchone()
        if header is None:
            raise ValueError(
                f"participant snapshot is not available: {snapshot_id}"
            )
        self.cursor.execute(
            """
            SELECT agent_id, agent_definition_version, participant_role
            FROM authority_agent_participant
            WHERE participant_snapshot_id = %s
            ORDER BY ordinal
            """,
            [snapshot_id],
        )
        return ParticipantSnapshot(
            snapshot_id=snapshot_id,
            participants=tuple(Participant(*row) for row in self.cursor.fetchall()),
            participant_hash=header[0],
        )

    def save_work_order(self, work_order: AgentWorkOrder) -> AgentWorkOrder:
        session = self.get_session(work_order.collaboration_session_id)
        self._assert_attempt_fence(work_order)
        turn_number = session.turn_number + 1
        round_number = max(1, session.round_number)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_collaboration_turn (
                turn_id, session_id, turn_number, round_number,
                operation_id, attempt_id, fencing_token, agent_id,
                agent_definition_version, message_type, status,
                stable_idempotency_key
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'SCHEDULED', %s
            )
            ON CONFLICT (turn_id) DO NOTHING
            """,
            [
                work_order.turn_id,
                work_order.collaboration_session_id,
                turn_number,
                round_number,
                work_order.operation_id,
                work_order.attempt_id,
                work_order.fencing_token,
                work_order.agent_id,
                work_order.agent_definition_version,
                work_order.message_type.value,
                work_order.work_order_id,
            ],
        )
        payload = _plain(work_order)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_work_order (
                work_order_id, session_id, turn_id, operation_id, attempt_id,
                fencing_token, agent_id, agent_definition_version,
                capability_id, capability_version,
                execution_capability_id, message_type,
                business_goal, current_issue,
                scope_snapshot_id, participant_snapshot_id,
                input_asset_versions, candidate_version_id,
                context_bundle_ref, evidence_refs, must_preserve, must_change,
                forbidden_changes, acceptance_criteria, risk_level,
                budget_policy_ref, timeout_policy_ref, approval_policy_ref,
                failure_policy, continuation_policy,
                project_id, workspace_id, book_id,
                route_snapshot_ref, input_manifest_ref, work_order_hash
            ) VALUES (
                %(work_order_id)s, %(collaboration_session_id)s, %(turn_id)s,
                %(operation_id)s, %(attempt_id)s, %(fencing_token)s,
                %(agent_id)s, %(agent_definition_version)s, %(capability)s,
                %(capability_version)s, %(execution_capability)s,
                %(message_type)s, %(business_goal)s, %(current_issue)s,
                %(scope_snapshot_ref)s, %(participant_snapshot_ref)s,
                %(input_asset_versions)s, %(candidate_version_ref)s,
                %(context_bundle_ref)s, %(evidence_refs)s, %(must_preserve)s,
                %(must_change)s, %(forbidden_changes)s,
                %(acceptance_criteria)s, %(risk_level)s,
                %(budget_policy_ref)s, %(timeout_policy_ref)s,
                %(approval_policy_ref)s, %(failure_policy)s,
                %(continuation_policy)s, %(project_id)s, %(workspace_id)s,
                %(book_id)s, %(route_snapshot_ref)s, %(input_manifest_ref)s,
                %(work_order_hash)s
            )
            ON CONFLICT (work_order_id) DO NOTHING
            """,
            {
                **payload,
                "candidate_version_ref": (
                    work_order.candidate_version_ref or None
                ),
                "work_order_hash": _hash(work_order),
            },
        )
        existing = self.get_work_order(work_order.work_order_id)
        if existing != work_order:
            raise ValueError("work order replay has different content")
        return existing

    def get_work_order(self, work_order_id: str) -> AgentWorkOrder:
        self.cursor.execute(
            _WORK_ORDER_SELECT + " WHERE work_order_id = %s",
            [work_order_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"work order is not available: {work_order_id}")
        return AgentWorkOrder(*row)

    def find_work_order_by_turn(self, turn_id: str) -> AgentWorkOrder | None:
        self.cursor.execute(
            _WORK_ORDER_SELECT + " WHERE turn_id = %s",
            [turn_id],
        )
        row = self.cursor.fetchone()
        return None if row is None else AgentWorkOrder(*row)

    def save_output(
        self,
        envelope: AgentOutputEnvelope,
        *,
        schema_validation_status: str = "PASSED",
        scope_validation_status: str = "PASSED",
    ) -> AgentOutputEnvelope:
        payload = _plain(envelope)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_output_envelope (
                output_id, session_id, turn_id, agent_id, message_type,
                structured_payload, natural_language_explanation,
                source_asset_versions, evidence_refs, assumptions, confidence,
                affected_assets, proposed_changes, preserved_constraints,
                accessed_knowledge, unresolved_questions, risk_level,
                requested_next_action, execution_evidence_ref, output_hash,
                schema_validation_status, scope_validation_status
            ) VALUES (
                %(output_id)s, %(session_id)s, %(turn_id)s, %(agent_id)s,
                %(message_type)s, %(structured_payload)s,
                %(natural_language_explanation)s, %(source_asset_versions)s,
                %(evidence_refs)s, %(assumptions)s, %(confidence)s,
                %(affected_assets)s, %(proposed_changes)s,
                %(preserved_constraints)s, %(accessed_knowledge)s,
                %(unresolved_questions)s, %(risk_level)s,
                %(requested_next_action)s, %(execution_evidence_ref)s,
                %(output_hash)s, %(schema_validation_status)s,
                %(scope_validation_status)s
            )
            ON CONFLICT (output_id) DO NOTHING
            """,
            {
                **payload,
                "structured_payload": Jsonb(payload["structured_payload"]),
                "proposed_changes": Jsonb(payload["proposed_changes"]),
                "output_hash": _hash(envelope),
                "schema_validation_status": schema_validation_status,
                "scope_validation_status": scope_validation_status,
            },
        )
        existing = self.find_output_by_turn(envelope.turn_id)
        if existing != envelope:
            raise ValueError("output replay has different content")
        return existing

    def find_output_by_turn(self, turn_id: str) -> AgentOutputEnvelope | None:
        self.cursor.execute(
            """
            SELECT output_id, session_id, turn_id, agent_id, message_type,
                   structured_payload, natural_language_explanation,
                   source_asset_versions, evidence_refs, assumptions,
                   confidence, affected_assets, proposed_changes,
                   preserved_constraints, accessed_knowledge,
                   unresolved_questions, risk_level, requested_next_action,
                   execution_evidence_ref
            FROM authority_agent_output_envelope
            WHERE turn_id = %s
            """,
            [turn_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        changes = tuple(
            ProposedAssetChange.from_mapping(item) for item in row[12]
        )
        return AgentOutputEnvelope(
            output_id=row[0],
            session_id=row[1],
            turn_id=row[2],
            agent_id=row[3],
            message_type=row[4],
            structured_payload=row[5],
            natural_language_explanation=row[6],
            source_asset_versions=tuple(row[7]),
            evidence_refs=tuple(row[8]),
            assumptions=tuple(row[9]),
            confidence=row[10],
            affected_assets=tuple(row[11]),
            proposed_changes=changes,
            preserved_constraints=tuple(row[13]),
            accessed_knowledge=tuple(row[14]),
            unresolved_questions=tuple(row[15]),
            risk_level=row[16],
            requested_next_action=row[17],
            execution_evidence_ref=row[18],
        )

    def save_message(
        self, message: AgentConversationMessage
    ) -> AgentConversationMessage:
        output = self.find_output_by_turn(message.turn_id)
        if output is None:
            raise ValueError("message requires a persisted output envelope")
        payload = _plain(message)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_conversation_message (
                message_id, session_id, turn_id, output_id, message_type,
                sender_id, recipient_ids, target_proposal_id,
                target_candidate_version_id, scope_snapshot_id,
                evidence_refs, parent_message_id, structured_payload,
                natural_language
            ) VALUES (
                %(message_id)s, %(session_id)s, %(turn_id)s, %(output_id)s,
                %(message_type)s, %(sender_id)s, %(recipient_ids)s,
                %(target_proposal_id)s, %(target_candidate_version_id)s,
                %(scope_snapshot_ref)s, %(evidence_refs)s,
                %(parent_message_id)s, %(structured_payload)s,
                %(natural_language)s
            )
            ON CONFLICT (message_id) DO NOTHING
            """,
            {
                **payload,
                "output_id": output.output_id,
                "target_proposal_id": message.target_proposal_id or None,
                "target_candidate_version_id": (
                    message.target_candidate_version_id or None
                ),
                "parent_message_id": message.parent_message_id or None,
                "structured_payload": Jsonb(payload["structured_payload"]),
            },
        )
        existing = self._message(message.message_id)
        if existing != message:
            raise ValueError("message replay has different content")
        return existing

    def messages(self, session_id: str) -> tuple[AgentConversationMessage, ...]:
        self.cursor.execute(
            _MESSAGE_SELECT
            + """
              WHERE message.session_id = %s
              ORDER BY turn.turn_number
            """,
            [session_id],
        )
        return tuple(_message_from_row(row) for row in self.cursor.fetchall())

    def _message(self, message_id: str) -> AgentConversationMessage:
        self.cursor.execute(
            _MESSAGE_SELECT + " WHERE message.message_id = %s",
            [message_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"message is not available: {message_id}")
        return _message_from_row(row)

    def save_candidate(self, candidate: CandidateVersion) -> CandidateVersion:
        for parent_id in candidate.parent_version_ids:
            parent = self.get_candidate(parent_id)
            if parent.session_id != candidate.session_id:
                raise ValueError("candidate parent belongs to another session")
        payload = _plain(candidate)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_candidate_version (
                candidate_version_id, session_id, candidate_type,
                originating_message_id, originating_turn_id,
                created_by_agent, scope_snapshot_id, content_ref,
                structured_diff, change_reason_refs, preserved_constraints,
                resolved_conflicts, unresolved_conflicts, validation_status,
                content_hash
            ) VALUES (
                %(candidate_version_id)s, %(session_id)s, %(candidate_type)s,
                %(originating_message_id)s, %(originating_turn_id)s,
                %(created_by_agent)s, %(scope_snapshot_ref)s, %(content_ref)s,
                %(structured_diff)s, %(change_reason_refs)s,
                %(preserved_constraints)s, %(resolved_conflicts)s,
                %(unresolved_conflicts)s, %(validation_status)s,
                %(content_hash)s
            )
            ON CONFLICT (candidate_version_id) DO NOTHING
            """,
            {
                **payload,
                "structured_diff": Jsonb(payload["structured_diff"]),
                "content_hash": _hash(candidate),
            },
        )
        for ordinal, parent_id in enumerate(candidate.parent_version_ids, 1):
            self.cursor.execute(
                """
                INSERT INTO authority_agent_candidate_parent (
                    child_candidate_version_id, parent_candidate_version_id,
                    parent_ordinal
                ) VALUES (%s, %s, %s)
                ON CONFLICT (
                    child_candidate_version_id, parent_candidate_version_id
                ) DO NOTHING
                """,
                [candidate.candidate_version_id, parent_id, ordinal],
            )
        existing = self.get_candidate(candidate.candidate_version_id)
        if existing != candidate:
            raise ValueError("candidate version replay has different content")
        return existing

    def get_candidate(self, candidate_id: str) -> CandidateVersion:
        self.cursor.execute(
            _CANDIDATE_SELECT + " WHERE candidate.candidate_version_id = %s",
            [candidate_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"candidate is not available: {candidate_id}")
        return _candidate_from_row(row)

    def candidates(self, session_id: str) -> tuple[CandidateVersion, ...]:
        self.cursor.execute(
            _CANDIDATE_SELECT
            + """
              WHERE candidate.session_id = %s
              ORDER BY candidate.created_at, candidate.candidate_version_id
            """,
            [session_id],
        )
        return tuple(_candidate_from_row(row) for row in self.cursor.fetchall())

    def candidate_lineage(self, candidate_id: str) -> tuple[str, ...]:
        ordered: list[str] = []
        visited: set[str] = set()

        def visit(identity: str) -> None:
            if identity in visited:
                return
            candidate = self.get_candidate(identity)
            for parent_id in candidate.parent_version_ids:
                visit(parent_id)
            visited.add(identity)
            ordered.append(identity)

        visit(candidate_id)
        return tuple(ordered)

    def save_conflict(self, conflict: ConflictRecord) -> ConflictRecord:
        payload = _plain(conflict)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_conflict_record (
                conflict_id, session_id, conflict_type, severity, raised_by,
                target_candidate_version_id, conflicting_asset_versions,
                claim, evidence_refs, affected_scopes, affected_assets,
                reader_outcome_impact, continuity_impact,
                ending_reachability_impact, requested_resolution, status,
                resolution_ref, authority_decision_id
            ) VALUES (
                %(conflict_id)s, %(session_id)s, %(conflict_type)s,
                %(severity)s, %(raised_by)s, %(target_candidate_version)s,
                %(conflicting_asset_versions)s, %(claim)s, %(evidence_refs)s,
                %(affected_scopes)s, %(affected_assets)s,
                %(reader_outcome_impact)s, %(continuity_impact)s,
                %(ending_reachability_impact)s, %(requested_resolution)s,
                %(status)s, %(resolution_ref)s, %(authority_decision_ref)s
            )
            ON CONFLICT (conflict_id) DO NOTHING
            """,
            {
                **payload,
                "resolution_ref": conflict.resolution_ref or None,
                "authority_decision_ref": (
                    conflict.authority_decision_ref or None
                ),
            },
        )
        existing = self.get_conflict(conflict.conflict_id)
        if existing != conflict:
            raise ValueError("conflict replay has different content")
        return existing

    def get_conflict(self, conflict_id: str) -> ConflictRecord:
        self.cursor.execute(
            _CONFLICT_SELECT + " WHERE conflict_id = %s",
            [conflict_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"conflict is not available: {conflict_id}")
        return ConflictRecord(*row)

    def conflicts(self, session_id: str) -> tuple[ConflictRecord, ...]:
        self.cursor.execute(
            _CONFLICT_SELECT + " WHERE session_id = %s ORDER BY raised_at",
            [session_id],
        )
        return tuple(ConflictRecord(*row) for row in self.cursor.fetchall())

    def resolve_conflicts(
        self, conflict_ids: tuple[str, ...], *, resolution_ref: str
    ) -> tuple[ConflictRecord, ...]:
        resolved = []
        for conflict_id in conflict_ids:
            self.cursor.execute(
                """
                UPDATE authority_agent_conflict_record
                SET status = 'RESOLVED', resolution_ref = %s, resolved_at = NOW()
                WHERE conflict_id = %s AND status = 'OPEN'
                """,
                [resolution_ref, conflict_id],
            )
            conflict = self.get_conflict(conflict_id)
            if (
                conflict.status is not ConflictStatus.RESOLVED
                or conflict.resolution_ref != resolution_ref
            ):
                raise ValueError("conflict could not be resolved idempotently")
            resolved.append(conflict)
        return tuple(resolved)

    def apply_conflict_decision(
        self,
        session_id: str,
        *,
        decision_ref: str,
        status: ConflictStatus,
    ) -> tuple[ConflictRecord, ...]:
        self.cursor.execute(
            """
            UPDATE authority_agent_conflict_record
            SET status = %s,
                authority_decision_id = %s,
                resolved_at = NOW()
            WHERE session_id = %s AND status = 'OPEN'
            RETURNING conflict_id
            """,
            [status.value, decision_ref, session_id],
        )
        identities = tuple(row[0] for row in self.cursor.fetchall())
        return tuple(self.get_conflict(identity) for identity in identities)

    def save_scope_expansion_request(
        self, request: ScopeExpansionRequest
    ) -> ScopeExpansionRequest:
        payload = _plain(request)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_scope_expansion_request (
                request_id, session_id, current_scope_snapshot_id,
                requested_scope_type, requested_scope, reason,
                affected_assets, risk_level, requesting_agent,
                required_authority, decision, decision_ref
            ) VALUES (
                %(request_id)s, %(session_id)s,
                %(current_scope_snapshot_ref)s, %(requested_scope_type)s,
                %(requested_scope)s, %(reason)s, %(affected_assets)s,
                %(risk_level)s, %(requesting_agent)s, %(required_authority)s,
                %(decision)s, %(decision_ref)s
            )
            ON CONFLICT (request_id) DO NOTHING
            """,
            {
                **payload,
                "requested_scope_type": request.requested_scope.kind.value,
                "requested_scope": Jsonb(payload["requested_scope"]),
                "decision_ref": request.decision_ref or None,
            },
        )
        rows = self.scope_expansion_requests(request.session_id)
        existing = next(item for item in rows if item.request_id == request.request_id)
        if existing != request:
            raise ValueError("scope expansion replay has different content")
        return existing

    def scope_expansion_requests(
        self, session_id: str
    ) -> tuple[ScopeExpansionRequest, ...]:
        self.cursor.execute(
            """
            SELECT request_id, session_id, current_scope_snapshot_id,
                   requested_scope, reason, affected_assets, risk_level,
                   requesting_agent, required_authority, decision,
                   COALESCE(decision_ref, '')
            FROM authority_agent_scope_expansion_request
            WHERE session_id = %s
            ORDER BY created_at
            """,
            [session_id],
        )
        return tuple(
            ScopeExpansionRequest(
                request_id=row[0],
                session_id=row[1],
                current_scope_snapshot_ref=row[2],
                requested_scope=NarrativeScope(**row[3]),
                reason=row[4],
                affected_assets=tuple(row[5]),
                risk_level=row[6],
                requesting_agent=row[7],
                required_authority=row[8],
                decision=row[9],
                decision_ref=row[10],
            )
            for row in self.cursor.fetchall()
        )

    def resolve_scope_expansion_request(
        self,
        request_id: str,
        *,
        decision: str,
        decision_ref: str,
    ) -> ScopeExpansionRequest:
        self.cursor.execute(
            """
            UPDATE authority_agent_scope_expansion_request
            SET decision = %s, decision_ref = %s, decided_at = NOW()
            WHERE request_id = %s
              AND (
                  decision = 'PENDING'
                  OR (decision = %s AND decision_ref = %s)
              )
            RETURNING session_id
            """,
            [decision, decision_ref, request_id, decision, decision_ref],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(
                "scope expansion request already has a different decision"
            )
        requests = self.scope_expansion_requests(row[0])
        return next(item for item in requests if item.request_id == request_id)

    def save_decision(
        self, decision: CollaborationDecision
    ) -> CollaborationDecision:
        payload = _plain(decision)
        self.cursor.execute(
            """
            INSERT INTO authority_agent_collaboration_decision (
                decision_id, decision_type, authority_type,
                authority_version, session_id, candidate_version_id,
                accepted_changes, rejected_changes, deferred_changes,
                accepted_with_objections, unresolved_objections,
                required_followup, affected_asset_versions,
                commit_policy_ref, decision_evidence, decision_hash
            ) VALUES (
                %(decision_id)s, %(decision)s, %(authority_type)s,
                %(authority_version)s, %(session_id)s,
                %(candidate_version_id)s, %(accepted_changes)s,
                %(rejected_changes)s, %(deferred_changes)s,
                %(accepted_with_objections)s, %(unresolved_objections)s,
                %(required_followup)s, %(affected_asset_versions)s,
                %(commit_policy_ref)s, %(decision_evidence)s,
                %(decision_hash)s
            )
            ON CONFLICT (decision_id) DO NOTHING
            """,
            {
                **payload,
                "candidate_version_id": (
                    decision.candidate_version_id or None
                ),
                "decision_hash": _hash(decision),
            },
        )
        existing = self.get_decision(decision.decision_id)
        if existing != decision:
            raise ValueError("decision replay has different content")
        return existing

    def get_decision(self, decision_id: str) -> CollaborationDecision:
        self.cursor.execute(
            """
            SELECT decision_id, decision_type, authority_type,
                   authority_version, session_id,
                   COALESCE(candidate_version_id, ''),
                   accepted_changes, rejected_changes, deferred_changes,
                   accepted_with_objections, unresolved_objections,
                   required_followup, affected_asset_versions,
                   commit_policy_ref, decision_evidence
            FROM authority_agent_collaboration_decision
            WHERE decision_id = %s
            """,
            [decision_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise ValueError(f"decision is not available: {decision_id}")
        return CollaborationDecision(*row)

    def save_commit(self, commit: CollaborationCommit) -> CollaborationCommit:
        self.cursor.execute(
            """
            INSERT INTO authority_agent_collaboration_commit (
                commit_id, session_id, decision_id, candidate_version_id,
                operation_id, asset_version_id, stable_idempotency_key,
                source_lineage, receipt_ref, attempt_id, fencing_token,
                content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            [
                commit.commit_id,
                commit.session_id,
                commit.decision_id,
                commit.candidate_version_id,
                commit.operation_id,
                commit.asset_version_id,
                commit.stable_idempotency_key,
                Jsonb({"candidate_version_ids": list(commit.source_lineage)}),
                commit.receipt_ref or None,
                commit.attempt_id or None,
                commit.fencing_token or None,
                commit.content_hash or None,
            ],
        )
        existing = self.find_commit(commit.session_id)
        if existing != commit:
            raise ValueError("collaboration commit replay has different content")
        return existing

    def find_commit(self, session_id: str) -> CollaborationCommit | None:
        self.cursor.execute(
            """
            SELECT commit_id, session_id, decision_id, candidate_version_id,
                   operation_id, asset_version_id, stable_idempotency_key,
                   source_lineage, COALESCE(receipt_ref, ''),
                   COALESCE(attempt_id, ''), COALESCE(fencing_token, 0),
                   COALESCE(content_hash, '')
            FROM authority_agent_collaboration_commit
            WHERE session_id = %s
            """,
            [session_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return CollaborationCommit(
            commit_id=row[0],
            session_id=row[1],
            decision_id=row[2],
            candidate_version_id=row[3],
            operation_id=row[4],
            asset_version_id=row[5],
            stable_idempotency_key=row[6],
            source_lineage=tuple(row[7]["candidate_version_ids"]),
            receipt_ref=row[8],
            attempt_id=row[9],
            fencing_token=int(row[10]),
            content_hash=row[11],
        )

    def save_processing_result(self, turn_id: str, result: Any) -> Any:
        payload = _plain(result)
        status = (
            "ACCEPTED"
            if result.domain_acceptance is DomainAcceptance.ACCEPTED
            else "REPAIR_REQUIRED"
            if result.domain_acceptance is DomainAcceptance.REPAIR_REQUIRED
            else "REJECTED"
        )
        self.cursor.execute(
            """
            UPDATE authority_agent_collaboration_turn
            SET status = %s,
                domain_acceptance = %s,
                processing_result = %s,
                completed_at = NOW()
            WHERE turn_id = %s
              AND (
                  processing_result = '{}'::jsonb
                  OR processing_result = %s
              )
            """,
            [
                status,
                result.domain_acceptance.value,
                Jsonb(payload),
                turn_id,
                Jsonb(payload),
            ],
        )
        if self.cursor.rowcount != 1:
            raise ValueError("turn processing result replay has different content")
        return self.find_processing_result(turn_id)

    def find_processing_result(self, turn_id: str) -> Any | None:
        self.cursor.execute(
            """
            SELECT processing_result
            FROM authority_agent_collaboration_turn
            WHERE turn_id = %s
            """,
            [turn_id],
        )
        row = self.cursor.fetchone()
        if row is None or not row[0]:
            return None
        from novel_forge.modules.agent_collaboration.application import (
            TurnProcessingResult,
        )

        payload = dict(row[0])
        payload["domain_acceptance"] = DomainAcceptance(
            payload["domain_acceptance"]
        )
        payload["conflict_ids"] = tuple(payload.get("conflict_ids") or ())
        payload["violations"] = tuple(payload.get("violations") or ())
        return TurnProcessingResult(**payload)

    def _assert_attempt_fence(self, work_order: AgentWorkOrder) -> None:
        self.cursor.execute(
            """
            SELECT attempt.operation_id, attempt.status, lease.fencing_token
            FROM authority_attempt AS attempt
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id = attempt.attempt_id
             AND lease.released_at IS NULL
            WHERE attempt.attempt_id = %s
            """,
            [work_order.attempt_id],
        )
        row = self.cursor.fetchone()
        if row is None or row != (
            work_order.operation_id,
            "RUNNING",
            work_order.fencing_token,
        ):
            raise ValueError("work order does not bind a current running Attempt fence")


class PostgresAuthorityCandidateCommitter:
    """Domain Authority command adapter over the existing AssetVersion authority."""

    def __init__(
        self,
        cursor: Any,
        *,
        execution_proof: Mapping[str, bool],
    ) -> None:
        self.cursor = cursor
        self.assets = AuthorityAssetDocumentRepository(cursor)
        required = {
            "fixture_protocol_only",
            "real_model_call",
            "production_verified",
        }
        if set(execution_proof) != required or any(
            not isinstance(execution_proof[key], bool) for key in required
        ):
            raise ValueError("Authority commit requires explicit execution proof")
        self.execution_proof = dict(execution_proof)

    def commit_candidate(
        self,
        *,
        session: AgentCollaborationSession,
        candidate: CandidateVersion,
        decision: CollaborationDecision,
        operation_id: str,
        idempotency_key: str,
    ) -> Mapping[str, str]:
        self.cursor.execute(
            """
            SELECT saga.trace_id, saga.correlation_id
            FROM authority_saga AS saga
            WHERE saga.saga_id = %s AND saga.project_id = %s
            """,
            [session.saga_id, session.project_id],
        )
        trace = self.cursor.fetchone()
        if trace is None:
            raise ValueError("collaboration Saga trace is unavailable")
        candidate_lineage = PostgresAgentCollaborationRepository(
            self.cursor
        ).candidate_lineage(candidate.candidate_version_id)
        lineage = {
            "session_id": session.session_id,
            "candidate_version_id": candidate.candidate_version_id,
            "candidate_lineage": list(candidate_lineage),
            "candidate_parent_version_ids": list(candidate.parent_version_ids),
            "originating_message_id": candidate.originating_message_id,
            "originating_turn_id": candidate.originating_turn_id,
            "scope_snapshot_ref": candidate.scope_snapshot_ref,
            "content_ref": candidate.content_ref,
            "structured_diff": _plain(candidate.structured_diff),
            "preserved_constraints": list(candidate.preserved_constraints),
            "resolved_conflicts": list(candidate.resolved_conflicts),
            "unresolved_conflicts": list(candidate.unresolved_conflicts),
            "decision_id": decision.decision_id,
            "accepted_changes": list(decision.accepted_changes),
            "accepted_with_objections": list(
                decision.accepted_with_objections
            ),
            "decision_evidence": list(decision.decision_evidence),
        }
        asset_id = str(
            uuid5(
                NAMESPACE_URL,
                f"novel-forge:book-design:{session.project_id}:{session.session_id}",
            )
        )
        document = self.assets.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=session.project_id,
                asset_id=asset_id,
                asset_type="book_design_core_advantage",
                schema_version="book-design-core-advantage.v1",
                logical_ref=(
                    f"agent-collaboration/{session.session_id}/"
                    "accepted-core-advantage"
                ),
                category="book_design",
                output_key="accepted_candidate",
                role="primary",
                content={
                    "type": "book_design_core_advantage",
                    "lineage": lineage,
                    **self.execution_proof,
                },
                qualification_policy=decision.commit_policy_ref,
                trace_id=str(trace[0]),
                correlation_id=str(trace[1]),
            )
        )
        return {
            "commit_id": str(
                uuid5(
                    NAMESPACE_URL,
                    f"novel-forge:collaboration-commit:{idempotency_key}",
                )
            ),
            "asset_version_id": document.asset_version_id,
            "receipt_ref": "",
        }


def _session_parameters(session: AgentCollaborationSession) -> dict[str, Any]:
    return {
        **_plain(session),
        "scope_snapshot_ref": session.scope_snapshot_ref or None,
        "participant_snapshot_ref": session.participant_snapshot_ref or None,
        "current_candidate_version_ref": (
            session.current_candidate_version_ref or None
        ),
        "authority_decision_ref": session.authority_decision_ref or None,
        "last_turn_id": session.last_turn_id or None,
    }


def _scope_contract(payload: Mapping[str, Any]) -> AgentScopeContract:
    narrative = NarrativeScope(**payload["narrative"])
    read = AssetReadScope(**payload["asset_read"])
    proposal = ProposalScope(**payload["proposal"])
    authority = AuthorityScope(**payload["authority"])
    temporal_payload = dict(payload["temporal"])
    temporal_payload["active_range"] = tuple(temporal_payload["active_range"])
    temporal = TemporalScope(**temporal_payload)
    knowledge = KnowledgeVisibilityScope(**payload["knowledge"])
    return AgentScopeContract(
        scope_contract_id=str(payload["scope_contract_id"]),
        version=int(payload["version"]),
        narrative=narrative,
        asset_read=read,
        proposal=proposal,
        authority=authority,
        temporal=temporal,
        knowledge=knowledge,
    )


def _version_ref(value: str) -> tuple[str, int]:
    capability_id, separator, version = value.rpartition("@")
    if not separator or not capability_id or int(version) <= 0:
        raise ValueError(f"invalid capability version reference: {value}")
    return capability_id, int(version)


def _plain(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    return value


def _hash(value: Any) -> str:
    encoded = json.dumps(
        _plain(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _message_from_row(row: tuple[Any, ...]) -> AgentConversationMessage:
    return AgentConversationMessage(
        message_id=row[0],
        session_id=row[1],
        turn_id=row[2],
        message_type=row[3],
        sender_id=row[4],
        recipient_ids=tuple(row[5]),
        target_proposal_id=row[6],
        target_candidate_version_id=row[7],
        scope_snapshot_ref=row[8],
        evidence_refs=tuple(row[9]),
        parent_message_id=row[10],
        structured_payload=row[11],
        natural_language=row[12],
    )


def _candidate_from_row(row: tuple[Any, ...]) -> CandidateVersion:
    return CandidateVersion(
        candidate_version_id=row[0],
        session_id=row[1],
        candidate_type=row[2],
        parent_version_ids=tuple(row[3] or ()),
        originating_message_id=row[4],
        originating_turn_id=row[5],
        created_by_agent=row[6],
        scope_snapshot_ref=row[7],
        content_ref=row[8],
        structured_diff=row[9],
        change_reason_refs=tuple(row[10]),
        preserved_constraints=tuple(row[11]),
        resolved_conflicts=tuple(row[12]),
        unresolved_conflicts=tuple(row[13]),
        validation_status=row[14],
    )


_WORK_ORDER_SELECT = """
SELECT work_order_id, session_id, turn_id, operation_id, attempt_id,
       fencing_token, agent_id, agent_definition_version, capability_id,
       message_type, business_goal, current_issue, scope_snapshot_id,
       participant_snapshot_id, input_asset_versions,
       COALESCE(candidate_version_id, ''), context_bundle_ref, evidence_refs,
       must_preserve, must_change, forbidden_changes, acceptance_criteria,
       risk_level, budget_policy_ref, timeout_policy_ref, approval_policy_ref,
       failure_policy, continuation_policy, project_id, workspace_id, book_id,
       route_snapshot_ref, input_manifest_ref, capability_version,
       execution_capability_id
FROM authority_agent_work_order
"""

_MESSAGE_SELECT = """
SELECT message.message_id, message.session_id, message.turn_id,
       message.message_type, message.sender_id, message.recipient_ids,
       COALESCE(message.target_proposal_id, ''),
       COALESCE(message.target_candidate_version_id, ''),
       message.scope_snapshot_id, message.evidence_refs,
       COALESCE(message.parent_message_id, ''), message.structured_payload,
       message.natural_language
FROM authority_agent_conversation_message AS message
JOIN authority_agent_collaboration_turn AS turn
  ON turn.turn_id = message.turn_id
"""

_CANDIDATE_SELECT = """
SELECT candidate.candidate_version_id, candidate.session_id,
       candidate.candidate_type,
       COALESCE(
           (
               SELECT ARRAY_AGG(
                   parent.parent_candidate_version_id
                   ORDER BY parent.parent_ordinal
               )
               FROM authority_agent_candidate_parent AS parent
               WHERE parent.child_candidate_version_id =
                   candidate.candidate_version_id
           ),
           ARRAY[]::TEXT[]
       ),
       candidate.originating_message_id, candidate.originating_turn_id,
       candidate.created_by_agent, candidate.scope_snapshot_id,
       candidate.content_ref, candidate.structured_diff,
       candidate.change_reason_refs, candidate.preserved_constraints,
       candidate.resolved_conflicts, candidate.unresolved_conflicts,
       candidate.validation_status
FROM authority_agent_candidate_version AS candidate
"""

_CONFLICT_SELECT = """
SELECT conflict_id, session_id, conflict_type, severity, raised_by,
       target_candidate_version_id, conflicting_asset_versions, claim,
       evidence_refs, affected_scopes, affected_assets,
       reader_outcome_impact, continuity_impact,
       ending_reachability_impact, requested_resolution, status,
       COALESCE(resolution_ref, ''), COALESCE(authority_decision_id, '')
FROM authority_agent_conflict_record
"""


__all__ = [
    "PostgresAgentCollaborationRepository",
    "PostgresAuthorityCandidateCommitter",
]
