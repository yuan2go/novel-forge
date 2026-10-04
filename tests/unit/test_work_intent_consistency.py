from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from novel_forge.modules.chapter_authority.chapter_plan_views import (
    build_creative_baseline,
    build_draft_plan_view,
    build_draft_style_view,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    _materialize_production_codex_prompt,
    PostgresChapterExecutionContractBinder,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_task_view,
)
from novel_forge.modules.chapter_quality_authority.context_views import (
    build_quality_context_view,
)
from novel_forge.modules.chapter_quality_authority.domain import (
    build_quality_group_evidence,
)
from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    default_chapter_artifact_resolver,
)
from novel_forge.modules.content_quality_loop.domain import derive_quality_actions
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution import ExecutionRuntimeClass
from tests.unit.test_capability_pack_artifact_materialization import (
    _prompt_materialization,
)
from tests.unit.test_production_execution_gateway import contracts
from tests.unit.test_quality_context_authority import _bundle


ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64


def work_input(style: str, thresholds: dict | None = None) -> tuple[dict, dict, dict]:
    plan = {
        "chapter": 1,
        "title": "观察",
        "premise": "人物在冬日观察城市。",
        "point_of_view": "第三人称限知",
        "target_word_count": 2000,
        "prohibited_outcomes": [],
        "style_constraints": [style],
        "source_chapter_plan_asset_version_id": "plan:v1",
        "source_chapter_plan_content_hash": HASH,
    }
    context = _bundle()
    for segment in context["context_segments"]:
        if segment["asset_type"] in {"canon_snapshot", "story_state_snapshot"}:
            segment["structured_facts"] = []
    context["context_segments"][0]["structured_facts"] = [
        {"key": "thresholds", "value": thresholds or {}}
    ]
    context["production_input_manifest"]["style_policy_version_id"] = "style:v1"
    context["context_segments"].append(
        {
            "asset_type": "style_policy",
            "asset_version_id": "style:v1",
            "content_digest": HASH,
            "safe_summary": "本书语气",
            "source_expression_included": False,
            "structured_facts": [{"key": "style_constraints", "value": [style]}],
        }
    )
    candidate = {
        "chapter": 1,
        "title": plan["title"],
        "text": "雪落在街道上。" * 20,
        "creative_baseline": build_creative_baseline(plan, context),
    }
    return plan, context, candidate


def final_input(stage: str, style: str) -> tuple[str, dict]:
    plan, context, candidate = work_input(style)
    context["host_quality_evidence"] = {"contract_version": "accepted-quality-host-projection.v1",
        "provider_visibility": "INTERNAL_QUALITY_ONLY", "segments": [{"structured_facts": [{"private": "SYNTHETIC_HOST_ONLY_MARKER"}]}]}
    materialization = _prompt_materialization(context)
    resolver = default_chapter_artifact_resolver(ROOT)
    template = resolver.resolve(
        ArtifactKind.PROMPT_TEMPLATE, "prompt-template:chapter-generation-pack", "v8"
    )
    materialization["pack_artifacts"]["prompt_template"] = template.to_dict()
    for kind, key, ref, version in (
        (ArtifactKind.PROMPT_SYSTEM_INSTRUCTION, "system_instruction", "prompt-system:chapter-generation-pack", "v3"),
        (ArtifactKind.SKILL, "skill", "prose-generation" if stage in {"draft", "revision"} else "quality-review", "prose-generation-v4" if stage in {"draft", "revision"} else "quality-review-v3"),
    ):
        materialization["pack_artifacts"][key] = resolver.resolve(kind, ref, version).to_dict()
    materialization["knowledge_selection"] = [
        resolver.resolve(ArtifactKind.KNOWLEDGE, "knowledge:chapter-causal-cost:v2", "v2").to_dict()
    ]
    inputs = {
        "draft": candidate,
        "revision": candidate,
        "review": {"issues": []},
        "plan": build_draft_plan_view(plan, work_requirements=True),
        "style": build_draft_style_view(context, work_requirements=True),
    }
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage=stage, request_payload={"input": inputs}, prompt_contract_version="v8")
    materialization["output_schema"] = {"ref": ref, "content": schema, "content_hash": "sha256:" + hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    *_, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
    )
    return _materialize_production_codex_prompt(
        request=request, stage=stage, inputs=inputs, materialization=materialization
    )


@pytest.mark.parametrize("stage", ["draft", "review", "revision", "rereview"])
def test_style_changes_at_actual_materializer_in_both_directions(stage):
    restrained, _ = final_input(stage, "克制冷峻，允许长句，禁止笑点")
    humorous, _ = final_input(stage, "轻松幽默，适合儿童")
    assert "克制冷峻，允许长句，禁止笑点" in restrained
    assert "轻松幽默，适合儿童" not in restrained
    assert "轻松幽默，适合儿童" in humorous
    assert "克制冷峻，允许长句，禁止笑点" not in humorous


def test_new_projection_is_explicit_and_legacy_projection_remains_frozen():
    plan, context, _ = work_input("合法长句")
    assert "style_constraints" not in build_draft_plan_view(plan)
    assert build_draft_plan_view(plan, work_requirements=True)["style_constraints"] == [
        "合法长句"
    ]
    assert build_draft_style_view(context)["contract_version"] == "draft-style-view-v1"
    for stage in ("review", "revision", "rereview"):
        with pytest.raises(KernelError, match="CREATIVE_BASELINE_REQUIRED"):
            build_provider_task_view(
                stage, {"draft": {}, "revision": {}}, work_requirements=True
            )


def quality_result(thresholds: dict) -> dict:
    plan, context, candidate = work_input("观察性叙述", thresholds)
    view = build_quality_context_view(
        group="structural",
        revision=candidate,
        revision_asset_version_id="candidate:v1",
        chapter_plan=plan,
        chapter_plan_asset_version_id="plan:v1",
        context_bundle=context,
        context_bundle_asset_version_id="context:v1",
        canon={},
        canon_asset_version_id="canon:v1",
        work_requirements=True,
    )
    return build_quality_group_evidence(
        group="structural",
        project_id="project-1",
        revision=candidate,
        revision_asset_version_id="candidate:v1",
        context_bundle=context,
        canon={},
        fixture=True,
        quality_context=view,
    )


def test_compiled_measurement_controls_formula_report_and_action():
    reports = []
    for limit in (6, 200):
        result = quality_result({"maximum_average_paragraph": limit})
        report = next(
            item
            for item in result["dimensions"]
            if item["dimension"] == "paragraph_structure"
        )
        reports.append(report)
        assert report["threshold"] == limit
        assert report["evidence_locations"][0]["threshold"] == limit
        assert report["evidence_locations"][0]["unit"] == "CODEPOINTS"
        assert (
            report["creative_judgment"] == "CONFIGURED_MEASUREMENT_NOT_LITERARY_PROOF"
        )
    assert [item["gate_status"] for item in reports] == ["FAILED", "PASSED"]


def test_missing_aesthetic_measurement_does_not_use_legacy_sentence_or_paragraph_limit():
    result = quality_result({})
    by_dimension = {item["dimension"]: item for item in result["dimensions"]}
    assert by_dimension["readability"]["gate_status"] == "INSUFFICIENT_EVIDENCE"
    assert by_dimension["readability"]["score"] is None
    assert by_dimension["readability"]["weight"] == 0
    assert by_dimension["paragraph_structure"]["gate_status"] == "INSUFFICIENT_EVIDENCE"
    pending = {**by_dimension["readability"], "evidence_asset_version_id": "quality:v1"}
    action = derive_quality_actions([pending])[0]
    assert action["required_action"] == "EVIDENCE_REASSESSMENT"
    assert action["permitted_change_scope"] == "EVIDENCE_ONLY"
    failed = deepcopy(pending)
    failed.update(
        gate_status="FAILED", evidence_locations=[{"quote": "不合本书要求的精确原文"}]
    )
    assert derive_quality_actions([failed])[0]["required_action"] == "LOCAL_REPAIR"


def test_quality_rejects_baseline_version_drift_instead_of_rescoring_another_work():
    plan, context, candidate = work_input("原始风格")
    plan["style_constraints"] = ["另一风格"]
    with pytest.raises(KernelError, match="QUALITY_CREATIVE_BASELINE_DRIFT"):
        build_quality_context_view(
            group="source_originality",
            revision=candidate,
            revision_asset_version_id="candidate:v1",
            chapter_plan=plan,
            chapter_plan_asset_version_id="plan:v1",
            context_bundle=context,
            context_bundle_asset_version_id="context:v1",
            canon={},
            canon_asset_version_id="canon:v1",
            work_requirements=True,
        )


def test_non_applicable_methods_do_not_score_and_selected_methods_remain_gated():
    plan, context, candidate = work_input("观察性叙述")
    plan.update(chapter_contract_schema_version="chapter-mission-scene.v3", primary_function="observation",
                reward_action=None, promise_action=None, ending_hook=None, antagonist_actions=[], serialization_function=None)
    candidate['creative_baseline'] = build_creative_baseline(plan, context)
    def evaluate():
        view = build_quality_context_view(group='commercial', revision=candidate, revision_asset_version_id='candidate:v1',
            chapter_plan=plan, chapter_plan_asset_version_id='plan:v1', context_bundle=context,
            context_bundle_asset_version_id='context:v1', canon={}, canon_asset_version_id='canon:v1', work_requirements=True)
        return build_quality_group_evidence(group='commercial', project_id='project-1', revision=candidate,
            revision_asset_version_id='candidate:v1', context_bundle=context, canon={}, fixture=False, quality_context=view)
    reports = {r['dimension']: r for r in evaluate()['dimensions']}
    for dimension in ('golden_opening', 'reward', 'reader_promise', 'chapter_hook', 'antagonist_pressure'):
        assert reports[dimension]['gate_status'] == 'NOT_APPLICABLE'
        assert reports[dimension]['score'] is None
        assert reports[dimension]['weight'] == 0
        assert reports[dimension]['revision_strategy'] == []
    plan['reward_action'] = '兑现本书已选择的承诺'
    candidate['creative_baseline'] = build_creative_baseline(plan, context)
    reward = next(r for r in evaluate()['dimensions'] if r['dimension']=='reward')
    assert reward['gate_status'] == 'REQUIRES_PROVIDER_JUDGE'
    assert reward['blocking'] is True


def test_old_cached_score_is_not_reinterpreted_under_new_semantics():
    from novel_forge.modules.chapter_quality_authority.domain import _calibrated_evidence
    context = [{'asset_version_id': 'old:v1', 'structured_facts': [{'key': 'dimension_evidence', 'value': [
        {'dimension': 'style_drift', 'gate_status': 'PASSED', 'score': 100, 'fixture_protocol_only': True}
    ]}]}]
    assert _calibrated_evidence('style_drift', context, target_asset_version_id='candidate:v1', fixture=True) is not None
    assert _calibrated_evidence('style_drift', context, target_asset_version_id='candidate:v1', fixture=True,
        quality_policy_digest=HASH, creative_baseline_digest=HASH) is None


@pytest.mark.parametrize("stage", ["draft", "review", "revision", "rereview"])
def test_work_prompt_reaches_exact_sdk_boundary(stage):
    from types import SimpleNamespace
    from novel_forge.modules.production_execution.provider_admission import ProviderRequestEnvelope, build_route_token_accounting_contract, prepare_provider_admission
    from novel_forge.modules.provider_control.contracts import ProviderInvocationRequest
    from novel_forge.modules.provider_control.openai_v2 import OpenAISdkTransport
    from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE
    prompt, evidence = final_input(stage, "克制冷峻，允许长句，禁止笑点")
    assert evidence["provider_prompt_projection_version"] == "authority-projection-work-requirements.v1"
    seen = []
    response = SimpleNamespace(id="synthetic-request", output_text='{}', usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: seen.append(kwargs) or response))
    envelope = ProviderRequestEnvelope(provider="openai", model="synthetic-model", protocol="openai-responses-text-envelope-v1", input_text=prompt,
        max_output_tokens=4096, timeout_seconds=60, stable_idempotency_key="synthetic:"+stage, reasoning_effort="high")
    contract = build_route_token_accounting_contract(provider="openai", model=envelope.model, route_identity="synthetic-route", accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1", accounting_evidence_ref="synthetic-byte-bound", model_context_limit=512_000, execution_token_limit=512_000, output_reserve=4096, safety_margin=256, framing_overhead=32)
    admission = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    request = ProviderInvocationRequest(provider="openai", model=envelope.model, capability="model."+stage, stage=stage,
        stable_idempotency_key=envelope.stable_idempotency_key, request_payload=envelope.to_dict(), request_hash=envelope.envelope_hash,
        timeout_seconds=60, trace_id="synthetic-trace", correlation_id="synthetic-correlation", operation_id="synthetic-operation",
        external_effect_id="synthetic-effect", budget_reservation_id="synthetic-reservation", provider_admission=admission.to_dict())
    OpenAISdkTransport(client).execute(request)
    assert "SYNTHETIC_HOST_ONLY_MARKER" not in prompt
    assert seen[0]["input"] == prompt
    assert seen[0]["max_output_tokens"] == 4096
    assert "克制冷峻，允许长句，禁止笑点" in seen[0]["input"]
    schema = json.loads(prompt.split("<output_schema>\n", 1)[1].split("\n</output_schema>", 1)[0])
    assert schema["type"] == "object"
    assert "properties" in schema
    assert evidence["output_schema_ref"].startswith("schema:chapter-provider-output:")


@pytest.mark.parametrize("stage", ["draft", "review", "revision", "rereview"])
def test_work_prompt_reaches_native_http_boundary(stage):
    from dataclasses import replace
    from io import BytesIO
    from novel_forge.modules.production_execution.provider_admission import (
        ProviderRequestEnvelope, TokenAccountingContract,
        prepare_provider_admission,
    )
    from tests.unit.test_deepseek_provider import adapter, invocation, response
    from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE
    prompt, _ = final_input(stage, "轻松幻想，允许笑点")
    schema = json.loads(prompt.split("<output_schema>\n", 1)[1].split("\n</output_schema>", 1)[0])
    request = invocation()
    envelope = replace(ProviderRequestEnvelope.from_dict(request.request_payload),
        input_text=prompt, max_output_tokens=4096)
    contract = replace(TokenAccountingContract.from_dict(request.provider_admission["accounting_contract"]),
        model_context_limit=512000, execution_token_limit=512000, output_reserve=4096)
    admission = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    request = replace(request, stage=stage, request_payload=envelope.to_dict(), request_hash=envelope.envelope_hash,
        provider_admission=admission.to_dict())
    seen = []
    def transport(wire, **kwargs):
        seen.append(json.loads(wire.data))
        return BytesIO(json.dumps(response()).encode())
    adapter(transport=transport).invoke(request)
    assert seen[0]["messages"] == [{"role": "user", "content": prompt}]
    assert json.loads(seen[0]["messages"][0]["content"].split("<output_schema>\n", 1)[1].split("\n</output_schema>", 1)[0]) == schema
    assert "tools" not in seen[0]
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "SYNTHETIC_HOST_ONLY_MARKER" not in prompt


def test_work_prompt_reaches_isolated_cli_stdin(tmp_path):
    import sys
    from tests.unit.test_production_execution_gateway import (
        AdmissionController, StaticExecutionContractSource, StaticAttemptFenceVerifier,
        PersistentExecutionDirectory, InMemoryExecutionRecordStore, CodexCliExecutionBackend,
        StaticExecutionPayloadResolver, ResolvedExecutionPayload, CodexProcessSupervisor,
        LocalProcessExecutionPolicy, ExecutionBackendRegistry, ProductionExecutionGateway, ExecutionOutcome,
    )
    prompt, evidence = final_input("draft", "克制冷峻，允许长句，禁止笑点")
    capability, profile, policy, route, manifest, request = contracts(
        backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    source = StaticExecutionContractSource(route_snapshots=(route,), model_profiles=(profile,),
        route_policies=(policy,), input_manifests=(manifest,))
    admission = AdmissionController(source, StaticAttemptFenceVerifier({("operation:1", "attempt:1"): 7}))
    directory = PersistentExecutionDirectory(tmp_path / "executions")
    result_path = directory.prepare(request.execution_id).result_path("result.json")
    stdin_path = tmp_path / "synthetic-stdin.txt"
    command = (sys.executable, "-c", "import json,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read()); pathlib.Path(sys.argv[2]).write_text(json.dumps({'text':'synthetic process receipt'}))", str(stdin_path), str(result_path))
    backend = CodexCliExecutionBackend(admission=admission,
        payload_resolver=StaticExecutionPayloadResolver({request.execution_id: ResolvedExecutionPayload(
            request_payload={"input": {"chapter": 1}}, input_text=prompt, working_directory=str(tmp_path),
            timeout_seconds=5, output_schema_version=evidence["output_schema_ref"], command=command)}),
        record_store=InMemoryExecutionRecordStore(), supervisor=CodexProcessSupervisor(directory),
        execution_policy=LocalProcessExecutionPolicy(fixed_working_directory=str(tmp_path),
            allowed_command_prefixes=((sys.executable,),), maximum_result_bytes=1000000))
    registry = ExecutionBackendRegistry()
    registry.register(backend)
    gateway = ProductionExecutionGateway(registry, admission)
    result = gateway.reconcile(gateway.submit(request))
    assert result.outcome is ExecutionOutcome.SUCCEEDED
    assert stdin_path.read_text() == prompt
    assert "SYNTHETIC_HOST_ONLY_MARKER" not in stdin_path.read_text()


def test_native_frontier_aliases_preserve_exact_identity_without_hiding_missing_state():
    from novel_forge.modules.chapter_authority.context_compression_provider import compression_boundary_identity
    legacy = {"accepted_through_chapter": 0, "canon_snapshot_version": "canon:v1", "story_state_snapshot_version": "state:v1"}
    normalized = compression_boundary_identity(legacy, strict=True)
    assert compression_boundary_identity(normalized, strict=True) == normalized
    for incomplete in ({}, {"accepted_through_chapter": 0}, {**legacy, "canon_snapshot_asset_version_id": "different:v1"}):
        with pytest.raises(KernelError, match="ACCEPTED_BOUNDARY_INVALID"):
            compression_boundary_identity(incomplete, strict=True)


@pytest.mark.parametrize("judgment", ["UNCERTAIN", "AESTHETIC_SUGGESTION"])
def test_evidence_or_advice_cannot_automatically_rewrite_prose(judgment):
    from novel_forge.modules.revision.domain import apply_revision_result
    plan, context, draft = work_input("保留观察性长句")
    draft.update(title="观察", text="Snow falls.\n\nThe river waits.")
    quote = "Snow falls."
    issue = {"code": "proposal", "severity": "minor", "judgment_kind": judgment, "status": "OPEN",
        "evidence_locator": {"start": 0, "end": len(quote), "quote": quote}, "revision_goal": "Shorten the prose"}
    review = {"issues": [issue], "creative_baseline_digest": draft["creative_baseline"]["baseline_digest"]}
    args = dict(project_id="project", draft=draft, review=review, draft_asset_version_id="draft:v1",
        review_asset_version_id="review:v1", context_bundle_version_id="context:v1", provider_evidence={})
    unchanged = apply_revision_result(**args, result={"text": draft["text"], "resolved_issue_codes": []})
    assert unchanged["text"] == draft["text"]
    assert unchanged["issue_resolutions"][0]["to_status"] == "OPEN"
    with pytest.raises(KernelError, match="REVISION_OUTSIDE_DIAGNOSIS_SCOPE"):
        apply_revision_result(**args, result={"text": "Shortened.", "resolved_issue_codes": []})
    with pytest.raises(KernelError, match="REVISION_UNAUTHORIZED_DIAGNOSIS"):
        apply_revision_result(**args, result={"text": draft["text"], "resolved_issue_codes": ["proposal"]})


def test_selected_defect_repairs_only_its_paragraph_and_retains_other_content():
    from novel_forge.modules.review.diagnostics import validate_prose_repair_scope, prose_repair_diagnoses
    text = "The wrong color is red.\n\nA quiet observer waits."
    source = {"text": text}
    review = {"issues": [{"code": "color", "severity": "major", "judgment_kind": "SEMANTIC_CONFLICT",
        "evidence_locator": {"start": 19, "end": 22, "quote": "red"}}]}
    diagnoses = prose_repair_diagnoses(review, work_requirements=True)
    validate_prose_repair_scope(source, diagnoses, text.replace("red", "blue"))
    with pytest.raises(KernelError, match="REVISION_OUTSIDE_DIAGNOSIS_SCOPE"):
        validate_prose_repair_scope(source, diagnoses, text.replace("observer", "hero"))


def test_sampling_keeps_frozen_predecessors_separate_from_new_requests():
    from novel_forge.modules.command_kernel.routing_bootstrap import chapter_sample_source_version_supported
    assert all(chapter_sample_source_version_supported(v) for v in ("3.4.1", "3.5.0", "3.6.0"))
    assert not chapter_sample_source_version_supported("3.3.0")
    assert not chapter_sample_source_version_supported("3.6-author-input.v2")
