from dataclasses import dataclass, replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_forge.api.models import product_model_map
from novel_forge.api.routers import content_authority as router_module
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.authority_security import PrincipalType, TrustedPrincipalResolver
from novel_forge.modules.content_authority import reference_review


@pytest.fixture
def author_api(monkeypatch):
    resolver = TrustedPrincipalResolver(environment='test', configured_local_operator_id='human:fixture')
    sample = {'asset_version_id': 'sample:fixture', 'content_hash': 'sha256:' + 'a' * 64,
              'workspace_id': 'workspace:fixture', 'book_id': 'book:fixture',
              'content': {'core_conflict': 'A witness must pay a visible cost.'},
              'reference_contract': {'dimensions': ['GATE:CORE_CONFLICT_CLARITY'],
                                     'protocol_version': 'fixture:protocol', 'evaluation_version': 'fixture:evaluation'}}
    query = MagicMock(return_value={'samples': [sample]})
    monkeypatch.setattr(reference_review, 'planning_reference_samples', query)
    monkeypatch.setattr(router_module, 'build_trusted_principal_resolver', lambda: resolver)

    @dataclass
    class Result:
        operation_id: str = 'annotation:fixture'
        asset_version_id: str = 'evaluation:fixture'
        replayed: bool = False

    application = SimpleNamespace(database_url='unused', execute=MagicMock(return_value=Result()))
    app = FastAPI()
    app.include_router(router_module.create_router(ProductRouterContext(
        app_settings=None, models=product_model_map(), services=SimpleNamespace(content_authority_application=application))))
    body = {'project_id': 'project:fixture', 'book_id': 'book:fixture',
            'asset_version_id': sample['asset_version_id'], 'content_hash': sample['content_hash'],
            'dimension': 'GATE:CORE_CONFLICT_CLARITY', 'status': 'PASSED', 'score': 75, 'confidence': .8,
            'evaluator_identity_class': 'AUTHOR_EDITOR', 'scope_type': 'CHAPTER', 'chapter_start': 1, 'chapter_end': 1,
            'quote': 'visible cost', 'rationale': 'The cost creates a consequential choice.',
            'preserve_strengths': 'Keep the witness agency.', 'blind': False, 'human_confirmation': True,
            'idempotency_key': 'same-request'}
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, body=body, sample=sample, application=application, query=query,
                              principal=resolver.resolve_api_principal())


def test_author_form_resolves_native_input_actor_and_stable_retry(author_api):
    f = author_api
    for _ in range(2):
        response = f.client.post('/product/content-authority/reference-evaluations', json=f.body)
        assert response.status_code == 200, response.text
        assert response.json()['production_eligible'] is False
    first, second = [call.args[0] for call in f.application.execute.call_args_list]
    assert first == second
    assert first.actor_id == 'human:fixture'
    assert first.workspace_id == 'workspace:fixture'
    assert first.input_assets == ({'asset_version_id': f.sample['asset_version_id'], 'content_hash': f.sample['content_hash']},)
    assert first.payload['evaluation']['blind'] is False
    assert first.payload['evaluation']['evaluator_id'] == first.actor_id
    assert first.idempotency_key == 'author-reference:same-request'


@pytest.mark.parametrize('change', [
    {'actor_id': 'other-person'}, {'human_confirmation': False}, {'score': 101}, {'confidence': -1},
    {'rationale': '   '}, {'preserve_strengths': '  '}, {'chapter_end': 0}, {'chapter_end': 2},
    {'scope_type': 'ARC', 'chapter_start': 3, 'chapter_end': 2},
])
def test_invalid_author_claim_is_rejected_before_native_mutation(author_api, change):
    f = author_api
    response = f.client.post('/product/content-authority/reference-evaluations', json={**f.body, **change})
    assert response.status_code == 422, response.text
    f.application.execute.assert_not_called()


@pytest.mark.parametrize('change,code', [
    ({'quote': 'invented evidence'}, 'QUALITY_REFERENCE_QUOTE_MISMATCH'),
    ({'content_hash': 'sha256:' + 'b' * 64}, 'QUALITY_REFERENCE_TARGET_INVALID'),
    ({'dimension': 'unknown'}, 'QUALITY_REFERENCE_ANNOTATION_INVALID'),
])
def test_exact_quote_sample_and_frozen_dimension_are_required(author_api, change, code):
    f = author_api
    response = f.client.post('/product/content-authority/reference-evaluations', json={**f.body, **change})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == code
    f.application.execute.assert_not_called()


def test_service_cannot_claim_human_contribution(author_api):
    f = author_api
    with pytest.raises(PermissionError, match='authenticated human'):
        reference_review.reference_evaluation_request('unused', principal=replace(f.principal, principal_type=PrincipalType.SERVICE), values=f.body)
    f.query.assert_not_called()


def test_project_scope_checked_before_query(author_api):
    f = author_api
    with pytest.raises(PermissionError):
        reference_review.reference_evaluation_request('unused', principal=replace(f.principal, project_scope=frozenset({'different'})), values=f.body)
    f.query.assert_not_called()
