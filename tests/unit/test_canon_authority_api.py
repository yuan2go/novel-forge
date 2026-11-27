from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_forge.api.routers.canon_authority import create_router
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import TrustedPrincipalResolver


class CanonAuthorityApiTests(unittest.TestCase):
    def _client(self, *, scope=frozenset({"project-a"})):
        root = tempfile.TemporaryDirectory()
        settings = IndustrialSettings(
            root=Path(root.name), environment="test", storage_authority="postgresql",
            database_url="postgresql://fixture",
        )
        app = FastAPI()
        app.include_router(create_router(ProductRouterContext(settings, {}, object())))
        resolver = TrustedPrincipalResolver(
            environment="test", configured_local_operator_id="trusted-operator",
            configured_project_scope=scope,
        )
        return root, TestClient(app), resolver

    def test_decision_body_is_strict_and_uses_trusted_principal(self) -> None:
        root, client, resolver = self._client()
        with root, patch(
            "novel_forge.api.routers.canon_authority.build_trusted_principal_resolver",
            return_value=resolver,
        ), patch(
            "novel_forge.api.routers.canon_authority.decide_canon_approval",
            return_value={"decision": "APPROVE", "gate_resumed": True},
        ) as decide:
            response = client.post(
                "/product/canon-authority/approvals/request-1/decisions",
                json={
                    "project_id": "project-a", "expected_version": 0,
                    "decision": "APPROVE", "reason": "evidence reviewed",
                    "evidence": {"ticket": "local"}, "idempotency_key": "once",
                },
            )
            invalid = client.post(
                "/product/canon-authority/approvals/request-1/decisions",
                json={
                    "project_id": "project-a", "expected_version": 0,
                    "decision": "APPROVE", "reason": "evidence reviewed",
                    "idempotency_key": "twice", "unexpected": True,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(invalid.status_code, 422)
        context = decide.call_args.args[1]
        self.assertEqual(context.principal_id, "trusted-operator")

    def test_cross_project_query_is_denied_before_database_access(self) -> None:
        root, client, resolver = self._client(scope=frozenset({"project-a"}))
        with root, patch(
            "novel_forge.api.routers.canon_authority.build_trusted_principal_resolver",
            return_value=resolver,
        ), patch(
            "novel_forge.api.routers.canon_authority.list_canon_approvals"
        ) as listing:
            response = client.get(
                "/product/canon-authority/approvals",
                params={"project_id": "project-b"},
            )
        self.assertEqual(response.status_code, 403)
        listing.assert_not_called()

    def test_reopen_is_strict_and_uses_trusted_principal(self) -> None:
        root, client, resolver = self._client()
        with root, patch(
            "novel_forge.api.routers.canon_authority.build_trusted_principal_resolver",
            return_value=resolver,
        ), patch(
            "novel_forge.api.routers.canon_authority.reopen_canon_approval",
            return_value={"status": "PENDING", "replayed": False},
        ) as reopen:
            response = client.post(
                "/product/canon-authority/approvals/request-1/reopen",
                json={
                    "project_id": "project-a", "expected_version": 1,
                    "reason": "requested evidence arrived", "idempotency_key": "reopen-1",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(reopen.call_args.args[1].principal_id, "trusted-operator")


if __name__ == "__main__":
    unittest.main()
