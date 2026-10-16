from copy import deepcopy
from dataclasses import replace
import json
import hashlib
from types import SimpleNamespace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection, prepare_request_capacity
from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope, build_route_token_accounting_contract, prepare_provider_admission, verify_provider_admission,
)
from novel_forge.modules.production_execution.token_meter import count_text
from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE


def route(*, method="MODEL_TOKENIZER_V1", model="gpt-4.1", limit=512_000):
    return SimpleNamespace(token_accounting_method=method, token_accounting_evidence_ref="fixture:matched-tokenizer",
        model_context_limit=limit, model_output_limit=100, token_safety_margin=0, token_framing_overhead=0,
        model_profile=SimpleNamespace(model_id=model, model_provider="scripted_provider_v2" if model == "fixture" else "openai"))


def test_tokenized_complete_request_boundary_and_byte_observation_are_separate(tmp_path):
    from tokenizers import Tokenizer, models, pre_tokenizers
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "甲": 1, "乙": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Split("", behavior="isolated")
    path = tmp_path / "fixture-tokenizer.json"
    tokenizer.save(str(path))
    evidence = "tokenizer-json:" + hashlib.sha256(path.read_bytes()).hexdigest() + ":" + str(path)
    text = "甲乙相疑，只有旧约失效才可通关。" * 100
    amount = count_text(text, method="PINNED_TOKENIZER_JSON_V1", model="fixture-tokenizer", evidence_ref=evidence)
    contract = build_route_token_accounting_contract(provider="openai", model="fixture-tokenizer", route_identity="route:one",
        accounting_method="PINNED_TOKENIZER_JSON_V1", accounting_evidence_ref=evidence,
        model_context_limit=amount + 100, execution_token_limit=512_000, output_reserve=100,
        safety_margin=0, framing_overhead=0, contract_version="provider-token-accounting-v4")
    envelope = ProviderRequestEnvelope("openai", "fixture-tokenizer", "openai-responses-text-envelope-v1", text, 100, 60, "one")
    receipt = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert receipt.status == "ADMITTED" and receipt.total_reserved == amount + 100
    assert receipt.measurement["utf8_bytes"] > amount
    assert receipt.measurement["actual_provider_input_tokens"] is None
    verify_provider_admission(envelope, receipt)
    rejected = prepare_provider_admission(envelope, replace(contract, model_context_limit=amount + 99), complete_request_coverage=COMPLETE_COVERAGE)
    assert rejected.status == "REJECTED" and rejected.reason == "PROVIDER_CONTEXT_LIMIT_EXCEEDED"


def test_512k_system_ceiling_applies_even_when_model_is_larger():
    text = "x" * (512_000 - 100)
    contract = build_route_token_accounting_contract(provider="scripted_provider_v2", model="fixture", route_identity="fixture",
        accounting_method="", accounting_evidence_ref="", model_context_limit=1_000_000,
        execution_token_limit=1_000_000, output_reserve=100, safety_margin=0, framing_overhead=0,
        contract_version="provider-token-accounting-v4")
    envelope = ProviderRequestEnvelope("scripted_provider_v2", "fixture", "scripted-responses-text-envelope-v1", text, 100, 60, "one")
    boundary = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert boundary.status == "ADMITTED" and boundary.total_reserved == boundary.applicable_limit == 512_000
    over = prepare_provider_admission(replace(envelope, input_text=text + "x"), contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert over.status == "REJECTED" and over.total_reserved == 512_001


def test_upper_bound_overflow_does_not_claim_proven_token_overflow():
    contract = build_route_token_accounting_contract(provider="openai", model="gpt-4.1", route_identity="one",
        accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1", accounting_evidence_ref="fixture:bytes",
        model_context_limit=100, execution_token_limit=100, output_reserve=10, safety_margin=0, framing_overhead=0,
        contract_version="provider-token-accounting-v4")
    envelope = ProviderRequestEnvelope("openai", "gpt-4.1", "openai-responses-text-envelope-v1", "甲" * 100, 10, 60, "one")
    result = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert result.reason == "PROVIDER_CONTEXT_CAPACITY_UNCERTAIN"
    assert result.measurement["tokenized_text_tokens"] is None


def test_new_complete_policy_defers_large_byte_material_to_full_request_meter():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_knowledge_view
    content = " " * (9 * 1024 * 1024)
    source = {"ref": "owned:fixture", "version": "v1", "content_hash": "sha256:fixture", "content": content}
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_KNOWLEDGE_BUDGET_EXCEEDED"):
        build_provider_knowledge_view([source])
    prepared = build_provider_knowledge_view([source], complete_request_capacity=True)
    assert prepared[0]["content"] == content
    projection = prepare_request_capacity(original={"knowledge": prepared}, stage="draft", source_boundary={},
        route=route(), measure=lambda _: (500_000, 512_000),
        model_call=lambda *_: pytest.fail("fitting complete requests must not be compressed"), chunk_fits=lambda _: True)
    assert projection is None


def source_data(paragraphs=24, width=300):
    return {"input_manifest": {"exact_current_draft": "Current draft remains exact."},
        "context_bundle": {"segments": [{"asset_type": "chapter_episodic_summary",
            "safe_summary": "\n\n".join(f"Earlier incident {index}: " + "a" * width for index in range(paragraphs)),
            "structured_facts": [{"condition": "The oath must expire before departure.", "knowledge_owner": "Mei only"}]}]}}


def run_preparation(data, *, limit=2500, overhead=100, supported=True, fits=None, cache=None):
    calls = []
    cache = {} if cache is None else cache
    boundary = {"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b",
                "sources": [{"asset_version_id": "context:one", "content_hash": "sha256:" + "a" * 64}]}

    def measure(projection):
        value = apply_capacity_projection(data, projection) if projection else data
        return len(json.dumps(value, ensure_ascii=False).encode()) + overhead, limit

    def call(stage, task):
        key = stage + json.dumps(task, sort_keys=True)
        if key not in cache:
            calls.append((stage, deepcopy(task)))
            cache[key] = ({"selected_unit_ids": [task["units"][0]["unit_id"]] if len(task["units"][0]["text"].encode()) < task["target_tokens"] else []} if stage == "context_compress" else
                          {"supported": supported, "coverage_complete": supported, "missing_unit_ids": [], "distorted_unit_ids": []})
        return cache[key]

    result = prepare_request_capacity(original=data, stage="draft", source_boundary=boundary,
        route=route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture", limit=limit),
        measure=measure, model_call=call, chunk_fits=fits or (lambda chunk: len(json.dumps(chunk["units"])) < 1100))
    return result, calls


def test_materials_fit_but_complete_request_overflows_and_downstream_consumes_extract():
    data = source_data(12, 100)
    original_bytes = len(json.dumps(data).encode())
    fast, calls = run_preparation(data, limit=original_bytes + 100)
    assert fast is None and not calls
    projection, calls = run_preparation(data, limit=original_bytes + 99, overhead=100)
    assert projection and calls
    final = apply_capacity_projection(data, projection)
    assert final["input_manifest"] == data["input_manifest"]
    assert final["context_bundle"]["segments"][0]["structured_facts"] == data["context_bundle"]["segments"][0]["structured_facts"]
    assert final != data
    assert projection["measurement"]["after_reserved"] <= projection["measurement"]["limit"]


def test_more_than_eight_chunks_and_large_paragraph_do_not_impose_lifetime_failure():
    projection, calls = run_preparation(source_data(40, 200), limit=6000)
    assert projection and sum(stage == "context_compress" for stage, _ in calls) > 8
    oversized, calls = run_preparation(source_data(1, 8000), limit=4000)
    assert oversized and len(calls) > 2
    assert all(len(json.dumps(task["units"])) < 1100 for _, task in calls)


def test_fidelity_restore_has_no_silent_drop_and_sources_are_rechecked():
    data = source_data()
    with pytest.raises(KernelError, match="REQUIRED_BUDGET_EXCEEDED|COMPRESSION_NO_PROGRESS"):
        run_preparation(data, supported=False)
    projection, _ = run_preparation(data, limit=5000)
    changed = deepcopy(data)
    changed["input_manifest"]["exact_current_draft"] = "A new selected draft."
    with pytest.raises(KernelError, match="SOURCE_DRIFT"):
        apply_capacity_projection(changed, projection)


def test_deterministic_restart_reuses_successful_chunk_inputs():
    cache = {}
    data = source_data()
    first, calls = run_preparation(data, limit=5000, cache=cache)
    second, replay_calls = run_preparation(data, limit=5000, cache=cache)
    assert calls and not replay_calls and first == second


def test_necessary_content_cannot_be_dropped_to_fit():
    with pytest.raises(KernelError, match="REQUIRED_BUDGET_EXCEEDED"):
        run_preparation({"input_manifest": {"exact_draft": "x" * 3000}, "context_bundle": {}}, limit=100)


def test_preserved_quote_survives_oversized_unit_boundaries_without_new_separators():
    from novel_forge.modules.context_builder.task_compression import _split_oversized_units, _join_source_text
    quote = "abcdefghijklmno.pqr"
    text = quote + "XYZ" * 20
    units = _split_oversized_units([{"unit_id": "text:0", "text": text, "required": True,
        "field": "safe_summary", "index": 0}], lambda group: len(group[0]["text"]) <= 20, preserve_quotes=(quote,))
    restored = _join_source_text(units)
    assert restored == text and quote in restored


def test_fidelity_restore_reallocates_other_history_after_a_plateau():
    data = {"context_bundle": {"segments": [
        {"asset_type": "chapter_episodic_summary", "safe_summary": "A" * 900},
        {"asset_type": "chapter_episodic_summary", "safe_summary": "\n\n".join("B" * 700 + str(i) for i in range(4))}]}}
    boundary = {"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b",
        "sources": [{"asset_version_id": "context:one", "content_hash": "sha256:" + "a" * 64}]}
    calls = []
    def call(stage, task):
        calls.append((stage, task))
        is_a = task["units"][0]["text"].startswith("A")
        if stage == "context_compress":
            return {"selected_unit_ids": [task["units"][0]["unit_id"]] if task["target_tokens"] >= 701 else []}
        return {"supported": not is_a, "coverage_complete": not is_a, "missing_unit_ids": [], "distorted_unit_ids": []}
    projection = prepare_request_capacity(original=data, stage="draft", source_boundary=boundary,
        route=route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture", limit=1700),
        measure=lambda p: (len(json.dumps(apply_capacity_projection(data,p) if p else data).encode()) + 100,1700),
        model_call=call, chunk_fits=lambda _: True)
    derived = apply_capacity_projection(data, projection)
    assert derived["context_bundle"]["segments"][0]["safe_summary"] == "A" * 900
    assert projection["measurement"]["after_reserved"] <= 1700
    assert sum(stage == "context_compress" and task["units"][0]["text"].startswith("A") for stage, task in calls) == 1


def test_unavailable_tokenizer_is_an_actionable_admission_failure():
    with pytest.raises(KernelError, match="PROVIDER_TOKENIZER_UNAVAILABLE"):
        count_text("An original source", method="MODEL_TOKENIZER_V1", model="unverified-model-alias")


def test_capacity_preparation_only_narrows_the_final_router_without_authorizing_it():
    from dataclasses import asdict
    from novel_forge.modules.production_execution.cost_routing import CostAwareRouter
    from novel_forge.modules.production_execution.routing_runtime import ProductionProviderRouter
    from tests.unit.test_cost_aware_routing import candidate, task, samples, NOW
    cheaper, prepared = candidate("cheap", "1"), candidate("prepared", "2")
    binding = {"candidate": {key: asdict(prepared)[key] for key in
        ("candidate_id", "provider", "model", "model_revision", "reasoning", "context_limit", "output_limit")}, "route": {}}
    values = {"cheap": samples(), "prepared": samples()}
    unbound = CostAwareRouter().explain(task(), [cheaper, prepared], values, now=NOW).to_dict()
    assert unbound["selected"]["candidate"]["candidate_id"] == "cheap"
    narrowed = CostAwareRouter().explain(task(declared_requirements={"capacity_route_binding": binding}),
        [cheaper, prepared], values, now=NOW).to_dict()
    assert narrowed["selected"]["candidate"]["candidate_id"] == "prepared"
    unavailable = replace(prepared, available=False)
    denied = CostAwareRouter().explain(task(declared_requirements={"capacity_route_binding": binding}),
        [cheaper, unavailable], values, now=NOW).to_dict()
    assert not denied["selected"]
    router = ProductionProviderRouter("postgresql://not-connected", candidates=[prepared], task_money_limit="1", task_token_limit=1)
    with pytest.raises(KernelError, match="ROUTING_CAPACITY_PREPARATION_ONLY"):
        router.select(None, task_type="draft", project_id="p", work_id="b", operation_id="o", attempt_id="a",
            stable_key="k", input_tokens=1000, output_tokens=100, trace_id="t", correlation_id="c", prepare_capacity=True)


def test_codex_separate_protocol_schema_is_frozen_and_included_in_capacity():
    from novel_forge.modules.production_execution.token_meter import route_input_tokens, route_protocol_schema
    from novel_forge.modules.chapter_authority.context_compression_provider import CLI_CONTEXT_HEADROOM_POLICY
    schema = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"], "additionalProperties": False}
    configured = route(method="CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1", model="fixture-codex", limit=512000)
    configured.model_profile.model_provider = "codex-cli"
    configured.output_reservation_policy = CLI_CONTEXT_HEADROOM_POLICY
    protocol_schema = route_protocol_schema(configured, schema, "fixture-schema:v1")
    contract = build_route_token_accounting_contract(provider="codex-cli", model="fixture-codex", route_identity="fixture:cli",
        accounting_method=configured.token_accounting_method, accounting_evidence_ref="fixture:cli",
        model_context_limit=512000, execution_token_limit=512000, output_reserve=100,
        safety_margin=0, framing_overhead=0, contract_version="provider-token-accounting-v4")
    envelope = ProviderRequestEnvelope("codex-cli", "fixture-codex", "codex-cli-application-stdin-v1", "visible schema in Prompt", 100, 60, "fixture",
        protocol_schema_json=protocol_schema)
    receipt = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert receipt.status == "ADMITTED"
    assert receipt.component_usage["application_protocol_schema"] == len(protocol_schema.encode())
    assert receipt.total_reserved == route_input_tokens(configured, envelope.input_text, protocol_schema_json=protocol_schema) + 100
    assert ProviderRequestEnvelope.from_identity_dict(envelope.to_identity_dict(), input_text=envelope.input_text) == envelope
    assert replace(envelope, protocol_schema_json="{}").envelope_hash != envelope.envelope_hash


def test_cli_backend_checks_the_actual_schema_file_before_starting_a_process(tmp_path):
    import sys
    from novel_forge.modules.production_execution import (
        CodexCliExecutionBackend, CodexProcessSupervisor, ExecutionRuntimeClass,
        InMemoryExecutionRecordStore, LocalProcessExecutionPolicy, PersistentExecutionDirectory,
        ResolvedExecutionPayload, StaticExecutionPayloadResolver,
    )
    from novel_forge.modules.production_execution.backends import CodexPricingSnapshot
    from novel_forge.modules.production_execution.token_meter import route_protocol_schema
    from tests.unit.test_execution_backend_conformance import QualifiedBackendConformanceTests
    from tests.unit.test_production_execution_gateway import contracts
    _, admission, request = QualifiedBackendConformanceTests._model_admission(contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE))
    directory = PersistentExecutionDirectory(tmp_path / "executions")
    backend = CodexCliExecutionBackend(admission=admission, payload_resolver=StaticExecutionPayloadResolver({}),
        record_store=InMemoryExecutionRecordStore(), supervisor=CodexProcessSupervisor(directory),
        execution_policy=LocalProcessExecutionPolicy(fixed_working_directory=str(tmp_path),
            allowed_command_prefixes=((sys.executable,),), maximum_result_bytes=1_000_000),
        codex_executable=sys.executable, codex_home=str(tmp_path),
        pricing=CodexPricingSnapshot("fixture", "fixture:price", "USD", "0", "0", "0"),
        structured_result_validator=lambda *_: None)
    selected = admission.admit(request, backend.capability_profile)
    schema = {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"], "additionalProperties": False}
    configured = route(model="fixture-codex")
    configured.model_profile.model_provider = "codex-cli"
    frozen = route_protocol_schema(configured, schema, "fixture:v1")
    payload = ResolvedExecutionPayload(request_payload={"protocol_schema_json": frozen}, input_text="task",
        working_directory=str(tmp_path), timeout_seconds=60, output_schema_version="fixture:v1", output_schema=schema)
    prepared = backend._prepare_payload(request, payload, selected)
    schema_path = prepared.command[prepared.command.index("--output-schema") + 1]
    from pathlib import Path
    assert Path(schema_path).read_bytes() == frozen.encode()
    with pytest.raises(ValueError, match="PROVIDER_PROTOCOL_SCHEMA_DRIFT"):
        backend._prepare_payload(request, replace(payload, output_schema={**schema, "description": "changed"}), selected)
