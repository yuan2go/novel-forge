"""Native PostgreSQL budget transactions; fixture Effects never invoke a real model."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal

import pytest

from novel_forge.modules.command_kernel.budget_runtime import (
    assert_provider_execution_authorized, reserve_provider_budget,
    resolve_provider_budget_failure, settle_provider_budget,
)
from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration import test_single_book_budget_postgres as support
from tests.unit.test_creative_budget_renewal import renewed_policy
from tests.unit.test_single_book_budget_contract import chapter_identity, planning_identity


def test_renewal_preserves_unknown_and_bounds_new_money_tokens_and_entitlement():
    fixture = support.provider_campaign_fixture()
    project = fixture.projects["A"]
    prior = deepcopy(fixture.policies["A"])
    old_effects = [fixture.native_effect(planning_identity()) for _ in range(2)]
    reservations = [reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, effect,
        entitlement=index == 1, amount="0.6", tokens=200)) for index, effect in enumerate(old_effects)]
    resolve_provider_budget_failure(DATABASE_URL, reservation_id=reservations[1]["reservation_id"], project_id=project,
        external_state_unknown=True)
    before = fixture.usage()
    renewal = renewed_policy(prior, before)
    fixture.configure(renewal)
    after = fixture.usage()
    assert after["reservation_ids"] == before["reservation_ids"]
    assert after["shared_total"] == before["shared_total"]
    assert after["renewal_usage"]["calls_used_or_reserved"] == 0
    assert after["entitlement_usd"] is None
    with AuthorityUnitOfWork(DATABASE_URL) as uow:
        uow.cursor.execute("SELECT status,evidence->'creative_experiment'->>'policy_version' FROM authority_budget_reservation WHERE reservation_id=%s",
            [reservations[1]["reservation_id"]])
        assert uow.cursor.fetchone() == ("HELD_UNKNOWN", prior["policy_version"])
    settled = settle_provider_budget(DATABASE_URL, reservation_id=reservations[0]["reservation_id"], project_id=project,
        actual_amount="0.1", actual_tokens=50, evidence={"fixture": True})
    assert settled["status"] == "SETTLED"
    assert fixture.usage()["renewal_usage"]["conservative_tokens"] == 0
    authorization = renewal["authorization"]["authorization_ref"]
    for index in range(2):
        effect = fixture.native_effect(chapter_identity(index + 1))
        request = support.campaign_reservation(fixture, effect, entitlement=index == 1,
            amount="0.4", tokens=300, authorization=authorization)
        reservation = reserve_provider_budget(DATABASE_URL, request)
        assert_provider_execution_authorized(DATABASE_URL, operation_id=effect[0].operation_id,
            external_effect_id=effect[1], project_id=project, budget_reservation_id=reservation["reservation_id"])
    usage = fixture.usage()
    assert usage["renewal_usage"]["calls_used_or_reserved"] == 2
    assert usage["renewal_usage"]["conservative_tokens"] == 600
    assert Decimal(usage["renewal_usage"]["priced_usd"]) == Decimal("0.4")
    assert usage["renewal_usage"]["unpriced_calls"] == 1
    assert len(usage["entitlements"]) == 2
    # Historical settlement saved 150 tokens, but that cannot enlarge the new 600-token grant.
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_RENEWAL_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture,
            fixture.native_effect(chapter_identity(2, stage="review")), tokens=1, amount="0.01"))
    with pytest.raises(KernelError, match="BUDGET_IDEMPOTENCY_CONFLICT"):
        reserve_provider_budget(DATABASE_URL, replace(support.campaign_reservation(fixture, old_effects[1], entitlement=True), stable_idempotency_key="unknown-renamed"))
    assert get_creative_budget(DATABASE_URL, project)["budget_binding"]["policy_version"] == renewal["policy_version"]


@pytest.mark.parametrize("mutation", ["stale_ledger", "predecessor", "book", "campaign", "evidence", "future_window"])
def test_renewal_native_configuration_rejects_unapproved_or_stale_basis(mutation):
    fixture = support.provider_campaign_fixture()
    renewal = renewed_policy(fixture.policies["A"], fixture.usage())
    if mutation == "stale_ledger":
        reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, fixture.native_effect(planning_identity())))
    elif mutation == "predecessor":
        renewal["comparison_budget"]["previous_policy"]["policy_hash"] = "a" * 64
    elif mutation == "book":
        renewal["comparison_budget"]["arms"][0]["book_id"] += ":other"
        renewal["authorization"]["book_id"] += ":other"
    elif mutation == "campaign":
        renewal["comparison_budget"]["experiment_id"] += ":reset"
    elif mutation == "evidence":
        renewal["authorization"]["evidence_hash"] = fixture.policies["A"]["authorization"]["evidence_hash"]
    else:
        renewal["comparison_budget"]["renewal"]["authorized_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_RENEWAL_INVALID"):
        fixture.configure(renewal)


def test_renewal_does_not_reauthorize_an_expired_frozen_reservation(monkeypatch):
    from tests.unit import test_creative_budget_contract as contract_support
    import novel_forge.modules.command_kernel.creative_budget_runtime as runtime
    factory = contract_support.provider_campaign_policy
    now = datetime.now(timezone.utc)

    def short_policy():
        policy = factory()
        policy["comparison_budget"]["expires_at"] = (now + timedelta(minutes=5)).isoformat()
        return policy

    monkeypatch.setattr(contract_support, "provider_campaign_policy", short_policy)
    fixture = support.provider_campaign_fixture()
    project = fixture.projects["A"]
    effect = fixture.native_effect(chapter_identity(1))
    reservation = reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, effect))
    fixture.configure(renewed_policy(fixture.policies["A"], fixture.usage()))

    class AfterOldExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(minutes=10)

    monkeypatch.setattr(runtime, "datetime", AfterOldExpiry)
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_AUTHORIZATION_EXPIRED"):
        assert_provider_execution_authorized(DATABASE_URL, operation_id=effect[0].operation_id,
            external_effect_id=effect[1], project_id=project, budget_reservation_id=reservation["reservation_id"])


@pytest.mark.parametrize("ceiling", ["calls", "money"])
def test_renewal_shared_ceiling_cannot_be_reset_by_new_effect_or_model(ceiling, monkeypatch):
    plan = support.plan_external_effect
    models = iter(("first-authorized-model", "another-authorized-model"))
    monkeypatch.setattr(support, "plan_external_effect", lambda *args, **kwargs: plan(*args, **{**kwargs, "model_id": next(models)}))
    fixture = support.provider_campaign_fixture()
    fixture.configure(renewed_policy(fixture.policies["A"], fixture.usage(), calls=1, tokens=600, amount="1")
                      if ceiling == "calls" else renewed_policy(fixture.policies["A"], fixture.usage()))
    effect = fixture.native_effect(chapter_identity(1))
    reserve_provider_budget(DATABASE_URL, replace(support.campaign_reservation(fixture, effect, tokens=100,
        amount="0.1" if ceiling == "calls" else "1"), model_id="first-authorized-model"))
    next_effect = fixture.native_effect(chapter_identity(2))
    with pytest.raises(KernelError, match="CREATIVE_BUDGET_RENEWAL_EXHAUSTED"):
        reserve_provider_budget(DATABASE_URL, replace(support.campaign_reservation(fixture, next_effect,
            tokens=100, amount="0.01"), model_id="another-authorized-model"))


def test_renewal_reservations_serialize_the_shared_new_call_limit():
    from concurrent.futures import ThreadPoolExecutor
    fixture = support.provider_campaign_fixture()
    fixture.configure(renewed_policy(fixture.policies["A"], fixture.usage(), calls=1, tokens=600, amount="1"))
    effects = [fixture.native_effect(chapter_identity(1)) for _ in range(2)]

    def reserve(effect):
        try:
            return reserve_provider_budget(DATABASE_URL, support.campaign_reservation(fixture, effect, tokens=100, amount="0.1"))["status"]
        except KernelError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, effects)) == ["CREATIVE_BUDGET_RENEWAL_EXHAUSTED", "RESERVED"]
