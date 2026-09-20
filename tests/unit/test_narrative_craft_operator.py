from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.api.routers.mkaos_authority import create_router
from novel_forge.cli.authority import _authority_parser
from novel_forge.modules.mkaos_authority.craft import core_catalog_hash


def test_craft_catalog_and_authoring_use_native_authenticated_product_surface(monkeypatch):
    principal = SimpleNamespace(principal_id="trusted-craft-operator")
    authorize = Mock(return_value=principal)
    monkeypatch.setattr("novel_forge.api.routers.mkaos_authority._authorize", authorize)
    application = Mock()
    application.admit_core_craft.return_value = {"operation_id": "craft-op", "status": "READY"}
    app = FastAPI()
    app.include_router(create_router(ProductRouterContext(None, {}, SimpleNamespace(
        mkaos_authority_application=application, mkaos_authority_query=Mock()))))
    client = TestClient(app)
    catalog = client.get("/product/mkaos/craft-catalog", params={"project_id": "project"})
    assert catalog.status_code == 200
    assert len(catalog.json()["mechanisms"]) == 43
    assert catalog.json()["activation"] == "EXPLICIT_CANDIDATE_AND_APPROVAL_REQUIRED"
    authored = client.post("/product/mkaos/craft-candidates", json={"project_id": "project", "workspace_id": "workspace",
        "mechanism_id": "subtext-pressure", "catalog_hash": core_catalog_hash(), "idempotency_key": "author-once"})
    assert authored.status_code == 202
    command = application.admit_core_craft.call_args.args[0]
    assert command.actor_id == "trusted-craft-operator"
    assert command.catalog_hash == catalog.json()["catalog_hash"]
    authorize.assert_called_with("mkaos.authority.execute", "project")


def test_cli_requires_explicit_project_and_exposes_separate_author_and_approval():
    parser = _authority_parser()
    for action in ("catalog", "cards", "author", "approve-core", "trace"):
        args = parser.parse_args(["authority-craft", action, "--project-id", "project"])
        assert args.action == action
        assert args.catalog_hash == ""
        assert args.rationale == ""


def test_cli_historical_catalog_approval_reaches_native_exact_candidate_validation(monkeypatch):
    from novel_forge.cli.craft import run_craft_command
    from novel_forge.modules.mkaos_authority.craft import CRAFT_ORIGINAL_POLICY

    principal = Mock(principal_id="trusted-operator")
    resolver = Mock()
    resolver.resolve_api_principal.return_value = principal
    monkeypatch.setattr("novel_forge.api.authority_dependencies.build_trusted_principal_resolver", lambda: resolver)
    monkeypatch.setattr("novel_forge.api.authority_dependencies.authority_release_identity", lambda: ("next-build", "f"*40))
    application = Mock()
    monkeypatch.setattr("novel_forge.modules.mkaos_authority.application.MkaosAuthorityApplication", lambda *args, **kwargs: application)
    historical_hash = "sha256:" + "a" * 64
    assert historical_hash != core_catalog_hash()
    args = _authority_parser().parse_args(["authority-craft", "approve-core", "--project-id", "project",
        "--workspace-id", "workspace", "--idempotency-key", "approval", "--catalog-hash", historical_hash,
        "--candidate-asset-version-id", "candidate:v1", "--rationale", "Approve the persisted exact catalog"])
    run_craft_command(SimpleNamespace(database_url="test-database"), args)
    principal.require.assert_called_once_with("mkaos.authority.approve", "project")
    command = application.execute_approval.call_args.args[0]
    assert command.policy_version == CRAFT_ORIGINAL_POLICY+":"+historical_hash
    assert command.candidate_asset_version_id == "candidate:v1"
