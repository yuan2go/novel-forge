from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority import manuscript
from novel_forge.modules.book_authority.working_prose import validate_working_projection
from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_task_view,
    compile_working_history_transport,
    expand_exact_context_references,
)
from novel_forge.modules.chapter_authority.quality_length_requirement import generation_requirement
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft_selection import _hash
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage, PlanningWorldPreparation
from novel_forge.modules.worldbuilding.working_state import project_working_observation_context
from tests.unit.test_author_length_binding import context as length_context
from tests.unit.test_book_method_scope_projection import group_selection
from tests.unit.test_capability_pack_artifact_materialization import _prompt_materialization
from tests.unit.test_longform_working_history import _native_history, _policy
from tests.unit.test_world_working_continuity import world_source


@pytest.fixture(autouse=True)
def forbid_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline final-input tests forbid Provider, database and subprocess I/O")
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("psycopg.connect", forbidden)


def _working(monkeypatch, target=130):
    uow, book, _ = _native_history(monkeypatch, target)
    return manuscript.freeze_working_context(uow, book, target, projection_policy=_policy())


@pytest.mark.parametrize("literal", ["{{target_scope}}", "{{context_bundle}}", "{{some_literal}}", "花括号 {{input_manifest}} 与引号 \\\"保留\\\""])
def test_final_prompt_treats_inserted_author_text_as_opaque(literal):
    from hashlib import sha256
    from tests.unit.test_capability_pack_artifact_materialization import _materialize_chapter_codex_prompt
    from tests.unit.test_production_execution_gateway import contracts
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    *_, request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    materialization = _prompt_materialization({"context_segments": []})
    materialization["pack_artifacts"]["prompt_template"]["content"] = {
        "text": "<data>{{provider_data_envelope}}</data>{{target_scope}}{{context_bundle}}"}
    prompt, evidence = _materialize_chapter_codex_prompt(request=request, stage="draft",
        inputs={"plan": {"chapter": 1, "chapter_objective": literal}}, materialization=materialization)
    envelope = json.loads(prompt.split("<data>", 1)[1].split("</data>", 1)[0])
    assert envelope["input_manifest"]["chapter_plan"]["chapter_objective"] == literal
    assert evidence["fully_rendered_prompt_hash"] == "sha256:" + sha256(prompt.encode()).hexdigest()
    assert evidence["template_render_contract"] == "opaque-template-substitution.v1"


def test_legacy_render_contract_reconstructs_frozen_template_semantics():
    from tests.unit.test_production_execution_gateway import contracts
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    *_, request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    materialization = _prompt_materialization({"context_segments": []})
    materialization["pack_artifacts"]["prompt_template"]["content"] = {"text": "{{provider_data_envelope}}"}
    with pytest.raises(KernelError, match="CHAPTER_CAPABILITY_TEMPLATE_INVALID"):
        _materialize_production_codex_prompt(request=request, stage="draft", inputs={"plan": {"chapter_objective": "{{literal}}"}},
            materialization=materialization, template_render_contract="sequential-template-substitution.v1")


def test_long_history_omission_ledger_stays_out_of_final_provider_input(monkeypatch):
    from novel_forge.modules.narrative_state.working_memory import normalize_observations
    uow, book, _ = _native_history(monkeypatch, 600, tiny=True)
    def memory(_uow, _book, source):
        text = source.content["text"]
        notes = [{"kind": "KNOWLEDGE", "subject": "主角", "state_key": str(index),
            "claim": "人物相信这次经历。", "perspective": "BELIEF", "knowledge_owner": "主角",
            "quote": text, "causes": []} for index in range(64)]
        return normalize_observations(notes, text), {"kind": "WRITER_SELF_OBSERVATION"}
    monkeypatch.setattr("novel_forge.modules.book_authority.manuscript_memory.source_memory", memory)
    working = manuscript.freeze_working_context(uow, book, 600, projection_policy=_policy())
    host = deepcopy(working)
    assert len(working["working_memory"]["omitted_observation_ids"]) > 38000
    from novel_forge.modules.book_authority.working_prose import project_working_history_for_provider
    delivered = project_working_history_for_provider(working)
    assert working == host
    assert len(json.dumps(delivered, ensure_ascii=False)) < 150_000
    assert delivered["sources"] == working["sources"]
    packet = delivered["working_memory"]
    assert "omitted_observation_ids" not in packet
    assert packet["host_packet_hash"] == working["working_memory"]["packet_hash"]
    assert packet["omitted_observation_count"] == len(working["working_memory"]["omitted_observation_ids"])
    assert packet["entries"] == working["working_memory"]["entries"]
    validate_working_projection(delivered, project_id="project", book_id="book", target_chapter=600, accepted_through_chapter=0)
    context = length_context()
    context.update(project_id="project", book_id="book", chapter=600,
        accepted_boundary={"accepted_through_chapter": 0}, working_manuscript=working)
    context["chapter_generation_length"] = generation_requirement(context)
    prompt, evidence, envelope, _ = _materialize("draft", {"plan": {"chapter": 600, "target_word_count": 4500},
        "style": {}, "chapter_memo": {}, "realization_contract": {}}, context, writer=True)
    assert len(prompt.encode()) < 200_000
    assert evidence["rendered_prompt_bytes"] == len(prompt.encode())
    assert envelope["context_bundle"]["working_manuscript"]["working_memory"]["entries"] == packet["entries"]
    for row in working["sources"][-2:]:
        assert row["omitted_ranges"] == []
        assert all(passage["text"] in prompt for passage in row["passages"])
    from novel_forge.modules.production_execution.provider_admission import (
        ProviderRequestEnvelope, build_route_token_accounting_contract, prepare_provider_admission, verify_provider_admission,
    )
    from tests.unit.test_provider_token_admission import COMPLETE_COVERAGE
    envelope = ProviderRequestEnvelope(provider="codex-cli", model="gpt-6.1-sol",
        protocol="codex-cli-application-stdin-v1", input_text=prompt, max_output_tokens=32000,
        timeout_seconds=300, stable_idempotency_key="synthetic-history:600")
    contract = build_route_token_accounting_contract(provider="codex-cli", model="gpt-6.1-sol",
        route_identity="synthetic-history-route", accounting_method="CODEX_CLI_APPLICATION_UTF8_BYTES_UPPER_BOUND_V1",
        accounting_evidence_ref="synthetic-visible-stdin-accounting.v1",
        model_context_limit=258400, execution_token_limit=258400, output_reserve=32000,
        safety_margin=256, framing_overhead=16)
    receipt = prepare_provider_admission(envelope, contract, complete_request_coverage=COMPLETE_COVERAGE)
    assert receipt.status == "ADMITTED" and receipt.precision == "APPLICATION_VISIBLE_UPPER_BOUND"
    verify_provider_admission(envelope, receipt)


def _materialize(stage, inputs, context, *, writer=False):
    if writer:
        context.update(context_profile_version="draft-context-profile-v4", token_budget=131072)
        context["context_manifest"] = {"narrative_position": {"book_id": context["book_id"], "chapter": context["chapter"]},
            "authority_state_boundary": {"accepted_through_chapter": 0}}
    materialization = _prompt_materialization(context)
    template = materialization["pack_artifacts"]["prompt_template"]
    template.update(ref="prompt-template:chapter-generation-pack" if writer else "prompt-template:story-planning-pack",
                    version="v13" if writer else "v2", content={"text": "<data>{{provider_data_envelope}}</data>"})
    task = build_provider_task_view(stage, inputs, compact_contract=True,
                                   project_methods=writer, instruction_cleanup=writer, work_requirements=writer)
    view = build_provider_context_view(stage, context, task,
        writer_projection_version="accepted-writer-history.v2" if writer else "")
    context["context_manifest"] = {**context.get("context_manifest", {}),
        "provider_context_view": {**context.get("context_manifest", {}).get("provider_context_view", {}),
                                  "content_hash": canonical_hash(view)}}
    prompt, evidence = _materialize_production_codex_prompt(stage=stage, inputs=inputs,
        target_scope={"scope_kind": "book", "scope_id": context["book_id"], "project_id": context["project_id"], "book_id": context["book_id"]},
        materialization=materialization)
    encoded = json.loads(prompt.split("<data>", 1)[1].split("</data>", 1)[0])
    return prompt, evidence, expand_exact_context_references(encoded), materialization


def _world(monkeypatch, *, target=130, method_scope=True, projection="world-role-delivery.v4"):
    source = world_source()
    working = _working(monkeypatch, target)
    source.update(target_chapter=target, working_manuscript=working, provider_projection_version=projection)
    source["request"] = {"book_run_id": working["book_run_id"], "accepted_through_chapter": 0}
    source["reality"].update(project_id="project", book_id="book")
    source["reality"] = project_working_observation_context(
        reality=source["reality"], working=working, characters=[])
    source["policy"].update(version="world-production-policy.v4", context_token_budget=131072)
    source["private_raw_source"] = "PRIVATE_REFERENCE_EXPRESSION_MUST_NOT_REACH_PROVIDER"
    source["planning_window"] = [{"role": "arc_plans", "asset_version_id": "arc:own:v1", "content_hash": "sha256:arc",
        "content": {"hard_constraints": ["Keep the author's actual promise"], "knowledge_translations": [{
            "knowledge_card_asset_version_id": "method:v1", "content_hash": "sha256:method", "decision": "ADAPT",
            "rationale": "PRIOR_APPLICATION_ADMIN_AUDIT_ONLY", "use_sites": []}]}}]
    selection = group_selection()
    selection["need"]["hard_constraints"] = ["UNVERIFIED_RETRIEVAL_QUERY_STATUS_ONLY"]
    selection["need"]["target_stage"] = "chapter_plan.generate"
    selection["selected"][0]["applicability_assessment"]["hard_constraints"] = deepcopy(selection["need"]["hard_constraints"])
    selection["selected"][0]["selected_content"]["prerequisites"] = ["Person has an available choice"]
    selection["need"]["need_digest"] = _hash({key: value for key, value in selection["need"].items() if key != "need_digest"})
    selection["selection_digest"] = _hash({key: value for key, value in selection.items() if key != "selection_digest"})
    reference = {"asset_version_id": "world:source:v1", "content_hash": canonical_hash({"contract": source})}
    stage = PlanningWorldPreparation.generation_stage(source, reference, selection,
        method_scope_projection="world-method-scope-projection.v1" if method_scope else None)
    task = build_provider_task_view(stage.name, {"world_preparation": stage.task})["world_preparation"]
    context = {"project_id": "project", "book_id": "book", "logical_key": f"chapter:{target}",
        "world_preparation": task, "narrative_intelligence": selection, "token_budget": 131072,
        **({"world_method_scope_projection_version": "world-method-scope-projection.v1"} if method_scope else {})}
    return source, stage, task, context, selection


@pytest.mark.parametrize("target", [130, 600])
def test_actual_writer_prompt_keeps_author_han_scale_and_one_complete_recent_prose_copy(monkeypatch, target):
    working = _working(monkeypatch, target)
    context = length_context()
    context.update(project_id="project", book_id="book", chapter=target,
        accepted_boundary={"accepted_through_chapter": 0}, working_manuscript=working)
    context["chapter_generation_length"] = generation_requirement(context)
    inputs = {"plan": {"chapter": target, "target_word_count": 4500}, "style": {},
              "chapter_memo": {}, "realization_contract": {}}
    frozen = deepcopy(working)
    prompt, evidence, envelope, _ = _materialize("draft", inputs, context, writer=True)
    delivered = envelope["context_bundle"]["working_manuscript"]
    assert working == frozen
    assert envelope["context_bundle"]["chapter_generation_length"]["minimum"] == 4000
    assert envelope["context_bundle"]["chapter_generation_length"]["maximum"] == 5000
    assert envelope["context_bundle"]["chapter_generation_length"]["unit"] == "HAN_CHARACTERS_V1"
    assert delivered["sources"] == working["sources"]
    assert delivered["source_history"]["source_count"] == target - 1
    assert "sources" not in delivered["source_history"]
    for row in working["sources"][-2:]:
        assert row["omitted_ranges"] == []
        for passage in row["passages"]:
            assert prompt.count(passage["text"]) == 1
    assert evidence["provider_view"]["working_history_transport"]["projections"]
    assert evidence["provider_view"]["exact_context_references"]["decoded_equal"]


def test_actual_world_v5_prompt_composes_complete_prose_method_conditions_and_prior_audit_reference(monkeypatch):
    source, stage, task, context, selection = _world(monkeypatch)
    before = deepcopy(source)
    prompt, evidence, envelope, _ = _materialize(stage.name, {"world_preparation": task}, context)
    delivered = envelope["input_manifest"]["world_preparation"]
    assert source == before
    assert delivered["contract_version"] == "world-provider-task.v5"
    assert delivered["world_method_scope_projection_version"] == "world-method-scope-projection.v1"
    card = delivered["narrative_intelligence"]["selected"][0]
    assert card["selected_content"] == selection["selected"][0]["selected_content"]
    assert card["applicability_assessment"]["unmet_prerequisites"] == ["Current information"]
    assert "UNVERIFIED_RETRIEVAL_QUERY_STATUS_ONLY" not in prompt
    assert "PRIVATE_REFERENCE_EXPRESSION_MUST_NOT_REACH_PROVIDER" not in prompt
    assert "PRIOR_APPLICATION_ADMIN_AUDIT_ONLY" not in prompt
    arc = delivered["planning_window"][0]
    assert arc["content"]["hard_constraints"] == ["Keep the author's actual promise"]
    assert arc["prior_method_audit_receipt"]["plan_asset_version_id"] == "arc:own:v1"
    assert arc["prior_method_audit_receipt"]["json_pointer"] == "/contract/planning_window/0/content/knowledge_translations"
    for row in source["working_manuscript"]["sources"][-2:]:
        assert row["omitted_ranges"] == []
        for passage in row["passages"]:
            assert prompt.count(passage["text"]) == 1
    validate_working_projection(delivered["working_manuscript"], project_id="project", book_id="book")
    assert evidence["provider_view"]["working_history_transport"]["projections"]


def test_native_world_context_freezes_composed_method_view_and_rejects_prior_audit_drift(monkeypatch):
    source, stage, task, context, _ = _world(monkeypatch)
    projected = PlanningProviderStage(stage.name, task, stage.output_schema)
    document = SimpleNamespace(asset_version_id=task["source_ref"]["asset_version_id"],
        content_hash=task["source_ref"]["content_hash"], asset_type="world_preparation_source", content={"contract": source})
    command = SimpleNamespace(project_id="project", book_id="book", logical_key="chapter:130",
        generator_operation_name="chapter_plan.generate", planning_scope=SimpleNamespace(value="CHAPTER"))
    base = SimpleNamespace(content={key: value for key, value in context.items() if key != "world_preparation"})
    native = PostgresPlanningExecutionPreparer._world_context_content(
        command=command, base=base, stage=projected, source=document)
    prompt, evidence, envelope, _ = _materialize(stage.name, {"world_preparation": task}, native)
    assert "Person has an available choice" in prompt
    assert envelope["input_manifest"]["world_preparation"]["working_manuscript"]["target_chapter"] == 130
    assert evidence["provider_view"]["working_history_transport"]["projections"]
    changed = deepcopy(source)
    changed["planning_window"][0]["content"]["knowledge_translations"][0]["rationale"] = "changed audit"
    document.content = {"contract": changed}
    with pytest.raises(KernelError, match="WORLD_METHOD_SOURCE_DRIFT"):
        PostgresPlanningExecutionPreparer._world_context_content(command=command, base=base, stage=projected, source=document)


def test_frozen_v3_world_without_new_method_scope_retains_legacy_delivery(monkeypatch):
    source = world_source()
    source["provider_projection_version"] = "world-role-delivery.v3"
    source["reality"] = project_working_observation_context(
        reality=source["reality"], working=source["working_manuscript"], characters=[])
    stage = PlanningWorldPreparation.generation_stage(source,
        {"asset_version_id": "legacy:source", "content_hash": canonical_hash({"contract": source})}, {})
    task = build_provider_task_view(stage.name, {"world_preparation": stage.task})["world_preparation"]
    context = {"project_id": "p", "book_id": "b", "world_preparation": task, "narrative_intelligence": {}}
    _, evidence, envelope, _ = _materialize(stage.name, {"world_preparation": task}, context)
    delivered = envelope["input_manifest"]["world_preparation"]
    assert delivered["contract_version"] == "world-provider-task.v4"
    assert delivered["working_manuscript"] == source["working_manuscript"]
    assert "world_method_scope_projection_version" not in delivered
    assert "working_history_transport" not in evidence["provider_view"]


def test_final_world_history_transport_retains_a_resolvable_original_delivery_receipt(monkeypatch):
    _, stage, task, context, _ = _world(monkeypatch)
    _, evidence, envelope, _ = _materialize(stage.name, {"world_preparation": task}, context)
    delivered = envelope["input_manifest"]["world_preparation"]
    projections = evidence["provider_view"]["working_history_transport"]["projections"]
    projection = next(row for row in projections if row["json_pointer"] == "/input_manifest/world_preparation/working_manuscript")
    assert projection["source_snapshot_hash"] == task["working_delivery_receipt"]["delivery_snapshot_hash"]
    assert projection["delivery_snapshot_hash"] == delivered["working_manuscript"]["snapshot_hash"]
    assert delivered["working_delivery_receipt"] == task["working_delivery_receipt"]
    history_receipt = delivered["working_history_delivery_receipt"]
    assert history_receipt["source_snapshot_hash"] == delivered["working_delivery_receipt"]["delivery_snapshot_hash"]
    assert history_receipt["delivery_snapshot_hash"] == delivered["working_manuscript"]["snapshot_hash"]
    assert build_provider_task_view(stage.name, {"world_preparation": delivered})["world_preparation"] == delivered
    repeated, receipt = compile_working_history_transport(envelope)
    assert repeated == envelope
    assert receipt["projections"] == []


@pytest.mark.parametrize("field,value", [
    ("source_snapshot_hash", "sha256:forged"),
    ("delivery_snapshot_hash", "sha256:forged"),
    ("source_history_hash", "sha256:forged"),
    ("prose_unchanged", False),
    ("contract_version", "forged"),
])
def test_final_world_rejects_forged_history_to_original_receipt_mapping(monkeypatch, field, value):
    _, stage, task, context, _ = _world(monkeypatch)
    _, _, envelope, _ = _materialize(stage.name, {"world_preparation": task}, context)
    delivered = envelope["input_manifest"]["world_preparation"]
    delivered["working_history_delivery_receipt"][field] = value
    with pytest.raises(KernelError, match="WORLD_WORKING_DELIVERY_DRIFT"):
        build_provider_task_view(stage.name, {"world_preparation": delivered})


def test_frozen_context_hash_rejects_post_freeze_author_scale_drift(monkeypatch):
    working = _working(monkeypatch)
    context = length_context()
    context.update(project_id="project", book_id="book", chapter=130,
        accepted_boundary={"accepted_through_chapter": 0}, working_manuscript=working)
    context["chapter_generation_length"] = generation_requirement(context)
    inputs = {"plan": {}, "style": {}, "chapter_memo": {}, "realization_contract": {}}
    _, _, _, materialization = _materialize("draft", inputs, context, writer=True)
    context["chapter_generation_length"]["maximum"] = 6000
    with pytest.raises(KernelError, match="CHAPTER_GENERATION_LENGTH_BINDING_INVALID"):
        _materialize_production_codex_prompt(stage="draft", inputs=inputs,
            target_scope={"scope_kind": "book", "scope_id": "book", "project_id": "project", "book_id": "book"},
            materialization=materialization)
