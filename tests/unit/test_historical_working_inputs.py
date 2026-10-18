from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority import manuscript as m
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.chapter_authority_repositories import AuthorityHandlerRepository


def operation(source_chapter=18, target=19):
    working = {'book_run_id': 'run', 'target_chapter': target,
               'sources': [{'chapter': source_chapter, 'asset_version_id': 'draft', 'content_hash': 'hash'}]}
    return {'definition_name': 'story_planning.generate', 'project_id': 'p', 'workspace_id': 'w',
            'operation_id': 'op', 'command_payload': {'payload': {'book_id': 'book',
            'arc_working_set': {'working_manuscript': working}}},
            'input_asset_snapshot': [{'asset_version_id': 'draft', 'content_hash': 'hash'}]}


def fixture(monkeypatch):
    cursor = Mock()
    cursor.fetchone.return_value = ({'project_id': 'p', 'workspace_id': 'w', 'book_id': 'book',
                                   'book_run_id': 'run', 'current_chapter': 18},)
    monkeypatch.setattr(m, 'effective_workflow', lambda *a: m.AUTHOR_WORKFLOW)
    verify = Mock()
    monkeypatch.setattr(m, 'verify_working_context', verify)
    return SimpleNamespace(cursor=cursor), verify


def test_exact_working_history_retains_book_and_hash_verification(monkeypatch):
    uow, verify = fixture(monkeypatch)
    assert m.historical_working_inputs(uow, operation()) == ('book', frozenset({'draft'}))
    verify.assert_called_once()


@pytest.mark.parametrize('source,target', [(19, 19), (20, 19), (0, 19), (18, 20), (18, 18)])
def test_future_or_wrong_frontier_is_closed(monkeypatch, source, target):
    uow, _ = fixture(monkeypatch)
    with pytest.raises(KernelError, match='preceding writing history'):
        m.historical_working_inputs(uow, operation(source, target))


def test_hash_drift_is_closed(monkeypatch):
    uow, _ = fixture(monkeypatch)
    op = operation()
    op['input_asset_snapshot'][0]['content_hash'] = 'changed'
    with pytest.raises(KernelError, match='exact frozen input hashes'):
        m.historical_working_inputs(uow, op)


def test_foreign_owner_is_closed(monkeypatch):
    uow, _ = fixture(monkeypatch)
    uow.cursor.fetchone.return_value = None
    with pytest.raises(KernelError, match='exact author-first Book'):
        m.historical_working_inputs(uow, operation())


def test_obsolete_selection_is_closed(monkeypatch):
    uow, _ = fixture(monkeypatch)
    monkeypatch.setattr(m, 'verify_working_context', Mock(side_effect=KernelError('MANUSCRIPT_DEPENDENCY_CHANGED', 'changed')))
    with pytest.raises(KernelError, match='changed'):
        m.historical_working_inputs(uow, operation())


@pytest.mark.parametrize('kind,active_change,allowed', [
    ('draft_chapter', True, True), ('author_edit_candidate', True, True),
    ('draft_chapter', False, False), ('chapter_execution_intent', True, False)])
def test_only_active_plan_invalidation_of_verified_historical_prose_is_readable(kind, active_change, allowed):
    cursor = Mock()
    row = ('draft', kind, 'hash', {}, 'ACTIVE', 'ELIGIBLE', 'CLEAR', 'ELIGIBLE', 'policy')
    cursor.fetchone.side_effect = [row, ('invalidation', 'approved change'), (active_change,)]
    cursor.fetchall.return_value = []
    repository = AuthorityHandlerRepository(cursor)
    options = {'historical_working_book_id': 'book', 'historical_working_asset_version_ids': frozenset({'draft'})}
    if allowed:
        assert repository.frozen_inputs('p', [{'asset_version_id': 'draft', 'content_hash': 'hash'}], **options)[0]['asset_version_id'] == 'draft'
    else:
        with pytest.raises(KernelError, match='unresolved semantic invalidation'):
            repository.frozen_inputs('p', [{'asset_version_id': 'draft', 'content_hash': 'hash'}], **options)
    assert all('UPDATE' not in call.args[0] for call in cursor.execute.call_args_list)


def test_chapter_history_requires_exact_native_reservation(monkeypatch):
    uow, _ = fixture(monkeypatch)
    op = operation()
    op['definition_name'] = 'chapter.context.retrieve'
    payload = op['command_payload']['payload']
    op['command_payload'] = {'book_id': 'book', 'preparation_report': payload['arc_working_set']}
    uow.cursor.fetchone.side_effect = [({'project_id': 'p', 'workspace_id': 'w', 'book_id': 'book',
                                      'book_run_id': 'run', 'current_chapter': 18},), ({'different': True},)]
    with pytest.raises(KernelError, match='exact Book reservation'):
        m.historical_working_inputs(uow, op)


def test_post_delivery_review_gets_no_historical_exception(monkeypatch):
    uow, _ = fixture(monkeypatch)
    op = operation()
    op['definition_name'] = 'chapter.quality.evaluate'
    assert m.historical_working_inputs(uow, op) == ('', frozenset())
    uow.cursor.execute.assert_not_called()


def test_memo_indirect_history_keeps_only_its_own_frozen_inputs(monkeypatch):
    uow, verify = fixture(monkeypatch)
    op = operation()
    op['definition_name'] = 'chapter.memo.generate'
    payload = op['command_payload']['payload']
    op['command_payload'] = {'book_id': 'book', 'preparation_report': payload['arc_working_set']}
    op['input_asset_snapshot'] = [{'asset_version_id': 'current-intent', 'content_hash': 'intent-hash'}]
    assert m.historical_working_inputs(uow, op) == ('', frozenset())
    uow.cursor.execute.assert_not_called()
    verify.assert_not_called()


@pytest.mark.parametrize('facts', [(False,)*4, (True, False, False, False), (False, True, False, False),
                                  (False, False, True, False), (False, False, False, True)])
def test_indirect_memo_scope_successor_preserves_effects_outputs_and_retry_bound(facts):
    source = operation()
    source.update(definition_name='chapter.memo.generate', definition_version='3.10.0')
    payload = source['command_payload']['payload']
    source['command_payload'] = {'book_id': 'book', 'preparation_report': payload['arc_working_set']}
    source['input_asset_snapshot'] = [{'asset_version_id': 'intent', 'content_hash': 'intent-hash'}]
    policy = {'contract_version': 'chapter-historical-input-scope-repair.v1', 'input_snapshot': source['input_asset_snapshot'],
              'target_deployment_id': 'pack', 'release_sha': 'sha'}
    cursor = Mock()
    cursor.fetchall.return_value = [('MANUSCRIPT_INPUT_SNAPSHOT_MISSING', 'MANUSCRIPT_INPUT_SNAPSHOT_MISSING: Historical sources require exact frozen input hashes')]
    cursor.fetchone.side_effect = [facts, ('pack',)]
    if any(facts):
        with pytest.raises(KernelError, match='Preserve dispatched'):
            m.require_historical_input_scope_repair(cursor, source, policy, '3.10.0')
    else:
        assert m.require_historical_input_scope_repair(cursor, source, policy, '3.10.0')
    assert all('UPDATE' not in call.args[0] for call in cursor.execute.call_args_list)


def test_direct_history_cannot_use_indirect_memo_repair():
    source = operation()
    source.update(definition_name='chapter.memo.generate', definition_version='3.10.0')
    payload = source['command_payload']['payload']
    source['command_payload'] = {'book_id': 'book', 'preparation_report': payload['arc_working_set']}
    with pytest.raises(KernelError, match='exact indirect Memo'):
        m.require_historical_input_scope_repair(Mock(), source,
            {'contract_version': 'chapter-historical-input-scope-repair.v1', 'input_snapshot': source['input_asset_snapshot']}, '3.10.0')


def test_context_build_direct_history_uses_exact_book_reservation(monkeypatch):
    uow, verify = fixture(monkeypatch)
    op = operation()
    op['definition_name'] = 'chapter.context.build'
    payload = op['command_payload']['payload']
    op['command_payload'] = {'book_id': 'book', 'preparation_report': payload['arc_working_set']}
    uow.cursor.fetchone.side_effect = [({'project_id': 'p', 'workspace_id': 'w', 'book_id': 'book',
                                      'book_run_id': 'run', 'current_chapter': 18},), (payload['arc_working_set']['working_manuscript'],)]
    assert m.historical_working_inputs(uow, op) == ('book', frozenset({'draft'}))
    verify.assert_called_once()


@pytest.mark.parametrize('case,allowed', [('valid', True), ('accepted', False), ('active-child', False),
    ('cancelled', False), ('foreign-actor', False), ('missing-request', False), ('unbound-request', False),
    ('wrong-hash', False), ('unapproved-target', False)])
def test_current_unaccepted_planning_correction_requires_exact_native_change_request(monkeypatch, case, allowed):
    uow, verify = fixture(monkeypatch)
    book = {'project_id': 'p', 'workspace_id': 'w', 'book_id': 'book', 'book_run_id': 'run',
        'current_chapter': 18, 'accepted_through_chapter': 0, 'state': 'PAUSED',
        'active_chapter_request_id': None, 'stable_idempotency_key': 'formation:production'}
    op = operation(17, 18)
    op['actor_id'] = 'operator'
    payload = op['command_payload']['payload']
    payload.update(actor_id='operator', generator_operation_name='chapter_group_plan.generate', logical_key='chapter-group:13',
        change_evidence_version_ids=['change'])
    op['input_asset_snapshot'].append({'asset_version_id': 'change', 'content_hash': 'change-hash'})
    if case == 'accepted':
        book['accepted_through_chapter'] = 18
    if case == 'active-child':
        book['active_chapter_request_id'] = 'live'
    if case == 'cancelled':
        book['state'] = 'CANCELLED'
    if case == 'foreign-actor':
        payload['actor_id'] = 'foreign'
    if case == 'missing-request':
        payload['change_evidence_version_ids'] = []
    if case == 'unbound-request':
        op['input_asset_snapshot'].pop()
    uow.cursor.fetchone.side_effect = [(book,), (case not in {'wrong-hash', 'unapproved-target'},)]
    if allowed:
        assert m.historical_working_inputs(uow, op) == ('book', frozenset({'draft'}))
        verify.assert_called_once()
        sql = uow.cursor.execute.call_args_list[-1].args[0]
        assert 'active_story_plan_version' in sql and 'authority_operation_output_asset' in sql
        assert 'content_hash' in sql and 'authority_story_creation_cancellation' in sql
    else:
        with pytest.raises(KernelError, match='preceding writing history'):
            m.historical_working_inputs(uow, op)
        verify.assert_not_called()
