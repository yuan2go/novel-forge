from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view, build_provider_task_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.execution import PostgresPlanningExecutionPreparer


def planning_bundle(content: dict, *, budget: int = 16000) -> dict:
    return {
        "schema_version": "novelos.planning_context_bundle.v1",
        "book_id": "book:one",
        "logical_key": "chapter:3",
        "planning_scope": "CHAPTER",
        "token_budget": budget,
        "input_versions": [{
            "role": "chapter_group_plan", "asset_type": "planning_generation_candidate",
            "asset_version_id": "plan:v1", "content_hash": "sha256:" + "a" * 64,
            "content": content,
        }],
    }


def test_thirteenth_constraint_and_long_required_field_reach_provider_unchanged():
    constraints = [f"constraint-{number}" for number in range(13)]
    constraints[-1] = "禁止使用尚未公开的救援路线。" * 250 + "END-REQUIRED"
    bundle = planning_bundle({"hard_constraints": constraints})
    original = deepcopy(bundle)
    view = build_provider_context_view("chapter_plan.generate", bundle, {})
    assert view["segments"][0]["content"]["hard_constraints"] == constraints
    assert bundle == original


def test_existing_planning_invariants_and_obligation_fields_remain_required():
    invariants = [f"invariant-{i}" for i in range(13)]
    content = {"invariants": invariants, "prohibited_outcomes": ["unearned rescue"], "required_obligation_ids": ["oath:1"]}
    view = build_provider_context_view("chapter_plan.generate", planning_bundle(content), {})
    for key, expected in content.items():
        assert view["segments"][0]["content"][key] == expected


def test_required_field_blocks_when_budget_cannot_hold_it():
    with pytest.raises(KernelError, match="budget|boundary"):
        build_provider_context_view(
            "chapter_plan.generate",
            planning_bundle({"hard_constraints": ["required" * 1000]}, budget=400), {},
        )


def test_outside_scope_segments_do_not_fall_back_to_future_plans():
    bundle = planning_bundle({"narrative_segments": [
        {"chapter_range": [4, 6], "objective": "FUTURE-SECRET"},
    ]})
    bundle["input_versions"][0]["role"] = "volume_plan"
    view = build_provider_context_view("chapter_plan.generate", bundle, {})
    assert view["segments"][0]["content"]["narrative_segments"] == []


def test_optional_pruning_records_exact_source_path_and_loss():
    suggestions = ["optional idea " * 4000]
    bundle = planning_bundle({"hard_constraints": ["water remains limited"], "soft_suggestions": suggestions}, budget=1000)
    view = build_provider_context_view("chapter_plan.generate", bundle, {})
    assert view["segments"][0]["content"]["hard_constraints"] == ["water remains limited"]
    losses = view["selection_explanation"]["loss_records"]
    loss = next(item for item in losses if item["reason"] == "OPTIONAL_CONTEXT_BUDGET")
    source = view["selection_explanation"]["loss_sources"][loss["source_index"]]
    assert source["asset_version_id"] == "plan:v1"
    assert source["source_content_hash"] == "sha256:" + "a" * 64
    assert loss["path"] == "/soft_suggestions"
    assert loss["removed_value_hash"].startswith("sha256:")
    assert loss["removed_item_count"] == 1


def test_loss_lineage_shares_source_identity_without_dropping_field_receipts():
    bundle = planning_bundle({"hard_constraints": ["Water remains limited"], **{f"unneeded_{index}": index for index in range(24)}}, budget=3000)
    identity = "planning-version:" + "a" * 400
    bundle["input_versions"][0]["asset_version_id"] = identity
    view = build_provider_context_view("chapter_plan.generate", bundle, {})
    explanation = view["selection_explanation"]
    assert view["segments"][0]["content"]["hard_constraints"] == ["Water remains limited"]
    assert len(explanation["loss_sources"]) == 1
    assert explanation["loss_sources"][0]["asset_version_id"] == identity
    assert {item["source_index"] for item in explanation["loss_records"]} == {0}
    assert {item["path"] for item in explanation["loss_records"]} == {f"/unneeded_{index}" for index in range(24)}
    assert len({item["removed_value_hash"] for item in explanation["loss_records"]}) == 24


def test_protected_chapter_summary_is_not_resliced_at_provider_rendering():
    summary = "required rule " * 150 + "END-REQUIRED"
    bundle = {
        "context_segments": [{
            "asset_version_id": "rule:v1", "asset_type": "world_bible",
            "context_class": "PROTECTED", "safe_summary": summary,
            "structured_facts": [], "allowed_use": "generation",
        }],
    }
    view = build_provider_context_view("review", bundle, {})
    assert view["segments"][0]["safe_summary"] == summary


def test_world_request_references_frozen_loss_audit_without_repeating_it_as_creative_input():
    constraints = [f"required:{index}" for index in range(13)]
    task = {"contract_version": "world-provider-task.v1", "role": "WORLD_REASONER", "fact_mutation_allowed": False,
            "source_ref": {"asset_version_id": "source:world:v1", "content_hash": "sha256:" + "b" * 64},
            "planning_window": [{"content": {"hard_constraints": constraints},
                                 "loss_sources": [{"asset_version_id": "plan:v1"}],
                                 "loss_records": [{"path": f"/field/{index}", "removed_value_hash": "sha256:" + "a" * 64, "source_index": 0} for index in range(200)]}]}
    frozen = deepcopy(task)
    view = build_provider_task_view("world_candidates.generate", {"world_preparation": task})
    segment = view["world_preparation"]["planning_window"][0]
    assert segment["content"]["hard_constraints"] == constraints
    assert "loss_records" not in segment
    assert segment["selection_loss_receipt"]["source_ref"] == task["source_ref"]
    assert segment["selection_loss_receipt"]["json_pointer"] == "/contract/planning_window/0"
    assert segment["selection_loss_receipt"]["loss_record_count"] == 200
    assert task == frozen
    assert build_provider_task_view("world_candidates.generate", view) == view


def frozen_planning_bundle() -> dict:
    bundle = planning_bundle({"hard_constraints": [f"condition-{i}" for i in range(13)]})
    command = SimpleNamespace(
        project_id="project:one", book_id="book:one", generator_operation_name="chapter_plan.generate",
        planning_scope=SimpleNamespace(value="CHAPTER"), logical_key="chapter:3",
    )
    bundle["context_manifest"] = PostgresPlanningExecutionPreparer._planning_context_manifest(
        command=command, selected_inputs=bundle["input_versions"], content=bundle,
    )
    bundle["estimated_tokens"] = bundle["context_manifest"]["token_accounting"]["accepted_tokens"]
    return bundle


def test_recovery_uses_frozen_projection_and_rejects_semantic_input_drift(monkeypatch):
    bundle = frozen_planning_bundle()
    expected = deepcopy(bundle["context_manifest"]["provider_context_view"]["compiled_view"])

    def recompile_forbidden(*args, **kwargs):
        pytest.fail("A frozen request must not rerun semantic projection on resume")

    monkeypatch.setattr("novel_forge.modules.chapter_authority.provider_views._project_planning_content", recompile_forbidden)
    assert build_provider_context_view("chapter_plan.generate", bundle, {}) == expected
    bundle["input_versions"][0]["content"]["hard_constraints"][-1] = "changed"
    with pytest.raises(KernelError, match="IDENTITY_MISMATCH"):
        build_provider_context_view("chapter_plan.generate", bundle, {})


def test_repair_keeps_original_constraints_and_thirteenth_diagnosis():
    bundle = planning_bundle({"hard_constraints": [f"condition-{i}" for i in range(13)]})
    directives = [{"repair_directive": f"Repair issue {i}"} for i in range(13)]
    bundle["repair_context"] = {
        "source_candidate": {"asset_version_id": "candidate:v1", "content_hash": "sha256:" + "b" * 64,
                             "content": {"objective": "Repair without losing the water condition"}},
        "failed_narrative_qualifications": directives,
    }
    view = build_provider_context_view("chapter_plan.generate", bundle, {})
    assert view["segments"][0]["content"]["hard_constraints"][-1] == "condition-12"
    assert view["repair_context"]["failed_narrative_qualifications"] == directives


def test_repair_keeps_distinct_required_roles_and_accepted_cognition():
    bundle = planning_bundle({"hard_constraints": [], "forbidden_events": []})
    bundle["input_versions"] = [
        {"role": role, "asset_version_id": f"{role}:v1", "asset_type": "planning_generation_candidate",
         "content_hash": "sha256:" + "a" * 64, "content": {"hard_constraints": [], "forbidden_events": []}}
        for role in ("book_plan", "volume_plan", "arc_plans")
    ]
    cognition = {"facts": [{"fact_id": "signed-message", "status": "KNOWN", "character_id": "mara"}]}
    bundle["input_versions"].append({"role": "story_state", "asset_version_id": "state:v1", "asset_type": "story_state",
                                      "content_hash": "sha256:" + "b" * 64, "content": cognition})
    bundle["repair_context"] = {"source_candidate": {"asset_version_id": "candidate:v1", "content_hash": "sha256:" + "c" * 64,
                                                      "content": {"objective": "Only use accepted character knowledge"}},
                                "validation_failure": {"code": "SCENE_ACCEPTED_KNOWLEDGE_MISMATCH"}}
    command = SimpleNamespace(project_id="project:one", book_id="book:one", generator_operation_name="chapter_plan.generate",
                              planning_scope=SimpleNamespace(value="CHAPTER"), logical_key="chapter:3")
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(command=command, selected_inputs=bundle["input_versions"], content=bundle)
    projected = {item["role"]: item["content"] for item in manifest["provider_context_view"]["compiled_view"]["segments"]}
    assert set(projected) == {"book_plan", "volume_plan", "arc_plans", "story_state"}
    assert projected["story_state"] == cognition
    assert not manifest["deduplication_decisions"]


def test_planning_budget_counts_creative_payload_and_freezes_complete_loss_audit():
    constraints = ["water condition " * 450]
    bundle = planning_bundle({"hard_constraints": constraints, **{f"outside_role_{index}": f"excluded-{index}" for index in range(80)}}, budget=6000)
    command = SimpleNamespace(project_id="project:one", book_id="book:one", generator_operation_name="chapter_plan.generate",
                              planning_scope=SimpleNamespace(value="CHAPTER"), logical_key="chapter:3")
    manifest = PostgresPlanningExecutionPreparer._planning_context_manifest(command=command, selected_inputs=bundle["input_versions"], content=bundle)
    compiled = manifest["provider_context_view"]["compiled_view"]
    assert compiled["segments"][0]["content"]["hard_constraints"] == constraints
    assert len(manifest["projection_audit"]["loss_records"]) == 80
    assert "loss_records" not in compiled["selection_explanation"]
    assert compiled["selection_explanation"]["loss_receipt"]["json_pointer"] == "/context_manifest/projection_audit"
    bundle["context_manifest"] = manifest
    assert build_provider_context_view("chapter_plan.generate", bundle, {}) == compiled
    bundle["context_manifest"]["projection_audit"]["loss_records"].pop()
    with pytest.raises(KernelError, match="IDENTITY_MISMATCH"):
        build_provider_context_view("chapter_plan.generate", bundle, {})


def test_frozen_semantics_reach_final_request_and_final_budget_admission():
    from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
    from novel_forge.modules.production_execution.provider_admission import (
        ProviderRequestEnvelope, build_route_token_accounting_contract, prepare_provider_admission,
    )

    bundle = frozen_planning_bundle()
    artifacts = {
        key: {"ref": key, "version": "v1", "content_hash": "sha256:" + "b" * 64, "content": {"text": value}}
        for key, value in {
            "system_instruction": "Follow the frozen scope.",
            "skill": "Preserve all mandatory conditions.",
            "prompt_template": "{{stage}} {{input_manifest}} {{context_bundle}} {{output_schema_ref}}",
        }.items()
    }
    prompt, evidence = _materialize_production_codex_prompt(
        request=SimpleNamespace(target_scope=SimpleNamespace(to_dict=lambda: {"book_id": "book:one"})),
        stage="chapter_plan.generate",
        inputs={
            "planning_command": {"logical_key": "chapter:3"},
            "frozen_inputs": [{key: value for key, value in bundle["input_versions"][0].items() if key != "content"}],
            "authoritative_narrative_load": {"narrative_load_policy": {}, "narrative_load_projection": {}},
            "arc_working_set": {},
            "narrative_intelligence": {"schema_version": "mkaos-narrative-intelligence-selection.v1", "selected": [],
                                       "authority_boundary": {"semantic_role": "POSSIBILITY_ONLY", "may_mutate_story_authority": False}},
        },
        materialization={
            "pack_artifacts": artifacts,
            "context_selection": [{"asset_version_id": "context:v1", "content": bundle}],
            "knowledge_selection": [{"ref": "governed-skill:v1", "version": "v1", "content": {"principles": ["Preserve causality"]}}],
            "tool_permissions": {"allowed": ["model.provider.invoke"]},
            "output_schema": {"ref": "schema:chapter-plan", "content": {"type": "object"}},
        },
    )
    frozen = bundle["context_manifest"]["provider_context_view"]
    assert json.dumps(frozen["compiled_view"], ensure_ascii=False, sort_keys=True, separators=(",", ":")) in prompt
    assert "condition-12" in prompt
    assert evidence["provider_view"]["component_hashes"]["provider_context_view"] == frozen["content_hash"]
    envelope = ProviderRequestEnvelope(provider="openai", model="fixture-model", protocol="openai-responses-text-envelope-v1",
                                      input_text=prompt, max_output_tokens=64, timeout_seconds=30, stable_idempotency_key="fixture:one")
    contract = build_route_token_accounting_contract(
        provider="openai", model="fixture-model", route_identity="fixture:one",
        accounting_method="OPENAI_UTF8_BYTES_UPPER_BOUND_V1", accounting_evidence_ref="fixture:meter",
        model_context_limit=100000, execution_token_limit=100000, output_reserve=64,
        safety_margin=32, framing_overhead=16,
    )
    coverage = ("system_runtime_instructions", "prompt_template", "skill_instructions", "tool_policy_and_schemas",
                "structured_output_schema", "context_bundle", "request_envelope_and_framing", "output_reserve", "safety_margin")
    receipt = prepare_provider_admission(envelope, contract, complete_request_coverage=coverage)
    assert receipt.status == "ADMITTED"
    assert receipt.component_usage["provider_input"] == len(prompt.encode("utf-8"))
    historical_limit = prepare_provider_admission(envelope, replace(contract, execution_token_limit=1000), complete_request_coverage=coverage)
    assert historical_limit.status == "ADMITTED"
    assert historical_limit.accounting_contract["execution_token_limit"] == 1000
    assert historical_limit.total_reserved > 1000
    assert historical_limit.applicable_limit == contract.model_context_limit
    blocked = prepare_provider_admission(envelope, replace(contract, model_context_limit=1000), complete_request_coverage=coverage)
    assert blocked.status == "REJECTED"
    assert blocked.reason == "PROVIDER_CONTEXT_LIMIT_EXCEEDED"
    assert blocked.total_reserved == receipt.total_reserved
    assert blocked.applicable_limit == 1000
