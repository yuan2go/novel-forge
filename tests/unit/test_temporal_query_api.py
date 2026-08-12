from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.api.routers.temporal_query import create_router
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import TrustedPrincipalResolver


class TemporalQueryApiTests(unittest.TestCase):
    def _client(
        self, *, scope: frozenset[str]
    ) -> tuple[object, TestClient, Mock, TrustedPrincipalResolver]:
        root = tempfile.TemporaryDirectory()
        settings = IndustrialSettings(
            root=Path(root.name),
            environment="test",
            storage_authority="postgresql",
            database_url="postgresql://fixture",
        )
        service = Mock()
        service.relationship_at.return_value = {"status": "FOUND"}
        app = FastAPI()
        app.include_router(
            create_router(
                ProductRouterContext(
                    settings,
                    {},
                    SimpleNamespace(temporal_query_service=service),
                )
            )
        )
        resolver = TrustedPrincipalResolver(
            environment="test",
            configured_local_operator_id="trusted-operator",
            configured_project_scope=scope,
        )
        return root, TestClient(app), service, resolver

    def test_relationship_query_dispatches_only_after_scope_authorization(self) -> None:
        root, client, service, resolver = self._client(scope=frozenset({"project-a"}))
        with (
            root,
            patch(
                "novel_forge.api.routers.temporal_query.build_trusted_principal_resolver",
                return_value=resolver,
            ),
        ):
            response = client.post(
                "/product/temporal-query",
                json={
                    "project_id": "project-a",
                    "query": "relationship_at",
                    "source_id": "character-a",
                    "target_id": "character-b",
                    "chapter": 35,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        service.relationship_at.assert_called_once_with(
            "project-a", "character-a", "character-b", 35
        )

    def test_cross_project_and_incomplete_queries_fail_closed(self) -> None:
        root, client, service, resolver = self._client(scope=frozenset({"project-a"}))
        with (
            root,
            patch(
                "novel_forge.api.routers.temporal_query.build_trusted_principal_resolver",
                return_value=resolver,
            ),
        ):
            denied = client.post(
                "/product/temporal-query",
                json={
                    "project_id": "project-b",
                    "query": "pending_promises_at",
                    "chapter": 20,
                },
            )
            invalid = client.post(
                "/product/temporal-query",
                json={
                    "project_id": "project-a",
                    "query": "character_knows_at",
                    "chapter": 20,
                    "character_id": "character-a",
                },
            )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(invalid.status_code, 422)
        service.character_knows_at.assert_not_called()


if __name__ == "__main__":
    unittest.main()
