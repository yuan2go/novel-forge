from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from novel_forge.modules.agent_collaboration import (
    AgentCollaborationApplication,
    AgentCollaborationSession,
    AgentMessageType,
    AgentOutputEnvelope,
    AgentScopeContract,
    AgentWorkOrder,
    AssetReadScope,
    AuthorityScope,
    CollaborationDecision,
    CollaborationDecisionType,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    InMemoryAgentCollaborationRepository,
    KnowledgeVisibility,
    KnowledgeVisibilityScope,
    NarrativeScope,
    Participant,
    ParticipantSnapshot,
    ProposalScope,
    ProposedAssetChange,
    ScopeExpansionRequest,
    SessionStatus,
    TemporalScope,
    TerminationPolicy,
)
from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionEvidence,
)


class _AuthorityCommitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def commit_candidate(
        self,
        *,
        session,
        candidate,
        decision,
        operation_id,
        idempotency_key,
    ):
        self.calls.append(
            {
                "session_id": session.session_id,
                "candidate_version_id": candidate.candidate_version_id,
                "decision_id": decision.decision_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
            }
        )
        return {
            "commit_id": "commit:1",
            "asset_version_id": "asset-version:book-design:1",
            "receipt_ref": "",
        }


class _ExecutionPort:
    production_execution_gateway_backed = True

    def __init__(self, candidate: DomainExecutionCandidate) -> None:
        self.candidate = candidate
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return self.candidate


class AgentCollaborationApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAgentCollaborationRepository()
        self.committer = _AuthorityCommitter()
        self.application = AgentCollaborationApplication(
            self.repository,
            authority_committer=self.committer,
        )
        self.session = self.application.create_collaboration_session(_session())
        self.scope = _scope().freeze(
            snapshot_id="scope-snapshot:book:1",
            authority_id="book-design-authority:1",
        )
        self.participants = ParticipantSnapshot.freeze(
            snapshot_id="participants:book-design:1",
            participants=(
                Participant("character-design-agent", 1, "PROPOSAL_OWNER"),
                Participant("plot-architecture-agent", 1, "CHALLENGER"),
                Participant("reader-outcome-judge", 1, "JUDGE"),
            ),
        )
        self.application.freeze_scope(self.session.session_id, self.scope)
        self.application.assign_participants(
            self.session.session_id, self.participants
        )

    def test_authority_led_flow_versions_candidates_and_commits_once(self) -> None:
        proposal = self._accept(
            _work_order(1, AgentMessageType.PROPOSAL, "character-design-agent"),
            _envelope(
                1,
                AgentMessageType.PROPOSAL,
                "character-design-agent",
                candidate_version_id="candidate:v1",
                candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
                content_ref="content:candidate:v1",
                structured_diff={"op": "create", "path": "/core_advantage"},
            ),
        )
        self.assertEqual(proposal.domain_acceptance.value, "ACCEPTED")
        self.assertEqual(proposal.candidate_version_id, "candidate:v1")

        challenge = self._accept(
            _work_order(
                2,
                AgentMessageType.CHALLENGE,
                "plot-architecture-agent",
                candidate="candidate:v1",
            ),
            _envelope(
                2,
                AgentMessageType.CHALLENGE,
                "plot-architecture-agent",
                target_candidate="candidate:v1",
                conflict={
                    "conflict_id": "conflict:plot-scale",
                    "conflict_type": "PLOT_SCALABILITY",
                    "severity": "MAJOR",
                    "claim": "The advantage has no escalating cost.",
                    "reader_outcome_impact": "mid-book tension collapses",
                    "continuity_impact": "cost rules are underspecified",
                    "ending_reachability_impact": "ending remains reachable",
                    "requested_resolution": "add an irreversible escalating cost",
                    "affected_scopes": ["BOOK"],
                    "affected_assets": ["book_design_candidate"],
                    "conflicting_asset_versions": ["asset-version:plot:1"],
                },
            ),
        )
        self.assertEqual(challenge.conflict_ids, ("conflict:plot-scale",))
        self.assertEqual(
            self.repository.get_session(self.session.session_id).status,
            SessionStatus.REVISION_PENDING,
        )

        revision = self._accept(
            _work_order(
                3,
                AgentMessageType.REVISION,
                "character-design-agent",
                candidate="candidate:v1",
            ),
            _envelope(
                3,
                AgentMessageType.REVISION,
                "character-design-agent",
                target_candidate="candidate:v1",
                candidate_version_id="candidate:v2",
                candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
                content_ref="content:candidate:v2",
                structured_diff={
                    "op": "add",
                    "path": "/core_advantage/escalating_cost",
                    "value": "memory erosion",
                },
                change_reason_refs=("message:2",),
                resolved_conflicts=("conflict:plot-scale",),
            ),
        )
        self.assertEqual(revision.candidate_version_id, "candidate:v2")
        self.assertEqual(
            self.repository.get_candidate("candidate:v2").parent_version_ids,
            ("candidate:v1",),
        )
        self.assertEqual(
            self.repository.get_conflict("conflict:plot-scale").status,
            ConflictStatus.RESOLVED,
        )

        evaluation = self._accept(
            _work_order(
                4,
                AgentMessageType.EVALUATION,
                "reader-outcome-judge",
                candidate="candidate:v2",
            ),
            _envelope(
                4,
                AgentMessageType.EVALUATION,
                "reader-outcome-judge",
                target_candidate="candidate:v2",
                recommendation="ACCEPT_WITH_NON_BLOCKING_OBJECTIONS",
            ),
        )
        self.assertEqual(evaluation.domain_acceptance.value, "ACCEPTED")
        self.assertEqual(
            self.repository.get_session(self.session.session_id).status,
            SessionStatus.CONSENSUS_REACHED,
        )
        self.application.record_conflict(
            ConflictRecord(
                conflict_id="conflict:cost-calibration",
                session_id=self.session.session_id,
                conflict_type="COST_CALIBRATION",
                severity=ConflictSeverity.MINOR,
                raised_by="reader-outcome-judge",
                target_candidate_version="candidate:v2",
                conflicting_asset_versions=(),
                claim="Per-volume cost remains uncalibrated.",
                evidence_refs=("evidence:4",),
                affected_scopes=("BOOK",),
                affected_assets=("book_design_candidate",),
                reader_outcome_impact="late-book cost may feel uneven",
                continuity_impact="no immediate contradiction",
                ending_reachability_impact="ending remains reachable",
                requested_resolution="calibrate during volume planning",
                status=ConflictStatus.OPEN,
                resolution_ref="",
                authority_decision_ref="",
            )
        )

        self.application.request_authority_decision(self.session.session_id)
        decision = CollaborationDecision(
            decision_id="decision:book-design:1",
            decision=CollaborationDecisionType.ACCEPTED,
            authority_type="BOOK_DESIGN_AUTHORITY",
            authority_version=1,
            session_id=self.session.session_id,
            candidate_version_id="candidate:v2",
            accepted_changes=("core advantage", "escalating cost"),
            rejected_changes=(),
            deferred_changes=(),
            accepted_with_objections=("cost calibration remains",),
            unresolved_objections=(),
            required_followup=("calibrate cost per volume",),
            affected_asset_versions=(),
            commit_policy_ref="commit-policy:book-design:v1",
            decision_evidence=("message:4",),
        )
        self.application.apply_authority_decision(decision)
        first_commit = self.application.commit_accepted_candidate(
            self.session.session_id,
            operation_id="operation:commit",
            idempotency_key="commit:session:1",
        )
        replay = self.application.commit_accepted_candidate(
            self.session.session_id,
            operation_id="operation:commit",
            idempotency_key="commit:session:1",
        )

        self.assertEqual(first_commit, replay)
        self.assertEqual(len(self.committer.calls), 1)
        self.assertEqual(
            self.repository.get_session(self.session.session_id).status,
            SessionStatus.COMMITTED,
        )
        self.assertEqual(
            self.repository.candidate_lineage("candidate:v2"),
            ("candidate:v1", "candidate:v2"),
        )
        accepted_objection = self.repository.get_conflict(
            "conflict:cost-calibration"
        )
        self.assertEqual(
            accepted_objection.status,
            ConflictStatus.ACCEPTED_NON_BLOCKING,
        )
        self.assertEqual(
            accepted_objection.authority_decision_ref,
            decision.decision_id,
        )

    def test_scope_violation_preserves_output_but_not_message_or_candidate(self) -> None:
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        self.application.schedule_next_turn(work_order)
        output = _envelope(
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id="candidate:forbidden",
            candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
            content_ref="content:forbidden",
            structured_diff={"op": "replace", "path": "/ending"},
            changes=(
                ProposedAssetChange(
                    asset_type="book_design_candidate",
                    asset_version_id="",
                    narrative_scope=NarrativeScope(
                        kind="BOOK",
                        book_id="book:1",
                    ),
                    change_type="ending.replace",
                    knowledge_visibility=KnowledgeVisibility.HIDDEN_PLANNING,
                ),
            ),
        )

        result = self.application.accept_agent_output(work_order, output)

        self.assertEqual(result.domain_acceptance.value, "REPLAN_REQUIRED")
        self.assertFalse(result.conversation_message_accepted)
        self.assertEqual(result.candidate_version_id, "")
        self.assertIsNotNone(self.repository.find_output_by_turn("turn:1"))
        self.assertEqual(self.repository.messages(self.session.session_id), ())
        self.assertEqual(self.repository.candidates(self.session.session_id), ())
        self.assertEqual(
            self.repository.get_session(self.session.session_id).status,
            SessionStatus.SCOPE_VIOLATION,
        )

    def test_duplicate_output_does_not_duplicate_turn_message_or_candidate(self) -> None:
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        output = _envelope(
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id="candidate:v1",
            candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
            content_ref="content:candidate:v1",
            structured_diff={"op": "create"},
        )
        self.application.schedule_next_turn(work_order)

        first = self.application.accept_agent_output(work_order, output)
        replay = self.application.accept_agent_output(work_order, output)

        self.assertEqual(first, replay)
        self.assertEqual(len(self.repository.messages(self.session.session_id)), 1)
        self.assertEqual(len(self.repository.candidates(self.session.session_id)), 1)
        self.assertEqual(
            self.repository.get_session(self.session.session_id).turn_number,
            1,
        )

    def test_production_repository_rejects_output_without_pep_evidence(self) -> None:
        self.repository.production_authority = True
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        output = _envelope(
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id="candidate:v1",
            candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
            content_ref="content:candidate:v1",
            structured_diff={"op": "create"},
        )
        self.application.schedule_next_turn(work_order)

        with self.assertRaisesRegex(ValueError, "PEP execution evidence"):
            self.application.accept_agent_output(work_order, output)

    def test_recovery_and_cancellation_do_not_depend_on_chat_memory(self) -> None:
        recovered = AgentCollaborationApplication(
            self.repository,
            authority_committer=self.committer,
        ).recover_collaboration_session(self.session.session_id)
        self.assertEqual(recovered.scope_snapshot.snapshot_id, self.scope.snapshot_id)
        self.assertEqual(
            recovered.participant_snapshot.snapshot_id,
            self.participants.snapshot_id,
        )

        cancelled = self.application.cancel_collaboration_session(
            self.session.session_id
        )
        self.assertEqual(cancelled.status, SessionStatus.CANCELLED)

    def test_execute_turn_uses_pep_evidence_before_domain_acceptance(self) -> None:
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        output = _envelope(
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id="candidate:v1",
            candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
            content_ref="content:candidate:v1",
            structured_diff={"op": "create"},
        )
        evidence = _execution_evidence(work_order)
        port = _ExecutionPort(
            DomainExecutionCandidate(
                candidate_kind=CandidateKind.AGENT_RESULT,
                raw_output=output.to_dict(),
                evidence=evidence,
            )
        )

        result = self.application.execute_turn(work_order, port)

        self.assertTrue(result.backend_success)
        self.assertTrue(result.schema_validation_passed)
        self.assertTrue(result.scope_validation_passed)
        self.assertTrue(result.conversation_message_accepted)
        self.assertEqual(result.candidate_version_id, "candidate:v1")
        self.assertEqual(len(port.commands), 1)
        self.assertEqual(port.commands[0].capability, "agent.workspace.execute")
        self.assertEqual(
            port.commands[0].context["agent_work_order"]["attempt_id"],
            work_order.attempt_id,
        )

    def test_execute_turn_repairs_malformed_backend_output_without_message(self) -> None:
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        port = _ExecutionPort(
            DomainExecutionCandidate(
                candidate_kind=CandidateKind.AGENT_RESULT,
                raw_output={"malformed": True},
                evidence=_execution_evidence(work_order),
            )
        )

        result = self.application.execute_turn(work_order, port)

        self.assertEqual(result.domain_acceptance.value, "REPAIR_REQUIRED")
        self.assertTrue(result.backend_success)
        self.assertTrue(result.output_received)
        self.assertFalse(result.schema_validation_passed)
        self.assertFalse(result.conversation_message_accepted)
        self.assertEqual(
            self.repository.messages(self.session.session_id),
            (),
        )

    def test_scope_expansion_requires_authority_and_new_snapshot(self) -> None:
        repository = InMemoryAgentCollaborationRepository()
        application = AgentCollaborationApplication(repository)
        session = application.create_collaboration_session(
            replace(
                _session(),
                session_id="session:chapter",
                saga_id="saga:chapter",
                created_operation_id="operation:chapter",
                owner_authority="CHAPTER_DESIGN_AUTHORITY",
            )
        )
        chapter_contract = replace(
            _scope(),
            scope_contract_id="scope-contract:chapter-design",
            narrative=NarrativeScope(
                kind="CHAPTER",
                book_id="book:1",
                volume_id="volume:1",
                arc_id="arc:1",
                chapter_group_id="chapter-group:1",
                chapter_id="chapter:8",
            ),
            authority=AuthorityScope(
                authority_type="CHAPTER_DESIGN_AUTHORITY",
                allowed_narrative_scopes=("CHAPTER",),
                allowed_change_types=(
                    "core_advantage.create",
                    "core_advantage.revise",
                ),
            ),
        )
        current_snapshot = chapter_contract.freeze(
            snapshot_id="scope-snapshot:chapter:8",
            authority_id="chapter-design-authority:1",
        )
        application.freeze_scope(session.session_id, current_snapshot)
        application.assign_participants(
            session.session_id,
            ParticipantSnapshot.freeze(
                snapshot_id="participants:chapter:8",
                participants=(
                    Participant(
                        "character-design-agent", 1, "PROPOSAL_OWNER"
                    ),
                ),
            ),
        )
        request = ScopeExpansionRequest(
            request_id="scope-expansion:1",
            session_id=session.session_id,
            current_scope_snapshot_ref=current_snapshot.snapshot_id,
            requested_scope=NarrativeScope(
                kind="ARC",
                book_id="book:1",
                volume_id="volume:1",
                arc_id="arc:1",
            ),
            reason="The cost mechanism changes the whole arc escalation.",
            affected_assets=("arc_plan",),
            risk_level="HIGH",
            requesting_agent="character-design-agent",
            required_authority="ARC_DESIGN_AUTHORITY",
        )

        application.request_scope_expansion(request)
        approved_contract = replace(
            chapter_contract,
            scope_contract_id="scope-contract:arc-design",
            version=2,
            narrative=request.requested_scope,
            authority=AuthorityScope(
                authority_type="ARC_DESIGN_AUTHORITY",
                allowed_narrative_scopes=("ARC",),
                allowed_change_types=(
                    "core_advantage.create",
                    "core_advantage.revise",
                ),
            ),
        )
        approved_snapshot = approved_contract.freeze(
            snapshot_id="scope-snapshot:arc:1",
            authority_id="arc-design-authority:1",
        )
        decision = CollaborationDecision(
            decision_id="decision:scope-expansion:1",
            decision=CollaborationDecisionType.SCOPE_EXPANSION_APPROVED,
            authority_type="ARC_DESIGN_AUTHORITY",
            authority_version=1,
            session_id=session.session_id,
            candidate_version_id="",
            accepted_changes=("expand CHAPTER to ARC",),
            rejected_changes=(),
            deferred_changes=(),
            accepted_with_objections=(),
            unresolved_objections=(),
            required_followup=("create successor collaboration",),
            affected_asset_versions=(),
            commit_policy_ref="scope-expansion-policy:v1",
            decision_evidence=(request.request_id,),
        )

        resolved = application.decide_scope_expansion(
            request.request_id,
            decision,
            approved_scope_snapshot=approved_snapshot,
        )

        escalated = repository.get_session(session.session_id)
        self.assertEqual(
            resolved.decision, "SCOPE_EXPANSION_APPROVED"
        )
        self.assertEqual(escalated.status, SessionStatus.ESCALATED)
        self.assertEqual(
            escalated.scope_snapshot_ref, current_snapshot.snapshot_id
        )
        self.assertEqual(
            repository.get_scope_snapshot(approved_snapshot.snapshot_id),
            approved_snapshot,
        )
        successor = application.create_collaboration_session(
            replace(
                _session(),
                session_id="session:arc",
                saga_id="saga:arc",
                created_operation_id="operation:arc",
                owner_authority="ARC_DESIGN_AUTHORITY",
            )
        )
        frozen = application.freeze_scope(
            successor.session_id, approved_snapshot
        )
        self.assertEqual(
            frozen.scope_snapshot_ref, approved_snapshot.snapshot_id
        )

    def _accept(
        self, work_order: AgentWorkOrder, envelope: AgentOutputEnvelope
    ):
        self.application.schedule_next_turn(work_order)
        return self.application.accept_agent_output(work_order, envelope)


def _session() -> AgentCollaborationSession:
    return AgentCollaborationSession(
        session_id="session:1",
        project_id="project:1",
        owner_authority="BOOK_DESIGN_AUTHORITY",
        business_goal="Design the protagonist core advantage mechanism.",
        issue_type="CORE_ADVANTAGE_DESIGN",
        scope_snapshot_ref="",
        participant_snapshot_ref="",
        current_candidate_version_ref="",
        status=SessionStatus.CREATED,
        round_number=0,
        turn_number=0,
        execution_count=0,
        spent_budget=Decimal("0"),
        budget_ref="budget-policy:book-design:v1",
        termination_policy_ref="termination:book-design:v1",
        created_operation_id="operation:root",
        saga_id="saga:1",
        authority_decision_ref="",
        last_turn_id="",
    )


def _execution_evidence(
    work_order: AgentWorkOrder,
) -> DomainExecutionEvidence:
    return DomainExecutionEvidence(
        execution_id=f"execution:{work_order.turn_id}",
        operation_id=work_order.operation_id,
        attempt_id=work_order.attempt_id,
        fencing_token=work_order.fencing_token,
        capability=work_order.execution_capability,
        backend_id="scripted-fixture",
        route_snapshot_id=f"route:{work_order.turn_id}",
        input_manifest_ref=f"input:{work_order.turn_id}",
        output_manifest_ref=f"output:{work_order.turn_id}",
        validation_manifest_ref=f"validation:{work_order.turn_id}",
        usage_receipt_ref=f"usage:{work_order.turn_id}",
        cost_receipt_ref=f"cost:{work_order.turn_id}",
        fixture_protocol_only=True,
        real_model_call=False,
        production_verified=False,
    )


def _scope() -> AgentScopeContract:
    return AgentScopeContract(
        scope_contract_id="scope-contract:book-design",
        version=1,
        narrative=NarrativeScope(kind="BOOK", book_id="book:1"),
        asset_read=AssetReadScope(
            allowed_asset_types=(
                "book_design_candidate",
                "character_card",
                "plot_plan",
            ),
            asset_version_ids=(
                "asset-version:character:1",
                "asset-version:plot:1",
            ),
        ),
        proposal=ProposalScope(
            allowed_asset_types=("book_design_candidate",),
            allowed_change_types=(
                "core_advantage.create",
                "core_advantage.revise",
            ),
            forbidden_asset_types=("canon", "published_chapter"),
            forbidden_change_types=("ending.replace", "canon.mutate"),
        ),
        authority=AuthorityScope(
            authority_type="BOOK_DESIGN_AUTHORITY",
            allowed_narrative_scopes=("BOOK",),
            allowed_change_types=(
                "core_advantage.create",
                "core_advantage.revise",
            ),
        ),
        temporal=TemporalScope(
            past_locked_through=0,
            active_range=(1, 120),
            forecast_horizon=120,
            published_boundary=0,
        ),
        knowledge=KnowledgeVisibilityScope(
            allowed=(
                "AUTHOR_KNOWLEDGE",
                "PUBLIC_CANON",
                "HIDDEN_PLANNING",
            )
        ),
    )


def _work_order(
    number: int,
    message_type: AgentMessageType,
    agent_id: str,
    *,
    candidate: str = "",
) -> AgentWorkOrder:
    return AgentWorkOrder(
        work_order_id=f"work-order:{number}",
        collaboration_session_id="session:1",
        turn_id=f"turn:{number}",
        operation_id=f"operation:{number}",
        attempt_id=f"attempt:{number}",
        fencing_token=number,
        agent_id=agent_id,
        agent_definition_version=1,
        capability="book-design.deliberate",
        message_type=message_type,
        business_goal="Design the protagonist core advantage mechanism.",
        current_issue="Balance agency, cost, plot scaling, and reader payoff.",
        scope_snapshot_ref="scope-snapshot:book:1",
        participant_snapshot_ref="participants:book-design:1",
        input_asset_versions=(
            "asset-version:character:1",
            "asset-version:plot:1",
        ),
        candidate_version_ref=candidate,
        context_bundle_ref=f"context:turn:{number}",
        evidence_refs=(),
        must_preserve=("ending remains unchanged",),
        must_change=(),
        forbidden_changes=("ending.replace", "canon.mutate"),
        acceptance_criteria=("structured output", "scope compliant"),
        risk_level="HIGH",
        budget_policy_ref="budget-policy:book-design:v1",
        timeout_policy_ref="timeout-policy:agent-turn:v1",
        approval_policy_ref="approval-policy:book-design:v1",
        failure_policy="REPAIR_THEN_STOP",
        continuation_policy="AUTHORITY_LED",
        project_id="project:1",
        workspace_id="workspace:agent-collaboration",
        book_id="book:1",
        route_snapshot_ref=f"route:turn:{number}",
        input_manifest_ref=f"input:turn:{number}",
        capability_version=1,
        execution_capability="agent.workspace.execute",
    )


def _envelope(
    number: int,
    message_type: AgentMessageType,
    agent_id: str,
    *,
    target_candidate: str = "",
    candidate_version_id: str = "",
    candidate_type: str = "",
    content_ref: str = "",
    structured_diff: dict | None = None,
    change_reason_refs: tuple[str, ...] = (),
    resolved_conflicts: tuple[str, ...] = (),
    conflict: dict | None = None,
    recommendation: str = "",
    changes: tuple[ProposedAssetChange, ...] | None = None,
) -> AgentOutputEnvelope:
    if changes is None:
        changes = (
            ProposedAssetChange(
                asset_type="book_design_candidate",
                asset_version_id="",
                narrative_scope=NarrativeScope(
                    kind="BOOK",
                    book_id="book:1",
                ),
                change_type=(
                    "core_advantage.create"
                    if message_type is AgentMessageType.PROPOSAL
                    else "core_advantage.revise"
                ),
                knowledge_visibility=KnowledgeVisibility.HIDDEN_PLANNING,
            ),
        ) if message_type in {
            AgentMessageType.PROPOSAL,
            AgentMessageType.REVISION,
            AgentMessageType.COUNTER_PROPOSAL,
        } else ()
    payload = {
        "claim": f"structured {message_type.value.lower()}",
        "target_candidate_version_id": target_candidate,
        "candidate_version_id": candidate_version_id,
        "candidate_type": candidate_type,
        "content_ref": content_ref,
        "structured_diff": structured_diff or {},
        "change_reason_refs": list(change_reason_refs),
        "resolved_conflicts": list(resolved_conflicts),
        "unresolved_conflicts": [],
        "conflict": conflict or {},
        "recommendation": recommendation,
    }
    return AgentOutputEnvelope(
        output_id=f"output:{number}",
        session_id="session:1",
        turn_id=f"turn:{number}",
        agent_id=agent_id,
        message_type=message_type,
        structured_payload=payload,
        natural_language_explanation=f"Turn {number} explanation.",
        source_asset_versions=(
            "asset-version:character:1",
            "asset-version:plot:1",
        ),
        evidence_refs=(f"evidence:{number}",),
        assumptions=("fixture assumptions",),
        confidence=0.8,
        affected_assets=tuple(change.asset_type for change in changes),
        proposed_changes=changes,
        preserved_constraints=("ending remains unchanged",),
        accessed_knowledge=(KnowledgeVisibility.HIDDEN_PLANNING,),
        unresolved_questions=(),
        risk_level="HIGH",
        requested_next_action="CONTINUE",
        execution_evidence_ref=f"execution-evidence:{number}",
    )


if __name__ == "__main__":
    unittest.main()
