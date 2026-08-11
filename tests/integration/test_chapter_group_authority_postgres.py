from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
    build_reader_outcome_model_port,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority.governed_scheduler import (
    PostgresBookAuthorityScheduler,
)
from novel_forge.modules.book_authority.production import (
    ChapterAuthorityCommandAdapter,
    PostgresBookAuthority,
    StartBookProductionCommand,
    SubmitBookChapterCommand,
)
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAuthorityApplication,
)
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.chapter_group_authority import (
    PostgresChapterGroupAuthority,
    StartChapterGroupCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration import (
    test_postgresql_only_chapter_slice as chapter_fixture,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration.test_book_to_chapter_authority_vertical_postgres import (
    BookToChapterAuthorityVerticalPostgresTests,
)


class ChapterGroupAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_chapter_group_three_chapter_vertical_and_rolling_horizon(
        self,
    ) -> None:
        fixture = self._fixture()
        group_authority = fixture["group_authority"]
        principal = fixture["principal"]
        group = group_authority.start(
            StartChapterGroupCommand(
                project_id=fixture["project_id"],
                workspace_id=f"workspace:{fixture['project_id']}",
                actor_id=principal.principal_id,
                trace_id=identifier("group-trace"),
                correlation_id=fixture["book"].root_operation_id,
                stable_idempotency_key=(
                    f"{fixture['project_id']}:group:1:v1"
                ),
                book_run_id=fixture["book"].book_run_id,
                group_plan_version_id=fixture["group_plan"][
                    "asset_version_id"
                ],
                group_plan_content_hash=fixture["group_plan"][
                    "content_hash"
                ],
            ),
            principal=principal,
        )
        paused = group_authority.pause(
            group["group_run_id"],
            reason="operator checkpoint",
            principal=principal,
        )
        self.assertEqual(paused["state"], "PAUSED")
        with self.assertRaisesRegex(
            KernelError, "CHAPTER_GROUP_DISPATCH_NOT_READY"
        ):
            group_authority.dispatch(
                group["group_run_id"],
                self._chapter_command(fixture, 1),
                principal=principal,
            )
        resumed = group_authority.resume(
            group["group_run_id"],
            reason="checkpoint cleared",
            principal=principal,
        )
        self.assertEqual(resumed["state"], "READY")

        scheduler = PostgresBookAuthorityScheduler(
            fixture["book_authority"], principal=principal
        )
        for chapter_number in (1, 2, 3):
            running = group_authority.dispatch(
                group["group_run_id"],
                self._chapter_command(fixture, chapter_number),
                principal=principal,
            )
            self.assertEqual(running["state"], "CHAPTER_RUNNING")
            with self.assertRaisesRegex(
                KernelError, "CHAPTER_GROUP_DISPATCH_NOT_READY"
            ):
                group_authority.dispatch(
                    group["group_run_id"],
                    self._chapter_command(
                        fixture, min(3, chapter_number + 1)
                    ),
                    principal=principal,
                )
            request = fixture["book_authority"].require_chapter_request(
                str(running["active_chapter_request_id"])
            )
            self._run_child(
                fixture,
                str(request["chapter_root_operation_id"]),
            )
            accepted = group_authority.reconcile_and_accept(
                group["group_run_id"], principal=principal
            )
            self.assertEqual(
                int(accepted["accepted_through_chapter"]),
                chapter_number,
            )
            scheduler.tick(fixture["book"].book_run_id)
            scheduler.tick(fixture["book"].book_run_id)
            if chapter_number == 3:
                scheduler.tick(fixture["book"].book_run_id)
                scheduler.tick(fixture["book"].book_run_id)

        closed = group_authority.close(
            group["group_run_id"], principal=principal
        )
        self.assertEqual(closed["state"], "COMPLETED")
        self.assertTrue(closed["recap_operation_id"])
        self.assertTrue(closed["plan_adjustment_proposal_version_id"])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT chapter_request_id),
                       COUNT(DISTINCT child_root_operation_id)
                FROM authority_chapter_group_chapter
                WHERE group_run_id=%s AND status='ACCEPTED'
                """,
                [group["group_run_id"]],
            )
            accepted_counts = tuple(
                int(value) for value in uow.cursor.fetchone()
            )
            uow.cursor.execute(
                """
                SELECT executed_through_chapter,
                       frozen_through_chapter,
                       planned_through_chapter,
                       speculative_through_chapter,
                       status
                FROM planning_horizon
                WHERE project_id=%s AND book_id=%s
                """,
                [fixture["project_id"], fixture["book_id"]],
            )
            horizon = uow.cursor.fetchone()
            uow.cursor.execute(
                """
                SELECT content
                FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [closed["plan_adjustment_proposal_version_id"]],
            )
            proposal = dict(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_operation
                WHERE root_operation_id=%s
                  AND definition_name LIKE %s
                """,
                [group["root_operation_id"], "chapter_group.%"],
            )
            step_count = int(uow.cursor.fetchone()[0])
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset
                  ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND asset.asset_type='chapter_outcome'
                  AND version.content->>'parent_group_version_id'=%s
                """,
                [
                    fixture["project_id"],
                    fixture["group_plan"]["asset_version_id"],
                ],
            )
            group_bound_outcomes = int(uow.cursor.fetchone()[0])
        self.assertEqual(accepted_counts, (3, 3, 3))
        self.assertEqual(tuple(horizon), (3, 3, 10, 23, "CURRENT"))
        self.assertFalse(proposal["active_plan_mutation_allowed"])
        self.assertTrue(proposal["authority_decision_required"])
        self.assertGreaterEqual(step_count, 16)
        self.assertEqual(group_bound_outcomes, 3)

    def test_group_cancel_propagates_to_active_child(self) -> None:
        fixture = self._fixture()
        group = fixture["group_authority"].start(
            StartChapterGroupCommand(
                project_id=fixture["project_id"],
                workspace_id=f"workspace:{fixture['project_id']}",
                actor_id=fixture["principal"].principal_id,
                trace_id=identifier("group-cancel-trace"),
                correlation_id=fixture["book"].root_operation_id,
                stable_idempotency_key=(
                    f"{fixture['project_id']}:group:cancel:v1"
                ),
                book_run_id=fixture["book"].book_run_id,
                group_plan_version_id=fixture["group_plan"][
                    "asset_version_id"
                ],
                group_plan_content_hash=fixture["group_plan"][
                    "content_hash"
                ],
            ),
            principal=fixture["principal"],
        )
        fixture["group_authority"].dispatch(
            group["group_run_id"],
            self._chapter_command(fixture, 1),
            principal=fixture["principal"],
        )
        cancelled = fixture["group_authority"].cancel(
            group["group_run_id"],
            reason="operator cancelled group",
            principal=fixture["principal"],
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT operation.status, delegation.status
                FROM authority_chapter_group_chapter AS child
                JOIN authority_operation AS operation
                  ON operation.operation_id=child.child_root_operation_id
                JOIN authority_child_delegation AS delegation
                  ON delegation.delegation_id=child.child_delegation_id
                WHERE child.group_run_id=%s
                """,
                [group["group_run_id"]],
            )
            child = uow.cursor.fetchone()
        self.assertEqual(cancelled["state"], "ABORTED")
        self.assertEqual(str(child[0]), "CANCELLATION_REQUESTED")
        self.assertEqual(str(child[1]), "CANCELLATION_REQUESTED")

    def _fixture(self) -> dict:
        project_id = identifier("chapter-group")
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
            "NOVEL_FORGE_COMMIT_SHA": "f" * 40,
            "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
            "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(
                Path(root.name) / "objects"
            ),
            "NOVEL_FORGE_AUTHORITY_WORKER_ID": "group-chapter-worker",
        }
        execution = build_production_execution_composition(settings, env=env)
        chapter = build_chapter_authority_application(
            settings, execution=execution, env=env
        )
        followup = BookFollowupAuthorityApplication(
            DATABASE_URL,
            application_build_id="chapter-group-integration",
            commit_sha="f" * 40,
            model_port=build_reader_outcome_model_port(
                settings, execution=execution, env=env
            ),
            worker_id="group-followup-worker",
        )
        book_authority = PostgresBookAuthority(
            DATABASE_URL,
            chapter_port=ChapterAuthorityCommandAdapter(
                chapter,
                external_effect_adapters=execution.external_effect_adapters,
            ),
            followup_application=followup,
            application_build_id="chapter-group-integration",
            commit_sha="f" * 40,
        )
        principal = Principal(
            principal_id="chapter-group-operator",
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
        worker = Principal(
            principal_id="chapter-group-worker",
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
        versions = (
            BookToChapterAuthorityVerticalPostgresTests._seed_book_inputs(
                project_id
            )
        )
        book_id = f"book:{project_id}"
        seed_authority_project_book(project_id=project_id, book_id=book_id)
        book = book_authority.start(
            StartBookProductionCommand(
                project_id=project_id,
                workspace_id=f"workspace:{project_id}",
                book_id=book_id,
                actor_id=principal.principal_id,
                trace_id=identifier("book-trace"),
                correlation_id=identifier("book-correlation"),
                stable_idempotency_key=f"{project_id}:book:v1",
                book_design_version=versions.pop("book_design_version"),
                book_plan_version=versions.pop("book_plan_version"),
                production_profile_version="production-profile:v1",
                longform_context_versions=versions,
                target_chapter_count=3,
                light_recap_cadence=3,
                formal_recap_cadence=10,
            ),
            principal=principal,
        )
        planning = self._seed_planning(
            project_id=project_id,
            book_id=book_id,
            operation_id=book.root_operation_id,
            volume_plan_version=versions["volume_plan_version"],
            candidates=candidates,
        )
        return {
            "project_id": project_id,
            "book_id": book_id,
            "chapter": chapter,
            "book_authority": book_authority,
            "group_authority": PostgresChapterGroupAuthority(
                DATABASE_URL,
                book_authority=book_authority,
                application_build_id="chapter-group-integration",
                commit_sha="f" * 40,
            ),
            "principal": principal,
            "worker": worker,
            "candidates": candidates,
            "chapter_plans": planning["chapter_plans"],
            "group_plan": planning["group_plan"],
            "book": book,
        }

    def _chapter_command(
        self, fixture: dict, chapter_number: int
    ) -> SubmitBookChapterCommand:
        plan = fixture["chapter_plans"][chapter_number]
        candidates = tuple(
            item
            for item in fixture["candidates"]
            if item["asset_type"] != "chapter_plan"
        ) + (plan,)
        return SubmitBookChapterCommand(
            book_run_id=fixture["book"].book_run_id,
            chapter_number=chapter_number,
            title=f"Group Chapter {chapter_number}",
            premise="A decision creates an irreversible cost.",
            chapter_plan_asset_version_id=plan["asset_version_id"],
            chapter_plan_content_hash=plan["content_hash"],
            context_candidates=candidates,
            parent_group_version_id=fixture["group_plan"][
                "asset_version_id"
            ],
        )

    @staticmethod
    def _run_child(fixture: dict, root_operation_id: str) -> None:
        for _ in range(len(ChapterNode) + 3):
            tick = fixture["chapter"].scheduler(
                principal=fixture["worker"]
            ).tick(
                project_id=fixture["project_id"],
                root_operation_id=root_operation_id,
            )
            if tick.saga_status == "SUCCEEDED":
                return
        raise AssertionError("Chapter Saga did not reach SUCCEEDED")

    @staticmethod
    def _seed_planning(
        *,
        project_id: str,
        book_id: str,
        operation_id: str,
        volume_plan_version: str,
        candidates: list[dict],
    ) -> dict:
        first = next(
            item for item in candidates if item["asset_type"] == "chapter_plan"
        )
        matrix = [
            {
                "chapter_number": chapter,
                "primary_function": function,
                "secondary_functions": ["continuity"],
                "required_state_delta": {"pressure": chapter},
                "required_arc_contributions": ["mainline"],
                "promise_action": "advance",
                "foreshadow_action": "plant",
                "reward_action": "partial",
                "ending_hook": hook,
                "prohibited_outcomes": ["premature closure"],
            }
            for chapter, function, hook in (
                (1, "DISCOVERY", "threat revealed"),
                (2, "ESCALATION", "cost revealed"),
                (3, "REVERSAL", "choice demanded"),
            )
        ]
        group_content = {
            "type": "ChapterGroupPlan",
            "local_objective": "force a public commitment",
            "chapter_range": [1, 3],
            "chapter_function_matrix": matrix,
        }
        group = ChapterGroupAuthorityPostgresTests._seed_asset(
            project_id,
            "chapter_group_plan",
            "group-plan",
            group_content,
        )
        chapter_plans: dict[int, dict] = {}
        for chapter in (1, 2, 3):
            content = {
                **dict(first["content"]),
                "chapter": chapter,
                "chapter_number": chapter,
                "title": f"Group Chapter {chapter}",
                "chapter_objective": matrix[chapter - 1][
                    "required_state_delta"
                ],
            }
            chapter_plans[chapter] = (
                ChapterGroupAuthorityPostgresTests._seed_asset(
                    project_id,
                    "chapter_plan",
                    f"group-chapter-plan-{chapter}",
                    content,
                )
            )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            volume_binding = f"binding:{project_id}:volume"
            uow.cursor.execute(
                """
                INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type,
                    logical_key, asset_version_id, parent_version_id,
                    execution_scope, freshness, created_by_operation_id
                ) VALUES (
                    %s, %s, %s, 'VOLUME', 'volume:1', %s, %s,
                    'FROZEN', 'CURRENT', %s
                )
                """,
                [
                    volume_binding,
                    project_id,
                    book_id,
                    volume_plan_version,
                    volume_plan_version,
                    operation_id,
                ],
            )
            group_binding = f"binding:{project_id}:group"
            uow.cursor.execute(
                """
                INSERT INTO story_plan_binding(
                    binding_id, project_id, book_id, contract_type,
                    logical_key, asset_version_id, parent_version_id,
                    execution_scope, freshness, created_by_operation_id
                ) VALUES (
                    %s, %s, %s, 'CHAPTER_GROUP', 'group:1', %s, %s,
                    'FROZEN', 'CURRENT', %s
                )
                """,
                [
                    group_binding,
                    project_id,
                    book_id,
                    group["asset_version_id"],
                    volume_plan_version,
                    operation_id,
                ],
            )
            for chapter, plan in chapter_plans.items():
                binding_id = f"binding:{project_id}:chapter:{chapter}"
                uow.cursor.execute(
                    """
                    INSERT INTO story_plan_binding(
                        binding_id, project_id, book_id, contract_type,
                        logical_key, asset_version_id, parent_version_id,
                        execution_scope, freshness, created_by_operation_id
                    ) VALUES (
                        %s, %s, %s, 'CHAPTER', %s, %s, %s,
                        'FROZEN', 'CURRENT', %s
                    )
                    """,
                    [
                        binding_id,
                        project_id,
                        book_id,
                        f"chapter:{chapter}",
                        plan["asset_version_id"],
                        group["asset_version_id"],
                        operation_id,
                    ],
                )
                uow.cursor.execute(
                    """
                    INSERT INTO active_story_plan_version(
                        project_id, book_id, logical_key, binding_id,
                        asset_version_id, activated_by_operation_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        project_id,
                        book_id,
                        f"chapter:{chapter}",
                        binding_id,
                        plan["asset_version_id"],
                        operation_id,
                    ],
                )
            for logical_key, binding_id, version_id in (
                ("volume:1", volume_binding, volume_plan_version),
                (
                    "group:1",
                    group_binding,
                    group["asset_version_id"],
                ),
            ):
                uow.cursor.execute(
                    """
                    INSERT INTO active_story_plan_version(
                        project_id, book_id, logical_key, binding_id,
                        asset_version_id, activated_by_operation_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        project_id,
                        book_id,
                        logical_key,
                        binding_id,
                        version_id,
                        operation_id,
                    ],
                )
            uow.commit()
        return {"group_plan": group, "chapter_plans": chapter_plans}

    @staticmethod
    def _seed_asset(
        project_id: str,
        asset_type: str,
        label: str,
        content: dict,
    ) -> dict:
        asset_id = f"{project_id}:{label}:asset"
        version_id = f"{project_id}:{label}:v1"
        content_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                content, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
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
                ) VALUES (%s, %s, 'chapter-group-fixture-v1',
                          'ELIGIBLE', '{}'::jsonb)
                """,
                [f"{version_id}:qualification", version_id],
            )
            uow.commit()
        return {
            "asset_type": asset_type,
            "asset_version_id": version_id,
            "content_hash": content_hash,
            "content": content,
            "project_id": project_id,
            "estimated_tokens": max(1, len(json.dumps(content)) // 4),
            "allowed_use": "generation",
            "source_use_mode": "generation",
            "safe_summary": f"Frozen {asset_type} fixture.",
            "structured_facts": [],
            "narrative_function": asset_type,
        }


if __name__ == "__main__":
    unittest.main()
