from types import SimpleNamespace
from copy import deepcopy

import pytest

from novel_forge.modules.production_execution import saved_result_recovery as recovery
from novel_forge.modules.production_execution.backends import CodexCliExecutionBackend
from novel_forge.modules.production_execution.contracts import ExecutionOutcome, ExecutionRuntimeClass
from novel_forge.modules.command_kernel import generation_isolation
from tests.unit.test_production_execution_gateway import contracts
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import _hash
from novel_forge.modules.production_execution.backends import ResolvedExecutionPayload, _freeze_output_contract


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


@pytest.fixture
def reconciled_cli(tmp_path, monkeypatch):
    from novel_forge.modules.production_execution.process_supervisor import PosixProcessIdentityProbe
    monkeypatch.setattr(PosixProcessIdentityProbe, "is_alive", lambda self, pid: False)
    request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)[5]
    identity = {key: getattr(request, key) for key in ("execution_id", "operation_id", "attempt_id", "fencing_token")}
    payload = ResolvedExecutionPayload(request_payload={"input":"original"}, input_text="original",
        working_directory=str(tmp_path), timeout_seconds=30, output_schema_version="schema:v1", output_schema={"type":"object"})
    record = {"request":request.to_dict(), "handle":{**identity,"backend_id":"codex-cli","transport":"LOCAL_CLI_REMOTE_INFERENCE"},
        "result":{**identity,"outcome":"UNKNOWN","process_receipt_ref":"authority-asset-version:original-process"},
        "process_receipt":{**identity,"status":"FAILED","result_integrity":"MISSING","input_sha256":"a"*64,
            "process_group":{"pid":123456,"process_start_token":"original-start"}},
        "raw_evidence":{"capability_evidence":{"provider_request_envelope_hash":"sha256:original-envelope",
            "provider_view":{"component_hashes":{"fully_rendered_prompt":"sha256:"+"a"*64}}}},
        "frozen_output_contract":_freeze_output_contract(request,payload,_hash(payload.request_payload))}
    content = {"contract_version":"authority-execution-recovery.v1", "execution_id":request.execution_id,
        "request_contract_hash":request.contract_hash, "record":record, "record_state_hash":_hash(record).removeprefix("sha256:")}
    execution = {"execution_request":record["request"], "execution_handle":record["handle"], "execution_result":record["result"]}
    scope = dict(effect={"operation_id":request.operation_id,"external_effect_id":request.external_effect_id,
        "stable_idempotency_key":request.stable_idempotency_key},project_id=request.project_id,book_id=request.book_id,
        capability={"provider_request_envelope_hash":"sha256:original-envelope"})
    return content, execution, scope


def test_original_native_query_receipt_can_supply_missing_dispatch_receipt(reconciled_cli):
    content, execution, scope = reconciled_cli
    assert generation_isolation.require_reconciled_cli_isolation_record(content,execution,**scope) == content["record"]


@pytest.mark.parametrize("changed", ["book", "effect", "state_hash", "execution_result", "envelope", "process_identity", "handle_identity", "input_hash"])
def test_reconciled_receipt_cannot_cross_original_execution_or_hash_boundary(reconciled_cli, changed):
    content, execution, scope = deepcopy(reconciled_cli)
    if changed == "book":
        scope["book_id"] = "other-book"
    elif changed == "effect":
        scope["effect"]["external_effect_id"] = "other-effect"
    elif changed == "state_hash":
        content["record_state_hash"] = "0" * 64
    elif changed == "execution_result":
        execution["execution_result"] = {"outcome":"UNKNOWN"}
    elif changed == "envelope":
        scope["capability"]["provider_request_envelope_hash"] = "different-envelope"
    elif changed == "handle_identity":
        content["record"]["handle"]["attempt_id"] = "other-attempt"
        content["record_state_hash"] = _hash(content["record"]).removeprefix("sha256:")
    elif changed == "input_hash":
        content["record"]["process_receipt"]["input_sha256"] = "b"*64
        content["record_state_hash"] = _hash(content["record"]).removeprefix("sha256:")
    else:
        content["record"]["process_receipt"]["fencing_token"] += 1
        content["record_state_hash"] = _hash(content["record"]).removeprefix("sha256:")
    with pytest.raises(KernelError, match="GENERATION_ISOLATION_IDENTITY_CONFLICT"):
        generation_isolation.require_reconciled_cli_isolation_record(content,execution,**scope)


@pytest.mark.parametrize("identity", ["same", "unknown", "unverified", "reused"])
def test_orphaned_receipt_requires_observed_original_process_stop(reconciled_cli, monkeypatch, identity):
    from novel_forge.modules.production_execution.process_supervisor import PosixProcessIdentityProbe
    content, execution, scope = deepcopy(reconciled_cli)
    process = content["record"]["process_receipt"]
    process["status"] = "ORPHANED"
    process["recovery_reason"] = "PROCESS_IDENTITY_UNVERIFIABLE"
    if identity == "unverified":
        process["process_group"]["process_start_token"] = "unverified:original-start"
    current = None if identity == "unknown" else "other-start" if identity == "reused" else "original-start"
    monkeypatch.setattr(PosixProcessIdentityProbe,"is_alive",lambda self,pid:True)
    monkeypatch.setattr(PosixProcessIdentityProbe,"process_start_token",lambda self,pid:current)
    content["record_state_hash"] = _hash(content["record"]).removeprefix("sha256:")
    if identity == "reused":
        assert generation_isolation.require_reconciled_cli_isolation_record(content,execution,**scope)
    else:
        with pytest.raises(KernelError,match="GENERATION_ISOLATION_PROCESS_LIVE"):
            generation_isolation.require_reconciled_cli_isolation_record(content,execution,**scope)


@pytest.mark.parametrize("recoverable", ["normalized_output_ref", "raw_output_ref", "usage_receipt_ref", "live_process"])
def test_completed_result_or_live_process_requires_reuse_instead_of_successor(reconciled_cli, recoverable):
    content, execution, scope = deepcopy(reconciled_cli)
    if recoverable == "live_process":
        content["record"]["process_receipt"]["status"] = "RUNNING"
    else:
        content["record"]["result"][recoverable] = "authority-asset-version:saved"
    content["record_state_hash"] = _hash(content["record"]).removeprefix("sha256:")
    with pytest.raises(KernelError, match="GENERATION_ISOLATION_RESULT_RECOVERABLE"):
        generation_isolation.require_reconciled_cli_isolation_record(content,execution,**scope)


@pytest.mark.parametrize("principal_type,source_actor,scope,denied", [
    ("local_operator", "original-worker", "project", False),
    ("worker", "operator", "project", False),
    ("worker", "original-worker", "project", True),
    ("local_operator", "original-worker", "other-project", True),
])
def test_saved_result_recovery_retains_actor_and_project_authorization(monkeypatch, principal_type, source_actor, scope, denied):
    from novel_forge.modules.authority_security import Principal, PrincipalType

    principal = Principal("operator", PrincipalType(principal_type), frozenset({"external_effect.resolve"}), frozenset({scope}), "trusted-test")
    def enter_owner(*args):
        raise RuntimeError("recovery-owner-reached")
    monkeypatch.setattr(recovery, "AuthorityUnitOfWork", enter_owner)
    with pytest.raises(PermissionError if denied else RuntimeError):
        recovery.recover_saved_local_results(None, database_url="unused", project_id="project", book_id="book", principal=principal, source_actor_id=source_actor)
