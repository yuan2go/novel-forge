from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from novel_forge.modules.agent_runtime.application import (
    AgentHarnessAdmissionRequest,
    AgentRuntimeAuthorityApplication,
)
from novel_forge.modules.agent_runtime.harness import (
    AcceptedBoundaryRef,
    AgentHarnessBudget,
    AgentHarnessStatus,
    AgentToolKind,
    AgentToolSpec,
    AutonomousAgentRole,
)
from novel_forge.modules.agent_runtime.harness_runtime import (
    build_scripted_agent_harness_factory,
)
from novel_forge.modules.agent_runtime.production import (
    PostgresAgentExecutionContractBinder,
    agent_route_execution_identity,
    build_production_agent_harness_factory,
    canonical_policy_hash,
)
from novel_forge.modules.agent_runtime.policy import SERVER_AGENT_TOOL_CATALOG
from novel_forge.api.authority_dependencies import (
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.agent_runtime.scheduler import AgentAuthorityScheduler
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.production import (
    PostgresBookAuthority,
    StartBookProductionCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    plan_external_effect,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    connect,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
)
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as book_fixtures,
)
from tests.integration.capability_pack_postgres_support import (
    CapabilityPackPostgresHarness,
)


RELEASE_SHA = "9" * 40


class _UnusedPort:
    pass


class _SimulatedProcessCrash(BaseException):
    pass


class AgentHarnessSchedulerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def _admit_fixture(
        self, *, execution_contract: dict[str, object] | None = None
    ) -> tuple[str, str, str, str]:
        project_id = identifier("agent-harness-recovery")
        workspace_id = f"workspace:{project_id}"
        book_id = f"book:{project_id}"
        actor_id = "agent-harness-recovery-operator"
        worker_id = "agent-harness-recovery-worker"
        seed_authority_project_book(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
        )
        versions = (
            book_fixtures.BookToChapterAuthorityVerticalPostgresTests._seed_book_inputs(
                project_id
            )
        )
        principal = Principal(
            principal_id=actor_id,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {"book.authority.execute", "agent.authority.execute"}
            ),
            project_scope=frozenset({project_id}),
            authentication_source="integration-fixture",
        )
        book = PostgresBookAuthority(
            DATABASE_URL,
            chapter_port=_UnusedPort(),  # type: ignore[arg-type]
            followup_application=_UnusedPort(),  # type: ignore[arg-type]
            application_build_id="agent-harness-recovery",
            commit_sha=RELEASE_SHA,
            legacy_fixture_input_allowed=True,
        ).start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=actor_id,
                trace_id=identifier("agent-harness-recovery-book-trace"),
                correlation_id=identifier("agent-harness-recovery-book-correlation"),
                stable_idempotency_key=f"{project_id}:book",
                book_design_version=versions.pop("book_design_version"),
                book_plan_version=versions.pop("book_plan_version"),
                production_profile_version="production-profile:v1",
                longform_context_versions=versions,
                target_chapter_count=1,
                input_mode="LEGACY_FIXTURE_INPUT_MODE",
            ),
            principal=principal,
        )
        session_id = identifier("agent-recovery-session")
        application = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id="agent-harness-recovery",
            commit_sha=RELEASE_SHA,
            runtime_environment="test",
        )
        admission_request = AgentHarnessAdmissionRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=actor_id,
            agent_session_id=session_id,
            agent_role=AutonomousAgentRole.STUDIO_DIRECTOR,
            instruction="Propose a direction at the accepted boundary.",
            accepted_boundary=AcceptedBoundaryRef(
                book_id=book_id,
                book_run_id=book.book_run_id,
                accepted_through_chapter=0,
                acceptance_id="",
                projection_set_id="",
            ),
            tool_policy=(
                AgentToolSpec(
                    tool_name="narrative.query_accepted",
                    kind=AgentToolKind.READ_ONLY_QUERY,
                    input_schema_ref="schema:accepted-query:v1",
                    output_schema_ref="schema:accepted-result:v1",
                    allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
                ),
            ),
            skill_bindings=(
                {
                    "skill_id": "studio-direction",
                    "skill_version": "1.0.0",
                    "skill_hash": "sha256:" + "b" * 64,
                },
            ),
            budget=AgentHarnessBudget(
                max_turns=3,
                max_tool_calls=2,
                max_external_effects=3,
                max_input_tokens=100,
                max_output_tokens=100,
                max_cost_amount="1",
            ),
            idempotency_key=f"{project_id}:agent-session",
            trace_id=identifier("agent-harness-recovery-trace"),
            correlation_id=identifier("agent-harness-recovery-correlation"),
            execution_contract=dict(execution_contract or {}),
            execution_contract_hash=(
                canonical_policy_hash(execution_contract) if execution_contract else ""
            ),
        )
        with self.assertRaisesRegex(
            KernelError, "latest complete accepted projection set"
        ):
            application.admit_harness_session(
                replace(
                    admission_request,
                    agent_session_id=identifier("stale-agent-session"),
                    accepted_boundary=AcceptedBoundaryRef(
                        book_id=book_id,
                        book_run_id=book.book_run_id,
                        accepted_through_chapter=1,
                        acceptance_id="missing-acceptance",
                        projection_set_id="missing-projection",
                    ),
                    idempotency_key=f"{project_id}:stale-agent-session",
                ),
                principal=principal,
            )
        admitted = application.admit_harness_session(
            admission_request,
            principal=principal,
        )
        return project_id, session_id, str(admitted["operation_id"]), worker_id

    def test_session_executes_on_attempt_lease_and_commits_transcript_only(
        self,
    ) -> None:
        project_id = identifier("agent-harness-runtime")
        workspace_id = f"workspace:{project_id}"
        book_id = f"book:{project_id}"
        actor_id = "agent-harness-operator"
        worker_id = "agent-harness-worker"
        seed_authority_project_book(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
        )
        versions = (
            book_fixtures.BookToChapterAuthorityVerticalPostgresTests._seed_book_inputs(
                project_id
            )
        )
        book_principal = Principal(
            principal_id=actor_id,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-fixture",
        )
        book_authority = PostgresBookAuthority(
            DATABASE_URL,
            chapter_port=_UnusedPort(),  # type: ignore[arg-type]
            followup_application=_UnusedPort(),  # type: ignore[arg-type]
            application_build_id="agent-harness-integration",
            commit_sha=RELEASE_SHA,
            legacy_fixture_input_allowed=True,
        )
        book = book_authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=actor_id,
                trace_id=identifier("agent-harness-book-trace"),
                correlation_id=identifier("agent-harness-book-correlation"),
                stable_idempotency_key=f"{project_id}:book",
                book_design_version=versions.pop("book_design_version"),
                book_plan_version=versions.pop("book_plan_version"),
                production_profile_version="production-profile:v1",
                longform_context_versions=versions,
                target_chapter_count=1,
                input_mode="LEGACY_FIXTURE_INPUT_MODE",
            ),
            principal=book_principal,
        )

        agent_principal = Principal(
            principal_id=actor_id,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"agent.authority.execute"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-fixture",
        )
        application = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id="agent-harness-integration",
            commit_sha=RELEASE_SHA,
            runtime_environment="test",
        )
        session_id = identifier("agent-session")
        admitted = application.admit_harness_session(
            AgentHarnessAdmissionRequest(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=actor_id,
                agent_session_id=session_id,
                agent_role=AutonomousAgentRole.STUDIO_DIRECTOR,
                instruction="Propose the next direction without mutating truth.",
                accepted_boundary=AcceptedBoundaryRef(
                    book_id=book_id,
                    book_run_id=book.book_run_id,
                    accepted_through_chapter=0,
                    acceptance_id="",
                    projection_set_id="",
                ),
                tool_policy=(
                    AgentToolSpec(
                        tool_name="narrative.query_accepted",
                        kind=AgentToolKind.READ_ONLY_QUERY,
                        input_schema_ref="schema:accepted-query:v1",
                        output_schema_ref="schema:accepted-result:v1",
                        allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
                    ),
                ),
                skill_bindings=(
                    {
                        "skill_id": "studio-direction",
                        "skill_version": "1.0.0",
                        "skill_hash": "sha256:" + "a" * 64,
                    },
                ),
                budget=AgentHarnessBudget(
                    max_turns=3,
                    max_tool_calls=2,
                    max_external_effects=3,
                    max_input_tokens=100,
                    max_output_tokens=100,
                    max_cost_amount="1",
                ),
                idempotency_key=f"{project_id}:agent-session",
                trace_id=identifier("agent-harness-trace"),
                correlation_id=identifier("agent-harness-correlation"),
            ),
            principal=agent_principal,
        )
        scheduler = AgentAuthorityScheduler(
            DATABASE_URL,
            execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
            worker_id=worker_id,
            harness_factory=build_scripted_agent_harness_factory(
                DATABASE_URL, worker_id=worker_id
            ),
        )

        tick = scheduler.tick(
            project_id=project_id,
            agent_run_id=str(admitted["operation_id"]),
        )

        self.assertEqual(tick.operation_status, "SUCCEEDED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            session = uow.repositories.agent_runtime.require_harness_session(session_id)
        self.assertIs(session.status, AgentHarnessStatus.COMPLETED)
        with connect() as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM authority_attempt
                     WHERE operation_id=%s),
                    (SELECT COUNT(*) FROM authority_external_effect
                     WHERE operation_id=%s AND status='SUCCEEDED'),
                    (SELECT COUNT(*) FROM authority_agent_transcript_event
                     WHERE agent_session_id=%s),
                    (SELECT COUNT(*) FROM authority_completion_gate
                     WHERE operation_id=%s
                       AND gate_key='agent_session_transcript_committed'
                       AND status='PASSED'),
                    (SELECT COUNT(*)
                     FROM authority_agent_candidate_version AS candidate
                     JOIN authority_agent_work_order AS work_order
                       ON work_order.turn_id=candidate.originating_turn_id
                     WHERE work_order.operation_id=%s)
                """,
                [
                    admitted["operation_id"],
                    admitted["operation_id"],
                    session_id,
                    admitted["operation_id"],
                    admitted["operation_id"],
                ],
            ).fetchone()
        self.assertEqual(tuple(counts), (1, 2, 6, 1, 0))

    def test_completed_transcript_replays_after_process_crash_without_new_effect(
        self,
    ) -> None:
        project_id, session_id, operation_id, worker_id = self._admit_fixture()

        def crash(point: str) -> None:
            raise _SimulatedProcessCrash(point)

        first = AgentAuthorityScheduler(
            DATABASE_URL,
            execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
            worker_id=worker_id,
            harness_factory=build_scripted_agent_harness_factory(
                DATABASE_URL, worker_id=worker_id
            ),
            harness_fault_injector=crash,
            lease_seconds=1,
        )
        with self.assertRaises(_SimulatedProcessCrash):
            first.tick(project_id=project_id, agent_run_id=operation_id)

        with connect() as connection:
            before = connection.execute(
                """
                SELECT operation.status, session.status,
                       (SELECT COUNT(*) FROM authority_external_effect
                        WHERE operation_id=operation.operation_id),
                       (SELECT COUNT(*) FROM authority_agent_transcript_event
                        WHERE agent_session_id=session.agent_session_id),
                       (SELECT attempt_id FROM authority_attempt
                        WHERE operation_id=operation.operation_id
                        ORDER BY attempt_number DESC LIMIT 1)
                FROM authority_operation AS operation
                JOIN authority_agent_harness_session AS session
                  ON session.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [operation_id],
            ).fetchone()
            connection.execute(
                """
                UPDATE authority_lease_acquisition
                SET expires_at=acquired_at + INTERVAL '1 millisecond'
                WHERE attempt_id=%s AND status='HELD'
                """,
                [before[4]],
            )
            connection.commit()
        self.assertEqual(tuple(before[:4]), ("EXECUTING", "COMPLETED", 2, 6))

        recovered = AgentAuthorityScheduler(
            DATABASE_URL,
            execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
            worker_id=f"{worker_id}:recovered",
            harness_factory=build_scripted_agent_harness_factory(
                DATABASE_URL, worker_id=f"{worker_id}:recovered"
            ),
            lease_seconds=1,
        ).tick(project_id=project_id, agent_run_id=operation_id)

        self.assertEqual(recovered.operation_status, "SUCCEEDED")
        self.assertEqual(recovered.attempt_id, str(before[4]))
        with connect() as connection:
            after = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM authority_external_effect
                     WHERE operation_id=%s),
                    (SELECT COUNT(*) FROM authority_agent_transcript_event
                     WHERE agent_session_id=%s),
                    (SELECT COUNT(*) FROM authority_lease_acquisition
                     WHERE attempt_id=%s)
                """,
                [operation_id, session_id, before[4]],
            ).fetchone()
        self.assertEqual(tuple(after), (2, 6, 2))

    def test_execution_contract_is_frozen_on_session_and_operation(self) -> None:
        contract = {
            "contract_version": "agent-session-execution-contract.v1",
            "runtime_binding": {
                "provider": "provider-a",
                "model_id": "model-a",
                "route_policy_id": "route-a",
            },
            "capability_pack_snapshot_hash": "sha256:" + "a" * 64,
            "release_sha": RELEASE_SHA,
        }
        project_id, session_id, operation_id, _worker_id = self._admit_fixture(
            execution_contract=contract
        )
        expected_hash = canonical_policy_hash(contract)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            session = uow.repositories.agent_runtime.require_harness_session(session_id)
            uow.cursor.execute(
                """
                SELECT command_payload->'execution_contract',
                       command_payload->>'execution_contract_hash'
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                """,
                [operation_id, project_id],
            )
            operation_contract = uow.cursor.fetchone()
        self.assertEqual(dict(session.execution_contract), contract)
        self.assertEqual(session.execution_contract_hash, expected_hash)
        self.assertEqual(dict(operation_contract[0]), contract)
        self.assertEqual(str(operation_contract[1]), expected_hash)

    def test_config_change_after_admission_fails_before_provider_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory), database_url=DATABASE_URL
            )
            common = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AGENT_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "objects",
            }
            runtime_a = build_production_execution_composition(
                settings,
                env={**common, "NOVEL_FORGE_AGENT_MODEL": "fixture-agent-model-a"},
            )
            runtime_b = build_production_execution_composition(
                settings,
                env={**common, "NOVEL_FORGE_AGENT_MODEL": "fixture-agent-model-b"},
            )
            binding_a = agent_route_execution_identity(
                runtime_a.gateway.routes["agent_session"],
                capability_pack_id="agent_session_pack",
            )
            contract = {
                "contract_version": "agent-session-execution-contract.v1",
                "runtime_binding": binding_a,
                "capability_pack_snapshot_hash": "sha256:" + "a" * 64,
                "release_sha": RELEASE_SHA,
            }
            project_id, _session_id, operation_id, worker_id = self._admit_fixture(
                execution_contract=contract
            )
            binder = PostgresAgentExecutionContractBinder(
                DATABASE_URL,
                runtime_b.gateway.routes,
                capability_pack_id="agent_session_pack",
                pack_environment="test",
                pack_runtime_profile="test",
                pack_release_channel="VALIDATION",
                pack_required=False,
            )
            factory = build_production_agent_harness_factory(
                DATABASE_URL,
                adapter=runtime_b.gateway,
                capability_binder=binder,
                planning=_UnusedPort(),  # type: ignore[arg-type]
                plan_change=_UnusedPort(),  # type: ignore[arg-type]
                principal=Principal(
                    principal_id="contract-drift-worker",
                    principal_type=PrincipalType.SERVICE,
                    permissions=frozenset(),
                    project_scope=frozenset({project_id}),
                    authentication_source="integration-fixture",
                ),
                worker_id=worker_id,
            )
            with self.assertRaises(KernelError) as caught:
                AgentAuthorityScheduler(
                    DATABASE_URL,
                    execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
                    worker_id=worker_id,
                    harness_factory=factory,
                ).tick(project_id=project_id, agent_run_id=operation_id)
            self.assertEqual(
                caught.exception.code, "AGENT_EXECUTION_RUNTIME_BINDING_DRIFT"
            )
            with connect() as connection:
                count = connection.execute(
                    """
                    SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id=%s AND effect_type='model.invoke'
                    """,
                    [operation_id],
                ).fetchone()[0]
            self.assertEqual(int(count), 0)

    def test_child_capability_budget_rolls_up_without_second_ledger(self) -> None:
        project_id, session_id, operation_id, _worker_id = self._admit_fixture()
        child_operation_id = identifier("agent-capability-child")
        definition_name = identifier("agent-capability-definition")
        with connect() as connection:
            insert_definition(connection.cursor(), definition_name)
            insert_operation(
                connection.cursor(),
                operation_id=child_operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
                causation_operation_id=operation_id,
            )
            connection.commit()
        context = EffectCommandContext(
            operation_id=child_operation_id,
            project_id=project_id,
            actor_id="agent-capability-worker",
            trace_id=identifier("agent-capability-trace"),
            correlation_id=f"agent-session:{session_id}",
            causation_id=operation_id,
        )
        first_effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider="provider-child",
            capability="model.planning",
            stable_idempotency_key=identifier("agent-child-effect-1"),
            request_payload={"candidate_only": True},
            max_attempts=1,
            reversible=False,
            completion_policy="synchronous_final",
        )
        first = reserve_provider_budget(
            DATABASE_URL,
            BudgetReservationRequest(
                operation_id=child_operation_id,
                external_effect_id=str(first_effect["external_effect_id"]),
                project_id=project_id,
                stable_idempotency_key=identifier("agent-child-budget-1"),
                provider="provider-child",
                currency="USD",
                estimated_amount="0.6",
                estimated_tokens=10,
            ),
        )
        settle_provider_budget(
            DATABASE_URL,
            reservation_id=str(first["reservation_id"]),
            project_id=project_id,
            actual_amount="0.6",
            actual_tokens=10,
            evidence={"model_id": "child-model"},
        )
        second_effect = plan_external_effect(
            DATABASE_URL,
            context,
            effect_type="model.invoke",
            provider="provider-child",
            capability="model.planning",
            stable_idempotency_key=identifier("agent-child-effect-2"),
            request_payload={"candidate_only": True},
            max_attempts=1,
            reversible=False,
            completion_policy="synchronous_final",
        )
        with self.assertRaises(KernelError) as caught:
            reserve_provider_budget(
                DATABASE_URL,
                BudgetReservationRequest(
                    operation_id=child_operation_id,
                    external_effect_id=str(second_effect["external_effect_id"]),
                    project_id=project_id,
                    stable_idempotency_key=identifier("agent-child-budget-2"),
                    provider="provider-child",
                    currency="USD",
                    estimated_amount="0.5",
                    estimated_tokens=10,
                ),
            )
        self.assertEqual(caught.exception.code, "AGENT_HARNESS_BUDGET_EXHAUSTED")
        with connect() as connection:
            evidence = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(settled_amount), 0)
                FROM authority_budget_reservation
                WHERE operation_id=%s AND status='SETTLED'
                """,
                [child_operation_id],
            ).fetchone()
            duplicate_session_ledger = connection.execute(
                """
                SELECT COUNT(*) FROM authority_budget_reservation
                WHERE operation_id=%s
                """,
                [operation_id],
            ).fetchone()[0]
        self.assertEqual(int(evidence[0]), 1)
        self.assertEqual(float(evidence[1]), 0.6)
        self.assertEqual(int(duplicate_session_ledger), 0)

    def test_controlled_unbound_harness_fails_before_operation_admission(self) -> None:
        project_id, prior_session_id, _operation_id, _worker_id = self._admit_fixture()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            prior = uow.repositories.agent_runtime.require_harness_session(
                prior_session_id
            )
        actor_id = "agent-harness-recovery-operator"
        principal = Principal(
            principal_id=actor_id,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"agent.authority.execute"}),
            project_scope=frozenset({project_id}),
            authentication_source="integration-fixture",
        )
        session_id = identifier("controlled-unbound-agent-session")
        application = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id="agent-harness-controlled-unbound",
            commit_sha=RELEASE_SHA,
            runtime_environment="validation",
            production_agent_model_binding=None,
        )
        with self.assertRaises(KernelError) as caught:
            application.admit_harness_session(
                AgentHarnessAdmissionRequest(
                    project_id=project_id,
                    workspace_id=prior.workspace_id,
                    book_id=prior.accepted_boundary.book_id,
                    actor_id=actor_id,
                    agent_session_id=session_id,
                    agent_role=prior.role,
                    instruction="This must not become a stranded READY operation.",
                    accepted_boundary=prior.accepted_boundary,
                    tool_policy=prior.tool_policy,
                    skill_bindings=(),
                    budget=prior.budget,
                    idempotency_key=f"{project_id}:controlled-unbound",
                    trace_id=identifier("controlled-unbound-trace"),
                    correlation_id=identifier("controlled-unbound-correlation"),
                    agent_id="studio-director",
                ),
                principal=principal,
            )
        self.assertEqual(
            caught.exception.code, "AGENT_HARNESS_PRODUCTION_MODEL_UNBOUND"
        )
        with connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) FROM authority_agent_harness_session
                WHERE agent_session_id=%s
                """,
                [session_id],
            ).fetchone()[0]
        self.assertEqual(int(count), 0)

    def test_controlled_admission_freezes_deployed_execution_contract(self) -> None:
        pack_harness = CapabilityPackPostgresHarness(
            "agent-session-controlled-admission",
            application_build_id="agent-session-controlled-admission",
            release_sha=RELEASE_SHA,
        )
        pack_path = (
            Path(__file__).resolve().parents[2]
            / "config/capability_packs/agent_session_pack.json"
        )
        pack_harness._base_manifest = json.loads(  # noqa: SLF001
            pack_path.read_text(encoding="utf-8")
        )
        workflow = pack_harness._base_manifest["workflow_template"]  # noqa: SLF001
        pack_harness.workflow_definition_ref = (
            f"{workflow['workflow_id']}@{workflow['workflow_version']}"
        )
        approval_scope = pack_harness.approval_scope(
            environments=("validation",),
            runtime_profiles=("validation",),
        )
        pack = pack_harness.register_compile_approve(
            "1.0.0",
            generation=1,
            approval_scope=approval_scope,
            proof_skill_ref="agent-loop-governance",
            release_sha=RELEASE_SHA,
            target_runtime_profile="validation",
        )
        deployment = pack_harness.deploy(
            pack,
            environment="validation",
            runtime_profile="validation",
        )
        pack_harness.activate(deployment, environment="validation")

        versions = (
            book_fixtures.BookToChapterAuthorityVerticalPostgresTests._seed_book_inputs(
                pack_harness.project_id
            )
        )
        actor_id = f"agent-operator:{pack_harness.project_id}"
        principal = Principal(
            principal_id=actor_id,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {"book.authority.execute", "agent.authority.execute"}
            ),
            project_scope=frozenset({pack_harness.project_id}),
            authentication_source="integration-fixture",
        )
        book = PostgresBookAuthority(
            DATABASE_URL,
            chapter_port=_UnusedPort(),  # type: ignore[arg-type]
            followup_application=_UnusedPort(),  # type: ignore[arg-type]
            application_build_id="agent-session-controlled-admission",
            commit_sha=RELEASE_SHA,
            legacy_fixture_input_allowed=True,
        ).start(
            StartBookProductionCommand(
                project_id=pack_harness.project_id,
                workspace_id=pack_harness.workspace_id,
                book_id=pack_harness.book_ids[0],
                actor_id=actor_id,
                trace_id=identifier("agent-controlled-book-trace"),
                correlation_id=identifier("agent-controlled-book-correlation"),
                stable_idempotency_key=f"{pack_harness.project_id}:book",
                book_design_version=versions.pop("book_design_version"),
                book_plan_version=versions.pop("book_plan_version"),
                production_profile_version="production-profile:v1",
                longform_context_versions=versions,
                target_chapter_count=1,
                input_mode="LEGACY_FIXTURE_INPUT_MODE",
            ),
            principal=principal,
        )
        route_artifact = next(
            item
            for item in pack.compiled["resolved_artifacts"]
            if item["ref"] == "chapter.agent_session.route:v1"
        )
        runtime_binding = {
            "contract_version": "agent-route-execution-identity.v1",
            "stage": "agent_session",
            "provider": "controlled-provider",
            "model_id": "controlled-agent-model",
            "reasoning_effort": "medium",
            "model_profile_id": "chapter.agent_session.default",
            "model_profile_version": 1,
            "model_profile_hash": "sha256:" + "1" * 64,
            "route_policy_id": "chapter.agent_session.route",
            "route_policy_version": 1,
            "route_policy_ref": "chapter.agent_session.route:v1",
            "route_policy_hash": route_artifact["content_hash"],
            "fallback_policy_id": "chapter.agent_session.fail-closed",
            "fallback_policy_version": 1,
            "fallback_policy_hash": "sha256:" + "2" * 64,
            "backend_id": "remote-provider-controlled",
            "backend_version": "v1",
            "runtime_class": "REMOTE_PROVIDER_API",
            "runtime_host_id": "controlled-provider-runtime",
            "auth_profile_ref": "secret-profile:agent-provider",
            "prompt_version": "v1",
            "skill_version": "v1",
            "system_instruction_hash": pack.prompt_hash,
            "template_hash": next(
                item["content_hash"]
                for item in pack.compiled["resolved_artifacts"]
                if item["kind"] == "PROMPT_TEMPLATE"
            ),
            "skill_content_hash": pack.skill_hash,
            "prompt_compiler_version": "agent-session-prompt-compiler:v1",
            "output_schema_ref": "schema:execution-output:agent-workspace-execute:v1",
            "release_sha": RELEASE_SHA,
            "capability_pack_id": pack_harness.pack_id,
            "gateway": "PRODUCTION_EXECUTION_GATEWAY",
        }
        runtime_binding["runtime_binding_hash"] = canonical_policy_hash(runtime_binding)
        application = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id="agent-session-controlled-admission",
            commit_sha=RELEASE_SHA,
            runtime_environment="validation",
            production_agent_model_binding=runtime_binding,
        )
        agent_ref = str(pack.compiled["workflow_nodes"][0]["agent_definition_ref"])
        agent_id = agent_ref.rpartition("@")[0]
        tool_names = (
            "narrative.query_accepted",
            "story_planning.generate_candidate",
            "plan_change.submit",
        )
        admitted = application.admit_harness_session(
            AgentHarnessAdmissionRequest(
                project_id=pack_harness.project_id,
                workspace_id=pack_harness.workspace_id,
                book_id=pack_harness.book_ids[0],
                actor_id=actor_id,
                agent_session_id=identifier("controlled-agent-session"),
                agent_role=AutonomousAgentRole.STUDIO_DIRECTOR,
                instruction="Query accepted narrative evidence before proposing.",
                accepted_boundary=AcceptedBoundaryRef(
                    book_id=pack_harness.book_ids[0],
                    book_run_id=book.book_run_id,
                    accepted_through_chapter=0,
                    acceptance_id="",
                    projection_set_id="",
                ),
                tool_policy=tuple(
                    SERVER_AGENT_TOOL_CATALOG[name] for name in tool_names
                ),
                skill_bindings=(),
                budget=AgentHarnessBudget(
                    max_turns=3,
                    max_tool_calls=3,
                    max_external_effects=4,
                    max_input_tokens=1000,
                    max_output_tokens=1000,
                    max_cost_amount="1",
                ),
                idempotency_key=f"{pack_harness.project_id}:controlled-session",
                trace_id=identifier("controlled-agent-trace"),
                correlation_id=identifier("controlled-agent-correlation"),
                agent_id=agent_id,
            ),
            principal=principal,
        )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            session = uow.repositories.agent_runtime.require_harness_session(
                str(admitted["agent_session_id"])
            )
            operation = uow.repositories.attempt_runtime.operation_state(
                str(admitted["operation_id"]), pack_harness.project_id
            )
        contract = dict(session.execution_contract)
        self.assertEqual(
            session.execution_contract_hash,
            admitted["execution_contract_hash"],
        )
        self.assertEqual(contract["runtime_binding"], runtime_binding)
        self.assertEqual(
            contract["capability_pack_execution_snapshot"]["binding_set_hash"],
            deployment.binding_set_hash,
        )
        self.assertEqual(contract["release_sha"], RELEASE_SHA)
        self.assertEqual(contract["authority_policy"], "SUBMIT_ONLY_NO_DIRECT_MUTATION")
        self.assertEqual(operation["status"], "READY")

    def test_pep_gateway_receipt_recovers_before_transcript_without_duplicate_model_effect(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = IndustrialSettings(
                root=Path(directory), database_url=DATABASE_URL
            )
            execution = build_production_execution_composition(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "test",
                    "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                    "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                    "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                    "NOVEL_FORGE_AGENT_PROVIDER": "mock",
                    "NOVEL_FORGE_AGENT_MODEL": "fixture-agent-model",
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "objects",
                },
            )
            runtime_binding = agent_route_execution_identity(
                execution.gateway.routes["agent_session"],
                capability_pack_id="agent_session_pack",
            )
            project_id, session_id, operation_id, worker_id = self._admit_fixture(
                execution_contract={
                    "contract_version": "agent-session-execution-contract.v1",
                    "runtime_binding": runtime_binding,
                    "release_sha": RELEASE_SHA,
                }
            )
            binder = PostgresAgentExecutionContractBinder(
                DATABASE_URL,
                execution.gateway.routes,
                capability_pack_id="agent_session_pack",
                pack_environment="test",
                pack_runtime_profile="test",
                pack_release_channel="VALIDATION",
                pack_required=False,
            )

            def crash_after_provider(point: str) -> None:
                if point == "after_provider_success":
                    raise _SimulatedProcessCrash(point)

            first_factory = build_production_agent_harness_factory(
                DATABASE_URL,
                adapter=execution.gateway,
                capability_binder=binder,
                planning=_UnusedPort(),  # type: ignore[arg-type]
                plan_change=_UnusedPort(),  # type: ignore[arg-type]
                principal=Principal(
                    principal_id="pep-agent-worker",
                    principal_type=PrincipalType.SERVICE,
                    permissions=frozenset(),
                    project_scope=frozenset({project_id}),
                    authentication_source="integration-fixture",
                ),
                worker_id=worker_id,
                model_fault_injector=crash_after_provider,
            )
            with self.assertRaises(_SimulatedProcessCrash):
                AgentAuthorityScheduler(
                    DATABASE_URL,
                    execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
                    worker_id=worker_id,
                    harness_factory=first_factory,
                    lease_seconds=1,
                ).tick(project_id=project_id, agent_run_id=operation_id)

            with connect() as connection:
                before = connection.execute(
                    """
                    SELECT effect.external_effect_id, effect.status,
                           effect.provider, effect.capability,
                           attempt.attempt_id
                    FROM authority_external_effect AS effect
                    JOIN authority_attempt AS attempt
                      ON attempt.operation_id=effect.operation_id
                    WHERE effect.operation_id=%s
                      AND effect.effect_type='model.invoke'
                    ORDER BY effect.created_at
                    """,
                    [operation_id],
                ).fetchall()
                self.assertEqual(len(before), 1)
                self.assertEqual(
                    tuple(before[0][1:4]),
                    (
                        "SUCCEEDED",
                        "production_execution_gateway",
                        "model.agent_session",
                    ),
                )
                connection.execute(
                    """
                    UPDATE authority_lease_acquisition
                    SET expires_at=acquired_at + INTERVAL '1 millisecond'
                    WHERE attempt_id=%s AND status='HELD'
                    """,
                    [before[0][4]],
                )
                connection.commit()

            recovered_worker = f"{worker_id}:recovered"
            recovered_factory = build_production_agent_harness_factory(
                DATABASE_URL,
                adapter=execution.gateway,
                capability_binder=binder,
                planning=_UnusedPort(),  # type: ignore[arg-type]
                plan_change=_UnusedPort(),  # type: ignore[arg-type]
                principal=Principal(
                    principal_id="pep-agent-worker",
                    principal_type=PrincipalType.SERVICE,
                    permissions=frozenset(),
                    project_scope=frozenset({project_id}),
                    authentication_source="integration-fixture",
                ),
                worker_id=recovered_worker,
            )
            recovered = AgentAuthorityScheduler(
                DATABASE_URL,
                execution_preparer=_UnusedPort(),  # type: ignore[arg-type]
                worker_id=recovered_worker,
                harness_factory=recovered_factory,
                lease_seconds=1,
            ).tick(project_id=project_id, agent_run_id=operation_id)
            self.assertEqual(recovered.operation_status, "SUCCEEDED")

            with connect() as connection:
                effects = connection.execute(
                    """
                    SELECT effect.request_payload,
                           receipt.payload->'evidence'
                    FROM authority_external_effect AS effect
                    JOIN LATERAL (
                      SELECT external_receipt.payload
                      FROM authority_external_effect_dispatch AS dispatch
                      JOIN authority_external_receipt AS external_receipt
                        ON external_receipt.dispatch_id=dispatch.dispatch_id
                      WHERE dispatch.external_effect_id=effect.external_effect_id
                      ORDER BY external_receipt.received_at DESC LIMIT 1
                    ) AS receipt ON TRUE
                    WHERE effect.operation_id=%s
                      AND effect.effect_type='model.invoke'
                    ORDER BY effect.created_at
                    """,
                    [operation_id],
                ).fetchall()
                transcript_count = connection.execute(
                    """
                    SELECT COUNT(*) FROM authority_agent_transcript_event
                    WHERE agent_session_id=%s
                    """,
                    [session_id],
                ).fetchone()[0]
                first_dispatch_count = connection.execute(
                    """
                    SELECT COUNT(*) FROM authority_external_effect_dispatch
                    WHERE external_effect_id=%s
                    """,
                    [before[0][0]],
                ).fetchone()[0]
            self.assertEqual(len(effects), 2)
            self.assertEqual(
                str(
                    effects[0][1]["production_execution"]["execution_request"][
                        "capability"
                    ]
                ),
                "agent.workspace.execute",
            )
            self.assertEqual(
                effects[0][0]["_production_execution"]["agent_execution_contract_hash"],
                canonical_policy_hash(
                    {
                        "contract_version": "agent-session-execution-contract.v1",
                        "runtime_binding": runtime_binding,
                        "release_sha": RELEASE_SHA,
                    }
                ),
            )
            self.assertEqual(int(first_dispatch_count), 1)
            self.assertEqual(int(transcript_count), 8)


if __name__ == "__main__":
    unittest.main()
