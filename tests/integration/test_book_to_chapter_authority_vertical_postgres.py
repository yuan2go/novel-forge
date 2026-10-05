from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
    build_reader_outcome_model_port,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.production import (
    ChapterAuthorityCommandAdapter,
    PostgresBookAuthority,
    StartBookProductionCommand,
    SubmitBookChapterCommand,
    _validate_chapter_acceptance_evidence,
    select_chapter_acceptance_outputs,
)
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.book_authority.governed_scheduler import (
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_intelligence import PacingAnalysisService
from novel_forge.modules.narrative_state import NarrativeStateRebuildService
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.temporal_query import TemporalQueryService
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSagaAdmission,
    SingleChapterRequest,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.workers.book_authority import (
    execute_book_coordination_claim,
    schedule_book_coordination_jobs,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration import test_postgresql_only_chapter_slice as chapter_fixture


@dataclass
class _SynchronousCommandPort:
    """Fixture executor over the real Chapter Authority command/runtime path."""

    application: object
    submissions: int = 0

    def submit(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission:
        principal.require("chapter.authority.execute", request.project_id)
        self.submissions += 1
        result = self.application.run(request)
        return ChapterSagaAdmission(
            root_operation_id=result.root_operation_id,
            saga_id=result.saga_id,
            first_operation_id=result.operation_ids[next(iter(result.operation_ids))],
            status="ACCEPTED",
            replayed=False,
        )

    def require_run(self, *, project_id: str, root_operation_id: str):
        return self.application.query.require_run(
            project_id=project_id, root_operation_id=root_operation_id
        )

    def require_acceptance_evidence(self, *, project_id: str, root_operation_id: str):
        return self.application.query.require_acceptance_evidence(
            project_id=project_id, root_operation_id=root_operation_id
        )


class BookToChapterAuthorityVerticalPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_acceptance_freezes_typed_execution_plan_for_chapter_outcome(self) -> None:
        logical_plan = "story-planning-candidate:chapter-1"
        execution_plan = "typed-chapter-plan:chapter-1"
        execution_hash = "sha256:typed-plan"
        contents = {
            "chapter_plan": {
                "chapter": 1,
                "source_chapter_plan_asset_version_id": execution_plan,
                "source_chapter_plan_content_hash": execution_hash,
            },
            "best_draft_candidate": {},
            "re_review_report": {"decision": "PASSED", "blocking_issue_count": 0},
            "canon_patch": {"gate": "PASSED", "conflicts": []},
            "canon_snapshot": {},
            "quality_score_report": {"gate": "PASSED_WITH_UNCALIBRATED"},
            "release_package": {
                "release_status": "READY_FOR_BLOB_VERIFICATION",
                "source_asset_version_id": "best_draft_candidate:v1",
            },
            "final_release_gate_report": {
                "gate": "PASSED",
                "release_status": "INTERNAL_RELEASE_FINALIZED",
                "accepted_asset_version_ids": {
                    "export": "release_package:v1",
                    "quality": "quality_score_report:v1",
                    "rereview": "re_review_report:v1",
                    "canon": "canon_patch:v1",
                    "context_bundle": "context_bundle:v1",
                },
                "blob_receipt": {"receipt_id": "receipt:chapter-1"},
            },
        }
        outputs = [
            {
                "asset_type": asset_type,
                "asset_version_id": (
                    execution_plan
                    if asset_type == "chapter_plan"
                    else f"{asset_type}:v1"
                ),
                "content_hash": (
                    execution_hash
                    if asset_type == "chapter_plan"
                    else f"sha256:{asset_type}"
                ),
                "content": content,
                "lifecycle": "ACTIVE",
                "eligibility": "ELIGIBLE",
                "governance": "CLEAR",
            }
            for asset_type, content in contents.items()
        ]

        frozen = _validate_chapter_acceptance_evidence(
            request={
                "chapter_number": 1,
                "project_id": "grounded-contract-fixture",
                "chapter_plan_version": logical_plan,
                "chapter_plan_content_hash": "sha256:logical-plan",
                "command_payload": {
                    "execution_chapter_plan_asset_version_id": execution_plan,
                    "execution_chapter_plan_content_hash": execution_hash,
                },
            },
            evidence={
                "status": "SUCCEEDED",
                "saga": {"status": "SUCCEEDED"},
                "outputs": outputs,
                "model_effects": [],
                "budgets": [],
            },
        )

        self.assertIn(
            {"asset_version_id": execution_plan, "content_hash": execution_hash},
            frozen,
        )
        self.assertNotIn(
            {
                "asset_version_id": logical_plan,
                "content_hash": "sha256:logical-plan",
            },
            frozen,
        )

        corrected_outputs = [
            *outputs,
            *[
                {
                    **next(
                        item for item in outputs if item["asset_type"] == asset_type
                    ),
                    "asset_version_id": f"{asset_type}:superseded",
                    "content_hash": f"sha256:{asset_type}:superseded",
                }
                for asset_type in (
                    "best_draft_candidate",
                    "re_review_report",
                    "canon_patch",
                    "quality_score_report",
                )
            ],
        ]
        corrected = _validate_chapter_acceptance_evidence(
            request={
                "chapter_number": 1,
                "project_id": "grounded-contract-fixture",
                "chapter_plan_version": logical_plan,
                "chapter_plan_content_hash": "sha256:logical-plan",
                "command_payload": {
                    "execution_chapter_plan_asset_version_id": execution_plan,
                    "execution_chapter_plan_content_hash": execution_hash,
                },
            },
            evidence={
                "status": "SUCCEEDED",
                "saga": {"status": "SUCCEEDED"},
                "outputs": corrected_outputs,
                "model_effects": [],
                "budgets": [],
            },
        )
        self.assertTrue(
            all(
                not item["asset_version_id"].endswith(":superseded")
                for item in corrected
            )
        )
        corrected_evidence = {
            "status": "SUCCEEDED",
            "saga": {"status": "SUCCEEDED"},
            "outputs": corrected_outputs,
            "model_effects": [],
            "budgets": [],
        }
        self.assertEqual(
            select_chapter_acceptance_outputs(corrected_evidence)[
                "best_draft_candidate"
            ]["asset_version_id"],
            "best_draft_candidate:v1",
        )
        self.assertEqual(
            select_chapter_acceptance_outputs(corrected_evidence)[
                "quality_score_report"
            ]["asset_version_id"],
            "quality_score_report:v1",
        )

        from novel_forge.modules.canon_graph.grounding import text_hash
        contents["best_draft_candidate"].update({"text": "她关上了门。", "selected_source_asset_version_id": "revision:v1"})
        binding = {"contract_version": "grounded-canon.v1", "project_id": "grounded-contract-fixture",
                   "semantic_status": "SUPPORTED_CANDIDATE", "candidate_asset_version_id": "best_draft_candidate:v1",
                   "context_asset_version_id": "context_bundle:v1", "text_hash": text_hash("她关上了门。")}
        contents["canon_patch"].update({"grounding": binding, "source_asset_version_id": "best_draft_candidate:v1"})
        contents["re_review_report"].update({"diagnostic_contract_version": "actionable-diagnostics.v1",
                                          "target_text_hash": binding["text_hash"], "revision_version_id": "revision:v1",
                                          "context_bundle_version_id": "context_bundle:v1"})
        contents["quality_score_report"].update({"target_asset_version_id": "best_draft_candidate:v1",
                                               "canon_patch_version_id": "canon_patch:v1", "review_asset_version_id": "re_review_report:v1",
                                               "context_bundle_version_id": "context_bundle:v1"})

        recovered = _validate_chapter_acceptance_evidence(
            request={
                "chapter_number": 1,
                "project_id": "grounded-contract-fixture",
                "chapter_plan_version": logical_plan,
                "chapter_plan_content_hash": "sha256:logical-plan",
                "command_payload": {
                    "execution_chapter_plan_asset_version_id": execution_plan,
                    "execution_chapter_plan_content_hash": execution_hash,
                },
            },
            evidence={
                "status": "SUCCEEDED",
                "saga": {"status": "SUCCEEDED"},
                "outputs": outputs,
                "model_effects": [
                    {
                        "operation_id": "operation:draft",
                        "external_effect_id": "effect:draft:attempt:1",
                        "attempt_id": "attempt:draft:1",
                        "attempt_status": "FAILED_RETRYABLE",
                        "status": "FAILED_RETRYABLE",
                    },
                    {
                        "operation_id": "operation:draft",
                        "external_effect_id": "effect:draft:attempt:2",
                        "attempt_id": "attempt:draft:2",
                        "attempt_status": "SUCCEEDED",
                        "status": "SUCCEEDED",
                    },
                ],
                "budgets": [],
            },
        )
        self.assertEqual(recovered, frozen)

        with self.assertRaisesRegex(KernelError, "effects_terminal"):
            _validate_chapter_acceptance_evidence(
                request={
                    "chapter_number": 1,
                "project_id": "grounded-contract-fixture",
                    "chapter_plan_version": logical_plan,
                    "chapter_plan_content_hash": "sha256:logical-plan",
                    "command_payload": {
                        "execution_chapter_plan_asset_version_id": execution_plan,
                        "execution_chapter_plan_content_hash": execution_hash,
                    },
                },
                evidence={
                    "status": "SUCCEEDED",
                    "saga": {"status": "SUCCEEDED"},
                    "outputs": outputs,
                    "model_effects": [
                        {
                            "operation_id": "operation:draft",
                            "external_effect_id": "effect:draft:attempt:1",
                            "attempt_id": "attempt:draft:1",
                            "attempt_status": "FAILED_RETRYABLE",
                            "status": "FAILED_RETRYABLE",
                        }
                    ],
                    "budgets": [],
                },
            )

    def test_book_acceptance_atomically_materializes_projection_set_without_sidecar_ownership(
        self,
    ) -> None:
        project_id = identifier("book-chapter-vertical")
        with tempfile.TemporaryDirectory() as root:
            settings = IndustrialSettings(
                root=Path(root),
                environment="test",
                storage_authority="postgresql",
                database_url=DATABASE_URL,
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
                "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(Path(root) / "objects"),
                "NOVEL_FORGE_AUTHORITY_WORKER_ID": "book-chapter-pep-worker",
                "NOVEL_FORGE_ENABLE_SYNCHRONOUS_AUTHORITY_FIXTURE": "true",
            }
            execution = build_production_execution_composition(settings, env=env)
            chapter = build_chapter_authority_application(
                settings, execution=execution, env=env
            )
            followup = BookFollowupAuthorityApplication(
                DATABASE_URL,
                application_build_id="book-chapter-vertical",
                commit_sha="e" * 40,
                model_port=build_reader_outcome_model_port(
                    settings, execution=execution, env=env
                ),
                worker_id="book-followup-vertical-worker",
            )
            port = _SynchronousCommandPort(chapter)
            authority = PostgresBookAuthority(
                DATABASE_URL,
                chapter_port=port,
                followup_application=followup,
                application_build_id="book-chapter-vertical",
                commit_sha="e" * 40,
                legacy_fixture_input_allowed=True,
            )
            principal = Principal(
                principal_id="book-authority-operator",
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset(
                    {
                        "book.authority.execute",
                        "book.followup:*",
                        "chapter.authority.execute",
                    }
                ),
                project_scope=frozenset({project_id}),
                authentication_source="integration-test",
            )
            candidates = (
                chapter_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(
                    project_id, current_state_contract=True
                )
            )
            longform_versions = self._seed_book_inputs(project_id)
            book = authority.start(
                StartBookProductionCommand(
                    project_id=project_id,
                    workspace_id=f"workspace:{project_id}",
                    book_id=f"book:{project_id}",
                    actor_id=principal.principal_id,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                    stable_idempotency_key=f"{project_id}:book:v1",
                    book_design_version=longform_versions.pop("book_design_version"),
                    book_plan_version=longform_versions.pop("book_plan_version"),
                    production_profile_version="production-profile:v1",
                    longform_context_versions=longform_versions,
                    target_chapter_count=1,
                    input_mode="LEGACY_FIXTURE_INPUT_MODE",
                    light_recap_cadence=1,
                    formal_recap_cadence=1,
                ),
                principal=principal,
            )
            paused = authority.pause(
                book.book_run_id, reason="fixture pause", principal=principal
            )
            resumed = authority.resume(
                book.book_run_id, reason="fixture resume", principal=principal
            )
            self.assertEqual(paused["state"], "PAUSED")
            self.assertEqual(resumed["state"], "READY")
            plan = next(
                item for item in candidates if item["asset_type"] == "chapter_plan"
            )
            chapter_command = SubmitBookChapterCommand(
                context_token_budget=64_000,
                book_run_id=book.book_run_id,
                chapter_number=1,
                title="The Cost of a Promise",
                premise="The protagonist must pay a visible cost.",
                chapter_plan_asset_version_id=str(plan["asset_version_id"]),
                chapter_plan_content_hash=str(plan["content_hash"]),
                context_candidates=tuple(candidates),
            )

            request = authority.submit_chapter(chapter_command, principal=principal)
            replay = authority.submit_chapter(chapter_command, principal=principal)
            reconciled = authority.reconcile_chapter(request["chapter_request_id"])

            self.assertEqual(port.submissions, 1)
            self.assertEqual(
                request["chapter_root_operation_id"],
                replay["chapter_root_operation_id"],
            )
            self.assertEqual(reconciled["status_reference"], "SUCCEEDED")

            scheduler = PostgresBookAuthorityScheduler(
                authority,
                query=PostgresBookProductionQuery(DATABASE_URL),
                principal=principal,
            )
            runtime_jobs = RuntimeJobAuthority(DATABASE_URL)

            def runtime_tick() -> dict[str, object]:
                schedule_book_coordination_jobs(
                    PostgresBookProductionQuery(DATABASE_URL),
                    runtime_jobs,
                    limit=10,
                    book_run_id=book.book_run_id,
                )
                claim = runtime_jobs.claim(
                    runtime_group="book",
                    worker_id="book-runtime-integration-worker",
                    lease_seconds=30,
                    job_kinds=("BOOK_COORDINATION_TICK",),
                    subject_kind="BOOK_RUN",
                    subject_id=book.book_run_id,
                )
                self.assertIsNotNone(claim)
                assert claim is not None
                return execute_book_coordination_claim(
                    runtime_jobs,
                    scheduler,
                    claim,
                )

            acceptance_tick = runtime_tick()
            self.assertEqual(acceptance_tick["action"], "ACCEPT_CHAPTER")
            accepted = authority.require(book.book_run_id)
            self.assertEqual(accepted["state"], "READY")
            self.assertEqual(accepted["current_chapter"], 1)
            self.assertTrue(accepted["active_longform_projection_set_id"])
            authority.complete_book_checkpoint(book.book_run_id, chapter_number=1)
            final = authority.require(book.book_run_id)

            self.assertEqual(final["state"], "COMPLETED")
            self.assertEqual(final["current_chapter"], 1)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT operation.status, saga.status
                    FROM authority_operation AS operation
                    JOIN authority_saga AS saga
                      ON saga.root_operation_id=operation.operation_id
                    WHERE operation.operation_id=%s
                    """,
                    [book.root_operation_id],
                )
                terminal = uow.cursor.fetchone()
                uow.cursor.execute(
                    """
                    SELECT operation.definition_name,
                           jsonb_array_length(operation.input_asset_snapshot)
                    FROM authority_operation AS operation
                    WHERE operation.operation_id=%s
                    ORDER BY operation.definition_name
                    """,
                    [book.root_operation_id],
                )
                frozen_input_counts = dict(uow.cursor.fetchall())
                uow.cursor.execute(
                    """
                    SELECT COUNT(*),
                           COUNT(*) FILTER (
                               WHERE projection_set_id=%s
                           ),
                           COUNT(*) FILTER (
                               WHERE chapter_outcome_asset_version_id=%s
                                 AND story_state_asset_version_id=%s
                                 AND canon_snapshot_asset_version_id=%s
                           )
                    FROM authority_book_narrative_projection_set
                    WHERE book_run_id=%s AND chapter_number=1
                    """,
                    [
                        final["active_longform_projection_set_id"],
                        final["last_chapter_outcome_version_id"],
                        final["active_story_state_version_id"],
                        final["active_canon_snapshot_version_id"],
                        book.book_run_id,
                    ],
                )
                projection_set_evidence = tuple(
                    int(value) for value in uow.cursor.fetchone()
                )
                uow.cursor.execute(
                    """
                    SELECT COUNT(*),
                           COUNT(*) FILTER (WHERE job.status='SUCCEEDED'),
                           COUNT(*) FILTER (
                               WHERE lease.status='RELEASED'
                                 AND attempt.fencing_token > 0
                           ),
                           COUNT(*) FILTER (
                               WHERE (
                                   SELECT COUNT(*)
                                   FROM authority_runtime_job_checkpoint AS checkpoint
                                   WHERE checkpoint.attempt_id=attempt.attempt_id
                               ) >= 2
                           )
                    FROM authority_runtime_job AS job
                    JOIN authority_runtime_job_attempt AS attempt
                      ON attempt.attempt_id=job.current_attempt_id
                    JOIN authority_runtime_job_lease AS lease
                      ON lease.attempt_id=attempt.attempt_id
                    WHERE job.runtime_group='book'
                      AND job.job_kind='BOOK_COORDINATION_TICK'
                      AND job.subject_id=%s
                    """,
                    [book.book_run_id],
                )
                runtime_job_evidence = tuple(
                    int(value) for value in uow.cursor.fetchone()
                )
            self.assertEqual(terminal, ("SUCCEEDED", "SUCCEEDED"))
            self.assertEqual(runtime_job_evidence, (1, 1, 1, 1))
            self.assertEqual(projection_set_evidence, (1, 1, 1))
            self.assertEqual(
                frozen_input_counts,
                {
                    "book.production.coordinate": 12,
                },
            )

            blocked_book = authority.start(
                StartBookProductionCommand(
                    project_id=project_id,
                    workspace_id=f"workspace:{project_id}",
                    book_id=f"book:{project_id}",
                    actor_id=principal.principal_id,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                    stable_idempotency_key=f"{project_id}:book:guard:v1",
                    book_design_version=final["book_design_version"],
                    book_plan_version=final["book_plan_version"],
                    production_profile_version="production-profile:v1",
                    longform_context_versions=dict(final["longform_context_versions"]),
                    target_chapter_count=2,
                    input_mode="LEGACY_FIXTURE_INPUT_MODE",
                ),
                principal=principal,
            )
            with self.assertRaisesRegex(
                KernelError, "BOOK_CHAPTER_SUBMISSION_NOT_READY"
            ):
                authority.submit_chapter(
                    SubmitBookChapterCommand(
                context_token_budget=64_000,
                        book_run_id=blocked_book.book_run_id,
                        chapter_number=2,
                        title="Out of order",
                        premise="This must never reach Chapter Authority.",
                        chapter_plan_asset_version_id=str(plan["asset_version_id"]),
                        chapter_plan_content_hash=str(plan["content_hash"]),
                        context_candidates=tuple(candidates),
                    ),
                    principal=principal,
                )

    def test_book_to_chapter_two_chapter_vertical_postgres(self) -> None:
        project_id = identifier("book-two-chapter-vertical")
        with tempfile.TemporaryDirectory() as root:
            settings = IndustrialSettings(
                root=Path(root),
                environment="test",
                storage_authority="postgresql",
                database_url=DATABASE_URL,
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
                "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_EMBEDDING_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_EMBEDDING_MODEL": "scripted-embedding-v1",
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(Path(root) / "objects"),
                "NOVEL_FORGE_AUTHORITY_WORKER_ID": "two-chapter-pep-worker",
            }
            execution = build_production_execution_composition(settings, env=env)
            chapter = build_chapter_authority_application(
                settings, execution=execution, env=env
            )
            followup = BookFollowupAuthorityApplication(
                DATABASE_URL,
                application_build_id="two-chapter-vertical",
                commit_sha="e" * 40,
                model_port=build_reader_outcome_model_port(
                    settings, execution=execution, env=env
                ),
                worker_id="two-chapter-followup-worker",
            )
            authority = PostgresBookAuthority(
                DATABASE_URL,
                chapter_port=ChapterAuthorityCommandAdapter(
                    chapter,
                    external_effect_adapters=execution.external_effect_adapters,
                ),
                followup_application=followup,
                application_build_id="two-chapter-vertical",
                commit_sha="e" * 40,
                legacy_fixture_input_allowed=True,
            )
            principal = self._principal(project_id)
            worker = Principal(
                principal_id="two-chapter-worker",
                principal_type=PrincipalType.WORKER,
                permissions=frozenset(
                    {"chapter.authority.execute", "external_effect.execute"}
                ),
                project_scope=frozenset({project_id}),
                authentication_source="integration-test",
            )
            candidates = list(
                chapter_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(
                    project_id
                )
            )
            plans = self._seed_two_chapter_plans(
                project_id, candidates, canonical_execution=True
            )
            longform_versions = self._seed_book_inputs(project_id)
            book = authority.start(
                StartBookProductionCommand(
                    project_id=project_id,
                    workspace_id=f"workspace:{project_id}",
                    book_id=f"book:{project_id}",
                    actor_id=principal.principal_id,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                    stable_idempotency_key=f"{project_id}:book:v1",
                    book_design_version=longform_versions.pop("book_design_version"),
                    book_plan_version=longform_versions.pop("book_plan_version"),
                    production_profile_version="production-profile:v1",
                    longform_context_versions=longform_versions,
                    target_chapter_count=2,
                    input_mode="LEGACY_FIXTURE_INPUT_MODE",
                ),
                principal=principal,
            )

            accepted_versions: list[tuple[str, str]] = []
            for chapter_number in (1, 2):
                chapter_candidates = tuple(
                    plans[chapter_number]
                    if item["asset_type"] == "chapter_plan"
                    else item
                    for item in candidates
                )
                plan = plans[chapter_number]
                command = SubmitBookChapterCommand(
                context_token_budget=64_000,
                    book_run_id=book.book_run_id,
                    chapter_number=chapter_number,
                    title=f"Chapter {chapter_number}",
                    premise=f"Chapter {chapter_number} pays a visible cost.",
                    chapter_plan_asset_version_id=str(plan["asset_version_id"]),
                    chapter_plan_content_hash=str(plan["content_hash"]),
                    context_candidates=chapter_candidates,
                )
                delegated = authority.submit_chapter(command, principal=principal)
                replay = authority.submit_chapter(command, principal=principal)
                self.assertEqual(
                    delegated["chapter_root_operation_id"],
                    replay["chapter_root_operation_id"],
                )
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    uow.cursor.execute(
                        """
                        SELECT COUNT(*) FROM authority_operation
                        WHERE project_id=%s AND definition_name='chapter.slice.run'
                        """,
                        [project_id],
                    )
                    self.assertEqual(int(uow.cursor.fetchone()[0]), chapter_number)

                # A quality-gated Chapter may execute one bounded correction loop.
                # Keep the proof bounded without assuming exactly one operation per
                # canonical node.
                for _ in range(len(ChapterNode) * 2 + 4):
                    scheduler = chapter.scheduler(principal=worker)
                    tick = scheduler.tick(
                        project_id=project_id,
                        root_operation_id=delegated["chapter_root_operation_id"],
                    )
                    if tick.saga_status == "SUCCEEDED":
                        break
                reconciled = authority.reconcile_chapter(
                    delegated["chapter_request_id"]
                )
                self.assertEqual(reconciled["status_reference"], "SUCCEEDED")
                accepted = authority.accept_chapter(
                    delegated["chapter_request_id"], principal=principal
                )
                replayed_acceptance = authority.accept_chapter(
                    delegated["chapter_request_id"], principal=principal
                )
                self.assertEqual(accepted["accepted_through_chapter"], chapter_number)
                self.assertEqual(
                    replayed_acceptance["accepted_through_chapter"],
                    chapter_number,
                )
                accepted_versions.append(
                    (
                        str(accepted["active_story_state_version_id"]),
                        str(accepted["last_chapter_outcome_version_id"]),
                    )
                )
                if chapter_number == 1:
                    embedding_runtime = chapter.embedding_projection_runtime
                    self.assertIsNotNone(embedding_runtime)
                    assert embedding_runtime is not None
                    embedding_operations = embedding_runtime.schedule_pending(
                        project_id=project_id,
                        limit=20,
                    )
                    self.assertEqual(len(embedding_operations), 7)
                    for operation_id in embedding_operations:
                        embedding_runtime.tick(
                            project_id=project_id,
                            operation_id=operation_id,
                        )

            final = authority.require(book.book_run_id)
            self.assertEqual(final["state"], "READY")
            final = authority.complete_book_checkpoint(
                book.book_run_id, chapter_number=2
            )
            self.assertEqual(final["state"], "COMPLETED")
            self.assertEqual(final["current_chapter"], 2)
            self.assertEqual(final["accepted_through_chapter"], 2)
            self.assertEqual(len({item[0] for item in accepted_versions}), 2)
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    """
                    SELECT status, COUNT(*)
                    FROM authority_child_delegation
                    WHERE project_id=%s
                    GROUP BY status
                    """,
                    [project_id],
                )
                delegation_statuses = dict(uow.cursor.fetchall())
                uow.cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM authority_book_chapter_acceptance AS acceptance
                    JOIN authority_asset_version AS outcome
                      ON outcome.asset_version_id =
                         acceptance.chapter_outcome_asset_version_id
                    JOIN authority_asset_version AS state
                      ON state.asset_version_id =
                         acceptance.story_state_asset_version_id
                    WHERE acceptance.project_id=%s
                    """,
                    [project_id],
                )
                acceptance_count = int(uow.cursor.fetchone()[0])
                uow.cursor.execute(
                    """
                    SELECT COUNT(*), MAX(accepted_chapter)
                    FROM authority_narrative_state_event_projection
                    WHERE project_id=%s AND book_id=%s
                    """,
                    [project_id, f"book:{project_id}"],
                )
                event_projection_count, latest_event_chapter = uow.cursor.fetchone()
                uow.cursor.execute(
                    """
                    SELECT accepted_through_chapter, story_state
                    FROM authority_narrative_current_state_projection
                    WHERE project_id=%s AND book_id=%s
                    """,
                    [project_id, f"book:{project_id}"],
                )
                current_projection = uow.cursor.fetchone()
                uow.cursor.execute(
                    """
                    SELECT version.content
                    FROM authority_operation_output_asset AS output
                    JOIN authority_operation AS operation
                      ON operation.operation_id=output.operation_id
                    JOIN authority_asset_version AS version
                      ON version.asset_version_id=output.asset_version_id
                    WHERE operation.project_id=%s
                      AND operation.definition_name='chapter.context.build'
                      AND output.output_key='chapter.context'
                    ORDER BY operation.created_at
                    """,
                    [project_id],
                )
                context_bundles = [dict(row[0]) for row in uow.cursor.fetchall()]
                uow.cursor.execute(
                    """
                    SELECT version.content
                    FROM authority_operation_output_asset AS output
                    JOIN authority_operation AS operation
                      ON operation.operation_id=output.operation_id
                    JOIN authority_asset_version AS version
                      ON version.asset_version_id=output.asset_version_id
                    WHERE operation.project_id=%s
                      AND operation.definition_name='chapter.context.retrieve'
                      AND output.output_key='chapter.retrieval'
                    ORDER BY operation.created_at
                    """,
                    [project_id],
                )
                retrieval_results = [dict(row[0]) for row in uow.cursor.fetchall()]
                uow.cursor.execute("""
                    SELECT version.content FROM authority_asset_version version
                    JOIN authority_asset asset USING(asset_id)
                    WHERE asset.project_id=%s AND asset.asset_type='chapter_memo'
                    ORDER BY version.created_at
                """, [project_id])
                chapter_memos = [dict(row[0]) for row in uow.cursor.fetchall()]
                uow.cursor.execute(
                    """
                    SELECT COUNT(*), COUNT(DISTINCT memory_layer)
                    FROM authority_narrative_retrieval_document
                    WHERE project_id=%s AND book_id=%s
                    """,
                    [project_id, f"book:{project_id}"],
                )
                retrieval_document_count, retrieval_layer_count = (
                    int(value) for value in uow.cursor.fetchone()
                )
                uow.cursor.execute(
                    """
                    SELECT COUNT(*) FILTER (
                               WHERE accepted_from_chapter=1
                                 AND memory_layer IN ('L1','L2','L4','L5')
                                 AND accepted_to_chapter=1
                           ),
                           BOOL_AND(metadata ? 'structured_facts')
                    FROM authority_narrative_retrieval_document
                    WHERE project_id=%s AND book_id=%s
                    """,
                    [project_id, f"book:{project_id}"],
                )
                closed_current_documents, retrieval_fact_metadata_complete = (
                    uow.cursor.fetchone()
                )
                uow.cursor.execute(
                    """
                    SELECT COUNT(*), BOOL_AND(version.content->>'gate'='PASSED')
                    FROM authority_operation_output_asset AS output
                    JOIN authority_operation AS operation
                      ON operation.operation_id=output.operation_id
                    JOIN authority_asset_version AS version
                      ON version.asset_version_id=output.asset_version_id
                    WHERE operation.project_id=%s
                      AND operation.definition_name='chapter.canon.update'
                      AND output.output_key='chapter.canon'
                    """,
                    [project_id],
                )
                canon_gate_count, all_canon_gates_passed = uow.cursor.fetchone()
                uow.cursor.execute(
                    """
                    SELECT version.content
                    FROM authority_asset AS asset
                    JOIN authority_asset_version AS version
                      ON version.asset_id=asset.asset_id
                    WHERE asset.project_id=%s
                      AND asset.asset_type='multiscale_narrative_quality_report'
                    ORDER BY version.created_at DESC
                    LIMIT 1
                    """,
                    [project_id],
                )
                multiscale_quality = dict(uow.cursor.fetchone()[0])
                uow.cursor.execute(
                    """
                    SELECT COUNT(*), COUNT(receipt.receipt_id)
                    FROM authority_external_effect AS effect
                    JOIN authority_operation AS operation
                      ON operation.operation_id=effect.operation_id
                    LEFT JOIN authority_external_effect_dispatch AS dispatch
                      ON dispatch.external_effect_id=effect.external_effect_id
                     AND dispatch.status='SUCCEEDED'
                    LEFT JOIN authority_external_receipt AS receipt
                      ON receipt.dispatch_id=dispatch.dispatch_id
                    WHERE operation.project_id=%s
                      AND operation.definition_name='chapter.context.retrieve'
                      AND effect.capability='model.retrieval'
                      AND effect.status='SUCCEEDED'
                    """,
                    [project_id],
                )
                query_embedding_effects = tuple(
                    int(value) for value in uow.cursor.fetchone()
                )
            self.assertEqual(delegation_statuses, {"ACCEPTED": 2})
            self.assertEqual(acceptance_count, 2)
            self.assertGreater(int(event_projection_count), 0)
            self.assertEqual(int(latest_event_chapter), 2)
            self.assertEqual(int(current_projection[0]), 2)
            current_state = dict(current_projection[1])["current_state"]
            self.assertEqual(
                current_state["character_arc"][0]["state"]["state"],
                "CONSEQUENT",
            )
            self.assertEqual(current_state["character_arc"][0]["entity_version"], 2)
            self.assertEqual(
                current_state["reader_knowledge"][0]["state"]["status"],
                "KNOWN",
            )
            self.assertEqual(len(current_state["disclosure_event"]), 2)
            self.assertEqual(len(context_bundles), 2)
            self.assertEqual(len(retrieval_results), 2)
            chapter_two_retrieval = retrieval_results[1]
            self.assertTrue(chapter_two_retrieval["result_fingerprint"])
            self.assertEqual(
                chapter_two_retrieval["query_plan"]["queries"],
                chapter_memos[1]["retrieval_queries"],
            )
            self.assertTrue(chapter_two_retrieval["selected_documents"])
            self.assertEqual(
                chapter_two_retrieval["retrieval_campaign"]["round_count"], 1
            )
            self.assertEqual(
                chapter_two_retrieval["retrieval_campaign"]["authority"],
                "DETERMINISTIC_CONTEXT_POLICY",
            )
            self.assertEqual(
                chapter_two_retrieval["semantic_status"]["query_embedding_status"],
                "NOT_READY",
            )
            self.assertTrue(chapter_two_retrieval["semantic_status"]["deterministic_coverage_fast_path"])
            self.assertEqual(query_embedding_effects, (0, 0))
            self.assertTrue(
                all(
                    int(item["accepted_from_chapter"]) <= 1
                    for item in chapter_two_retrieval["selected_documents"]
                )
            )
            # Each accepted Chapter contributes six structured correctness and
            # authoring projections plus its accepted prose archive entry.
            self.assertEqual(retrieval_document_count, 14)
            self.assertGreaterEqual(retrieval_layer_count, 5)
            self.assertEqual(int(closed_current_documents), 4)
            self.assertTrue(retrieval_fact_metadata_complete)
            self.assertTrue(context_bundles[1]["context_manifest"]["retrieval_trace"])
            accepted_retrieval_trace = [
                item
                for item in context_bundles[1]["context_manifest"]["retrieval_trace"]
                if item["provenance"].get("retrieval_document_ids")
            ]
            self.assertTrue(accepted_retrieval_trace)
            self.assertTrue(
                all(
                    int(
                        item["provenance"]["accepted_boundary"][
                            "accepted_through_chapter"
                        ]
                    )
                    == 1
                    for item in accepted_retrieval_trace
                )
            )
            self.assertEqual(
                context_bundles[1]["chapter_execution_expectations"][
                    "required_state_transitions"
                ][0]["from_state"],
                "COMMITTED",
            )
            self.assertEqual(
                context_bundles[1]["task_narrative_projection"]["character_ids"],
                ["protagonist"],
            )
            self.assertGreaterEqual(int(canon_gate_count), 2)
            self.assertTrue(all_canon_gates_passed)
            self.assertEqual(multiscale_quality["observation_status"], "MEASURED")
            self.assertEqual(multiscale_quality["accepted_observation_count"], 1)
            self.assertEqual(multiscale_quality["accepted_through_chapter"], 1)
            self.assertEqual(
                multiscale_quality["source_accepted_asset_version_ids"],
                [accepted_versions[0][1]],
            )
            quality_observations = [
                observation
                for segment in context_bundles[1]["host_quality_evidence"]["segments"]
                for fact in segment.get("structured_facts") or ()
                if fact.get("key") == "accepted_quality_observations"
                for observation in fact.get("value") or ()
            ]
            self.assertEqual(len(quality_observations), 1)
            self.assertEqual(quality_observations[0]["chapter_number"], 1)
            self.assertEqual(
                quality_observations[0]["accepted_asset_version_id"],
                accepted_versions[0][1],
            )
            self.assertEqual(
                quality_observations[0]["projection_contract_version"],
                "accepted-quality-observation-v3",
            )
            self.assertTrue(quality_observations[0]["canon_snapshot_asset_version_id"])
            self.assertNotIn("text", quality_observations[0])
            self.assertEqual(
                multiscale_quality["source_acceptance_ids"],
                [quality_observations[0]["acceptance_id"]],
            )
            self.assertEqual(
                multiscale_quality["contract_version"],
                "multiscale-narrative-quality-v3",
            )
            self.assertEqual(
                multiscale_quality["canonical_longitudinal_evidence"][
                    "observation_status"
                ],
                "MEASURED",
            )
            self.assertEqual(
                multiscale_quality["compatibility_projection"]["status"],
                "DEPRECATED_NON_CANONICAL",
            )

            rebuilt = NarrativeStateRebuildService(DATABASE_URL).rebuild(
                project_id=project_id,
                book_id=f"book:{project_id}",
            )
            self.assertEqual(rebuilt.accepted_outcome_count, 2)
            self.assertEqual(rebuilt.accepted_through_chapter, 2)
            self.assertEqual(rebuilt.projection, dict(current_projection[1]))

            temporal = TemporalQueryService(DATABASE_URL)
            book_id = f"book:{project_id}"
            chapter_one = temporal.changes_between(project_id, book_id, 0, 1)
            chapter_two = temporal.changes_between(project_id, book_id, 0, 2)
            self.assertEqual(chapter_one["status"], "FOUND")
            self.assertTrue(chapter_one["changes"])
            self.assertTrue(
                all(item["accepted_chapter"] == 1 for item in chapter_one["changes"])
            )
            self.assertGreater(len(chapter_two["changes"]), len(chapter_one["changes"]))
            self.assertEqual(
                temporal.changes_between(
                    identifier("unrelated-project"),
                    identifier("unrelated-book"),
                    0,
                    2,
                )["changes"],
                [],
            )
            pacing = PacingAnalysisService(DATABASE_URL)
            chapter_one_pacing = pacing.aggregate_at(
                project_id=project_id,
                chapter=1,
            )
            chapter_two_pacing = pacing.aggregate_at(
                project_id=project_id,
                chapter=2,
            )
            chapter_one_window = next(
                item
                for item in chapter_one_pacing["aggregates"]
                if item["scale"] == "3_CHAPTER_WINDOW"
            )
            chapter_two_window = next(
                item
                for item in chapter_two_pacing["aggregates"]
                if item["scale"] == "3_CHAPTER_WINDOW"
            )
            self.assertEqual(chapter_one_window["chapters"], [1])
            self.assertEqual(chapter_two_window["chapters"], [1, 2])
            self.assertEqual(
                [
                    item["accepted_chapter"]
                    for item in pacing.hook_analyses_at(
                        project_id=project_id,
                        chapter=1,
                    )["analyses"]
                ],
                [1],
            )
            unrelated_pacing = pacing.aggregate_at(
                project_id=identifier("unrelated-project"),
                chapter=2,
            )
            self.assertTrue(
                all(item["chapters"] == [] for item in unrelated_pacing["aggregates"])
            )

    def test_author_workspace_keeps_frozen_profile_and_project_book_scope(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        project = fixture["project_id"]
        book_id = f"book:{project}"
        query = PostgresBookProductionQuery(DATABASE_URL)
        missing = query.author_workspace(project_id=project, book_id=book_id)
        self.assertEqual(len(missing["runs"]), 1)
        self.assertIsNone(missing["runs"][0]["frozen_profile"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            asset_id = identifier("production-profile")
            uow.cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'production_profile')", [asset_id, project])
            for version, state, content in ((1, 'SUPERSEDED', {"book_id": book_id, "context_profile": "v2"}),
                                            (2, 'ACTIVE', {"book_id": book_id, "context_profile": "v3"}),
                                            (3, 'ACTIVE', {"book_id": "another-book", "context_profile": "unrelated"})):
                if version == 3:
                    unrelated_asset = identifier("other-book-profile")
                    uow.cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'production_profile')", [unrelated_asset, project])
                uow.cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES (%s,%s,%s,%s,'ELIGIBLE','CLEAR',%s,%s,'fixture.v1')",
                    ['production-profile:v1' if version == 1 else f'{asset_id}:v{version}', unrelated_asset if version == 3 else asset_id, version, state, json.dumps(content), 'sha256:' + hashlib.sha256(json.dumps(content).encode()).hexdigest()])
            uow.commit()
        current = query.author_workspace(project_id=project, book_id=book_id)
        self.assertEqual(current["runs"][0]["frozen_profile"]["context_profile"], "v2")
        self.assertEqual([p["content"]["context_profile"] for p in current["profiles"]], ["v3"])
        self.assertEqual(current["runs"][0]["book_run_id"], fixture["book"].book_run_id)
        cast_version, design_version = identifier("cast-version"), identifier("design-version")
        cast_hash = "sha256:" + "a" * 64
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for asset_type, version, content, content_hash in (
                ("planning_generation_candidate", cast_version, {"generator_operation_name": "character.cast.generate", "candidate_payload": {"characters": [{"character_id": "actor:1", "name": "本书角色"}]}}, cast_hash),
                ("book_design", design_version, {"foundation_set": {"bindings": [{"role": "CHARACTER_CAST", "asset_version_id": cast_version, "content_hash": cast_hash}]}}, "sha256:" + "b" * 64),
            ):
                asset_id = identifier(asset_type)
                uow.cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)", [asset_id, project, asset_type])
                uow.cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version) VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'fixture.v1')", [version, asset_id, json.dumps(content), content_hash])
            uow.cursor.execute("UPDATE authority_book SET current_book_design_asset_version_id=%s WHERE project_id=%s AND book_id=%s", [design_version, project, book_id])
            uow.commit()
        characters = query.author_workspace(project_id=project, book_id=book_id)["approved_characters"]
        self.assertEqual(characters, [{"character_id": "actor:1", "name": "本书角色", "source_asset_version_id": cast_version, "source_content_hash": cast_hash}])
        from novel_forge.modules.book_authority.control_application import PostgresBookControlApplication
        from novel_forge.modules.book_authority.control_policy import ControlPolicy
        from novel_forge.storage.book_control_repositories import BookControlRepository
        controls = PostgresBookControlApplication(DATABASE_URL, application_build_id="book-authority-control", commit_sha="e" * 40)
        for mode in ("REVIEW_PLAN", "REVIEW_CHAPTER"):
            controls.configure(policy=ControlPolicy(policy_version=f"author:{mode}", mode=mode), project_id=project, workspace_id=f"workspace:{project}", principal=fixture["principal"], idempotency_key=f"policy:{mode}", trace_id="trace:policy", correlation_id="policy")
            if mode == "REVIEW_PLAN":
                with AuthorityUnitOfWork(DATABASE_URL) as uow:
                    BookControlRepository(uow.cursor).freeze(project_id=project, book_run_id=fixture["book"].book_run_id, chapter_number=1, actor_id=fixture["principal"].principal_id)
                    uow.commit()
        configuration = query.author_workspace(project_id=project, book_id=book_id)
        self.assertEqual(configuration["editorial_control"]["policy"]["mode"], "REVIEW_CHAPTER")
        self.assertEqual(configuration["runs"][0]["frozen_editorial_control"]["policy"]["mode"], "REVIEW_PLAN")
        with self.assertRaisesRegex(KernelError, "BOOK_NOT_FOUND"):
            query.author_workspace(project_id=identifier("other-project"), book_id=book_id)

    def test_book_chapter_dispatch_idempotency(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        command = self._chapter_command(fixture, chapter_number=1)
        first = fixture["authority"].submit_chapter(
            command, principal=fixture["principal"]
        )
        second = fixture["authority"].submit_chapter(
            command, principal=fixture["principal"]
        )
        self.assertEqual(
            first["chapter_root_operation_id"],
            second["chapter_root_operation_id"],
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT child_root_operation_id)
                FROM authority_child_delegation
                WHERE project_id=%s
                """,
                [fixture["project_id"]],
            )
            self.assertEqual(uow.cursor.fetchone(), (1, 1))

    def test_book_pause_blocks_new_child(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        fixture["authority"].pause(
            fixture["book"].book_run_id,
            reason="operator gate",
            principal=fixture["principal"],
        )
        with self.assertRaisesRegex(KernelError, "BOOK_CHAPTER_SUBMISSION_NOT_READY"):
            fixture["authority"].submit_chapter(
                self._chapter_command(fixture, chapter_number=1),
                principal=fixture["principal"],
            )

    def test_book_mutations_are_transaction_commands_with_business_events(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        fixture["authority"].pause(
            fixture["book"].book_run_id,
            reason="command boundary proof",
            principal=fixture["principal"],
        )
        fixture["authority"].resume(
            fixture["book"].book_run_id,
            reason="command boundary proof",
            principal=fixture["principal"],
        )

        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation
                WHERE project_id=%s
                  AND definition_name='book.authority.mutate'
                  AND status='SUCCEEDED'
                """,
                [fixture["project_id"]],
            )
            commands = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT event_type
                FROM state_event
                WHERE project_id=%s
                  AND event_type IN (
                    'book.production.started',
                    'book.production.paused',
                    'book.production.resumed'
                  )
                """,
                [fixture["project_id"]],
            )
            events = {str(row[0]) for row in uow.cursor.fetchall()}
        self.assertEqual(commands, 3)
        self.assertEqual(
            events,
            {
                "book.production.started",
                "book.production.paused",
                "book.production.resumed",
            },
        )

    def test_book_accept_requires_all_evidence(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=1)
        delegated = fixture["authority"].submit_chapter(
            self._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        with self.assertRaisesRegex(KernelError, "BOOK_CHAPTER_ACCEPTANCE_NOT_READY"):
            fixture["authority"].accept_chapter(
                delegated["chapter_request_id"],
                principal=fixture["principal"],
            )
        self.assertEqual(
            fixture["authority"].require(fixture["book"].book_run_id)[
                "accepted_through_chapter"
            ],
            0,
        )

    def test_book_resume_reconciles_existing_child(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=1)
        delegated = fixture["authority"].submit_chapter(
            self._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        fixture["authority"].pause(
            fixture["book"].book_run_id,
            reason="pause while child runs",
            principal=fixture["principal"],
        )
        self._run_child(fixture, delegated["chapter_root_operation_id"])
        resumed = fixture["authority"].resume(
            fixture["book"].book_run_id,
            reason="resume and reconcile",
            principal=fixture["principal"],
        )
        self.assertEqual(resumed["state"], "CHAPTER_COMPLETED")

    def test_book_cancel_propagates_to_child(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        delegated = fixture["authority"].submit_chapter(
            self._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        cancelled = fixture["authority"].cancel(
            fixture["book"].book_run_id,
            reason="operator cancelled Book",
            principal=fixture["principal"],
        )
        child = fixture["chapter"].query.require_run(
            project_id=fixture["project_id"],
            root_operation_id=delegated["chapter_root_operation_id"],
        )
        self.assertEqual(cancelled["state"], "ABORTED")
        self.assertIn(child["status"], {"CANCELLATION_REQUESTED", "CANCELLED"})

    def test_book_cancel_preserves_successful_unaccepted_child(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        delegated = fixture["authority"].submit_chapter(
            self._chapter_command(fixture, chapter_number=1), principal=fixture["principal"])
        self._run_child(fixture, delegated["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
        stopped = fixture["authority"].cancel(fixture["book"].book_run_id,
            reason="retain candidate without acceptance", principal=fixture["principal"])
        self.assertEqual(stopped["state"], "ABORTED")
        self.assertEqual(stopped["accepted_through_chapter"], 0)
        child = fixture["chapter"].query.require_run(project_id=fixture["project_id"],
            root_operation_id=delegated["chapter_root_operation_id"])
        self.assertEqual(child["status"], "SUCCEEDED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT status FROM authority_child_delegation WHERE chapter_request_id=%s",
                [delegated["chapter_request_id"]])
            self.assertEqual(uow.cursor.fetchone()[0], "SUCCEEDED")
        replay = fixture["authority"].cancel(fixture["book"].book_run_id,
            reason="retain candidate without acceptance", principal=fixture["principal"])
        self.assertEqual(replay["version"], stopped["version"])

    def test_book_cancel_preserves_accepted_chapter_history(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=2)
        delegated = fixture["authority"].submit_chapter(self._chapter_command(fixture, chapter_number=1), principal=fixture["principal"])
        self._run_child(fixture, delegated["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
        accepted = fixture["authority"].accept_chapter(delegated["chapter_request_id"], principal=fixture["principal"])
        stopped = fixture["authority"].cancel(fixture["book"].book_run_id, reason="stop after accepted chapter", principal=fixture["principal"])
        self.assertEqual(stopped["state"], "ABORTED")
        self.assertEqual(stopped["accepted_through_chapter"], 1)
        self.assertEqual(stopped["last_chapter_outcome_version_id"], accepted["last_chapter_outcome_version_id"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT status FROM authority_child_delegation WHERE chapter_request_id=%s", [delegated["chapter_request_id"]])
            self.assertEqual(uow.cursor.fetchone()[0], "ACCEPTED")
            uow.cursor.execute("SELECT status FROM authority_book_chapter_acceptance WHERE chapter_request_id=%s", [delegated["chapter_request_id"]])
            self.assertEqual(uow.cursor.fetchone()[0], "COMMITTED")

    def test_book_reconcile_after_worker_restart(self) -> None:
        failure = {"enabled": True}

        def inject(point: str) -> None:
            if failure["enabled"] and point == "before_delegation_persist":
                raise RuntimeError("injected crash before delegation persist")

        fixture = self._new_book_fixture(
            target_chapter_count=1, failure_injector=inject
        )
        with self.assertRaisesRegex(RuntimeError, "injected crash"):
            fixture["authority"].submit_chapter(
                self._chapter_command(fixture, chapter_number=1),
                principal=fixture["principal"],
            )
        failure["enabled"] = False
        request_id = next(
            item["chapter_request_id"]
            for item in self._chapter_requests(fixture["project_id"])
        )
        recovered = fixture["authority"].recover_chapter_submission(
            request_id, principal=fixture["principal"]
        )
        self.assertTrue(recovered["chapter_root_operation_id"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation
                WHERE project_id=%s AND definition_name='chapter.slice.run'
                """,
                [fixture["project_id"]],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 1)

    def test_book_cursor_advances_once(self) -> None:
        failure = {"enabled": True}

        def inject(point: str) -> None:
            if failure["enabled"] and point == "after_acceptance_before_cursor":
                raise RuntimeError("injected crash inside acceptance transaction")

        fixture = self._new_book_fixture(
            target_chapter_count=1, failure_injector=inject
        )
        delegated = fixture["authority"].submit_chapter(
            self._chapter_command(fixture, chapter_number=1),
            principal=fixture["principal"],
        )
        self._run_child(fixture, delegated["chapter_root_operation_id"])
        fixture["authority"].reconcile_chapter(delegated["chapter_request_id"])
        with self.assertRaisesRegex(RuntimeError, "acceptance transaction"):
            fixture["authority"].accept_chapter(
                delegated["chapter_request_id"],
                principal=fixture["principal"],
            )
        self.assertEqual(
            fixture["authority"].require(fixture["book"].book_run_id)[
                "accepted_through_chapter"
            ],
            0,
        )
        failure["enabled"] = False
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute("SELECT COUNT(*) FROM authority_narrative_reality_revision WHERE book_run_id=%s", [fixture["book"].book_run_id])
            self.assertEqual(uow.cursor.fetchone()[0], 0)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as workers:
            concurrent = list(workers.map(lambda _: fixture["authority"].accept_chapter(delegated["chapter_request_id"], principal=fixture["principal"]), range(2)))
        accepted = concurrent[0]
        self.assertTrue(all(item["accepted_through_chapter"] == 1 for item in concurrent))
        replay = fixture["authority"].accept_chapter(
            delegated["chapter_request_id"],
            principal=fixture["principal"],
        )
        self.assertEqual(accepted["accepted_through_chapter"], 1)
        self.assertEqual(replay["accepted_through_chapter"], 1)
        from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            chain = NarrativeRealityRepository(uow.cursor).verify_replay(book_run_id=fixture["book"].book_run_id)
            self.assertEqual(chain["accepted_count"], 1)

    def test_book_does_not_precreate_all_chapters(self) -> None:
        fixture = self._new_book_fixture(target_chapter_count=100)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*) FROM authority_operation
                WHERE project_id=%s AND definition_name='chapter.slice.run'
                """,
                [fixture["project_id"]],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 0)

    def _new_book_fixture(
        self,
        *,
        target_chapter_count: int,
        failure_injector=None,
    ) -> dict[str, object]:
        project_id = identifier("book-authority-control")
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        settings = IndustrialSettings(
            root=Path(root.name),
            environment="test",
            storage_authority="postgresql",
            database_url=DATABASE_URL,
        )
        env = {
            "NOVEL_FORGE_ENVIRONMENT": "test",
            "NOVEL_FORGE_COMMIT_SHA": "e" * 40,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(Path(root.name) / "objects"),
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "book-control-pep-worker",
        }
        execution = build_production_execution_composition(settings, env=env)
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        followup = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="book-authority-control",
            commit_sha="e" * 40,
            model_port=build_reader_outcome_model_port(
                settings, execution=execution, env=env
            ),
            worker_id="book-control-followup-worker",
        )
        authority = PostgresBookAuthority(
            DATABASE_URL,
            chapter_port=ChapterAuthorityCommandAdapter(
                chapter,
                external_effect_adapters=execution.external_effect_adapters,
            ),
            followup_application=followup,
            application_build_id="book-authority-control",
            commit_sha="e" * 40,
            failure_injector=failure_injector,
            legacy_fixture_input_allowed=True,
        )
        principal = self._principal(project_id)
        worker = Principal(
            principal_id="book-control-worker",
            principal_type=PrincipalType.WORKER,
            permissions=frozenset(
                {"chapter.authority.execute", "external_effect.execute"}
            ),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )
        candidates = list(
            chapter_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(project_id, current_state_contract=True)
        )
        self._seed_two_chapter_plans(project_id, candidates)
        versions = self._seed_book_inputs(project_id)
        book = authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                book_id=f"book:{project_id}",
                actor_id=principal.principal_id,
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                stable_idempotency_key=f"{project_id}:book:v1",
                book_design_version=versions.pop("book_design_version"),
                book_plan_version=versions.pop("book_plan_version"),
                production_profile_version="production-profile:v1",
                longform_context_versions=versions,
                target_chapter_count=target_chapter_count,
                input_mode="LEGACY_FIXTURE_INPUT_MODE",
            ),
            principal=principal,
        )
        return {
            "project_id": project_id,
            "chapter": chapter,
            "authority": authority,
            "principal": principal,
            "worker": worker,
            "candidates": candidates,
            "book": book,
        }

    def _chapter_command(
        self, fixture: dict[str, object], *, chapter_number: int
    ) -> SubmitBookChapterCommand:
        candidates = fixture["candidates"]
        plan = next(item for item in candidates if item["asset_type"] == "chapter_plan")
        return SubmitBookChapterCommand(
                context_token_budget=64_000,
            book_run_id=fixture["book"].book_run_id,
            chapter_number=chapter_number,
            title=f"Chapter {chapter_number}",
            premise="A decision creates an irreversible cost.",
            chapter_plan_asset_version_id=str(plan["asset_version_id"]),
            chapter_plan_content_hash=str(plan["content_hash"]),
            context_candidates=tuple(candidates),
        )

    @staticmethod
    def _run_child(fixture: dict[str, object], root_operation_id: str) -> None:
        for _ in range(len(ChapterNode) * 2 + 4):
            tick = (
                fixture["chapter"]
                .scheduler(principal=fixture["worker"])
                .tick(
                    project_id=fixture["project_id"],
                    root_operation_id=root_operation_id,
                )
            )
            if tick.saga_status == "SUCCEEDED":
                return
        raise AssertionError("Chapter Saga did not reach SUCCEEDED")

    @staticmethod
    def _chapter_requests(project_id: str) -> list[dict[str, str]]:
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT chapter_request_id
                FROM authority_book_chapter_request
                WHERE project_id=%s
                """,
                [project_id],
            )
            return [
                {"chapter_request_id": str(row[0])} for row in uow.cursor.fetchall()
            ]

    @staticmethod
    def _principal(project_id: str) -> Principal:
        return Principal(
            principal_id="book-authority-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "book.authority.execute",
                    "book.followup:*",
                    "chapter.authority.execute",
                }
            ),
            project_scope=frozenset({project_id}),
            authentication_source="integration-test",
        )

    @staticmethod
    def _seed_two_chapter_plans(
        project_id: str,
        candidates: list[dict[str, object]],
        *,
        canonical_execution: bool = False,
        plan_transform=None,
    ) -> dict[int, dict[str, object]]:
        first = next(
            dict(item) for item in candidates if item["asset_type"] == "chapter_plan"
        )
        if canonical_execution:
            first_content = {
                **dict(first["content"]),
                "narrative_architecture_version": "canonical-narrative-v1",
                "narrative_segment_ref": {
                    "volume_plan_version_id": "volume-plan:v1",
                    "segment_id": "narrative-segment:1",
                },
                "chapter_intent": "Turn denial into a witnessed commitment.",
                "arc_schedule": [
                    {
                        "arc_plan_version_id": f"{project_id}:fixture-arc-plan-v1",
                        "role": "PRIMARY",
                        "segment_id": "arc-segment:1",
                        "expected_movement": "denial becomes commitment",
                    }
                ],
                "setups": [],
                "payoffs": [],
                "character_participation": [
                    {
                        "character_id": "protagonist",
                        "goal": "protect the witness",
                        "trajectory_refs": ["character-arc:accountability"],
                        "known_fact_ids": [],
                        "unknown_fact_ids": ["fact:hidden-cost"],
                        "belief_refs": ["belief:safety-through-silence"],
                        "expected_change": "accept public accountability",
                        "causal_trigger": "the safe route closes",
                        "entry_emotion": "defensive fear",
                        "exit_emotion": "costly resolve",
                        "resource_changes": ["safety decreases"],
                        "relationship_changes": ["witness trust increases"],
                    }
                ],
                "knowledge_boundaries": [
                    {
                        "layer": "READER_KNOWLEDGE",
                        "subject_id": "reader",
                        "fact_id": "fact:hidden-cost",
                        "status": "HINTED",
                    }
                ],
                "disclosures": [
                    {
                        "disclosure_id": "disclosure:hidden-cost:hint",
                        "fact_id": "fact:hidden-cost",
                        "audience": "READER",
                        "mode": "HINT",
                        "presentation_channel": "CONSEQUENCE",
                    }
                ],
                "required_state_transitions": [
                    {
                        "state_kind": "character_arc",
                        "entity_key": "protagonist:accountability",
                        "from_state": "DENIAL",
                        "to_state": "COMMITTED",
                    }
                ],
                "reader_experience": {
                    "entry_question": "Will the protagonist stay silent?",
                    "target_emotion": "costly relief",
                    "exit_question": "Who will exploit the choice?",
                },
                "scene_plan": [
                    {
                        "scene_id": "chapter:1:scene:1",
                        "scene_group_id": "chapter:1:group:1",
                        "goal": "make the choice unavoidable",
                        "conflict": "silence endangers the witness",
                        "participants": ["protagonist"],
                        "arc_progress": [f"{project_id}:fixture-arc-plan-v1"],
                        "information_gain": ["fact:hidden-cost"],
                        "state_transitions": ["protagonist:accountability"],
                        "entry_state": "private denial",
                        "exit_state": "public commitment",
                        "reader_effect": "relief becomes anticipation",
                        "beats": ["pressure", "choice", "cost"],
                    }
                ],
                "expected_exit_state": {
                    "summary": "The protagonist is publicly committed."
                },
            }
            if plan_transform is not None:
                first_content = plan_transform(first_content)
            first_hash = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        first_content, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
            )
            first = {
                **first,
                "asset_version_id": f"{project_id}:canonical-chapter-plan-v1",
                "content_hash": first_hash,
                "content": first_content,
            }
        second_content = {
            **dict(first["content"]),
            "chapter": 2,
            "title": "The Debt Compounds",
            "chapter_objective": "Escalate the cost created by chapter one.",
        }
        if second_content.get("narrative_realization_slice"):
            second_content["narrative_realization_slice"] = {
                **second_content["narrative_realization_slice"], "chapter_number": 2
            }
        if canonical_execution:
            second_content.update(
                {
                    "chapter_intent": "Turn commitment into an irreversible consequence.",
                    "character_participation": [
                        {
                            **second_content["character_participation"][0],
                            "expected_change": "accept the consequence of accountability",
                            "entry_emotion": "costly resolve",
                            "exit_emotion": "sober determination",
                        }
                    ],
                    "knowledge_boundaries": [
                        {
                            "layer": "READER_KNOWLEDGE",
                            "subject_id": "reader",
                            "fact_id": "fact:hidden-cost",
                            "status": "KNOWN",
                        }
                    ],
                    "disclosures": [
                        {
                            "disclosure_id": "disclosure:hidden-cost:confirm",
                            "fact_id": "fact:hidden-cost",
                            "audience": "READER",
                            "mode": "CONFIRM",
                            "presentation_channel": "CONSEQUENCE",
                        }
                    ],
                    "required_state_transitions": [
                        {
                            "state_kind": "character_arc",
                            "entity_key": "protagonist:accountability",
                            "from_state": "COMMITTED",
                            "to_state": "CONSEQUENT",
                        }
                    ],
                    "scene_plan": [
                        {
                            **second_content["scene_plan"][0],
                            "scene_id": "chapter:2:scene:1",
                            "scene_group_id": "chapter:2:group:1",
                            "entry_state": "public commitment",
                            "exit_state": "irreversible consequence",
                        }
                    ],
                    "expected_exit_state": {
                        "summary": "The commitment now carries an irreversible consequence."
                    },
                }
            )
        if plan_transform is not None:
            second_content = plan_transform(second_content)
        second_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    second_content, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        )
        second = {
            **first,
            "asset_version_id": f"{project_id}:chapter-plan-v2",
            "content_hash": second_hash,
            "content": second_content,
        }
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            if canonical_execution:
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset(asset_id, project_id, asset_type)
                    VALUES (%s, %s, 'chapter_plan')
                    """,
                    [f"{project_id}:canonical-chapter-plan-1", project_id],
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'chapter-plan.v4')
                    """,
                    [
                        first["asset_version_id"],
                        f"{project_id}:canonical-chapter-plan-1",
                        json.dumps(first["content"]),
                        first["content_hash"],
                    ],
                )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, 'chapter_plan')
                """,
                [f"{project_id}:chapter-plan-2", project_id],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, %s)
                """,
                [
                    second["asset_version_id"],
                    f"{project_id}:chapter-plan-2",
                    json.dumps(second_content),
                    second_hash,
                    (
                        "chapter-plan.v4"
                        if canonical_execution
                        else "integration-fixture.v1"
                    ),
                ],
            )
            uow.commit()
        return {1: first, 2: second}

    @staticmethod
    def _seed_book_inputs(
        project_id: str, *, scope_already_seeded: bool = False
    ) -> dict[str, Any]:
        if not scope_already_seeded:
            seed_authority_project_book(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                book_id=f"book:{project_id}",
            )
        types = {
            "book_design_version": "book_design",
            "book_plan_version": "book_plan",
            "volume_plan_version": "volume_plan",
            "arc_plan_versions": "arc_plan",
            "character_state_version": "character_state",
            "foreshadowing_state_version": "foreshadowing_state",
            "quality_trend_version": "quality_trend",
            "reward_ledger_version": "reward_ledger",
            "promise_ledger_version": "reader_promise_ledger",
            "reader_segment_version": "reader_segment_profile",
            "reader_contract_version": "reader_contract",
            "platform_profile_version": "platform_profile",
        }
        versions: dict[str, Any] = {}
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for key, asset_type in types.items():
                version_id = (
                    f"{project_id}:fixture-arc-plan-v1"
                    if key == "arc_plan_versions"
                    else f"{project_id}:{asset_type}:v1"
                )
                asset_id = f"{version_id}:asset"
                content = {
                    "contract_version": f"{asset_type}-fixture-v1",
                    "safe_summary": f"Frozen {asset_type} fixture.",
                }
                content_hash = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            content, sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset(asset_id, project_id, asset_type)
                    VALUES (%s, %s, %s)
                    """,
                    [asset_id, project_id, asset_type],
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (
                        %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s, 'integration-fixture.v1'
                    )
                    """,
                    [version_id, asset_id, json.dumps(content), content_hash],
                )
                uow.cursor.execute(
                    """
                    INSERT INTO authority_asset_qualification(
                        qualification_id, asset_version_id, policy_version,
                        decision, evidence
                    ) VALUES (%s, %s, 'book-input-fixture-v1',
                              'ELIGIBLE', '{}'::jsonb)
                    """,
                    [f"{version_id}:qualification", version_id],
                )
                versions[key] = (
                    [version_id] if key == "arc_plan_versions" else version_id
                )
            uow.commit()
        return versions


if __name__ == "__main__":
    unittest.main()
