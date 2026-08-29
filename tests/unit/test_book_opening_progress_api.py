from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_forge.api.models import product_model_map
from novel_forge.api.routers.book_authority import create_router
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.authority_security import Principal, PrincipalType


def test_opening_progress_route_uses_read_model_and_query_permission() -> None:
    calls: list[tuple[str, str]] = []
    report = {
        "schema_version": "novel-forge.book-opening-workflow-progress.v1",
        "opening_run_id": "opening:1",
        "project_id": "project:1",
        "compatibility_mode": "NODED_WORKFLOW",
        "progress_status": "READY",
        "current_layer": {"node_kind": "BOOK_PLAN"},
        "furthest_completed_layer": None,
        "nodes": [],
        "reviewable_artifact": {"status": "NOT_FORMED"},
        "persistent_checkpoint": {"status": "NOT_FORMED"},
        "blocking_reason": {"is_blocked": False},
        "runtime_fence": {"status": "NOT_REQUIRED"},
        "budget_usage": {"status": "OPEN"},
    }

    class ProgressQuery:
        def __init__(self, database_url: str) -> None:
            calls.append(("database", database_url))

        def progress(self, *, opening_run_id: str):  # type: ignore[no-untyped-def]
            calls.append(("opening", opening_run_id))
            return SimpleNamespace(project_id="project:1", to_dict=lambda: report)

    principal = Principal(
        principal_id="trusted-operator",
        principal_type=PrincipalType.LOCAL_OPERATOR,
        permissions=frozenset({"book.authority.query"}),
        project_scope=frozenset({"project:1"}),
        authentication_source="test",
    )
    resolver = SimpleNamespace(resolve_api_principal=lambda **_values: principal)
    composition = SimpleNamespace(
        opening=SimpleNamespace(database_url="postgresql:///novel_forge")
    )
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
            "novel_forge.api.routers.book_authority."
            "PostgresBookOpeningWorkflowProgressQuery",
            ProgressQuery,
            create=True,
        ),
        patch(
            "novel_forge.api.routers.book_authority.build_trusted_principal_resolver",
            return_value=resolver,
        ),
        TestClient(app) as client,
    ):
        response = client.get(
            "/product/production/book-authority/opening-runs/opening:1/progress"
        )

    assert response.status_code == 200, response.text
    assert response.json() == report
    assert calls == [
        ("database", "postgresql:///novel_forge"),
        ("opening", "opening:1"),
    ]
