from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import unittest

from novel_forge.api.authority_dependencies import build_chapter_authority_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_import import (
    GitRepositoryExternalEffectAdapter,
    LocalObjectStoreReader,
    PostgresContentIntelligenceExecutionPort,
    SourceImportApplication,
    SourceImportPolicy,
    SourceImportScheduler,
)
from novel_forge.modules.source_import.application import CreateSourceImportCommand
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class SourceContentRoutingPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("source-profile-project")
        self.workspace_id = identifier("source-profile-workspace")
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-profile-integration",
            commit_sha="f" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id="source-profile-operator",
                idempotency_key=f"project:{self.project_id}",
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                payload={"title": "Heterogeneous Source Routing"},
            )
        )
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "mixed-corpus"
        self.object_root = self.root / "objects"
        (self.repository / "经典文学").mkdir(parents=True)
        (self.repository / "经济学").mkdir(parents=True)
        (self.repository / "经典文学" / "长篇小说.txt").write_text(
            "第一章\n他说：“你终于来了。”她说：“我一直在等。”\n"
            "突然有人走进房间，他看着窗外，后来又问道。\n"
            "第二章\n“为什么？”“因为必须如此。”此时她心想。\n"
            "第三章\n“走吧。”“现在？”“现在。”他说完便离开。\n",
            encoding="utf-8",
        )
        (self.repository / "经济学" / "宏观经济学.txt").write_text(
            "第一章 理论与定义\n"
            "本章定义总需求模型，并说明研究假设、数据、方法和结论。\n"
            "第二章 机制与约束\n讨论模型适用范围、证据、案例与约束。\n",
            encoding="utf-8",
        )
        self._git("init", "-b", "main")
        self._git("config", "user.email", "fixture@example.invalid")
        self._git("config", "user.name", "Source Profile Fixture")
        self._git("add", ".")
        self._git("commit", "-m", "mixed corpus")
        self.commit_sha = self._git("rev-parse", "HEAD").strip()

        git_adapter = GitRepositoryExternalEffectAdapter(
            self.root / "git-cache",
            allow_file_repositories=True,
            allowed_file_roots=(self.root,),
        )
        chapter = build_chapter_authority_application(
            IndustrialSettings(root=self.root, database_url=DATABASE_URL),
            env={
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(self.object_root),
                "NOVEL_FORGE_COMMIT_SHA": "f" * 40,
            },
        )
        execution_port = PostgresContentIntelligenceExecutionPort(
            DATABASE_URL,
            transport=chapter.model_port.adapter,
            worker_id="source-profile-worker",
            lease_seconds=30,
        )
        self.application = SourceImportApplication(
            DATABASE_URL,
            application_build_id="source-profile-integration",
            commit_sha="f" * 40,
            worker_id="source-profile-worker",
            git_adapter=git_adapter,
            object_store_adapter=chapter.object_store_adapter,
            object_store_reader=LocalObjectStoreReader(self.object_root),
            execution_port=execution_port,
            allow_fixture_intelligence=True,
            allow_file_repositories=True,
        )
        self.scheduler = SourceImportScheduler(
            self.application,
            worker_id="source-profile-worker",
            lease_seconds=30,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_auto_routes_mixed_corpus_and_freezes_profile_evidence(self) -> None:
        admitted = self._create_import("auto", "auto")
        self.scheduler.run_or_recover(
            operation_id=admitted["operation_id"], project_id=self.project_id
        )
        self._run_ready_operations()

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT result->'source_profile'->>'selected_analysis_profile',
                       result->>'source_profile_asset_version_id'
                FROM authority_source_import_work
                WHERE project_id=%s AND import_job_id=%s AND work_kind='FILE'
                ORDER BY source_path
                """,
                [self.project_id, admitted["import_job_id"]],
            )
            file_profiles = cursor.fetchall()
            self.assertEqual(
                {row[0] for row in file_profiles},
                {"classic_literature", "professional_knowledge"},
            )
            self.assertTrue(all(row[1] for row in file_profiles))

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version
                  ON version.asset_id=asset.asset_id
                WHERE asset.project_id=%s
                  AND asset.asset_type='source_content_profile'
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='INELIGIBLE'
                """,
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 2)

            cursor.execute(
                """
                SELECT operation.command_payload->'payload'
                         ->>'resolved_analysis_profile',
                       COUNT(*)
                FROM authority_operation AS operation
                JOIN LATERAL jsonb_array_elements(operation.input_asset_snapshot) input
                  ON TRUE
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=input->>'asset_version_id'
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE operation.project_id=%s
                  AND operation.definition_name='source.import.deconstruction.execute'
                  AND asset.asset_type='source_content_profile'
                GROUP BY 1
                """,
                [self.project_id],
            )
            routed = dict(cursor.fetchall())
            self.assertGreater(routed.get("classic_literature", 0), 0)
            self.assertGreater(routed.get("professional_knowledge", 0), 0)

            self._assert_profiled_analyzers(cursor)
            cursor.execute(
                "SELECT COUNT(*) FROM authority_mkaos_knowledge_candidate WHERE project_id=%s",
                [self.project_id],
            )
            self.assertGreater(cursor.fetchone()[0], 0)

    def test_new_auto_policy_reuses_existing_source_and_only_reanalyzes(self) -> None:
        legacy = self._create_import("writing_theory", "legacy")
        self.scheduler.run_or_recover(
            operation_id=legacy["operation_id"], project_id=self.project_id
        )
        self._run_ready_operations()
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_document WHERE project_id=%s",
                [self.project_id],
            )
            source_count = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_transform WHERE project_id=%s",
                [self.project_id],
            )
            transform_count = int(cursor.fetchone()[0])

        routed = self._create_import("auto", "auto-after-legacy")
        self.scheduler.run_or_recover(
            operation_id=routed["operation_id"], project_id=self.project_id
        )
        self._run_ready_operations()

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_document WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], source_count)
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_transform WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], transform_count)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_source_import_work
                WHERE project_id=%s AND import_job_id=%s AND work_kind='FILE'
                  AND result->>'reused_source_transform'='true'
                  AND COALESCE((result->>'provider_tokens')::int, -1)=0
                """,
                [self.project_id, routed["import_job_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], transform_count)
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_source_import_work
                WHERE project_id=%s AND import_job_id=%s AND work_kind='FILE'
                  AND result ? 'source_profile_asset_version_id'
                """,
                [self.project_id, routed["import_job_id"]],
            )
            self.assertEqual(cursor.fetchone()[0], transform_count)
            self._assert_profiled_analyzers(cursor)

    def _create_import(self, profile_id: str, suffix: str) -> dict[str, Any]:
        policy = SourceImportPolicy(analysis_profile=profile_id)
        return self.application.create_import(
            CreateSourceImportCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                source_type="github_repository",
                repository_url=self.repository.as_uri(),
                requested_ref=self.commit_sha,
                policy=policy,
                analysis_profile=profile_id,
                mode="IMPORT",
                rights_authorization="licensed",
                license_name="fixture-license",
                copyright_boundary="analysis and abstraction only",
                actor_id="source-profile-operator",
                idempotency_key=f"{suffix}:{self.project_id}",
                trace_id=f"trace:{suffix}:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
            )
        )

    def _assert_profiled_analyzers(self, cursor: Any) -> None:
        cursor.execute(
            """
            SELECT observation.analyzer_id
            FROM authority_source_deconstruction_observation AS observation
            WHERE observation.project_id=%s
            ORDER BY observation.analyzer_id
            """,
            [self.project_id],
        )
        analyzers = {str(row[0]) for row in cursor.fetchall()}
        self.assertTrue(
            any(value.startswith("novel-forge.classic_literature.") for value in analyzers)
        )
        self.assertTrue(
            any(value.startswith("novel-forge.professional_knowledge.") for value in analyzers)
        )

    def _run_ready_operations(self) -> None:
        for _ in range(120):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT operation_id
                    FROM authority_operation
                    WHERE project_id=%s AND status='READY'
                      AND definition_name LIKE 'source.import.%%'
                    ORDER BY created_at, operation_id
                    """,
                    [self.project_id],
                )
                ready = [str(row[0]) for row in cursor.fetchall()]
            if not ready:
                return
            for operation_id in ready:
                self.scheduler.run_or_recover(
                    operation_id=operation_id, project_id=self.project_id
                )
        raise AssertionError("heterogeneous Source routing did not settle")

    def _git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=self.repository,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout


if __name__ == "__main__":
    unittest.main()
