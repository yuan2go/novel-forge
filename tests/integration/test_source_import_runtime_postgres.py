from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from novel_forge.api.authority_app import create_authority_app
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority import (
    ApproveKnowledgeCandidateCommand,
    BuildKnowledgePackCommand,
    KnowledgePackSelection,
    MkaosAuthorityApplication,
    MkaosAuthorityQuery,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.source_import import (
    ApplyReprocessingPlanCommand,
    CreateSourceImportCommand,
    GitRepositoryExternalEffectAdapter,
    LocalObjectStoreReader,
    PostgresContentIntelligenceExecutionPort,
    SourceImportApplication,
    SourceImportPolicy,
    SourceImportQuery,
    SourceImportScheduler,
)
from novel_forge.modules.source_authority import (
    PlanSourceReprocessingCommand,
    ReprocessingTarget,
    SourceAuthorityQuery,
)
from novel_forge.modules.source_authority.deconstruction import (
    AnalyzerContract,
    ObservationScope,
)
from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class _RetryOnceGitAdapter:
    def __init__(self, delegate: GitRepositoryExternalEffectAdapter) -> None:
        self.delegate = delegate
        self.provider = delegate.provider
        self.reconciliation_mode = delegate.reconciliation_mode
        self.capability_profile = delegate.capability_profile
        self.execute_count = 0

    def execute(self, **kwargs: object) -> ProviderResult:
        self.execute_count += 1
        if self.execute_count == 1:
            return ProviderResult(
                "retryable_failure",
                "git:injected-retry",
                {"injected_failure": True},
            )
        return self.delegate.execute(**kwargs)  # type: ignore[arg-type]

    def query(self, **kwargs: object) -> ProviderResult:
        return self.delegate.query(**kwargs)  # type: ignore[arg-type]

    def cancel(self, **kwargs: object) -> ProviderResult:
        return self.delegate.cancel(**kwargs)  # type: ignore[arg-type]

    def read_blob(self, repository_identity: str, object_id: str) -> bytes:
        return self.delegate.read_blob(repository_identity, object_id)


class SourceImportRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("source-import-project")
        self.workspace_id = identifier("source-import-workspace")
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-import-integration",
            commit_sha="e" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id="source-import-operator",
                idempotency_key=f"project:{self.project_id}",
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                payload={"title": "Source Import Runtime"},
            )
        )
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "fixture-repository"
        self.object_root = self.root / "objects"
        self.repository.mkdir(exist_ok=True)
        self._git("init", "-b", "main", cwd=self.repository)
        self._git("config", "user.email", "fixture@example.invalid")
        self._git("config", "user.name", "Source Import Fixture")
        (self.repository / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.repository / "theory.md").write_text(
            "# Hook\nA question creates forward pressure.\n", encoding="utf-8"
        )
        (self.repository / "duplicate.md").write_text(
            "# Hook\nA question creates forward pressure.\n", encoding="utf-8"
        )
        (self.repository / "binary.bin").write_bytes(b"\x00fixture")
        self._git("add", ".")
        self._git("commit", "-m", "initial fixture")
        self.commit_a = self._git("rev-parse", "HEAD").strip()
        git_adapter = GitRepositoryExternalEffectAdapter(
            self.root / "git-cache",
            allow_file_repositories=True,
            allowed_file_roots=(self.root,),
        )
        self.git_adapter = git_adapter
        self.chapter_application = build_chapter_authority_application(
            IndustrialSettings(root=self.root, database_url=DATABASE_URL),
            env={
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
                "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
                "NOVEL_FORGE_REVISION_PROVIDER": "mock",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(self.object_root),
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            },
        )
        execution_port = PostgresContentIntelligenceExecutionPort(
            DATABASE_URL,
            transport=self.chapter_application.model_port.adapter,
            worker_id="source-import-integration-worker",
            lease_seconds=30,
        )
        self.execution_port = execution_port
        self.application = SourceImportApplication(
            DATABASE_URL,
            application_build_id="source-import-integration",
            commit_sha="e" * 40,
            worker_id="source-import-integration-worker",
            git_adapter=git_adapter,
            object_store_adapter=self.chapter_application.object_store_adapter,
            object_store_reader=LocalObjectStoreReader(self.object_root),
            execution_port=execution_port,
            allow_fixture_intelligence=True,
            allow_file_repositories=True,
        )
        self.scheduler = SourceImportScheduler(
            self.application,
            worker_id="source-import-integration-worker",
            lease_seconds=30,
        )
        self.query = SourceImportQuery(DATABASE_URL)
        self.mkaos_application = MkaosAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-import-integration",
            commit_sha="e" * 40,
            allow_fixture_activation=True,
        )
        self.mkaos_query = MkaosAuthorityQuery(DATABASE_URL)
        self.principal = Principal(
            principal_id="source-import-governance-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "mkaos.authority.execute",
                    "mkaos.authority.approve",
                    "mkaos.authority.query",
                }
            ),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_commit_import_deduplicates_content_and_reuses_transform(self) -> None:
        first = self._create_import("first", self.commit_a)
        self.scheduler.run_or_recover(
            operation_id=first["operation_id"], project_id=self.project_id
        )
        file_operations = self._operations("source.import.file.process")
        self.assertEqual(len(file_operations), 1)
        for operation_id in file_operations:
            self.scheduler.run_or_recover(
                operation_id=operation_id, project_id=self.project_id
            )
        for operation_id in self._operations(
            "source.import.deconstruction.execute"
        ):
            self.scheduler.run_or_recover(
                operation_id=operation_id, project_id=self.project_id
            )
        for operation_id in self._operations("source.import.mkaos.extract"):
            self.scheduler.run_or_recover(
                operation_id=operation_id, project_id=self.project_id
            )

        imported = self.query.import_job(
            project_id=self.project_id, import_job_id=first["import_job_id"]
        )
        preview = self.query.preview(
            project_id=self.project_id, import_job_id=first["import_job_id"]
        )
        self.assertEqual(preview["resolved_commit_sha"], self.commit_a)
        self.assertEqual(imported["counters"]["files_blocked"], 2)
        files = self.query.files(
            project_id=self.project_id, import_job_id=first["import_job_id"]
        )
        theory_files = [item for item in files if item["path"].endswith(".md")]
        self.assertEqual(len(theory_files), 2)
        self.assertEqual(
            len({item["source_document_id"] for item in theory_files}), 1
        )
        self.assertEqual(
            len({item["source_transform_id"] for item in theory_files}), 1
        )
        downstream = self.query.downstream_status(
            project_id=self.project_id, import_job_id=first["import_job_id"]
        )
        self.assertEqual(downstream["observations"], 6)
        self.assertEqual(downstream["knowledge_candidates"], 6)

        candidate_id = self._candidate_for_dimension("pacing")
        candidate = next(
            item
            for item in self.mkaos_query.list_candidates(
                project_id=self.project_id
            )
            if item["asset_version_id"] == candidate_id
        )
        approval = self.mkaos_application.execute_approval(
            ApproveKnowledgeCandidateCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                candidate_asset_version_id=candidate["asset_version_id"],
                policy_version="source-import-governance:v1",
                rationale=(
                    "Fixture candidate is abstract, evidence-backed, and contains "
                    "no source expression."
                ),
                actor_id="untrusted-request-actor",
                idempotency_key=f"approve:{candidate['asset_version_id']}",
                trace_id=f"trace:approve:{candidate['asset_version_id']}",
                correlation_id=f"correlation:{self.project_id}",
            ),
            principal=self.principal,
        )
        pack = self.mkaos_application.execute_pack(
            BuildKnowledgePackCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                target_asset_version_id=imported[
                    "repository_snapshot_asset_version_id"
                ],
                selector_policy_version="source-import-selector:v1",
                selector_policy_hash=(
                    "sha256:"
                    + hashlib.sha256(b"source-import-selector:v1").hexdigest()
                ),
                selections=(
                    KnowledgePackSelection(
                        knowledge_card_asset_version_id=approval[
                            "asset_version_id"
                        ],
                        usage_role="constraint",
                        frozen_weight=Decimal("1"),
                    ),
                ),
                actor_id="untrusted-request-actor",
                idempotency_key=f"pack:{first['import_job_id']}",
                trace_id=f"trace:pack:{first['import_job_id']}",
                correlation_id=f"correlation:{self.project_id}",
            ),
            principal=self.principal,
        )
        governed = self.query.downstream_status(
            project_id=self.project_id, import_job_id=first["import_job_id"]
        )
        self.assertEqual(governed["knowledge_cards"], 1)
        self.assertEqual(governed["knowledge_packs"], 1)
        pack_projection = self.mkaos_query.require_pack(
            project_id=self.project_id,
            knowledge_pack_id=pack["knowledge_pack_id"],
        )
        self.assertEqual(pack_projection["item_count"], 1)
        serialized_pack = json.dumps(
            pack_projection, ensure_ascii=False, sort_keys=True, default=str
        )
        self.assertNotIn("A question and deadline create forward pressure", serialized_pack)
        self.assertNotIn("source_segments", serialized_pack)

        second = self._create_import("second", self.commit_a)
        self.scheduler.run_or_recover(
            operation_id=second["operation_id"], project_id=self.project_id
        )
        replay = self.query.import_job(
            project_id=self.project_id, import_job_id=second["import_job_id"]
        )
        self.assertEqual(replay["effective_status"], "IMPORTED")
        self.assertTrue(replay["counters"]["snapshot_reused"])
        self.assertEqual(replay["counters"]["files_to_fetch"], 0)
        self.assertEqual(len(self._operations("source.import.file.process")), 1)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_document WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_transform WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)

        rights_review = self._create_import(
            "rights-review",
            self.commit_a,
            mode="PREVIEW",
            rights_authorization="unknown",
            license_name="",
            copyright_boundary="",
        )
        self.scheduler.run_or_recover(
            operation_id=rights_review["operation_id"], project_id=self.project_id
        )
        rights_preview = self.query.import_job(
            project_id=self.project_id,
            import_job_id=rights_review["import_job_id"],
        )
        self.assertNotEqual(
            rights_preview["repository_snapshot_asset_version_id"],
            imported["repository_snapshot_asset_version_id"],
        )
        self.assertEqual(
            self.query.preview(
                project_id=self.project_id,
                import_job_id=rights_review["import_job_id"],
            )["manifest_hash"],
            preview["manifest_hash"],
        )
        self.assertEqual(rights_preview["counters"]["files_eligible"], 0)
        self.assertEqual(len(self._operations("source.import.file.process")), 1)

        pacing_scope, pacing_analyzer, transform_id = self._observation_contract(
            "pacing"
        )
        structure_scope, structure_analyzer, _ = self._observation_contract(
            "structure"
        )
        source_count_before = len(
            self._operations("source.import.file.process")
        )
        pacing_versions_before = self._dimension_asset_versions("pacing")
        structure_versions_before = self._dimension_asset_versions("structure")
        plan = self.application.source_authority.execute_reprocessing_plan(
            PlanSourceReprocessingCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                targets=(
                    ReprocessingTarget(
                        scope=pacing_scope,
                        analyzer=replace(
                            pacing_analyzer,
                            analyzer_version="2.0",
                            prompt_version="2.0",
                        ),
                    ),
                    ReprocessingTarget(
                        scope=structure_scope,
                        analyzer=structure_analyzer,
                    ),
                ),
                cause_type="ANALYZER_UPGRADE",
                source_transform_id=transform_id,
                actor_id="source-import-operator",
                idempotency_key=f"upgrade:pacing:{first['import_job_id']}",
                trace_id=f"trace:upgrade:{first['import_job_id']}",
                correlation_id=f"correlation:{self.project_id}",
            )
        )
        planned_actions = {
            (item["dimension"], item["action"]) for item in plan["items"]
        }
        self.assertIn(("pacing", "RECOMPUTE"), planned_actions)
        self.assertIn(("structure", "REUSE"), planned_actions)
        apply = self.application.apply_reprocessing_plan(
            ApplyReprocessingPlanCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                reprocessing_plan_asset_version_id=plan["asset_version_id"],
                actor_id="source-import-operator",
                idempotency_key=f"apply:{plan['asset_version_id']}",
                trace_id=f"trace:apply:{plan['asset_version_id']}",
                correlation_id=f"correlation:{self.project_id}",
            )
        )
        self.scheduler.run_or_recover(
            operation_id=apply["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        applied_plan = self.query.reprocessing_plan(
            project_id=self.project_id,
            plan_asset_version_id=plan["asset_version_id"],
        )
        statuses = {(item["action"], item["status"]) for item in applied_plan["items"]}
        self.assertIn(("RECOMPUTE", "APPLIED"), statuses)
        self.assertIn(("REUSE", "REUSED"), statuses)
        self.assertIn(("REABSTRACT", "APPLIED"), statuses)
        self.assertIn(("REGOVERN", "BLOCKED"), statuses)
        self.assertEqual(applied_plan["status"], "BLOCKED")
        invalidations = SourceAuthorityQuery(DATABASE_URL).list_invalidations(
            project_id=self.project_id,
            status="OPEN",
            dimension="pacing",
        )
        self.assertTrue(invalidations)
        self.assertTrue(
            all(item["dimension"] == "pacing" for item in invalidations)
        )
        self.assertEqual(
            self._dimension_asset_versions("structure"), structure_versions_before
        )
        self.assertEqual(
            len(self._dimension_asset_versions("pacing")),
            len(pacing_versions_before) + 1,
        )
        self.assertEqual(
            len(self._operations("source.import.file.process")), source_count_before
        )

        self._git("mv", "duplicate.md", "renamed.md")
        (self.repository / "theory.md").write_text(
            "# Hook\nA question and deadline create forward pressure.\n",
            encoding="utf-8",
        )
        (self.repository / "added.md").write_text(
            "# Conflict\nA forced choice exposes incompatible benefits.\n",
            encoding="utf-8",
        )
        (self.repository / "binary.bin").unlink()
        self._git("add", "-A")
        self._git("commit", "-m", "incremental fixture")
        commit_b = self._git("rev-parse", "HEAD").strip()
        file_ops_before_update = len(
            self._operations("source.import.file.process")
        )
        deconstruction_ops_before_update = len(
            self._operations("source.import.deconstruction.execute")
        )
        third = self._create_import("third", commit_b)
        self.scheduler.run_or_recover(
            operation_id=third["operation_id"], project_id=self.project_id
        )
        incremental = self.query.import_job(
            project_id=self.project_id, import_job_id=third["import_job_id"]
        )
        incremental_files = self.query.files(
            project_id=self.project_id, import_job_id=third["import_job_id"]
        )
        self.assertEqual(incremental["counters"]["files_to_fetch"], 2)
        self.assertEqual(
            next(
                item for item in incremental_files if item["path"] == "renamed.md"
            )["diff_state"],
            "RENAMED_SAME_CONTENT",
        )
        self.assertEqual(
            next(
                item for item in incremental_files if item["path"] == "renamed.md"
            )["status"],
            "REUSED",
        )
        self._run_ready_source_operations()
        self.assertEqual(
            len(self._operations("source.import.file.process")),
            file_ops_before_update + 2,
        )
        self.assertEqual(
            len(self._operations("source.import.deconstruction.execute")),
            deconstruction_ops_before_update + 12,
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_document WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 3)
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_transform WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 3)

        (self.repository / "retry.md").write_text(
            "# Recovery\nRetry must preserve the frozen repository identity.\n",
            encoding="utf-8",
        )
        self._git("add", "retry.md")
        self._git("commit", "-m", "provider retry fixture")
        commit_c = self._git("rev-parse", "HEAD").strip()
        retry_adapter = _RetryOnceGitAdapter(self.git_adapter)
        self.application.git_adapter = retry_adapter
        retry_import = self._create_import("retry", commit_c, mode="PREVIEW")
        duplicate_retry = self._create_import("retry", commit_c, mode="PREVIEW")
        self.assertEqual(
            duplicate_retry["operation_id"], retry_import["operation_id"]
        )
        with self.assertRaisesRegex(Exception, "SOURCE_IMPORT_EFFECT_FAILED"):
            self.scheduler.run_or_recover(
                operation_id=retry_import["operation_id"],
                project_id=self.project_id,
            )
        failed_retry = self.query.import_job(
            project_id=self.project_id,
            import_job_id=retry_import["import_job_id"],
        )
        self.assertEqual(failed_retry["status"], "FAILED_RETRYABLE")
        restarted_scheduler = SourceImportScheduler(
            self.application,
            worker_id="source-import-restarted-worker",
            lease_seconds=30,
        )
        restarted_scheduler.run_or_recover(
            operation_id=retry_import["operation_id"],
            project_id=self.project_id,
        )
        recovered_preview = self.query.import_job(
            project_id=self.project_id,
            import_job_id=retry_import["import_job_id"],
        )
        self.assertEqual(recovered_preview["status"], "PREVIEWED")
        self.assertEqual(retry_adapter.execute_count, 2)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT effect.external_effect_id),
                       COUNT(dispatch.dispatch_id)
                FROM authority_external_effect AS effect
                LEFT JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                WHERE effect.operation_id=%s
                  AND effect.capability='source.remote.fetch'
                """,
                [retry_import["operation_id"]],
            )
            effect_rows, effect_ids, dispatches = cursor.fetchone()
        self.assertEqual((effect_rows, effect_ids, dispatches), (2, 1, 2))

        self.application.git_adapter = self.git_adapter
        (self.repository / "crash.md").write_text(
            "# Checkpoint\nA durable Provider receipt must survive worker loss.\n",
            encoding="utf-8",
        )
        self._git("add", "crash.md")
        self._git("commit", "-m", "provider receipt recovery fixture")
        commit_d = self._git("rev-parse", "HEAD").strip()
        crash_import = self._create_import("crash", commit_d)
        self.scheduler.run_or_recover(
            operation_id=crash_import["operation_id"],
            project_id=self.project_id,
        )
        crash_file_operation = self._ready_operations(
            "source.import.file.process"
        )[0]
        self.scheduler.run_or_recover(
            operation_id=crash_file_operation,
            project_id=self.project_id,
        )
        crash_analysis_operation = self._ready_operations(
            "source.import.deconstruction.execute"
        )[0]
        original_execution_log = self.execution_port._execution_log
        crash_injected = False

        def fail_after_provider_receipt(**kwargs: object):
            nonlocal crash_injected
            if not crash_injected:
                crash_injected = True
                raise KernelError(
                    "MODEL_EFFECT_RETRYABLE_POST_RECEIPT",
                    "injected worker loss after durable Provider receipt",
                )
            return original_execution_log(**kwargs)  # type: ignore[arg-type]

        self.execution_port._execution_log = fail_after_provider_receipt  # type: ignore[method-assign]
        try:
            with self.assertRaisesRegex(
                KernelError, "MODEL_EFFECT_RETRYABLE_POST_RECEIPT"
            ):
                self.scheduler.run_or_recover(
                    operation_id=crash_analysis_operation,
                    project_id=self.project_id,
                )
        finally:
            self.execution_port._execution_log = original_execution_log  # type: ignore[method-assign]
        self.assertEqual(self._model_effect_count(crash_analysis_operation), 1)
        recovered_analysis = restarted_scheduler.run_or_recover(
            operation_id=crash_analysis_operation,
            project_id=self.project_id,
        )
        self.assertTrue(recovered_analysis["result"]["provider_execution_reused"])
        self.assertEqual(self._model_effect_count(crash_analysis_operation), 1)
        admission = SourceAuthorityQuery(DATABASE_URL).data_import_admission(
            project_id=self.project_id
        )
        admission_checks = {
            item["name"]: item["passed"] for item in admission["checks"]
        }
        self.assertEqual(
            (admission["capability_status"], admission["project_qualification"]),
            ("CAPABILITY_IMPLEMENTED", "PROJECT_NOT_QUALIFIED"),
        )
        self.assertTrue(admission_checks["repository_import_runtime"])
        self.assertTrue(admission_checks["incremental_repository_import"])
        self.assertTrue(admission_checks["reprocessing_execution"])
        self.assertTrue(admission_checks["failure_recovery"])
        self.assertFalse(admission_checks["token_cost_traceability"])
        self.assertFalse(admission["data_import_ready"])

    def test_import_work_rejects_cross_project_job_reference(self) -> None:
        current = self._create_import("scope-current", self.commit_a, mode="PREVIEW")
        other_project_id = identifier("source-import-other-project")
        other_workspace_id = identifier("source-import-other-workspace")
        ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="source-import-integration",
            commit_sha="e" * 40,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=other_project_id,
                workspace_id=other_workspace_id,
                actor_id="source-import-operator",
                idempotency_key=f"project:{other_project_id}",
                trace_id=f"trace:{other_project_id}",
                correlation_id=f"correlation:{other_project_id}",
                payload={"title": "Other Source Import Runtime"},
            )
        )
        policy = SourceImportPolicy(analysis_profile="writing_theory")
        other = self.application.create_import(
            CreateSourceImportCommand(
                project_id=other_project_id,
                workspace_id=other_workspace_id,
                source_type="github_repository",
                repository_url=self.repository.as_uri(),
                requested_ref=self.commit_a,
                policy=policy,
                analysis_profile=policy.analysis_profile,
                mode="PREVIEW",
                rights_authorization="licensed",
                license_name="MIT",
                copyright_boundary="analysis and abstraction only",
                actor_id="source-import-operator",
                idempotency_key=f"{other_project_id}:scope-other",
                trace_id=f"trace:{other_project_id}:scope-other",
                correlation_id=f"correlation:{other_project_id}",
            )
        )
        with self.assertRaisesRegex(psycopg.Error, "job scope mismatch"):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE authority_source_import_work
                    SET import_job_id=%s
                    WHERE project_id=%s AND import_job_id=%s
                    """,
                    [
                        other["import_job_id"],
                        self.project_id,
                        current["import_job_id"],
                    ],
                )

    def test_product_api_previews_repository_without_low_level_inputs(self) -> None:
        environment = {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "source-import-api-integration",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_MODEL_PROVIDER": "mock",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "local",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(self.object_root),
            "NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT": str(
                self.root / "api-git-cache"
            ),
            "NOVEL_FORGE_SOURCE_IMPORT_FILE_FIXTURE_ROOT": str(self.root),
            "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": self.project_id,
        }
        settings = IndustrialSettings(
            root=self.root,
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        with patch.dict(os.environ, environment, clear=False):
            app = create_authority_app(settings)
            with TestClient(app) as client:
                admitted = client.post(
                    "/product/source-imports/preview",
                    json={
                        "project_id": self.project_id,
                        "workspace_id": self.workspace_id,
                        "source": {
                            "type": "github_repository",
                            "repository": self.repository.as_uri(),
                            "ref": self.commit_a,
                        },
                        "policy": {"analysis_profile": "writing_theory"},
                        "rights_authorization": "licensed",
                        "license_name": "MIT",
                        "copyright_boundary": "analysis and abstraction only",
                        "idempotency_key": f"api-preview:{self.project_id}",
                    },
                )
                self.assertEqual(admitted.status_code, 202, admitted.text)
                payload = admitted.json()
                self.scheduler.run_or_recover(
                    operation_id=payload["operation_id"],
                    project_id=self.project_id,
                )
                status = client.get(
                    f"/product/source-imports/{payload['import_job_id']}",
                    params={"project_id": self.project_id},
                )
                files = client.get(
                    f"/product/source-imports/{payload['import_job_id']}/files",
                    params={"project_id": self.project_id},
                )
                imported = client.post(
                    "/product/source-imports",
                    json={
                        "project_id": self.project_id,
                        "workspace_id": self.workspace_id,
                        "source": {
                            "type": "github_repository",
                            "repository": self.repository.as_uri(),
                            "ref": self.commit_a,
                        },
                        "policy": {"analysis_profile": "writing_theory"},
                        "rights_authorization": "licensed",
                        "license_name": "MIT",
                        "copyright_boundary": "analysis and abstraction only",
                        "idempotency_key": f"api-import:{self.project_id}",
                    },
                )
                self.assertEqual(imported.status_code, 202, imported.text)
                import_payload = imported.json()
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["status"], "PREVIEWED")
        self.assertTrue(status.json()["repository_snapshot_asset_version_id"])
        self.assertEqual(
            self.query.preview(
                project_id=self.project_id,
                import_job_id=payload["import_job_id"],
            )["resolved_commit_sha"],
            self.commit_a,
        )
        self.assertEqual(files.status_code, 200, files.text)
        self.assertTrue(any(item["path"].endswith(".md") for item in files.json()))
        self.assertEqual(self._operations("source.import.file.process"), [])
        self.scheduler.run_or_recover(
            operation_id=import_payload["operation_id"],
            project_id=self.project_id,
        )
        imported_job = self.query.import_job(
            project_id=self.project_id,
            import_job_id=import_payload["import_job_id"],
        )
        self.assertTrue(imported_job["counters"]["snapshot_reused"])
        self.assertEqual(imported_job["counters"]["files_to_fetch"], 1)
        self.assertEqual(len(self._operations("source.import.file.process")), 1)

    def _create_import(
        self,
        suffix: str,
        ref: str,
        *,
        mode: str = "IMPORT",
        rights_authorization: str = "licensed",
        license_name: str = "MIT",
        copyright_boundary: str = "analysis and abstraction only",
    ) -> dict[str, object]:
        policy = SourceImportPolicy(analysis_profile="writing_theory")
        return self.application.create_import(
            CreateSourceImportCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                source_type="github_repository",
                repository_url=self.repository.as_uri(),
                requested_ref=ref,
                policy=policy,
                analysis_profile=policy.analysis_profile,
                mode=mode,
                rights_authorization=rights_authorization,
                license_name=license_name,
                copyright_boundary=copyright_boundary,
                actor_id="source-import-operator",
                idempotency_key=f"{self.project_id}:{suffix}",
                trace_id=f"trace:{self.project_id}:{suffix}",
                correlation_id=f"correlation:{self.project_id}",
            )
        )

    def _operations(self, definition: str) -> list[str]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_id FROM authority_operation
                WHERE project_id=%s AND definition_name=%s
                ORDER BY created_at, operation_id
                """,
                [self.project_id, definition],
            )
            return [str(row[0]) for row in cursor.fetchall()]

    def _candidate_for_dimension(self, dimension: str) -> str:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT candidate.asset_version_id
                FROM authority_mkaos_knowledge_candidate AS candidate
                JOIN authority_asset_version AS candidate_version
                  ON candidate_version.asset_version_id=candidate.asset_version_id
                JOIN LATERAL jsonb_array_elements_text(
                    candidate_version.content->'lineage'
                      ->'observation_asset_version_ids'
                ) AS lineage(observation_id) ON TRUE
                JOIN authority_source_deconstruction_observation AS observation
                  ON observation.asset_version_id=lineage.observation_id
                WHERE candidate.project_id=%s AND observation.dimension=%s
                ORDER BY candidate.created_at DESC
                LIMIT 1
                """,
                [self.project_id, dimension],
            )
            row = cursor.fetchone()
        if row is None:
            raise AssertionError(f"candidate for {dimension} was not produced")
        return str(row[0])

    def _observation_contract(
        self, dimension: str
    ) -> tuple[ObservationScope, AnalyzerContract, str]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content, chunk.source_transform_id
                FROM authority_source_deconstruction_observation AS observation
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=observation.asset_version_id
                JOIN authority_source_deconstruction_observation_input AS input
                  ON input.observation_asset_version_id=observation.asset_version_id
                 AND input.role='SOURCE_CHUNK_EVIDENCE'
                JOIN authority_source_chunk AS chunk
                  ON chunk.asset_version_id=input.input_asset_version_id
                WHERE observation.project_id=%s AND observation.dimension=%s
                  AND version.lifecycle='ACTIVE'
                ORDER BY observation.created_at DESC
                LIMIT 1
                """,
                [self.project_id, dimension],
            )
            row = cursor.fetchone()
        if row is None:
            raise AssertionError(f"Observation for {dimension} was not produced")
        content = dict(row[0])
        analyzer = AnalyzerContract(
            **{
                key: value
                for key, value in dict(content["analyzer"]).items()
                if key != "fingerprint"
            }
        )
        return ObservationScope(**dict(content["scope"])), analyzer, str(row[1])

    def _dimension_asset_versions(self, dimension: str) -> tuple[str, ...]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT asset_version_id
                FROM authority_source_deconstruction_observation
                WHERE project_id=%s AND dimension=%s
                ORDER BY asset_version_id
                """,
                [self.project_id, dimension],
            )
            return tuple(str(row[0]) for row in cursor.fetchall())

    def _run_ready_source_operations(self) -> None:
        for _ in range(40):
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
        raise AssertionError("Source reprocessing did not reach a durable pause")

    def _ready_operations(self, definition: str) -> list[str]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_id
                FROM authority_operation
                WHERE project_id=%s AND definition_name=%s AND status='READY'
                ORDER BY created_at, operation_id
                """,
                [self.project_id, definition],
            )
            return [str(row[0]) for row in cursor.fetchall()]

    def _model_effect_count(self, operation_id: str) -> int:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_external_effect
                WHERE project_id=%s AND operation_id=%s
                  AND effect_type='model.invoke'
                """,
                [self.project_id, operation_id],
            )
            return int(cursor.fetchone()[0])

    def _git(self, *arguments: str, cwd: Path | None = None) -> str:
        directory = cwd or self.repository
        directory.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ("git", *arguments),
            cwd=directory,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout


if __name__ == "__main__":
    unittest.main()
