from __future__ import annotations

from dataclasses import replace
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
from novel_forge.modules.agent_runtime.scheduler import AgentAuthorityScheduler
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.production import (
    PostgresBookAuthority,
    StartBookProductionCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    connect,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration import (
    test_book_to_chapter_authority_vertical_postgres as book_fixtures,
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

    def _admit_fixture(self) -> tuple[str, str, str, str]:
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


if __name__ == "__main__":
    unittest.main()
