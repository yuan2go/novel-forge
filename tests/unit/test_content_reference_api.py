from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_forge.api.models import product_model_map
from novel_forge.api.routers import content_authority as router_module
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.authority_security import TrustedPrincipalResolver
from novel_forge.modules.chapter_quality_authority import reference_subject
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import application as content_module
from novel_forge.modules.content_authority.definitions import CONTENT_INTEGRATION_PROVEN


@pytest.fixture
def reference_api(monkeypatch):
    binding = {"asset_version_id": "sample:fixture", "content_hash": "sha256:" + "a" * 64}
    subject = {**binding, "asset_type": "planning_generation_candidate", "content": {},
               "generation_operation_id": "generation:fixture", "generation_actor_id": "generator:fixture"}
    application = content_module.ContentAuthorityApplication(
        "unused", application_build_id="reference-api-test", commit_sha="a" * 40,
        integration_proven=CONTENT_INTEGRATION_PROVEN, trusted_only=True,
    )
    uow = MagicMock()
    uow.__enter__.return_value.repositories.attempt_runtime.operation_state.return_value = {"status": "READY"}
    monkeypatch.setattr(content_module, "AuthorityUnitOfWork", lambda _: uow)
    native_admission = MagicMock(return_value={"operation_id": "annotation:fixture", "replayed": False})
    monkeypatch.setattr(content_module, "admit_command", native_admission)

    def require_subject(cursor, *, project_id, binding, allowed_types):
        if project_id != "project:fixture" or binding != {
            "asset_version_id": "sample:fixture", "content_hash": "sha256:" + "a" * 64
        }:
            raise KernelError("QUALITY_REFERENCE_TARGET_INVALID", "fixture native sample binding differs")
        return subject

    native_subject = MagicMock(side_effect=require_subject)
    monkeypatch.setattr(reference_subject, "require_reference_subject", native_subject)
    query = MagicMock()
    query.require.return_value = SimpleNamespace(**binding)
    resolver = MagicMock()
    resolver.resolve_override.side_effect = KernelError("ASSET_NOT_PRODUCTION_READY", "sample remains ineligible")
    monkeypatch.setattr(router_module, "AuthorityAssetQuery", lambda _: query)
    monkeypatch.setattr(router_module, "PostgresProductionAssetResolver", lambda _: resolver)
    monkeypatch.setattr(router_module, "build_trusted_principal_resolver", lambda: TrustedPrincipalResolver(
        environment="test", configured_local_operator_id="human:fixture",
    ))
    app = FastAPI()
    app.include_router(router_module.create_router(ProductRouterContext(
        app_settings=None, models=product_model_map(),
        services=SimpleNamespace(content_authority_application=application),
    )))
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, binding=binding, native_admission=native_admission,
                              native_subject=native_subject, query=query, resolver=resolver)


def annotation_request(binding, name="quality.human_evaluation.record"):
    key, author = (("evaluation", "evaluator_id") if name == "quality.human_evaluation.record"
                   else ("adjudication", "adjudicator_id"))
    return {"definition_name": name, "project_id": "project:fixture", "workspace_id": "workspace:fixture",
            "input_asset_version_ids": [binding["asset_version_id"]], "idempotency_key": "annotation:fixture",
            "actor_id": "untrusted-caller", "payload": {"reference_sample": dict(binding), key: {
                "subject_asset_version_id": binding["asset_version_id"], author: "human:fixture",
            }}}


@pytest.mark.parametrize("name", ["quality.human_evaluation.record", "quality.adjudication.record"])
def test_reference_annotation_api_reaches_native_content_admission(reference_api, name):
    fixture = reference_api
    response = fixture.client.post("/product/content-authority/commands", json=annotation_request(fixture.binding, name))
    assert response.status_code == 202, response.text
    admitted = fixture.native_admission.call_args.args[1]
    assert admitted["definition_name"] == name
    assert admitted["definition_version"] == reference_subject.PLANNING_REFERENCE_ANNOTATION_VERSION
    assert admitted["actor_id"] == "human:fixture"
    assert admitted["input_assets"] == [fixture.binding]
    assert fixture.native_subject.call_count == 2
    fixture.resolver.resolve_override.assert_not_called()


@pytest.mark.parametrize("mismatch", ["hash", "project", "author", "grant"])
def test_reference_api_retains_native_binding_and_author_validation(reference_api, mismatch):
    fixture = reference_api
    request = annotation_request(fixture.binding)
    if mismatch == "hash":
        request["payload"]["reference_sample"]["content_hash"] = "sha256:" + "b" * 64
    elif mismatch == "project":
        request["project_id"] = "project:other"
    elif mismatch == "author":
        request["payload"]["evaluation"]["evaluator_id"] = "different-person"
    else:
        fixture.native_subject.side_effect = KernelError("QUALITY_REFERENCE_TARGET_INVALID", "native generation grant missing")
    response = fixture.client.post("/product/content-authority/commands", json=request)
    assert response.status_code == 409, response.text
    fixture.native_admission.assert_not_called()


@pytest.mark.parametrize("change", ["ordinary", "unrelated_operation", "unbound_input"])
def test_reference_api_does_not_relax_ordinary_or_extra_input_gate(reference_api, change):
    fixture = reference_api
    request = annotation_request(fixture.binding)
    if change == "ordinary":
        request["payload"].pop("reference_sample")
    elif change == "unrelated_operation":
        request["definition_name"] = "theme.question.create"
    else:
        request["input_asset_version_ids"].append("other:ineligible")
    response = fixture.client.post("/product/content-authority/commands", json=request)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ASSET_NOT_PRODUCTION_READY"
    fixture.native_admission.assert_not_called()
    fixture.resolver.resolve_override.assert_called_once()
