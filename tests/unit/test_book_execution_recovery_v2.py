from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority import execution_recovery_v2 as recovery
from novel_forge.modules.command_kernel.errors import KernelError


class Cursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.queries = []

    def execute(self, sql, values=()):
        self.queries.append((sql, values))

    def fetchone(self):
        return next(self.rows)

    def fetchall(self):
        return next(self.rows)


class Principal:
    principal_id = 'operator'

    def require(self, permission, project):
        assert permission in {'book.authority.execute', 'chapter.authority.execute'}
        assert project == 'project'


@pytest.fixture
def source(monkeypatch):
    template = dict(mode='CREATIVE_VALIDATION', version='creative-execution-template.v11', book_id='book',
                    member_authorization_ref='grant', require_literary_qualification=False, require_independent_review=True)
    admission = {'policy_snapshot': {'policy': {'execution_templates': [template]}}}
    monkeypatch.setattr(recovery, 'selected_book_template', lambda *a, **k: deepcopy(admission))
    monkeypatch.setattr(recovery, 'verify_template_provenance', lambda *a: deepcopy(template))
    root = dict(operation_id='root', definition_name='chapter.slice.run', definition_version='3.8.0',
                project_id='project', workspace_id='workspace', actor_id='operator', status='WAITING_CHILDREN',
                command_payload={'book_id': 'book', 'chapter': 1})
    book = dict(book_run_id='book-run', project_id='project', workspace_id='workspace', book_id='book',
                active_chapter_request_id='request', accepted_through_chapter=0, state='CHAPTER_RUNNING')
    request = dict(chapter_request_id='request', project_id='project', book_run_id='book-run',
                   chapter_root_operation_id='root', chapter_number=1)
    effects = []
    for number in range(1, 3):
        payload = {'_production_execution': {'attempt_id': f'attempt-{number}', 'capability_runtime': {
            'pack_ref': 'chapter_generation@2.26.0', 'routing_decision': {'selected': {'candidate': {
                'provider': 'codex-cli', 'authorization_ref': 'grant', 'pricing': {'accounting_basis': 'ACCOUNT_ENTITLEMENT'}}}}}}}
        error = {'production_execution': {'execution_result': {'outcome': 'TIMED_OUT', 'started_at': None, 'process_receipt_ref': f'process-{number}'},
                                         'execution_handle': {'transport': 'LOCAL_CLI_REMOTE_INFERENCE'}, 'process_evidence': {'failure_code': 'PROCESS_TIMEOUT'}}}
        effects.append([f'effect-{number}', 'FAILED_RETRYABLE', f'hash-{number}', payload, error, 'SETTLED',
                        'chapter.memo.generate', '60', '2', 'memo', number, 'project', 'workspace', 'operator', '3.8.0'])
    return root, book, request, effects, admission


@pytest.mark.parametrize('boundary', ['known', 'unknown-graph', 'held-graph', 'lease-graph', 'missing-settlement',
    'output', 'missing-process-receipt', 'paid', 'foreign-effect-actor', 'foreign-request-book', 'duplicate-attempt',
    'mixed-operation', 'mixed-pack', 'unexhausted', 'future-memo', 'different-bound', 'started-remote', 'missing-start-proof', 'foreign-transport', 'future-source', 'old-template', 'accepted', 'cancelled-creation'])
def test_only_complete_stopped_settled_prefix_can_recover(source, monkeypatch, boundary):
    root, book, request, effects, admission = source
    flags = [False, False, False]
    if boundary in {'unknown-graph', 'held-graph', 'lease-graph'}:
        flags[{'unknown-graph': 0, 'held-graph': 1, 'lease-graph': 2}[boundary]] = True
    if boundary == 'missing-settlement':
        effects[0][5] = None
    if boundary == 'output':
        effects[0][4]['production_execution']['execution_result']['raw_output_ref'] = 'partial'
    if boundary == 'missing-process-receipt':
        effects[0][4]['production_execution']['execution_result'].pop('process_receipt_ref')
    if boundary == 'paid':
        effects[0][3]['_production_execution']['capability_runtime']['routing_decision']['selected']['candidate']['pricing']['accounting_basis'] = 'API_USAGE'
    if boundary == 'foreign-effect-actor':
        effects[1][-2] = 'foreign'
    if boundary == 'foreign-request-book':
        request['book_run_id'] = 'foreign'
    if boundary == 'duplicate-attempt':
        effects[1][10] = 1
    if boundary == 'mixed-operation':
        effects[1][9] = 'other-memo'
    if boundary == 'mixed-pack':
        effects[1][3]['_production_execution']['capability_runtime']['pack_ref'] = 'other@3.0.0'
    if boundary == 'unexhausted':
        effects = effects[:-1]
    if boundary == 'started-remote':
        effects[0][4]['production_execution']['execution_result']['started_at'] = '2026-10-07T00:00:00Z'
    if boundary == 'missing-start-proof':
        effects[0][4]['production_execution']['execution_result'].pop('started_at')
    if boundary == 'foreign-transport':
        effects[0][4]['production_execution']['execution_handle']['transport'] = 'LOCAL_PROCESS'
    if boundary == 'future-memo':
        effects[0][-1] = '3.8.1'
    if boundary == 'different-bound':
        effects[0][8] = '3'
    if boundary == 'future-source':
        root['definition_version'] = '3.10.1'
    if boundary == 'old-template':
        admission['policy_snapshot']['policy']['execution_templates'][0]['version'] = 'creative-execution-template.v10'
        monkeypatch.setattr(recovery, 'selected_book_template', lambda *a, **k: admission)
    cursor = Cursor([(root,), ('book-run', 'CHAPTER_RUNNING', 'RUNNING', boundary == 'cancelled-creation'), flags,
                     effects, (boundary == 'accepted',)])
    if boundary in {'unknown-graph', 'held-graph', 'lease-graph', 'foreign-request-book', 'cancelled-creation'}:
        with pytest.raises(KernelError):
            recovery.source_evidence(cursor, book=book, request=request, principal=Principal())
    else:
        result = recovery.source_evidence(cursor, book=book, request=request, principal=Principal())
        assert bool(result) == (boundary == 'known')
        if result:
            assert len(result['effects']) == 2
            assert all(effect['remote_usage'] == 'UNKNOWN' for effect in result['effects'])
            assert result['target_definition_version'] == '3.10.0'


@pytest.mark.parametrize('owned', [True, False])
def test_cancelled_predecessor_requires_unique_owned_recovery_command(source, owned):
    root, book, request, effects, _ = source
    root['status'] = 'CANCELLED'
    cursor = Cursor([(root,), ('book-run', 'CHAPTER_RUNNING', 'RUNNING', False), (1, 1) if owned else (2, 1),
                     (False, False, False), effects, (False,)])
    if owned:
        assert recovery.source_evidence(cursor, book=book, request=request, principal=Principal())
        assert cursor.queries[2][1][0].startswith('chapter-timeout-v2:')
    else:
        with pytest.raises(KernelError, match='owned recovery cancellation'):
            recovery.source_evidence(cursor, book=book, request=request, principal=Principal())


@pytest.mark.parametrize('binding', [{}, [], 'foreign', {'contract_version': recovery.CONTRACT}])
def test_invalid_v2_binding_fails_before_database(binding):
    with pytest.raises(KernelError, match='Invalid native execution successor binding'):
        recovery.require_dispatch('must-not-connect', command_payload={'preparation_report': {recovery.BINDING: binding}}, root_operation_id='root')


@pytest.mark.parametrize('boundary', ['known', 'cancelled-creation', 'accepted-frontier', 'foreign-actor', 'new-output',
                                      'held-later', 'lease-later', 'proof-drift', 'linked-foreign-root'])
def test_resume_rechecks_full_source_proof_before_submit(source, monkeypatch, boundary):
    root, book, predecessor, effects, admission = source
    predecessor.update(generation=1)
    root['status'] = 'CANCELLED'
    receipts = recovery._timeout_effects(Cursor([(False, False, False), effects]), root=root,
                                        target_template=admission['policy_snapshot']['policy']['execution_templates'][0])
    proof = recovery._source_proof(root, predecessor, admission, receipts)
    binding = dict(contract_version=recovery.CONTRACT, book_run_id='book-run', chapter_request_id='new',
                   predecessor_request_id='request', predecessor_root_operation_id='root', generation=2,
                   source_digest=recovery._proof_digest(proof), target_definition_version='3.10.0')
    frozen = dict(project_id='project', workspace_id='workspace', actor_id='operator', book_id='book', chapter=1,
                  preparation_report={recovery.BINDING: binding})
    request = dict(chapter_request_id='new', book_run_id='book-run', project_id='project', chapter_number=1, generation=2,
                   chapter_root_operation_id=None, status_reference='SUBMITTING',
                   command_payload={recovery.COMMAND: frozen, 'preparation_report': frozen['preparation_report']})
    book['active_chapter_request_id'] = 'new'
    flags = [False, boundary == 'held-later', boundary == 'lease-later']
    if boundary == 'accepted-frontier':
        book['accepted_through_chapter'] = 1
    if boundary == 'foreign-actor':
        root['actor_id'] = 'foreign'
    if boundary == 'new-output':
        effects[0][4]['production_execution']['execution_result']['output_manifest_ref'] = 'late-output'
    if boundary == 'proof-drift':
        effects[0][2] = 'foreign-hash'
    if boundary == 'linked-foreign-root':
        request['chapter_root_operation_id'] = 'foreign-root'
    row = (book, request, predecessor, root, boundary == 'cancelled-creation', False)
    cursor = Cursor([row, (1, 1), flags, effects])
    if boundary == 'known':
        assert recovery._require_successor_frontier(cursor, request=request, book=book, principal=Principal()) == (book, request)
    elif boundary == 'linked-foreign-root':
        with pytest.raises(KernelError):
            recovery._require_successor_frontier(cursor, request=request, book=book, principal=Principal())
    else:
        class UnitOfWork:
            def __init__(self, _):
                self.cursor = cursor
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        monkeypatch.setattr(recovery, 'AuthorityUnitOfWork', UnitOfWork)
        calls = []
        authority = SimpleNamespace(database_url='offline', require=lambda _: book, require_chapter_request=lambda _: request,
                                    chapter_port=SimpleNamespace(submit=lambda *a, **k: calls.append(a)))
        with pytest.raises(KernelError):
            recovery.resume_successor(authority, chapter_request_id='new', principal=Principal())
        assert calls == []
