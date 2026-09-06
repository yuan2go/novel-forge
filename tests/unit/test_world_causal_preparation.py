from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS
from tests.unit.test_narrative_reality_causality import reality_state, transition


def generated_paths():
    return json.loads(json.dumps(_generated_paths()))


def _generated_paths():
    target = replace(transition(), actor_id="faction:caravan", epistemic_basis=())
    preparation = replace(
        target, transition_id="gather", requirements=(), changes={"balance": 3}
    )
    return {
        "disposition": "CANDIDATES",
        "reason": "The approved journey requires supplies.",
        "candidates": [
            {
                "transition": asdict(target),
                "affected_entities": ["supply"],
                "world_consequences": ["caravan can depart"],
                "arc_refs": [],
                "obligation_refs": [],
                "risks": [],
                "rationale": "Gather provisions before departure.",
                "soft_assumptions": ["traders will negotiate"],
                "narrative_preferences": ["retain uncertainty"],
                "preparation_paths": [
                    {
                        "path_id": "gather-path",
                        "steps": [
                            {"transition": asdict(preparation), "chapter_offset": 0}
                        ],
                        "rationale": "Acquire provisions.",
                    },
                    {
                        "path_id": "trade-path",
                        "steps": [
                            {
                                "transition": asdict(
                                    replace(preparation, transition_id="trade")
                                ),
                                "chapter_offset": 0,
                            }
                        ],
                        "rationale": "Trade for provisions.",
                    },
                ],
            }
        ],
    }


def evaluation():
    return {
        "evaluations": [
            {
                "transition_id": "departure",
                "dimensions": dict.fromkeys(DIRECTOR_DIMENSIONS, 0.8),
                "rationale": "Preparation supports the goal.",
                "preferred_path_id": "gather-path",
            }
        ]
    }


def test_preparation_uses_accepted_resource_reducer_semantics():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    for path in generated["candidates"][0]["preparation_paths"]:
        path["steps"][0]["transition"]["changes"] = {
            "balance_before": 2,
            "delta": 1,
            "balance_after": 3,
        }
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "PREPARATION_REQUIRED"
    for path in generated["candidates"][0]["preparation_paths"]:
        path["steps"][0]["transition"]["changes"]["balance_before"] = 0
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "BLOCKED"
    assert {path["rejection"]["code"] for path in result["rejected_paths"]} == {
        "NARRATIVE_RESOURCE_BALANCE_INVALID"
    }


def test_world_policy_bounds_projected_time_as_well_as_candidate_count():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    generated["candidates"][0]["transition"]["story_time"].update(
        start_ordinal=100_000, end_ordinal=100_000
    )
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "BLOCKED"
    assert (
        result["candidate_futures"][0]["rejection"]["code"]
        == "WORLD_PRODUCTION_TIME_BOUND"
    )


def test_generated_preparation_is_selected_but_only_actual_support_discharges_debt():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    reality = reality_state()
    before = deepcopy(reality)
    result = compile_world_plan(
        reality=reality,
        generated=generated_paths(),
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "PREPARATION_REQUIRED"
    assert result["selected_path_id"] == "gather-path"
    assert len(result["causal_debts"]) == 1
    assert result["causal_debts"][0]["status"] == "PREPARATION_REQUIRED"
    assert result["preparation_schedule"][0]["chapter_number"] == 2
    assert result["alternative_paths"][0]["path_id"] == "trade-path"
    assert reality == before
    reality["current_state"]["resource_state"][0]["state"]["balance"] = 3
    reality["current_state"]["resource_state"][0]["source_event_id"] = "accepted:gather"
    reality["events"].append({"event_id": "event:supply"})
    result = compile_world_plan(
        reality=reality,
        generated=generated_paths(),
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "ELIGIBLE"
    assert result["causal_debts"][0]["discharge_evidence"] == "accepted:gather"


def test_failed_preparation_cannot_be_outscored_or_silently_repaired():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    for path in generated["candidates"][0]["preparation_paths"]:
        path["steps"][0]["transition"]["changes"]["balance"] = -1
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "BLOCKED"
    assert not result["preparation_schedule"]
    assert all(
        path["rejection"]["code"] == "WORLD_QUANTITY_INVALID"
        for path in result["rejected_paths"]
    )


@pytest.mark.parametrize("disposition", ["NO_OP", "DEFER"])
def test_no_world_event_is_a_reasoned_durable_planning_result(disposition):
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    result = compile_world_plan(
        reality=reality_state(),
        generated={
            "disposition": disposition,
            "reason": "No active pressure requires a transition in this window.",
            "candidates": [],
        },
        evaluation={"evaluations": []},
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == disposition
    assert not result["causal_debts"]
    assert not result["selected_candidate_id"]


def test_generation_bound_and_unknown_director_references_fail_closed():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    generated["candidates"] *= 5
    with pytest.raises(KernelError) as error:
        compile_world_plan(
            reality=reality_state(),
            generated=generated,
            evaluation=evaluation(),
            policy=WorldProductionPolicy(),
            chapter_number=2,
            intent_version_id="intent:1",
        )
    assert error.value.code == "WORLD_GENERATION_BOUND_EXCEEDED"
    judged = evaluation()
    judged["evaluations"][0]["transition_id"] = "invented"
    with pytest.raises(KernelError) as error:
        compile_world_plan(
            reality=reality_state(),
            generated=generated_paths(),
            evaluation=judged,
            policy=WorldProductionPolicy(),
            chapter_number=2,
            intent_version_id="intent:1",
        )
    assert error.value.code == "WORLD_DIRECTOR_REFERENCE_INVALID"


def test_complete_world_task_respects_frozen_budget_not_only_state_selection():
    from novel_forge.modules.story_planning_runtime.world_preparation import (
        PlanningProviderStage,
    )

    with pytest.raises(KernelError, match="WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        PlanningProviderStage(
            "world_candidates.generate",
            {
                "contract_version": "world-provider-task.v1",
                "fact_mutation_allowed": False,
                "role": "WORLD_REASONER",
                "policy": {"context_token_budget": 100},
                "world_foundation": {"approved_history": "x" * 4000},
            },
            {},
        )


def test_duplicate_preparation_event_names_are_rejected_before_chapter_planning():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    paths = generated["candidates"][0]["preparation_paths"]
    paths[:] = paths[:1]
    paths[0]["steps"].append(deepcopy(paths[0]["steps"][0]))
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "BLOCKED"
    assert (
        result["rejected_paths"][0]["rejection"]["code"]
        == "WORLD_PREPARATION_IDENTITY_COLLISION"
    )


def test_local_goal_support_requires_validated_own_preparation_path():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    generated["candidates"][0]["transition"]["cause_refs"] = ["local:gather"]
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "PREPARATION_REQUIRED"
    assert result["selected_path_id"] == "gather-path"
    assert result["preparation_schedule"][0]["transition"]["transition_id"] == "gather"
    assert result["causal_debts"][0]["status"] == "PREPARATION_REQUIRED"
    assert result["causal_debts"][0]["discharge_evidence"] == ""
    assert result["rejected_paths"][0]["path_id"] == "trade-path"
    assert (
        result["rejected_paths"][0]["rejection"]["code"]
        == "WORLD_BATCH_REFERENCE_UNKNOWN"
    )


@pytest.mark.parametrize(
    "bad_ref", ["event:invented", "local:foreign-path", "local:departure"]
)
def test_preparation_cannot_legitimize_unknown_or_cyclic_target_sources(bad_ref):
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    generated["candidates"][0]["transition"]["cause_refs"] = [bad_ref]
    result = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert result["disposition"] == "BLOCKED"
    assert not result["preparation_schedule"]


def test_preparation_topology_is_independent_of_provider_array_order():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    target = generated["candidates"][0]
    target["preparation_paths"] = target["preparation_paths"][:1]
    path = target["preparation_paths"][0]
    first = path["steps"][0]
    first["transition"]["story_time"].update(start_ordinal=11, end_ordinal=11)
    second = deepcopy(first)
    second["transition"].update(transition_id="pack", cause_refs=["local:gather"])
    second["transition"]["story_time"].update(start_ordinal=12, end_ordinal=12)
    second["chapter_offset"] = 1
    path["steps"].append(second)
    target["transition"]["cause_refs"] = ["local:pack"]
    options = dict(
        reality=reality_state(),
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    ordered = compile_world_plan(generated=generated, **options)
    assert ordered["disposition"] == "PREPARATION_REQUIRED"
    before = deepcopy(generated)
    path["steps"].reverse()
    shuffled = compile_world_plan(generated=generated, **options)
    assert shuffled["preparation_schedule"] == ordered["preparation_schedule"]
    assert before["candidates"][0]["preparation_paths"][0]["steps"] == list(
        reversed(path["steps"])
    )
