from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority import execution_recovery as recovery
from novel_forge.modules.command_kernel.errors import KernelError


class Cursor:
    def __init__(self, root, effect, *, lease=False, accepted=False, cancelled=False):
        self.responses = iter([(root,), ('book-run','CHAPTER_RUNNING','RUNNING',cancelled), [effect], (lease,), (accepted,)])

    def execute(self, *args):
        pass

    def fetchone(self):
        return next(self.responses)

    def fetchall(self):
        return next(self.responses)


class Principal:
    principal_id = "operator"

    def require(self, permission, project):
        assert permission in {"book.authority.execute", "chapter.authority.execute"}
        assert project == "project"


@pytest.fixture
def source(monkeypatch):
    template = {
        "mode": "CREATIVE_VALIDATION",
        "book_id": "book",
        "member_authorization_ref": "grant",
        "require_literary_qualification": False,
        "require_independent_review": True,
    }
    monkeypatch.setattr(
        recovery,
        "selected_book_template",
        lambda *a, **k: {
            "policy_snapshot": {"policy": {"execution_templates": [template]}}
        },
    )
    monkeypatch.setattr(
        recovery, "verify_template_provenance", lambda *a: deepcopy(template)
    )
    root = {
        "operation_id": "root",
        "definition_version": "3.8.0",
        "command_payload": {"book_id":"book", "chapter":1},
        "project_id":"project", "workspace_id":"workspace",
        "actor_id": "operator",
        "status": "WAITING_CHILDREN",
    }
    book = {
        "project_id": "project",
        "book_id": "book",
        "book_run_id":"book-run", "workspace_id":"workspace",
        "state": "CHAPTER_RUNNING",
        "active_chapter_request_id": "request",
        "accepted_through_chapter": 0,
    }
    request = {
        "project_id":"project", "book_run_id":"book-run",
        "chapter_root_operation_id": "root",
        "chapter_request_id": "request",
        "chapter_number": 1,
    }
    candidate = {
        "provider": "codex-cli",
        "pricing": {"accounting_basis": "ACCOUNT_ENTITLEMENT"},
        "authorization_ref": "grant",
    }
    payload = {
        "_production_execution": {
            "capability_runtime": {
                "routing_decision": {"selected": {"candidate": candidate}}
            }
        }
    }
    error = {
        "production_execution": {
            "execution_result": {"outcome": "TIMED_OUT"},
            "process_evidence": {"failure_code": "PROCESS_TIMEOUT"},
        }
    }
    effect = [
        "effect",
        "FAILED_RETRYABLE",
        "hash",
        payload,
        error,
        "SETTLED",
        "chapter.memo.generate",
        "60",
    ]
    return root, book, request, effect, candidate, error


@pytest.mark.parametrize(
    "boundary",
    [
        "known",
        "unknown",
        "success",
        "held-reserve",
        "paid",
        "output",
        "foreign-actor",
        "accepted-frontier",
        "changed-grant",
        "lease",
        "accepted",
        "strict",
    ],
)
def test_only_known_preprose_member_timeout_is_eligible(source, monkeypatch, boundary):
    root, book, request, effect, candidate, error = source
    if boundary == "unknown":
        effect[1] = "UNKNOWN"
    if boundary == "success":
        effect[1] = "SUCCEEDED"
    if boundary == "held-reserve":
        effect[5] = "HELD"
    if boundary == "paid":
        candidate["pricing"]["accounting_basis"] = "API_USAGE"
    if boundary == "output":
        error["production_execution"]["execution_result"]["output_manifest_ref"] = (
            "partial"
        )
    if boundary == "foreign-actor":
        root["actor_id"] = "foreign"
    if boundary == "accepted-frontier":
        book["accepted_through_chapter"] = 1
    if boundary == "changed-grant":
        candidate["authorization_ref"] = "other-grant"
    if boundary == "strict":
        monkeypatch.setattr(recovery, "selected_book_template", lambda *a, **k: None)
    cursor = Cursor(
        root, effect, lease=boundary == "lease", accepted=boundary == "accepted"
    )
    if boundary == "lease":
        with pytest.raises(KernelError, match="Wait for the original execution lease"):
            recovery.source_evidence(
                cursor, book=book, request=request, principal=Principal()
            )
    else:
        result = recovery.source_evidence(
            cursor, book=book, request=request, principal=Principal()
        )
        assert bool(result) == (boundary == "known")


@pytest.mark.parametrize(
    "binding", [{}, [], "foreign", {"contract_version": recovery.CONTRACT}]
)
def test_malformed_execution_binding_fails_before_database(binding):
    with pytest.raises(KernelError, match="Invalid native execution successor binding"):
        recovery.require_dispatch(
            "must-not-connect",
            command_payload={"preparation_report": {recovery.BINDING: binding}},
            root_operation_id="root",
        )


@pytest.mark.parametrize('boundary', ['creation-cancelled', 'foreign-root-project', 'foreign-root-workspace',
                                      'foreign-request-book', 'foreign-request-project'])
def test_timeout_source_rejects_cancelled_creation_and_foreign_scope(source, boundary):
    root, book, request, effect, _, _ = source
    if boundary == 'foreign-root-project':
        root['project_id'] = 'foreign'
    if boundary == 'foreign-root-workspace':
        root['workspace_id'] = 'foreign'
    if boundary == 'foreign-request-book':
        request['book_run_id'] = 'foreign'
    if boundary == 'foreign-request-project':
        request['project_id'] = 'foreign'
    with pytest.raises(KernelError):
        recovery.source_evidence(Cursor(root, effect, cancelled=boundary == 'creation-cancelled'),
                                 book=book, request=request, principal=Principal())


class SuccessorCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, *args):
        pass

    def fetchone(self):
        return self.row


@pytest.fixture
def successor_frontier():
    book = dict(book_run_id='book-run', project_id='project', workspace_id='workspace', book_id='book',
                state='CHAPTER_SUBMITTED', active_chapter_request_id='new-request', accepted_through_chapter=0)
    predecessor = dict(chapter_request_id='old-request', book_run_id='book-run', project_id='project',
                       chapter_root_operation_id='old-root', chapter_number=1, generation=1)
    root = dict(operation_id='old-root', project_id='project', workspace_id='workspace',
                actor_id='operator', status='CANCELLED')
    binding = dict(contract_version=recovery.CONTRACT, book_run_id='book-run', chapter_request_id='new-request',
                   predecessor_request_id='old-request', predecessor_root_operation_id='old-root', generation=2)
    frozen = dict(project_id='project', workspace_id='workspace', book_id='book', chapter=1,
                  actor_id='operator', preparation_report={recovery.BINDING:binding})
    successor = dict(chapter_request_id='new-request', book_run_id='book-run', project_id='project',
                     chapter_root_operation_id=None, chapter_number=1, generation=2, status_reference='SUBMITTING',
                     command_payload={recovery.COMMAND:frozen, 'preparation_report':frozen['preparation_report']})
    return book, successor, predecessor, root, False


@pytest.mark.parametrize('boundary', ['known', 'cancelled-creation', 'aborted-book', 'accepted-frontier',
    'cancelled-successor', 'foreign-predecessor-book', 'foreign-predecessor-project', 'foreign-root-workspace',
    'forged-generation', 'forged-binding-root', 'forged-actor', 'already-linked-foreign-root'])
def test_successor_gate_before_submit_or_link_rejects_cancelled_or_forged_scope(successor_frontier, boundary):
    current, successor, predecessor, root, cancelled = deepcopy(successor_frontier)
    requested, book = deepcopy(successor), deepcopy(current)
    if boundary == 'cancelled-creation':
        cancelled = True
    if boundary == 'aborted-book':
        current['state'] = 'ABORTED'
    if boundary == 'accepted-frontier':
        current['accepted_through_chapter'] = 1
    if boundary == 'cancelled-successor':
        successor['status_reference'] = 'CANCELLED'
    if boundary == 'foreign-predecessor-book':
        predecessor['book_run_id'] = 'foreign'
    if boundary == 'foreign-predecessor-project':
        predecessor['project_id'] = 'foreign'
    if boundary == 'foreign-root-workspace':
        root['workspace_id'] = 'foreign'
    if boundary == 'forged-generation':
        successor['generation'] = 3
    if boundary == 'forged-binding-root':
        requested['command_payload'][recovery.COMMAND]['preparation_report'][recovery.BINDING]['predecessor_root_operation_id'] = 'foreign'
        successor['command_payload'] = deepcopy(requested['command_payload'])
    if boundary == 'forged-actor':
        requested['command_payload'][recovery.COMMAND]['actor_id'] = 'foreign'
        successor['command_payload'] = deepcopy(requested['command_payload'])
    if boundary == 'already-linked-foreign-root':
        successor['chapter_root_operation_id'] = 'foreign'
    cursor = SuccessorCursor((current, successor, predecessor, root, cancelled))
    if boundary == 'known':
        assert recovery._require_successor_frontier(cursor, request=requested, book=book,
                                                   principal=Principal()) == (current, successor)
    else:
        with pytest.raises(KernelError, match='CHAPTER_TIMEOUT_RECOVERY_CONFLICT'):
            recovery._require_successor_frontier(cursor, request=requested, book=book, principal=Principal())


@pytest.mark.parametrize('linked', [False, True])
def test_cancelled_creation_blocks_successor_resume_before_submit(successor_frontier, monkeypatch, linked):
    book, request, predecessor, root, _ = deepcopy(successor_frontier)
    if linked:
        request['chapter_root_operation_id'] = 'successor-root'
    row = (book, request, predecessor, root, True)
    class UnitOfWork:
        def __init__(self, _database_url):
            self.cursor = SuccessorCursor(row)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(recovery, 'AuthorityUnitOfWork', UnitOfWork)
    submissions = []
    authority = SimpleNamespace(database_url='offline', require_chapter_request=lambda _: request,
        require=lambda _: book, chapter_port=SimpleNamespace(submit=lambda *a, **k: submissions.append(a)))
    with pytest.raises(KernelError, match='CHAPTER_TIMEOUT_RECOVERY_CONFLICT'):
        recovery.resume_successor(authority, chapter_request_id=request['chapter_request_id'], principal=Principal())
    assert submissions == []


@pytest.mark.parametrize('cancelled', [False, True])
def test_successor_dispatch_checks_original_cancellation_from_native_book_scope(successor_frontier, monkeypatch, cancelled):
    book, request, _, _, _ = successor_frontier
    binding = request['command_payload']['preparation_report'][recovery.BINDING]
    row = ('successor-root', request['chapter_request_id'], 2, 'old-request', 0, 1,
           request['command_payload'], None, 'delegation', 'CANCELLED', False, 'project')
    class DispatchCursor:
        def __init__(self):
            self.rows = iter([row, ('book-run', 'CHAPTER_RUNNING', 'RUNNING', cancelled)])

        def execute(self, *args):
            pass

        def fetchone(self):
            return next(self.rows)

    class UnitOfWork:
        def __init__(self, _database_url):
            self.cursor = DispatchCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(recovery, 'AuthorityUnitOfWork', UnitOfWork)
    command = {'book_id':book['book_id'], 'chapter':1, 'preparation_report':{recovery.BINDING:binding}}
    if cancelled:
        with pytest.raises(KernelError, match='CHAPTER_RECOVERY_FRONTIER_CANCELLED'):
            recovery.require_dispatch('offline', command_payload=command, root_operation_id='successor-root')
    else:
        recovery.require_dispatch('offline', command_payload=command, root_operation_id='successor-root')
