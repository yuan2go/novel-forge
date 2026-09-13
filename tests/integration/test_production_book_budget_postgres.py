from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import pytest

from novel_forge.modules.command_kernel.budget_runtime import resolve_provider_budget_failure, settle_provider_budget
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import FakeDeterministicProvider
from novel_forge.modules.command_kernel.external_effect_runtime import dispatch_external_effect
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated
from tests.integration.test_single_book_budget_postgres import SingleBookBudget
from tests.unit.test_production_book_budget_contract import production_book_policy
from tests.unit.test_single_book_budget_contract import chapter_identity, planning_identity


@pytest.fixture
def production_budget():
    ensure_migrated()
    fixture = SingleBookBudget()
    fixture.configure()
    return fixture


def test_reallocation_retains_old_reserved_usage_receipt_and_blocks_old_book(production_budget):
    fixture = production_budget
    old_book = fixture.books["A"]
    old_effect = fixture.native_effect(planning_identity())
    request, reservation = fixture.reserve("CREATION", 100, effect=old_effect)
    proof = fixture.proof(reservation)
    policy = production_book_policy(fixture.policies["A"])
    allocation = policy["comparison_budget"]["arms"][0]
    for key in ("calls", "tokens"):
        allocation["creation_late_allocation"][key] += allocation["source_allocation"][key]
        allocation["source_allocation"][key] = 0
    policy["authorization"]["authorized_cumulative_caps"].update(
        SOURCE=deepcopy(allocation["source_allocation"]), CREATION_LATE=deepcopy(allocation["creation_late_allocation"]))
    fixture.configure(policy)
    assert fixture.usage()["project_total"]["conservative_tokens"] == 100
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_SCOPE_MISMATCH"):
        fixture.reserve("CREATION", 1, effect=fixture.native_effect(chapter_identity(1)))
    fixture.books["A"] = policy["authorization"]["book_id"]
    fixture.reserve("CREATION", 100, effect=fixture.native_effect(chapter_identity(13)))
    dispatch_external_effect(DATABASE_URL, old_effect[0], effect_id=old_effect[1], worker_id="creative-budget-fixture",
                             lease_seconds=30, adapter=FakeDeterministicProvider("success"))
    settle_provider_budget(DATABASE_URL, reservation_id=reservation["reservation_id"], project_id=request.project_id,
                           actual_amount=None, actual_tokens=80, evidence={"fixture": True, "real_model_call": False})
    assert fixture.proof(reservation) == proof
    assert proof["authorization"]["book_id"] == old_book
    usage = fixture.usage()
    assert usage["shared_total"]["calls_used_or_reserved"] == 2
    assert usage["shared_total"]["conservative_tokens"] == 180
    assert usage["phases"]["DESIGN"]["recorded_actual_tokens"] == 80


def test_unknown_prior_book_reservation_remains_unavailable_after_reallocation(production_budget):
    fixture = production_budget
    effect = fixture.native_effect(planning_identity(), scenario="timeout_after")
    request, reservation = fixture.reserve("CREATION", 100, effect=effect)
    dispatch_external_effect(DATABASE_URL, effect[0], effect_id=effect[1], worker_id="creative-budget-fixture",
                             lease_seconds=30, adapter=FakeDeterministicProvider("timeout_after"))
    assert resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservation["reservation_id"],
                                           project_id=request.project_id)["status"] == "HELD_UNKNOWN"
    policy = production_book_policy(fixture.policies["A"])
    policy["authorization"]["authorized_cumulative_caps"]["DESIGN"] = {"calls": 1, "tokens": 100}
    fixture.configure(policy)
    fixture.books["A"] = policy["authorization"]["book_id"]
    assert fixture.usage()["phases"]["DESIGN"]["unmeasured_reserved_tokens"] == 100
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        fixture.reserve("CREATION", 1, effect=fixture.native_effect(planning_identity()))


def test_reallocation_cannot_move_reserved_phase_credits_or_restore_old_policy(production_budget):
    fixture = production_budget
    fixture.reserve("CREATION", 100, effect=fixture.native_effect(planning_identity()))
    previous = deepcopy(fixture.policies["A"])
    policy = production_book_policy(previous)
    policy["authorization"]["authorized_cumulative_caps"]["DESIGN"] = {"calls": 0, "tokens": 0}
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_EXHAUSTED"):
        fixture.configure(policy)
    policy = production_book_policy(previous)
    fixture.configure(policy)
    previous["policy_version"] += ":restore"
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_PLAN_IMMUTABLE"):
        fixture.configure(previous)
    assert fixture.usage()["project_total"]["calls_used_or_reserved"] == 1


def test_concurrent_reallocations_only_one_exact_predecessor_wins(production_budget):
    fixture = production_budget
    policies = [production_book_policy(fixture.policies["A"]) for _ in range(2)]
    policies[1]["policy_version"] += ":concurrent"
    policies[1]["comparison_budget"]["arms"][0]["chapter_ranges"] = {"CREATION_EARLY": [1, 15], "CREATION_LATE": [16, 30]}
    policies[1]["authorization"]["business_scope"]["max_chapter_number"] = 30
    def configure(policy):
        try:
            fixture.configure(policy)
            return "SELECTED"
        except KernelError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(configure, policies))
    assert sorted(outcomes) == ["CREATIVE_BUDGET_PREDECESSOR_MISMATCH", "SELECTED"]
