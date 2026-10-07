from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.execution_window import _current_length_source, _current_continued_attempt_limit
from novel_forge.modules.chapter_authority.quality_correction_control import require_next_pass


def source():
    root = {'operation_id': 'root', 'definition_version': '3.10.0', 'project_id': 'p', 'workspace_id': 'w',
            'actor_id': 'author', 'command_payload': {}}
    child = {**root, 'operation_id': 'revision', 'root_operation_id': 'root', 'definition_name': 'chapter.revision.apply',
        'definition_snapshot': {'policy': {'quality_range_policy': 'NAMED_DIAGNOSIS_UNION_V1',
            'candidate_retry_feedback': 'chapter-candidate-retry-feedback.v2', 'chapter_length_scope': 'chapter-length-repair.v1'}}}
    return root, child, ('FAILED_RETRYABLE', 'CHAPTER_LENGTH_REPAIR_INCOMPLETE', 'author', 'chapter.revision.apply')


def test_current_length_phase_is_distinct_and_requires_bounded_repair_phase():
    root, child, failure = source()
    assert _current_length_source(root, child, failure, True)
    assert not _current_length_source(root, child, failure, False)


@pytest.mark.parametrize('field,value', [('definition_version', '3.10.1'), ('root_operation_id', 'other'),
    ('actor_id', 'other'), ('workspace_id', 'other'), ('project_id', 'other'), ('definition_name', 'chapter.draft.generate')])
def test_current_length_phase_cannot_borrow_future_or_foreign_source(field, value):
    root, child, failure = source()
    child[field] = value
    assert not _current_length_source(root, child, failure, True)


@pytest.mark.parametrize('owner,key', [('root', 'business_deadline_at'), ('root', 'author_deadline_at'),
    ('child', 'business_deadline_at'), ('child', 'author_deadline_at')])
def test_current_length_phase_preserves_author_deadline(owner, key):
    root, child, failure = source()
    root['command_payload'] = {}
    child['command_payload'] = {}
    (root if owner == 'root' else child)['command_payload'][key] = 'fixed'
    with pytest.raises(KernelError, match='EXECUTION_WINDOW_AUTHOR_DEADLINE'):
        _current_length_source(root, child, failure, True)


class Evidence:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params):
        self.sql = sql

    def fetchone(self):
        return self.row


def test_current_control_extension_never_resets_frozen_paid_attempt_limit(monkeypatch):
    from novel_forge.modules.command_kernel import execution_window, step_successor_v2, derived_step_revalidation
    calls = []
    monkeypatch.setattr(execution_window, 'require_live_chapter_frontier', lambda cursor, **scope: calls.append(scope))
    monkeypatch.setattr(step_successor_v2, '_require_reconciled_graph', lambda *args, **scope: calls.append(scope))
    monkeypatch.setattr(derived_step_revalidation, '_settled_graph', lambda *args: None)
    assert _current_continued_attempt_limit(Evidence(None), 'revision', 'p', 2) is None
    frozen = {'original_attempt_limit': 2, 'control_recovery_attempt_limit': 3}
    assert _current_continued_attempt_limit(Evidence((frozen, 2, "root")), 'revision', 'p', 2) == 3
    for original, limit in ((3, 2), (2, 3)):
        assert _current_continued_attempt_limit(Evidence((frozen, limit, "root")), 'revision', 'p', original) == original
    changed = deepcopy(frozen)
    changed['control_recovery_attempt_limit'] = 4
    assert _current_continued_attempt_limit(Evidence((changed, 2, "root")), 'revision', 'p', 2) == 2


@pytest.mark.parametrize('passes,hashes,code', [(3, ['a', 'b', 'c'], 'QUALITY_CORRECTION_CONTROL_EXHAUSTED'),
    (2, ['same', 'same', 'same'], 'QUALITY_CORRECTION_NO_PROGRESS')])
def test_current_length_phase_does_not_override_authority_progress_limits(passes, hashes, code):
    with pytest.raises(KernelError, match=code):
        require_next_pass(completed_passes=passes, candidate_hashes=hashes,
            control={'maximum_passes': 3, 'maximum_unchanged_candidates': 2})


def test_recorded_v6_control_extension_cannot_run_after_book_cancellation(monkeypatch):
    from novel_forge.modules.command_kernel import execution_window
    def cancelled(*args, **scope):
        raise KernelError('CHAPTER_RECOVERY_FRONTIER_CANCELLED', 'Original Creation was cancelled')
    monkeypatch.setattr(execution_window, 'require_live_chapter_frontier', cancelled)
    with pytest.raises(KernelError, match='CHAPTER_RECOVERY_FRONTIER_CANCELLED'):
        _current_continued_attempt_limit(Evidence(({'original_attempt_limit': 2, 'control_recovery_attempt_limit': 3}, 2, 'root')), 'revision', 'p', 2)
