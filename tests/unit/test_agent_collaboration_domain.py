from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

from novel_forge.modules.agent_collaboration import (
    AgentCapability,
    AgentCollaborationSession,
    AgentConversationMessage,
    AgentDefinition,
    AgentMessageType,
    CandidateVersion,
    CollaborationDecision,
    CollaborationDecisionType,
    CollaborationStateMachine,
    ConflictRecord,
    ConflictSeverity,
    ConflictStatus,
    DomainAcceptance,
    Participant,
    ParticipantSnapshot,
    SessionStatus,
    TerminationContext,
    TerminationPolicy,
)


class AgentCollaborationDomainTests(unittest.TestCase):
    def test_definition_and_capability_are_versioned_and_distinct(self) -> None:
        capability = AgentCapability(
            capability_id="character.core_advantage.propose",
            version=1,
            domain="character",
            input_schema_ref="schema:collaboration-input:v1",
            output_schema_ref="schema:agent-output-envelope:v1",
            supported_message_types=(
                AgentMessageType.PROPOSAL,
                AgentMessageType.REVISION,
            ),
            supported_scope_types=("BOOK", "ARC"),
            risk_class="HIGH",
            execution_requirements={"structured_output": True},
            qualification_status="QUALIFIED_FIXTURE",
        )
        definition = AgentDefinition(
            agent_id="character-design-agent",
            version=2,
            agent_type="SPECIALIST",
            domain="character",
            role="CHARACTER_DESIGN",
            capability_refs=(
                "character.core_advantage.propose@1",
            ),
            input_contract_ref="schema:collaboration-input:v1",
            output_contract_ref="schema:agent-output-envelope:v1",
            authority_scope_ref="scope-contract:book-design@1",
            default_scope_policy_ref="scope-policy:book-design:v1",
            allowed_tools=("read_asset", "request_production_execution"),
            allowed_context_types=("context_bundle", "scope_snapshot"),
            execution_policy_ref="execution-policy:agent-turn:v1",
            approval_policy_ref="approval-policy:book-design:v1",
            quality_policy_ref="quality-policy:book-design:v1",
            status="ACTIVE",
        )

        self.assertNotEqual(definition.agent_id, capability.capability_id)
        self.assertEqual(definition.capability_refs[0], f"{capability.capability_id}@1")
        with self.assertRaises(FrozenInstanceError):
            definition.version = 3  # type: ignore[misc]

    def test_participant_snapshot_is_frozen_and_role_complete(self) -> None:
        snapshot = ParticipantSnapshot.freeze(
            snapshot_id="participants:1",
            participants=(
                Participant(
                    agent_id="character-design-agent",
                    agent_definition_version=2,
                    role="PROPOSAL_OWNER",
                ),
                Participant(
                    agent_id="reader-outcome-judge",
                    agent_definition_version=1,
                    role="READER_OUTCOME_JUDGE",
                ),
            ),
        )

        self.assertTrue(snapshot.has_role("PROPOSAL_OWNER"))
        self.assertEqual(len(snapshot.participants), 2)

    def test_message_requires_structured_candidate_target_for_challenge(self) -> None:
        with self.assertRaisesRegex(ValueError, "target candidate"):
            AgentConversationMessage(
                message_id="message:challenge:1",
                session_id="session:1",
                turn_id="turn:2",
                message_type=AgentMessageType.CHALLENGE,
                sender_id="plot-architecture-agent",
                recipient_ids=("character-design-agent",),
                target_proposal_id="message:proposal:1",
                target_candidate_version_id="",
                scope_snapshot_ref="scope-snapshot:1",
                evidence_refs=("evidence:plot:1",),
                parent_message_id="message:proposal:1",
                structured_payload={"claim": "weak escalation path"},
                natural_language="The advantage does not scale into Act II.",
            )

    def test_session_state_machine_rejects_illegal_jump_and_duplicate_turn(self) -> None:
        session = _session()
        frozen = CollaborationStateMachine.transition(
            session, SessionStatus.SCOPE_FROZEN
        )
        with self.assertRaisesRegex(ValueError, "illegal"):
            CollaborationStateMachine.transition(
                frozen, SessionStatus.ACCEPTED
            )

        advanced = replace(frozen, last_turn_id="turn:1", turn_number=1)
        with self.assertRaisesRegex(ValueError, "duplicate turn"):
            advanced.advance_turn("turn:1")

    def test_normal_state_progression_reaches_committed(self) -> None:
        statuses = (
            SessionStatus.SCOPE_FROZEN,
            SessionStatus.PARTICIPANTS_ASSIGNED,
            SessionStatus.INITIAL_PROPOSAL_PENDING,
            SessionStatus.DELIBERATING,
            SessionStatus.REVISION_PENDING,
            SessionStatus.EVALUATING,
            SessionStatus.CONSENSUS_REACHED,
            SessionStatus.AUTHORITY_DECISION_PENDING,
            SessionStatus.ACCEPTED,
            SessionStatus.COMMITTED,
        )
        session = _session()
        for status in statuses:
            session = CollaborationStateMachine.transition(session, status)
        self.assertEqual(session.status, SessionStatus.COMMITTED)

    def test_candidate_version_is_immutable_and_preserves_lineage(self) -> None:
        first = CandidateVersion(
            candidate_version_id="candidate:1",
            session_id="session:1",
            candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
            parent_version_ids=(),
            originating_message_id="message:proposal:1",
            originating_turn_id="turn:1",
            created_by_agent="character-design-agent",
            scope_snapshot_ref="scope-snapshot:1",
            content_ref="content:candidate:1",
            structured_diff={"op": "create"},
            change_reason_refs=("goal:core-advantage",),
            preserved_constraints=("ending unchanged",),
            resolved_conflicts=(),
            unresolved_conflicts=(),
            validation_status="VALID",
        )
        revision = CandidateVersion(
            candidate_version_id="candidate:2",
            session_id="session:1",
            candidate_type=first.candidate_type,
            parent_version_ids=(first.candidate_version_id,),
            originating_message_id="message:revision:1",
            originating_turn_id="turn:3",
            created_by_agent="character-design-agent",
            scope_snapshot_ref=first.scope_snapshot_ref,
            content_ref="content:candidate:2",
            structured_diff={"op": "replace", "path": "/cost"},
            change_reason_refs=("message:challenge:1",),
            preserved_constraints=first.preserved_constraints,
            resolved_conflicts=("conflict:1",),
            unresolved_conflicts=(),
            validation_status="VALID",
        )

        self.assertEqual(revision.parent_version_ids, ("candidate:1",))
        self.assertIn("message:challenge:1", revision.change_reason_refs)
        with self.assertRaises(FrozenInstanceError):
            revision.content_ref = "overwrite"  # type: ignore[misc]

    def test_termination_policy_stops_for_budget_rounds_and_blocking_conflict(self) -> None:
        policy = TerminationPolicy(
            policy_id="termination:book-design:v1",
            max_rounds=3,
            max_turns=8,
            max_executions=8,
            max_budget=Decimal("2.00"),
            required_participant_roles=(
                "PROPOSAL_OWNER",
                "CHALLENGER",
                "JUDGE",
            ),
            required_evaluation_roles=("JUDGE",),
            blocking_issue_threshold=1,
            major_issue_threshold=3,
            unresolved_conflict_policy="BLOCK",
            scope_violation_policy="ESCALATE",
            consensus_policy="AUTHORITY_LED",
        )
        evaluation = policy.evaluate(
            TerminationContext(
                round_number=3,
                turn_number=5,
                execution_count=5,
                spent_budget=Decimal("1.50"),
                participant_roles=frozenset(
                    {"PROPOSAL_OWNER", "CHALLENGER", "JUDGE"}
                ),
                evaluation_roles=frozenset({"JUDGE"}),
                blocking_conflicts=1,
                major_issues=0,
                scope_violations=0,
                human_decision_required=False,
            )
        )

        self.assertTrue(evaluation.must_stop)
        self.assertIn("MAX_ROUNDS_REACHED", evaluation.reasons)
        self.assertIn("BLOCKING_CONFLICT", evaluation.reasons)
        self.assertEqual(
            evaluation.recommended_status, SessionStatus.CONFLICT_UNRESOLVED
        )

    def test_termination_policy_distinguishes_budget_execution_and_human_gates(
        self,
    ) -> None:
        policy = TerminationPolicy(
            policy_id="termination:book-design:v1",
            max_rounds=3,
            max_turns=8,
            max_executions=8,
            max_budget=Decimal("2.00"),
            required_participant_roles=("PROPOSAL_OWNER",),
            required_evaluation_roles=(),
            blocking_issue_threshold=1,
            major_issue_threshold=3,
            unresolved_conflict_policy="BLOCK",
            scope_violation_policy="ESCALATE",
            consensus_policy="AUTHORITY_LED",
        )
        base = dict(
            round_number=1,
            turn_number=1,
            execution_count=1,
            spent_budget=Decimal("0.50"),
            participant_roles=frozenset({"PROPOSAL_OWNER"}),
            evaluation_roles=frozenset(),
            blocking_conflicts=0,
            major_issues=0,
            scope_violations=0,
            human_decision_required=False,
        )

        budget = policy.evaluate(
            TerminationContext(
                **{**base, "spent_budget": Decimal("2.00")}
            )
        )
        executions = policy.evaluate(
            TerminationContext(**{**base, "execution_count": 8})
        )
        human = policy.evaluate(
            TerminationContext(
                **{**base, "human_decision_required": True}
            )
        )

        self.assertEqual(
            budget.recommended_status, SessionStatus.BUDGET_EXHAUSTED
        )
        self.assertEqual(
            executions.recommended_status,
            SessionStatus.MAX_ROUNDS_REACHED,
        )
        self.assertEqual(
            human.recommended_status,
            SessionStatus.HUMAN_DECISION_REQUIRED,
        )

    def test_authority_decision_cannot_accept_blocking_conflict(self) -> None:
        conflict = ConflictRecord(
            conflict_id="conflict:1",
            session_id="session:1",
            conflict_type="ENDING_REACHABILITY",
            severity=ConflictSeverity.BLOCKING,
            raised_by="plot-architecture-agent",
            target_candidate_version="candidate:2",
            conflicting_asset_versions=("plot-plan:1",),
            claim="The mechanism removes the Act III cost.",
            evidence_refs=("evidence:plot:1",),
            affected_scopes=("BOOK",),
            affected_assets=("book_design_candidate",),
            reader_outcome_impact="payoff becomes free",
            continuity_impact="none",
            ending_reachability_impact="blocked",
            requested_resolution="restore irreversible cost",
            status=ConflictStatus.OPEN,
            resolution_ref="",
            authority_decision_ref="",
        )
        decision = CollaborationDecision(
            decision_id="decision:1",
            decision=CollaborationDecisionType.ACCEPTED,
            authority_type="BOOK_DESIGN_AUTHORITY",
            authority_version=1,
            session_id="session:1",
            candidate_version_id="candidate:2",
            accepted_changes=("cost model",),
            rejected_changes=(),
            deferred_changes=(),
            accepted_with_objections=(),
            unresolved_objections=("conflict:1",),
            required_followup=(),
            affected_asset_versions=(),
            commit_policy_ref="commit-policy:book-design:v1",
            decision_evidence=("evaluation:1",),
        )

        with self.assertRaisesRegex(ValueError, "blocking conflict"):
            decision.validate_against((conflict,))

    def test_scope_expansion_decision_does_not_require_candidate(self) -> None:
        decision = CollaborationDecision(
            decision_id="decision:scope:1",
            decision=CollaborationDecisionType.SCOPE_EXPANSION_APPROVED,
            authority_type="ARC_DESIGN_AUTHORITY",
            authority_version=1,
            session_id="session:1",
            candidate_version_id="",
            accepted_changes=("expand CHAPTER to ARC",),
            rejected_changes=(),
            deferred_changes=(),
            accepted_with_objections=(),
            unresolved_objections=(),
            required_followup=("start a successor session",),
            affected_asset_versions=(),
            commit_policy_ref="scope-expansion-policy:v1",
            decision_evidence=("scope-expansion-request:1",),
        )

        self.assertEqual(decision.candidate_version_id, "")
        with self.assertRaisesRegex(ValueError, "candidate"):
            CollaborationDecision(
                decision_id="decision:asset:missing-candidate",
                decision=CollaborationDecisionType.ACCEPTED,
                authority_type="BOOK_DESIGN_AUTHORITY",
                authority_version=1,
                session_id="session:1",
                candidate_version_id="",
                accepted_changes=(),
                rejected_changes=(),
                deferred_changes=(),
                accepted_with_objections=(),
                unresolved_objections=(),
                required_followup=(),
                affected_asset_versions=(),
                commit_policy_ref="commit-policy:v1",
                decision_evidence=("message:1",),
            )

    def test_cancel_and_human_decision_are_deterministic_exception_states(self) -> None:
        session = CollaborationStateMachine.transition(
            _session(), SessionStatus.SCOPE_FROZEN
        )
        cancelled = CollaborationStateMachine.transition(
            session, SessionStatus.CANCELLED
        )
        self.assertEqual(cancelled.status, SessionStatus.CANCELLED)

        another = CollaborationStateMachine.transition(
            _session(), SessionStatus.SCOPE_FROZEN
        )
        human = CollaborationStateMachine.transition(
            another, SessionStatus.HUMAN_DECISION_REQUIRED
        )
        self.assertEqual(human.status, SessionStatus.HUMAN_DECISION_REQUIRED)

    def test_domain_acceptance_values_cover_repair_replan_and_human_gate(self) -> None:
        self.assertEqual(DomainAcceptance.REPAIR_REQUIRED.value, "REPAIR_REQUIRED")
        self.assertEqual(DomainAcceptance.REPLAN_REQUIRED.value, "REPLAN_REQUIRED")
        self.assertEqual(
            DomainAcceptance.HUMAN_DECISION_REQUIRED.value,
            "HUMAN_DECISION_REQUIRED",
        )


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
        saga_id="saga:collaboration:1",
        authority_decision_ref="",
        last_turn_id="",
    )


if __name__ == "__main__":
    unittest.main()
