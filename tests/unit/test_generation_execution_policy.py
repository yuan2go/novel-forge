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
    from novel_forge.modules.context_builder.production_retrieval import build_retrieval_query_plan
    retrieval = build_retrieval_query_plan(intent=intent, memo=memo)
    assert retrieval["memo_fingerprint"] == memo["memo_fingerprint"]


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
            if "SELECT op.root_operation_id" in self.statement:
                return ("root",)
            return ({"external_capabilities": ["external.publish"]}, "workspace", "root")
        def fetchall(self):
            return [(["external.publish"], False), (["model.draft"], False)]
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
    release, entered, finished = Event(), Event(), Event()
    original_save = store.save_record
    def save(record):
        original_save(record)
        if record.raw_evidence.get("invocation_finished"):
            finished.set()
    monkeypatch.setattr(store, "save_record", save)
    def invoke(_):
        entered.set()
        release.wait()
        return response
    backend.provider_adapter = SimpleNamespace(invoke=invoke)
    def cancelled():
        if entered.is_set():
            raise KernelError("OPERATION_CANCELLATION_REQUESTED", "cancelled")
    monkeypatch.setattr(lease_heartbeat, "assert_active_leases_healthy", cancelled)
    try:
        with pytest.raises(KernelError, match="OPERATION_CANCELLATION_REQUESTED"):
            backend._invoke_interruptibly(record, SimpleNamespace(
                request_hash=record.frozen_output_contract["request_hash"], model="gpt-test"))
        assert entered.is_set()
        assert store.get_record(request.execution_id).raw_evidence["local_wait_revoked"] is True
        from novel_forge.modules.production_execution.backends import provider_invocation_inflight
        assert provider_invocation_inflight({"request": request.to_dict(), "raw_evidence": record.raw_evidence})
    finally:
        release.set()
        assert finished.wait(2)
    assert not provider_invocation_inflight({"request": request.to_dict(), "raw_evidence": record.raw_evidence})
    latest=store.get_record(request.execution_id)
    raw=store.read_evidence(latest.raw_evidence["retained_model_result_ref"])
    assert raw["selection_status"] == "REVOKED"
    assert raw["acceptance_status"] == "NOT_ACCEPTED"


def test_remote_cancel_before_dispatch_never_sends_provider_request(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.command_kernel import lease_heartbeat
    backend, request, store = _remote_backend()
    backend.submit(request)
    record = store.get_record(request.execution_id)
    calls = []
    backend.provider_adapter = SimpleNamespace(invoke=lambda request: calls.append(request))
    before = dict(record.raw_evidence)
    def cancelled():
        raise KernelError("OPERATION_CANCELLATION_REQUESTED", "cancelled before dispatch")
    monkeypatch.setattr(lease_heartbeat, "assert_active_leases_healthy", cancelled)
    with pytest.raises(KernelError, match="OPERATION_CANCELLATION_REQUESTED"):
        backend._invoke_interruptibly(record, SimpleNamespace())
    assert calls == []
    assert record.raw_evidence == before


def test_remote_finished_marker_failure_cannot_discard_received_prose(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    backend, request, store = _remote_backend()
    backend.submit(request)
    record = store.get_record(request.execution_id)
    response = replace(record.provider_result, evidence={
        "result": {"chapter": 1, "title": "留存", "text": "完整返回的正文。"},
        "model_id": backend.admission.resolve_route(request).model_id,
        "source_complete": True})
    original_save = store.save_record
    failed = []
    def save(value):
        if value.raw_evidence.get("invocation_finished") and not failed:
            failed.append(True)
            raise OSError("injected finished marker outage")
        original_save(value)
    record.raw_evidence["invocation_finished"] = False
    monkeypatch.setattr(store, "save_record", save)
    backend.provider_adapter = SimpleNamespace(invoke=lambda request: response)
    result = backend._invoke_interruptibly(record, SimpleNamespace(
        request_hash=record.frozen_output_contract["request_hash"], model="gpt-test"))
    assert result is response
    raw_response = store.read_evidence(record.raw_evidence["received_provider_response_ref"])
    assert raw_response["evidence"]["result"]["text"] == response.evidence["result"]["text"]
    assert record.raw_evidence["invocation_observation_errors"][0]["stage"] == "FINISHED_MARKER"
    backend._record_provider_result(record, result)
    retained = store.read_evidence(store.get_record(request.execution_id).raw_evidence["retained_prose_candidate_ref"])
    assert retained["text"] == response.evidence["result"]["text"]


def test_expired_membership_price_observation_does_not_revoke_generation_authorization():
    from datetime import timedelta
    from novel_forge.modules.production_execution.codex_model_catalog import codex_catalog_candidates
    from tests.unit.test_cost_aware_routing import task, route, NOW, candidate
    member = codex_catalog_candidates(({'model':'authorized-model','reasoning':'high','role':'PRIMARY',
        'tasks':['classification'],'context_limit':4096,'output_limit':1024},),
        entitlement={'configuration_ref':'member-config-v1','authorization_ref':'existing-member-grant'}, quota=1,
        valid_from=(NOW-timedelta(days=2)).isoformat(), valid_until=(NOW-timedelta(days=1)).isoformat())[0]
    request=task(declared_requirements={'pure_generation':True})
    selected=route(request,[member],{})
    assert selected['status']=='SELECTED'
    assert selected['selected']['candidate']['authorization_ref']=='existing-member-grant'
    assert 'PRICING_NOT_EFFECTIVE' in selected['selected']['diagnostic_reasons']
    from dataclasses import replace
    paid_base=candidate()
    paid=replace(paid_base,pricing=replace(paid_base.pricing,effective_until=(NOW-timedelta(days=1)).isoformat(),effective_from=(NOW-timedelta(days=2)).isoformat()))
    assert 'PRICING_NOT_EFFECTIVE' in route(request,[paid],{})['candidates'][0]['rejected_reasons']


def test_reused_process_id_does_not_create_a_historical_inflight_lock(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.production_execution import backends
    monkeypatch.setattr(backends, '_provider_process_probe', SimpleNamespace(
        is_alive=lambda pid: True, process_start_token=lambda pid: 'new-process-identity'))
    record={'request':{'execution_id':'old-execution'},'raw_evidence':{
        'invocation_process_id':999999, 'invocation_process_start_identity':'old-process-identity'}}
    assert not backends.provider_invocation_inflight(record)
    record['raw_evidence']['invocation_process_start_identity']='new-process-identity'
    assert backends.provider_invocation_inflight(record)
    record['raw_evidence']['invocation_finished']=True
    assert not backends.provider_invocation_inflight(record)

def test_legacy_terminal_before_output_commit_replays_exact_frozen_result(monkeypatch):
    from types import SimpleNamespace
    from novel_forge.modules.context_builder.retrieval_campaign import RetrievalCampaignPolicy
    from unittest.mock import Mock
    from novel_forge.modules.chapter_authority import handlers
    old_policy = RetrievalCampaignPolicy(policy_version="minimum-sufficient-retrieval-campaign-v1")
    coverage = {"sufficient": False, "missing": {"fact_ids": ["missing"]}}
    rounds = ({"contract_version": "retrieval-round-snapshot-v1", "round_number": 0,
        "snapshot_hash": "old-round", "query_plan": {}, "semantic_status": {}, "documents": [],
        "rejected_documents": [], "provider_evidence": {}, "external_effect_id": "",
        "coverage_after": coverage, "coverage_before": coverage, "new_evidence_count": 0,
        "usage": {"input_tokens": 2, "output_tokens": 1, "cost_amount": "0.1", "currency": "USD", "latency_ms": 4}},)
    identity = handlers._content_hash({"campaign_id": "campaign", "round_snapshot_hashes": ["old-round"],
        "coverage": coverage, "termination_reason": "NO_NEW_EVIDENCE"})
    expected = {"project_id": "project", "book_id": "book", "selected_documents": [],
        "retrieval_campaign": {"contract_version": "retrieval-campaign-result-v1", "campaign_id": "campaign",
            "policy_version": old_policy.policy_version, "accepted_boundary": {"accepted_through_chapter": 0},
            "round_count": 1, "round_snapshot_hashes": ["old-round"], "coverage": coverage,
            "termination_reason": "NO_NEW_EVIDENCE", "final_evidence_identity": identity,
            "usage": {"provider_calls": 0, "input_tokens": 2, "output_tokens": 1, "model_tokens": 3,
                "cost_amount": "0.1", "currency": "USD", "latency_ms": 4, "candidate_count": 0},
            "authority": "DETERMINISTIC_CONTEXT_POLICY"}}
    fingerprint = handlers._content_hash(expected)
    expected["result_fingerprint"] = fingerprint
    campaign = {"campaign_id": "campaign", "status": "COMPLETED", "termination_reason": "NO_NEW_EVIDENCE",
        "final_result": None, "final_result_fingerprint": fingerprint}
    def start(*args, **kwargs):
        assert kwargs["policy"].to_dict() == old_policy.to_dict()
        return campaign
    def complete(*args, **kwargs):
        assert kwargs["final_result_fingerprint"] == fingerprint and kwargs["final_result"] == expected
        return campaign
    monkeypatch.setattr(handlers, "start_retrieval_campaign", start)
    monkeypatch.setattr(handlers, "load_retrieval_rounds", lambda *args, **kwargs: rounds)
    monkeypatch.setattr(handlers, "complete_retrieval_campaign", complete)
    monkeypatch.setattr(handlers, "build_campaign_final_query_plan", lambda **kwargs: {})
    monkeypatch.setattr(handlers, "build_retrieval_result", lambda **kwargs: {"project_id": "project", "book_id": "book", "selected_documents": []})
    handler = handlers._RetrievalHandler(provider=SimpleNamespace(invoke=Mock(side_effect=AssertionError("No Provider on terminal replay"))), expansion_provider_bound=True)
    request = SimpleNamespace(database_url="fixture", project_id="project", operation_id="operation", attempt_id="attempt",
        fencing_token=1, worker_id="worker", effective_definition_version="3.0.0", command={"book_id": "book"})
    plan = SimpleNamespace(content={"book_id": "book", "chapter": 1})
    intent = SimpleNamespace(asset_version_id="intent", content={"accepted_boundary": {"accepted_through_chapter": 0}, "intent_fingerprint": "intent-hash"})
    memo = SimpleNamespace(asset_version_id="memo", content={"memo_fingerprint": "memo-hash"})
    for _ in range(2):
        result = handler._run_campaign(request=request, plan=plan, intent=intent, memo=memo,
            query_plan={"campaign_policy": old_policy.to_dict(), "coverage_contract": {"accepted_boundary": {"accepted_through_chapter": 0}}},
            frozen_union=SimpleNamespace(query_embedding=(), query_embedding_evidence={}), discovery_rejections=())
        assert result == expected
    handler.provider.invoke.assert_not_called()
