from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.modules.capability_pack_authority.application import _select_capability_skill
from novel_forge.modules.capability_packs.artifacts import ArtifactKind, default_chapter_artifact_resolver
from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
from novel_forge.modules.capability_packs.screenplay_profiles import build_screenplay_pack_profile
from novel_forge.modules.chapter_authority.execution_gateway import _materialize_production_codex_prompt
from novel_forge.modules.chapter_authority.prompt_methods import project_planning_system, project_sections, project_skill_method
from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import build_retrieval_query_plan, build_retrieval_result
from novel_forge.modules.context_builder.writer_projection import (
    WRITER_PROJECTION_VERSION, bind_writer_history_source, project_writer_history,
)
from tests.unit.test_capability_pack_artifact_materialization import _prompt_materialization
from tests.unit.test_context_retrieval_v2 import _document, _intent, _memo

ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64


def test_accepted_history_preserves_full_body_and_host_evidence_but_not_review_or_rejected_quotes():
    source = {"chapter": 7, "scene_artifacts": [{"slot_id": "s1", "text": "正文" * 5000, "used_fact_ids": ["fact:1"]}],
              "selected_review": {"instructions": "OLD-REVIEW"}, "candidate_comparison": {"quote": "REJECTED-QUOTE"},
              "provider_evidence": {"error": "PROVIDER-NOISE"}, "best_candidate_snapshot": {"text": "DUPLICATE"}}
    document = {**_document(), "content_text": json.dumps(source)}
    original = deepcopy(document)
    query = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    kwargs = dict(project_id="project", book_id="book", intent_asset_version_id="i", memo_asset_version_id="m",
                  documents=[document], discovery_rejections=[], semantic_status={})
    result = build_retrieval_result(query_plan=query, **kwargs)
    selected = result["selected_documents"][0]
    projected = json.loads(selected["safe_summary"])
    assert projected["scene_artifacts"] == source["scene_artifacts"]
    assert len(selected["safe_summary"]) > 4000
    assert selected["compression_method"] == "none"
    assert selected["source_content_hash"] == document["source_content_hash"]
    assert selected["projection_hash"] == document["projection_hash"]
    assert selected["compression_provenance"]["writer_projection_version"] == query["writer_projection_version"]
    for marker in ("OLD-REVIEW", "REJECTED-QUOTE", "PROVIDER-NOISE", "DUPLICATE"):
        assert marker not in selected["safe_summary"]
    assert document == original
    assert build_retrieval_result(query_plan=query, **kwargs) == result
    legacy_query = {key: value for key, value in query.items() if key != "writer_projection_version"}
    legacy = build_retrieval_result(query_plan=legacy_query, **kwargs)["selected_documents"][0]
    assert legacy["safe_summary"] == original["content_text"][:4000]
    assert "writer_projection_version" not in legacy["compression_provenance"]


@pytest.mark.parametrize("source_type", ["best_draft_candidate", "draft_version"])
def test_malformed_or_inconsistent_accepted_prose_fails_closed(source_type):
    with pytest.raises(KernelError, match="WRITER_HISTORY_SOURCE_INVALID"):
        project_writer_history('{"text":"cut', source_artifact_type=source_type)
    with pytest.raises(KernelError, match="WRITER_HISTORY_PROSE_DRIFT"):
        project_writer_history(json.dumps({"text": "different", "scene_artifacts": [{"text": "original"}]}), source_artifact_type=source_type)
    assert json.loads(project_writer_history(json.dumps({"text": "old complete body"}), source_artifact_type=source_type)) == {"text": "old complete body"}


def test_explicit_scene_separators_and_source_characters_are_preserved():
    source = {"text": "🌙\n第二场", "scene_artifacts": [{"text": "🌙"}, {"text": "第二场"}], "scene_separators": ["\n"]}
    projected = json.loads(project_writer_history(json.dumps(source), source_artifact_type="best_draft_candidate"))
    assert projected["scene_artifacts"] == source["scene_artifacts"]
    assert projected["scene_separators"] == ["\n"]


def test_index_text_stays_rankable_while_writer_uses_exact_bound_source_prose():
    source = {"text": "完整接受正文。" * 1000, "selected_review": {"instruction": "SOURCE-REVIEW"},
              "provider_evidence": {"error": "SOURCE-ERROR"}}
    document = {**_document(), "content_text": "INDEX-REVIEW-NOISE"}
    document["writer_history_projection"] = bind_writer_history_source(
        source, source_asset_version_id=document["source_asset_version_id"],
        source_content_hash=document["source_content_hash"], source_artifact_type=document["source_artifact_type"],
    )
    original = deepcopy(document)
    query = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    kwargs = dict(project_id="project", book_id="book", intent_asset_version_id="i", memo_asset_version_id="m",
                  documents=[document], discovery_rejections=[], semantic_status={})
    clean = build_retrieval_result(query_plan=query, **kwargs)["selected_documents"][0]
    legacy = build_retrieval_result(query_plan={key: value for key, value in query.items() if key != "writer_projection_version"},
                                   **kwargs)["selected_documents"][0]
    assert json.loads(clean["safe_summary"]) == {"text": source["text"]}
    assert len(clean["safe_summary"]) > 4000
    assert legacy["safe_summary"] == document["content_text"]
    assert clean["retrieval_scores"] == legacy["retrieval_scores"]
    assert document == original
    assert clean["compression_provenance"]["writer_source_text_fingerprint"] == document["writer_history_projection"]["source_text_fingerprint"]
    for noise in ("SOURCE-REVIEW", "SOURCE-ERROR", "INDEX-REVIEW-NOISE"):
        assert noise not in clean["safe_summary"]


@pytest.mark.parametrize("field", ["version", "source_asset_version_id", "source_content_hash", "source_artifact_type", "text", "text_fingerprint"])
def test_bound_retrieval_history_rejects_source_or_semantic_projection_tampering(field):
    from novel_forge.modules.context_builder.production_retrieval import _selected_document

    document = {**_document(), "content_text": "a plain indexed extract"}
    document["writer_history_projection"] = bind_writer_history_source(
        {"text": "accepted body"}, source_asset_version_id=document["source_asset_version_id"],
        source_content_hash=document["source_content_hash"], source_artifact_type=document["source_artifact_type"],
    )
    document["writer_history_projection"][field] = "tampered"
    with pytest.raises(KernelError, match="WRITER_HISTORY_SOURCE_BINDING_INVALID"):
        _selected_document(document, clean_history=True)


@pytest.mark.parametrize("asset_type", ["narrative_retrieval_document", "character_timeline", "world_bible"])
def test_private_facts_cannot_escape_through_type_aliases_or_json_summary(asset_type):
    facts = [{"fact_id": "public", "state": {"detail": "PUBLIC-STORY", "private": {"provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "NESTED-SECRET"}}},
             {"fact_id": "private", "provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "PRIVATE-FACT"}]
    context = {"context_segments": [{"asset_type": asset_type, "asset_version_id": "source:1", "safe_summary": json.dumps(facts), "structured_facts": facts}]}
    old = build_provider_context_view("draft", context, {})
    new = build_provider_context_view("draft", context, {}, clean_writer_context=True)
    assert "PRIVATE-FACT" in json.dumps(old)
    assert "PUBLIC-STORY" in json.dumps(new)
    assert "PRIVATE-FACT" not in json.dumps(new)
    assert "NESTED-SECRET" not in json.dumps(new)
    assert context["context_segments"][0]["structured_facts"] == facts


@pytest.mark.parametrize("capability,expected,stage", [
    ("reader.promise.generate", "topic-development", "reader.promise.generate"),
    ("planning.book.generate", "long-outline", "book_plan.generate"),
    ("planning.arc.generate", "long-outline", "arc_plan.generate"),
    ("planning.story_chapter.generate", "chapter-outline", "chapter_plan.generate"),
])
def test_current_planning_bindings_select_generation_methods_without_deconstruction(capability, expected, stage):
    profile = build_story_planning_pack_profile(ROOT, operation_definition_hash=HASH)
    skill = _select_capability_skill(profile.manifest["skill_binding"]["skills"], capability_id=capability, input_contract_ref="input", output_contract_ref="output")
    assert skill["skill_ref"] == expected
    artifact = next(item for item in profile.artifact_catalog["artifacts"] if item["kind"] == "SKILL" and item["ref"] == expected and item["version"] == skill["version"])
    method = project_skill_method(artifact["content"]["text"], ref=expected, version=skill["version"], stage=stage, targeted=False)
    assert "Markdown" not in method
    if stage == "reader.promise.generate":
        assert "## Reader promise" in method
        assert "## Creative direction" not in method
        assert "/data/analysis" not in method
    if stage == "book_plan.generate":
        assert "## Book planning" in method
        assert "## Arc planning" not in method


def test_frozen_planning_skill_selection_remains_compatible():
    source = build_story_planning_pack_profile(ROOT, operation_definition_hash=HASH)
    skills = deepcopy(source.manifest["skill_binding"]["skills"])
    for skill in skills:
        skill["version"] = "long-outline-v1" if skill["skill_ref"] == "long-outline" else skill["skill_ref"] + "-qualification-v1"
    assert _select_capability_skill(skills, capability_id="reader.promise.generate", input_contract_ref="i", output_contract_ref="o")["skill_ref"] == "hot-novel-business-deconstruction"


@pytest.mark.parametrize("stage", ["creative.candidates.generate", "world.design.generate", "book_plan.generate", "arc_plan.generate", "chapter_group_plan.generate", "chapter_plan.generate"])
def test_planning_system_only_contains_current_stage_rules(stage):
    text = (ROOT / "config/capability_packs/artifacts/story_planning_system_instruction.md").read_text()
    projected = project_planning_system(text, stage=stage)
    assert "Instruction priority" in projected
    assert "narrative_qualification" in projected
    assert ("publish-metadata inputs" in projected) == (stage == "chapter_plan.generate")
    assert ("arc_segment.entry_state_ref" in projected) == (stage == "arc_plan.generate")
    assert ("chapter_function_matrix` row" in projected) == (stage == "chapter_group_plan.generate")
    assert ("obligation_windows[].obligation_id" in projected) == (stage == "book_plan.generate")
    assert len(projected) < len(text)


@pytest.mark.parametrize("stage,ref,method", [
    ("screenplay_generate", "prose-generation", "Screenplay generation"),
    ("screenplay_revision", "prose-generation", "Screenplay revision"),
    ("screenplay_review", "quality-review", "Screenplay review"),
])
def test_screenplay_profile_projects_only_its_adaptation_method(stage, ref, method):
    profile = build_screenplay_pack_profile(ROOT, stage=stage, operation_definition_hash=HASH)
    skill = profile.manifest["skill_binding"]["skills"][0]
    assert skill["skill_ref"] == ref
    artifact = next(item for item in profile.artifact_catalog["artifacts"] if item["kind"] == "SKILL" and item["ref"] == ref and item["version"] == skill["version"])
    projected = project_skill_method(artifact["content"]["text"], ref=ref, version=skill["version"], stage=stage, targeted=False)
    assert "## " + method in projected
    assert "scene_artifacts" not in projected
    assert "## Draft" not in projected
    assert "## Chapter review" not in projected


def test_projection_rejects_missing_duplicate_or_wrong_stage_methods():
    with pytest.raises(KernelError, match="PROMPT_METHOD_PROJECTION_INVALID"):
        project_sections("## Shared rules\n\nx", "Shared rules", "Draft")
    with pytest.raises(KernelError, match="PROMPT_METHOD_PROJECTION_INVALID"):
        project_sections("\n## Shared rules\nx\n## Shared rules\ny", "Shared rules")
    with pytest.raises(KernelError, match="PROMPT_METHOD_STAGE_UNSUPPORTED"):
        project_skill_method((ROOT / "skills/prose-generation/SKILL.md").read_text(), ref="prose-generation", version="prose-generation-v4", stage="review", targeted=False)


def test_legacy_artifact_hashes_remain_exact():
    resolver = default_chapter_artifact_resolver(ROOT)
    expected = [(ArtifactKind.SKILL, "prose-generation", "prose-generation-v3", "7728142f0f7319b4aea1d2ee285e7d792e1212357282a8f76c6c3c54e532fa1d"),
                (ArtifactKind.SKILL, "chapter-outline", "chapter-plan-skill-v2", "d70ad57ec4d0452e2544e3465c96efe9776e347a39966fdc8834c8e4e27ac61f"),
                (ArtifactKind.PROMPT_SYSTEM_INSTRUCTION, "prompt-system:chapter-generation-pack", "v2", "aac995402b1a612d5c47c29cce9e3808db9a8413f3079785a98182f629f6e757"),
                (ArtifactKind.PROMPT_TEMPLATE, "prompt-template:chapter-generation-pack", "v5", "1884c4c455147b5063ebf50d661077f6061002120861b4140d14f8af9cf40906")]
    for kind, ref, version, digest in expected:
        assert resolver.resolve(kind, ref, version).content_hash == "sha256:" + digest


@pytest.mark.parametrize("version,legacy", [("v5", True), ("v6", False), ("v7", False)])
def test_effective_writer_prompt_preserves_story_and_versioned_history_boundary(version, legacy):
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    from tests.unit.test_production_execution_gateway import contracts

    resolver = default_chapter_artifact_resolver(ROOT)
    history = {"text": "ACCEPTED-STORY", "selected_review": {"rule": "OLD-REVIEW-INSTRUCTION"},
               "candidate_comparison": {"evidence": {"quote": "REJECTED-EXPRESSION"}}, "provider_evidence": {"error": "OLD-PROVIDER-ERROR"}}
    context = {"context_segments": [{"asset_type": "narrative_retrieval_document", "asset_version_id": "accepted:7", "narrative_function": "recent_accepted_prose",
                                    "safe_summary": json.dumps(history), "structured_facts": [{"fact_id": "secret", "provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "PRIVATE-QUALITY"}]}]}
    materialization = _prompt_materialization(context)
    materialization["pack_artifacts"] = {
        "system_instruction": resolver.resolve(ArtifactKind.PROMPT_SYSTEM_INSTRUCTION, "prompt-system:chapter-generation-pack", "v2" if legacy else "v3").to_dict(),
        "prompt_template": resolver.resolve(ArtifactKind.PROMPT_TEMPLATE, "prompt-template:chapter-generation-pack", version).to_dict(),
        "skill": resolver.resolve(ArtifactKind.SKILL, "prose-generation", "prose-generation-v3" if legacy else "prose-generation-v4").to_dict(),
    }
    *_, request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    prompt, evidence = _materialize_production_codex_prompt(request=request, stage="draft", inputs={"plan": {}, "style": {}, "chapter_memo": {}, "realization_contract": {}}, materialization=materialization)
    assert "ACCEPTED-STORY" in prompt
    for marker in ("OLD-REVIEW-INSTRUCTION", "REJECTED-EXPRESSION", "OLD-PROVIDER-ERROR", "PRIVATE-QUALITY"):
        assert (marker in prompt) == legacy
    method = prompt.split("<governed_skill>\n", 1)[1].split("\n</governed_skill>", 1)[0]
    if not legacy:
        assert "## Draft" in method
        assert "Targeted revision" not in method
        assert "ReReview" not in method
        assert "Screenplay generation" not in method
        assert evidence["method_selection"]["skill_sections"] == ["Shared rules", "Draft"]
        assert evidence["provider_view"]["context_contract_version"] == ("provider-context-view-v6" if version == "v7" else "provider-context-view-v5")
        assert evidence["provider_prompt_projection_version"] == ("authority-projection-task-provider-v5" if version == "v7" else "authority-projection-task-provider-v4")
    assert evidence["provider_view"]["provider_admission_uses_component_estimates"] is False


@pytest.mark.parametrize("stage,method", [("world_candidates.generate", "World transition proposals"), ("world_candidates.evaluate", "World transition evaluation"), ("world_candidates.actor_0", "Actor intention"), ("world_candidates.actor_1", "Actor intention"), ("world_candidates.actor_2", "Actor intention")])
def test_native_world_substages_retain_their_chapter_producer_without_unrelated_planning_rules(stage, method):
    profile = build_story_planning_pack_profile(ROOT, operation_definition_hash=HASH)
    skill = _select_capability_skill(profile.manifest["skill_binding"]["skills"], capability_id="planning.story_chapter.generate", input_contract_ref="i", output_contract_ref="o")
    assert skill["skill_ref"] == "chapter-outline"
    text = (ROOT / "skills/chapter-outline/SKILL.md").read_text()
    projected = project_skill_method(text, ref=skill["skill_ref"], version=skill["version"], stage=stage, targeted=False)
    assert "## " + method in projected
    assert "## Chapter planning" not in projected
    system = project_planning_system((ROOT / "config/capability_packs/artifacts/story_planning_system_instruction.md").read_text(), stage=stage)
    assert "publish-metadata inputs" not in system
    assert "ANCHOR < DEFINED < DETAILED < ACTIVE" not in system


def test_evaluator_and_reader_outcome_select_only_their_judgment_methods():
    from novel_forge.modules.capability_packs.longform_profiles import build_narrative_evaluation_pack_profile, build_reader_outcome_pack_profile
    for builder, stage, heading in [(build_narrative_evaluation_pack_profile, "narrative_semantic_evaluation", "Design evaluation"), (build_reader_outcome_pack_profile, "reader_outcome", "Reader outcome")]:
        profile = builder(ROOT, operation_definition_hash=HASH)
        skill = profile.manifest["skill_binding"]["skills"][0]
        artifact = next(item for item in profile.artifact_catalog["artifacts"] if item["kind"] == "SKILL" and item["ref"] == skill["skill_ref"] and item["version"] == skill["version"])
        method = project_skill_method(artifact["content"]["text"], ref=skill["skill_ref"], version=skill["version"], stage=stage, targeted=False)
        assert "## " + heading in method
        assert "## Chapter review" not in method
        assert "## Feedback interpretation" not in method


def test_clean_retrieval_merge_compression_and_final_writer_projection_compose():
    from dataclasses import replace
    from novel_forge.modules.chapter_authority.handlers import merge_task_retrieval_projections
    from novel_forge.modules.context_builder.domain import build_authority_context_bundle
    from novel_forge.modules.context_builder.production_retrieval import _selected_document
    from novel_forge.modules.context_builder.task_compression import compile_task_context
    from tests.unit.test_task_scoped_context import candidate, TASK, BOUNDARY

    original = {"chapter": 3, "scene_artifacts": [
        {"slot_id": "s1", "text": "You owe me one joke."},
        {"slot_id": "s2", "text": "Unrelated banquet. " * 200}],
        "selected_review": {"rule": "OLD-REVIEW"}, "candidate_comparison": {"quote": "REJECTED-PROSE"}}
    selected = _selected_document({"source_asset_version_id": "source:1", "source_content_hash": HASH,
        "source_artifact_type": "best_draft_candidate", "projection_hash": HASH, "content_text": json.dumps(original), "metadata": {}}, clean_history=True)
    metadata = merge_task_retrieval_projections({"content_hash": HASH, "safe_summary": json.dumps(original),
        "physical_asset_type": "narrative_retrieval_document", "structured_facts": [{"fact_id": "private", "provider_visibility": "INTERNAL_QUALITY_ONLY", "value": "PRIVATE-QUALITY"}],
        "provenance": {"authority_asset_version_id": "source:1"}}, [selected])
    assert json.loads(metadata["safe_summary"])["scene_artifacts"] == original["scene_artifacts"]
    assert metadata["structured_facts"] == []
    assert metadata["physical_asset_type"] == "best_draft_candidate"
    source = replace(candidate(kind="narrative_retrieval_document", text=metadata["safe_summary"]),
        physical_asset_type="best_draft_candidate", narrative_function="recent_accepted_prose", provenance=metadata["provenance"])

    def choose(stage, task):
        for marker in ("OLD-REVIEW", "REJECTED-PROSE", "PRIVATE-QUALITY"):
            assert marker not in json.dumps(task["units"])
        return {"selected_unit_ids": ["json:scene_artifacts:0"]} if stage == "context_compress" else {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}

    compiled, receipt = compile_task_context([source], task=TASK, token_budget=350, required_asset_types=(), model_call=choose, compression_input_tokens=8192)
    assert compiled[0].compression_method == "host-bound-extractive-semantic.v2"
    assert receipt["compression_trace"][0]["writer_projection_version"] == WRITER_PROJECTION_VERSION
    plan = replace(candidate(kind="chapter_plan", text="Exact frozen chapter plan.", required=True), asset_version_id="plan:21", estimated_tokens=40,
        provenance={"authority_asset_version_id": "plan:21"}, source_identity="plan:21", content_digest="sha256:" + "c" * 64, source_revision="sha256:" + "c" * 64)
    bundle = build_authority_context_bundle(project_id="project", book_id="book", stage="draft", created_by_operation_id="operation",
        context_profile_version="draft-context-profile-v4", token_budget=1000, candidates=[plan, *compiled], authority_state_boundary=BOUNDARY,
        narrative_position={"chapter": 21, "book_id": "book"}, task_context_receipt=receipt)
    view = build_provider_context_view("draft", bundle, {}, clean_writer_context=True)
    assert "You owe me one joke." in json.dumps(view)
    for marker in ("Unrelated banquet", "OLD-REVIEW", "REJECTED-PROSE", "PRIVATE-QUALITY"):
        assert marker not in json.dumps(view)
    assert json.loads(selected["safe_summary"])["scene_artifacts"] == original["scene_artifacts"]
    legacy_view = build_provider_context_view("draft", bundle, {})
    assert "You owe me one joke." in json.dumps(legacy_view)
    without_projection = deepcopy(bundle)
    del without_projection["context_manifest"]["compression_trace"][0]["trace"][0]["writer_projection_version"]
    with pytest.raises(KernelError, match="WRITER_HISTORY_COMPRESSED_PROJECTION_REQUIRED"):
        build_provider_context_view("draft", without_projection, {}, clean_writer_context=True)
    tampered = deepcopy(bundle)
    next(segment for segment in tampered["context_segments"] if segment["asset_version_id"] == "source:1")["safe_summary"] += "\n\nREJECTED-PROSE"
    with pytest.raises(KernelError, match="WRITER_HISTORY_COMPRESSED_PROJECTION_REQUIRED"):
        build_provider_context_view("draft", tampered, {}, clean_writer_context=True)


@pytest.mark.parametrize("experience", [
    "Quiet family recollections with stable relationships and no conflict escalation.",
    "A legal procedural story whose author selects witness verification and receipts.",
    "An original cultivation adventure whose author selects growth and danger.",
])
def test_narrative_intent_pack_reaches_real_prompt_assembly_and_keeps_work_specific_story(experience):
    from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema
    from tests.unit.test_provider_task_views import _authoritative_load, _arc_working_set, _narrative_intelligence
    from tests.unit.test_production_execution_gateway import contracts

    profile = build_story_planning_pack_profile(ROOT, operation_definition_hash=HASH)
    assert profile.manifest["identity"]["version"] == "2.18.0"
    assert profile.manifest["prompt_binding"]["template_version"] == "v3"
    artifacts = profile.artifact_catalog["artifacts"]
    def artifact(kind, ref, version):
        return next(item for item in artifacts if (item["kind"], item["ref"], item["version"]) == (kind, ref, version))
    context = {"schema_version": "novelos.planning_context_bundle.v1", "book_id": "book-1",
        "logical_key": "book:main", "planning_scope": "BOOK", "input_versions": [
            {"role": "book_design", "asset_version_id": "design:v1", "asset_type": "book_design",
             "content_hash": HASH, "content": {"premise": experience, "target_chapters": 240}}]}
    inputs = {"planning_command": {"logical_key": "book:main", "planning_scope": "BOOK",
        "narrative_search_planning_horizon": {"target_chapters": 240, "opening_topology_budget": {"calls": "HOST-BUDGET-NOISE"}},
        "narrative_search_desired_transformation": {"goal": experience, "selection_policy": {"weights": "HOST-SCORE-NOISE"}},
        "narrative_search_hard_constraints": [experience], "repair_reason": "HOST-RETRY-NOISE"},
        "frozen_inputs": [{"role": "book_design", "asset_version_id": "design:v1", "content_hash": HASH}],
        "authoritative_narrative_load": _authoritative_load(), "arc_working_set": _arc_working_set(),
        "narrative_intelligence": _narrative_intelligence()}
    import hashlib
    passages, offset = [], 0
    for text in ("Previously selected prose.\n\n", "The character retains the prior choice.\n"):
        passages.append({"start": offset, "end": offset + len(text), "text": text,
                         "text_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()})
        offset += len(text)
    inputs["arc_working_set"]["working_manuscript"] = {"selected_version": "selected:v4", "passages": passages}
    materialization = _prompt_materialization(context)
    materialization["pack_artifacts"] = {
        "system_instruction": artifact("PROMPT_SYSTEM_INSTRUCTION", "prompt-system:story-planning-pack", "v12"),
        "prompt_template": artifact("PROMPT_TEMPLATE", "prompt-template:story-planning-pack", "v3"),
        "skill": artifact("SKILL", "long-outline", "long-outline-v4")}
    schema = bind_narrative_intent_schema({"type": "object", "properties": {"constraints": {"type": "array"}}})
    materialization["output_schema"] = {"ref": "schema:planning-provider-output:book:v1:narrative-intent-v1", "content_hash": HASH, "content": schema}
    frozen = deepcopy((inputs, materialization))
    from novel_forge.modules.production_execution import ExecutionRuntimeClass
    *_, request = contracts(backend_id="codex-cli", runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE)
    prompt, evidence = _materialize_production_codex_prompt(request=request, stage="book_plan.generate", inputs=inputs, materialization=materialization)
    assert experience in prompt
    for noise in ("HOST-BUDGET-NOISE", "HOST-SCORE-NOISE", "HOST-RETRY-NOISE"):
        assert noise not in prompt
    assert (inputs, materialization) == frozen
    assert evidence["provider_prompt_projection_version"] == "planning-narrative-intent-projection.v1"
    assert len(evidence["narrative_intent_projection"]["omissions"]) >= 3
    assert evidence["method_selection"]["skill_sections"] == ["Shared rules", "Book planning"]
    assert "Chapter serialization realization" not in evidence["method_selection"]["system_sections"]
    assert "Chapter plan" not in evidence["method_selection"]["system_sections"]
    assert '"target_chapters":240' in prompt
    assert '"selected_version":"selected:v4"' in prompt
    assert '"__text_fragments__"' in prompt
    assert "Previously selected prose.\\n\\nThe character retains the prior choice.\\n" in prompt
    assert "All prose, whitespace, source positions and version bindings are retained" in prompt
    proof = evidence["provider_view"]["exact_context_references"]
    assert proof["text_fragment_group_count"] == 1 and proof["decoded_equal"]


def test_narrative_intent_projection_preserves_relative_refs_knowledge_and_full_repair_sources():
    from novel_forge.modules.chapter_authority.provider_views import project_planning_narrative_intent

    task = {"stage": "chapter_plan.generate", "planning_command": {"generation_operation_id": "operation:1"},
            "working_continuity": {"prose": "Previously witnessed response", "accepted_through_chapter": 0}}
    context = {"stage": "chapter_plan.generate", "segments": [{"role": "chapter_group_plan", "content": {"chapter_function_matrix": [{"chapter": 1}]}}],
        "matrix_source": {"json_pointer": "/segments/0/content/chapter_function_matrix/0"},
        "accepted_state_boundary": {"accepted_through_chapter": 0},
        "repair_context": {"source_candidate": {"content": {"scene_plan": [{"objective": "author's procedural intention"}]}}, "validation_failure": "retain exact failure"},
        "selection_explanation": {"audit_hash": HASH, "literal_references": "Read the full string in the named source role"}}
    original = deepcopy((task, context))
    new_task, new_context, receipt = project_planning_narrative_intent(task, context)
    assert (task, context) == original
    for key in ("segments", "matrix_source", "accepted_state_boundary", "repair_context"):
        assert new_context[key] == context[key]
    assert new_task["narrative_inputs"]["working_continuity"] == task["working_continuity"]
    assert new_task["output_protocol"]["planning_command"]["generation_operation_id"] == "operation:1"
    assert new_context["projection_reading_contract"]["literal_references"] == context["selection_explanation"]["literal_references"]
    assert receipt["semantic_source_rewrite"] is False


def test_historical_planning_profile_retains_previous_skill_bytes_and_new_schema_is_shape_compatible():
    from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema

    legacy = build_story_planning_pack_profile(ROOT, operation_definition_hash=HASH, narrative_intent_boundary=False)
    assert legacy.manifest["identity"]["version"] == "2.13.0"
    assert legacy.manifest["prompt_binding"]["template_version"] == "v2"
    for artifact in legacy.artifact_catalog["artifacts"]:
        if artifact["kind"] == "SKILL" and "legacy-narrative-intent" in artifact.get("source_identity", ""):
            assert artifact["content"]["text"] == (ROOT / artifact["source_identity"]).read_text()
    schema = {"type": "object", "additionalProperties": False, "required": ["constraints"],
              "properties": {"constraints": {"type": "array", "items": {"type": "string"}}}}
    revised = bind_narrative_intent_schema(schema)
    assert revised != schema
    for value in ({"constraints": []}, {"constraints": ["The detective checks a witness as the author requires."]}, {"constraints": 3}, {"constraints": [], "extra": True}):
        def valid(contract):
            try:
                validate_chapter_provider_output_against_schema("book_plan.generate", contract, value)
                return True
            except KernelError:
                return False
        assert valid(schema) == valid(revised)


def test_event_first_schema_hints_reach_nested_plan_fields_without_changing_validation():
    from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema

    fields = {key: {"type": "array", "items": {"type": "string"}} for key in
              ("hard_constraints", "required_events", "forbidden_events")}
    schema = {"type": "object", "additionalProperties": False, "required": ["plan"],
              "properties": {"plan": {"type": "object", "additionalProperties": False,
                  "required": list(fields), "properties": fields}}}
    original = deepcopy(schema)
    legacy = bind_narrative_intent_schema(schema)
    revised = bind_narrative_intent_schema(schema, event_first_planning=True)
    assert schema == original
    assert legacy == bind_narrative_intent_schema(schema, event_first_planning=False)
    assert legacy["properties"]["plan"]["properties"] == fields
    for field in fields:
        assert "fictional" in revised["properties"]["plan"]["properties"][field]["description"].lower()
    samples = [
        {"plan": {"hard_constraints": ["Keep this work's ordinary protagonist."], "required_events": ["Complete the agreed delivery."], "forbidden_events": []}},
        {"plan": {**{key: [] for key in fields}, "hard_constraints": 3}},
        {"plan": {"required_events": [], "forbidden_events": []}},
        {"plan": {**{key: [] for key in fields}, "new_gate": True}},
    ]
    for sample in samples:
        def valid(contract):
            try:
                validate_chapter_provider_output_against_schema("chapter_group_plan.generate", contract, sample)
                return True
            except KernelError:
                return False
        assert valid(schema) == valid(legacy) == valid(revised)


@pytest.mark.parametrize("stage", ["context_compress", "context_fidelity"])
def test_semantic_context_substages_project_real_frozen_skill_and_system_methods(stage):
    method = "source-unit-dependency-and-final-composition.v2"
    for ref, version in [("prose-generation", "prose-generation-v5"), ("long-outline", "long-outline-v5")]:
        text = (ROOT / "skills" / ref / "SKILL.md").read_text()
        assert project_skill_method(text, ref=ref, version=version, stage=stage, targeted=False, context_substage_method=method) == project_sections(text, "Shared rules")
    text = (ROOT / "config/capability_packs/artifacts/story_planning_system_instruction.md").read_text()
    assert project_planning_system(text, stage=stage, context_substage_method=method) == project_sections(text, "Shared rules")
