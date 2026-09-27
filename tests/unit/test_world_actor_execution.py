from copy import deepcopy
import json

import pytest

from novel_forge.modules.canon_graph.background import attach_background_proposals, bind_world_execution, public_world_direction
from novel_forge.modules.canon_graph.grounding import extract_grounded_candidates, grounded_claims, validate_support_review
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.contracts import narrative_event_payload
from novel_forge.modules.worldbuilding.actor_execution import compile_current_actor_steps
from novel_forge.modules.worldbuilding.actor_intents import reconcile_accepted_intent
from novel_forge.modules.worldbuilding.actor_isolation import validate_actor_output, validate_actor_policy
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy
from tests.unit.test_world_actor_intents import binding_and_outcome, frozen_source, raw_intention, task_for


def execution():
    task = task_for()
    output = validate_actor_output(raw_intention(task), task)
    binding, _ = binding_and_outcome(output)
    action = binding["action"]
    action["world_plan"]["chapter_number"] = 1
    action["world_plan"]["causal_debts"] = []
    binding["frozen_source"] = {"reality": {"current_state": {}, "events": []}}
    event = action["world_plan"]["candidate_futures"][0]["transition"]
    event.update(state_kind="world_state", entity_key="world_state_id=lamp", changes={"status": "PRESERVED"})
    refs = [{"asset_version_id": "actor:one", "content_hash": "actor-hash"}]
    action.update(execution_contract_version="world-scene-execution.v2", actor_proposals=refs)
    action["current_actor_steps"] = compile_current_actor_steps(action, [output], refs)
    return output, binding, event


def observation(binding, event, action="闻澈护住证词副本，没有把尚待交付的证词当成已经送达。"):
    transition = {**deepcopy(event), "action": action}
    claim = {"world_state_id": "lamp", "status": "PRESERVED", "summary": action,
             "evidence_start": 0, "evidence_end": len(action), "evidence_quote": action,
             "claim_kind": "OBJECTIVE_EVENT", "confidence": 1.0,
             "world_transition": {"payload_json": json.dumps(transition)},
             "causal_batch": {"contract_version": "causal-batch-event.v1", "local_id": event["transition_id"], "depends_on": event["cause_refs"]},
             "story_time": event["story_time"]}
    revision = {"chapter": 1, "text": action}
    extracted = extract_grounded_candidates(project_id="project", revision=revision, revision_asset_version_id="draft:accepted",
        context_bundle_version_id="context", provider_extraction={"extraction_status": "EXTRACTED", "world_state_changes": [claim]})
    return revision, attach_background_proposals(extraction=extracted, binding=binding)


def outcome(extraction):
    claim = extraction["world_state_changes"][0]
    return {"state_events": [{"event_id": "observed:one", "evidence": claim["extraction_evidence"],
            "provenance": {"accepted_draft_asset_version_id": "draft:accepted"},
            "mutation": {"payload": narrative_event_payload(claim)}}]}


def test_new_execution_preserves_exact_current_step_and_legacy_direction_bytes():
    output, binding, event = execution()
    public = public_world_direction(binding)
    current = public["on_camera_events"][0]
    assert public["contract_version"] == "world-planning-direction.v2"
    assert current["action"] == output["action"] == current["actor_step"]["action"]
    assert current["actor_step"]["step_id"] == output["intent_state"]["selected_step_id"]
    assert "将副本交给可信同门" not in json.dumps(public, ensure_ascii=False)
    assert "保全同门与证词" not in json.dumps(public, ensure_ascii=False)
    scene = bind_world_execution(binding, [{"scene_id": "scene:one", "world_event_ids": [event["transition_id"]]}])
    assert scene["contract_version"] == "world-scene-execution.v2"
    assert scene["on_camera_events"][0]["scene_id"] == "scene:one"
    legacy = deepcopy(binding)
    del legacy["action"]["execution_contract_version"]
    del legacy["action"]["current_actor_steps"]
    old = bind_world_execution(legacy, [{"scene_id": "scene:one", "world_event_ids": [event["transition_id"]]}])
    assert old["contract_version"] == "world-scene-execution.v1"
    assert "action" not in old["on_camera_events"][0] and "actor_step" not in old["on_camera_events"][0]


def test_policy_requires_explicit_new_execution_contract_and_preserves_missing_field():
    source = frozen_source()
    args = dict(character_ids=["hero", "rival"], policy=WorldProductionPolicy(**source["policy"]))
    assert "execution_contract_version" not in validate_actor_policy(source["actor_experiment"], **args)
    policy = {**source["actor_experiment"], "execution_contract_version": "world-scene-execution.v2"}
    assert validate_actor_policy(policy, **args) == policy
    for value in ("world-scene-execution.v1", "latest"):
        with pytest.raises(KernelError, match="WORLD_ACTOR_POLICY_INVALID"):
            validate_actor_policy({**policy, "execution_contract_version": value}, **args)


def test_observer_action_remains_independent_and_support_compares_exact_approved_step():
    output, binding, event = execution()
    revision, extracted = observation(binding, event)
    claim = grounded_claims(extracted)[0]["claim"]
    comparison = claim["actor_step_execution"]
    assert comparison["approved_target"]["action"] == output["action"]
    assert comparison["observed_action"] == revision["text"] != output["action"]
    assert json.loads(claim["world_transition"]["payload_json"])["action"] == revision["text"]
    assert claim["extraction_evidence"]["quote"] == revision["text"]
    supported = {"coverage": "COMPLETE", "claims": [{"claim_id": claim["grounded_claim_id"], "assessment": "SUPPORTED",
                 "observed_kind": "OBJECTIVE_EVENT", "reason": "正文确实保存副本，尚未交付。"}]}
    assert validate_support_review(extraction=extracted, revision=revision, revision_asset_version_id="draft:accepted", result=supported)["semantic_status"] == "SUPPORTED_CANDIDATE"
    completed = reconcile_accepted_intent(output=output, binding=binding, outcome=outcome(extracted), acceptance_id="accepted:one", outcome_ref={"asset_version_id": "outcome", "content_hash": "hash"})
    assert completed["steps"][0]["status"] == "COMPLETED"
    assert completed["steps"][0]["completion"]["observed_action"] == revision["text"]
    assert completed["steps"][1]["status"] == "PLANNED"


@pytest.mark.parametrize("assessment", ["UNSUPPORTED", "UNCERTAIN"])
def test_same_state_counter_without_realized_action_cannot_pass_semantic_support(assessment):
    _, binding, event = execution()
    revision, extracted = observation(binding, event, "闻澈望着证词，打算明日再动手。")
    claim = grounded_claims(extracted)[0]["claim"]
    assert claim["status"] == "PRESERVED"
    assert claim["actor_step_execution"]["approved_target"]["action"] != claim["actor_step_execution"]["observed_action"]
    with pytest.raises(KernelError, match="CANON_GROUNDING_REEXTRACTION_REQUIRED"):
        validate_support_review(extraction=extracted, revision=revision, revision_asset_version_id="draft:accepted", result={
            "coverage": "COMPLETE", "claims": [{"claim_id": claim["grounded_claim_id"], "assessment": assessment,
            "observed_kind": "OBJECTIVE_EVENT", "reason": "有状态计数但正文并未执行当前步骤。"}]})


@pytest.mark.parametrize("mutation", [
    lambda event: event["mutation"]["payload"].pop("actor_step_execution"),
    lambda event: event["mutation"]["payload"]["actor_step_execution"]["approved_target"].update(step_id="deliver-copy"),
    lambda event: event.update(evidence={}),
])
def test_new_completion_requires_exact_step_comparison_and_accepted_prose_grounding(mutation):
    output, binding, event = execution()
    _, extracted = observation(binding, event)
    accepted = outcome(extracted)
    mutation(accepted["state_events"][0])
    with pytest.raises(KernelError, match="WORLD_ACTOR_COMPLETION_SUPPORT_REQUIRED"):
        reconcile_accepted_intent(output=output, binding=binding, outcome=accepted, acceptance_id="accepted:one", outcome_ref={"asset_version_id": "outcome", "content_hash": "hash"})


def test_disclosed_fact_does_not_grant_other_characters_private_step_lineage():
    from novel_forge.modules.narrative_state.information import disclosed_fact_projection

    _, binding, event = execution()
    _, extracted = observation(binding, event)
    accepted = outcome(extracted)["state_events"][0]
    disclosed = disclosed_fact_projection({"source_event_id": accepted["event_id"], "state": accepted["mutation"]["payload"]})
    assert "actor_step_execution" not in disclosed["state"]
    assert "preparation_lineage" not in disclosed["state"]
    assert disclosed["state"]["status"] == "PRESERVED"
