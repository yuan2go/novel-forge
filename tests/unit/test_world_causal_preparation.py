from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.hierarchical_planning.causal_domain import DIRECTOR_DIMENSIONS
from tests.unit.test_narrative_reality_causality import reality_state, transition


def generated_paths():
    return json.loads(json.dumps(_generated_paths()))


def test_serialized_world_contract_exposes_native_time_and_causal_predicates():
    from novel_forge.modules.chapter_authority.provider_output_contracts import (
        validate_native_world_schema_fragment,
    )
    from novel_forge.modules.worldbuilding.production_schema import (
        decode_world_generation,
        world_transition_schema,
    )

    schema = world_transition_schema()

    def validate(value):
        return validate_native_world_schema_fragment(
            "world_candidates.generate",
            schema,
            value,
            output_schema_ref="schema:world_candidates.generate:v1",
        )

    raw = generated_paths()
    for candidate in raw["candidates"]:
        validate(candidate["transition"])
        candidate["transition"] = {"payload_json": json.dumps(candidate["transition"])}
        for path in candidate["preparation_paths"]:
            for step in path["steps"]:
                validate(step["transition"])
                step["transition"] = {"payload_json": json.dumps(step["transition"])}
    assert decode_world_generation(raw) == generated_paths()
    invalid = generated_paths()["candidates"][0]["transition"]
    invalid["story_time"] = "chapter:1"
    with pytest.raises(KernelError, match="WORLD_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate(invalid)
    raw["candidates"][0]["transition"]["payload_json"] = json.dumps(invalid)
    with pytest.raises(
        KernelError, match=r"\$\.candidates\[0\]\.transition.payload_json"
    ):
        decode_world_generation(raw)


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


def test_continuation_never_treats_plan_success_as_accepted_completion():
    from novel_forge.modules.worldbuilding.continuation import decide_preparation
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    original = compile_world_plan(
        reality=reality_state(),
        generated=generated_paths(),
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    origin = {
        "asset_version_id": "action:original",
        "content_hash": "sha256:origin",
        "action": {"world_plan": original},
    }
    reality = reality_state()
    due = decide_preparation(
        reality=reality,
        origin=origin,
        accepted_steps={},
        chapter_number=3,
        intent_version_id="intent:1",
    )
    assert due["status"] == "EXECUTE" and not due["execute_target"]
    assert due["due_transitions"][0]["transition_id"] == "gather"
    unsupported = decide_preparation(
        reality=reality,
        origin=origin,
        accepted_steps={"gather": "accepted:gather"},
        chapter_number=3,
        intent_version_id="intent:1",
    )
    assert unsupported["status"] == "WAIT_PRECONDITION"
    assert not unsupported["due_transitions"]
    retired = decide_preparation(
        reality=reality,
        origin=origin,
        accepted_steps={},
        chapter_number=3,
        intent_version_id="intent:replacement",
    )
    assert (
        retired["status"] == "CANCEL"
        and retired["reason"] == "APPROVED_INTENT_REPLACED"
    )
    assert not retired["accepted_step_mapping"]
    expired = decide_preparation(
        reality=reality,
        origin=origin,
        accepted_steps={},
        chapter_number=6,
        intent_version_id="intent:1",
    )
    assert (
        expired["status"] == "CANCEL"
        and expired["reason"] == "PREPARATION_WINDOW_EXPIRED"
    )
    completed = decide_preparation(
        reality=reality,
        origin=origin,
        accepted_steps={"departure": "accepted:goal"},
        chapter_number=3,
        intent_version_id="intent:replacement",
    )
    assert completed["status"] == "COMPLETE"
    assert completed["accepted_step_mapping"] == {"departure": "accepted:goal"}
    assert original["chapter_number"] == 2


def test_disclosure_resolves_an_accepted_occurrence_after_current_state_moves_on():
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    reality = reality_state()
    reality["chapter_number"] = 3
    reality["current_state"]["world_state"] = [
        {
            "entity_key": "world_state_id=decree",
            "source_event_id": "event:E2",
            "state": {"world_state_id": "decree", "status": "SUPERSEDED"},
        }
    ]
    reality["events"].append(
        {
            "event_id": "event:E1",
            "scope": {"project_id": "project", "book_id": "book"},
            "state_kind": "world_state",
            "identity": {"entity_key": "world_state_id=decree"},
            "mutation": {
                "payload": {
                    "world_state_id": "decree",
                    "status": "ISSUED",
                    "fact_origin": {
                        "kind": "GOVERNED_BACKGROUND",
                        "private_rationale": "secret motive",
                    },
                }
            },
            "coordinate": {"source_chapter": 1},
            "provenance": {"chapter_outcome_id": "accepted:1"},
        }
    )
    generated = generated_paths()
    item = generated["candidates"][0]
    item["preparation_paths"] = []
    item["transition"].update(
        state_kind="disclosure_event",
        entity_key="disclosure_id=old-decree",
        requirements=[],
        cause_refs=["event:E1"],
        changes={
            "disclosure_id": "old-decree",
            "fact_id": "event:E1",
            "audience": "READER",
            "disclosure_mode": "CONFIRM",
        },
    )
    item["information_scope"] = {
        "reader_exposure": "REVEAL",
        "reveal_event_ids": ["event:E1"],
    }
    judged = evaluation()
    judged["evaluations"][0]["preferred_path_id"] = ""
    result = compile_world_plan(
        reality=reality,
        generated=generated,
        evaluation=judged,
        policy=WorldProductionPolicy(),
        chapter_number=4,
        intent_version_id="intent:1",
    )
    disclosure = result["disclosure_projection"][0]
    assert disclosure["fact_id"] == "event:E1"
    assert disclosure["source"]["state"]["status"] == "ISSUED"
    assert "secret motive" not in json.dumps(disclosure)
    assert reality["current_state"]["world_state"][0]["source_event_id"] == "event:E2"


@pytest.mark.parametrize(
    "audience,mode",
    [
        ("READER", "PARTIAL"),
        ("hero", "CONFIRM"),
        ("READER", "MISDIRECT"),
        ("READER", "WITHHOLD"),
    ],
)
def test_disclosure_projection_exposes_only_the_requested_audience_fields(
    audience, mode
):
    from novel_forge.modules.narrative_state.information import project_disclosure

    reality = reality_state()
    reality["approved_character_ids"] = ["hero"]
    reality["current_state"]["world_state"] = [
        {
            "entity_key": "world_state_id=decree",
            "source_event_id": "event:E1",
            "state": {
                "status": "ISSUED",
                "secret": "The council hid the heir.",
                "fact_origin": {
                    "kind": "GOVERNED_BACKGROUND",
                    "cause": "hidden motive",
                },
            },
        }
    ]
    result = project_disclosure(
        reality,
        {
            "disclosure_id": "notice",
            "event_id": "event:E1",
            "audience": audience,
            "mode": mode,
            "fields": [] if mode == "WITHHOLD" else ["status"],
            "presentation_channel": "LETTER",
            "claim_kind": "CURRENT_ASSERTION",
        },
    )
    assert result["audience"] == audience and result["mode"] == mode
    assert "secret" not in json.dumps(result) and "hidden motive" not in json.dumps(
        result
    )
    if audience != "READER" or mode == "WITHHOLD":
        assert not result["source"].get("state")
    else:
        assert result["source"]["state"] == {"status": "ISSUED"}
    assert not reality["current_state"].get("reader_knowledge")


def test_continuation_reuses_an_exact_accepted_effect_without_reexecuting_a_step():
    from novel_forge.modules.worldbuilding.continuation import decide_preparation
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    generated["candidates"][0]["transition"]["cause_refs"] = ["local:gather"]
    original = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    reality = reality_state()
    resource = reality["current_state"]["resource_state"][0]
    resource["state"]["balance"] = 3
    resource["source_event_id"] = "accepted:other-supplier"
    decision = decide_preparation(
        reality=reality,
        origin={
            "asset_version_id": "action:original",
            "content_hash": "sha256:original",
            "action": {"world_plan": original},
        },
        accepted_steps={},
        chapter_number=3,
        intent_version_id="intent:1",
    )
    assert decision["status"] == "EXECUTE" and decision["execute_target"]
    assert decision["due_transitions"][0]["cause_refs"] == ["accepted:other-supplier"]
    assert decision["accepted_step_mapping"] == {}
    assert (
        decision["reused_effect_evidence"]["gather"]["event_id"]
        == "accepted:other-supplier"
    )
    assert original["preparation_schedule"][0]["status"] == "PLANNED_NOT_ACCEPTED"


@pytest.mark.parametrize("fault", ["reordered", "cycle", "unordered_write"])
def test_due_preparation_revalidates_the_same_batch_graph(fault):
    from novel_forge.modules.worldbuilding.continuation import decide_preparation
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan,
        WorldProductionPolicy,
    )

    generated = generated_paths()
    candidate = generated["candidates"][0]
    candidate["preparation_paths"] = candidate["preparation_paths"][:1]
    path = candidate["preparation_paths"][0]
    first = path["steps"][0]
    first["transition"]["story_time"].update(start_ordinal=11, end_ordinal=11)
    second = deepcopy(first)
    second["transition"].update(
        transition_id="pack", cause_refs=["local:gather"], changes={"balance": 4}
    )
    second["transition"]["story_time"].update(start_ordinal=12, end_ordinal=12)
    path["steps"].append(second)
    candidate["transition"]["cause_refs"] = ["local:pack"]
    plan = compile_world_plan(
        reality=reality_state(),
        generated=generated,
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=2,
        intent_version_id="intent:1",
    )
    assert plan["disposition"] == "PREPARATION_REQUIRED"
    if fault == "reordered":
        plan["preparation_schedule"].reverse()
    elif fault == "cycle":
        plan["preparation_schedule"][0]["transition"]["cause_refs"] = ["local:pack"]
    else:
        plan["preparation_schedule"][1]["transition"]["cause_refs"] = ["event:supply"]
    result = decide_preparation(
        reality=reality_state(),
        origin={
            "asset_version_id": "action:original",
            "content_hash": "sha256:original",
            "action": {"world_plan": plan},
        },
        accepted_steps={},
        chapter_number=3,
        intent_version_id="intent:1",
    )
    if fault == "reordered":
        assert result["status"] == "EXECUTE", result
        assert [row["transition_id"] for row in result["due_transitions"]] == [
            "gather",
            "pack",
        ]
    else:
        assert result["status"] == "BLOCKED", result
        assert (
            result["reason"]
            == {
                "cycle": "WORLD_BATCH_CAUSAL_CYCLE",
                "unordered_write": "WORLD_BATCH_CONCURRENT_WRITE",
            }[fault]
        )
        assert result["due_transitions"] == []


@pytest.mark.parametrize(
    "fault,code",
    [
        ("future", "WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID"),
        ("book", "WORLD_DISCLOSURE_SOURCE_SCOPE_INVALID"),
        ("unknown", "WORLD_DISCLOSURE_SOURCE_UNKNOWN"),
        ("assertion", "WORLD_DISCLOSURE_ASSERTION_STALE"),
        ("private", "WORLD_DISCLOSURE_FIELDS_INVALID"),
        ("audience", "WORLD_DISCLOSURE_AUDIENCE_INVALID"),
    ],
)
def test_historical_disclosure_rejects_inexact_or_overbroad_claims(fault, code):
    from novel_forge.modules.narrative_state.information import project_disclosure

    reality = reality_state()
    event = {
        "event_id": "event:E1",
        "scope": {"project_id": "project", "book_id": "book"},
        "coordinate": {"source_chapter": 1},
        "state_kind": "world_state",
        "identity": {"entity_key": "world_state_id=decree"},
        "mutation": {
            "payload": {"status": "ISSUED", "rationale": "private explanation"}
        },
    }
    reality["events"].append(event)
    row = {
        "disclosure_id": "notice",
        "event_id": "event:E1",
        "audience": "READER",
        "mode": "PARTIAL",
        "fields": ["status"],
        "presentation_channel": "LETTER",
        "claim_kind": "HISTORICAL_OCCURRENCE",
    }
    if fault == "future":
        event["coordinate"]["source_chapter"] = 2
    elif fault == "book":
        event["scope"]["book_id"] = "other-book"
    elif fault == "unknown":
        row["event_id"] = "event:invented"
    elif fault == "assertion":
        row["claim_kind"] = "CURRENT_ASSERTION"
    elif fault == "private":
        row["fields"] = ["rationale"]
    else:
        row["audience"] = "ALL"
    before = deepcopy(reality)
    with pytest.raises(KernelError) as caught:
        project_disclosure(reality, row)
    assert caught.value.code == code
    assert reality == before


@pytest.mark.parametrize("mode", ["MISDIRECT", "WITHHOLD"])
def test_misleading_character_presentation_cannot_smuggle_known_truth(mode):
    from novel_forge.modules.canon_graph.disclosure import bind_disclosure_policy

    reality = reality_state()
    reality["events"].append(
        {
            "event_id": "secret",
            "mutation": {"payload": {"fact_origin": {"kind": "GOVERNED_BACKGROUND"}}},
        }
    )
    policy = {
        "disclosure_id": "message",
        "fact_id": "secret",
        "audience": "hero",
        "mode": mode,
        "presentation_channel": "LETTER",
        "permitted_fields": [],
        "claim_kind": "HISTORICAL_OCCURRENCE",
        "source": {"state": {}},
    }
    extraction = {
        "disclosure_events": [
            {
                "disclosure_id": "message",
                "fact_id": "secret",
                "audience": "hero",
                "disclosure_mode": mode,
                "presentation_channel": "LETTER",
            }
        ],
        "character_knowledge_changes": [
            {"character_id": "hero", "fact_id": "secret", "status": "KNOWN"}
        ],
    }
    with pytest.raises(KernelError) as caught:
        bind_disclosure_policy(
            extraction,
            {
                "asset_version_id": "action",
                "content_hash": "sha256:action",
                "action": {
                    "contract_version": "world-production-action.v2",
                    "world_plan": {"disclosure_projection": [policy]},
                },
                "frozen_source": {"reality": reality},
            },
        )
    assert caught.value.code == "WORLD_KNOWLEDGE_DISCLOSURE_DRIFT"


def test_professional_card_translation_changes_native_world_resource_feasibility():
    from novel_forge.modules.mkaos_authority.domain import (
        NarrativeIntelligenceNeed, select_narrative_intelligence,
    )
    from novel_forge.modules.story_planning_runtime.knowledge_translation import (
        validate_knowledge_translations,
    )
    from novel_forge.modules.worldbuilding.production_planning import (
        compile_world_plan, WorldProductionPolicy,
    )
    from tests.unit.test_mkaos_authority_domain import _planning_card

    card = _planning_card(0)
    abstract = card["content"]["abstract_content"]
    abstract.pop("applicability")
    abstract.pop("failure_conditions")
    abstract.update(
        knowledge_kind="DOMAIN_INTELLIGENCE",
        semantic_family="PROFESSIONAL_CAUSAL_MECHANISM",
        discipline="resource_planning",
        mechanism="Spend two supply units on travel while retaining one emergency unit.",
        applicability_contract={
            "schema_version": "knowledge-applicability.v1",
            "usage_role": "MECHANISM",
            "prerequisites": [{
                "condition_id": "emergency-reserve",
                "path": "/story_state/current_state/resource_state/0/state/balance",
                "operator": "GTE", "value": 3,
            }],
            "exceptions": [], "hard_conflicts": [],
        },
    )
    generated = generated_paths()
    generated["candidates"][0]["transition"]["action"] = abstract["mechanism"]
    generated["candidates"][0]["transition"]["requirements"][0]["value"] = abstract["applicability_contract"]["prerequisites"][0]["value"]
    generated["knowledge_translations"] = [{
        "knowledge_card_asset_version_id": card["asset_version_id"],
        "content_hash": card["content_hash"],
        "decision": "ADAPT", "usage_role": "MECHANISM",
        "rationale": "Freeze the reserve threshold and travel expense in the causal transition.",
        "prerequisite_resolution": "Check accepted stock; if below three, gather supplies before departure.",
        "use_sites": [{
            "target_pointer": "/candidates/0/transition/action",
            "realization_excerpt": abstract["mechanism"],
            "expected_application": "The typed supplies requirement is three and the post-travel balance is one.",
            "preservation_requirements": ["Retain one supply unit after departure."],
            "verification_checks": ["Departure cannot precede accepted preparation when stock is insufficient."],
        }],
    }]
    for reserve, expected_assessment, expected_disposition in (
        (3, "APPLICABLE", "ELIGIBLE"),
        (2, "CONDITIONAL", "PREPARATION_REQUIRED"),
    ):
        reality = reality_state()
        reality["current_state"]["resource_state"][0]["state"]["balance"] = reserve
        before = deepcopy(reality)
        selection = select_narrative_intelligence(NarrativeIntelligenceNeed(
            scope="CHAPTER", target_stage="chapter_plan.generate",
            condition_sources={"story_state": {
                "asset_version_id": f"accepted-stock:{reserve}",
                "content_hash": "sha256:" + str(reserve) * 64,
                "content": reality,
            }},
        ), (card,))
        assert selection["selected"][0]["applicability_assessment"]["status"] == expected_assessment
        validate_knowledge_translations(generated, selection)
        decoded = {key: value for key, value in generated.items() if key != "knowledge_translations"}
        result = compile_world_plan(
            reality=reality, generated=decoded, evaluation=evaluation(),
            policy=WorldProductionPolicy(), chapter_number=2,
            intent_version_id="intent:professional-reserve",
        )
        assert result["disposition"] == expected_disposition
        assert result["authority"] == "PLANNING_PROPOSAL"
        assert result["fact_mutation_allowed"] is False
        assert reality == before
        if reserve == 2:
            assert result["causal_debts"][0]["status"] == "PREPARATION_REQUIRED"
            assert result["selected_path_id"] == "gather-path"
            assert result["preparation_schedule"][0]["chapter_number"] == 2
            without_preparation = deepcopy(decoded)
            without_preparation["candidates"][0]["preparation_paths"] = []
            no_path_evaluation = evaluation()
            no_path_evaluation["evaluations"][0]["preferred_path_id"] = ""
            assert compile_world_plan(
                reality=reality, generated=without_preparation,
                evaluation=no_path_evaluation, policy=WorldProductionPolicy(),
                chapter_number=2, intent_version_id="intent:professional-reserve",
            )["disposition"] == "BLOCKED"


@pytest.mark.parametrize("field", ["affected_entities", "world_consequences"])
def test_retained_world_candidate_missing_required_evidence_is_diagnosable_before_director(
    field,
):
    from novel_forge.modules.worldbuilding.production_planning import (
        WorldProductionPolicy,
        validate_generated_candidates,
    )

    raw = generated_paths()
    raw["candidates"][0][field] = []
    with pytest.raises(
        KernelError, match="WORLD_GENERATION_CANDIDATE_EVIDENCE_INVALID"
    ):
        validate_generated_candidates(raw, WorldProductionPolicy())


def test_world_provider_delivers_typed_nested_payload_without_normalizing_invalid_fields():
    from novel_forge.modules.command_kernel.service import _validate_json_schema as validate
    from novel_forge.modules.worldbuilding.production_schema import world_transition_payload_schema, decode_world_generation
    from novel_forge.modules.worldbuilding.dynamics import WorldTransition

    payload = generated_paths()["candidates"][0]["transition"]
    schema = world_transition_payload_schema()
    validate(schema, payload)
    WorldTransition.from_mapping(payload)
    for key, invalid in [("story_time", "chapter:1:morning"), ("epistemic_basis", "Observed directly"), ("requirements", "Supplies exist")]:
        damaged = {**payload, key: invalid}
        with pytest.raises(KernelError):
            validate(schema, damaged)
        with pytest.raises(KernelError, match="WORLD_PROVIDER_TRANSITION_INVALID"):
            decode_world_generation({"candidates": [{"transition": {"payload_json": json.dumps(damaged)}, "preparation_paths": []}]})


def test_world_reference_contract_uses_selected_arcs_and_accepted_obligations_only():
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation, world_plan_references
    from novel_forge.modules.worldbuilding.production_schema import world_generation_schema
    from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy

    source = {"entity_ids": ["faction:caravan", "supply"], "reality": {"current_state": {
        "narrative_obligation": [{"state": {"obligation_id": "accepted:obligation"}}]}}}
    command = SimpleNamespace(input_versions={"arc_plans": "selected:arc"},
        related_arc_plan_version_ids=("selected:character-arc",))
    refs = world_plan_references(source, command)
    assert refs == {"arc_refs": ["selected:arc", "selected:character-arc"], "obligation_refs": ["accepted:obligation"]}
    properties = world_generation_schema(WorldProductionPolicy(),
        **{key: tuple(value) for key, value in refs.items()})["properties"]["candidates"]["items"]["properties"]
    for key in refs:
        assert properties[key]["items"]["enum"] == refs[key]
        assert properties[key]["maxItems"] == len(refs[key])
    empty = world_generation_schema(WorldProductionPolicy(), arc_refs=(), obligation_refs=())["properties"]["candidates"]["items"]["properties"]
    assert empty["obligation_refs"]["maxItems"] == 0
    candidates = generated_paths()["candidates"]
    candidates[0]["arc_refs"] = refs["arc_refs"]
    PlanningWorldPreparation._validate_references(source, candidates, command)
    candidates[0]["arc_refs"].append("visible-but-unselected:arc")
    with pytest.raises(KernelError, match="WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN"):
        PlanningWorldPreparation._validate_references(source, candidates, command)


def test_retained_blocked_world_plan_preserves_exact_json_identity_after_storage():
    from novel_forge.modules.story_planning_runtime.world_preparation import require_exact_blocked_plan, blocked_candidate_diagnostic
    from novel_forge.modules.worldbuilding.production_planning import compile_world_plan, WorldProductionPolicy

    generated = generated_paths()
    generated["candidates"][0]["preparation_paths"] = []
    judged = evaluation()
    judged["evaluations"][0]["preferred_path_id"] = ""
    plan = compile_world_plan(reality=reality_state(), generated=generated, evaluation=judged,
        policy=WorldProductionPolicy(), chapter_number=2, intent_version_id="intent:v1")
    assert plan["disposition"] == "BLOCKED"
    candidate = plan["candidate_futures"][0]
    assert "transition_id" not in candidate
    diagnosis = blocked_candidate_diagnostic(candidate)
    assert diagnosis["transition_id"] == candidate["transition"]["transition_id"]
    assert diagnosis["unmet_requirements"] == [dict(item) for item in candidate["requirements"] if not item["satisfied"]]
    assert diagnosis["unmet_requirements"]
    stored = json.loads(json.dumps(plan))
    assert plan != stored
    require_exact_blocked_plan(plan, stored)
    stored["candidate_futures"][0]["requirements"][0]["value"] += 1
    with pytest.raises(KernelError, match="WORLD_REPAIR_CAUSAL_DIAGNOSTIC_DRIFT"):
        require_exact_blocked_plan(plan, stored)


def test_legacy_rejection_and_typed_transition_cannot_conflict_in_diagnostic():
    from novel_forge.modules.story_planning_runtime.world_preparation import blocked_candidate_diagnostic
    rejection = {"code": "WORLD_REALITY_CAUSE_UNKNOWN", "message": "Unknown cause"}
    assert blocked_candidate_diagnostic({"transition_id": "proposal", "rejection": rejection}) == {"transition_id": "proposal", "rejection": rejection}
    with pytest.raises(KernelError, match="WORLD_REPAIR_CAUSAL_DIAGNOSTIC_DRIFT"):
        blocked_candidate_diagnostic({"transition_id": "proposal", "transition": {"transition_id": "different"}})


@pytest.mark.parametrize('fault', ['none', 'missing_document', 'missing_receipt', 'different_output', 'different_source'])
def test_isolated_world_sibling_requires_original_success_and_source(monkeypatch, fault):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.world_preparation import PlanningWorldPreparation
    from novel_forge.modules.command_kernel import external_effect_runtime

    source = {'asset_version_id':'source:1', 'content_hash':'sha256:source'}
    document = SimpleNamespace(asset_version_id='generation:1', content={'contract':{
        'source':source if fault != 'different_source' else {'asset_version_id':'other-book'},
        'output':{'disposition':'NO_OP'}, 'evidence':{'external_receipt_ref':'effect:original'},
    }})
    receipt = None if fault == 'missing_receipt' else {'provider_evidence':{
        'result':{'disposition':'NO_OP'} if fault != 'different_output' else {'disposition':'DEFER'},
    }, 'budget_reservation_status':'HELD_UNKNOWN'}
    monkeypatch.setattr(external_effect_runtime, 'read_retained_generation_stage_success', lambda *args, **kwargs: receipt)
    preparer = PlanningWorldPreparation(SimpleNamespace(database_url='controlled-test'))
    monkeypatch.setattr(preparer, '_read', lambda *args: None if fault == 'missing_document' else document)
    monkeypatch.setattr(preparer, '_source_operation', lambda *args: 'original-operation')
    command = SimpleNamespace(project_id='project:1', actor_id='author:1', trace_id='trace', correlation_id='book:1')
    if fault in {'missing_receipt', 'different_output', 'different_source'}:
        with pytest.raises(KernelError, match='WORLD_ISOLATED_RECEIPT_INVALID'):
            preparer._read_known_isolated_stage(command, ['world_preparation/original-operation'], 'generation', source)
    else:
        assert preparer._read_known_isolated_stage(command, ['world_preparation/original-operation'], 'generation', source) is (None if fault == 'missing_document' else document)
