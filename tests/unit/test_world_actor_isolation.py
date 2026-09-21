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
