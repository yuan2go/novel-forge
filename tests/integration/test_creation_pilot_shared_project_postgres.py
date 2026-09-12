from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.creation_pilot import prepare_pilot_book
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import BookDesignAuthorityApplication
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.budget_runtime import BudgetReservationRequest, reserve_provider_budget, resolve_provider_budget_failure
from novel_forge.modules.project_authority import ProjectAuthorityApplication, ProjectAuthorityCommand
from novel_forge.modules.project_authority.query import ProjectAuthorityQuery
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, transaction
from tests.integration import test_mkaos_authority_postgres as source_fixture
from tests.integration import test_provider_budget_runtime_postgres as budget_fixture


@pytest.fixture
def pilot_project():
    ensure_migrated()
    project_id, workspace_id = identifier('shared-pilot-project'), identifier('shared-pilot-workspace')
    principal = Principal(principal_id='pilot-fixture-operator', principal_type=PrincipalType.LOCAL_OPERATOR,
                          permissions=frozenset({'project.authority.execute', 'book_design.authority.execute'}),
                          project_scope=frozenset({project_id}), authentication_source='integration-fixture')
    project_app = ProjectAuthorityApplication(DATABASE_URL, application_build_id='shared-pilot-fixture', commit_sha='b'*40)
    project_app.execute(ProjectAuthorityCommand(definition_name='project_lifecycle.create', project_id=project_id,
        workspace_id=workspace_id, actor_id=principal.principal_id, idempotency_key=f'{project_id}:source-project',
        trace_id=f'trace:{project_id}', correlation_id=project_id, payload={'title':'Existing source project'}), principal=principal)
    source_id = source_fixture.MkaosAuthorityPostgresTests()._source_chunk_version(project_id=project_id, workspace_id=workspace_id)
    book_app = BookDesignAuthorityApplication(DATABASE_URL, application_build_id='shared-pilot-fixture', commit_sha='b'*40)
    composition = SimpleNamespace(formation=SimpleNamespace(generation=SimpleNamespace(book_design=book_app)))
    return project_id, workspace_id, principal, project_app, composition, source_id


def _initialize(scope, *, run_key, book_id=None, workspace_id=None, principal=None):
    project_id, primary_workspace, operator, _, composition, _ = scope
    run_key = f'{project_id}:{run_key}'
    frozen = {'run_key':run_key, 'implementation_identity':'sha256:'+'c'*64,
              'creation_policy':{'profiles':{'production_profile':{'content':{'target_chapter_count':180,
                  'knowledge_access_policy':{'mode':'DENY_ALL','allowed_knowledge_card_asset_version_ids':[]}}}}}}
    return prepare_pilot_book(composition=composition, principal=principal or operator, project_id=project_id,
        workspace_id=workspace_id or primary_workspace, book_id=book_id or f'{project_id}:{run_key}', run_key=run_key,
        title=f'Independent {run_key}', frozen=frozen, initialize=True)


def test_existing_source_project_initializes_and_replays_owned_book_without_project_recreate(pilot_project):
    project_id, workspace_id, principal, _, _, source_id = pilot_project
    before = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
    context, effect_id = budget_fixture.ProviderBudgetRuntimePostgresTests()._effect_for_project(project_id)
    reservation = reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
        operation_id=context.operation_id, external_effect_id=effect_id, project_id=project_id,
        stable_idempotency_key=f'budget:{effect_id}', provider='fake_deterministic_provider', currency='UNKNOWN',
        estimated_amount=None, estimated_tokens=100, accounting_basis='ACCOUNT_ENTITLEMENT',
        cost_authorization_ref='fixture:prior-source-allocation', call_caps={'project_total':1}, token_caps={'project_total':1000},
    ))
    resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservation['reservation_id'],
                                    project_id=project_id, external_state_unknown=True)
    with transaction() as connection:
        budget_before = connection.execute('SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE reservation_id=%s',
                                           [reservation['reservation_id']]).fetchone()[0]
    book = _initialize(pilot_project, run_key='arm-a')
    replay = _initialize(pilot_project, run_key='arm-a')
    assert replay == book
    assert book['project_id'] == project_id and book['workspace_id'] == workspace_id
    after = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
    for field in ('version','title','asset_version_id','created_by_operation_id','last_operation_id'):
        assert after[field] == before[field]
    with transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM authority_source_chunk WHERE project_id=%s AND asset_version_id=%s', [project_id,source_id]).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM authority_operation WHERE project_id=%s AND definition_name='project_lifecycle.create'", [project_id]).fetchone()[0] == 1
        assert connection.execute('SELECT to_jsonb(b) FROM authority_budget_reservation b WHERE reservation_id=%s',
                                  [reservation['reservation_id']]).fetchone()[0] == budget_before
    other_context, other_effect = budget_fixture.ProviderBudgetRuntimePostgresTests()._effect_for_project(project_id)
    with pytest.raises(KernelError, match='BUDGET_CALL_CAP_EXCEEDED'):
        reserve_provider_budget(DATABASE_URL, BudgetReservationRequest(
            operation_id=other_context.operation_id, external_effect_id=other_effect, project_id=project_id,
            stable_idempotency_key=f'budget:{other_effect}', provider='fake_deterministic_provider', currency='UNKNOWN',
            estimated_amount=None, estimated_tokens=100, accounting_basis='ACCOUNT_ENTITLEMENT',
            cost_authorization_ref='fixture:prior-source-allocation', call_caps={'project_total':1}, token_caps={'project_total':1000},
        ))
    with pytest.raises(PermissionError):
        _initialize(pilot_project, run_key='denied', principal=replace(principal, permissions=frozenset()))


def test_second_book_keeps_workspace_guard_and_new_project_initializes_independently(pilot_project):
    project_id, workspace_id, principal, _, composition, _ = pilot_project
    first = _initialize(pilot_project, run_key='arm-a')
    with pytest.raises(KernelError, match='BOOK_SCOPE_CONFLICT'):
        _initialize(pilot_project, run_key='same-workspace-second-book')
    with transaction() as connection:
        assert connection.execute('SELECT book_id FROM authority_workspace WHERE workspace_id=%s', [workspace_id]).fetchone()[0] == first['book_id']
        assert connection.execute('SELECT COUNT(*) FROM authority_book WHERE project_id=%s', [project_id]).fetchone()[0] == 1
    control_project, control_workspace = identifier('control-pilot-project'), identifier('control-pilot-workspace')
    control_scope = (control_project, control_workspace, replace(principal, project_scope=frozenset({control_project})),
                     None, composition, None)
    control = _initialize(control_scope, run_key='arm-b')
    assert _initialize(control_scope, run_key='arm-b') == control
    assert control['project_id'] == control_project and control['workspace_id'] == control_workspace
    assert control['production_profile']['knowledge_access_policy']['mode'] == 'DENY_ALL'
    with transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM authority_source_chunk WHERE project_id=%s', [control_project]).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM authority_operation WHERE project_id=%s AND definition_name='project_lifecycle.create'", [control_project]).fetchone()[0] == 1


@pytest.mark.parametrize('fault', ['foreign_workspace','PAUSED','ARCHIVED','DELETED'])
def test_existing_project_scope_and_lifecycle_are_checked_before_book_creation(pilot_project, fault):
    project_id, workspace_id, principal, project_app, _, _ = pilot_project
    if fault != 'foreign_workspace':
        current = ProjectAuthorityQuery(DATABASE_URL).require_project(project_id)
        project_app.execute(ProjectAuthorityCommand(definition_name='project_lifecycle.transition', project_id=project_id,
            workspace_id=workspace_id, actor_id=principal.principal_id, expected_version=current['version'],
            expected_current_asset_version_id=current['asset_version_id'], idempotency_key=f'{project_id}:{fault}',
            trace_id=f'trace:{project_id}', correlation_id=project_id, payload={'target_status':fault}), principal=principal)
    with pytest.raises((KernelError, ValueError), match='workspace|ACTIVE|active'):
        _initialize(pilot_project, run_key='blocked', workspace_id=workspace_id+':foreign' if fault=='foreign_workspace' else workspace_id)
    with transaction() as connection:
        assert connection.execute('SELECT COUNT(*) FROM authority_book WHERE project_id=%s', [project_id]).fetchone()[0] == 0
