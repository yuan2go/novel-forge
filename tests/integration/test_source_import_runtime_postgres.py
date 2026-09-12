from __future__ import annotations

import hashlib
import json
import os
import shutil
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
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
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
    SourceIntelligencePolicy,
    SourceAnalysisOverride,
    SourceImportQuery,
    SourceImportScheduler,
    SourceMethodologyRegistry,
)
from novel_forge.modules.source_import.classical_corpus import resolve_work_spec
from novel_forge.modules.source_import.methodologies import METHODOLOGY_VERSIONS
from novel_forge.modules.source_import import analysis_profiles
from novel_forge.modules.source_import.profiling import SourceContentType
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
    build_production_execution_composition,
    build_source_import_application,
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


class _UnknownOnceGitAdapter:
    def __init__(self, delegate: GitRepositoryExternalEffectAdapter) -> None:
        self.delegate = delegate
        self.provider = delegate.provider
        self.reconciliation_mode = delegate.reconciliation_mode
        self.capability_profile = delegate.capability_profile
        self.execute_count = 0
        self.query_count = 0

    def execute(self, **kwargs: object) -> ProviderResult:
        self.execute_count += 1
        raise ExternalEffectAdapterError(
            "injected transport loss after request send",
            request_sent=True,
        )

    def query(self, **kwargs: object) -> ProviderResult:
        self.query_count += 1
        return self.delegate.execute(**kwargs)  # type: ignore[arg-type]

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
        settings = IndustrialSettings(root=self.root, database_url=DATABASE_URL)
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_PROVIDER_MODEL_CONTEXT_LIMIT": "131072",
            "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
            "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
            "NOVEL_FORGE_REVISION_PROVIDER": "mock",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(self.object_root),
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
        }
        self.production_execution = build_production_execution_composition(
            settings, env=env
        )
        execution_port = PostgresContentIntelligenceExecutionPort(
            DATABASE_URL,
            transport=self.production_execution.gateway,
            worker_id="source-import-integration-worker",
            lease_seconds=30,
            source_object_reader=LocalObjectStoreReader(self.object_root),
            provider_timeout_seconds=900,
        )
        self.execution_port = execution_port
        self.application = SourceImportApplication(
            DATABASE_URL,
            application_build_id="source-import-integration",
            commit_sha="e" * 40,
            worker_id="source-import-integration-worker",
            git_adapter=git_adapter,
            object_store_adapter=self.production_execution.object_store,
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

    def test_production_composition_runs_automatic_document_routing(self) -> None:
        settings = IndustrialSettings(root=self.root, database_url=DATABASE_URL)
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_DRAFT_PROVIDER": "mock",
            "NOVEL_FORGE_REVIEW_PROVIDER": "mock",
            "NOVEL_FORGE_REVISION_PROVIDER": "mock",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                self.root / "composed-objects"
            ),
            "NOVEL_FORGE_SOURCE_IMPORT_GIT_CACHE_ROOT": str(
                self.root / "composed-git-cache"
            ),
            "NOVEL_FORGE_SOURCE_IMPORT_FILE_FIXTURE_ROOT": str(self.root),
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "source-import-composition-test",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
        }
        execution = build_production_execution_composition(settings, env=env)
        composed = build_source_import_application(
            settings,
            execution=execution,
            env=env,
        )
        self.assertIsInstance(
            composed.execution_port, PostgresContentIntelligenceExecutionPort
        )
        admitted = composed.create_import(
            CreateSourceImportCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                source_type="github_repository",
                repository_url=self.repository.as_uri(),
                requested_ref=self.commit_a,
                policy=SourceImportPolicy(),
                intelligence_policy=SourceIntelligencePolicy(),
                analysis_override=None,
                mode="IMPORT",
                rights_authorization="licensed",
                license_name="MIT",
                copyright_boundary="analysis and abstraction only",
                actor_id="source-import-operator",
                idempotency_key="production-composition-routing",
                trace_id=f"trace:{self.project_id}:production-composition",
                correlation_id=f"correlation:{self.project_id}",
            )
        )
        scheduler = SourceImportScheduler(
            composed,
            worker_id="source-import-production-composition-worker",
            lease_seconds=30,
        )
        for _ in range(80):
            ready = self._ready_source_operation_ids()
            if not ready:
                break
            for operation_id in ready:
                scheduler.run_or_recover(
                    operation_id=operation_id, project_id=self.project_id
                )
        else:
            self.fail("production Source Import composition did not quiesce")
        routes = self._document_routes(admitted["import_job_id"])
        self.assertEqual(routes["theory.md"]["resolved_content_type"], "WRITING_THEORY")
        methodology_ids = {
            item["skill_id"] for item in routes["theory.md"]["methodologies"]
        }
        self.assertEqual(methodology_ids, {"multidisciplinary-knowledge"})

    def test_work_import_materializes_native_manifest_and_exact_replay(self) -> None:
        spec = resolve_work_spec("chinese-novel.sanguoyanyi")
        root = self.repository / spec.root_path
        root.mkdir(parents=True)
        info = {
            "catalogueTotal": 3,
            "catalogues": ["序言", "第一回", "附录"],
            "author": {
                "name": "测试作者",
                "dynasty": "测试朝代",
                "intro": "这段作者介绍不得混入正文。",
            },
        }
        (root / "info.json").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8"
        )
        (root / "0.html").write_text("序文<br>第二行", encoding="utf-8")
        (root / "1.html").write_text(
            "古典命运象征礼教正文第一段<br><br>古典命运象征礼教正文第二段",
            encoding="utf-8",
        )
        (root / "2.html").write_text("附录文本", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-m", "add governed work fixture")
        commit = self._git("rev-parse", "HEAD").strip()
        fixture_spec = replace(
            spec,
            repository_url=self.repository.as_uri(),
            repository_commit_sha=commit,
            registry_id="fixture-classical-corpus",
            registry_hash="sha256:" + "a" * 64,
        )
        policy = SourceImportPolicy(
            include_globs=fixture_spec.include_globs,
            extension_allowlist=(".html", ".json"),
            max_file_bytes=1_000_000,
            max_repository_bytes=5_000_000,
            max_files=10,
            max_chunk_bytes=256,
            parser_profile=fixture_spec.parser_profile,
            source_work_key=fixture_spec.work_key,
            corpus_registry_id=fixture_spec.registry_id,
            corpus_registry_hash=fixture_spec.registry_hash,
        )

        def create(
            suffix: str,
            *,
            pinned_commit: str = commit,
            pinned_policy: SourceImportPolicy = policy,
        ) -> dict[str, object]:
            return self.application.create_import(
                CreateSourceImportCommand(
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    source_type="github_repository",
                    repository_url=self.repository.as_uri(),
                    requested_ref=pinned_commit,
                    policy=pinned_policy,
                    intelligence_policy=SourceIntelligencePolicy(),
                    analysis_override=None,
                    mode="IMPORT",
                    rights_authorization="licensed",
                    license_name="MIT",
                    copyright_boundary="local analysis and abstraction only",
                    actor_id="source-import-operator",
                    idempotency_key=f"work-import:{self.project_id}:{suffix}",
                    trace_id=f"trace:{self.project_id}:work:{suffix}",
                    correlation_id=f"correlation:{self.project_id}",
                )
            )

        with patch(
            "novel_forge.modules.source_import.application.resolve_work_spec",
            return_value=fixture_spec,
        ):
            first = create("first")
            self.scheduler.run_or_recover(
                operation_id=str(first["operation_id"]), project_id=self.project_id
            )
            work_operations = self._operations("source.import.work.process")
            self.assertEqual(len(work_operations), 1)
            self.scheduler.run_or_recover(
                operation_id=work_operations[0], project_id=self.project_id
            )
            manifest = self.query.source_work_manifest(
                project_id=self.project_id,
                import_job_id=str(first["import_job_id"]),
            )
            self.assertEqual(manifest["unit_count"], 3)
            self.assertEqual(manifest["body_unit_count"], 3)
            self.assertEqual(manifest["chunk_count"], 3)
            self.assertEqual(
                [unit["kind"] for unit in manifest["units"]],
                ["PREFACE", "CHAPTER", "APPENDIX"],
            )
            self.assertEqual(
                manifest["manifest"]["normalized_projection"]
                ["traditional_simplified_conversion"],
                "NOT_APPLIED",
            )
            serialized = json.dumps(manifest, ensure_ascii=False, default=str)
            self.assertNotIn("古典命运象征礼教正文第一段", serialized)
            self.assertNotIn("这段作者介绍不得混入正文", serialized)

            self._run_ready_source_operations()
            deconstruction_operations = self._operations(
                "source.import.deconstruction.execute"
            )
            self.assertEqual(len(deconstruction_operations), 1)
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT observation.dimension
                    FROM authority_source_deconstruction_observation AS observation
                    WHERE observation.project_id=%s
                    ORDER BY observation.dimension
                    """,
                    [self.project_id],
                )
                dimensions = {str(row[0]) for row in cursor.fetchall()}
                cursor.execute(
                    """
                    SELECT version.content
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset
                      ON asset.asset_id=version.asset_id
                    WHERE asset.project_id=%s
                      AND asset.asset_type='model_call_log'
                      AND version.content ?
                          'source_compound_deconstruction_binding'
                    """,
                    [self.project_id],
                )
                compound_logs = [dict(row[0]) for row in cursor.fetchall()]
            self.assertEqual(
                dimensions,
                {
                    "chapter_hook",
                    "character_choice_cost",
                    "conflict",
                    "foreshadowing_payoff",
                    "information_gap",
                    "pacing",
                    "structure",
                },
            )
            self.assertEqual(len(compound_logs), 1)
            self.assertEqual(
                len(compound_logs[0]["source_deconstruction_bindings"]), 7
            )
            self.assertEqual(
                self._source_intelligence_counts()["knowledge_candidates"], 7
            )

            self._assert_corpus_boundary_on_work_candidates(first, commit)

            profiling_operations_before_replay = len(
                self._operations("source.import.document.profile")
            )
            second = create("second")
            self.scheduler.run_or_recover(
                operation_id=str(second["operation_id"]), project_id=self.project_id
            )
            work_operations = self._operations("source.import.work.process")
            self.assertEqual(len(work_operations), 2)
            self.scheduler.run_or_recover(
                operation_id=work_operations[-1], project_id=self.project_id
            )
            self.assertEqual(
                len(self._operations("source.import.document.profile")),
                profiling_operations_before_replay + 1,
            )
            replay = self.query.import_job(
                project_id=self.project_id,
                import_job_id=str(second["import_job_id"]),
            )

        self.assertEqual(replay["effective_status"], "PROCESSING")
        self.assertEqual(replay["counters"]["files_to_fetch"], 0)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM authority_source_work_version "
                "WHERE project_id=%s",
                [self.project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
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

        (root / "1.html").write_text(
            "原生作品正文改版第一段<br><br>原生作品正文改版第二段",
            encoding="utf-8",
        )
        self._git("add", ".")
        self._git("commit", "-m", "update governed work fixture")
        updated_commit = self._git("rev-parse", "HEAD").strip()
        updated_spec = replace(
            fixture_spec,
            repository_commit_sha=updated_commit,
            registry_hash="sha256:" + "b" * 64,
        )
        updated_policy = replace(
            policy,
            corpus_registry_hash=updated_spec.registry_hash,
        )
        with patch(
            "novel_forge.modules.source_import.application.resolve_work_spec",
            return_value=updated_spec,
        ):
            updated = create(
                "updated",
                pinned_commit=updated_commit,
                pinned_policy=updated_policy,
            )
            self.scheduler.run_or_recover(
                operation_id=str(updated["operation_id"]), project_id=self.project_id
            )
            updated_work_operation = self._operations(
                "source.import.work.process"
            )[-1]
            updated_result = self.scheduler.run_or_recover(
                operation_id=updated_work_operation, project_id=self.project_id
            )
            updated_manifest = self.query.source_work_manifest(
                project_id=self.project_id,
                import_job_id=str(updated["import_job_id"]),
            )

        self.assertFalse(updated_result["result"]["source_work_version_reused"])
        self.assertGreater(
            updated_result["result"]["invalidated_descendant_count"], 0
        )
        self.assertEqual(updated_manifest["repository_commit_sha"], updated_commit)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT work_version.status, version.lifecycle
                FROM authority_source_work_version AS work_version
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=work_version.asset_version_id
                WHERE work_version.project_id=%s
                ORDER BY work_version.created_at
                """,
                [self.project_id],
            )
            self.assertEqual(
                cursor.fetchall(),
                [("SUPERSEDED", "SUPERSEDED"), ("ACTIVE", "ACTIVE")],
            )
            cursor.execute(
                """
                SELECT COUNT(*) FROM authority_content_invalidation
                WHERE project_id=%s AND cause_type='UPSTREAM_REPLACED'
                """,
                [self.project_id],
            )
            self.assertGreater(cursor.fetchone()[0], 0)

    def test_source_qualification_uses_existing_stage_and_fixture_cannot_qualify(self) -> None:
        from argparse import Namespace
        from scripts.source_qualification import SourceResponseLoss, inspect_source_operation, run_source_qualification
        from scripts.run_real_provider_qualification import _effect_evidence
        from novel_forge.modules.provider_qualification.source_binding import _receipt, source_runtime_identity

        self._create_import("source-d0-scope", self.commit_a)
        for _ in range(40):
            pending = self._ready_operations("source.import.mkaos.extract")
            if pending:
                break
            ready = self._ready_source_operation_ids()
            assert ready, "native Source analysis must create an extraction stage"
            self.scheduler.run_or_recover(operation_id=ready[0], project_id=self.project_id)
        else:
            self.fail("Source did not produce a bounded extraction stage")
        operation_id = pending[0]
        with transaction() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT command_payload#>>'{payload,capability}' FROM authority_operation WHERE operation_id=%s", [operation_id])
            capability = cursor.fetchone()[0]
        scope = inspect_source_operation(DATABASE_URL, project_id=self.project_id, operation_id=operation_id, capability=capability)
        self.assertTrue(scope["inject_response_loss"])
        preview_args = Namespace(database_url=DATABASE_URL, source_project_id=self.project_id,
                                 source_operation_id=operation_id, source_capability=capability, execute=False)
        preview = run_source_qualification(
            preview_args,
            root=Path.cwd(), commit_sha="a" * 40, implementation_identity="sha256:" + "b" * 64,
        )
        self.assertEqual(preview["result"], "NOT_RUN")
        self.assertFalse(preview["provider_request_sent"])
        self.assertEqual(preview["required_route_contract"]["accounting_basis"], "PRICED")
        with patch.dict(os.environ, {"NOVEL_FORGE_CODEX_ACCOUNTING_MODE": "ACCOUNT_ENTITLEMENT"}):
            entitlement_preview = run_source_qualification(preview_args, root=Path.cwd(), commit_sha="a" * 40,
                                               implementation_identity="sha256:" + "b" * 64)
        self.assertEqual(entitlement_preview["status"], "READY_FOR_AUTHORIZATION")
        self.assertEqual(entitlement_preview["required_route_contract"]["accounting_basis"], "ACCOUNT_ENTITLEMENT")
        self.assertEqual(entitlement_preview["required_route_contract"]["monetary_cost"], "UNKNOWN")
        self.assertFalse(entitlement_preview["provider_request_sent"])
        self.assertTrue(inspect_source_operation(DATABASE_URL, project_id=self.project_id, operation_id=operation_id, capability=capability)["inject_response_loss"])
        with self.assertRaises(ValueError):
            inspect_source_operation(DATABASE_URL, project_id=self.project_id + ":other", operation_id=operation_id, capability=capability)
        original = self.execution_port.transport
        fault = SourceResponseLoss(original, enabled=True)
        self.execution_port.transport = fault
        with self.assertRaisesRegex(KernelError, "EFFECT_EXTERNAL_STATE_UNKNOWN"):
            self.scheduler.run_or_recover(operation_id=operation_id, project_id=self.project_id)
        self.assertTrue(fault.triggered)
        waiting = inspect_source_operation(DATABASE_URL, project_id=self.project_id, operation_id=operation_id, capability=capability)
        self.assertFalse(waiting["inject_response_loss"])
        self.execution_port.transport = original
        recovered = self.scheduler.run_or_recover(operation_id=operation_id, project_id=self.project_id)
        self.assertEqual(recovered["status"], "SUCCEEDED")
        replay = self.scheduler.run_or_recover(operation_id=operation_id, project_id=self.project_id)
        self.assertTrue(replay["replayed"])
        _effect, evidence, dispatches, receipts, reconciliations, _ = _effect_evidence(DATABASE_URL, operation_id=operation_id, capability=capability)
        self.assertEqual((dispatches, receipts, reconciliations), (1, 1, 1))
        self.assertTrue(evidence["fixture_protocol_only"])
        with transaction() as connection, self.assertRaisesRegex(KernelError, "SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
            _receipt(connection.cursor(), project_id=self.project_id, effect_id=str(_effect["external_effect_id"]))
        self.assertNotIn("capability_runtime", evidence)
        with self.assertRaisesRegex(KernelError, "SOURCE_RUNTIME_QUALIFICATION_REQUIRED"):
            source_runtime_identity(evidence)

    def test_unknown_effect_checkpoints_and_reconciles_without_redispatch(self) -> None:
        adapter = _UnknownOnceGitAdapter(self.git_adapter)
        self.application.git_adapter = adapter
        imported = self._create_import("unknown-effect", self.commit_a, mode="PREVIEW")

        with self.assertRaisesRegex(KernelError, "EFFECT_EXTERNAL_STATE_UNKNOWN"):
            self.scheduler.run_or_recover(
                operation_id=str(imported["operation_id"]),
                project_id=self.project_id,
            )

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, attempt.status, effect.status
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [imported["operation_id"]],
            )
            self.assertEqual(
                cursor.fetchone(),
                ("WAITING_EXTERNAL_RESULT", "CHECKPOINTED", "UNKNOWN"),
            )
        self.assertIn(
            (str(imported["operation_id"]), self.project_id),
            self.scheduler.pending_operations(),
        )

        recovered = self.scheduler.run_or_recover(
            operation_id=str(imported["operation_id"]),
            project_id=self.project_id,
        )

        self.assertEqual(recovered["status"], "SUCCEEDED")
        self.assertEqual(recovered["recovery_mode"], "external_effect_reconciled:success")
        self.assertEqual((adapter.execute_count, adapter.query_count), (1, 1))
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT effect.status, COUNT(dispatch.dispatch_id),
                       COUNT(reconciliation.reconciliation_id)
                FROM authority_external_effect AS effect
                LEFT JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                LEFT JOIN authority_effect_reconciliation_evidence AS reconciliation
                  ON reconciliation.external_effect_id=effect.external_effect_id
                WHERE effect.operation_id=%s
                GROUP BY effect.status
                """,
                [imported["operation_id"]],
            )
            self.assertEqual(cursor.fetchone(), ("SUCCEEDED", 1, 1))

    def _assert_corpus_boundary_on_work_candidates(self, imported, commit):
        from novel_forge.modules.source_authority import SourceAuthorityApplication, SourceAuthorityScheduler
        from tests.integration.test_corpus_foundation_postgres import CorpusFixture, DIGEST

        settings = IndustrialSettings(root=self.root, environment="test", database_url=DATABASE_URL)
        environment = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_MODEL_PROVIDER": "mock",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            "NOVEL_FORGE_APPLICATION_BUILD_ID": "source-corpus-coexistence",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(self.object_root),
            "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": self.project_id,
        }
        with patch.dict(os.environ, environment), TestClient(create_authority_app(settings)) as client:
            foundation = CorpusFixture(client, self.project_id, self.workspace_id,
                SourceAuthorityScheduler(SourceAuthorityApplication(DATABASE_URL,
                    application_build_id="source-corpus-coexistence", commit_sha="e" * 40)))
            source = foundation.source("BENCHMARK", "work-benchmark")
            rights = foundation.rights(source, "LICENSED")
            snapshot = self.query.import_job(project_id=self.project_id,
                import_job_id=imported["import_job_id"])["repository_snapshot_asset_version_id"]
            candidate = self._candidate_for_dimension("conflict")
            approval = self.mkaos_application.execute_approval(
                ApproveKnowledgeCandidateCommand(
                    project_id=self.project_id, workspace_id=self.workspace_id,
                    candidate_asset_version_id=candidate, policy_version="pre-corpus:v1",
                    rationale="Historical isolated fixture approval before Corpus classification",
                    actor_id="untrusted-actor", idempotency_key="pre-corpus",
                    trace_id="pre-corpus", correlation_id=self.project_id), principal=self.principal)
            pack = self.mkaos_application.execute_pack(BuildKnowledgePackCommand(
                project_id=self.project_id, workspace_id=self.workspace_id,
                target_asset_version_id=snapshot, selector_policy_version="corpus-test:v1",
                selector_policy_hash=DIGEST,
                selections=(KnowledgePackSelection(approval["asset_version_id"], "CONSTRAINT", Decimal("1")),),
                actor_id="untrusted-actor", idempotency_key="pre-corpus-pack",
                trace_id="pre-corpus-pack", correlation_id=self.project_id), principal=self.principal)
            assert self.mkaos_query.require_pack(project_id=self.project_id,
                knowledge_pack_id=pack["knowledge_pack_id"])["item_count"] == 1
            foundation.run({
                "action": "freeze_snapshot", "source_id": source, "rights_id": rights,
                "manifest": {"origin_uri": self.repository.as_uri(), "external_version": commit,
                    "format": "source-work", "checksum": DIGEST,
                    "adapter_profile": "metadata-only", "adapter_contract_version": "1"},
                "acquisition": {"locator": self.repository.as_uri(),
                    "acquired_at": "2026-09-08T00:00:00Z", "receipt_ref": "test-acquisition",
                    "checksum": DIGEST, "repository_snapshot_asset_version_id": snapshot},
            })
            candidate = self._candidate_for_dimension("pacing")
            with self.assertRaises(KernelError) as blocked:
                self.mkaos_application.execute_approval(
                    ApproveKnowledgeCandidateCommand(
                        project_id=self.project_id, workspace_id=self.workspace_id,
                        candidate_asset_version_id=candidate, policy_version="corpus-isolation:v1",
                        rationale="Corpus catalog purpose must not be laundered through SourceWork",
                        actor_id="untrusted-actor", idempotency_key="corpus-bypass",
                        trace_id="corpus-bypass", correlation_id=self.project_id), principal=self.principal)
            self.assertEqual(blocked.exception.code, "MKAOS_CORPUS_BRIDGE_REQUIRED")
            with self.assertRaises(KernelError) as blocked_pack:
                self.mkaos_query.require_pack(project_id=self.project_id, knowledge_pack_id=pack["knowledge_pack_id"])
            self.assertEqual(blocked_pack.exception.code, "MKAOS_CORPUS_BRIDGE_REQUIRED")
            if directory := os.environ.get("CORPUS_EVIDENCE_DIR"):
                Path(directory, "sourcework-corpus-coexistence.json").write_text(json.dumps({
                    "repository_snapshot_asset_version_id": snapshot,
                    "source_work_import_job": imported["import_job_id"],
                    "corpus_source_id": source, "rights_id": rights,
                    "historical_approval": approval, "historical_pack": pack,
                    "new_approval_blocked": blocked.exception.code,
                    "historical_pack_consumption_blocked": blocked_pack.exception.code,
                    "provider_evidence": "SCRIPTED_TRANSPORT_ONLY"}, indent=2, default=str))

    def test_source_provider_timeout_is_independent_from_worker_lease(self) -> None:
        self.assertEqual(self.execution_port.lease_seconds, 30)
        self.assertEqual(self.execution_port.provider_timeout_seconds, 900)

    def test_exact_commit_import_deduplicates_content_and_reuses_transform(
        self,
    ) -> None:
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
        self._run_ready_source_operations()

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
        self.assertEqual(len({item["source_document_id"] for item in theory_files}), 1)
        self.assertEqual(len({item["source_transform_id"] for item in theory_files}), 1)
        downstream = self.query.downstream_status(
            project_id=self.project_id, import_job_id=first["import_job_id"]
        )
        self.assertEqual(downstream["observations"], 6)
        self.assertEqual(downstream["knowledge_candidates"], 6)

        candidate_id = self._candidate_for_dimension("craft_principle")
        candidate = next(
            item
            for item in self.mkaos_query.list_candidates(project_id=self.project_id)
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
                    "sha256:" + hashlib.sha256(b"source-import-selector:v1").hexdigest()
                ),
                selections=(
                    KnowledgePackSelection(
                        knowledge_card_asset_version_id=approval["asset_version_id"],
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
        self.assertNotIn(
            "A question and deadline create forward pressure", serialized_pack
        )
        self.assertNotIn("source_segments", serialized_pack)

        second = self._create_import("second", self.commit_a)
        self.scheduler.run_or_recover(
            operation_id=second["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        replay = self.query.import_job(
            project_id=self.project_id, import_job_id=second["import_job_id"]
        )
        self.assertEqual(replay["effective_status"], "AWAITING_GOVERNANCE")
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
            "craft_principle"
        )
        structure_scope, structure_analyzer, _ = self._observation_contract(
            "concept_definition"
        )
        source_count_before = len(self._operations("source.import.file.process"))
        pacing_versions_before = self._dimension_asset_versions("craft_principle")
        structure_versions_before = self._dimension_asset_versions("concept_definition")
        plan = self.application.source_authority.execute_reprocessing_plan(
            PlanSourceReprocessingCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                targets=(
                    ReprocessingTarget(
                        scope=pacing_scope,
                        analyzer=replace(
                            pacing_analyzer,
                            analyzer_version="3.0",
                            prompt_version="3.0",
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
        self.assertIn(("craft_principle", "RECOMPUTE"), planned_actions)
        self.assertIn(("concept_definition", "REUSE"), planned_actions)
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
        self.assertIn(("RECOMPUTE", "BLOCKED"), statuses)
        self.assertIn(("REUSE", "REUSED"), statuses)
        self.assertIn(("REABSTRACT", "BLOCKED"), statuses)
        self.assertIn(("REGOVERN", "BLOCKED"), statuses)
        self.assertEqual(applied_plan["status"], "BLOCKED")
        invalidations = SourceAuthorityQuery(DATABASE_URL).list_invalidations(
            project_id=self.project_id,
            status="OPEN",
            dimension="craft_principle",
        )
        self.assertTrue(invalidations)
        self.assertTrue(
            all(item["dimension"] == "craft_principle" for item in invalidations)
        )
        self.assertEqual(
            self._dimension_asset_versions("concept_definition"),
            structure_versions_before,
        )
        self.assertEqual(
            len(self._dimension_asset_versions("craft_principle")),
            len(pacing_versions_before),
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
        file_ops_before_update = len(self._operations("source.import.file.process"))
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
            next(item for item in incremental_files if item["path"] == "renamed.md")[
                "diff_state"
            ],
            "RENAMED_SAME_CONTENT",
        )
        self.assertEqual(
            next(item for item in incremental_files if item["path"] == "renamed.md")[
                "status"
            ],
            "PROFILING",
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
        self.assertEqual(duplicate_retry["operation_id"], retry_import["operation_id"])
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
            "# Craft Checkpoint\nA writing craft Provider receipt must survive worker loss.\n",
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
        crash_file_operations = self._ready_work_operations(
            "source.import.file.process", str(crash_import["import_job_id"])
        )
        for crash_file_operation in crash_file_operations:
            self.scheduler.run_or_recover(
                operation_id=crash_file_operation,
                project_id=self.project_id,
            )
        self._run_source_until_analysis_ready(str(crash_import["import_job_id"]))
        crash_plan_id = str(
            self._document_routes(crash_import["import_job_id"])["crash.md"][
                "analysis_plan_asset_version_id"
            ]
        )
        crash_analysis_operation = self._ready_operation_for_work_target(
            "source.import.deconstruction.execute", crash_plan_id
        )
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
        policy = SourceImportPolicy()
        other = self.application.create_import(
            CreateSourceImportCommand(
                project_id=other_project_id,
                workspace_id=other_workspace_id,
                source_type="github_repository",
                repository_url=self.repository.as_uri(),
                requested_ref=self.commit_a,
                policy=policy,
                intelligence_policy=SourceIntelligencePolicy(),
                analysis_override=None,
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

    def test_document_routing_exact_reuse_and_contract_invalidation(self) -> None:
        (self.repository / "theory.md").unlink()
        (self.repository / "duplicate.md").unlink()
        (self.repository / "fiction.md").write_text(
            """# Chapter One
The protagonist entered the scene while the narrator withheld the motive.
\"You knew I would come,\" she said.
\"Dialogue is not proof,\" he said.
""",
            encoding="utf-8",
        )
        (self.repository / "professional.md").write_text(
            """# Distributed Systems Engineering
A quorum and consistency model constrain a distributed system protocol.
The algorithm trades availability against coordination and failure tolerance.
""",
            encoding="utf-8",
        )
        (self.repository / "opaque.md").write_text(
            "Notes without enough semantic or structural evidence.\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-m", "heterogeneous corpus fixture")
        heterogeneous_commit = self._git("rev-parse", "HEAD").strip()

        first = self._create_import("heterogeneous-first", heterogeneous_commit)
        self.scheduler.run_or_recover(
            operation_id=first["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()

        routes = self._document_routes(first["import_job_id"])
        self.assertEqual(
            routes["fiction.md"]["resolved_content_type"],
            "PUBLISHED_FICTION",
        )
        self.assertEqual(
            routes["professional.md"]["resolved_content_type"],
            "PROFESSIONAL_KNOWLEDGE",
        )
        self.assertEqual(routes["opaque.md"]["profile_status"], "NEEDS_REVIEW")
        self.assertIsNone(routes["opaque.md"]["analysis_plan_asset_version_id"])
        self.assertEqual(routes["opaque.md"]["file_status"], "PROFILE_REVIEW_REQUIRED")
        audited_files = {
            item["path"]: item
            for item in self.query.files(
                project_id=self.project_id,
                import_job_id=str(first["import_job_id"]),
            )
        }
        professional_audit = audited_files["professional.md"]
        self.assertGreater(
            float(professional_audit["source_profile"]["confidence"]), 0.72
        )
        self.assertTrue(professional_audit["source_profile"]["evidence"])
        self.assertTrue(
            professional_audit["analysis_plan"]["methodology_contract_hash"]
        )
        self.assertEqual(
            {item["skill_id"] for item in routes["fiction.md"]["methodologies"]},
            {"published-fiction-craft-analysis"},
        )
        self.assertEqual(
            {item["skill_id"] for item in routes["professional.md"]["methodologies"]},
            {"multidisciplinary-knowledge"},
        )
        materialized = self._materialized_deconstruction_skills()
        canonical = SourceMethodologyRegistry(
            Path(__file__).resolve().parents[2] / "skills"
        )
        self.assertEqual(
            materialized["published-fiction-craft-analysis"]["text"],
            canonical.require("published-fiction-craft-analysis").content,
        )
        self.assertEqual(
            materialized["multidisciplinary-knowledge"]["text"],
            canonical.require("multidisciplinary-knowledge").content,
        )
        self.assertNotEqual(
            materialized["published-fiction-craft-analysis"]["content_hash"],
            materialized["multidisciplinary-knowledge"]["content_hash"],
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_source_deconstruction_observation AS observation
                JOIN authority_source_analysis_plan AS plan
                  ON plan.asset_version_id=observation.analysis_plan_asset_version_id
                WHERE observation.project_id=%s
                  AND observation.analysis_lineage_version=
                      'source-analysis-lineage.v1'
                  AND observation.methodology_content_hash ~
                      '^sha256:[0-9a-f]{64}$'
                  AND plan.methodology_contract_hash ~
                      '^sha256:[0-9a-f]{64}$'
                """,
                [self.project_id],
            )
            traced_observations = int(cursor.fetchone()[0])
        self.assertGreater(traced_observations, 0)

        baseline = self._source_intelligence_counts()
        invalidations_before_classifier = self._invalidation_counts()
        second = self._create_import("heterogeneous-exact", heterogeneous_commit)
        self.scheduler.run_or_recover(
            operation_id=second["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        self.assertEqual(self._source_intelligence_counts(), baseline)
        second_work = self.query.work(
            project_id=self.project_id, import_job_id=second["import_job_id"]
        )
        replay_work = [
            item
            for item in second_work
            if item["work_kind"]
            in {
                "PROFILING",
                "ANALYSIS_PLANNING",
                "DECONSTRUCTION",
                "MKAOS_EXTRACTION",
            }
        ]
        self.assertTrue(replay_work)
        self.assertTrue(
            all(item["status"] in {"REUSED", "BLOCKED"} for item in replay_work)
        )

        professional_scope_hash = str(
            routes["professional.md"]["logical_document_scope_hash"]
        )
        scoped_override = SourceAnalysisOverride(
            logical_document_scope_hash=professional_scope_hash,
            content_type="WRITING_THEORY",
            reason=(
                "governance review determined this document is a writing craft "
                "reference despite its professional terminology"
            ),
            decision_ref="review-issue:source-profile:professional-override",
        )
        overridden = self._create_import(
            "heterogeneous-scoped-override",
            heterogeneous_commit,
            analysis_override=scoped_override,
        )
        self.scheduler.run_or_recover(
            operation_id=overridden["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        overridden_routes = self._document_routes(overridden["import_job_id"])
        self.assertEqual(
            overridden_routes["professional.md"]["resolved_content_type"],
            "WRITING_THEORY",
        )
        self.assertEqual(
            overridden_routes["professional.md"]["override_contract_hash"],
            scoped_override.contract_hash,
        )
        self.assertEqual(
            overridden_routes["fiction.md"]["resolved_content_type"],
            "PUBLISHED_FICTION",
        )
        self.assertEqual(overridden_routes["fiction.md"]["override_contract_hash"], "")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content->'governance_override'->>'reason',
                       version.content->'governance_override'
                         ->>'logical_document_scope_hash'
                FROM authority_source_content_profile AS profile
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=profile.asset_version_id
                WHERE profile.project_id=%s
                  AND profile.override_contract_hash=%s
                """,
                [self.project_id, scoped_override.contract_hash],
            )
            override_audit = cursor.fetchone()
        self.assertEqual(
            override_audit,
            (scoped_override.reason, professional_scope_hash),
        )
        baseline = self._source_intelligence_counts()

        classifier_policy = SourceIntelligencePolicy(classifier_version="1.1")
        reclassified = self._create_import(
            "heterogeneous-classifier-upgrade",
            heterogeneous_commit,
            intelligence_policy=classifier_policy,
        )
        self.scheduler.run_or_recover(
            operation_id=reclassified["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        after_classifier = self._source_intelligence_counts()
        self.assertEqual(
            after_classifier["source_documents"], baseline["source_documents"]
        )
        self.assertEqual(after_classifier["transforms"], baseline["transforms"])
        self.assertEqual(after_classifier["profiles"], baseline["profiles"] + 3)
        self.assertEqual(after_classifier["plans"], baseline["plans"] + 2)
        self.assertGreater(after_classifier["observations"], baseline["observations"])
        self.assertGreater(
            after_classifier["knowledge_candidates"],
            baseline["knowledge_candidates"],
        )
        invalidations_after_classifier = self._invalidation_counts()
        self.assertGreater(
            invalidations_after_classifier.get("CLASSIFIER_UPGRADE", 0),
            invalidations_before_classifier.get("CLASSIFIER_UPGRADE", 0),
        )

        skill_root = self.root / "governed-skill-fixture"
        for skill_id in (
            "published-fiction-craft-analysis",
            "multidisciplinary-knowledge",
            "anti-copy-abstraction",
        ):
            shutil.copytree(
                Path(__file__).resolve().parents[2] / "skills" / skill_id,
                skill_root / skill_id,
            )
        professional_skill = skill_root / "multidisciplinary-knowledge" / "SKILL.md"
        professional_skill.write_text(
            professional_skill.read_text(encoding="utf-8")
            + "\n<!-- governed methodology revision 1.1 -->\n",
            encoding="utf-8",
        )
        content_upgraded_registry = SourceMethodologyRegistry(
            skill_root, versions=METHODOLOGY_VERSIONS
        )
        self.application.methodology_registry = content_upgraded_registry
        self.execution_port.methodology_registry = content_upgraded_registry
        before_skill = self._source_intelligence_counts()
        invalidations_before_skill = self._invalidation_counts()
        content_upgraded = self._create_import(
            "heterogeneous-skill-content-upgrade",
            heterogeneous_commit,
            intelligence_policy=classifier_policy,
        )
        self.scheduler.run_or_recover(
            operation_id=content_upgraded["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        after_content = self._source_intelligence_counts()
        self.assertEqual(
            after_content["source_documents"], before_skill["source_documents"]
        )
        self.assertEqual(after_content["transforms"], before_skill["transforms"])
        self.assertEqual(after_content["profiles"], before_skill["profiles"])
        self.assertEqual(after_content["plans"], before_skill["plans"] + 1)
        self.assertEqual(
            after_content["observations"], before_skill["observations"] + 7
        )
        self.assertEqual(
            after_content["knowledge_candidates"],
            before_skill["knowledge_candidates"] + 7,
        )
        content_routes = self._document_routes(content_upgraded["import_job_id"])
        professional_methodologies = content_routes["professional.md"]["methodologies"]
        self.assertEqual(professional_methodologies[0]["skill_version"], "1.0.0")
        self.assertEqual(
            professional_methodologies[0]["methodology_content_hash"],
            content_upgraded_registry.require(
                "multidisciplinary-knowledge"
            ).content_digest,
        )

        version_upgraded_registry = SourceMethodologyRegistry(
            skill_root,
            versions={
                **METHODOLOGY_VERSIONS,
                "multidisciplinary-knowledge": "1.1.0",
            },
        )
        self.application.methodology_registry = version_upgraded_registry
        self.execution_port.methodology_registry = version_upgraded_registry
        before_version = self._source_intelligence_counts()
        version_upgraded = self._create_import(
            "heterogeneous-skill-version-upgrade",
            heterogeneous_commit,
            intelligence_policy=classifier_policy,
        )
        self.scheduler.run_or_recover(
            operation_id=version_upgraded["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        after_version = self._source_intelligence_counts()
        self.assertEqual(
            after_version["source_documents"], before_version["source_documents"]
        )
        self.assertEqual(after_version["transforms"], before_version["transforms"])
        self.assertEqual(after_version["profiles"], before_version["profiles"])
        self.assertEqual(after_version["plans"], before_version["plans"] + 1)
        self.assertEqual(
            after_version["observations"], before_version["observations"] + 7
        )
        self.assertEqual(
            after_version["knowledge_candidates"],
            before_version["knowledge_candidates"] + 7,
        )
        version_routes = self._document_routes(version_upgraded["import_job_id"])
        self.assertEqual(
            version_routes["professional.md"]["methodologies"][0]["skill_version"],
            "1.1.0",
        )
        self.assertGreater(
            self._invalidation_counts().get("METHODOLOGY_UPGRADE", 0),
            invalidations_before_skill.get("METHODOLOGY_UPGRADE", 0),
        )

        routing_policy = replace(
            classifier_policy,
            routing_policy_version="source-analysis-routing.v3",
        )
        before_routing = self._source_intelligence_counts()
        routing_upgraded = self._create_import(
            "heterogeneous-routing-upgrade",
            heterogeneous_commit,
            intelligence_policy=routing_policy,
        )
        self.scheduler.run_or_recover(
            operation_id=routing_upgraded["operation_id"], project_id=self.project_id
        )
        self._run_ready_source_operations()
        after_routing = self._source_intelligence_counts()
        self.assertEqual(
            after_routing["source_documents"], before_routing["source_documents"]
        )
        self.assertEqual(after_routing["transforms"], before_routing["transforms"])
        self.assertEqual(after_routing["profiles"], before_routing["profiles"])
        self.assertEqual(after_routing["plans"], before_routing["plans"] + 2)
        self.assertEqual(
            after_routing["observations"], before_routing["observations"] + 16
        )

        profile_type = SourceContentType.PROFESSIONAL_KNOWLEDGE
        original_profile = analysis_profiles._PROFILES[profile_type]
        before_profile = self._source_intelligence_counts()
        try:
            analysis_profiles._PROFILES[profile_type] = replace(
                original_profile, profile_version="2.1"
            )
            profile_upgraded = self._create_import(
                "heterogeneous-profile-upgrade",
                heterogeneous_commit,
                intelligence_policy=routing_policy,
            )
            self.scheduler.run_or_recover(
                operation_id=profile_upgraded["operation_id"],
                project_id=self.project_id,
            )
            self._run_ready_source_operations()
        finally:
            analysis_profiles._PROFILES[profile_type] = original_profile
        after_profile = self._source_intelligence_counts()
        self.assertEqual(
            after_profile["source_documents"], before_profile["source_documents"]
        )
        self.assertEqual(after_profile["transforms"], before_profile["transforms"])
        self.assertEqual(after_profile["profiles"], before_profile["profiles"])
        self.assertEqual(after_profile["plans"], before_profile["plans"] + 1)
        self.assertEqual(
            after_profile["observations"], before_profile["observations"] + 7
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
                        "policy": {},
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
                        "policy": {},
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
        intelligence_policy: SourceIntelligencePolicy | None = None,
        analysis_override: SourceAnalysisOverride | None = None,
    ) -> dict[str, object]:
        policy = SourceImportPolicy()
        return self.application.create_import(
            CreateSourceImportCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                source_type="github_repository",
                repository_url=self.repository.as_uri(),
                requested_ref=ref,
                policy=policy,
                intelligence_policy=(intelligence_policy or SourceIntelligencePolicy()),
                analysis_override=analysis_override,
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

    def _document_routes(self, import_job_id: object) -> dict[str, dict[str, object]]:
        job = self.query.import_job(
            project_id=self.project_id, import_job_id=str(import_job_id)
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT file.path, file.status, profile.status,
                       profile.resolved_content_type,
                       file.source_analysis_plan_asset_version_id,
                       COALESCE(plan.methodologies, '[]'::jsonb),
                       profile.logical_document_scope_hash,
                       profile.override_contract_hash
                FROM authority_source_repository_file AS file
                LEFT JOIN authority_source_content_profile AS profile
                  ON profile.asset_version_id=
                     file.source_content_profile_asset_version_id
                LEFT JOIN authority_source_analysis_plan AS plan
                  ON plan.asset_version_id=
                     file.source_analysis_plan_asset_version_id
                WHERE file.project_id=%s
                  AND file.repository_snapshot_asset_version_id=%s
                ORDER BY file.path
                """,
                [
                    self.project_id,
                    job["repository_snapshot_asset_version_id"],
                ],
            )
            rows = cursor.fetchall()
        return {
            str(row[0]): {
                "file_status": row[1],
                "profile_status": row[2],
                "resolved_content_type": row[3],
                "analysis_plan_asset_version_id": row[4],
                "methodologies": list(row[5]),
                "logical_document_scope_hash": row[6],
                "override_contract_hash": row[7],
            }
            for row in rows
        }

    def _materialized_deconstruction_skills(
        self,
    ) -> dict[str, dict[str, str]]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version.content->'contract'->'skill'->>'ref',
                       version.content->'contract'->'skill'->>'version',
                       version.content->'contract'->'skill'->>'content_hash',
                       version.content->'contract'->'skill'->>'text'
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND asset.asset_type='capability_materialization_manifest'
                  AND version.content->'contract'->>'stage'=
                      'source.deconstruction.observe'
                ORDER BY version.created_at
                """,
                [self.project_id],
            )
            rows = cursor.fetchall()
        return {
            str(row[0]): {
                "version": str(row[1]),
                "content_hash": str(row[2]),
                "text": str(row[3]),
            }
            for row in rows
        }

    def _source_intelligence_counts(self) -> dict[str, int]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM authority_source_document
                   WHERE project_id=%s),
                  (SELECT COUNT(*) FROM authority_source_transform
                   WHERE project_id=%s),
                  (SELECT COUNT(*) FROM authority_source_content_profile
                   WHERE project_id=%s),
                  (SELECT COUNT(*) FROM authority_source_analysis_plan
                   WHERE project_id=%s),
                  (SELECT COUNT(*)
                   FROM authority_source_deconstruction_observation
                   WHERE project_id=%s),
                  (SELECT COUNT(*) FROM authority_mkaos_knowledge_candidate
                   WHERE project_id=%s),
                  (SELECT COUNT(*) FROM authority_external_effect
                   WHERE project_id=%s AND effect_type='model.invoke')
                """,
                [self.project_id] * 7,
            )
            row = cursor.fetchone()
        keys = (
            "source_documents",
            "transforms",
            "profiles",
            "plans",
            "observations",
            "knowledge_candidates",
            "model_effects",
        )
        return dict(zip(keys, (int(item) for item in row), strict=True))

    def _invalidation_counts(self) -> dict[str, int]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT cause_type, COUNT(*)
                FROM authority_content_invalidation
                WHERE project_id=%s
                GROUP BY cause_type
                """,
                [self.project_id],
            )
            return {str(row[0]): int(row[1]) for row in cursor.fetchall()}

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
            ready = self._ready_source_operation_ids()
            if not ready:
                return
            for operation_id in ready:
                self.scheduler.run_or_recover(
                    operation_id=operation_id, project_id=self.project_id
                )
        raise AssertionError("Source reprocessing did not reach a durable pause")

    def _ready_source_operation_ids(self) -> list[str]:
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
            return [str(row[0]) for row in cursor.fetchall()]

    def _run_source_until_analysis_ready(self, import_job_id: str) -> None:
        planning_definitions = {
            "source.import.document.profile",
            "source.import.analysis.plan",
        }
        for _ in range(20):
            ready = [
                operation_id
                for definition in planning_definitions
                for operation_id in self._ready_work_operations(
                    definition, import_job_id
                )
            ]
            if not ready:
                if self._ready_work_operations(
                    "source.import.deconstruction.execute", import_job_id
                ):
                    return
                raise AssertionError("Source AnalysisPlan produced no analysis work")
            for operation_id in ready:
                self.scheduler.run_or_recover(
                    operation_id=operation_id, project_id=self.project_id
                )
        raise AssertionError("Source profiling/planning did not reach analysis")

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

    def _ready_work_operations(self, definition: str, import_job_id: str) -> list[str]:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.operation_id
                FROM authority_operation AS operation
                JOIN authority_source_import_work AS work
                  ON work.operation_id=operation.operation_id
                WHERE operation.project_id=%s
                  AND operation.definition_name=%s
                  AND operation.status='READY'
                  AND work.import_job_id=%s
                ORDER BY operation.created_at, operation.operation_id
                """,
                [self.project_id, definition, import_job_id],
            )
            return [str(row[0]) for row in cursor.fetchall()]

    def _ready_operation_for_work_target(
        self, definition: str, target_asset_version_id: str
    ) -> str:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.operation_id
                FROM authority_operation AS operation
                JOIN authority_source_import_work AS work
                  ON work.operation_id=operation.operation_id
                WHERE operation.project_id=%s
                  AND operation.definition_name=%s
                  AND operation.status='READY'
                  AND work.target_asset_version_id=%s
                ORDER BY operation.created_at, operation.operation_id
                LIMIT 1
                """,
                [
                    self.project_id,
                    definition,
                    target_asset_version_id,
                ],
            )
            row = cursor.fetchone()
        if row is None:
            raise AssertionError(
                f"No READY {definition} operation targets {target_asset_version_id}"
            )
        return str(row[0])

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
