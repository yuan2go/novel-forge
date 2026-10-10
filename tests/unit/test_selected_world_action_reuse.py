from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.world_preparation import require_selected_world_action

MODULE = 'novel_forge.modules.story_planning_runtime.world_preparation'
RUNTIME = 'novel_forge.modules.command_kernel.external_effect_runtime'


def fixtures():
    command = SimpleNamespace(project_id='project', workspace_id='workspace', book_id='book', actor_id='actor', trace_id='trace', correlation_id='correlation', governance_action_version_ids=('action',), world_preparation_request={'accepted_through_chapter': 0})
    def doc(key, body):
        return SimpleNamespace(asset_version_id=key, content_hash=key+'-hash', content={'contract': body})
    refs = {key: {'asset_version_id': key, 'content_hash': key+'-hash'} for key in ('source', 'generation', 'evaluation')}
    plan = {'disposition': 'ELIGIBLE', 'plan_digest': 'digest'}
    source = {'request': dict(command.world_preparation_request), 'contract_version': 'world-preparation-source.v1', 'reality': {}, 'policy': {}, 'intent_version_id': 'intent'}
    generation = {'source': refs['source'], 'output': {'candidates': []}, 'evidence': {'external_receipt_ref': 'generation-effect'}}
    evaluation = {'source': refs['source'], 'generation': refs['generation'], 'output': {'evaluation': []}, 'evidence': {'external_receipt_ref': 'evaluation-effect'}}
    action = {'contract_version': 'world-production-action.v1', 'project_id': 'project', 'book_id': 'book', 'actor_id': 'actor', 'authority': 'PLANNING_PROPOSAL', 'fact_mutation_allowed': False, 'world_plan': plan, **refs}
    docs = {key: doc(key, body) for key, body in [('action', action), ('source', source), ('generation', generation), ('evaluation', evaluation)]}
    return command, docs, plan


@pytest.mark.parametrize('disposition', ['ELIGIBLE', 'DEFER'])
@pytest.mark.parametrize('failure', ['none', 'book', 'actor', 'workspace', 'frontier', 'stale', 'hash', 'director-binding', 'unsettled', 'receipt-output', 'recompile', 'ambiguous'])
def test_selected_action_reuses_only_exact_current_settled_world_result(failure, disposition):
    command, docs, plan = fixtures()
    plan.update(disposition=disposition, fact_mutation_allowed=False)
    if failure in {'book', 'actor'}:
        docs['action'].content['contract'][failure+'_id'] = 'other'
    if failure == 'frontier':
        command.world_preparation_request = {'accepted_through_chapter': 1}
    if failure == 'hash':
        docs['generation'].content_hash = 'wrong'
    if failure == 'director-binding':
        docs['evaluation'].content['contract']['generation'] = {'asset_version_id': 'other', 'content_hash': 'other'}
    if failure == 'ambiguous':
        command.governance_action_version_ids = ('action', 'action')
    query = SimpleNamespace(database_url='db', require=lambda **kw: docs[kw['asset_version_id']])
    uow = MagicMock()
    uow.__enter__.return_value = uow
    def fetch():
        sql = uow.cursor.execute.call_args[0][0]
        return ('SUCCEEDED',) if 'SELECT status' in sql else ('other' if failure == 'workspace' else 'workspace', 'actor', 'book')
    uow.cursor.fetchone.side_effect = fetch
    def receipt(_db, _context, *, effect_id):
        key = effect_id.removesuffix('-effect')
        return {'budget_reservation_status': 'RESERVED' if failure == 'unsettled' else 'SETTLED', 'provider_evidence': {'result': {} if failure == 'receipt-output' else docs[key].content['contract']['output']}}
    with patch(MODULE+'.AuthorityUnitOfWork', return_value=uow), patch(MODULE+'.WorldPreparationRepository', autospec=True) as repository, patch(MODULE+'.PlanningWorldPreparation._source_operation', return_value='owner'), patch(MODULE+'.PlanningWorldPreparation.validate_retained_generation') as validate, patch(MODULE+'.decode_world_generation', return_value={}), patch(MODULE+'.WorldProductionPolicy'), patch(MODULE+'.compile_world_plan', return_value=deepcopy(plan) if failure != 'recompile' else {'disposition': 'BLOCKED'}), patch(RUNTIME+'.read_completed_operation_success', side_effect=receipt) as read, patch(RUNTIME+'.read_retained_generation_stage_success', side_effect=AssertionError('wrong owner reader')):
        if failure == 'stale':
            repository.return_value.assert_source_current.side_effect = KernelError('WORLD_SOURCE_DRIFT', 'changed source')
        if failure == 'none':
            assert require_selected_world_action(query, command=command) is docs['action']
            assert read.call_count == 2
            validate.assert_called_once()
        else:
            with pytest.raises(KernelError):
                require_selected_world_action(query, command=command)


def test_unselected_action_keeps_existing_generation_path():
    command, docs, _ = fixtures()
    command.governance_action_version_ids = ()
    assert require_selected_world_action(SimpleNamespace(), command=command) is None


@pytest.mark.parametrize('dependency', ['selected_candidate_id', 'selected_path_id', 'candidate_futures', 'preparation_schedule', 'causal_debts', 'actor_proposals', 'actor_experiment', 'preparation_sources', 'fact_mutation_allowed'])
def test_deferred_reuse_cannot_discard_a_dependency_or_certify_a_future(dependency):
    command, docs, plan = fixtures()
    plan.update(disposition='DEFER', fact_mutation_allowed=False)
    target = docs['source'].content['contract'] if dependency in {'actor_experiment', 'preparation_sources'} else docs['action'].content['contract'] if dependency == 'actor_proposals' else plan
    target[dependency] = True
    query = SimpleNamespace(database_url='db', require=lambda **kw: docs[kw['asset_version_id']])
    uow = MagicMock()
    uow.__enter__.return_value = uow
    uow.cursor.fetchone.return_value = ('workspace', 'actor', 'book')
    with patch(MODULE+'.AuthorityUnitOfWork', return_value=uow), patch(MODULE+'.PlanningWorldPreparation._source_operation', return_value='owner'):
        with pytest.raises(KernelError):
            require_selected_world_action(query, command=command)
