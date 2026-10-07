import pytest
from novel_forge.modules.book_authority.member_retry import eligible_retry


@pytest.mark.parametrize('row',[
    ('foreign',3,1,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','grant'),
    ('actor',3,3,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','grant'),
    ('actor',3,1,'REVIEW_EVIDENCE_INVALID','grant'),
    ('actor',3,1,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','other-grant'),
])
def test_waiting_cannot_expand_attempts_or_borrow_other_identity_or_host_failures(row):
    assert not eligible_retry(row,'actor','grant')


def test_known_transport_wait_retains_current_operation_bounds_and_authorization():
    assert eligible_retry(('actor',3,1,'MODEL_EFFECT_RETRYABLE_PROCESS_EXIT_FAILURE','grant'),'actor','grant')


def test_known_settled_host_repairs_require_their_explicit_successor_contract():
    for code, version in [("CHAPTER_LENGTH_REPAIR_INCOMPLETE", "3.9.26"), ("CANON_QUOTE_LOCALIZATION_INVALID", "3.9.29")]:
        assert not eligible_retry(("actor", 2, 1, code, "grant"), "actor", "grant")
        assert not eligible_retry(("actor", 2, 1, code, "grant", "3.9.24"), "actor", "grant")
        assert eligible_retry(("actor", 2, 1, code, "grant", version), "actor", "grant")
        assert not eligible_retry(("actor", 2, 2, code, "grant", version), "actor", "grant")


def test_current_semantic_successor_keeps_known_quote_retry_bounded():
    assert eligible_retry(('actor', 2, 1, 'CANON_QUOTE_LOCALIZATION_INVALID', 'grant', '3.9.30'), 'actor', 'grant')
    assert not eligible_retry(('actor', 2, 2, 'CANON_QUOTE_LOCALIZATION_INVALID', 'grant', '3.9.30'), 'actor', 'grant')


@pytest.mark.parametrize('version', ['3.10.0', '3.10.1'])
@pytest.mark.parametrize('name', ['chapter.revision.apply', 'chapter.canon.extract', 'chapter.memo.generate'])
@pytest.mark.parametrize('error', ['CHAPTER_LENGTH_REPAIR_INCOMPLETE', 'CANON_QUOTE_LOCALIZATION_INVALID'])
def test_current_host_retry_requires_exact_version_and_owner_name(version, name, error):
    expected = version == '3.10.0' and ((name == 'chapter.revision.apply' and error == 'CHAPTER_LENGTH_REPAIR_INCOMPLETE')
                                      or (name == 'chapter.canon.extract' and error == 'CANON_QUOTE_LOCALIZATION_INVALID'))
    assert eligible_retry(('actor', 2, 1, error, 'grant', version, name), 'actor', 'grant') is expected
    assert not eligible_retry(('actor', 2, 1, error, 'grant', version), 'actor', 'grant')


@pytest.mark.parametrize('boundary', ['known', 'unknown-sibling', 'held-sibling', 'live-lease', 'foreign-actor',
                                      'foreign-workspace', 'creation-cancelled', 'deadline'])
def test_member_wait_requires_live_original_settled_graph_before_sleep(monkeypatch, boundary):
    from types import SimpleNamespace
    from novel_forge.modules.book_authority import member_retry as retry
    from novel_forge.modules.command_kernel.errors import KernelError

    template = dict(version='creative-execution-template.v11', mode='CREATIVE_VALIDATION', book_id='book', member_authorization_ref='grant')
    admission = {'policy_snapshot': {'policy': {'execution_templates': [template]}}}
    monkeypatch.setattr(retry, 'selected_book_template', lambda *a, **k: admission)
    monkeypatch.setattr(retry, 'selected_template', lambda *a: template)
    monkeypatch.setattr(retry, 'monotonic', lambda: 1)
    sleeps = []
    monkeypatch.setattr(retry, 'sleep', sleeps.append)
    flags = [boundary == 'unknown-sibling', boundary == 'held-sibling', boundary == 'live-lease']
    graph = ('foreign' if boundary == 'foreign-actor' else 'actor', 'foreign' if boundary == 'foreign-workspace' else 'workspace', *flags)
    class Cursor:
        def __init__(self):
            self.rows = iter([('book-run', 'CHAPTER_RUNNING', 'RUNNING', boundary == 'creation-cancelled'), graph])
        def execute(self, *args):
            pass
        def fetchone(self):
            return next(self.rows)
        def fetchall(self):
            return [('actor', 2, 1, 'CANON_QUOTE_LOCALIZATION_INVALID', 'grant', '3.10.0', 'chapter.canon.extract')]
    class UnitOfWork:
        def __init__(self, _):
            self.cursor = Cursor()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(retry, 'AuthorityUnitOfWork', UnitOfWork)
    principal = SimpleNamespace(principal_id='actor', require=lambda *a: None)
    book = dict(project_id='project', workspace_id='workspace', book_id='book')
    authority = SimpleNamespace(database_url='offline', require=lambda _: book)
    values = dict(book_run_id='book-run', root_id='root', principal=principal, deadline=1 if boundary == 'deadline' else 10)
    if boundary in {'foreign-actor', 'foreign-workspace', 'creation-cancelled'}:
        with pytest.raises(KernelError):
            retry.wait_settled_member_retry(authority, **values)
    else:
        assert retry.wait_settled_member_retry(authority, **values) is (boundary == 'known')
    assert sleeps == ([9] if boundary == 'known' else [])
