from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.creative_budget_contract import contract_hash
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.versioned_policy_repository import policy_hash
from scripts.creation_comparison import creation_resume_semantics
from scripts import creation_pilot
from tests.unit.test_creation_comparison import comparison_identities
from tests.unit.test_single_book_budget_contract import single_book_policy


def single_resume_inputs():
    identity = comparison_identities(Path('/tmp/fixture-single-resume-not-written'))[0]
    frozen = deepcopy(identity['frozen_configuration'])
    policy = single_book_policy(chapter=6, design=False)
    policy['comparison_budget']['arms'][0].update(project_id=identity['project_id'], book_id=identity['book_id'])
    policy['authorization'].update(project_id=identity['project_id'], book_id=identity['book_id'])
    frozen['comparison_budget'] = policy['comparison_budget']
    frozen['runtime_settings'].update(NOVEL_FORGE_PROJECT_PROVIDER_CALL_LIMIT='480', NOVEL_FORGE_PROJECT_PROVIDER_TOKEN_LIMIT='12000000',
                                      NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF=policy['authorization']['authorization_ref'])
    frozen['cost_accounting']['authorization_ref'] = policy['authorization']['authorization_ref']
    binding = {'owner': 'CREATIVE_EXPERIMENT_BUDGET', 'policy_version': policy['policy_version'], 'policy_hash': policy_hash(policy),
               'contract_hash': contract_hash(policy['comparison_budget']), 'subject_id': 'project:' + identity['project_id'],
               'authorization': policy['authorization']}
    return frozen, binding


@pytest.mark.parametrize('initialize', [False, True])
def test_existing_single_book_resumes_with_chapter_only_grant_without_new_design_permission(monkeypatch, initialize):
    frozen, binding = single_resume_inputs()
    normalized = creation_resume_semantics(frozen, binding)
    scope = frozen['runtime_identity']
    book = {'project_id': scope['project_id'], 'book_id': scope['book_id'], 'runtime_policy': {'creation_pilot': normalized}, 'version': 10}
    query = SimpleNamespace(require_book=Mock(return_value=book))
    monkeypatch.setattr(creation_pilot, 'BookDesignAuthorityQuery', lambda _: query)
    monkeypatch.setattr(creation_pilot, 'ProjectAuthorityQuery', lambda _: SimpleNamespace(require_project=Mock(return_value={'status': 'ACTIVE', 'workspace_id': scope['workspace_id']})))
    application = SimpleNamespace(database_url='not-connected', execute=Mock())
    composition = SimpleNamespace(formation=SimpleNamespace(generation=SimpleNamespace(book_design=application)))
    result = creation_pilot.prepare_pilot_book(
        composition=composition, principal=Mock(), project_id=scope['project_id'], workspace_id=scope['workspace_id'], book_id=scope['book_id'],
        run_key=frozen['run_key'], title='Existing design, chapter-only continuation', frozen=frozen, initialize=initialize, budget_binding=binding,
    )
    assert result == book
    assert binding['authorization']['business_scope']['design_allowed'] is False
    assert book['runtime_policy']['creation_pilot'] == normalized
    assert application.execute.call_count == int(initialize)
    if initialize:
        assert application.execute.call_args.args[0].definition_name == 'book.create'


def test_new_single_book_still_requires_design_before_any_initialization_mutation(monkeypatch):
    frozen, binding = single_resume_inputs()
    scope = frozen['runtime_identity']
    query = SimpleNamespace(require_book=Mock(side_effect=KernelError('BOOK_NOT_FOUND', 'No existing Book')))
    monkeypatch.setattr(creation_pilot, 'BookDesignAuthorityQuery', lambda _: query)
    application = SimpleNamespace(database_url='not-connected', execute=Mock())
    composition = SimpleNamespace(formation=SimpleNamespace(generation=SimpleNamespace(book_design=application)))
    with pytest.raises(ValueError, match='requires native design authorization'):
        creation_pilot.prepare_pilot_book(
            composition=composition, principal=Mock(), project_id=scope['project_id'], workspace_id=scope['workspace_id'], book_id=scope['book_id'],
            run_key=frozen['run_key'], title='New Book remains blocked', frozen=frozen, initialize=True, budget_binding=binding,
        )
    application.execute.assert_not_called()
