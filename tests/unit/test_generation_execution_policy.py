from novel_forge.modules.command_kernel.generation_policy import pure_generation_capabilities
from novel_forge.modules.production_execution.process_supervisor import ProcessTimeout
from novel_forge.modules.production_execution.contracts import ExecutionRuntimeClass


def test_only_model_effects_have_generation_recovery_policy():
    assert pure_generation_capabilities(["model.draft", "model.context_compress"])
    assert not pure_generation_capabilities([])
    assert not pure_generation_capabilities(["model.draft", "remote.publish"])
    assert not pure_generation_capabilities(["storage.object.put"])


def test_generation_process_has_no_elapsed_time_limit():
    assert ProcessTimeout(None).timeout_seconds is None


def test_complete_prose_survives_auxiliary_and_accounting_failure():
    import json
    from types import SimpleNamespace
    from novel_forge.modules.production_execution.backends import InMemoryExecutionRecordStore
    from novel_forge.modules.production_execution.result_retention import retain_model_result
    from tests.unit.test_production_execution_gateway import contracts

    request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)[5]
    store = InMemoryExecutionRecordStore()
    record = SimpleNamespace(request=request, raw_evidence={}, frozen_output_contract={}, result=None)
    store.put_record(record)
    raw = json.dumps({"text": "徐照将最后一块窑泥搬上木车。", "scene_artifacts": "bad auxiliary"})
    ref = retain_model_result(record, store, raw_text=raw, complete=True, source={"usage": "UNKNOWN"})
    assert store.read_evidence(ref)["raw_text"] == raw
    candidate = store.read_evidence(record.raw_evidence["retained_prose_candidate_ref"])
    assert candidate["text"] == "徐照将最后一块窑泥搬上木车。"
    assert candidate["accounting_status"] == "UNRECONCILED"
    assert candidate["acceptance_status"] == "NOT_ACCEPTED"
    assert record.result is None
    assert ref == retain_model_result(record, store, raw_text=raw, complete=True, source={"usage": "UNKNOWN"})


def test_unconfirmed_fragment_never_becomes_a_complete_candidate():
    from types import SimpleNamespace
    from novel_forge.modules.production_execution.backends import InMemoryExecutionRecordStore
    from novel_forge.modules.production_execution.result_retention import retain_model_result
    from tests.unit.test_production_execution_gateway import contracts

    record = SimpleNamespace(request=contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)[5], raw_evidence={}, frozen_output_contract={}, result=None)
    store = InMemoryExecutionRecordStore()
    store.put_record(record)
    ref = retain_model_result(record, store, raw_text='{"text":"断在半途"}', complete=False, source={})
    assert store.read_evidence(ref)["completeness"] == "FRAGMENT"
    assert "retained_prose_candidate_ref" not in record.raw_evidence


def test_consumption_limits_and_failed_history_are_generation_diagnostics():
    from tests.unit.test_cost_aware_routing import candidate, task, route
    request = task(remaining_tokens=1, declared_requirements={"pure_generation": True},
        history=tuple({"candidate_id": "flash", "status": "FAILED_FINAL", "failure_class": "SCHEMA_REJECTION"} for _ in range(12)))
    result = route(request, [candidate()], {})
    assert result["status"] == "SELECTED"
    assert "CHAIN_ATTEMPTS_EXHAUSTED" in result["selected"]["diagnostic_reasons"]
    assert "BUDGET_HARD_LIMIT" in result["selected"]["diagnostic_reasons"]


def test_generation_still_requires_real_capacity_and_preserves_retry_after():
    from datetime import timedelta
    from tests.unit.test_cost_aware_routing import candidate, task, route, NOW
    oversized = task(output_tokens=999999, declared_requirements={"pure_generation": True})
    assert "CONTEXT_CAPACITY_EXCEEDED" in route(oversized, [candidate()], {})["candidates"][0]["rejected_reasons"]
    waiting = task(declared_requirements={"pure_generation": True}, history=({"candidate_id": "flash",
        "retry_after_until": (NOW + timedelta(seconds=10)).isoformat()},))
    assert "RETRY_AFTER_ACTIVE" in route(waiting, [candidate()], {})["candidates"][0]["rejected_reasons"]


def test_optional_memo_uses_frozen_inputs_without_inventing_model_success():
    from novel_forge.modules.chapter_authority.creative_memo import input_only_memo
    from novel_forge.modules.chapter_authority.execution_artifacts import build_chapter_execution_intent, validate_chapter_memo
    from tests.unit.test_chapter_execution_artifacts import _plan, _accepted
    intent = build_chapter_execution_intent(project_id="project", operation_id="intent-op",
        chapter_plan_asset_version_id="plan-v5", chapter_plan_content_hash="sha256:" + "a" * 64, chapter_plan=_plan(),
        accepted_inputs=(_accepted("story_state_snapshot", "story-state-v4"), _accepted("canon_snapshot", "canon-v4")))
    memo = input_only_memo(intent, "intent-v5")
    assert memo["qualification"] == "INPUT_FALLBACK"
    assert memo["enhancement_status"] == "NOT_REQUESTED"
    assert memo["execution_evidence"]["model_call"] == "NOT_RUN"
    assert memo["source_chapter_plan"] == intent["source_chapter_plan"]
    assert validate_chapter_memo(memo, intent=intent, intent_asset_version_id="intent-v5") == memo


def test_ambiguous_json_retains_raw_without_choosing_a_prose_interpretation():
    from types import SimpleNamespace
    from novel_forge.modules.production_execution.backends import InMemoryExecutionRecordStore
    from novel_forge.modules.production_execution.result_retention import retain_model_result
    from tests.unit.test_production_execution_gateway import contracts
    record = SimpleNamespace(request=contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)[5],
        raw_evidence={}, frozen_output_contract={}, result=None)
    store = InMemoryExecutionRecordStore()
    store.put_record(record)
    raw = '{"text":"第一份正文","text":"第二份正文"}'
    ref = retain_model_result(record, store, raw_text=raw, complete=True, source={})
    assert store.read_evidence(ref)["raw_text"] == raw
    assert "retained_prose_candidate_ref" not in record.raw_evidence


def test_generation_graph_keeps_non_generation_root_constraints():
    from novel_forge.modules.command_kernel.generation_policy import generation_graph
    class Cursor:
        def execute(self, statement, parameters):
            self.statement = statement
        def fetchone(self):
            return (["external.publish"],)
        def fetchall(self):
            assert "child.operation_id=%s" in self.statement
            return [(["external.publish"],), (["model.draft"],)]
    assert not generation_graph(Cursor(), "root", "project")


def test_structural_revision_uses_source_bound_scope_and_preserves_open_issues():
    from novel_forge.modules.revision.domain import apply_revision_result
    from novel_forge.modules.review.diagnostics import prose_hash, structural_repair_scope
    source = "他绕了两次院子。\n\n他又绕了一次院子。\n\n守门人拦住了他。"
    issue = {"code": "repetition", "severity": "major", "judgment_kind": "SEMANTIC_CONFLICT",
        "evidence_locator": {"start": 0, "end": 8, "quote": source[:8]},
        "repair": {"root_cause": "CHAPTER_STRUCTURE", "problem_owner": "PROSE", "repair_scope": "CHAPTER_REVISION",
            "revision_goal": "合并重复动作，保留守门人的阻拦和人物动机", "preserve": ["守门人阻拦"], "resolution_criteria": ["动作不再重复"]}}
    review = {"issues": [issue], "unresolved_issues": [], "diagnostic_contract_version": "actionable-diagnostics.v1",
        "target_asset_version_id": "draft-v1", "context_bundle_version_id": "context-v1", "target_text_hash": prose_hash(source),
        "cross_chapter_window": {"source_asset_version_id": "previous-v2"}}
    revised = apply_revision_result(project_id="project", draft={"chapter": 1, "title": "门前", "text": source},
        review=review, draft_asset_version_id="draft-v1", review_asset_version_id="review-v1", context_bundle_version_id="context-v1",
        result={"text": "他绕过院墙，守门人立即横臂拦住了他。", "resolved_issue_codes": []}, provider_evidence={})
    assert revised["repair_scope"] == "CHAPTER_REVISION"
    assert revised["realization_mapping_status"] == "NOT_MAPPED"
    assert revised["issue_resolutions"][0]["to_status"] == "OPEN"
    changed = {**issue, "repair": {**issue["repair"], "problem_owner": "PLAN", "repair_scope": "FUTURE_REPLAN"}}
    assert structural_repair_scope([changed]) == "LOCAL_PROSE"


def test_openai_bad_usage_keeps_actual_output_and_unknown_cost():
    from dataclasses import replace
    from tests.unit.test_provider_adapter_v2 import _request
    from novel_forge.modules.provider_control.openai_v2 import OpenAIProviderAdapterV2
    from types import SimpleNamespace
    raw = {"outcome": "success", "request_sent": True, "provider_request_id": "response-original",
        "evidence": {"result": {"text": "保留下来的完整正文。"}, "raw_output_text": '{"text":"保留下来的完整正文。"}',
            "usage": {"input_tokens": None, "output_tokens": "bad"}, "source_complete": True}}
    adapter = OpenAIProviderAdapterV2(SimpleNamespace(execute=lambda request: raw), supports_query=False,
        supports_cancel=False, supports_callback=False, supports_cost_receipt=True, provider_idempotency_supported=True)
    result = adapter.invoke(replace(_request(), provider="openai"))
    assert result.outcome == "unknown"
    assert result.evidence["result"]["text"] == "保留下来的完整正文。"
    assert result.evidence["cost"]["status"] == "UNKNOWN"
    assert "amount" not in result.evidence["cost"]
    assert result.evidence["raw_usage"]["output_tokens"] == "bad"


def _remote_backend():
    from tests.unit.test_production_execution_gateway import (contracts, _remote_adapter, _admitted_remote_payload,
        StaticExecutionContractSource, StaticAttemptFenceVerifier, AdmissionController, StaticExecutionPayloadResolver)
    from novel_forge.modules.production_execution.backends import RemoteProviderExecutionBackend, InMemoryExecutionRecordStore
    capability, profile, policy, route, manifest, request = contracts(backend_id="remote-provider", runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API)
    admission = AdmissionController(StaticExecutionContractSource(route_snapshots=(route,), model_profiles=(profile,),
        route_policies=(policy,), input_manifests=(manifest,)), StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}))
    adapter, _ = _remote_adapter("success")
    store = InMemoryExecutionRecordStore()
    backend = RemoteProviderExecutionBackend(backend_id="remote-provider", capability_profile=capability,
        provider_adapter=adapter, admission=admission, payload_resolver=StaticExecutionPayloadResolver(
            {request.execution_id: _admitted_remote_payload(request, "frozen payload")}), record_store=store)
    return backend, request, store


def test_identity_conflicting_remote_prose_retains_raw_without_complete_candidate():
    import pytest
    from dataclasses import replace
    backend, request, store = _remote_backend()
    backend.submit(request)
    record = store.get_record(request.execution_id)
    result = replace(record.provider_result, evidence={**record.provider_result.evidence,
        "model_id": "gpt-test", "source_complete": True, "operation_id": "another-operation",
        "result": {"text": "不属于当前调用的正文"}})
    with pytest.raises(ValueError, match="PROVIDER_FROZEN_CONTRACT_CONFLICT"):
        backend._record_provider_result(record, result, reject_conflict=True)
    raw = store.read_evidence(record.raw_evidence["retained_model_result_ref"])
    assert raw["completeness"] == "FRAGMENT"
    assert "retained_prose_candidate_ref" not in record.raw_evidence


def test_remote_wait_observes_cancellation_without_total_generation_deadline(monkeypatch):
    from threading import Event
    from types import SimpleNamespace
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel import lease_heartbeat
    backend, request, store = _remote_backend()
    backend.submit(request)
    record = store.get_record(request.execution_id)
    response = record.provider_result
    release, entered = Event(), Event()
    def invoke(_):
        entered.set()
        release.wait()
        return response
    backend.provider_adapter = SimpleNamespace(invoke=invoke)
    def cancelled():
        raise KernelError("OPERATION_CANCELLATION_REQUESTED", "cancelled")
    monkeypatch.setattr(lease_heartbeat, "assert_active_leases_healthy", cancelled)
    try:
        with pytest.raises(KernelError, match="OPERATION_CANCELLATION_REQUESTED"):
            backend._invoke_interruptibly(record, request)
        assert entered.is_set()
        assert store.get_record(request.execution_id).raw_evidence["local_wait_revoked"] is True
    finally:
        release.set()
