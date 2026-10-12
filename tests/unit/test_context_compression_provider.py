from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.context_compression_provider import require_task_reasoning, task_provider_output_reserve
from novel_forge.modules.chapter_authority.execution_gateway import _stage_semantic_contract, _stage_tool_permissions
from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_schema
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view, build_provider_task_view
from novel_forge.modules.command_kernel import budget_runtime
from novel_forge.modules.command_kernel.errors import KernelError


def _task() -> dict:
    return {
        "contract_version": "task-context-compression.v1",
        "policy_version": "task-scoped-context.v1",
        "accepted_boundary": {"accepted_through_chapter": 40, "canon_snapshot_version": "canon:40", "story_state_snapshot_version": "state:40"},
        "memo_fingerprint": "memo:40",
        "task": {"goal": "Lin suspects Mei, but does not know the oath expired."},
        "target_tokens": 512_000,
        "required_unit_ids": ["unit:conditional"],
        "units": [{"unit_id": "unit:conditional", "text": "Only if the oath expired yesterday, Mei may leave; Lin merely suspects it.", "required": True, "source_hash": "host-only", "position": [10, 100]}],
        "source_binding": {"asset_version_id": "source:40", "content_hash": "host-only"},
    }


def test_compression_view_keeps_conditional_and_epistemic_text_without_host_envelope() -> None:
    task = _task()
    view = build_provider_task_view("context_compress", {"context_compression_task": task, "database_url": "private"})
    assert view["units"] == [{"unit_id": "unit:conditional", "text": task["units"][0]["text"], "required": True}]
    assert "source_binding" not in view
    assert "position" not in view["units"][0]
    assert "source_hash" not in view["units"][0]
    assert "database_url" not in view
    memo = {"accepted_boundary": {"accepted_through_chapter": 40, "canon_snapshot_asset_version_id": "canon:40", "story_state_asset_version_id": "state:40"}, "memo_fingerprint": "memo:40"}
    assert build_provider_context_view("context_compress", memo, view)["protected"]
    memo["accepted_boundary"]["accepted_through_chapter"] = 41
    with pytest.raises(KernelError, match="BOUNDARY_DRIFT"):
        build_provider_context_view("context_compress", memo, view)


def test_independent_checker_requires_exact_selection_and_preserves_uncertain_verdict() -> None:
    task = _task()
    task["selected_unit_ids"] = ["invented"]
    with pytest.raises(KernelError, match="TASK_INVALID"):
        build_provider_task_view("context_fidelity", {"context_compression_task": task})
    failed = {"supported": False, "coverage_complete": False, "missing_unit_ids": ["unit:conditional"], "distorted_unit_ids": [], "reason": "Dropping the condition changes the oath from suspicion to fact."}
    assert normalize_model_output("context_fidelity", validate_chapter_provider_output_schema("context_fidelity", failed)) == failed
    with pytest.raises(KernelError, match="SCHEMA_INVALID"):
        validate_chapter_provider_output_schema("context_compress", {"selected_unit_ids": [], "supported": True})
    assert "do not rewrite text" in _stage_semantic_contract("context_compress")
    assert "Independently inspect" in _stage_semantic_contract("context_fidelity")
    assert "A legal ID alone is not fidelity proof" in _stage_semantic_contract("context_fidelity")


def test_task_reasoning_is_a_route_choice_and_silent_downgrade_remains_forbidden() -> None:
    route = SimpleNamespace(model_profile=SimpleNamespace(reasoning_effort="medium"), route_policy=SimpleNamespace(reasoning_downgrade_policy="PROHIBITED"))
    require_task_reasoning(route, task_scoped=False)
    require_task_reasoning(route, task_scoped=True)
    route.model_profile.reasoning_effort = "high"
    require_task_reasoning(route, task_scoped=True)
    route.route_policy.reasoning_downgrade_policy = "ALLOWED"
    with pytest.raises(KernelError, match="DOWNGRADE_FORBIDDEN"):
        require_task_reasoning(route, task_scoped=True)



def test_native_validation_reasoning_authorization_is_exact_and_keeps_no_downgrade() -> None:
    route = SimpleNamespace(model_profile=SimpleNamespace(reasoning_effort="medium"),
        route_policy=SimpleNamespace(reasoning_downgrade_policy="PROHIBITED"),
        task_reasoning_authorization=("medium", "sha256:" + "a" * 64))
    require_task_reasoning(route, task_scoped=True)
    route.model_profile.reasoning_effort = "low"
    with pytest.raises(KernelError, match="REASONING_AUTHORIZATION_DRIFT"):
        require_task_reasoning(route, task_scoped=True)
    route.model_profile.reasoning_effort = "medium"
    route.route_policy.reasoning_downgrade_policy = "ALLOWED"
    with pytest.raises(KernelError, match="DOWNGRADE_FORBIDDEN"):
        require_task_reasoning(route, task_scoped=True)


def test_pack_requires_explicit_context_node_and_substage_tool_authorization() -> None:
    import json
    policy = json.loads((Path(__file__).resolve().parents[2] / "config/capability_packs/chapter_generation_pack.json").read_text())["tool_permissions"]
    assert _stage_tool_permissions(policy, "context_compress")[0] == ("model.provider.invoke",)
    assert _stage_tool_permissions(policy, "context_fidelity")[0] == ("model.provider.invoke",)
    legacy = deepcopy(policy)
    legacy["external_models"].pop("context_substages")
    assert _stage_tool_permissions(legacy, "context_compress")[0] == ()
    unauthorized = deepcopy(policy)
    unauthorized["tools"][0]["allowed_operations"].remove("context")
    assert _stage_tool_permissions(unauthorized, "context_compress")[0] == ()


def test_new_planning_policy_separates_task_target_from_system_support_and_retains_old_contract() -> None:
    import json

    catalog = json.loads((Path(__file__).resolve().parents[2] / "config/capability_packs/artifacts/chapter_generation_contract_catalog.json").read_text())
    policies = {item["ref"]: item["content"] for item in catalog["artifacts"] if item["kind"] == "CONTEXT_POLICY"}
    old = policies["context-policy:chapter-generation-pack:v1"]
    current = policies["context-policy:chapter-generation-pack:v2"]
    assert old["max_tokens"] == 16_000
    assert "planning_task_token_budget" not in old
    assert current["max_tokens"] == 512_000
    assert current["planning_task_token_budget"] == 64_000


def test_token_reservation_uses_actual_input_and_independent_output_without_expanding_scope(monkeypatch) -> None:
    class Uow:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def commit(self): pass
    monkeypatch.setattr(budget_runtime, "AuthorityUnitOfWork", lambda *_a: Uow())
    monkeypatch.setattr(budget_runtime, "resolve_book_opening_budget_scope_in_uow", lambda *_a, **_k: None)
    modern = budget_runtime.resolve_provider_token_reservation_contract("fixture", operation_id="operation", project_id="project", currency="USD", frozen_request_token_ceiling=1200, requested_output_token_ceiling=800)
    assert modern["estimated_total_tokens"] == 2000
    assert modern["input_token_ceiling"] == 1200
    assert modern["max_output_tokens"] == 800
    assert modern["contract_version"] == "provider-token-reservation.v2"
    legacy = budget_runtime.resolve_provider_token_reservation_contract("fixture", operation_id="operation", project_id="project", currency="USD", frozen_request_token_ceiling=1200)
    assert legacy["estimated_total_tokens"] == 2400
    assert legacy["max_output_tokens"] == 1200
    assert legacy["contract_version"] == "provider-token-reservation.v1"


@pytest.mark.parametrize("stage,target", [("draft", 16_384), ("revision", 16_384), ("context_compress", 4096), ("context_fidelity", 2048)])
def test_output_reserve_is_independent_from_512k_system_support(stage, target) -> None:
    route = SimpleNamespace(model_output_limit=32_000, model_context_limit=512_000, model_profile=SimpleNamespace(model_provider="openai"))
    assert task_provider_output_reserve(stage, route) == target
    route.model_output_limit = 1500
    assert task_provider_output_reserve(stage, route) == 1500
    route.model_output_limit = 0
    with pytest.raises(KernelError, match="OUTPUT_CAPACITY_UNKNOWN"):
        task_provider_output_reserve(stage, route)
    assert task_provider_output_reserve(stage, route, router_binding_pending=True) == target


def test_final_openai_sdk_request_carries_high_and_admitted_output_reserve() -> None:
    from novel_forge.modules.production_execution.provider_admission import ProviderRequestEnvelope, build_route_token_accounting_contract, prepare_provider_admission
    from novel_forge.modules.provider_control.contracts import ProviderInvocationRequest
    from novel_forge.modules.provider_control.openai_v2 import OpenAISdkTransport
    from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE

    seen = []
    response = SimpleNamespace(id="fixture-request", output_text='{"selected_unit_ids": ["unit:conditional"]}', usage=SimpleNamespace(input_tokens=80, output_tokens=40))
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: seen.append(kwargs) or response))
    envelope = ProviderRequestEnvelope(provider="openai", model="gpt-fixture", protocol="openai-responses-text-envelope-v1", input_text="Only if the oath expired yesterday may Mei leave.", max_output_tokens=4096, timeout_seconds=60, stable_idempotency_key="context:fixture:stable", reasoning_effort="high")
    contract = build_route_token_accounting_contract(provider="openai", model="gpt-fixture", route_identity="route:fixture", accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1", accounting_evidence_ref="fixture-byte-bound", model_context_limit=512_000, execution_token_limit=512_000, output_reserve=4096, safety_margin=256, framing_overhead=32)
    admission = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    request = ProviderInvocationRequest(provider="openai", model=envelope.model, capability="model.context_compress", stage="context_compress", stable_idempotency_key=envelope.stable_idempotency_key, request_payload=envelope.to_dict(), request_hash=envelope.envelope_hash, timeout_seconds=60, trace_id="trace", correlation_id="correlation", operation_id="operation", external_effect_id="effect", budget_reservation_id="reservation", provider_admission=admission.to_dict())
    OpenAISdkTransport(client).execute(request)
    assert seen[0]["reasoning"] == {"effort": "high"}
    assert seen[0]["max_output_tokens"] == 4096
    assert seen[0]["extra_headers"]["Idempotency-Key"] == envelope.stable_idempotency_key


@pytest.mark.parametrize("stage", ["context_compress", "context_fidelity"])
@pytest.mark.parametrize("failure", ["overflow", "unknown_meter", "route_drift", "incomplete_coverage", "serialization_drift"])
def test_context_complete_request_rejects_before_transport(stage, failure):
    from dataclasses import replace
    from novel_forge.modules.production_execution.provider_admission import prepare_provider_admission
    from novel_forge.modules.provider_control.contracts import ProviderInvocationRequest
    from novel_forge.modules.provider_control.openai_v2 import OpenAISdkTransport
    from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE, _contract, _envelope

    envelope = _envelope("System, Prompt, Skill, tool and output schemas. " * 2)
    contract = _contract(limit=2048)
    coverage = COMPLETE_COVERAGE
    if failure == "overflow":
        contract = replace(contract, model_context_limit=180)
    elif failure == "unknown_meter":
        contract = replace(contract, precision="UNPROVEN", evidence_ref="")
    elif failure == "route_drift":
        contract = replace(contract, model="other-model")
    elif failure == "incomplete_coverage":
        coverage = ("context_bundle", "output_reserve")
    admission = prepare_provider_admission(envelope, contract, context_bundle_tokens=80,
                                          complete_request_coverage=coverage)
    if failure == "serialization_drift":
        assert admission.status == "ADMITTED"
        envelope = replace(envelope, input_text=envelope.input_text + "Changed Skill.")
    else:
        assert admission.context_bundle_status == "VALID"
        assert admission.status == "REJECTED"
    calls = []
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs)))
    request = ProviderInvocationRequest(provider=envelope.provider, model=envelope.model,
        capability="model." + stage, stage=stage, stable_idempotency_key=envelope.stable_idempotency_key,
        request_payload=envelope.to_dict(), request_hash=envelope.envelope_hash,
        timeout_seconds=envelope.timeout_seconds, trace_id="trace", correlation_id="correlation",
        operation_id="operation", external_effect_id="effect", budget_reservation_id="reservation",
        provider_admission=admission.to_dict())
    with pytest.raises(ValueError):
        OpenAISdkTransport(client).execute(request)
    assert calls == []


def test_final_deepseek_request_carries_high_thinking_and_exact_effect_identity() -> None:
    from dataclasses import replace
    from io import BytesIO
    import json
    from tests.unit.test_deepseek_provider import adapter, invocation, response

    seen = []
    def transport(request, **kwargs):
        seen.append(json.loads(request.data))
        return BytesIO(json.dumps(response(model="deepseek-v4-pro")).encode())
    request = replace(invocation(model="deepseek-v4-pro", reasoning="high"), capability="model.context_fidelity", stage="context_fidelity")
    result = adapter(transport).invoke(request)
    assert result.outcome == "success"
    assert seen[0]["thinking"] == {"type": "enabled"}
    assert seen[0]["reasoning_effort"] == "high"
    assert seen[0]["max_tokens"] == 256


def test_semantic_task_reuses_author_and_world_private_source_isolation():
    from tests.unit.test_author_design_adoption import design, digest
    from novel_forge.modules.story_design_authority.author_input import bind_author_design
    task = _task()
    task["task"] = {"stage": "draft", "chapter": 1, "plan": {"chapter": 1, "chapter_objective": "Keep the public promise.", "constraint_envelope": {"author_design": bind_author_design(design(), asset_version_id="author:1", content_hash=digest("author")), "world_preparation": {"action": {"private": "world-secret"}, "frozen_source": {"private": "world-secret"}}}}, "database_url": "transport-secret"}
    view = build_provider_task_view("context_compress", {"context_compression_task": task})
    assert view["task"]["plan"]["chapter_objective"] == "Keep the public promise."
    assert "幕后借用真相" not in str(view) and "第七章旧申请" not in str(view)
    assert "world-secret" not in str(view) and "transport-secret" not in str(view)
    assert view["task"]["plan"]["author_design_guidance"]["fragments"]


@pytest.mark.parametrize('stage', ['draft', 'context_compress', 'context_fidelity', 'book_plan.generate'])
def test_codex_backend_reserves_the_known_full_output_capacity(stage):
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    route = SimpleNamespace(model_output_limit=32_768, model_context_limit=512_000,
        model_profile=SimpleNamespace(model_provider='codex-cli', backend_id='codex-cli',
            runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE))
    assert task_provider_output_reserve(stage, route) == 32_768
    route.model_output_limit = 0
    with pytest.raises(KernelError, match='OUTPUT_CAPACITY_UNKNOWN'):
        task_provider_output_reserve(stage, route, router_binding_pending=True)


def test_output_reserve_uses_the_backend_contract_instead_of_the_provider_label():
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    route = SimpleNamespace(model_output_limit=32_768,
        model_profile=SimpleNamespace(model_provider='codex-cli', backend_id='remote-provider-openai',
            runtime_class=ExecutionRuntimeClass.REMOTE_PROVIDER_API))
    assert task_provider_output_reserve('draft', route) == 16_384


@pytest.mark.parametrize('backend,output_limit,expected', [('codex-cli', 32_768, 32_768), ('remote-provider-openai', 32_768, 16_384)])
def test_new_model_effect_output_is_independent_of_its_context_target(monkeypatch, backend, output_limit, expected):
    from novel_forge.modules.chapter_authority import model_effects
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    route = SimpleNamespace(model_output_limit=output_limit, model_profile=SimpleNamespace(backend_id=backend,
        model_provider='codex-cli' if backend == 'codex-cli' else 'openai', runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
        if backend == 'codex-cli' else ExecutionRuntimeClass.REMOTE_PROVIDER_API))
    port = model_effects.ExternalEffectChapterModelPort('unused', adapter=SimpleNamespace(provider='controlled', routes={'draft': route}),
        worker_id='worker', max_cost_per_call='1')
    request = ChapterHandlerRequest(operation_id='operation', project_id='project', workspace_id='workspace', trace_id='trace',
        correlation_id='correlation', command={'context_token_budget': 1000, 'draft_profile_version': 'draft-context-profile-v4'},
        inputs=(), attempt_id='attempt', fencing_token=7, worker_id='worker')
    monkeypatch.setattr(model_effects, 'read_external_effect_intent', lambda *args, **kwargs: None)
    seen = []
    class ReservationObserved(Exception):
        pass
    def reserve(*args, **kwargs):
        seen.append(kwargs)
        raise ReservationObserved()
    monkeypatch.setattr(model_effects, 'resolve_provider_token_reservation_contract', reserve)
    with pytest.raises(ReservationObserved):
        port.invoke(request, stage='draft', payload={})
    assert seen[0]['requested_output_token_ceiling'] == expected
    assert seen[0]['frozen_request_token_ceiling'] == 1


@pytest.mark.parametrize("stage", ["draft", "context_compress", "context_fidelity", "book_plan.generate"])
def test_final_codex_route_capacity_growth_cannot_outgrow_its_frozen_reservation(stage):
    from novel_forge.modules.chapter_authority.context_compression_provider import require_task_output_reserve
    from novel_forge.modules.production_execution import ExecutionRuntimeClass

    route = SimpleNamespace(model_output_limit=32_768, model_profile=SimpleNamespace(
        backend_id="codex-cli", runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
        model_provider="codex-cli"))
    require_task_output_reserve(stage, route, 32_768, capacity_error_code="FINAL_OUTPUT_CAPACITY_EXCEEDED")
    route.model_output_limit = 65_536
    with pytest.raises(KernelError, match="CLI_OUTPUT_RESERVATION_INSUFFICIENT"):
        require_task_output_reserve(stage, route, 32_768, capacity_error_code="FINAL_OUTPUT_CAPACITY_EXCEEDED")
    route.model_output_limit = 16_384
    require_task_output_reserve(stage, route, 32_768, capacity_error_code="FINAL_OUTPUT_CAPACITY_EXCEEDED")
    route.model_output_limit = 0
    with pytest.raises(KernelError, match="OUTPUT_CAPACITY_UNKNOWN"):
        require_task_output_reserve(stage, route, 32_768, capacity_error_code="FINAL_OUTPUT_CAPACITY_EXCEEDED")


def test_final_api_output_reserve_keeps_the_sent_token_bound():
    from novel_forge.modules.chapter_authority.context_compression_provider import require_task_output_reserve
    from novel_forge.modules.production_execution import ExecutionRuntimeClass

    route = SimpleNamespace(model_output_limit=32_768, model_profile=SimpleNamespace(
        backend_id="remote-provider-openai", runtime_class=ExecutionRuntimeClass.REMOTE_PROVIDER_API,
        model_provider="openai"))
    require_task_output_reserve("draft", route, 16_384, capacity_error_code="FINAL_OUTPUT_CAPACITY_EXCEEDED")
    with pytest.raises(KernelError, match="FINAL_OUTPUT_CAPACITY_EXCEEDED"):
        require_task_output_reserve("draft", route, 32_768, capacity_error_code="FINAL_OUTPUT_CAPACITY_EXCEEDED")


@pytest.mark.parametrize("backend", ["codex-cli", "remote-provider-openai"])
def test_authorization_cannot_shrink_the_new_output_requirement(monkeypatch, backend):
    from novel_forge.modules.chapter_authority import model_effects
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    from unittest.mock import Mock

    route = SimpleNamespace(model_output_limit=32_768, model_profile=SimpleNamespace(backend_id=backend,
        model_provider="codex-cli" if backend == "codex-cli" else "openai", runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
        if backend == "codex-cli" else ExecutionRuntimeClass.REMOTE_PROVIDER_API))
    port = model_effects.ExternalEffectChapterModelPort("unused", adapter=SimpleNamespace(provider="controlled", routes={"draft": route}),
        worker_id="worker", max_cost_per_call="1")
    request = ChapterHandlerRequest(operation_id="operation", project_id="project", workspace_id="workspace", trace_id="trace",
        correlation_id="correlation", command={"context_token_budget": 1000, "draft_profile_version": "draft-context-profile-v4"},
        inputs=(), attempt_id="attempt", fencing_token=7, worker_id="worker")
    monkeypatch.setattr(model_effects, "read_external_effect_intent", lambda *args, **kwargs: None)
    def reserve(*args, **kwargs):
        return {"source": "BOOK_OPENING_IMMUTABLE_PER_CALL_POLICY", "max_output_tokens": kwargs["requested_output_token_ceiling"] - 1}
    monkeypatch.setattr(model_effects, "resolve_provider_token_reservation_contract", reserve)
    plan = Mock()
    monkeypatch.setattr(model_effects, "plan_external_effect", plan)
    with pytest.raises(KernelError, match="PROVIDER_TOKEN_RESERVATION_INSUFFICIENT"):
        port.invoke(request, stage="draft", payload={})
    plan.assert_not_called()

@pytest.mark.parametrize("boundary", ["model", "authorization"])
def test_codex_full_output_and_reasoning_reserve_is_included_once_at_admission(boundary):
    from types import SimpleNamespace
    from dataclasses import replace
    from novel_forge.modules.production_execution.provider_admission import (
        ProviderRequestEnvelope, build_route_token_accounting_contract,
        prepare_provider_admission, verify_provider_admission,
    )
    from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE
    from novel_forge.modules.chapter_authority.context_compression_provider import task_provider_output_reserve
    from novel_forge.modules.production_execution import ExecutionRuntimeClass

    route = SimpleNamespace(model_output_limit=32_768, model_profile=SimpleNamespace(
        model_provider="codex-cli", backend_id="codex-cli", runtime_class=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE))
    output_reserve = task_provider_output_reserve("draft", route)
    contract = build_route_token_accounting_contract(
        provider="codex-cli", model="codex-test", route_identity="codex:capacity:1",
        accounting_method="CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1",
        accounting_evidence_ref="codex:stdin-bound:v1", model_context_limit=512_000,
        execution_token_limit=512_000, output_reserve=output_reserve, safety_margin=256, framing_overhead=32)
    envelope = ProviderRequestEnvelope(provider="codex-cli", model="codex-test", protocol="codex-cli-application-stdin-v1",
        input_text="x" * 4000, max_output_tokens=output_reserve, timeout_seconds=300, stable_idempotency_key="codex:capacity:1")
    receipt = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert receipt.component_usage["output_reserve"] == 32_768
    assert receipt.total_reserved == 4000 + 32_768 + 256 + 32
    assert receipt.status == "ADMITTED"
    limit_key = "model_context_limit" if boundary == "model" else "execution_token_limit"
    limited = replace(contract, **{limit_key: receipt.total_reserved - 1})
    rejected = prepare_provider_admission(envelope, limited, complete_request_coverage=COMPLETE_COVERAGE)
    assert rejected.total_reserved == receipt.total_reserved
    if boundary == "model":
        assert rejected.status == "REJECTED"
        assert rejected.reason == "PROVIDER_CONTEXT_LIMIT_EXCEEDED"
        with pytest.raises(ValueError, match="PROVIDER_ADMISSION_REJECTED"):
            verify_provider_admission(envelope, rejected)
    else:
        assert rejected.status == "ADMITTED"
        verify_provider_admission(envelope, rejected)
