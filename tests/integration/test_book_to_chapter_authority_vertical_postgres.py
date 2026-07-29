from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.api.authority_dependencies import build_chapter_authority_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.production import (
    PostgresBookAuthority,
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_authority.governed_scheduler import (
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.book_followup_authority.query import (
    BookFollowupProjectionQuery,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSagaAdmission,
    SingleChapterRequest,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
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


class BookToChapterAuthorityVerticalPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_book_chapter_reader_outcome_recap_and_checkpoint_are_one_governed_chain(
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
            chapter = build_chapter_authority_application(settings, env=env)
            followup = BookFollowupAuthorityApplication(
                DATABASE_URL,
                application_build_id="book-chapter-vertical",
                commit_sha="e" * 40,
                model_port=chapter.model_port,
                worker_id="book-followup-vertical-worker",
            )
            port = _SynchronousCommandPort(chapter)
            authority = PostgresBookAuthority(
                DATABASE_URL,
                chapter_port=port,
                followup_application=followup,
                application_build_id="book-chapter-vertical",
                commit_sha="e" * 40,
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
            candidates = chapter_fixture.PostgreSQLOnlyChapterSliceTests.release_evidence(
                project_id
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
                    book_design_version=longform_versions.pop(
                        "book_design_version"
                    ),
                    book_plan_version=longform_versions.pop("book_plan_version"),
                    production_profile_version="production-profile:v1",
                    longform_context_versions=longform_versions,
                    target_chapter_count=1,
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
                authority, principal=principal
            )
            reader_tick = scheduler.tick(book.book_run_id)
            recap_tick = scheduler.tick(book.book_run_id)
            final_tick = scheduler.tick(book.book_run_id)
            final = authority.require(book.book_run_id)

            self.assertEqual(final["state"], "COMPLETED")
            self.assertEqual(final["current_chapter"], 1)
            self.assertEqual(reader_tick.action, "SUBMIT_READER_OUTCOME")
            self.assertEqual(recap_tick.action, "SUBMIT_LONGFORM_RECAP")
            self.assertEqual(final_tick.action, "COMPLETE_LONGFORM_RECAP")
            query = BookFollowupProjectionQuery(DATABASE_URL)
            reader_projection = query.reader_outcome(
                project_id=project_id, operation_id=reader_tick.operation_id
            )
            recap_projection = query.longform_recap(
                project_id=project_id, operation_id=recap_tick.operation_id
            )
            self.assertEqual(reader_projection["content"]["gate"], "PASS")
            self.assertFalse(recap_projection["content"]["plan_mutation_allowed"])
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
                    SELECT COUNT(*) FROM authority_external_effect
                    WHERE operation_id=%s AND capability='model.reader_outcome'
                    """,
                    [reader_tick.operation_id],
                )
                reader_effects = int(uow.cursor.fetchone()[0])
                uow.cursor.execute(
                    """
                    SELECT operation.definition_name,
                           jsonb_array_length(operation.input_asset_snapshot)
                    FROM authority_operation AS operation
                    WHERE operation.operation_id = ANY(%s)
                    ORDER BY operation.definition_name
                    """,
                    [
                        [
                            book.root_operation_id,
                            reader_tick.operation_id,
                            recap_tick.operation_id,
                        ]
                    ],
                )
                frozen_input_counts = dict(uow.cursor.fetchall())
            self.assertEqual(terminal, ("SUCCEEDED", "SUCCEEDED"))
            self.assertEqual(reader_effects, 1)
            self.assertEqual(
                frozen_input_counts,
                {
                    "book.production.coordinate": 9,
                    "longform.recap": 11,
                    "reader_outcome.evaluate": 4,
                },
            )

            blocked_book = authority.start(
                StartBookProductionCommand(
                    project_id=project_id,
                    workspace_id=f"workspace:{project_id}",
                    book_id=f"book:{project_id}:sequential-guard",
                    actor_id=principal.principal_id,
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                    stable_idempotency_key=f"{project_id}:book:guard:v1",
                    book_design_version=final["book_design_version"],
                    book_plan_version=final["book_plan_version"],
                    production_profile_version="production-profile:v1",
                    longform_context_versions=dict(
                        final["longform_context_versions"]
                    ),
                    target_chapter_count=2,
                ),
                principal=principal,
            )
            with self.assertRaisesRegex(
                KernelError, "BOOK_CHAPTER_SUBMISSION_NOT_READY"
            ):
                authority.submit_chapter(
                    SubmitBookChapterCommand(
                        book_run_id=blocked_book.book_run_id,
                        chapter_number=2,
                        title="Out of order",
                        premise="This must never reach Chapter Authority.",
                        chapter_plan_asset_version_id=str(
                            plan["asset_version_id"]
                        ),
                        chapter_plan_content_hash=str(plan["content_hash"]),
                        context_candidates=tuple(candidates),
                    ),
                    principal=principal,
                )

    @staticmethod
    def _seed_book_inputs(project_id: str) -> dict[str, str]:
        types = {
            "book_design_version": "book_design",
            "book_plan_version": "book_plan",
            "volume_plan_version": "volume_plan",
            "arc_plan_version": "arc_plan",
            "character_state_version": "character_state",
            "foreshadowing_state_version": "foreshadowing_state",
            "quality_trend_version": "quality_trend",
            "reward_ledger_version": "reward_ledger",
            "promise_ledger_version": "reader_promise_ledger",
        }
        versions: dict[str, str] = {}
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for key, asset_type in types.items():
                version_id = f"{project_id}:{asset_type}:v1"
                asset_id = f"{version_id}:asset"
                content = {
                    "contract_version": f"{asset_type}-fixture-v1",
                    "safe_summary": f"Frozen {asset_type} fixture.",
                }
                content_hash = "sha256:" + hashlib.sha256(
                    json.dumps(
                        content, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
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
                        eligibility, governance, content, content_hash
                    ) VALUES (
                        %s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s
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
                versions[key] = version_id
            uow.commit()
        return versions


if __name__ == "__main__":
    unittest.main()
