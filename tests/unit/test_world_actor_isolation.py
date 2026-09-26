from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view, build_provider_context_view
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime.world_preparation import PlanningProviderStage
from novel_forge.modules.worldbuilding.actor_isolation import (
    actor_task, actor_output_schema, validate_actor_output, validate_actor_task, validate_actor_policy, require_actor_judgments,
)
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy


def source():
    return {
        "policy": asdict(WorldProductionPolicy(version="world-production-policy.v2", max_provider_stages=4,
                                               max_candidates=2, max_paths_per_candidate=1, max_preparation_steps=1, planning_window_chapters=1)),
        "character_definitions": [{"character_id": "hero", "name": "沈舟", "desire": "护住同门", "arc_direction": "FUTURE_ENDING_SECRET", "private_history": "GLOBAL_BACKSTORY_SECRET"},
                                  {"character_id": "rival", "name": "许霜", "desire": "RIVAL_PRIVATE_INTENTION"}],
        "reality": {"project_id": "p", "book_id": "b", "revision_id": "rev1", "baseline_kind": "ACCEPTED_REALITY", "chapter_number": 2,
                    "current_state": {"character_knowledge": [
                        {"source_event_id": "seen", "state": {"character_id": "hero", "fact_id": "gate", "status": "KNOWN", "content": "东门已封"}},
                        {"source_event_id": "forgotten", "state": {"character_id": "hero", "fact_id": "past", "status": "FORGOTTEN", "content": "FORGOTTEN_SECRET"}},
                        {"source_event_id": "rival-seen", "state": {"character_id": "rival", "fact_id": "spy", "status": "KNOWN", "content": "RIVAL_SECRET"}}],
                                      "world_state": [{"state": {"secret": "GLOBAL_CURRENT_SECRET"}}]}},
    }


def test_actor_materialized_task_omits_other_private_world_and_future_information():
    task = actor_task(source(), {"asset_version_id": "world:v1", "content_hash": "hash"}, "hero")
    stage = PlanningProviderStage("world_candidates.actor_0", task, actor_output_schema(task))
    inputs = {"world_preparation": stage.task, "planning_command": {"outline": "FUTURE_ENDING_SECRET"}}
    view = build_provider_task_view(stage.name, inputs)
    context = build_provider_context_view(stage.name, {"project_id": "p", "book_id": "b", "world_preparation": stage.task,
                                                      "author_design_projection": {"secret": "AUTHOR_SECRET"}}, view)
    materialized = json.dumps({"task": view, "context": context}, ensure_ascii=False)
    assert "东门已封" in materialized and "护住同门" in materialized
    assert "SECRET" not in materialized and "RIVAL_PRIVATE_INTENTION" not in materialized
    result = validate_actor_output({"actor_id": "hero", "action": "绕向西廊", "basis_summary": "已知东门封闭，需要护住同门。", "basis_refs": ["seen", "APPROVED_SELF_TRAITS"]}, task)
    assert result["projection_identity"] == task["projection_identity"]
    with pytest.raises(KernelError):
        validate_actor_output({"actor_id": "hero", "action": "偷看密信", "basis_summary": "对手知道的消息", "basis_refs": ["rival-seen"]}, task)
    leaked = deepcopy(task)
    leaked["world_foundation"] = source()["reality"]
    with pytest.raises(KernelError, match="WORLD_ACTOR_CONTEXT_LEAK"):
        validate_actor_task(leaked)


def test_default_world_policy_stays_unified_and_experiment_requires_explicit_bounded_policy():
    assert WorldProductionPolicy().version == "world-production-policy.v1"
    assert WorldProductionPolicy().max_provider_stages == 2
    experiment = {"version": "world-actor-experiment.v1", "actor_ids": ["hero", "rival"], "max_rounds": 1, "max_actions_per_actor": 1}
    assert validate_actor_policy(experiment, character_ids=["hero", "rival"], policy=WorldProductionPolicy(**source()["policy"])) == experiment
    for key, value in (("max_rounds", 2), ("actor_ids", ["unknown"]), ("max_actions_per_actor", 2)):
        with pytest.raises(KernelError):
            validate_actor_policy({**experiment, key: value}, character_ids=["hero", "rival"], policy=WorldProductionPolicy(**source()["policy"]))
    with pytest.raises(KernelError):
        validate_actor_policy(experiment, character_ids=["hero", "rival"], policy=WorldProductionPolicy())
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
    frozen = {**source(), "actor_experiment": experiment}
    source_ref = {"asset_version_id": "source:1", "content_hash": "source-hash"}
    with pytest.raises(KernelError, match="WORLD_ACTOR_PROPOSAL_REQUIRED"):
        PlanningWorldPreparation.generation_stage(frozen, source_ref, {})
    with pytest.raises(KernelError, match="WORLD_ACTOR_PROPOSAL_REQUIRED"):
        PlanningWorldPreparation.evaluation_stage(frozen, source_ref, {"source": source_ref}, {}, {})


def test_judge_must_disposition_all_proposals_and_cannot_replace_actor_intention():
    from tests.unit.test_world_causal_preparation import generated_paths

    proposal = {"actor_id": "hero", "action": "护住同门", "proposal_hash": "proposal:one"}
    generated = generated_paths()
    generated["candidates"] = [generated["candidates"][0]]
    generated["candidates"][0]["transition"]["actor_id"] = "hero"
    generated["candidates"][0]["transition"]["action"] = proposal["action"]
    generated["candidates"][0]["preparation_paths"] = []
    encoded = deepcopy(generated)
    encoded["candidates"][0]["transition"] = {"payload_json": json.dumps(generated["candidates"][0]["transition"])}
    encoded["actor_adjudications"] = [{"actor_id": "hero", "proposal_hash": "proposal:one", "decision": "EXECUTABLE", "consequence_summary": "代价由世界判断"}]
    require_actor_judgments(encoded, [proposal])
    wrong = deepcopy(encoded)
    wrong["actor_adjudications"] = []
    with pytest.raises(KernelError, match="WORLD_ACTOR_JUDGMENT_INCOMPLETE"):
        require_actor_judgments(wrong, [proposal])
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_REWRITTEN"):
        require_actor_judgments(encoded, [{**proposal, "action": "强行服从旧大纲"}])


def test_actor_without_private_basis_is_rejected_before_provider_request():
    frozen = source()
    frozen['reality']['current_state']['character_knowledge'] = [
        entry for entry in frozen['reality']['current_state']['character_knowledge']
        if entry['state']['character_id'] != 'rival'
    ]
    assert actor_task(frozen, {'asset_version_id': 'world:v1', 'content_hash': 'hash'}, 'hero')
    with pytest.raises(KernelError, match='WORLD_ACTOR_KNOWLEDGE_UNAVAILABLE'):
        actor_task(frozen, {'asset_version_id': 'world:v1', 'content_hash': 'hash'}, 'rival')


def test_empty_world_knowledge_query_receipt_preserves_required_constraints_and_frozen_legacy():
    from novel_forge.modules.chapter_authority.provider_views import _project_empty_world_selection
    from novel_forge.modules.narrative_state.reality import narrative_hash
    from tests.unit.test_author_design_adoption import _empty_world_knowledge, _world_author_context

    selection = _empty_world_knowledge()
    selection['need']['craft_context'] = {'characters': [f'query-only-{n}-' + 'retrieval term ' * 20 for n in range(30)]}
    selection['need']['need_digest'] = narrative_hash({key: value for key, value in selection['need'].items() if key != 'need_digest'})
    _, stage, context = _world_author_context('world_candidates.generate')
    task = {**stage.task, 'narrative_intelligence': selection}
    actual = build_provider_task_view(stage.name, {'world_preparation': task})
    selected = actual['world_preparation']['narrative_intelligence']
    receipt = selected['need']['query_directory_receipt']
    assert receipt['contract_version'] == 'world-empty-selection-query-receipt.v1'
    assert receipt['omitted_entry_count'] > 0
    assert 'craft_context' in receipt['omitted_fields']
    assert 'hard_constraints' not in receipt['omitted_fields']
    assert selected['need']['hard_constraints'] == selection['need']['hard_constraints']
    assert 'query-only-' not in json.dumps(actual)
    assert build_provider_task_view(stage.name, actual) == actual
    frozen = {**context, 'world_preparation': actual['world_preparation'], 'narrative_intelligence': selection}
    build_provider_context_view(stage.name, frozen, actual)
    legacy_selection = _project_empty_world_selection(selection, project_query_directory=False)
    legacy = build_provider_task_view(stage.name, {'world_preparation': {**stage.task, 'narrative_intelligence': legacy_selection}})
    assert 'craft_context' in legacy['world_preparation']['narrative_intelligence']['need']
    build_provider_context_view(stage.name, {**context, 'world_preparation': legacy['world_preparation'], 'narrative_intelligence': selection}, legacy)
    populated = deepcopy(selection)
    populated.update(selected=[{'knowledge_card_asset_version_id': 'selected:1', 'mechanism': 'Keep the adopted mechanism'}], selection_status='SELECTED')
    assert _project_empty_world_selection(populated) == populated
    drifted = deepcopy(frozen)
    drifted['narrative_intelligence']['need']['craft_context']['characters'].append('changed query')
    with pytest.raises(KernelError, match='WORLD_SELECTION_RECEIPT_DRIFT'):
        build_provider_context_view(stage.name, drifted, actual)


def test_actor_v2_carries_own_accepted_state_and_requires_pending_commitment_dispositions():
    from novel_forge.modules.narrative_state.reality import narrative_hash

    frozen = source()
    frozen["provider_projection_version"] = "world-role-delivery.v2"
    frozen["reality"]["current_state"]["character_belief"] = [
        {"source_event_id": "hero-belief", "state": {"character_id": "hero", "proposition_id": "safe-exit", "stance": "DOUBTS", "belief_confidence": 0.4, "summary": "The west corridor may also be watched"}}
    ]
    frozen["reality"]["current_state"].update({
        "character_state": [
            {"source_event_id": "hero-choice", "state": {"character_id": "hero", "action_state": "PROTECTING_WITNESS", "summary": "NARRATOR_ONLY_SECRET"}},
            {"source_event_id": "rival-choice", "state": {"character_id": "rival", "action_state": "RIVAL_SECRET"}},
        ],
        "relationship_state": [
            {"source_event_id": "hero-trust", "state": {"source_id": "hero", "target_id": "rival", "status": "TRUSTING", "summary": "NARRATOR_ONLY_SECRET"}},
            {"source_event_id": "rival-distrust", "state": {"source_id": "rival", "target_id": "hero", "summary": "RIVAL_SECRET"}},
        ],
        "narrative_obligation": [
            {"source_event_id": "promise-event", "state": {"character_id": "hero", "obligation_id": "protect-witness", "obligation_type": "PROMISE", "status": "OPEN", "current_development": "Witness still needs escort"}},
            {"source_event_id": "closed-promise", "state": {"character_id": "hero", "obligation_id": "old-promise", "obligation_type": "CHARACTER_COMMITMENT", "status": "FULFILLED"}},
            {"source_event_id": "rival-promise", "state": {"character_id": "rival", "obligation_id": "rival-secret", "status": "OPEN"}},
            {"source_event_id": "hero-foreshadow", "state": {"character_id": "hero", "obligation_id": "secret-lineage", "obligation_type": "FORESHADOWING", "status": "OPEN", "current_development": "NARRATOR_ONLY_SECRET"}},
            {"source_event_id": "reader-expectation", "state": {"character_id": "hero", "obligation_id": "reader-expects-betrayal", "obligation_type": "READER_EXPECTATION", "status": "OPEN", "current_development": "NARRATOR_ONLY_SECRET"}},
        ],
    })
    task = actor_task(frozen, {"asset_version_id": "world:v2", "content_hash": "hash"}, "hero")
    validate_actor_task(task)
    assert task["contract_version"] == "world-actor-task.v2"
    assert PlanningProviderStage("world_candidates.actor_0", task, actor_output_schema(task)).output_schema_ref == "schema:world_candidates.actor_0:v2"
    encoded = json.dumps(task)
    assert "PROTECTING_WITNESS" in encoded and "Witness still needs escort" in encoded
    belief = next(row for row in task["private_observation"]["observations"] if row["kind"] == "character_belief")["content"]
    assert belief["stance"] == "DOUBTS" and belief["belief_confidence"] == 0.4
    assert belief["summary"] == "The west corridor may also be watched"
    assert "rival-secret" not in encoded and "RIVAL_SECRET" not in encoded and "NARRATOR_ONLY_SECRET" not in encoded
    raw = {"actor_id": "hero", "action": "Escort the witness through the west corridor", "basis_summary": "My accepted promise still requires protection",
           "basis_refs": ["seen", "promise-event"],
           "commitment_dispositions": [{"obligation_id": "protect-witness", "source_event_id": "promise-event", "decision": "CONTINUE", "reason": "Carry out my accepted promise"}]}
    assert validate_actor_output(raw, task)["commitment_dispositions"] == raw["commitment_dispositions"]
    for changed in (
        {**raw, "commitment_dispositions": []},
        {**raw, "basis_refs": ["seen"]},
        {**raw, "commitment_dispositions": [{**raw["commitment_dispositions"][0], "source_event_id": "stale-event"}]},
    ):
        with pytest.raises(KernelError):
            validate_actor_output(changed, task)
    deferred = {**raw, "basis_refs": ["seen"], "commitment_dispositions": [{**raw["commitment_dispositions"][0], "decision": "DEFER"}]}
    assert validate_actor_output(deferred, task)["commitment_dispositions"][0]["decision"] == "DEFER"
    leaked = deepcopy(task)
    leaked["private_observation"]["accepted_self_state"].append({"kind": "relationship_state", "source_event_id": "rival-distrust", "content": {"source_id": "rival", "target_id": "hero"}})
    leaked["projection_identity"] = narrative_hash(leaked["private_observation"])
    with pytest.raises(KernelError, match="WORLD_ACTOR_CONTEXT_LEAK"):
        validate_actor_task(leaked)
    leaked = deepcopy(task)
    leaked["private_observation"]["accepted_self_state"].append({"kind": "narrative_obligation", "source_event_id": "hero-foreshadow", "content": {"character_id": "hero", "obligation_id": "secret-lineage", "obligation_type": "FORESHADOWING", "status": "OPEN"}})
    leaked["projection_identity"] = narrative_hash(leaked["private_observation"])
    with pytest.raises(KernelError, match="WORLD_ACTOR_CONTEXT_LEAK"):
        validate_actor_task(leaked)
    legacy = actor_task({key: value for key, value in frozen.items() if key != "provider_projection_version"}, {"asset_version_id": "world:v1", "content_hash": "hash"}, "hero")
    assert "accepted_self_state" not in legacy["private_observation"]
    assert "commitment_dispositions" not in actor_output_schema(legacy)["properties"]
    assert PlanningProviderStage("world_candidates.actor_0", legacy, actor_output_schema(legacy)).output_schema_ref == "schema:world_candidates.actor_0:v1"


def test_judge_must_retain_accepted_commitment_cause_when_continuing_actor_action():
    from tests.unit.test_world_causal_preparation import generated_paths

    proposal = {"actor_id": "hero", "action": "Protect the witness", "proposal_hash": "proposal:one",
                "commitment_dispositions": [{"obligation_id": "protect-witness", "source_event_id": "promise-event", "decision": "CONTINUE", "reason": "Keep my promise"}]}
    generated = generated_paths()
    candidate = generated["candidates"][0]
    candidate["transition"].update(actor_id="hero", action=proposal["action"])
    candidate["preparation_paths"] = []
    generated["candidates"] = [candidate]
    generated["actor_adjudications"] = [{"actor_id": "hero", "proposal_hash": "proposal:one", "decision": "EXECUTABLE", "consequence_summary": "The action continues the accepted commitment"}]
    transition = deepcopy(candidate["transition"])
    candidate["transition"] = {"payload_json": json.dumps(transition)}
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_REWRITTEN"):
        require_actor_judgments(generated, [proposal])
    transition["cause_refs"].append("promise-event")
    candidate["transition"] = {"payload_json": json.dumps(transition)}
    with pytest.raises(KernelError, match="WORLD_ACTOR_INTENT_REWRITTEN"):
        require_actor_judgments(generated, [proposal])
    candidate["obligation_refs"].append("protect-witness")
    require_actor_judgments(generated, [proposal])


@pytest.mark.parametrize("role", ["WORLD_REASONER", "DIRECTOR"])
def test_current_world_scope_cannot_silently_lose_accepted_causal_state_to_budget(role):
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation

    frozen = source()
    frozen.update(contract_version="world-preparation-source.v2", intent={}, world_foundation={}, planning_window=[], entity_ids=["hero"])
    frozen["reality"].update(foundation_cause_refs=["foundation:rule"], current_state={
        "character_state": [{"entity_key": "character_id=hero", "source_event_id": "hero-state", "state": {"character_id": "hero", "summary": "a" * 7500}}],
        "world_state": [{"entity_key": "world_state_id=gate", "source_event_id": "world-event", "state": {"world_state_id": "gate", "status": "SEALED", "summary": "b" * 1200}}],
        "reader_knowledge": [{"entity_key": "fact_id=reader-only", "source_event_id": "reader-event", "state": {"fact_id": "reader-only", "status": "KNOWN"}}],
    })
    reference = {"asset_version_id": "world:v1", "content_hash": "frozen"}
    legacy = PlanningWorldPreparation._task(frozen, reference, role)
    assert any(row["source_event_id"] == "world-event" and row["reason"] == "CONTEXT_BUDGET_EXCEEDED" for row in legacy["context_projection"]["rejections"])
    current = {**frozen, "provider_projection_version": "world-role-delivery.v2"}
    with pytest.raises(KernelError, match="REALITY_CONTEXT_REQUIRED_SOURCE_UNAVAILABLE"):
        PlanningWorldPreparation._task(current, reference, role)
    current["policy"] = {**current["policy"], "context_token_budget": 12000}
    admitted = PlanningWorldPreparation._task(current, reference, role)
    selected = {row["source_event_id"] for row in admitted["context_projection"]["selection"]}
    assert {"hero-state", "world-event"}.issubset(selected)
    assert ("reader-event" in selected) is (role == "DIRECTOR")
    assert PlanningWorldPreparation._task(frozen, reference, role) == legacy


@pytest.mark.parametrize("kind,identity_field", [("reader_promise", "promise_id"), ("foreshadow_state", "thread_id"), ("plot_thread", "thread_id"), ("narrative_obligation", "obligation_id")])
@pytest.mark.parametrize("causal", [False, True])
def test_legacy_commitment_versions_continue_exact_accepted_identity(kind, identity_field, causal):
    from novel_forge.modules.canon_graph.domain import _bind_narrative_entity_versions

    historical = {"narrative_obligation": [
        {"obligation_id": "other:escort", "entity_version": 9},
        {"obligation_id": "hero:escort", "entity_version": 2},
    ]}
    if kind != "narrative_obligation":
        historical[kind] = []
    change = {identity_field: "hero:escort", "status": "OPEN"}
    if causal:
        change.update(causal_batch={"contract_version": "causal-batch-event.v1", "local_id": "continue-escort", "depends_on": []}, story_time={"timeline_id": "main", "start_ordinal": 2, "end_ordinal": 2, "precision": "EXACT", "label": ""})
    changes = {kind: [deepcopy(change)]}
    _bind_narrative_entity_versions(changes, historical)
    assert changes[kind][0]["entity_version"] == 3
    repeated = {kind: [deepcopy(change)]}
    _bind_narrative_entity_versions(repeated, historical)
    assert repeated == changes
    _bind_narrative_entity_versions({kind: [change]}, {kind: [{identity_field: "hero:escort", "entity_version": 4}]})
    assert change["entity_version"] == 5
    unmatched = {identity_field: "new:escort", "status": "OPEN"}
    _bind_narrative_entity_versions({kind: [unmatched]}, historical)
    assert unmatched["entity_version"] == 1


def test_accepted_actor_commitment_rebuild_and_replay_preserve_version_gate():
    from novel_forge.modules.canon_graph.domain import _bind_narrative_entity_versions
    from novel_forge.modules.narrative_state import rebuild_story_state, events_from_chapter_outcome, reduce_story_state_v2
    from tests.unit.test_narrative_state_semantics_v2 import _outcome

    promise = {"character_id": "hero", "promise_id": "hero:escort", "status": "OPEN", "summary": "The witness still needs safe passage", "confidence": 1.0, "coverage": "EXPLICIT", "extraction_evidence": {"excerpt_digest": "sha256:promise"}}
    changes = {"reader_promise": [deepcopy(promise)]}
    _bind_narrative_entity_versions(changes, {})
    first_outcome = _outcome(1, changes)
    first = rebuild_story_state([first_outcome])
    historical = {"narrative_obligation": [{**row, **row["state"]} for row in first["current_state"]["narrative_obligation"]]}
    following = {"reader_promise": [{**promise, "from_status": "OPEN", "summary": "The same escort continues beyond the west corridor"}]}
    _bind_narrative_entity_versions(following, historical)
    second_outcome = _outcome(2, following)
    rebuilt = rebuild_story_state([first_outcome, second_outcome])
    state = rebuilt["current_state"]["narrative_obligation"]
    assert len(state) == 1 and state[0]["entity_version"] == 2
    assert state[0]["state"]["obligation_id"] == "hero:escort"
    assert state[0]["state"]["status"] == "OPEN"
    assert reduce_story_state_v2(previous=rebuilt, events=events_from_chapter_outcome(*second_outcome), chapter_outcome_asset_version_id=second_outcome[0], chapter_outcome_id=second_outcome[1]["chapter_outcome_id"]) == rebuilt
    stale = deepcopy(following)
    stale["reader_promise"][0]["entity_version"] = 1
    with pytest.raises(KernelError, match="NARRATIVE_ENTITY_VERSION_CONFLICT"):
        rebuild_story_state([first_outcome, _outcome(2, stale)])
