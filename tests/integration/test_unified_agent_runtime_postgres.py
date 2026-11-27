from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    connect,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration import (
    test_chapter_authority_scheduler_postgres as chapter_scheduler_fixtures,
)


RELEASE_SHA = "a" * 40
class UnifiedAgentRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_runtime_projection_reuses_kernel_attempt_and_lease_tables(self) -> None:
        with connect() as connection:
            tables = connection.execute(
                """
                SELECT
                    to_regclass('authority_agent_definition_activation'),
                    to_regclass('authority_chapter_node_agent_binding'),
                    to_regclass('authority_agent_runtime_binding'),
                    to_regclass('authority_attempt'),
                    to_regclass('authority_lease_acquisition'),
                    to_regclass('authority_agent_attempt'),
                    to_regclass('authority_agent_lease')
                """
            ).fetchone()

        self.assertEqual(
            tuple("" if value is None else str(value) for value in tables),
            (
                "authority_agent_definition_activation",
                "authority_chapter_node_agent_binding",
                "authority_agent_runtime_binding",
                "authority_attempt",
                "authority_lease_acquisition",
                "",
                "",
            ),
        )

    def test_runtime_binding_has_no_duplicate_status_column(self) -> None:
        with connect() as connection:
            columns = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='authority_agent_runtime_binding'
                    """
                ).fetchall()
            }

        self.assertIn("operation_id", columns)
        self.assertIn("attempt_id", columns)
        self.assertIn("fencing_token", columns)
        self.assertNotIn("run_status", columns)
        self.assertNotIn("attempt_status", columns)

    def test_draft_is_a_typed_capability_not_an_autonomous_agent(self) -> None:
        project_id = identifier("unified-capability-draft")
        workspace_id = f"workspace:{project_id}"
        actor = "unified-capability-operator"
        worker = "unified-capability-worker"
        with tempfile.TemporaryDirectory(
            prefix="novel-forge-capability-"
        ) as object_root:
            settings = IndustrialSettings(
                root=Path.cwd(), environment="test", database_url=DATABASE_URL
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": object_root,
            }
            execution = build_production_execution_composition(settings, env=env)
            chapter = build_chapter_authority_application(
                settings, execution=execution, env=env
            )
            principal = Principal(
                principal_id=actor,
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"chapter.authority.execute"}),
                project_scope=frozenset({project_id}),
                authentication_source="integration-fixture",
            )
            request = SingleChapterRequest(
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=actor,
                chapter=1,
                title="One Fenced Draft",
                premise="A promise creates a visible irreversible cost.",
                trace_id=identifier("capability-draft-trace"),
                correlation_id=identifier("capability-draft-correlation"),
                application_build_id="unified-capability-integration",
                commit_sha=RELEASE_SHA,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(
                    chapter_scheduler_fixtures.ChapterAuthoritySchedulerPostgresTests._release_evidence(
                        project_id
                    )
                ),
            )
            seed_authority_project_book(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=f"book:{project_id}",
            )
            admission = chapter.admit(request, principal=principal)
            scheduler = chapter.scheduler(
                principal=Principal(
                    principal_id=worker,
                    principal_type=PrincipalType.WORKER,
                    permissions=frozenset({"chapter.authority.execute"}),
                    project_scope=frozenset({project_id}),
                    authentication_source="integration-fixture",
                )
            )
            observed = []
            for expected in (
                "plan",
                "execution_intent",
                "memo",
                "retrieval",
                "context",
                "draft",
            ):
                tick = scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                )
                observed.append(tick.node)
                self.assertEqual(tick.node, expected)
            self.assertEqual(observed[-1], "draft")

        with connect() as connection:
            row = connection.execute(
                """
                SELECT operation.operation_id,
                       COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT binding.binding_id),
                       COUNT(DISTINCT candidate.candidate_version_id),
                       COUNT(DISTINCT output.asset_version_id),
                       MAX(version.lifecycle),
                       MAX(version.schema_version)
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                LEFT JOIN authority_agent_runtime_binding AS binding
                  ON binding.operation_id=operation.operation_id
                LEFT JOIN authority_agent_work_order AS work_order
                  ON work_order.work_order_id=binding.work_order_id
                LEFT JOIN authority_agent_candidate_version AS candidate
                  ON candidate.originating_turn_id=work_order.turn_id
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                 AND output.role='primary'
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE operation.project_id=%s
                  AND operation.definition_name='chapter.draft.generate'
                GROUP BY operation.operation_id
                """,
                [project_id],
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(tuple(row[1:5]), (1, 0, 0, 1))
        self.assertIn(str(row[5]), {"CANDIDATE", "ACTIVE"})
        self.assertEqual(str(row[6]), "draft-chapter.v1")


if __name__ == "__main__":
    unittest.main()
