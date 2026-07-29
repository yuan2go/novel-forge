from __future__ import annotations

import hashlib
import unittest

from novel_forge.modules.agent_collaboration import (
    AgentCollaborationApplication,
    AgentMessageType,
    InMemoryAgentCollaborationRepository,
    Participant,
    ParticipantSnapshot,
    ProposedAssetChange,
    KnowledgeVisibility,
    NarrativeScope,
)
from novel_forge.modules.production_execution import (
    AdmissionController,
    ArtifactPointer,
    CompletionMode,
    ExecutionBackendRegistry,
    ExecutionCapabilityProfile,
    ExecutionRequest,
    ExecutionRuntimeClass,
    GatewayDomainExecutionPort,
    InMemoryExecutionRecordStore,
    InputManifest,
    ModelProfile,
    ModelProfileStatus,
    ProductionExecutionGateway,
    ResolvedExecutionPayload,
    RoutePolicy,
    RouteSnapshot,
    ScriptedFixtureExecutionBackend,
    StaticAttemptFenceVerifier,
    StaticExecutionContractSource,
    StaticExecutionPayloadResolver,
    default_capability_registry,
)
from tests.unit.test_agent_collaboration_application import (
    _envelope,
    _scope,
    _session,
    _work_order,
)


class AgentCollaborationPepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAgentCollaborationRepository()
        self.application = AgentCollaborationApplication(self.repository)
        session = self.application.create_collaboration_session(_session())
        self.application.freeze_scope(
            session.session_id,
            _scope().freeze(
                snapshot_id="scope-snapshot:book:1",
                authority_id="book-design-authority:1",
            ),
        )
        self.application.assign_participants(
            session.session_id,
            ParticipantSnapshot.freeze(
                snapshot_id="participants:book-design:1",
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

    def test_agent_turn_traverses_gateway_and_freezes_route_evidence(self) -> None:
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        envelope = _envelope(
            1,
            AgentMessageType.PROPOSAL,
            "character-design-agent",
            candidate_version_id="candidate:v1",
            candidate_type="BOOK_DESIGN_CORE_ADVANTAGE",
            content_ref="content:candidate:v1",
            structured_diff={"op": "create", "path": "/core_advantage"},
        )
        port, store, route = _gateway_port(
            work_order, envelope.to_dict()
        )

        result = self.application.execute_turn(work_order, port)
        replay = self.application.execute_turn(work_order, port)

        self.assertEqual(result, replay)
        self.assertTrue(result.attempt_completion_allowed)
        self.assertEqual(result.candidate_version_id, "candidate:v1")
        persisted = self.repository.find_output_by_turn(work_order.turn_id)
        self.assertIsNotNone(persisted)
        validation = store.read_evidence(persisted.execution_evidence_ref)
        self.assertIn(route.route_snapshot_id, str(validation["checks"]))
        self.assertEqual(
            store.get_record(f"execution:{work_order.turn_id}")
            .request.route_snapshot_id,
            route.route_snapshot_id,
        )

    def test_backend_success_can_still_be_rejected_by_scope_policy(self) -> None:
        work_order = _work_order(
            1, AgentMessageType.PROPOSAL, "character-design-agent"
        )
        envelope = _envelope(
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
                        kind="BOOK", book_id="book:1"
                    ),
                    change_type="ending.replace",
                    knowledge_visibility=KnowledgeVisibility.HIDDEN_PLANNING,
                ),
            ),
        )
        port, _, _ = _gateway_port(work_order, envelope.to_dict())

        result = self.application.execute_turn(work_order, port)

        self.assertTrue(result.backend_success)
        self.assertTrue(result.schema_validation_passed)
        self.assertFalse(result.scope_validation_passed)
        self.assertFalse(result.conversation_message_accepted)
        self.assertFalse(result.attempt_completion_allowed)
        self.assertEqual(
            self.repository.candidates(work_order.collaboration_session_id),
            (),
        )


def _gateway_port(work_order, result):
    definition = default_capability_registry().resolve(
        work_order.execution_capability
    )
    capability = ExecutionCapabilityProfile(
        backend_id="scripted-fixture",
        backend_version="1.0.0",
        runtime_class=ExecutionRuntimeClass.SCRIPTED_FIXTURE,
        supported_completion_modes=(
            CompletionMode.SYNCHRONOUS,
            CompletionMode.POLL,
        ),
        supported_reasoning_efforts=("high", "xhigh"),
        supports_query=True,
        supports_cancel=True,
        supports_callback=False,
        supports_usage_receipt=True,
        supports_cost_receipt=True,
        supports_structured_output=True,
        supports_process_group_control=False,
        supports_persistent_execution_directory=False,
        supports_provider_idempotency=True,
        real_provider_validation_eligible=False,
        qualification_ref="capability-probe:scripted-fixture:1",
    )
    profile = ModelProfile(
        profile_id="agent.fixture",
        profile_version=1,
        backend_id=capability.backend_id,
        runtime_class=capability.runtime_class,
        model_provider="fixture",
        model_id="scripted-agent",
        reasoning_effort="xhigh",
        timeout_policy_ref=definition.timeout_policy_ref,
        workspace_policy_ref="workspace:agent",
        output_policy_ref="output:agent-envelope",
        fallback_policy="FAIL_CLOSED",
        status=ModelProfileStatus.ACTIVE,
        capability_probe_ref=capability.qualification_ref,
    )
    policy = RoutePolicy(
        policy_id="agent.fixture",
        policy_version=1,
        default_model_profile_id=profile.profile_id,
        allowed_model_profile_ids=(profile.profile_id,),
        rule_set_ref="route-rules:agent:1",
        fallback_policy="FAIL_CLOSED",
        fallback_policy_ref="agent.fixture.fail-closed",
        fallback_policy_version=1,
        reasoning_downgrade_policy="PROHIBITED",
        status="ACTIVE",
    )
    route = RouteSnapshot(
        route_snapshot_id=work_order.route_snapshot_ref,
        route_decision_id=f"route-decision:{work_order.turn_id}",
        operation_id=work_order.operation_id,
        attempt_id=work_order.attempt_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        backend_id=capability.backend_id,
        backend_version=capability.backend_version,
        runtime_host_id="host:fixture",
        auth_profile_ref="auth:fixture",
        model_profile_id=profile.profile_id,
        model_profile_version=profile.profile_version,
        model_provider=profile.model_provider,
        model_id=profile.model_id,
        requested_reasoning_effort="xhigh",
        reasoning_effort="xhigh",
        prompt_bundle_ref=f"prompt:{work_order.turn_id}",
        skill_bundle_ref=f"skills:{work_order.turn_id}",
        context_bundle_ref=work_order.context_bundle_ref,
        output_schema_ref="schema:agent-output-envelope:v1",
        release_sha="a" * 40,
        fallback_policy_ref=policy.fallback_policy_ref,
        fallback_policy_version=policy.fallback_policy_version,
    )
    artifacts = tuple(
        ArtifactPointer(
            artifact_ref=version_id,
            artifact_type=(
                "character_card"
                if "character" in version_id
                else "plot_plan"
            ),
            content_hash="sha256:"
            + hashlib.sha256(version_id.encode()).hexdigest(),
            schema_version="agent-input.v1",
            source_eligibility="FIXTURE_ELIGIBLE",
        )
        for version_id in work_order.input_asset_versions
    )
    target_scope = {
        "scope_kind": "book",
        "scope_id": work_order.book_id,
        "book_id": work_order.book_id,
    }
    manifest = InputManifest(
        manifest_id=work_order.input_manifest_ref,
        operation_id=work_order.operation_id,
        attempt_id=work_order.attempt_id,
        fencing_token=work_order.fencing_token,
        project_id=work_order.project_id,
        book_id=work_order.book_id,
        target_scope=target_scope,
        context_bundle_ref=route.context_bundle_ref,
        prompt_bundle_ref=route.prompt_bundle_ref,
        skill_bundle_ref=route.skill_bundle_ref,
        context_bundle_version=route.context_bundle_ref,
        prompt_bundle_version=route.prompt_bundle_ref,
        skill_bundle_version=route.skill_bundle_ref,
        canon_snapshot_version="canon:1",
        story_state_version="story-state:none",
        planning_version=artifacts[-1].asset_version_id,
        quality_profile_version="quality:agent:1",
        source_policy_ref=definition.source_policy_ref,
        source_eligibility="FIXTURE_ELIGIBLE",
        canon_version_refs=("canon:1",),
        arc_version_refs=("arc:1",),
        input_artifacts=artifacts,
        read_set=tuple(item.artifact_ref for item in artifacts),
    )
    request = ExecutionRequest(
        execution_id=f"execution:{work_order.turn_id}",
        operation_id=work_order.operation_id,
        root_operation_id="operation:root",
        saga_id="saga:1",
        attempt_id=work_order.attempt_id,
        fencing_token=work_order.fencing_token,
        project_id=work_order.project_id,
        workspace_id=work_order.workspace_id,
        book_id=work_order.book_id,
        target_scope=target_scope,
        domain=definition.domain.value,
        task_kind="agent.collaboration.turn",
        stage="deliberation",
        capability=work_order.execution_capability,
        importance_class="HIGH",
        risk_class=definition.risk_class.value,
        route_snapshot_id=route.route_snapshot_id,
        workspace_snapshot_ref=work_order.workspace_id,
        input_manifest_ref=manifest.manifest_id,
        resource_claims=("fixture:agent-turn",),
        timeout_policy_ref=definition.timeout_policy_ref,
        budget_policy_ref=definition.budget_policy_ref,
        permission_policy_ref=definition.permission_policy_ref,
        validation_policy_ref=definition.validation_policy_ref,
        commit_policy_ref=definition.commit_policy_ref,
        stable_idempotency_key=f"agent:{work_order.turn_id}",
        trace_id="trace:agent-collaboration",
        correlation_id="correlation:agent-collaboration",
        external_effect_id=f"external-effect:{work_order.turn_id}",
        budget_reservation_id=f"budget:{work_order.turn_id}",
    )
    source = StaticExecutionContractSource(
        route_snapshots=(route,),
        model_profiles=(profile,),
        route_policies=(policy,),
        input_manifests=(manifest,),
    )
    admission = AdmissionController(
        source,
        StaticAttemptFenceVerifier(
            {
                (
                    work_order.operation_id,
                    work_order.attempt_id,
                ): work_order.fencing_token
            }
        ),
    )
    store = InMemoryExecutionRecordStore()
    backend = ScriptedFixtureExecutionBackend(
        admission=admission,
        payload_resolver=StaticExecutionPayloadResolver(
            {
                request.execution_id: ResolvedExecutionPayload(
                    request_payload={"result": result},
                    input_text="frozen AgentWorkOrder",
                    working_directory=".",
                    timeout_seconds=5,
                    output_schema_version="agent-output-envelope.v1",
                )
            }
        ),
        record_store=store,
    )
    registry = ExecutionBackendRegistry()
    registry.register(backend)
    gateway = ProductionExecutionGateway(registry, admission)
    return (
        GatewayDomainExecutionPort(
            gateway=gateway,
            evidence_store=store,
            requests={work_order.execution_capability: request},
        ),
        store,
        route,
    )


if __name__ == "__main__":
    unittest.main()
