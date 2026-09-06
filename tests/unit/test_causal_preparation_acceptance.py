from copy import deepcopy

from novel_forge.modules.worldbuilding.production_planning import (
    compile_world_plan,
    WorldProductionPolicy,
)
from tests.unit.test_world_causal_preparation import generated_paths, evaluation
from tests.unit.test_narrative_reality_causality import reality_state


def binding(reality):
    plan = compile_world_plan(
        reality=reality,
        generated=generated_paths(),
        evaluation=evaluation(),
        policy=WorldProductionPolicy(),
        chapter_number=3,
        intent_version_id="intent",
    )
    return {
        "asset_version_id": "action",
        "content_hash": "sha256:" + "a" * 64,
        "action": {"world_plan": plan},
        "frozen_source": {"reality": reality},
    }


def test_selected_preparation_is_accepted_open_and_only_accepted_evidence_closes_it():
    from novel_forge.modules.canon_graph.causal_preparation import (
        preparation_observations,
    )

    reality = reality_state()
    planned = binding(reality)
    observations = preparation_observations(planned)
    assert len(observations) == 1
    obligation = observations[0]
    assert obligation["status"] == "OPEN"
    assert obligation["payoff_evidence"] == {}
    assert obligation["causal_plan_asset_version_id"] == "action"
    assert not reality["current_state"].get("narrative_obligation")
    accepted = deepcopy(reality)
    accepted["current_state"]["narrative_obligation"] = [{"state": obligation}]
    assert preparation_observations(binding(accepted)) == []
    source = accepted["current_state"]["resource_state"][0]
    source["state"]["balance"] = 3
    source["source_event_id"] = "actual:received-supplies"
    source["provenance"] = {"accepted_draft_asset_version_id": "chapter-outcome-draft"}
    paid = preparation_observations(binding(accepted))
    assert len(paid) == 1
    assert paid[0]["status"] == "FULFILLED"
    assert paid[0]["causal_plan_asset_version_id"] == "action"
    assert paid[0]["payoff_evidence"] == {
        "event_id": "actual:received-supplies",
        "asset_version_id": "chapter-outcome-draft",
        "evidence_mode": "ACCEPTED_REALITY_PREDICATE",
    }
    assert obligation["status"] == "OPEN"


def test_changed_approved_intent_retires_only_unfulfilled_preparation():
    from novel_forge.modules.canon_graph.causal_preparation import (
        preparation_observations,
    )

    reality = reality_state()
    original = preparation_observations(binding(reality))[0]
    accepted = deepcopy(reality)
    accepted["current_state"]["narrative_obligation"] = [{"state": original}]
    replacement = binding(accepted)
    replacement["action"]["world_plan"].update(
        intent_version_id="approved-new-intent", causal_debts=[]
    )
    retired = preparation_observations(replacement)
    assert retired[0]["status"] == "CANCELLED"
    assert (
        retired[0]["causal_plan_asset_version_id"]
        == original["causal_plan_asset_version_id"]
    )
    assert (
        retired[0]["retirement_evidence"]["intent_version_id"] == "approved-new-intent"
    )
    assert original["status"] == "OPEN"


def test_expired_unexecuted_preparation_requires_replanning_not_false_repayment():
    from novel_forge.modules.canon_graph.causal_preparation import (
        preparation_observations,
    )

    reality = reality_state()
    original = preparation_observations(binding(reality))[0]
    reality["current_state"]["narrative_obligation"] = [{"state": original}]
    next_binding = binding(reality)
    next_binding["action"]["world_plan"].update(
        chapter_number=original["target_window"]["to_chapter"] + 1, causal_debts=[]
    )
    update = preparation_observations(next_binding)
    assert len(update) == 1
    assert update[0]["status"] == "CANCELLED"
    assert update[0]["payoff_evidence"] == {}
    assert update[0]["retirement_evidence"]["reason"] == "PREPARATION_WINDOW_EXPIRED"
    assert original["status"] == "OPEN"


def test_new_preparation_after_expiry_has_a_new_commitment_identity():
    from novel_forge.modules.canon_graph.causal_preparation import (
        preparation_observations,
    )

    reality = reality_state()
    original = preparation_observations(binding(reality))[0]
    original["status"] = "CANCELLED"
    reality["current_state"]["narrative_obligation"] = [
        {
            "entity_key": "obligation_id=" + original["obligation_id"],
            "source_event_id": "accepted-expiry",
            "state": original,
        }
    ]
    renewed = preparation_observations(binding(reality))
    assert len(renewed) == 1 and renewed[0]["status"] == "OPEN"
    assert renewed[0]["obligation_id"] != original["obligation_id"]
    assert original["status"] == "CANCELLED"
