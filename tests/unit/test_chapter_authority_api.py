from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from novel_forge.api.authority_app import create_authority_app as create_app
from novel_forge.infrastructure.settings import IndustrialSettings


class _FakeQuery:
    def list_runs(self, *, project_id: str, limit: int) -> list[dict]:
        return [{"project_id": project_id, "limit": limit, "status": "SUCCEEDED"}]

    def require_run(self, *, project_id: str, root_operation_id: str) -> dict:
        return {
            "project_id": project_id,
            "root_operation_id": root_operation_id,
            "status": "SUCCEEDED",
        }


class _FakeApplication:
    def __init__(self) -> None:
        self.query = _FakeQuery()
        self.requests: list[object] = []
        self.model_port = SimpleNamespace(
            adapter=SimpleNamespace(provider_adapters={})
        )

    def run(self, request: object) -> object:
        self.requests.append(request)
        return SimpleNamespace(root_operation_id="operation-1")

    def admit(self, request: object, *, principal: object) -> object:
        self.requests.append(request)
        return SimpleNamespace(
            root_operation_id="operation-async-1",
            saga_id="saga-1",
            status="ACCEPTED",
            replayed=False,
        )


class _FakeContentApplication:
    database_url = "postgresql://fixture"

    def __init__(self) -> None:
        self.requests: list[tuple[object, object]] = []

    def admit(self, request: object, *, principal: object) -> object:
        self.requests.append((request, principal))
        return SimpleNamespace(
            operation_id="content-operation-1",
            project_id="project-1",
            book_id="book-1",
            replayed=False,
        )


class ChapterAuthorityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(
            "os.environ",
            {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_APPLICATION_BUILD_ID": "chapter-authority-api-test",
                "NOVEL_FORGE_COMMIT_SHA": "a" * 40,
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": "object-store",
                "NOVEL_FORGE_MODEL_PROVIDER": "mock",
            },
            clear=False,
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_content_command_returns_202_and_uses_trusted_principal(self) -> None:
        from fastapi.testclient import TestClient
        from novel_forge.modules.authority_security import TrustedPrincipalResolver

        fake = _FakeContentApplication()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "novel_forge.api.authority_app.build_content_authority_application",
                return_value=fake,
            ):
                app = create_app(
                    IndustrialSettings(
                        root=Path(directory), database_url="postgresql://fixture"
                    )
                )
            with (
                patch(
                    "novel_forge.api.routers.content_authority.build_content_authority_application",
                    return_value=fake,
                ),
                patch(
                    "novel_forge.api.routers.content_authority.build_trusted_principal_resolver",
                    return_value=TrustedPrincipalResolver(
                        environment="test",
                        configured_local_operator_id="trusted-operator",
                    ),
                ),
                TestClient(app) as client,
            ):
                response = client.post(
                    "/product/content-authority/commands",
                    json={
                        "definition_name": "theme.question.create",
                        "project_id": "project-1",
                        "workspace_id": "workspace-1",
                        "payload": {
                            "question": "When safety requires betrayal, is loyalty worth its cost?"
                        },
                        "idempotency_key": "content-command-1",
                        "actor_id": "untrusted-caller",
                    },
                )

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["operation_id"], "content-operation-1")
        request, principal = fake.requests[0]
        self.assertEqual(request.actor_id, "trusted-operator")
        self.assertEqual(principal.principal_id, "trusted-operator")

    def test_async_command_returns_202_and_uses_trusted_principal(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        from novel_forge.modules.authority_security import TrustedPrincipalResolver
        from novel_forge.modules.production_preparation.contracts import (
            ChapterAuthorityCommand,
            ProductionPreparationReport,
            ProductionPreparationResult,
        )

        fake = _FakeApplication()
        command = ChapterAuthorityCommand(
            project_id="project-1",
            book_id="book-1",
            workspace_id="workspace-1",
            chapter=1,
            chapter_plan_asset_version_id="chapter-plan-version-1",
            chapter_plan_content_hash="sha256:" + "a" * 64,
            title="Prepared title",
            premise="Prepared premise",
            context_candidates=(),
            context_version_refs={},
            context_token_budget=6000,
            preparation_report={"decision": "READY"},
            idempotency_key="chapter-command-1",
        )
        report = ProductionPreparationReport(
            project_id="project-1", chapter=1, decision="READY",
            selected_asset_version_ids=(), selection_reasons={},
            missing_required_asset_types=(), blocked_assets=(),
            approval_requirements=(), context_digest="sha256:ready",
            estimated_token_budget=6000, estimated_provider_budget={},
            repair_actions=(), idempotency_key="chapter-command-1",
        )
        preparation_service = SimpleNamespace(
            prepare=lambda request: ProductionPreparationResult(report=report, command=command)
        )
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "novel_forge.api.authority_app.build_chapter_authority_application",
                    return_value=fake,
                ),
                patch(
                    "novel_forge.api.authority_app.build_book_production_composition",
                    return_value=SimpleNamespace(authority=SimpleNamespace()),
                ),
            ):
                app = create_app(
                    IndustrialSettings(
                        root=Path(directory), database_url="postgresql://fixture"
                    )
                )
            with (
                patch(
                    "novel_forge.api.routers.chapter_authority.build_production_preparation_service",
                    return_value=preparation_service,
                ),
                patch(
                    "novel_forge.api.routers.chapter_authority.build_trusted_principal_resolver",
                    return_value=TrustedPrincipalResolver(
                        environment="test",
                        configured_local_operator_id="trusted-operator",
                    ),
                ),
                patch(
                    "novel_forge.api.routers.chapter_authority.authority_release_identity",
                    return_value=("build-42", "a" * 40),
                ),
                TestClient(app) as client,
            ):
                response = client.post(
                    "/product/production/chapter-authority/commands",
                    json={
                        "project_id": "project-1",
                        "workspace_id": "workspace-1",
                        "book_id": "book-1",
                        "chapter": 1,
                        "idempotency_key": "chapter-command-1",
                        "actor_id": "untrusted-caller",
                    },
                )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["saga_id"], "saga-1")
        self.assertEqual(fake.requests[0].actor_id, "trusted-operator")
        self.assertNotEqual(fake.requests[0].actor_id, "untrusted-caller")

    def test_command_and_strong_query_routes_use_authority_application(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        fake = _FakeApplication()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "novel_forge.api.authority_app.build_chapter_authority_application",
                    return_value=fake,
                ),
                patch(
                    "novel_forge.api.authority_app.build_chapter_authority_query",
                    return_value=fake.query,
                ),
                patch(
                    "novel_forge.api.authority_app.build_book_production_composition",
                    return_value=SimpleNamespace(authority=SimpleNamespace()),
                ),
            ):
                app = create_app(
                    IndustrialSettings(
                        root=Path(directory), database_url="postgresql://fixture"
                    )
                )
            with (
                patch(
                    "novel_forge.api.routers.chapter_authority.authority_release_identity",
                    return_value=("build-42", "a" * 40),
                ),
                TestClient(app) as client,
            ):
                response = client.post(
                    "/product/production/chapter-authority/run",
                    json={
                        "project_id": "project-1",
                        "workspace_id": "workspace-1",
                        "actor_id": "operator-1",
                        "chapter": 1,
                        "title": "A bounded chapter",
                        "premise": "A promise incurs a visible cost.",
                    },
                )
                listing = client.get(
                    "/product/production/chapter-authority/runs",
                    params={"project_id": "project-1", "limit": 12},
                )
                detail = client.get(
                    "/product/production/chapter-authority/run",
                    params={
                        "project_id": "project-1",
                        "root_operation_id": "operation-1",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["root_operation_id"], "operation-1")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["limit"], 12)
        self.assertEqual(detail.status_code, 200)
        request = fake.requests[0]
        self.assertEqual(request.application_build_id, "build-42")
        self.assertEqual(request.commit_sha, "a" * 40)
        self.assertTrue(request.trace_id.startswith("trace:"))

    def test_route_fails_closed_when_authority_dependencies_are_missing(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ModuleNotFoundError:
            self.skipTest("FastAPI test client is not installed")
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "novel_forge.api.authority_app.build_chapter_authority_query",
                return_value=None,
            ):
                app = create_app(
                    IndustrialSettings(
                        root=Path(directory), database_url="postgresql://fixture"
                    )
                )
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/product/production/chapter-authority/runs",
                    params={"project_id": "project-1"},
                )

        self.assertEqual(response.status_code, 503)
        self.assertIn("PostgreSQL database is required", response.json()["detail"])

    def test_chapter_query_denies_cross_project_scope(self) -> None:
        from fastapi.testclient import TestClient
        from novel_forge.modules.authority_security import TrustedPrincipalResolver

        fake = _FakeApplication()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "novel_forge.api.authority_app.build_chapter_authority_query",
                return_value=fake.query,
            ):
                app = create_app(
                    IndustrialSettings(
                        root=Path(directory), database_url="postgresql://fixture"
                    )
                )
            with (
                patch(
                    "novel_forge.api.routers.chapter_authority.build_trusted_principal_resolver",
                    return_value=TrustedPrincipalResolver(
                        environment="test",
                        configured_local_operator_id="scoped-operator",
                        configured_project_scope=frozenset({"project-allowed"}),
                    ),
                ),
                TestClient(app) as client,
            ):
                response = client.get(
                    "/product/production/chapter-authority/runs",
                    params={"project_id": "project-denied"},
                )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()


def test_chapter_sample_api_uses_trusted_actor_and_keeps_dry_run_non_mutating():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_forge.api import models
    from novel_forge.api.routers.chapter_authority import create_router
    from novel_forge.modules.authority_security import TrustedPrincipalResolver

    calls = []
    application = SimpleNamespace(
        prepare_provider_sample=lambda command, **kwargs: calls.append(("prepare", command, kwargs)) or {"provider_calls": 0},
        admit_provider_sample=lambda command, **kwargs: calls.append(("admit", command, kwargs)) or {"operation_id": "sample-operation"},
    )
    ctx = SimpleNamespace(
        models={name: getattr(models, name) for name in (
            "AuthorityChapterRunRequest", "AuthorityChapterCommandRequest", "AuthorityOperationControlRequest",
        )}, services=SimpleNamespace(chapter_application=application),
    )
    app = FastAPI()
    app.include_router(create_router(ctx))
    body = {"project_id": "sample-project", "actor_id": "untrusted", "source_operation_id": "frozen-draft",
            "authorization_id": "grant", "idempotency_key": "sample:one"}
    with patch("novel_forge.api.routers.chapter_authority.build_trusted_principal_resolver", return_value=TrustedPrincipalResolver(
        environment="test", configured_local_operator_id="trusted-operator",
    )), TestClient(app) as client:
        assert client.post("/product/production/chapter-authority/provider-samples?dry_run=true", json=body).json() == {"provider_calls": 0}
        assert [item[0] for item in calls] == ["prepare"]
        response = client.post("/product/production/chapter-authority/provider-samples", json=body)
        assert response.status_code == 202
        assert [item[0] for item in calls] == ["prepare", "admit"]
        assert all(item[1].actor_id == "trusted-operator" for item in calls)
        assert client.post("/product/production/chapter-authority/provider-samples", json={**body, "model": "caller-selected"}).status_code == 422
