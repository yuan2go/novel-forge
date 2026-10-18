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


@pytest.mark.parametrize("paragraphs,limit", [(600, 30000), (14000, 500000)])
def test_working_passages_batch_by_original_source_and_duplicate_wrappers_share_extract(paragraphs, limit):
    working = {"projection_policy": {"recent_complete_chapters": 2}, "target_chapter": 4,
        "sources": [{"chapter": 1, "asset_version_id": "chapter:one", "content_hash": "sha256:original",
            "passages": [{"text": f"Original paragraph {i}: " + "a" * 100} for i in range(paragraphs)]}]}
    data = {"context_bundle": {"working_manuscript": deepcopy(working)}, "input_manifest": {"working_manuscript": deepcopy(working)}}
    cache = {}
    projection, calls = run_preparation(data, limit=limit, fits=lambda _: True, cache=cache)
    final = apply_capacity_projection(data, projection)
    assert final["context_bundle"]["working_manuscript"] == final["input_manifest"]["working_manuscript"]
    assert len(projection["replacements"]) == paragraphs * 2
    assert sum(stage == "context_compress" for stage, _ in calls) == (paragraphs + 255) // 256
    assert all(task["task"]["source_expression"]["asset_version_id"] == "chapter:one" for _, task in calls)
    from novel_forge.modules.chapter_authority.context_compression_provider import context_compression_task_view
    for stage, task in calls:
        view = context_compression_task_view(stage, {"context_compression_task": task})
        assert view["task"]["source_expression"] == {"asset_version_id": "chapter:one", "content_hash": "sha256:original", "chapter": 1}
    assert len(json.dumps(final).encode()) + 100 <= limit
    replay, additional_calls = run_preparation(dict(reversed(list(data.items()))), limit=limit, fits=lambda _: True, cache=cache)
    assert replay == projection and not additional_calls


def test_necessary_content_cannot_be_dropped_to_fit():
    with pytest.raises(KernelError, match="REQUIRED_BUDGET_EXCEEDED"):
        run_preparation({"input_manifest": {"exact_draft": "x" * 3000}, "context_bundle": {}}, limit=100)


def test_rendered_extract_keeps_large_host_mapping_out_of_prompt_and_stays_frozen(monkeypatch):
    from novel_forge.modules.chapter_authority import execution_gateway as gateway
    passages = []
    position = 0
    for index in range(600):
        text = f"Original paragraph {index}: " + "a" * 100
        passages.append({"text": text, "start": position, "end": position + len(text),
            "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()})
        position += len(text)
    working = {"projection_policy": {"version": "working-prose-projection.v6", "recent_complete_chapters": 2}, "target_chapter": 4,
        "sources": [{"chapter": 1, "asset_version_id": "chapter:one", "content_hash": "sha256:original",
            "source_characters": position, "passages": passages}]}
    monkeypatch.setattr(gateway, "build_provider_task_view", lambda *_args, **_kw: {"contract_version": "fixture:task", "task_working_manuscript": deepcopy(working)})
    monkeypatch.setattr(gateway, "build_provider_context_view", lambda *_args, **_kw: {"contract_version": "fixture:context", "context_working_manuscript": deepcopy(working)})
    materialization = {"materialization_hash": "sha256:fixture", "pack_artifacts": {
        key: {"ref": key, "version": "v1", "content": {"text": text}}
        for key, text in {"system_instruction": "Keep source boundaries.", "skill": "Use exact supplied text.",
            "prompt_template": "{{input_manifest}} {{context_bundle}}"}.items()},
        "context_selection": [{"content": {"working_manuscript": working}}], "knowledge_selection": [{"ref": "knowledge:fixture", "content": {"rule": "Keep source attribution."}}],
        "tool_permissions": {"allowed": ["model.provider.invoke"]},
        "output_schema": {"ref": "schema:fixture", "content": {"type": "object"}}}
    materialization["pack_artifacts"]["prompt_template"].update(ref="prompt-template:chapter-generation-pack", version="v13")
    rendered_evidence = []
    def render(projection=None, capture=None):
        text, evidence = gateway._materialize_production_codex_prompt(stage="draft",
            target_scope={"scope_kind": "book", "scope_id": "b", "project_id": "p", "book_id": "b"},
            inputs={"_context_capacity_projection": projection} if projection else {},
            materialization=materialization, provider_data_capture=capture)
        rendered_evidence.append(evidence)
        return text
    original = {}
    before = render(capture=original)
    measured = []
    measured_transports = []
    def measure(projection):
        text = render(projection)
        measured.append(text)
        if projection is not None:
            measured_transports.append(projection.get("provider_extract_transport"))
        return len(text.encode()), 30000
    projection = prepare_request_capacity(original=original, stage="draft", route=route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture"),
        source_boundary={"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b", "sources": [{"asset_version_id": "context:one", "content_hash": "sha256:fixture"}]},
        measure=measure, chunk_fits=lambda _: True,
        model_call=lambda stage, task: {"selected_unit_ids": [task["units"][0]["unit_id"]]} if stage == "context_compress" else
            {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []})
    final = render(projection)
    assert final == measured[-1]
    assert len(final.encode()) < 30000 < len(before.encode())
    assert len(projection["replacements"]) == 1200
    from novel_forge.modules.context_builder.request_capacity import STORY_EXTRACT_TRANSPORT
    assert set(measured_transports) == {STORY_EXTRACT_TRANSPORT}
    assert projection["provider_extract_transport"] == STORY_EXTRACT_TRANSPORT
    assert rendered_evidence[-1]["provider_view"]["capacity_projection"]["original_hash"] == projection["original_hash"]
    for internal in ("historical_expressions", "source_projection_hash", "result_projection_hash",
                     "supplied_projection_hash", "derivation_hash", "mapping_custody", "final_composition_hash"):
        assert '"' + internal + '"' not in final
    legacy = deepcopy(projection)
    legacy.pop("provider_extract_transport")
    assert '"derivation_hash"' in render(legacy) and '"mapping_custody"' in render(legacy)
    unsupported = {**projection, "provider_extract_transport": "unsupported-future-format"}
    with pytest.raises(KernelError, match="CONTEXT_EXTRACT_TRANSPORT_INVALID"):
        render(unsupported)
    assert "chapter:one" in final and "sha256:original" in final and '"historical_extract":' in final
    from novel_forge.modules.context_builder.request_capacity import project_capacity_passages
    supplied = project_capacity_passages(original, apply_capacity_projection(original, projection), projection)
    source = supplied["context_bundle"]["context_working_manuscript"]["sources"][0]
    full = "".join(passage["text"] for passage in passages)
    assert source["omitted_ranges"] and len(source["passages"]) == 3
    assert len(working["sources"][0]["passages"]) == 600
    for passage in source["passages"]:
        assert full[passage["start"]:passage["end"]] == passage["text"]
        assert passage["text_hash"] == "sha256:" + hashlib.sha256(passage["text"].encode()).hexdigest()


def test_preserved_quote_survives_oversized_unit_boundaries_without_new_separators():
    from novel_forge.modules.context_builder.task_compression import _split_oversized_units, _join_source_text
    quote = "abcdefghijklmno.pqr"
    text = quote + "XYZ" * 20
    units = _split_oversized_units([{"unit_id": "text:0", "text": text, "required": True,
        "field": "safe_summary", "index": 0}], lambda group: len(group[0]["text"]) <= 20, preserve_quotes=(quote,))
    restored = _join_source_text(units)
    assert restored == text and quote in restored


@pytest.mark.parametrize("rich_row", [False, True])
def test_sparse_passages_keep_source_ownership_unicode_ranges_and_rich_fields(rich_row):
    from novel_forge.modules.context_builder.request_capacity import project_capacity_passages
    from novel_forge.modules.narrative_state.reality import narrative_hash
    text = "甲🙂\r\n乙\n\n丙仍不知道证人已离开。"
    passage = {"start": 0, "end": len(text), "text": text, "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()}
    if rich_row:
        passage["required_condition"] = "The witness must first consent."
    source = {"chapter": 1, "asset_version_id": "draft:one", "content_hash": "sha256:original",
        "status": "UNREVIEWED_WORKING_PROSE", "character_knowledge": "NOT_VERIFIED", "source_characters": len(text), "passages": [passage]}
    original = {"working_manuscript": {"projection_policy": {"recent_complete_chapters": 2}, "target_chapter": 4, "sources": [source]}}
    frozen = deepcopy(original)
    projection = {"contract_version": "complete-request-capacity.v1", "original_hash": narrative_hash(original),
        "replacements": [{"path": ["working_manuscript", "sources", 0, "passages", 0, "text"],
            "source_text_hash": narrative_hash(text), "ranges": [[0, 2], [7, len(text)]]}]}
    raw = deepcopy(original)
    raw["working_manuscript"]["sources"][0]["passages"][0]["text"] = text[:2] + "\n\n" + text[7:]
    projection["result_hash"] = narrative_hash(raw)
    supplied = project_capacity_passages(original, apply_capacity_projection(original, projection), projection)["working_manuscript"]["sources"][0]
    assert original == frozen
    assert {key: supplied[key] for key in ("asset_version_id", "content_hash", "status", "character_knowledge")} == {key: source[key] for key in ("asset_version_id", "content_hash", "status", "character_knowledge")}
    if rich_row:
        assert supplied["passages"][0]["required_condition"] == passage["required_condition"]
        assert "historical_extract" not in supplied
    else:
        assert supplied["omitted_ranges"] == [[2, 7]]
        assert [(row["start"], row["end"], row["text"]) for row in supplied["passages"]] == [(0, 2, text[:2]), (7, len(text), text[7:])]


@pytest.mark.parametrize("limit", [1300, 1500, 1700])
def test_fidelity_restore_reallocates_other_history_after_a_plateau(limit):
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
        route=route(method="SCRIPTED_UTF8_BYTES_EXACT_V1", model="fixture", limit=limit),
        measure=lambda p: (len(json.dumps(apply_capacity_projection(data,p) if p else data).encode()) + 100,limit),
        model_call=call, chunk_fits=lambda _: True)
    derived = apply_capacity_projection(data, projection)
    assert derived["context_bundle"]["segments"][0]["safe_summary"] == "A" * 900
    assert projection["measurement"]["after_reserved"] <= limit
    assert sum(stage == "context_compress" and task["units"][0]["text"].startswith("A") for stage, task in calls) == 1


def test_unavailable_tokenizer_is_an_actionable_admission_failure():
    with pytest.raises(KernelError, match="PROVIDER_TOKENIZER_UNAVAILABLE"):
        count_text("An original source", method="MODEL_TOKENIZER_V1", model="unverified-model-alias")


def test_restored_material_floor_cannot_inflate_substage_target_above_its_schema():
    from novel_forge.modules.context_contracts import ContextCandidate
    from novel_forge.modules.context_builder.task_compression import compile_task_context
    from novel_forge.modules.chapter_authority.context_compression_provider import context_compression_task_view
    quote = "Necessary condition: " + "a" * 20000
    boundary = {"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b",
        "sources": [{"asset_version_id": "context:one", "content_hash": "sha256:fixture"}]}
    candidate = ContextCandidate(asset_version_id="history:one", asset_type="historical_expression_projection", project_id="p",
        estimated_tokens=1, relevance_score=1, safe_summary="\n\n".join([quote] * 32 + ["optional " * 25000]),
        provenance={"frozen_input_boundary": boundary, "source_binding": boundary["sources"][0]})
    targets = []
    def call(stage, task):
        view = context_compression_task_view(stage, {"context_compression_task": task})
        targets.append(view["target_tokens"])
        return {"selected_unit_ids": task["required_unit_ids"]} if stage == "context_compress" else {
            "supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}
    _, receipt = compile_task_context([candidate], task={"stage": "draft", "frozen_input_boundary": boundary,
        "source_projection_hash": "sha256:fixture", "preserve_quotes": [quote]}, token_budget=200000,
        required_asset_types=(), model_call=call, compression_input_tokens=512000,
        token_counter=lambda value: len(json.dumps(value, ensure_ascii=False)), chunk_fits=lambda _: True,
        allow_restored_overflow=True)
    assert receipt["effective_material_target_tokens"] > 512000
    assert targets and all(0 < target <= 512000 for target in targets)


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


@pytest.mark.parametrize("metadata_version", [{"schema": "fixture.v1"}, ["fixture.v1"]])
def test_quote_protection_recurses_through_structured_version_metadata(metadata_version):
    from novel_forge.modules.context_builder.request_capacity import (
        protected_expression_quotes, validate_projection_quotes, working_observation_index,
    )

    quote = "她将旧凿留在住处，带着小册去上课。"
    observation = {"version": "working-observations.v1", "authority": "UNREVIEWED_WORKING_OBSERVATIONS",
        "entries": [{"observation_id": "working:chapter1:one", "quote": quote, "location": {"quote": quote},
            "source": {"asset_version_id": "draft:one", "content_hash": "sha256:" + "a" * 64}}]}
    payload = {"version": metadata_version, "nested": [{"version": metadata_version}], "working": observation,
        "source": {"asset_version_id": "draft:one", "safe_summary": quote}, "preserve_quotes": [quote]}
    assert protected_expression_quotes(payload, include_working_observations=True) == (quote,)
    assert working_observation_index(payload) == {("draft:one", "sha256:" + "a" * 64): [observation["entries"][0]]}
    assert validate_projection_quotes(payload, (quote,))
    omitted = {**payload, "source": {"asset_version_id": "draft:one", "safe_summary": "她仍在住处。"}}
    with pytest.raises(KernelError, match="QUOTE"):
        validate_projection_quotes(omitted, (quote,))
