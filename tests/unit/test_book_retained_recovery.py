from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from novel_forge.modules.book_authority.retained_recovery import _require_frontier
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.mark.parametrize('boundary', ['known', 'cancelled', 'accepted', 'foreign-book', 'foreign-project',
    'foreign-workspace', 'foreign-actor', 'foreign-chapter', 'old-reference', 'future-version', 'unknown-root', 'creation-cancelled'])
def test_retained_graph_cannot_borrow_cancelled_accepted_or_foreign_book_frontier(boundary):
    book = dict(book_run_id='book-run', book_id='book', project_id='project', workspace_id='workspace',
        active_chapter_request_id='request', accepted_through_chapter=0, state='CHAPTER_RUNNING')
    request = dict(chapter_request_id='request', book_run_id='book-run', project_id='project', chapter_number=1,
        chapter_root_operation_id='root', status_reference='FAILED_FINAL')
    root = dict(operation_id='root', project_id='project', workspace_id='workspace', actor_id='actor',
        definition_name='chapter.slice.run', definition_version='3.10.0', status='FAILED_FINAL',
        command_payload={'book_id': 'book', 'chapter': 1})
    if boundary == 'cancelled':
        book['state'] = 'CANCELLED'
    if boundary == 'accepted':
        book['accepted_through_chapter'] = 1
    if boundary == 'foreign-book':
        request['book_run_id'] = 'foreign'
    if boundary == 'foreign-project':
        request['project_id'] = 'foreign'
    if boundary == 'foreign-workspace':
        root['workspace_id'] = 'foreign'
    if boundary == 'foreign-actor':
        root['actor_id'] = 'foreign'
    if boundary == 'foreign-chapter':
        root['command_payload']['chapter'] = 2
    if boundary == 'old-reference':
        book['active_chapter_request_id'] = 'new-current-request'
    if boundary == 'future-version':
        root['definition_version'] = '3.10.1'
    if boundary == 'unknown-root':
        root['status'] = 'UNKNOWN'
    cursor = Mock()
    cursor.fetchone.return_value = ('book-run', 'CHAPTER_RUNNING', 'FAILED_FINAL', boundary == 'creation-cancelled')
    frozen = deepcopy((book, request, root))
    if boundary == 'known':
        _require_frontier(cursor, book=book, request=request, root=root, principal=SimpleNamespace(principal_id='actor'))
    else:
        with pytest.raises(KernelError):
            _require_frontier(cursor, book=book, request=request, root=root, principal=SimpleNamespace(principal_id='actor'))
    assert (book, request, root) == frozen
