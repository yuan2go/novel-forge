from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from novel_forge.modules.command_kernel.budget_runtime import (
    assert_provider_execution_authorized, reserve_provider_budget, resolve_provider_budget_failure, settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration import test_single_book_budget_postgres as support
from tests.unit.test_creative_budget_reallocation import reallocated_policy
from tests.unit.test_single_book_budget_contract import planning_identity, chapter_identity


def test_phase_reallocation_preserves_old_unknown_and_settlement_evidence():
    fixture = support.provider_campaign_fixture()
    project = fixture.projects["A"]
    prior = deepcopy(fixture.policies["A"])
    effects = [fixture.native_effect(planning_identity()) for _ in range(2)]
    reservations = [reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, effect,
        entitlement=index == 1, amount="0.4", tokens=100)) for index, effect in enumerate(effects)]
    resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservations[1]["reservation_id"],
        project_id=project, external_state_unknown=True)
    before = fixture.usage()
    policy = reallocated_policy(prior, before)
    fixture.configure(policy)
    after = fixture.usage()
    assert after["shared_total"] == before["shared_total"]
    assert after["reservation_ids"] == before["reservation_ids"]
    assert after["entitlements"] == before["entitlements"]
    assert after["entitlement_usd"] is None
    assert policy["comparison_budget"]["shared_total"] == prior["comparison_budget"]["shared_total"]
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT status,evidence->'creative_experiment'->>'policy_version' FROM authority_budget_reservation WHERE reservation_id=%s",
            [reservations[1]["reservation_id"]])
        assert uow.cursor.fetchone() == ("HELD_UNKNOWN", prior["policy_version"])
    settle_provider_budget(DATABASE_URL, reservation_id=reservations[0]["reservation_id"], project_id=project,
        actual_amount="0.1", actual_tokens=50, evidence={"fixture": True})
    assert fixture.usage()["shared_total"]["conservative_tokens"] == 150
    assert reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, effects[0],
        amount="0.4", tokens=100))["replayed"]
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture,
            fixture.native_effect(chapter_identity(1)), entitlement=True))


@pytest.mark.parametrize("mutation", ["old_v4", "stale_ledger", "predecessor", "permission", "total"])
def test_native_selection_rejects_unsafe_allocation_and_preserves_selected_policy(mutation):
    fixture = support.provider_campaign_fixture()
    prior = deepcopy(fixture.policies["A"])
    policy = reallocated_policy(prior, fixture.usage())
    if mutation == "old_v4":
        policy["comparison_budget"].update(contract_version=prior["comparison_budget"]["contract_version"])
        policy["comparison_budget"].pop("previous_policy")
        policy["comparison_budget"].pop("reallocation")
    elif mutation == "stale_ledger":
        reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, fixture.native_effect(planning_identity())))
    elif mutation == "predecessor":
        policy["comparison_budget"]["previous_policy"]["policy_hash"] = "f" * 64
    elif mutation == "permission":
        policy["authorization"]["business_scope"]["max_chapter_number"] += 1
        policy["comparison_budget"]["arms"][0]["chapter_ranges"]["PRODUCTION"][1] += 1
    else:
        plan = policy["comparison_budget"]
        plan["shared_total"]["calls"] += 1
        plan["arms"][0]["project_total"]["calls"] += 1
        plan["arms"][0]["reference_allocation"]["calls"] += 1
        policy["authorization"]["authorized_cumulative_caps"]["REFERENCE"]["calls"] += 1
    with pytest.raises(KernelError):
        fixture.configure(policy)
    assert fixture.policies["A"] == prior
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
    assert get_creative_budget(DATABASE_URL, fixture.projects["A"])["budget_binding"]["policy_version"] == prior["policy_version"]


def test_two_reallocations_cannot_both_append_to_same_selected_predecessor():
    fixture = support.provider_campaign_fixture()
    previous = deepcopy(fixture.policies["A"])
    usage = fixture.usage()
    policies = [reallocated_policy(previous, usage, tokens=amount) for amount in (100, 200)]
    for index, policy in enumerate(policies):
        policy["policy_version"] += ":" + str(index)

    def select(policy):
        try:
            fixture.configure(policy)
            return "SUCCEEDED"
        except KernelError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(select, policies)) == ["CREATIVE_BUDGET_REALLOCATION_INVALID", "SUCCEEDED"]


def test_carried_reserved_dispatch_uses_old_lineage_and_current_shared_ceiling():
    fixture = support.provider_campaign_fixture()
    project = fixture.projects["A"]
    previous = deepcopy(fixture.policies["A"])
    old_effects = [fixture.native_effect(planning_identity()) for _ in range(2)]
    old_reservations = [reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture,
        effect, tokens=100, amount="0.1")) for effect in old_effects]
    fixture.configure(reallocated_policy(previous, fixture.usage(), target="DESIGN"))
    new_effect = fixture.native_effect(planning_identity())
    reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, new_effect, tokens=100, amount="0.1"))
    for effect, reservation in zip(old_effects, old_reservations, strict=True):
        assert_provider_execution_authorized(DATABASE_URL, operation_id=effect[0].operation_id,
            external_effect_id=effect[1], project_id=project, budget_reservation_id=reservation["reservation_id"])
    assert fixture.usage()["phases"]["DESIGN"]["calls_used_or_reserved"] == 3
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture,
            fixture.native_effect(planning_identity()), tokens=1, amount="0.01"))
