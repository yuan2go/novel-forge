from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import preflight_continuation as recovery


def source_fixture(monkeypatch):
    from novel_forge.modules.book_authority import manuscript
    frozen = {'project_id': 'p', 'workspace_id': 'w', 'book_id': 'book',
        'execution_contract_version': '1.21.0', 'generator_operation_name': 'chapter_group_plan.generate',
        'repair_number': 0, 'change_evidence_version_ids': ['change'],
        'arc_working_set': {'working_manuscript': {'book_run_id': 'run', 'target_chapter': 16, 'snapshot_hash': 'working-hash'}}}
    failure = {'error_code': 'MANUSCRIPT_CONTEXT_INVALID',
        'error_message': 'MANUSCRIPT_CONTEXT_INVALID: Only the selected preceding writing history can be read'}
    operation = {'definition_snapshot': {'commit_sha': 'a' * 40},
        'input_asset_snapshot': [{'asset_version_id': 'change', 'content_hash': 'hash'}]}
    cursor = Mock()
    cursor.fetchone.side_effect = [(operation,), (16, 0, 'PAUSED', None), (False,), ('failed-attempt', 1)]
    snapshot = {'release_sha': 'a' * 40, 'pack_id': 'pack', 'pack_version': '2.19.0'}
    cursor.fetchall.return_value = [('parent-generation', snapshot, 'reference-snapshot', 'reference-hash')]
    doc = SimpleNamespace(asset_version_id='change', content_hash='hash', content={'target_plan_version_id': 'current-group'})
    uow = SimpleNamespace(cursor=cursor, repositories=SimpleNamespace(asset_documents=SimpleNamespace(require=Mock(return_value=doc))))
    verify = Mock(return_value=('book', frozenset({'previous-prose'})))
    monkeypatch.setattr(manuscript, 'historical_working_inputs', verify)
    return uow, ('FAILED_FINAL', 3), frozen, ('FAILED_FINAL', {}, failure), verify


@pytest.mark.parametrize('drift', ['', 'wrong-error', 'historical-contract', 'repair-counter', 'prior-continuation',
    'missing-change', 'active-child', 'accepted', 'wrong-frontier', 'cancelled', 'preparation-exists', 'input-hash', 'no-reference'])
def test_only_exact_stopped_unprepared_input_scope_failure_can_register(monkeypatch, drift):
    uow, row, frozen, attempt, verify = source_fixture(monkeypatch)
    if drift == 'wrong-error':
        attempt[2]['error_message'] = 'different failure'
    elif drift == 'historical-contract':
        frozen['execution_contract_version'] = '1.19.0'
    elif drift == 'repair-counter':
        frozen['repair_number'] = 1
    elif drift == 'prior-continuation':
        frozen['runtime_continuation_id'] = 'previous'
    elif drift == 'missing-change':
        frozen['change_evidence_version_ids'] = []
    elif drift in {'active-child', 'accepted', 'wrong-frontier', 'cancelled'}:
        checkpoint = {'active-child': (16, 0, 'PAUSED', 'active'), 'accepted': (16, 16, 'PAUSED', None),
            'wrong-frontier': (17, 0, 'PAUSED', None), 'cancelled': (16, 0, 'CANCELLED', None)}[drift]
        uow.cursor.fetchone.side_effect = [({'input_asset_snapshot': []},), checkpoint]
    elif drift == 'preparation-exists':
        uow.cursor.fetchone.side_effect = [({},), (16, 0, 'PAUSED', None), (True,)]
    elif drift == 'input-hash':
        uow.repositories.asset_documents.require.return_value.content_hash = 'changed'
    elif drift == 'no-reference':
        uow.cursor.fetchall.return_value = []
    if drift:
        with pytest.raises(KernelError, match='PLANNING_INPUT_SCOPE_'):
            recovery.require_input_scope_source(uow, source_operation_id='failed', row=row, frozen=frozen, attempt=attempt)
    else:
        source = recovery.require_input_scope_source(uow, source_operation_id='failed', row=row, frozen=frozen, attempt=attempt)
        assert source['snapshot'] is None and source['mode'] == recovery.INPUT_SCOPE_MODE
        assert source['depth'] == 1 and source['command']['repair_number'] == 0
        assert source['source_release_sha'] == 'a' * 40
        assert source['input_scope_failure']['source_attempt_id'] == 'failed-attempt'
        assert source['input_scope_failure']['reference_pack_snapshot_id'] == 'reference-snapshot'
        verify.assert_called_once()
        safety_query = uow.cursor.execute.call_args_list[2].args[0]
        for table in ['authority_external_effect', 'authority_budget_reservation', 'authority_operation_output_asset',
            'authority_attempt_capability_pack_snapshot', 'authority_lease_acquisition', 'authority_cancellation_command']:
            assert table in safety_query


def test_route_reference_never_becomes_a_failed_pack_or_source_call(monkeypatch):
    from novel_forge.modules.story_planning_runtime import runtime_continuation, database_recovery
    source = {'snapshot': None, 'source_release_sha': 'a' * 40, 'reference_snapshot': {'release_sha': 'a' * 40},
        'reference_operation_id': 'parent', 'input_scope_failure': {'source_pack_snapshot': None}}
    original = deepcopy(source)
    target = {'pack_snapshot': {'release_sha': 'b' * 40}}
    authorize = Mock(return_value={'capacity_only': True})
    receipt = Mock(return_value={'external_effect_id': 'parent-effect'})
    monkeypatch.setattr(runtime_continuation, '_capacity_authorization', authorize)
    monkeypatch.setattr(database_recovery, 'completed_reference_route', receipt)
    result = recovery.authorize_input_scope(None, source=source, successor=SimpleNamespace(repair_number=0), principal=None, target=target)
    assert source == original and source['snapshot'] is None
    assert authorize.call_args.kwargs['source']['snapshot'] == source['reference_snapshot']
    assert receipt.call_args.kwargs['reference_operation_id'] == 'parent'
    assert result['capacity_only'] is False and result['first_preparation'] == 'NATIVE_SUCCESSOR'
    assert result['route_reference_scope'] == 'TARGET_PLAN_COMPLETED_CALL_NOT_FAILED_SOURCE'
    assert result['preserved_repair_number'] == 0
    with pytest.raises(KernelError, match='PLANNING_INPUT_SCOPE_RELEASE_UNCHANGED'):
        recovery.authorize_input_scope(None, source=source, successor=None, principal=None,
            target={'pack_snapshot': {'release_sha': 'a' * 40}})


@pytest.mark.parametrize('upgrade', ['pack_version_successor', 'capacity_policy_upgrade', 'tool_policy_hash'])
def test_input_scope_recovery_does_not_authorize_a_pack_or_capacity_upgrade(monkeypatch, upgrade):
    from novel_forge.modules.story_planning_runtime import runtime_continuation, database_recovery
    monkeypatch.setattr(runtime_continuation, '_capacity_authorization', Mock(return_value={} if upgrade == 'tool_policy_hash' else {upgrade: {'verified': True}}))
    receipt = Mock()
    monkeypatch.setattr(database_recovery, 'completed_reference_route', receipt)
    with pytest.raises(KernelError, match='PLANNING_INPUT_SCOPE_PACK_CHANGED'):
        recovery.authorize_input_scope(None,
            source={'source_release_sha': 'a' * 40, 'reference_snapshot': {}},
            successor=None, principal=None, target={'pack_snapshot': {'release_sha': 'b' * 40, **({'tool_policy_hash': 'changed'} if upgrade == 'tool_policy_hash' else {})}})
    receipt.assert_not_called()
