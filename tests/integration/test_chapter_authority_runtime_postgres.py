from __future__ import annotations

import unittest

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_SLICE_DEFINITION_VERSION,
    chapter_operation_definitions,
)
from novel_forge.modules.chapter_authority.runtime import execute_chapter_handler
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    transaction,
)


class _PlanHandler:
    def execute(self, request):  # type: ignore[no-untyped-def]
        return ChapterHandlerOutput(
            asset_type="chapter_plan",
            output_key="chapter.plan",
            role="primary",
            content={
                "chapter": request.command["chapter"],
                "objective": request.command["premise"],
                "trace_id": request.trace_id,
            },
        )


class ChapterAuthorityRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_fenced_handler_materializes_one_replayable_authoritative_output(self) -> None:
        project_id = identifier("project")
        definitions = chapter_operation_definitions(
            application_build_id="chapter-runtime-test",
            commit_sha="b" * 40,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()
        admission = AdmissionContext(
            actor_id="chapter-worker",
            permissions=frozenset({"chapter.authority.execute"}),
            available_handlers=frozenset(item["handler_key"] for item in definitions),
            application_build_id="chapter-runtime-test",
            commit_sha="b" * 40,
        )
        operation_id = admit_command(
            DATABASE_URL,
            {
                "definition_name": ChapterNode.PLAN.definition_name,
                "definition_version": CHAPTER_SLICE_DEFINITION_VERSION,
                "project_id": project_id,
                "workspace_id": f"workspace:{project_id}",
                "actor_id": admission.actor_id,
                "idempotency_scope": "project:chapter-slice",
                "idempotency_key": f"{project_id}:chapter:1:plan",
                "trace_id": identifier("trace"),
                "span_id": identifier("span"),
                "correlation_id": identifier("correlation"),
                "causation_id": "",
                "input": {"chapter": 1, "premise": "A promise becomes a cost"},
                "input_assets": [],
            },
            context=admission,
        )["operation_id"]
        transition_operation(
            DATABASE_URL,
            OperationTransitionCommand(
                operation_id=operation_id,
                project_id=project_id,
                expected_version=0,
                expected_status="ADMITTED",
                target_status="READY",
                actor_id="chapter-coordinator",
                reason="unit node is ready",
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
                causation_id="",
            ),
        )
        attempt_id = create_attempt(
            DATABASE_URL,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )["attempt_id"]
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="chapter-worker",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="chapter-worker",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, worker)
        registry = ChapterHandlerRegistry()
        registry.register(ChapterNode.PLAN, _PlanHandler())

        created = execute_chapter_handler(
            DATABASE_URL,
            command=worker,
            node=ChapterNode.PLAN,
            registry=registry,
        )
        replay = execute_chapter_handler(
            DATABASE_URL,
            command=worker,
            node=ChapterNode.PLAN,
            registry=registry,
        )

        self.assertFalse(created.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(created.asset_version_id, replay.asset_version_id)
        self.assertEqual(created.content_hash, replay.content_hash)
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT asset.asset_type, version.lifecycle, version.eligibility,
                       version.governance, qualification.decision, binding.output_key,
                       binding.role, COUNT(*) OVER ()
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset ON asset.asset_id = binding.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = binding.asset_version_id
                JOIN authority_asset_qualification AS qualification
                  ON qualification.asset_version_id = version.asset_version_id
                WHERE binding.operation_id = %s
                """,
                [operation_id],
            )
            self.assertEqual(
                cursor.fetchone(),
                (
                    "chapter_plan",
                    "ACTIVE",
                    "ELIGIBLE",
                    "CLEAR",
                    "ELIGIBLE",
                    "chapter.plan",
                    "primary",
                    1,
                ),
            )
            cursor.execute(
                "SELECT COUNT(*) FROM audit_log WHERE operation_id = %s AND action = %s",
                [operation_id, ChapterNode.PLAN.completion_topic],
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT COUNT(*) FROM outbox_event WHERE project_id = %s AND topic = %s",
                [project_id, ChapterNode.PLAN.completion_topic],
            )
            self.assertEqual(cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
