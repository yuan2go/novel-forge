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
