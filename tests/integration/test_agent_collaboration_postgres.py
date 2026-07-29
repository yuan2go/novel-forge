from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

import psycopg

from novel_forge.modules.agent_collaboration import (
    AgentCapability,
    AgentCollaborationApplication,
    AgentCollaborationSession,
    AgentDefinition,
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
)
from novel_forge.storage.agent_collaboration_repositories import (
    PostgresAgentCollaborationRepository,
    PostgresAuthorityCandidateCommitter,
)
from tests.unit.test_agent_collaboration_pep import _gateway_port
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    connect,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
)


class AgentCollaborationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("collaboration-project")
        self.session_id = identifier("collaboration-session")
        self.saga_id = identifier("collaboration-saga")
        self.root_operation_id = identifier("collaboration-root-operation")
        self.commit_operation_id = identifier("collaboration-commit-operation")
        self.turn_bindings = [
            (
                identifier(f"turn-operation-{number}"),
                identifier(f"turn-attempt-{number}"),
                1,
            )
            for number in range(1, 5)
        ]
        self._insert_authority_graph()
        self._register_agents()
        self._create_and_freeze_session()

    def test_flow_recovers_across_connections_and_commits_authority_asset(self) -> None:
        proposal = _envelope(
            self.session_id,
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id=f"{self.session_id}:candidate:v1",
            content_ref="pep-evidence:proposal:v1",
            structured_diff={"op": "create", "path": "/core_advantage"},
        )
        first = self._accept(1, proposal)
        replay = self._accept(1, proposal)
        self.assertEqual(first, replay)

        candidate_v1 = first.candidate_version_id
        challenge = _envelope(
            self.session_id,
            2,
            AgentMessageType.CHALLENGE,
            "plot-architecture-agent",
            target_candidate=candidate_v1,
            conflict={
                "conflict_id": f"{self.session_id}:conflict:scale",
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
        )
        challenge_result = self._accept(2, challenge, candidate=candidate_v1)
        self.assertEqual(
            challenge_result.conflict_ids,
            (f"{self.session_id}:conflict:scale",),
        )

        revision = _envelope(
            self.session_id,
            3,
            AgentMessageType.REVISION,
            "character-design-agent",
            target_candidate=candidate_v1,
            candidate_version_id=f"{self.session_id}:candidate:v2",
            content_ref="pep-evidence:revision:v2",
            structured_diff={
                "op": "add",
                "path": "/core_advantage/escalating_cost",
                "value": "memory erosion",
            },
            change_reason_refs=(f"{self.session_id}:message:2",),
            resolved_conflicts=(f"{self.session_id}:conflict:scale",),
        )
        revision_result = self._accept(3, revision, candidate=candidate_v1)
        candidate_v2 = revision_result.candidate_version_id

        evaluation = _envelope(
            self.session_id,
            4,
            AgentMessageType.EVALUATION,
            "reader-outcome-judge",
            target_candidate=candidate_v2,
            recommendation="ACCEPT_WITH_NON_BLOCKING_OBJECTIONS",
        )
        self._accept(4, evaluation, candidate=candidate_v2)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            repository = uow.repositories.agent_collaboration
            application = AgentCollaborationApplication(repository)
            application.record_conflict(
                ConflictRecord(
                    conflict_id=f"{self.session_id}:conflict:calibration",
                    session_id=self.session_id,
                    conflict_type="COST_CALIBRATION",
                    severity=ConflictSeverity.MINOR,
                    raised_by="reader-outcome-judge",
                    target_candidate_version=candidate_v2,
                    conflicting_asset_versions=(),
                    claim="Per-volume cost remains uncalibrated.",
                    evidence_refs=(evaluation.output_id,),
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
            application.request_authority_decision(self.session_id)
            decision = CollaborationDecision(
                decision_id=f"{self.session_id}:decision",
                decision=CollaborationDecisionType.ACCEPTED,
                authority_type="BOOK_DESIGN_AUTHORITY",
                authority_version=1,
                session_id=self.session_id,
                candidate_version_id=candidate_v2,
                accepted_changes=("core advantage", "escalating cost"),
                rejected_changes=(),
                deferred_changes=(),
                accepted_with_objections=("cost calibration remains",),
                unresolved_objections=(),
                required_followup=("calibrate cost per volume",),
                affected_asset_versions=(),
                commit_policy_ref="commit-policy:book-design:v1",
                decision_evidence=(evaluation.output_id,),
            )
            application.apply_authority_decision(decision)
            uow.commit()

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            repository = uow.repositories.agent_collaboration
            application = AgentCollaborationApplication(
                repository,
                authority_committer=PostgresAuthorityCandidateCommitter(
                    uow.cursor,
                    execution_proof={
                        "fixture_protocol_only": True,
                        "real_model_call": False,
                        "production_verified": False,
                    },
                ),
            )
            commit = application.commit_accepted_candidate(
                self.session_id,
                operation_id=self.commit_operation_id,
                idempotency_key=f"commit:{self.session_id}",
            )
            uow.commit()

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            repository = uow.repositories.agent_collaboration
            recovered = AgentCollaborationApplication(
                repository
            ).recover_collaboration_session(self.session_id)
            asset = uow.repositories.asset_documents.require(
                project_id=self.project_id,
                asset_version_id=commit.asset_version_id,
            )
            turn_count = uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_agent_collaboration_turn
                WHERE session_id = %s
                """,
                [self.session_id],
            ).fetchone()[0]
            output_count = uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_agent_output_envelope
                WHERE session_id = %s
                """,
                [self.session_id],
            ).fetchone()[0]

        self.assertEqual(recovered.session.status, SessionStatus.COMMITTED)
        self.assertEqual(recovered.session.turn_number, 4)
        self.assertEqual(turn_count, 4)
        self.assertEqual(output_count, 4)
        self.assertEqual(
            commit.source_lineage,
            (candidate_v1, candidate_v2),
        )
        self.assertEqual(
            asset.content["lineage"]["candidate_version_id"],
            candidate_v2,
        )
        self.assertEqual(
            asset.content["lineage"]["candidate_lineage"],
            [candidate_v1, candidate_v2],
        )
        self.assertTrue(asset.content["fixture_protocol_only"])
        self.assertFalse(asset.content["real_model_call"])
        self.assertFalse(asset.content["production_verified"])
        accepted_objection = next(
            item
            for item in recovered.conflicts
            if item.conflict_id.endswith(":conflict:calibration")
        )
        self.assertEqual(
            accepted_objection.status,
            ConflictStatus.ACCEPTED_NON_BLOCKING,
        )

    def test_scope_candidate_and_output_records_are_immutable(self) -> None:
        proposal = _envelope(
            self.session_id,
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id=f"{self.session_id}:candidate:v1",
            content_ref="pep-evidence:proposal:v1",
            structured_diff={"op": "create"},
        )
        result = self._accept(1, proposal)

        with connect() as connection:
            with self.assertRaises(psycopg.errors.RaiseException):
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE authority_agent_scope_snapshot
                        SET scope_hash = 'mutated'
                        WHERE scope_snapshot_id = %s
                        """,
                        [f"{self.session_id}:scope"],
                    )
            connection.rollback()
            with self.assertRaises(psycopg.errors.RaiseException):
                with connection.transaction():
                    connection.execute(
                        """
                        UPDATE authority_agent_candidate_version
                        SET content_ref = 'mutated'
                        WHERE candidate_version_id = %s
                        """,
                        [result.candidate_version_id],
                    )
            connection.rollback()

    def test_stale_fence_cannot_schedule_turn(self) -> None:
        work_order = self._work_order(
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            fencing_token=99,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            with self.assertRaisesRegex(ValueError, "Attempt fence"):
                application.schedule_next_turn(work_order)

    def test_pep_successful_ending_change_is_scope_rejected_in_postgres(self) -> None:
        envelope = _envelope(
            self.session_id,
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id=f"{self.session_id}:candidate:forbidden",
            content_ref="pep-evidence:forbidden-ending",
            structured_diff={"op": "replace", "path": "/ending"},
        )
        forbidden_change = ProposedAssetChange(
            asset_type="book_design_candidate",
            asset_version_id="",
            narrative_scope=NarrativeScope(
                kind="BOOK", book_id="book:1"
            ),
            change_type="ending.replace",
            knowledge_visibility=KnowledgeVisibility.HIDDEN_PLANNING,
        )
        envelope = replace(
            envelope,
            proposed_changes=(forbidden_change,),
            affected_assets=(forbidden_change.asset_type,),
        )

        result = self._accept(1, envelope)

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            repository = uow.repositories.agent_collaboration
            recovered = AgentCollaborationApplication(
                repository
            ).recover_collaboration_session(self.session_id)
        self.assertTrue(result.backend_success)
        self.assertFalse(result.scope_validation_passed)
        self.assertFalse(result.conversation_message_accepted)
        self.assertEqual(
            recovered.session.status, SessionStatus.SCOPE_VIOLATION
        )
        self.assertEqual(recovered.messages, ())
        self.assertEqual(recovered.candidates, ())

    def test_authority_commit_rolls_back_on_crash_and_replays_once(self) -> None:
        proposal = _envelope(
            self.session_id,
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id=f"{self.session_id}:candidate:v1",
            content_ref="pep-evidence:proposal:v1",
            structured_diff={"op": "create", "path": "/core_advantage"},
        )
        proposal_result = self._accept(1, proposal)
        evaluation = _envelope(
            self.session_id,
            2,
            AgentMessageType.EVALUATION,
            "reader-outcome-judge",
            target_candidate=proposal_result.candidate_version_id,
            recommendation="ACCEPT",
        )
        self._accept(
            2,
            evaluation,
            candidate=proposal_result.candidate_version_id,
        )
        decision = CollaborationDecision(
            decision_id=f"{self.session_id}:decision:crash",
            decision=CollaborationDecisionType.ACCEPTED,
            authority_type="BOOK_DESIGN_AUTHORITY",
            authority_version=1,
            session_id=self.session_id,
            candidate_version_id=proposal_result.candidate_version_id,
            accepted_changes=("core advantage",),
            rejected_changes=(),
            deferred_changes=(),
            accepted_with_objections=(),
            unresolved_objections=(),
            required_followup=(),
            affected_asset_versions=(),
            commit_policy_ref="commit-policy:book-design:v1",
            decision_evidence=(evaluation.output_id,),
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            application.request_authority_decision(self.session_id)
            application.apply_authority_decision(decision)
            uow.commit()

        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                application = AgentCollaborationApplication(
                    uow.repositories.agent_collaboration,
                    authority_committer=PostgresAuthorityCandidateCommitter(
                        uow.cursor,
                        execution_proof={
                            "fixture_protocol_only": True,
                            "real_model_call": False,
                            "production_verified": False,
                        },
                    ),
                )
                application.commit_accepted_candidate(
                    self.session_id,
                    operation_id=self.commit_operation_id,
                    idempotency_key=f"commit:{self.session_id}:crash",
                )
                raise RuntimeError("simulated crash before transaction commit")

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            self.assertIsNone(
                uow.repositories.agent_collaboration.find_commit(
                    self.session_id
                )
            )
            self.assertEqual(
                uow.repositories.agent_collaboration.get_session(
                    self.session_id
                ).status,
                SessionStatus.ACCEPTED,
            )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration,
                authority_committer=PostgresAuthorityCandidateCommitter(
                    uow.cursor,
                    execution_proof={
                        "fixture_protocol_only": True,
                        "real_model_call": False,
                        "production_verified": False,
                    },
                ),
            )
            first = application.commit_accepted_candidate(
                self.session_id,
                operation_id=self.commit_operation_id,
                idempotency_key=f"commit:{self.session_id}:crash",
            )
            uow.commit()

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration,
                authority_committer=PostgresAuthorityCandidateCommitter(
                    uow.cursor,
                    execution_proof={
                        "fixture_protocol_only": True,
                        "real_model_call": False,
                        "production_verified": False,
                    },
                ),
            )
            replay = application.commit_accepted_candidate(
                self.session_id,
                operation_id=self.commit_operation_id,
                idempotency_key=f"commit:{self.session_id}:crash",
            )
            asset_count = uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_asset_version
                WHERE asset_version_id = %s
                """,
                [first.asset_version_id],
            ).fetchone()[0]

        self.assertEqual(first, replay)
        self.assertEqual(asset_count, 1)

    def test_scope_expansion_decision_creates_new_snapshot_not_mutation(self) -> None:
        session_id = identifier("chapter-collaboration")
        saga_id = identifier("chapter-collaboration-saga")
        operation_id = identifier("chapter-collaboration-operation")
        definition_name = identifier("chapter-collaboration-definition")
        with connect() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=self.project_id,
                status="EXECUTING",
            )
            cursor.execute(
                """
                INSERT INTO authority_saga (
                    saga_id, root_operation_id, project_id, status,
                    trace_id, correlation_id
                ) VALUES (%s, %s, %s, 'RUNNING', %s, %s)
                """,
                [
                    saga_id,
                    operation_id,
                    self.project_id,
                    f"trace:{session_id}",
                    f"correlation:{session_id}",
                ],
            )
            cursor.execute(
                """
                UPDATE authority_operation
                SET saga_id = %s
                WHERE operation_id = %s
                """,
                [saga_id, operation_id],
            )

        chapter_contract = replace(
            _scope(),
            scope_contract_id=f"{session_id}:scope-contract:chapter",
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
            snapshot_id=f"{session_id}:scope:chapter",
            authority_id="chapter-design-authority:fixture",
        )
        participant_snapshot = ParticipantSnapshot.freeze(
            snapshot_id=f"{session_id}:participants",
            participants=(
                Participant(
                    "character-design-agent", 1, "PROPOSAL_OWNER"
                ),
            ),
        )
        session = AgentCollaborationSession(
            session_id=session_id,
            project_id=self.project_id,
            owner_authority="CHAPTER_DESIGN_AUTHORITY",
            business_goal="Repair a chapter-level advantage cost.",
            issue_type="CHAPTER_ADVANTAGE_REPAIR",
            scope_snapshot_ref="",
            participant_snapshot_ref="",
            current_candidate_version_ref="",
            status=SessionStatus.CREATED,
            round_number=0,
            turn_number=0,
            execution_count=0,
            spent_budget=Decimal("0"),
            budget_ref="budget-policy:book-design:v1",
            termination_policy_ref="termination-policy:book-design:v1",
            created_operation_id=operation_id,
            saga_id=saga_id,
            authority_decision_ref="",
            last_turn_id="",
        )
        requested_scope = NarrativeScope(
            kind="ARC",
            book_id="book:1",
            volume_id="volume:1",
            arc_id="arc:1",
        )
        request = ScopeExpansionRequest(
            request_id=f"{session_id}:scope-expansion",
            session_id=session_id,
            current_scope_snapshot_ref=current_snapshot.snapshot_id,
            requested_scope=requested_scope,
            reason="The root cause changes the complete arc escalation.",
            affected_assets=("arc_plan",),
            risk_level="HIGH",
            requesting_agent="character-design-agent",
            required_authority="ARC_DESIGN_AUTHORITY",
        )
        approved_snapshot = replace(
            chapter_contract,
            scope_contract_id=f"{session_id}:scope-contract:arc",
            version=2,
            narrative=requested_scope,
            authority=AuthorityScope(
                authority_type="ARC_DESIGN_AUTHORITY",
                allowed_narrative_scopes=("ARC",),
                allowed_change_types=(
                    "core_advantage.create",
                    "core_advantage.revise",
                ),
            ),
        ).freeze(
            snapshot_id=f"{session_id}:scope:arc",
            authority_id="arc-design-authority:fixture",
        )
        decision = CollaborationDecision(
            decision_id=f"{session_id}:scope-decision",
            decision=CollaborationDecisionType.SCOPE_EXPANSION_APPROVED,
            authority_type="ARC_DESIGN_AUTHORITY",
            authority_version=1,
            session_id=session_id,
            candidate_version_id="",
            accepted_changes=("expand CHAPTER to ARC",),
            rejected_changes=(),
            deferred_changes=(),
            accepted_with_objections=(),
            unresolved_objections=(),
            required_followup=("create successor session",),
            affected_asset_versions=(),
            commit_policy_ref="scope-expansion-policy:v1",
            decision_evidence=(request.request_id,),
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            application.create_collaboration_session(session)
            application.freeze_scope(session_id, current_snapshot)
            application.assign_participants(
                session_id, participant_snapshot
            )
            application.request_scope_expansion(request)
            resolved = application.decide_scope_expansion(
                request.request_id,
                decision,
                approved_scope_snapshot=approved_snapshot,
            )
            uow.commit()

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            recovered = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            ).recover_collaboration_session(session_id)
            candidate_id = uow.cursor.execute(
                """
                SELECT candidate_version_id
                FROM authority_agent_collaboration_decision
                WHERE decision_id = %s
                """,
                [decision.decision_id],
            ).fetchone()[0]

        self.assertEqual(
            resolved.decision, "SCOPE_EXPANSION_APPROVED"
        )
        self.assertIsNone(candidate_id)
        self.assertEqual(
            recovered.session.scope_snapshot_ref,
            current_snapshot.snapshot_id,
        )
        self.assertEqual(recovered.session.status, SessionStatus.ESCALATED)

    def _accept(
        self,
        number: int,
        envelope: AgentOutputEnvelope,
        *,
        candidate: str = "",
    ):
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            work_order = self._work_order(
                number,
                envelope.message_type,
                envelope.agent_id,
                candidate=candidate,
            )
            execution_port, _, _ = _gateway_port(
                work_order, envelope.to_dict()
            )
            result = application.execute_turn(
                work_order, execution_port
            )
            uow.commit()
            return result

    def _work_order(
        self,
        number: int,
        message_type: AgentMessageType,
        agent_id: str,
        *,
        candidate: str = "",
        fencing_token: int | None = None,
    ) -> AgentWorkOrder:
        operation_id, attempt_id, token = self.turn_bindings[number - 1]
        return AgentWorkOrder(
            work_order_id=f"{self.session_id}:work-order:{number}",
            collaboration_session_id=self.session_id,
            turn_id=f"{self.session_id}:turn:{number}",
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=token if fencing_token is None else fencing_token,
            agent_id=agent_id,
            agent_definition_version=1,
            capability="book-design.deliberate",
            message_type=message_type,
            business_goal="Design the protagonist core advantage mechanism.",
            current_issue="Balance agency, cost, plot scaling, and reader payoff.",
            scope_snapshot_ref=f"{self.session_id}:scope",
            participant_snapshot_ref=f"{self.session_id}:participants",
            input_asset_versions=(
                "asset-version:character:1",
                "asset-version:plot:1",
            ),
            candidate_version_ref=candidate,
            context_bundle_ref=f"{self.session_id}:context:{number}",
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
            project_id=self.project_id,
            workspace_id="workspace:agent-collaboration",
            book_id="book:1",
            route_snapshot_ref=(
                f"{self.session_id}:route:{number}"
            ),
            input_manifest_ref=(
                f"{self.session_id}:input:{number}"
            ),
            capability_version=1,
            execution_capability="agent.workspace.execute",
        )

    def _insert_authority_graph(self) -> None:
        definition_name = identifier("agent-collaboration-operation")
        with connect() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=self.root_operation_id,
                definition_name=definition_name,
                project_id=self.project_id,
                status="EXECUTING",
            )
            cursor.execute(
                """
                INSERT INTO authority_saga (
                    saga_id, root_operation_id, project_id, status,
                    trace_id, correlation_id
                ) VALUES (%s, %s, %s, 'RUNNING', %s, %s)
                """,
                [
                    self.saga_id,
                    self.root_operation_id,
                    self.project_id,
                    f"trace:{self.session_id}",
                    f"correlation:{self.session_id}",
                ],
            )
            cursor.execute(
                """
                UPDATE authority_operation
                SET saga_id = %s
                WHERE operation_id = %s
                """,
                [self.saga_id, self.root_operation_id],
            )
            for ordinal, (operation_id, attempt_id, token) in enumerate(
                self.turn_bindings, 1
            ):
                insert_operation(
                    cursor,
                    operation_id=operation_id,
                    definition_name=definition_name,
                    project_id=self.project_id,
                    status="EXECUTING",
                    root_operation_id=self.root_operation_id,
                    parent_operation_id=self.root_operation_id,
                )
                cursor.execute(
                    """
                    UPDATE authority_operation
                    SET saga_id = %s, step_key = %s
                    WHERE operation_id = %s
                    """,
                    [self.saga_id, f"agent-turn-{ordinal}", operation_id],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_saga_step (
                        saga_id, operation_id, step_key, ordinal
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    [
                        self.saga_id,
                        operation_id,
                        f"agent-turn-{ordinal}",
                        ordinal,
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_attempt (
                        attempt_id, operation_id, attempt_number, status
                    ) VALUES (%s, %s, 1, 'RUNNING')
                    """,
                    [attempt_id, operation_id],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_lease_acquisition (
                        lease_id, attempt_id, owner, fencing_token,
                        expires_at, heartbeat_at, status
                    ) VALUES (
                        %s, %s, %s, %s,
                        NOW() + INTERVAL '10 minutes', NOW(), 'HELD'
                    )
                    """,
                    [
                        identifier("lease"),
                        attempt_id,
                        "collaboration-worker",
                        token,
                    ],
                )
            insert_operation(
                cursor,
                operation_id=self.commit_operation_id,
                definition_name=definition_name,
                project_id=self.project_id,
                status="EXECUTING",
                root_operation_id=self.root_operation_id,
                parent_operation_id=self.root_operation_id,
            )
            cursor.execute(
                """
                UPDATE authority_operation
                SET saga_id = %s, step_key = 'authority-commit'
                WHERE operation_id = %s
                """,
                [self.saga_id, self.commit_operation_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_saga_step (
                    saga_id, operation_id, step_key, ordinal
                ) VALUES (%s, %s, 'authority-commit', 5)
                """,
                [self.saga_id, self.commit_operation_id],
            )

    def _register_agents(self) -> None:
        capability = AgentCapability(
            capability_id="book-design.deliberate",
            version=1,
            domain="book_design",
            input_schema_ref="schema:agent-work-order:v1",
            output_schema_ref="schema:agent-output-envelope:v1",
            supported_message_types=tuple(AgentMessageType),
            supported_scope_types=("BOOK",),
            risk_class="HIGH",
            execution_requirements={"pep_required": True},
            qualification_status="QUALIFIED_FIXTURE",
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            repository: PostgresAgentCollaborationRepository = (
                uow.repositories.agent_collaboration
            )
            repository.register_capability(capability)
            for agent_id, role in (
                ("character-design-agent", "CHARACTER_DESIGN"),
                ("plot-architecture-agent", "PLOT_ARCHITECTURE"),
                ("reader-outcome-judge", "READER_OUTCOME_JUDGE"),
            ):
                repository.register_definition(
                    AgentDefinition(
                        agent_id=agent_id,
                        version=1,
                        agent_type="SPECIALIST",
                        domain="book_design",
                        role=role,
                        capability_refs=("book-design.deliberate@1",),
                        input_contract_ref="schema:agent-work-order:v1",
                        output_contract_ref="schema:agent-output-envelope:v1",
                        authority_scope_ref="scope:book-design:v1",
                        default_scope_policy_ref="scope-policy:book-design:v1",
                        allowed_tools=(
                            "read_asset",
                            "request_production_execution",
                        ),
                        allowed_context_types=(
                            "context_bundle",
                            "scope_snapshot",
                        ),
                        execution_policy_ref="execution-policy:agent-turn:v1",
                        approval_policy_ref="approval-policy:book-design:v1",
                        quality_policy_ref="quality-policy:book-design:v1",
                        status="ACTIVE",
                    )
                )
            uow.commit()

    def _create_and_freeze_session(self) -> None:
        session = AgentCollaborationSession(
            session_id=self.session_id,
            project_id=self.project_id,
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
            termination_policy_ref="termination-policy:book-design:v1",
            created_operation_id=self.root_operation_id,
            saga_id=self.saga_id,
            authority_decision_ref="",
            last_turn_id="",
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            application = AgentCollaborationApplication(
                uow.repositories.agent_collaboration
            )
            application.create_collaboration_session(session)
            application.freeze_scope(
                self.session_id,
                _scope().freeze(
                    snapshot_id=f"{self.session_id}:scope",
                    authority_id="book-design-authority:fixture",
                ),
            )
            application.assign_participants(
                self.session_id,
                ParticipantSnapshot.freeze(
                    snapshot_id=f"{self.session_id}:participants",
                    participants=(
                        Participant(
                            "character-design-agent", 1, "PROPOSAL_OWNER"
                        ),
                        Participant(
                            "plot-architecture-agent", 1, "CHALLENGER"
                        ),
                        Participant(
                            "reader-outcome-judge", 1, "JUDGE"
                        ),
                    ),
                ),
            )
            uow.commit()


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


def _envelope(
    session_id: str,
    number: int,
    message_type: AgentMessageType,
    agent_id: str,
    *,
    target_candidate: str = "",
    candidate_version_id: str = "",
    content_ref: str = "",
    structured_diff: dict | None = None,
    change_reason_refs: tuple[str, ...] = (),
    resolved_conflicts: tuple[str, ...] = (),
    conflict: dict | None = None,
    recommendation: str = "",
) -> AgentOutputEnvelope:
    changes = (
        ProposedAssetChange(
            asset_type="book_design_candidate",
            asset_version_id="",
            narrative_scope=NarrativeScope(kind="BOOK", book_id="book:1"),
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
    } else ()
    return AgentOutputEnvelope(
        output_id=f"{session_id}:output:{number}",
        session_id=session_id,
        turn_id=f"{session_id}:turn:{number}",
        agent_id=agent_id,
        message_type=message_type,
        structured_payload={
            "message_id": f"{session_id}:message:{number}",
            "claim": f"structured {message_type.value.lower()}",
            "target_candidate_version_id": target_candidate,
            "candidate_version_id": candidate_version_id,
            "candidate_type": "BOOK_DESIGN_CORE_ADVANTAGE",
            "content_ref": content_ref,
            "structured_diff": structured_diff or {},
            "change_reason_refs": list(change_reason_refs),
            "resolved_conflicts": list(resolved_conflicts),
            "unresolved_conflicts": [],
            "conflict": conflict or {},
            "recommendation": recommendation,
        },
        natural_language_explanation=f"Turn {number} fixture explanation.",
        source_asset_versions=(
            "asset-version:character:1",
            "asset-version:plot:1",
        ),
        evidence_refs=(f"{session_id}:evidence:{number}",),
        assumptions=("fixture assumptions",),
        confidence=0.8,
        affected_assets=tuple(change.asset_type for change in changes),
        proposed_changes=changes,
        preserved_constraints=("ending remains unchanged",),
        accessed_knowledge=(KnowledgeVisibility.HIDDEN_PLANNING,),
        unresolved_questions=(),
        risk_level="HIGH",
        requested_next_action="CONTINUE",
        execution_evidence_ref=f"{session_id}:validation:{number}",
    )


if __name__ == "__main__":
    unittest.main()
