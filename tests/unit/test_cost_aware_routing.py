from dataclasses import replace
from datetime import datetime, timezone

import pytest

from novel_forge.modules.production_execution.cost_routing import (
    BenchmarkObservation,
    CostAwareRouter,
    ModelCandidate,
    PricingSnapshot,
    RoutingTask,
)


NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


def candidate(name="flash", price="1", **overrides):
    return ModelCandidate(
        name,
        "deepseek",
        name,
        "high",
        name,
        ("structured_output",),
        100_000,
        20_000,
        PricingSnapshot(
            "price-v1",
            "2026-09-01T00:00:00+00:00",
            "2026-10-01T00:00:00+00:00",
            price,
            "0.01",
            price,
            source="official",
        ),
        "capability-v1",
        **overrides,
    )


def task(**overrides):
    return replace(
        RoutingTask(
            "classification",
            "project",
            "book",
            "operation",
            "attempt",
            1000,
            100,
            100_000,
            "1",
        ),
        **overrides,
    )


def samples(score=0.99, n=30, cached=0, **overrides):
    return [
        BenchmarkObservation(
            str(i),
            NOW.isoformat(),
            score,
            True,
            True,
            False,
            False,
            False,
            False,
            2,
            1000,
            100,
            cached,
            ".001",
            **overrides,
        )
        for i in range(n)
    ]


def route(task_context, candidates, observations):
    return (
        CostAwareRouter()
        .explain(task_context, candidates, observations, now=NOW)
        .to_dict()
    )


def test_quality_floor_precedes_price_and_equal_quality_uses_effective_cost():
    cheap, strong = candidate(), candidate("pro", "3")
    result = route(task(), [cheap, strong], {"flash": samples(0.5), "pro": samples()})
    assert result["selected"]["candidate"]["candidate_id"] == "pro"
    result = route(task(), [strong, cheap], {"flash": samples(), "pro": samples()})
    assert result["selected"]["candidate"]["candidate_id"] == "flash"


def test_absent_stale_and_fixture_benchmarks_fail_closed():
    for evidence in (
        [],
        samples(n=1),
        samples(evidence_kind="FIXTURE"),
        [replace(row, occurred_at="2026-07-01T00:00:00+00:00") for row in samples()],
    ):
        result = route(task(), [candidate()], {"flash": evidence})
        assert result["status"] == "BLOCKED"
        assert "BENCHMARK_INSUFFICIENT" in result["candidates"][0]["rejected_reasons"]


def test_high_risk_uncertainty_and_budget_never_lower_floor():
    context = task(task_type="critical_chapter", remaining_money="0.0001")
    result = route(context, [candidate()], {"flash": samples()})
    assert result["status"] == "BLOCKED"
    assert result["policy"]["quality_floor"] == 0.85
    assert "BUDGET_HARD_LIMIT" in result["candidates"][0]["rejected_reasons"]


def test_cache_changes_rank_but_reservation_assumes_miss():
    cold, warm = candidate(), candidate("pro", "2")
    context = task(cache_eligible=True, reusable_prefix_tokens=1000)
    result = route(
        context, [cold, warm], {"flash": samples(), "pro": samples(cached=1000)}
    )
    assert result["selected"]["candidate"]["candidate_id"] == "pro"
    assert result["selected"]["reservation_upper_bound"] == "0.0022"
    assert result["selected"]["estimated_monetary_cost"] == "0.00021"


def test_soft_limit_is_visible_and_does_not_remove_qualified_routes():
    result = route(task(soft_money_limit=".0001"), [candidate()], {"flash": samples()})
    assert result["selected"]["soft_limit_pressure"] is True


@pytest.mark.parametrize(
    "failure", ["QUALITY_FAILURE", "SCHEMA_REJECTION", "CONTEXT_OVERFLOW"]
)
def test_failed_route_is_excluded(failure):
    context = task(history=({"candidate_id": "flash", "failure_class": failure},))
    result = route(
        context,
        [candidate(), candidate("pro", "2")],
        {"flash": samples(), "pro": samples()},
    )
    assert result["selected"]["candidate"]["candidate_id"] == "pro"


def test_unavailable_capability_and_capacity_fail_closed():
    for value in (
        candidate(available=False),
        replace(candidate(), context_limit=100),
        replace(candidate(), capabilities=("text",)),
    ):
        assert route(task(), [value], {"flash": samples()})["status"] == "BLOCKED"


def test_codex_requires_threshold_authorization_quota_and_no_loop():
    codex = candidate(
        "codex",
        "10",
        escalation_only=True,
        quota_remaining=1,
        authorization_ref="grant:1",
    )
    assert route(task(), [codex], {"codex": samples()})["status"] == "BLOCKED"
    context = task(
        history=tuple(
            {"candidate_id": "flash", "failure_class": "QUALITY_FAILURE"}
            for _ in range(2)
        )
    )
    assert route(context, [codex], {"codex": samples()})["status"] == "SELECTED"
    assert (
        route(context, [replace(codex, available=False)], {"codex": samples()})[
            "status"
        ]
        == "BLOCKED"
    )
    context = replace(
        context,
        history=(*context.history, {"candidate_id": "codex", "escalation": True}),
    )
    assert route(context, [codex], {"codex": samples()})["status"] == "BLOCKED"


def test_unknown_outcome_requires_reconciliation_and_decision_is_immutable():
    context = task(history=({"failure_class": "UNKNOWN_EXTERNAL_OUTCOME"},))
    decision = CostAwareRouter().explain(
        context, [candidate()], {"flash": samples()}, now=NOW
    )
    original = decision.to_dict()
    original["policy"]["quality_floor"] = 0
    assert decision.to_dict()["policy"]["quality_floor"] == 0.60
    assert decision.to_dict()["status"] == "BLOCKED"
