from __future__ import annotations

import json
import logging
import hashlib
import sys
from types import SimpleNamespace

import pytest

from novel_forge.logging.execution import execution_step
from novel_forge.modules.production_execution.provider_protocol_failure import codex_stream_summary
from novel_forge.modules.production_execution.backends import (
    CodexCliExecutionBackend, InMemoryExecutionRecordStore, LocalProcessExecutionPolicy,
    ResolvedExecutionPayload, StaticExecutionPayloadResolver,
)
from novel_forge.modules.production_execution.gateway import (
    AdmissionController, ExecutionBackendRegistry, ProductionExecutionGateway,
    StaticAttemptFenceVerifier, StaticExecutionContractSource,
)
from novel_forge.modules.production_execution.process_supervisor import (
    CodexProcessSupervisor, PersistentExecutionDirectory,
)
from novel_forge.modules.production_execution import ExecutionOutcome, ExecutionRuntimeClass
from tests.unit.test_production_execution_gateway import contracts
from tests.unit.test_codex_execution_evidence import _entitlement
from novel_forge.modules.story_planning_runtime.execution import (
    _PlanningExecutionBinding, _PlanningGatewayEffectAdapter,
)


def test_nested_steps_correlate_without_logging_payload_or_exception(caplog):
    caplog.set_level(logging.INFO, logger="novel_forge.execution")
    request = SimpleNamespace(execution_id="execution:1", operation_id="operation:1",
        input_text="PRIVATE PROSE", environment_overrides={"TOKEN": "PRIVATE TOKEN"})

    @execution_step("test.storage")
    def storage():
        raise OSError("PRIVATE TOKEN PRIVATE PROSE")

    @execution_step("test.dispatch")
    def dispatch(request):
        return storage()

    with pytest.raises(OSError, match="PRIVATE TOKEN"):
        dispatch(request)
    rows = [json.loads(row.message) for row in caplog.records]
    assert [(row["step"], row["phase"]) for row in rows] == [
        ("test.dispatch", "started"), ("test.storage", "started"),
        ("test.storage", "failed"), ("test.dispatch", "failed")]
    assert all(row["execution_id"] == "execution:1" for row in rows)
    assert rows[1]["parent_span_id"] == rows[0]["span_id"]
    assert rows[2]["error_type"] == "OSError"
    assert "PRIVATE" not in caplog.text


def test_logging_failure_does_not_change_execution(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("log sink unavailable")

    monkeypatch.setattr(logging.getLogger("novel_forge.execution"), "info", fail)

    @execution_step("test.execution")
    def execute():
        return 42

    assert execute() == 42


def test_private_exception_text_retains_cause_and_traceback_but_redacts_credentials(caplog, monkeypatch):
    monkeypatch.setenv("NOVEL_FORGE_EXECUTION_DIAGNOSTICS_EXCEPTION_TEXT", "1")
    caplog.set_level(logging.INFO, logger="novel_forge.execution")

    @execution_step("test.private_failure")
    def execute():
        try:
            raise ConnectionError("error decoding response body sk-proj-abcdefghijklmnop")
        except ConnectionError as exc:
            raise RuntimeError("gateway failed password=privatepassword123") from exc

    with pytest.raises(RuntimeError):
        execute()
    row = next(json.loads(row.message) for row in caplog.records if '"phase": "exception"' in row.message)
    assert "ConnectionError" in row["traceback"]
    assert "error decoding response body" in row["traceback"]
    assert "gateway failed" in row["error_message"]
    assert "abcdefghijklmnop" not in caplog.text
    assert "privatepassword123" not in caplog.text


def test_stream_summary_identifies_disconnect_without_claiming_remote_outcome():
    error = "stream disconnected before completion: Transport error: network error: error decoding response body PRIVATE TOKEN"
    stdout = "\n".join(json.dumps(event) for event in [
        {"type": "thread.started", "thread_id": "thread:1"},
        {"type": "turn.started"}, {"type": "error", "message": error},
        {"type": "turn.failed", "error": {"message": error}}])
    summary = codex_stream_summary(stdout)
    assert summary["stream_disconnected"] is True
    assert summary["response_body_decode_failed"] is True
    assert summary["turn_completed"] is False
    assert summary["usage_present"] is False
    assert summary["remote_outcome"] == "UNESTABLISHED"
    assert "PRIVATE" not in json.dumps(summary)


def test_stream_summary_does_not_report_warning_as_transport_failure():
    stdout = json.dumps({"type": "item.completed", "item": {
        "type": "error", "message": "Warning: ignored tools.view_image"}})
    summary = codex_stream_summary(stdout)
    assert summary["stream_disconnected"] is False
    assert summary["event_counts"] == {"item.completed": 1}


@pytest.mark.parametrize("scenario", ["disconnect", "success", "bad_schema", "storage_failure"])
def test_gateway_diagnostics_locate_failure_and_recovery_never_respawns(tmp_path, caplog, monkeypatch, scenario):
    caplog.set_level(logging.INFO, logger="novel_forge.execution")
    _, profile, policy, route, manifest, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    admission = AdmissionController(StaticExecutionContractSource(
        route_snapshots=(route,), model_profiles=(profile,), route_policies=(policy,),
        input_manifests=(manifest,)), StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}))
    directory = PersistentExecutionDirectory(tmp_path / "executions")
    result_path = directory.prepare(request.execution_id).result_path("result.json")
    event = {"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 1}}
    if scenario == "disconnect":
        event = {"type": "error", "message": "stream disconnected before completion: error decoding response body"}
    program = "import json,sys; print(sys.argv[2]); "
    program += "sys.exit(1)" if scenario == "disconnect" else "json.dump({'text':'PRIVATE PROSE'},open(sys.argv[1],'w'))"
    store = InMemoryExecutionRecordStore()
    supervisor = CodexProcessSupervisor(directory)
    launch = supervisor.run
    launches = []

    def count_launch(*args, **kwargs):
        launches.append(1)
        return launch(*args, **kwargs)

    monkeypatch.setattr(supervisor, "run", count_launch)

    def validate(*args, **kwargs):
        if scenario == "bad_schema":
            raise ValueError("PRIVATE PROSE PRIVATE TOKEN")
        return {"text": "PRIVATE PROSE"}

    backend = CodexCliExecutionBackend(admission=admission,
        payload_resolver=StaticExecutionPayloadResolver({request.execution_id: ResolvedExecutionPayload(
            request_payload={"stage": "draft"}, input_text="PRIVATE PROMPT", working_directory=str(tmp_path),
            timeout_seconds=5, output_schema_version="schema:test:1", output_schema={"type": "object"},
            command=(sys.executable, "-c", program, str(result_path), json.dumps(event)),
            allowed_tools=("model.provider.invoke",), capability_evidence={
                "fully_rendered_prompt_hash": "sha256:" + hashlib.sha256(b"PRIVATE PROMPT").hexdigest()} )}),
        record_store=store, supervisor=supervisor, account_entitlement=_entitlement(),
        structured_result_validator=validate, execution_policy=LocalProcessExecutionPolicy(
            fixed_working_directory=str(tmp_path), allowed_command_prefixes=((sys.executable,),), maximum_result_bytes=100000))
    registry = ExecutionBackendRegistry()
    registry.register(backend)
    gateway = ProductionExecutionGateway(registry, admission)
    handle = gateway.submit(request)
    if scenario == "storage_failure":
        def failed_write(*args, **kwargs):
            raise OSError("PRIVATE DATABASE CREDENTIAL")
        monkeypatch.setattr(store, "put_evidence", failed_write)
        with pytest.raises(OSError):
            gateway.reconcile(handle)
        assert store.get_record(request.execution_id).result is None
    else:
        result = gateway.reconcile(handle)
        assert result.outcome == {"disconnect": ExecutionOutcome.UNKNOWN,
            "success": ExecutionOutcome.SUCCEEDED, "bad_schema": ExecutionOutcome.FINAL_FAILURE}[scenario]
        assert gateway.reconcile(handle) == result
        assert gateway.submit(request) == handle
        adapter = _PlanningGatewayEffectAdapter(transport=SimpleNamespace(
            provider="codex-cli", reconciliation_mode="query", capability_profile=object()),
            session=SimpleNamespace(gateway=gateway, evidence_store=store),
            binding=_PlanningExecutionBinding(request, route, manifest))
        recovered = adapter.query(stable_idempotency_key=request.stable_idempotency_key,
            capability=request.capability, request_payload={"external_effect_id": request.external_effect_id})
        assert recovered.outcome == {"disconnect": "ambiguous", "success": "success",
            "bad_schema": "failed_final"}[scenario]
        rows = [json.loads(row.message) for row in caplog.records]
        assert any(row["step"].endswith("_PlanningGatewayEffectAdapter._invoke") for row in rows)
        assert any(row["step"] == "codex.recovery" and row["cached_result"] for row in rows)
        if scenario == "disconnect":
            assert result.usage_receipt_ref is None
            assert any(row["step"] == "codex.stream" and row["stream_disconnected"] for row in rows)
        if scenario == "bad_schema":
            assert any(row["step"].endswith("._validate_successful_process") and row["phase"] == "failed" for row in rows)
    assert len(launches) == 1
    assert "PRIVATE" not in caplog.text
    assert "ProductionExecutionGateway" in caplog.text
    assert "CodexProcessSupervisor.run" in caplog.text
