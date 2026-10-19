from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.story_planning_runtime.domain import GENERATOR_INPUT_ROLES
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
from novel_forge.modules.story_planning_runtime.world_sampling import _compiled_sample_schema, _source_generation_stage
from tests.unit.test_world_working_continuity import world_source
from tests.unit.test_story_planning_runtime import _realization_slice


@pytest.mark.parametrize("has_references", [False, True])
def test_sampling_reconstructs_original_reference_scope_and_preserves_unmarked_history(has_references):
    source = world_source()
    payload = dict(project_id="p", workspace_id="w", book_id="b", actor_id="author",
                   generator_operation_name="chapter_plan.generate", logical_key="chapter:5",
                   input_versions={role: "original:" + role for role in GENERATOR_INPUT_ROLES["chapter_plan.generate"]},
                   related_arc_plan_version_ids=["original:companion-arc"], execution_contract_version="1.21.0",
                   idempotency_key="native", trace_id="trace", correlation_id="correlation",
                   narrative_realization=_realization_slice(chapter_number=5))
    references = {"arc_refs": ["original:arc_plans", "original:companion-arc"], "obligation_refs": []}
    ref = {"asset_version_id": "original-source", "content_hash": "digest"}
    original = PlanningWorldPreparation.generation_stage(source, ref, {},
        allowed_references=references if has_references else None)
    snapshot = deepcopy(original.task)
    reconstructed = _source_generation_stage(source, ref, {}, source_payload=payload, source_task=original.task)
    assert reconstructed == original and original.task == snapshot
    forged = deepcopy(original.task)
    if has_references:
        forged["plan_reference_contract"]["arc_refs"] = ["another-book:arc"]
        assert _source_generation_stage(source, ref, {}, source_payload=payload, source_task=forged).task != forged
    else:
        changed = {**payload, "related_arc_plan_version_ids": ["newer:arc"]}
        assert _source_generation_stage(source, ref, {}, source_payload=changed, source_task=original.task) == original
        assert "plan_reference_contract" not in reconstructed.task


@pytest.mark.parametrize("prompt_version", ["v1", "v2", "v3"])
@pytest.mark.parametrize("stage_name", ["world_candidates.generate", "world_candidates.evaluate"])
def test_sample_compiles_schema_with_its_original_pack_for_generation_and_director(prompt_version, stage_name):
    from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema

    source = world_source()
    source_ref = {"asset_version_id": "source", "content_hash": "digest"}
    if stage_name == "world_candidates.generate":
        stage = PlanningWorldPreparation.generation_stage(source, source_ref, {},
            allowed_references={"arc_refs": ["arc:original"], "obligation_refs": []})
    else:
        stage = PlanningWorldPreparation.evaluation_stage(source, source_ref,
            {"source": source_ref, "output": _generation_result(agency=True)},
            {"asset_version_id": "generation", "content_hash": "generation-hash"}, {})
    schema = stage.output_schema
    original = deepcopy(schema)
    materialization = {"pack_artifacts": {"prompt_template": {"ref": "prompt-template:story-planning-pack", "version": prompt_version},
                                          "skill": {"ref": "chapter-outline", "version": "chapter-outline-qualification-v4"}}}
    compiled, ref = _compiled_sample_schema(stage, materialization)
    assert schema == original
    if prompt_version == "v3":
        assert compiled == bind_narrative_intent_schema(original)
        assert ref == stage.output_schema_ref + ":narrative-intent-v1"
    else:
        assert compiled == original and ref == stage.output_schema_ref


@pytest.mark.parametrize("agency", [False, True])
@pytest.mark.parametrize("wrong_contract", [False, True])
def test_sample_result_decodes_only_the_frozen_agency_contract(agency, wrong_contract):
    from dataclasses import asdict
    from novel_forge.modules.story_planning_runtime.world_sampling import world_sample_result_review
    from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy

    result = _generation_result(agency=agency != wrong_contract)
    frozen = SimpleNamespace(
        source=SimpleNamespace(content={"contract": {"policy": asdict(WorldProductionPolicy())}}),
        context=SimpleNamespace(content={}),
        stage=SimpleNamespace(name="world_candidates.generate", task={"epistemic_contract": "world-agency.v2"} if agency else {}),
    )
    review = world_sample_result_review(frozen, result, None)
    assert review["rule_validation"]["status"] == ("FAILED" if wrong_contract else "PASSED")
    assert review["reference_evaluation"] is None


def _generation_result(*, agency):
    import json
    from tests.unit.test_world_causal_preparation import generated_paths
    from tests.unit.test_world_initial_agency import chain

    result = generated_paths()
    candidate = result["candidates"][0]
    transition = chain()[0] if agency else candidate["transition"]
    candidate.update(transition={"payload_json": json.dumps(transition)}, preparation_paths=[])
    return result
