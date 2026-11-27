from copy import deepcopy
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage
from novel_forge.modules.worldbuilding.actor_isolation import actor_output_schema, actor_task, validate_actor_output, validate_actor_policy
from novel_forge.modules.worldbuilding.actor_intents import reconcile_accepted_intent
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy
from tests.unit.test_world_actor_isolation import source


def frozen_source(prior=None):
    frozen = source()
    frozen.update(provider_projection_version="world-role-delivery.v2", request={"book_run_id": "same-book-run"},
                  actor_experiment={"version": "world-actor-experiment.v2", "actor_ids": ["hero", "rival"], "max_rounds": 1,
                                    "max_actions_per_actor": 1, "max_intent_steps": 4},
                  actor_intent_sources={"hero": prior} if prior else {})
    return frozen


def task_for(prior=None):
    return actor_task(frozen_source(prior), {"asset_version_id": "source", "content_hash": "source-hash"}, "hero")


def raw_intention(task):
    context = task["private_observation"]["intent_context"]
    prior = context["state"]
    steps = [{"step_id": "secure-copy", "action": "护住证词副本", "depends_on": [], "basis_refs": ["seen"], "obligation_ids": [], "decision": "CONTINUE", "reason": "先保住证据"},
             {"step_id": "deliver-copy", "action": "将副本交给可信同门", "depends_on": ["secure-copy"], "basis_refs": ["seen"], "obligation_ids": [], "decision": "CONTINUE", "reason": "后续交付仍是计划"}]
    if prior:
        steps = [{key: deepcopy(value) for key, value in item.items() if key not in {"status", "version", "completion"}} for item in prior["steps"]]
        for step, old in zip(steps, prior["steps"], strict=True):
            step["decision"] = "PRESERVE" if old["status"] in {"COMPLETED", "ABANDONED"} else "CONTINUE"
    selected = next((step for step in steps if step["decision"] == "CONTINUE"), None)
    return {"actor_id": "hero", "action": selected["action"] if selected else "等待", "basis_summary": "依据自己看见的封门与保护同门的愿望", "basis_refs": ["seen"], "commitment_dispositions": [],
            "intent_plan": {"intent_id": context["intent_id"], "goal_id": context["goal_id"], "revision": context["next_revision"],
                            "goal": "保全同门与证词", "constraints": ["不让证人暴露"], "disposition": "CONTINUE", "reason": "封门后仍需保全证词", "trigger_refs": ["seen"],
                            "steps": steps, "selected_step_id": selected["step_id"] if selected else None}}


def accepted_source(state):
    return {"proposal_ref": {"asset_version_id": "actor:one", "content_hash": "actor-hash"}, "acceptance_id": "accept:one",
            "outcome_ref": {"asset_version_id": "outcome:one", "content_hash": "outcome-hash"}, "state": state}


def binding_and_outcome(output):
    from tests.unit.test_world_causal_preparation import generated_paths
    from novel_forge.modules.canon_graph.background import preparation_lineage

    transition = deepcopy(generated_paths()["candidates"][0]["transition"])
    transition.update(actor_id="hero", action=output["action"], camera="ON_CAMERA")
    binding = {"asset_version_id": "action:one", "content_hash": "action-hash", "action": {"contract_version": "world-production-action.v2", "world_plan": {
        "disposition": "ELIGIBLE", "selected_candidate_id": "selected", "selected_path_id": "", "candidate_futures": [{"candidate_id": "selected", "eligible": True, "transition": transition}]}}}
    outcome = {"state_events": [{"event_id": "observed:one", "provenance": {"accepted_draft_asset_version_id": "draft:accepted"},
                  "mutation": {"payload": {"preparation_lineage": preparation_lineage(binding, transition["transition_id"]), "world_transition": {"payload_json": json.dumps(transition)}}}}]}
    return binding, outcome


def test_v3_intent_is_bounded_explicit_and_legacy_contract_stays_v2():
    frozen = frozen_source()
    validate_actor_policy(frozen["actor_experiment"], character_ids=["hero", "rival"], policy=WorldProductionPolicy(**frozen["policy"]))
    task = task_for()
    assert PlanningProviderStage("world_candidates.actor_0", task, actor_output_schema(task)).output_schema_ref.endswith(":v3")
    output = validate_actor_output(raw_intention(task), task)
    assert [step["status"] for step in output["intent_state"]["steps"]] == ["PLANNED", "PLANNED"]
    assert output["intent_state"]["revision"] == 1
    legacy = frozen_source()
    legacy["actor_experiment"] = {key: value for key, value in legacy["actor_experiment"].items() if key != "max_intent_steps"}
    legacy["actor_experiment"]["version"] = "world-actor-experiment.v1"
    task = actor_task(legacy, {"asset_version_id": "source", "content_hash": "hash"}, "hero")
    assert task["contract_version"] == "world-actor-task.v2"
    assert "intent_plan" not in actor_output_schema(task)["properties"]
    assert "intent_context" not in task["private_observation"]


def test_only_accepted_observed_action_completes_step_then_next_round_uses_exact_predecessor():
    task = task_for()
    output = validate_actor_output(raw_intention(task), task)
    binding, outcome = binding_and_outcome(output)
    common = dict(output=output, binding=binding, acceptance_id="accept:one", outcome_ref=accepted_source({})["outcome_ref"])
    unobserved = reconcile_accepted_intent(**common, outcome={"state_events": []})
    assert all(step["status"] == "PLANNED" for step in unobserved["steps"])
    completed = reconcile_accepted_intent(**common, outcome=outcome)
    assert completed["steps"][0]["status"] == "COMPLETED"
    assert completed["steps"][1]["status"] == "PLANNED"
    assert output["intent_state"]["steps"][0]["status"] == "PLANNED"
    next_task = task_for(accepted_source(completed))
    next_raw = raw_intention(next_task)
    next_output = validate_actor_output(next_raw, next_task)
    assert next_output["intent_state"]["intent_id"] == completed["intent_id"]
    assert next_output["intent_state"]["goal_id"] == completed["goal_id"]
    assert next_output["intent_state"]["revision"] == 2
    assert next_output["intent_state"]["predecessor"] == accepted_source({})["proposal_ref"]
    assert next_output["intent_state"]["steps"][0]["completion"]["event_id"] == "observed:one"
    assert next_output["intent_state"]["selected_step_id"] == "deliver-copy"
    assert next_output["intent_state"]["steps"][1]["status"] == "PLANNED"
    assert "RIVAL_SECRET" not in json.dumps(next_task)


@pytest.mark.parametrize("mutation,code", [
    (lambda plan: plan["steps"].pop(0), "WORLD_ACTOR_INTENT_STEP_LOST"),
    (lambda plan: plan.update(selected_step_id="deliver-copy"), "WORLD_ACTOR_INTENT_SELECTION_INVALID"),
    (lambda plan: plan["steps"][0].update(depends_on=["deliver-copy"]), "WORLD_ACTOR_INTENT_DEPENDENCY_INVALID"),
    (lambda plan: plan.update(goal="抢走掌门之位"), "WORLD_ACTOR_INTENT_GOAL_REWRITTEN"),
    (lambda plan: plan["steps"][0].update(action="潜入敌方密室"), "WORLD_ACTOR_INTENT_REVISION_INVALID"),
])
def test_pending_plan_cannot_drop_steps_skip_dependencies_or_silently_change_goal(mutation, code):
    first_task = task_for()
    state = validate_actor_output(raw_intention(first_task), first_task)["intent_state"]
    task = task_for(accepted_source(state))
    raw = raw_intention(task)
    mutation(raw["intent_plan"])
    with pytest.raises(KernelError, match=code):
        validate_actor_output(raw, task)


@pytest.mark.parametrize("decision", ["CONTINUE", "DEFER", "REORDER", "RENEGOTIATE", "ABANDON"])
def test_reevaluation_keeps_reasons_and_versions_without_mutating_accepted_facts(decision):
    first_task = task_for()
    state = validate_actor_output(raw_intention(first_task), first_task)["intent_state"]
    task = task_for(accepted_source(state))
    raw = raw_intention(task)
    plan = raw["intent_plan"]
    plan["disposition"] = decision
    for step in plan["steps"]:
        step["decision"] = decision
    if decision in {"DEFER", "ABANDON"}:
        plan["selected_step_id"] = None
    if decision == "RENEGOTIATE":
        plan["goal"] = "先保住证人，再另寻可信交付者"
        plan["steps"][1]["action"] = "与同门重新协商见证条件"
    result = validate_actor_output(raw, task)["intent_state"]
    assert result["disposition"] == decision
    assert all(step["version"] == 2 and step["completion"] is None for step in result["steps"])
    assert all(step["status"] == "PLANNED" for step in state["steps"])


def test_completed_step_and_private_projection_cannot_be_rewritten():
    from novel_forge.modules.narrative_state.reality import narrative_hash
    from novel_forge.modules.worldbuilding.actor_isolation import validate_actor_task

    task = task_for()
    output = validate_actor_output(raw_intention(task), task)
    binding, outcome = binding_and_outcome(output)
    state = reconcile_accepted_intent(output=output, binding=binding, outcome=outcome, acceptance_id="accepted", outcome_ref={"asset_version_id": "o", "content_hash": "h"})
    task = task_for(accepted_source(state))
    raw = raw_intention(task)
    raw["intent_plan"]["steps"][0]["decision"] = "RENEGOTIATE"
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_HISTORY_REWRITTEN"):
        validate_actor_output(raw, task)
    task["private_observation"]["intent_context"]["state"]["rival_secret"] = "leak"
    task["projection_identity"] = narrative_hash(task["private_observation"])
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_CONTEXT_INVALID"):
        validate_actor_task(task)


def test_reorder_changes_dependencies_explicitly_and_forgotten_basis_cannot_drive_action():
    first_task = task_for()
    state = validate_actor_output(raw_intention(first_task), first_task)["intent_state"]
    task = task_for(accepted_source(state))
    raw = raw_intention(task)
    plan = raw["intent_plan"]
    plan["disposition"] = "REORDER"
    plan["steps"].reverse()
    plan["steps"][0].update(decision="REORDER", depends_on=[])
    plan["steps"][1].update(decision="REORDER", depends_on=["deliver-copy"])
    plan["selected_step_id"] = "deliver-copy"
    raw["action"] = plan["steps"][0]["action"]
    output = validate_actor_output(raw, task)
    assert output["intent_state"]["steps"][0]["step_id"] == "deliver-copy"
    assert output["intent_state"]["steps"][1]["depends_on"] == ["deliver-copy"]
    forgotten = frozen_source(accepted_source(state))
    forgotten["reality"]["current_state"]["character_knowledge"][0]["source_event_id"] = "new-seen"
    changed_task = actor_task(forgotten, {"asset_version_id": "s2", "content_hash": "h2"}, "hero")
    raw = raw_intention(changed_task)
    raw["basis_refs"] = ["new-seen"]
    raw["intent_plan"]["trigger_refs"] = ["new-seen"]
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_SELECTION_INVALID"):
        validate_actor_output(raw, changed_task)


def test_abandoning_intention_does_not_erase_or_complete_an_accepted_commitment():
    frozen = frozen_source()
    frozen["reality"]["current_state"]["narrative_obligation"] = [{"source_event_id": "promise:accepted", "state": {
        "character_id": "hero", "obligation_id": "protect", "obligation_type": "PROMISE", "status": "OPEN"}}]
    task = actor_task(frozen, {"asset_version_id": "s", "content_hash": "h"}, "hero")
    raw = raw_intention(task)
    raw["commitment_dispositions"] = [{"obligation_id": "protect", "source_event_id": "promise:accepted", "decision": "DEFER", "reason": "先重新协商安全路线，原承诺仍然有效"}]
    raw["intent_plan"].update(disposition="ABANDON", selected_step_id=None)
    for step in raw["intent_plan"]["steps"]:
        step.update(decision="ABANDON", obligation_ids=["protect"])
    output = validate_actor_output(raw, task)
    assert output["intent_state"]["status"] == "ABANDONED"
    assert frozen["reality"]["current_state"]["narrative_obligation"][0]["state"]["status"] == "OPEN"
    raw["commitment_dispositions"] = []
    with pytest.raises(KernelError):
        validate_actor_output(raw, task)


def test_v3_complete_input_budget_failure_preserves_pending_steps():
    task = task_for()
    task["policy"]["context_token_budget"] = 1
    with pytest.raises(KernelError, match="WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        PlanningProviderStage("world_candidates.actor_0", task, actor_output_schema(task))
    assert task["private_observation"]["intent_context"]["max_steps"] == 4


@pytest.mark.parametrize("disposition", ["DEFER", "ABANDON"])
def test_judge_cannot_execute_an_intention_without_a_selected_step(disposition):
    from novel_forge.modules.worldbuilding.actor_isolation import require_actor_judgments
    from tests.unit.test_world_causal_preparation import generated_paths

    task = task_for()
    raw = raw_intention(task)
    raw["intent_plan"].update(disposition=disposition, selected_step_id=None)
    for step in raw["intent_plan"]["steps"]:
        step["decision"] = disposition
    proposal = {**validate_actor_output(raw, task), "proposal_hash": "exact-proposal"}
    generated = generated_paths()
    candidate = generated["candidates"][0]
    candidate["transition"].update(actor_id="hero", action=proposal["action"])
    candidate["transition"] = {"payload_json": json.dumps(candidate["transition"])}
    candidate["preparation_paths"] = []
    generated["candidates"] = [candidate]
    generated["actor_adjudications"] = [{"actor_id": "hero", "proposal_hash": "exact-proposal",
        "decision": "EXECUTABLE", "consequence_summary": "未选择步骤不得执行"}]
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_REWRITTEN"):
        require_actor_judgments(generated, [proposal])
    generated["candidates"] = []
    generated["actor_adjudications"][0]["decision"] = "REJECTED"
    require_actor_judgments(generated, [proposal])


@pytest.mark.parametrize("preserve_reason", [None, "保留已经完成的证词保护，重新确认后再履行下一步"])
def test_world_judge_deduplicates_intent_plan_without_losing_pending_steps_or_provenance(preserve_reason):
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    actor_task_input = task_for()
    proposal = validate_actor_output(raw_intention(actor_task_input), actor_task_input)
    if preserve_reason:
        binding, outcome = binding_and_outcome(proposal)
        completed = reconcile_accepted_intent(output=proposal, binding=binding, outcome=outcome,
            acceptance_id="accept:one", outcome_ref=accepted_source({})["outcome_ref"])
        actor_task_input = task_for(accepted_source(completed))
        raw = raw_intention(actor_task_input)
        raw["intent_plan"]["steps"][0]["reason"] = preserve_reason
        proposal = validate_actor_output(raw, actor_task_input)
        assert proposal["intent_state"]["steps"][0]["reason"] != preserve_reason
    task = {"contract_version": "world-provider-task.v2", "role": "WORLD_REASONER", "fact_mutation_allowed": False,
        "source_ref": {"asset_version_id": "source:1", "content_hash": "sha256:source"}, "projection_identity": "sha256:projection",
        "context_projection": {"selection": []}, "actor_proposals": [proposal]}
    frozen = deepcopy(task)
    projected = build_provider_task_view("world_candidates.generate", {"world_preparation": task})["world_preparation"]
    delivered = projected["actor_proposals"][0]
    assert "intent_plan" not in delivered
    assert delivered["intent_state"] == proposal["intent_state"]
    assert delivered["proposal_hash"] == proposal["proposal_hash"]
    assert delivered["intent_plan_receipt"]["proposed_step_dispositions"] == {step["step_id"]: {"decision": step["decision"], "reason": step["reason"]} for step in proposal["intent_plan"]["steps"]}
    assert task == frozen
    assert build_provider_task_view("world_candidates.generate", {"world_preparation": projected})["world_preparation"] == projected
    malformed = deepcopy(task)
    malformed["actor_proposals"][0]["intent_plan"]["steps"][1]["action"] = "silently lose commitment"
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_PROJECTION_DRIFT"):
        build_provider_task_view("world_candidates.generate", {"world_preparation": malformed})
