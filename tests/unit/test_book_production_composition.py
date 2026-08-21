from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType


class BookProductionCompositionTests(unittest.TestCase):
    def test_builder_reuses_one_dependency_graph(self) -> None:
        from novel_forge.api.authority_dependencies import (
            build_book_production_composition,
        )

        principal = Principal(
            principal_id="book-worker",
            principal_type=PrincipalType.WORKER,
            permissions=frozenset({"*"}),
            project_scope=frozenset({"*"}),
            authentication_source="test",
        )
        chapter = SimpleNamespace()
        followup = SimpleNamespace()
        book = SimpleNamespace(
            database_url="postgresql://authority",
            application_build_id="build-1",
            commit_sha="a" * 40,
            followup=followup,
        )
        planning_authority = SimpleNamespace()
        story_design = SimpleNamespace()
        planning = SimpleNamespace(
            planning=planning_authority,
            story_design=story_design,
        )
        preparation = SimpleNamespace()
        projection_repair = SimpleNamespace()

        execution = SimpleNamespace()
        with (
            patch(
                "novel_forge.api.authority_dependencies.build_book_authority_application",
                return_value=book,
            ),
            patch(
                "novel_forge.api.authority_dependencies.build_story_planning_generation_application",
                return_value=planning,
            ),
            patch(
                "novel_forge.api.authority_dependencies.build_production_preparation_service",
                return_value=preparation,
            ),
            patch(
                "novel_forge.api.authority_dependencies.PostgresBookProjectionRepairAuthority",
                return_value=projection_repair,
            ),
        ):
            composition = build_book_production_composition(
                IndustrialSettings(
                    root=Path("."), database_url="postgresql://authority"
                ),
                env={
                    "NOVEL_FORGE_APPLICATION_BUILD_ID": "build-1",
                    "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
                },
                principal=principal,
                execution=execution,
                chapter_application=chapter,
            )

        self.assertIs(composition.authority, book)
        self.assertIs(composition.planning, planning)
        self.assertIs(composition.production_preparation, preparation)
        self.assertIs(composition.projection_repair, projection_repair)
        self.assertIs(composition.followup, followup)
        self.assertIs(composition.chapter_groups.book, book)
        self.assertIs(composition.plan_change.story_design, story_design)
        self.assertIs(composition.plan_change.planning, planning_authority)
        self.assertIs(composition.replan.book, book)
        self.assertIs(composition.replan.planning, planning)
        self.assertEqual(
            composition.corrective_actions.database_url, "postgresql://authority"
        )
        self.assertIs(composition.supervisor.authority, book)
        self.assertIs(composition.supervisor.query, composition.query)
        self.assertIs(composition.supervisor.scheduler.query, composition.query)
        self.assertIs(composition.supervisor.chapter_groups, composition.chapter_groups)
        self.assertIs(composition.supervisor.production_preparation, preparation)

    def test_tick_has_one_canonical_supervisor_path(self) -> None:
        from novel_forge.modules.book_authority.composition import (
            BookProductionComposition,
        )

        calls: list[tuple[str, str]] = []
        supervisor = SimpleNamespace(
            tick=lambda book_run_id: (
                calls.append(("supervisor", book_run_id)) or "supervisor-tick"
            ),
        )
        composition = BookProductionComposition(
            authority=SimpleNamespace(),
            query=SimpleNamespace(),
            planning=SimpleNamespace(),
            chapter_groups=SimpleNamespace(),
            production_preparation=SimpleNamespace(),
            followup=SimpleNamespace(),
            plan_change=SimpleNamespace(),
            input_resolver=SimpleNamespace(),
            replan=SimpleNamespace(),
            corrective_actions=SimpleNamespace(),
            supervisor=supervisor,
            principal=Principal(
                principal_id="trusted-operator",
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"book.authority.approve_replan"}),
                project_scope=frozenset({"project:1"}),
                authentication_source="test",
            ),
            projection_repair=SimpleNamespace(),
        )
        assert composition.query is not None

        self.assertEqual(composition.tick("book-run:1"), "supervisor-tick")
        self.assertEqual(calls, [("supervisor", "book-run:1")])

    def test_formal_replan_approval_is_scoped_to_the_book_run(self) -> None:
        from novel_forge.modules.book_authority.composition import (
            BookProductionComposition,
        )
        from novel_forge.modules.command_kernel.errors import KernelError

        approvals: list[tuple[str, str, str, dict[str, object]]] = []
        replan = SimpleNamespace(
            require=lambda _replan_id: {
                "book_run_id": "book-run:1",
                "project_id": "project:1",
            },
            approve=lambda replan_id, **values: (
                approvals.append(
                    (
                        replan_id,
                        values["authority_type"],
                        values["authority_version"],
                        values["evidence"],
                    )
                )
                or {"replan_id": replan_id, "status": "ACTIVE"}
            ),
        )
        composition = BookProductionComposition(
            authority=SimpleNamespace(),
            query=SimpleNamespace(),
            planning=SimpleNamespace(),
            chapter_groups=SimpleNamespace(),
            production_preparation=SimpleNamespace(),
            followup=SimpleNamespace(),
            plan_change=SimpleNamespace(),
            input_resolver=SimpleNamespace(),
            replan=replan,
            corrective_actions=SimpleNamespace(),
            supervisor=SimpleNamespace(),
            principal=Principal(
                principal_id="trusted-operator",
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({"book.authority.approve_replan"}),
                project_scope=frozenset({"project:1"}),
                authentication_source="test",
            ),
            projection_repair=SimpleNamespace(),
        )
        assert composition.query is not None

        result = composition.approve_replan(
            book_run_id="book-run:1",
            replan_id="replan:1",
            authority_type="PLAN_CHANGE_AUTHORITY",
            authority_version="operator-approval-v1",
            evidence={"operator_approved": True},
        )

        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(len(approvals), 1)
        with self.assertRaises(KernelError) as raised:
            composition.approve_replan(
                book_run_id="book-run:other",
                replan_id="replan:1",
                authority_type="PLAN_CHANGE_AUTHORITY",
                authority_version="operator-approval-v1",
                evidence={"operator_approved": True},
            )
        self.assertEqual(raised.exception.code, "BOOK_REPLAN_SCOPE_MISMATCH")

        worker_composition = BookProductionComposition(
            authority=SimpleNamespace(),
            query=SimpleNamespace(),
            planning=SimpleNamespace(),
            chapter_groups=SimpleNamespace(),
            production_preparation=SimpleNamespace(),
            followup=SimpleNamespace(),
            plan_change=SimpleNamespace(),
            input_resolver=SimpleNamespace(),
            replan=replan,
            corrective_actions=SimpleNamespace(),
            supervisor=SimpleNamespace(),
            principal=Principal(
                principal_id="book-worker",
                principal_type=PrincipalType.WORKER,
                permissions=frozenset({"book.authority.execute"}),
                project_scope=frozenset({"project:1"}),
                authentication_source="test",
            ),
            projection_repair=SimpleNamespace(),
        )
        assert worker_composition.query is not None
        with self.assertRaises(PermissionError):
            worker_composition.approve_replan(
                book_run_id="book-run:1",
                replan_id="replan:1",
                authority_type="PLAN_CHANGE_AUTHORITY",
                authority_version="worker-forbidden-v1",
                evidence={},
            )

    def test_authority_api_is_the_only_replan_approval_entrypoint(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from novel_forge.api.models import product_model_map
        from novel_forge.api.routers.book_authority import create_router
        from novel_forge.api.routers.context import ProductRouterContext

        approvals: list[dict[str, object]] = []
        composition = SimpleNamespace(
            authority=SimpleNamespace(
                require=lambda _book_run_id: {"project_id": "project:1"}
            ),
            approve_replan=lambda **values: (
                approvals.append(values)
                or {"replan_id": values["replan_id"], "status": "ACTIVE"}
            ),
        )
        principal = Principal(
            principal_id="trusted-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(
                {
                    "book.authority.execute",
                    "book.authority.approve_replan",
                }
            ),
            project_scope=frozenset({"project:1"}),
            authentication_source="test",
        )
        resolver = SimpleNamespace(resolve_api_principal=lambda **_values: principal)
        app = FastAPI()
        app.include_router(
            create_router(
                ProductRouterContext(
                    app_settings=SimpleNamespace(),
                    models=product_model_map(),
                    services=SimpleNamespace(book_production=composition),
                )
            )
        )

        with (
            patch(
                "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
                return_value=resolver,
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/product/production/book-authority/runs/book-run:1/"
                "replans/replan:1/approve",
                json={
                    "authority_type": "PLAN_CHANGE_AUTHORITY",
                    "authority_version": "operator-approval-v1",
                    "evidence": {"operator_approved": True},
                    "actor_id": "untrusted-caller",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ACTIVE")
        self.assertEqual(
            approvals,
            [
                {
                    "book_run_id": "book-run:1",
                    "replan_id": "replan:1",
                    "authority_type": "PLAN_CHANGE_AUTHORITY",
                    "authority_version": "operator-approval-v1",
                    "evidence": {"operator_approved": True},
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
