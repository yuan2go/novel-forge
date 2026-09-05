from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetAssessmentOutcome,
    BudgetEvidenceLinkRequest,
    BudgetScopeRequest,
    canonical_budget_policy,
    canonical_budget_snapshot,
    deterministic_budget_scope_id,
    deterministic_budget_evidence_link_id,
    next_provider_budget_allowance,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _scope() -> dict[str, object]:
    return {
        "budget_scope_id": "budget-scope:opening-1",
        "project_id": "project:1",
        "owner_kind": "BOOK_OPENING",
        "owner_id": "opening:1",
        "currency": "USD",
        "policy_contract_version": "book-opening-budget.v1",
        "policy_hash": "sha256:" + "1" * 64,
        "policy_snapshot": {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 4,
            "token_limit": 20_000,
            "cost_limit_usd": "2.00",
        },
        "budget_timezone": "UTC",
        "started_at": "2026-08-29T00:00:00+00:00",
        "deadline_at": "2026-08-29T01:00:00+00:00",
        "revision": 3,
    }


def test_canonical_budget_policy_is_order_independent_and_decimal_stable() -> None:
    first = canonical_budget_policy(
        {
            "token_limit": 20_000,
            "cost_limit_usd": "2.00",
            "provider_call_limit": 4,
            "execution_mode": "PROVIDER_ALLOWED",
        }
    )
    second = canonical_budget_policy(
        {
            "execution_mode": "provider_allowed",
            "provider_call_limit": 4,
            "cost_limit_usd": "2.0",
            "token_limit": 20_000,
        }
    )

    assert first == second
    assert first["policy_snapshot"] == {
        "cost_limit_usd": "2",
        "execution_mode": "PROVIDER_ALLOWED",
        "provider_call_limit": 4,
        "token_limit": 20_000,
    }
    assert first["policy_hash"].startswith("sha256:")


def test_next_provider_allowance_uses_frozen_per_call_limits() -> None:
    allowance = next_provider_budget_allowance(
        {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 40,
            "token_limit": 1_800_000,
            "cost_limit_usd": "20",
            "per_call_token_limit": 100_000,
            "per_call_cost_limit_usd": "2",
        }
    )

    assert allowance == {
        "execution_mode": "PROVIDER_ALLOWED",
        "requested_calls": 1,
        "requested_tokens": 100_000,
        "requested_amount": "2",
    }


@pytest.mark.parametrize(
    "policy",
    [
        {},
        {"execution_mode": "UNBOUNDED"},
        {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 0,
            "token_limit": 10,
            "cost_limit_usd": "1",
        },
        {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 1,
            "token_limit": -1,
            "cost_limit_usd": "1",
        },
        {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 1,
            "token_limit": 10,
            "cost_limit_usd": "NaN",
        },
    ],
)
def test_canonical_budget_policy_rejects_unbounded_or_invalid_provider_policy(
    policy: dict[str, object],
) -> None:
    with pytest.raises(KernelError, match="budget scope policy"):
        canonical_budget_policy(policy)


def test_canonical_budget_snapshot_sorts_evidence_and_hashes_authority_only() -> None:
    reservations = [
        {
            "reservation_id": "reservation:2",
            "version": 1,
            "status": "SETTLED",
            "reserved_amount": "0.50",
            "settled_amount": "0.40",
            "estimated_tokens": 200,
            "actual_tokens": 180,
            "budget_breach": False,
        },
        {
            "reservation_id": "reservation:1",
            "version": 0,
            "status": "RESERVED",
            "reserved_amount": "0.25",
            "settled_amount": "0",
            "estimated_tokens": 100,
            "actual_tokens": 0,
            "budget_breach": False,
        },
    ]
    links = [
        {
            "budget_evidence_link_id": "link:2",
            "evidence_hash": "sha256:" + "b" * 64,
        },
        {
            "budget_evidence_link_id": "link:1",
            "evidence_hash": "sha256:" + "a" * 64,
        },
    ]

    first = canonical_budget_snapshot(
        scope=_scope(),
        reservations=reservations,
        evidence_links=links,
        outcome=BudgetAssessmentOutcome.ELIGIBLE,
        reasons=(),
    )
    second = canonical_budget_snapshot(
        scope=deepcopy(_scope()),
        reservations=reversed(reservations),
        evidence_links=reversed(links),
        outcome="ELIGIBLE",
        reasons=(),
    )

    assert first == second
    assert [
        item["reservation_id"] for item in first["reservations"]
    ] == ["reservation:1", "reservation:2"]
    assert [
        item["budget_evidence_link_id"] for item in first["evidence_links"]
    ] == ["link:1", "link:2"]
    assert first["snapshot_hash"].startswith("sha256:")
    assert "observed_at" not in first


def test_projection_only_policy_is_bounded_without_provider_limits() -> None:
    policy = canonical_budget_policy({"execution_mode": "PROJECTION_ONLY"})

    assert policy["policy_snapshot"] == {"execution_mode": "PROJECTION_ONLY"}
    assert policy["policy_hash"].startswith("sha256:")


def test_budget_scope_request_freezes_identity_policy_and_deadline() -> None:
    started_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
    request = BudgetScopeRequest(
        project_id="project:1",
        owner_kind="book_opening",
        owner_id="opening:1",
        stable_idempotency_key="budget-scope:opening:1",
        currency="usd",
        policy_contract_version="book-opening-budget.v1",
        policy_snapshot={
            "execution_mode": "provider_allowed",
            "provider_call_limit": 4,
            "token_limit": 20_000,
            "cost_limit_usd": "2.00",
        },
        started_at=started_at,
        deadline_at=started_at + timedelta(hours=1),
        created_by_operation_id="operation:opening:1",
    )

    assert request.owner_kind == "BOOK_OPENING"
    assert request.currency == "USD"
    assert request.budget_scope_id == deterministic_budget_scope_id(
        project_id="project:1",
        owner_kind="BOOK_OPENING",
        owner_id="opening:1",
    )
    assert request.policy_snapshot["cost_limit_usd"] == "2"
    assert request.policy_hash.startswith("sha256:")


def test_budget_scope_request_rejects_unknown_owner_or_unbounded_deadline() -> None:
    started_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
    base = {
        "project_id": "project:1",
        "owner_kind": "BOOK_OPENING",
        "owner_id": "opening:1",
        "stable_idempotency_key": "budget-scope:opening:1",
        "currency": "USD",
        "policy_contract_version": "book-opening-budget.v1",
        "policy_snapshot": {"execution_mode": "PROJECTION_ONLY"},
        "started_at": started_at,
        "deadline_at": started_at + timedelta(hours=1),
        "created_by_operation_id": "operation:opening:1",
    }

    with pytest.raises(KernelError, match="owner_kind"):
        BudgetScopeRequest(**{**base, "owner_kind": "GLOBAL"})
    with pytest.raises(KernelError, match="deadline"):
        BudgetScopeRequest(**{**base, "deadline_at": started_at})
    with pytest.raises(KernelError, match="timezone-aware"):
        BudgetScopeRequest(
            **{
                **base,
                "started_at": started_at.replace(tzinfo=None),
                "deadline_at": (started_at + timedelta(hours=1)).replace(
                    tzinfo=None
                ),
            }
        )


def test_budget_evidence_link_identity_is_generation_and_version_bound() -> None:
    request = BudgetEvidenceLinkRequest(
        budget_scope_id="budget-scope:1",
        budget_scope_revision=3,
        project_id="project:1",
        reservation_id="reservation:1",
        evidence_kind="operation_cost",
        evidence_id="budget-cost:reservation:1",
        evidence_version=0,
        evidence_hash="sha256:" + "a" * 64,
        stable_idempotency_key="operation-cost:reservation:1",
    )

    assert request.evidence_kind == "OPERATION_COST"
    assert request.budget_evidence_link_id == deterministic_budget_evidence_link_id(
        budget_scope_id="budget-scope:1",
        reservation_id="reservation:1",
        evidence_kind="OPERATION_COST",
        evidence_id="budget-cost:reservation:1",
        evidence_version=0,
    )
    with pytest.raises(KernelError, match="evidence_kind"):
        BudgetEvidenceLinkRequest(
            **{
                **{
                    field: getattr(request, field)
                    for field in (
                        "budget_scope_id",
                        "budget_scope_revision",
                        "project_id",
                        "reservation_id",
                        "evidence_id",
                        "evidence_version",
                        "evidence_hash",
                        "stable_idempotency_key",
                    )
                },
                "evidence_kind": "PROMPT",
            }
        )
