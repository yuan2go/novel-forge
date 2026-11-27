from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from novel_forge.api.models import product_model_map
from novel_forge.api.routers.book_authority import create_router
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.authority_security import Principal, PrincipalType


def _client(planning):
    app = FastAPI()
    app.include_router(create_router(ProductRouterContext(
        app_settings=SimpleNamespace(), models=product_model_map(),
        services=SimpleNamespace(book_production=SimpleNamespace(planning=planning)),
    )))
    return TestClient(app)


def _principal(project="project:1"):
    return Principal(principal_id="existing-operator", principal_type=PrincipalType.LOCAL_OPERATOR,
                     permissions=frozenset({"story_planning.authority.execute"}),
                     project_scope=frozenset({project}), authentication_source="test")


def _request():
    return {"project_id": "project:1", "expected_source_version": 7,
            "decision_evidence": {"authorization_ref": "user:decision", "authorized_reasoning_effort": "high", "reason": "Continue a verified zero-dispatch failure"},
            "trace_id": "trace:1", "correlation_id": "correlation:1"}


_ROUTE = "/product/production/book-authority/books/book:1/planning-generations/source:1/runtime-continuation"
_RESOLVER = "novel_forge.api.routers.book_authority.build_trusted_principal_resolver"


def test_runtime_continuation_route_binds_trusted_principal_and_exact_source():
    principal = _principal()
    planning = Mock()
    planning.require_generation.return_value = {"project_id": "project:1", "book_id": "book:1"}
    planning.register_runtime_continuation.return_value = {"continuation_id": "continuation:1"}
    with patch(_RESOLVER, return_value=SimpleNamespace(resolve_api_principal=lambda: principal)), _client(planning) as client:
        response = client.post(_ROUTE, json=_request())
    assert response.status_code == 200, response.text
    assert response.json() == {"continuation_id": "continuation:1"}
    planning.register_runtime_continuation.assert_called_once_with("source:1", principal=principal, **_request())


@pytest.mark.parametrize("foreign_project,foreign_book", [(True, False), (False, True)])
def test_runtime_continuation_route_rejects_foreign_scope_before_registration(foreign_project, foreign_book):
    principal = _principal("project:other" if foreign_project else "project:1")
    planning = Mock()
    planning.require_generation.return_value = {"project_id": "project:1", "book_id": "book:other" if foreign_book else "book:1"}
    with patch(_RESOLVER, return_value=SimpleNamespace(resolve_api_principal=lambda: principal)), _client(planning) as client:
        response = client.post(_ROUTE, json=_request())
    assert response.status_code == (403 if foreign_project else 409), response.text
    planning.register_runtime_continuation.assert_not_called()
    if foreign_project:
        planning.require_generation.assert_not_called()
    else:
        assert response.json()["detail"]["code"] == "BOOK_PLANNING_SCOPE_MISMATCH"


@pytest.mark.parametrize("version", [True, "7", 7.0, 0, -1, None, []])
def test_runtime_continuation_route_requires_positive_integer_cas(version):
    principal, planning = _principal(), Mock()
    with patch(_RESOLVER, return_value=SimpleNamespace(resolve_api_principal=lambda: principal)), _client(planning) as client:
        response = client.post(_ROUTE, json={**_request(), "expected_source_version": version})
    assert response.status_code == 422, response.text
    planning.register_runtime_continuation.assert_not_called()
