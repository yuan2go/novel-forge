from dataclasses import replace
from types import SimpleNamespace

import pytest

from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage
from novel_forge.modules.story_planning_runtime.world_sampling import (
    FrozenWorldSample, WORLD_ACTOR_SAMPLE_STAGES, world_sample_definitions, world_sample_result_review,
)
from novel_forge.modules.worldbuilding.actor_isolation import actor_output_schema, actor_task
from tests.unit.test_world_actor_isolation import source


def test_actor_sample_output_validates_private_basis_and_continuing_obligation():
    contract = source()
    contract["provider_projection_version"] = "world-role-delivery.v2"
    contract["reality"]["current_state"]["narrative_obligation"] = [{
        "source_event_id": "accepted-promise", "state": {"character_id": "hero", "obligation_id": "protect-companion", "obligation_type": "PROMISE", "status": "OPEN"},
    }]
    task = actor_task(contract, {"asset_version_id": "source:v2", "content_hash": "hash"}, "hero")
    stage = PlanningProviderStage("world_candidates.actor_0", task, actor_output_schema(task))
    frozen = FrozenWorldSample({}, (), (), SimpleNamespace(content={}), SimpleNamespace(content={"contract": contract}), stage)
    output = {"actor_id": "hero", "action": "用断剑撑住落门，让同门先过。", "basis_summary": "东门封闭，守住已许下的承诺。",
              "basis_refs": ["seen", "accepted-promise"], "commitment_dispositions": [{"obligation_id": "protect-companion", "source_event_id": "accepted-promise", "decision": "CONTINUE", "reason": "同门尚未脱险"}]}
    assert world_sample_result_review(frozen, output, None) == {"rule_validation": {"status": "PASSED"}, "reference_evaluation": None}
    for invalid in ({**output, "basis_refs": ["rival-seen"]}, {**output, "commitment_dispositions": []}):
        review = world_sample_result_review(frozen, invalid, None)
        assert review["rule_validation"]["status"] == "FAILED"
        assert review["reference_evaluation"] is None
    for index in range(3):
        assert world_sample_result_review(replace(frozen, stage=replace(stage, name=f"world_candidates.actor_{index}")), output, None)["rule_validation"]["status"] == "PASSED"


def test_actor_sample_definitions_stay_experimental_and_use_native_workflow():
    from novel_forge.modules.capability_packs.operation_catalog import world_sampling_workflow_binding_catalog
    from novel_forge.modules.chapter_quality_authority.generator_reference import generator_reference_contract

    definitions = {row["name"]: row for row in world_sample_definitions(application_build_id="fixture", commit_sha="a" * 40)}
    for stage in WORLD_ACTOR_SAMPLE_STAGES:
        name = "world.provider.sample." + stage.rsplit(".", 1)[1]
        definition = definitions[name]
        assert definition["completion_contract"]["required_asset_selectors"][0]["eligibility"] == "INELIGIBLE"
        assert definition["policy"]["production_eligible"] is False
        assert world_sampling_workflow_binding_catalog().resolve(stage).operation_name == name
        contract = generator_reference_contract(stage, "sha256:" + "a" * 64)
        assert set(contract["dimensions"]) == {"goal_consistency", "epistemic_isolation", "commitment_continuity", "action_causality"}
        assert contract["sample_promotion_allowed"] is False
    with pytest.raises(KeyError, match="workflow binding not found"):
        world_sampling_workflow_binding_catalog(reference_samples=True).resolve("world_candidates.actor_0")


def test_world_schema_identity_shares_only_instance_ids_and_preserves_semantics():
    from copy import deepcopy
    from novel_forge.modules.story_planning_runtime.execution import world_schema_evidence_identity
    from novel_forge.modules.worldbuilding.actor_isolation import actor_judge_schema
    from novel_forge.modules.worldbuilding.production_schema import world_evaluation_schema

    contract = source()
    contract["provider_projection_version"] = "world-role-delivery.v2"
    task = actor_task(contract, {"asset_version_id": "source:v2", "content_hash": "hash"}, "hero")
    schema = actor_output_schema(task)
    ref = "schema:world_candidates.actor_0:v2"
    identity = world_schema_evidence_identity(schema, ref)
    rebound = deepcopy(schema)
    rebound["properties"]["actor_id"]["enum"] = ["another-actor"]
    rebound["properties"]["basis_refs"]["items"]["enum"] = ["another-id-" + str(i) for i in range(len(rebound["properties"]["basis_refs"]["items"]["enum"]))]
    assert identity == world_schema_evidence_identity(rebound, ref)
    assert identity != world_schema_evidence_identity(schema, ref.replace(":v2", ":v1"))
    with_commitment = deepcopy(contract)
    with_commitment["reality"]["current_state"]["narrative_obligation"] = [{"source_event_id": "accepted-promise", "state": {"character_id": "hero", "obligation_id": "protect-companion", "obligation_type": "PROMISE", "status": "OPEN"}}]
    committed_schema = actor_output_schema(actor_task(with_commitment, {"asset_version_id": "source:v2", "content_hash": "hash"}, "hero"))
    assert identity != world_schema_evidence_identity(committed_schema, ref)
    for key, replacement in (("minItems", 1), ("maxItems", 1)):
        changed = deepcopy(schema)
        changed["properties"]["commitment_dispositions"][key] = replacement
        assert identity != world_schema_evidence_identity(changed, ref)
    changed = deepcopy(schema)
    changed["properties"]["commitment_dispositions"]["items"]["properties"]["decision"]["enum"] = ["ABANDON", "DEFER"]
    assert identity != world_schema_evidence_identity(changed, ref)
    changed = deepcopy(rebound)
    changed["properties"]["basis_refs"]["items"]["enum"].append("additional-event")
    assert identity != world_schema_evidence_identity(changed, ref)
    changed = deepcopy(rebound)
    changed["properties"]["basis_refs"]["items"]["enum"][0] = 1
    assert identity != world_schema_evidence_identity(changed, ref)
    judge = actor_judge_schema({"properties": {}, "required": []}, [{"actor_id": "hero", "proposal_hash": "hash:1"}])
    other_judge = actor_judge_schema({"properties": {}, "required": []}, [{"actor_id": "rival", "proposal_hash": "hash:2"}])
    judge_ref = "schema:world_candidates.generate:v1:actor-isolation-v1"
    assert world_schema_evidence_identity(judge, judge_ref) == world_schema_evidence_identity(other_judge, judge_ref)
    other_judge["properties"]["actor_adjudications"]["items"]["properties"]["decision"]["enum"] = ["OTHER", "REJECTED"]
    assert world_schema_evidence_identity(judge, judge_ref) != world_schema_evidence_identity(other_judge, judge_ref)
    one = world_evaluation_schema({"candidates": [{"transition": {"transition_id": "one"}}]})
    two = world_evaluation_schema({"candidates": [{"transition": {"transition_id": "two"}}]})
    director_ref = "schema:world_candidates.evaluate:v1"
    assert world_schema_evidence_identity(one, director_ref) == world_schema_evidence_identity(two, director_ref)
    two["properties"]["evaluations"]["items"]["properties"]["dimensions"]["properties"]["causal_coherence"] = {"type": "number", "minimum": 0, "maximum": .5}
    assert world_schema_evidence_identity(one, director_ref) != world_schema_evidence_identity(two, director_ref)


def test_world_schema_identity_preserves_factory_identity_through_module_path_alias(tmp_path, monkeypatch):
    from pathlib import Path
    from novel_forge.modules.story_planning_runtime import execution

    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    expected = execution.world_schema_evidence_identity(schema, "schema:world:path-isolation")
    root = Path(execution.__file__).resolve().parents[1]
    alias = tmp_path / "modules-alias"
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(execution, "__file__", str(alias / "story_planning_runtime" / "execution.py"))
    assert execution.world_schema_evidence_identity(schema, "schema:world:path-isolation") == expected
