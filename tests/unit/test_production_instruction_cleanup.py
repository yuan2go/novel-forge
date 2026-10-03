from copy import deepcopy
from dataclasses import replace
import json

import pytest

from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
from novel_forge.modules.chapter_authority.handlers import merge_task_retrieval_projections
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view, build_provider_task_view
from novel_forge.modules.capability_packs.artifacts import ArtifactKind, default_chapter_artifact_resolver
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.domain import build_authority_context_bundle
from novel_forge.modules.context_builder.production_retrieval import build_retrieval_query_plan, build_retrieval_result
from novel_forge.modules.context_builder.retrieval_rebuild import writer_index_document
from novel_forge.modules.context_builder.story_projection import STORY_PROJECTION_VERSION, clean_context_candidate, story_history, visible_business_data
from novel_forge.modules.context_builder.task_compression import _units, compile_task_context
from novel_forge.modules.production_execution import ExecutionRuntimeClass
from tests.unit.test_capability_pack_artifact_materialization import ROOT, _prompt_materialization
from tests.unit.test_context_retrieval_v2 import _document, _intent, _memo
from tests.unit.test_production_execution_gateway import contracts
from tests.unit.test_task_scoped_context import BOUNDARY, TASK, candidate


NOISE = ("OLD-REVIEW", "REJECTED-QUOTE", "PROVIDER-ERROR", "PRIVATE-FACT")


def mixed_source(noise="a"):
    return {"chapter": 7, "provider_evidence": {"error": "PROVIDER-ERROR" + noise * 7000},
            "candidate_comparison": {"rejected_revision_checks": [{"quote": "REJECTED-QUOTE"}]},
            "selected_review": {"instruction": "OLD-REVIEW", "character_id": noise},
            "scene_artifacts": [{"slot_id": "s1", "text": "You owe me one joke.", "used_fact_ids": ["fact:public"]}],
            "structured_facts": [{"fact_id": "fact:public", "state": {"event": "Door remains locked.",
                "encoded": json.dumps({"provider_evidence": {"error": "PROVIDER-ERROR"}, "public": "KEEP-FACT"})}},
                {"fact_id": "secret", "provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "PRIVATE-FACT"}]}


def pipeline(profile, source):
    doc = {**_document(), "content_text": json.dumps(source), "source_asset_version_id": "source:1", "metadata": {"structured_facts": source["structured_facts"]}}
    query = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    selected = build_retrieval_result(project_id="project", book_id="book", intent_asset_version_id="i", memo_asset_version_id="m",
        query_plan=query, documents=[doc], discovery_rejections=[], semantic_status={})["selected_documents"][0]
    merged = merge_task_retrieval_projections({"content_hash": doc["source_content_hash"], "safe_summary": json.dumps(source),
        "physical_asset_type": "best_draft_candidate", "structured_facts": source["structured_facts"],
        "provenance": {"authority_asset_version_id": "source:1"}}, [selected])
    history = replace(candidate(kind="narrative_retrieval_document", text=merged["safe_summary"]),
        physical_asset_type="best_draft_candidate", narrative_function="recent_accepted_prose",
        structured_facts=tuple(merged["structured_facts"]), provenance=merged["provenance"])
    history = clean_context_candidate(history, stage="draft")
    plan = replace(candidate(kind="chapter_plan", text="Frozen plan.", required=True), asset_version_id="plan:21",
        source_identity="plan:21", content_digest="sha256:" + "c" * 64, source_revision="sha256:" + "c" * 64, estimated_tokens=30)
    bundle = build_authority_context_bundle(project_id="project", book_id="book", stage="draft", created_by_operation_id="operation",
        context_profile_version=profile, token_budget=4000, candidates=[plan, history], authority_state_boundary=BOUNDARY,
        narrative_position={"chapter": 21, "book_id": "book"})
    materialization = _prompt_materialization(bundle)
    from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema
    from novel_forge.modules.capability_packs.artifacts import artifact_content_hash
    schema = chapter_provider_output_schema("draft")
    materialization["output_schema"] = {"ref": "schema:chapter-provider-output:draft:v3", "content_hash": artifact_content_hash(schema), "content": schema}
    resolver = default_chapter_artifact_resolver(ROOT)
    materialization["pack_artifacts"] = {
        "system_instruction": resolver.resolve(ArtifactKind.PROMPT_SYSTEM_INSTRUCTION, "prompt-system:chapter-generation-pack", "v3").to_dict(),
        "prompt_template": resolver.resolve(ArtifactKind.PROMPT_TEMPLATE, "prompt-template:chapter-generation-pack", "v7").to_dict(),
        "skill": resolver.resolve(ArtifactKind.SKILL, "prose-generation", "prose-generation-v4").to_dict(),
    }
    *_, request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    prompt, evidence = _materialize_production_codex_prompt(request=request, stage="draft", inputs={"plan": {}, "style": {}, "chapter_memo": {}, "realization_contract": {}}, materialization=materialization)
    return history, bundle, prompt, evidence


@pytest.mark.parametrize("profile", ["draft-context-profile-v2", "draft-context-profile-v3", "draft-context-profile-v4"])
def test_actual_retrieval_context_and_prompt_are_invariant_to_audit_metadata(profile):
    a = pipeline(profile, mixed_source("a"))
    b = pipeline(profile, mixed_source("z"))
    assert a[0].safe_summary == b[0].safe_summary
    assert a[0].estimated_tokens == b[0].estimated_tokens
    assert a[1]["context_segments"] == b[1]["context_segments"]
    assert a[2] == b[2]
    for marker in NOISE:
        assert marker not in a[2]
    assert "You owe me one joke." in a[2] and "KEEP-FACT" in a[2]
    assert a[3]["provider_view"]["provider_admission_uses_component_estimates"] is False


@pytest.mark.parametrize("kind", ["story_state_snapshot", "narrative_retrieval_document", "world_bible"])
def test_nested_and_stringified_visibility_is_typed_and_stage_specific(kind):
    facts = [{"fact_id": "public", "state": {"label": "KEEP", "encoded": json.dumps({"nested": {"provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "PRIVATE-FACT"}})}},
             {"provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "PRIVATE-FACT"}]
    clean = visible_business_data(facts, stage="draft", history=True)
    assert "KEEP" in json.dumps(clean) and "PRIVATE-FACT" not in json.dumps(clean)
    for stage in ("review", "quality_structural", "reference_analysis"):
        assert visible_business_data(facts, stage=stage, history=True) == facts
    source = replace(candidate(kind, text=json.dumps(facts)), structured_facts=tuple(facts))
    assert "PRIVATE-FACT" not in clean_context_candidate(source, stage="draft").safe_summary
    assert clean_context_candidate(source, stage="review") == source
    context = {"task_narrative_projection": {"fact_refs": ["public"]}, "context_segments": [{"asset_type": kind, "asset_version_id": "visible:1", "safe_summary": json.dumps(facts), "structured_facts": facts}]}
    writer = build_provider_context_view("draft", context, {}, writer_projection_version=STORY_PROJECTION_VERSION)
    assert "PRIVATE-FACT" not in json.dumps(writer)
    assert "KEEP" in json.dumps(writer)


def test_current_revision_draft_and_bound_diagnostics_are_preserved():
    source = replace(candidate("review_issue", text="CURRENT-DIAGNOSTIC"), structured_facts=({"provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "authorized diagnostic"},))
    assert clean_context_candidate(source, stage="revision") == source
    task = build_provider_task_view("revision", {"draft": {"text": "CURRENT-DRAFT"}, "required_actions": [{"issue_code": "VOICE", "instruction": "CURRENT-DIAGNOSTIC"}]})
    assert "CURRENT-DRAFT" in json.dumps(task) and "CURRENT-DIAGNOSTIC" in json.dumps(task)
    quality = build_provider_task_view("quality_structural", {"quality_context": {"bound_evidence": source.structured_facts}})
    assert "authorized diagnostic" in json.dumps(quality)
    context = {"context_segments": [{"asset_type": "review_issue", "asset_version_id": "bound:review", "structured_facts": list(source.structured_facts), "safe_summary": source.safe_summary}]}
    assert "authorized diagnostic" in json.dumps(build_provider_context_view("revision", context, {}, writer_projection_version=STORY_PROJECTION_VERSION))


def test_revision_diagnosis_is_defined_once_with_exact_locator_and_preservation():
    diagnosis = {"code": "VOICE", "severity": "blocking", "judgment_kind": "HARD_REQUIREMENT", "revision_goal": "UNIQUE-DIAGNOSIS-GOAL",
                 "evidence_locator": {"quote": "old quote", "slot_id": "s1"}, "preserve": ["voice"], "acceptance_criteria": ["restore motive"]}
    inputs = {"draft": {"text": "old quote", "realization_contract": {"contract_version": "scene-realization-composition.v2"}, "scene_artifacts": [{"slot_id": "s1", "text": "old quote"}]}, "review": {"issues": [diagnosis]}}
    legacy = build_provider_task_view("revision", inputs, compact_contract=True)
    cleaned = build_provider_task_view("revision", inputs, compact_contract=True, instruction_cleanup=True)
    assert json.dumps(legacy).count("UNIQUE-DIAGNOSIS-GOAL") == 2
    assert json.dumps(cleaned).count("UNIQUE-DIAGNOSIS-GOAL") == 1
    assert cleaned["review_issues"] == [diagnosis]
    assert cleaned["targeted_editing"]["diagnosis_codes"] == ["VOICE"]
    assert "tasks" not in cleaned["targeted_editing"]


def test_body_expression_is_never_filtered_by_keywords_or_json_syntax():
    body = '{"selected_review":"the character reads this literal document"}'
    source = {"text": body, "selected_review": {"instruction": "OLD-REVIEW"}}
    assert json.loads(story_history(json.dumps(source), physical_type="best_draft_candidate"))["text"] == body


def test_fast_and_scripted_overflow_paths_use_clean_original_units():
    source = replace(candidate(text=json.dumps({"summary": "You owe me one joke.\n\n" + "Banquet. " * 500,
        "candidate_comparison": {"instruction": "OLD-REVIEW"}, "unknown_metadata": "unneeded"})),
        provenance={"writer_projection_version": STORY_PROJECTION_VERSION})
    task = {**TASK, "writer_projection_version": STORY_PROJECTION_VERSION}
    fast, receipt = compile_task_context([source], task=task, token_budget=10000, required_asset_types=(), model_call=lambda *a: pytest.fail("fast path called Provider"))
    assert receipt["fast_path"] and "OLD-REVIEW" not in fast[0].safe_summary
    unknown = next(unit for unit in _units(fast[0], task) if unit["unit_id"] == "json:unknown_metadata")
    assert unknown["required"] is False
    calls = []
    def scripted(stage, payload):
        calls.append(stage)
        assert "OLD-REVIEW" not in json.dumps(payload)
        if stage == "context_compress":
            return {"selected_unit_ids": ["json:summary:0"]}
        return {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}
    result, receipt = compile_task_context([source], task=task, token_budget=160, required_asset_types=(), model_call=scripted, compression_input_tokens=8192)
    assert result[0].safe_summary == "You owe me one joke."
    assert calls == ["context_compress", "context_fidelity"]
    assert receipt["compression_trace"][0]["writer_projection_version"] == STORY_PROJECTION_VERSION


def test_required_clean_body_exceeding_budget_fails_without_prefix_or_expansion():
    source = replace(candidate("best_draft_candidate", text=json.dumps(mixed_source())), required=True)
    with pytest.raises(KernelError, match="necessary exact task content"):
        compile_task_context([source], task={**TASK, "writer_projection_version": STORY_PROJECTION_VERSION}, token_budget=10, required_asset_types=())


def test_writer_index_text_graph_and_facts_ignore_review_only_changes():
    doc = {"source_artifact_type": "best_draft_candidate", "metadata": {}, "content_text": "old"}
    a, b = writer_index_document(doc, mixed_source("a")), writer_index_document(doc, mixed_source("z"))
    assert a == b
    assert not a["character_ids"]
    assert "You owe me one joke." in a["content_text"]
    for marker in NOISE:
        assert marker not in json.dumps(a)


def test_quality_visibility_does_not_globally_mutate_context_or_sources():
    source = mixed_source()
    saved = deepcopy(source)
    story_history(json.dumps(source), physical_type="best_draft_candidate")
    assert source == saved
    context = {"context_segments": [{"asset_version_id": "s", "asset_type": "world_bible", "safe_summary": json.dumps(source["structured_facts"])}]}
    review = build_provider_context_view("review", context, {}, writer_projection_version=STORY_PROJECTION_VERSION)
    assert "PRIVATE-FACT" in json.dumps(review)
