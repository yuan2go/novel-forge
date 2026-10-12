from types import SimpleNamespace

from novel_forge.modules.production_execution import saved_result_recovery as recovery
from novel_forge.modules.production_execution.backends import CodexCliExecutionBackend
from novel_forge.modules.production_execution.contracts import ExecutionOutcome, ExecutionRuntimeClass
from novel_forge.modules.command_kernel import generation_isolation
from tests.unit.test_production_execution_gateway import contracts


def test_orphaned_original_dispatch_is_checkpointed_before_isolation(monkeypatch):
    request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)[5]
    result = SimpleNamespace(outcome=ExecutionOutcome.ORPHANED)
    backend = object.__new__(CodexCliExecutionBackend)
    monkeypatch.setattr(backend, 'reconcile', lambda handle: result)
    record = SimpleNamespace(request=request, handle=SimpleNamespace(backend_id='codex-cli'))
    observed = {'original_execution': request.execution_id}
    calls = []
    monkeypatch.setattr(generation_isolation, 'checkpoint_orphaned_cli_dispatch',
        lambda *args, **kwargs: calls.append(kwargs) or True, raising=False)

    class Cursor:
        def execute(self, query, args):
            self.rows = [(request.execution_id,)] if 'SELECT DISTINCT' in query else []

        def fetchall(self):
            return self.rows

    class Uow:
        def __init__(self, *args):
            self.cursor = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(recovery, 'AuthorityUnitOfWork', Uow)
    session = SimpleNamespace(
        evidence_store=SimpleNamespace(get_record=lambda identity: record),
        gateway=SimpleNamespace(
            admission=SimpleNamespace(resolve_route=lambda req: SimpleNamespace(backend_id='codex-cli'),
                _admit_frozen_contracts=lambda *args: None),
            backends=SimpleNamespace(resolve=lambda identity: backend),
            _validate_result=lambda *args: None))
    transport = SimpleNamespace(session_for_project=lambda project: session,
        saved_result_evidence=lambda *args: observed)
    backend.capability_profile = SimpleNamespace()
    principal = SimpleNamespace(principal_id='operator', require=lambda *args: None)
    assert recovery.recover_saved_local_results(transport, database_url='db',
        project_id=request.project_id, book_id=request.book_id, principal=principal)
    assert len(calls) == 1
    assert calls[0]['execution_id'] == request.execution_id
    assert calls[0]['evidence'] == observed
    assert calls[0]['principal'] is principal
