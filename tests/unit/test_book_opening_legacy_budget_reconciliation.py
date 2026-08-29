from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from novel_forge.modules.book_authority.opening import (
    BookOpeningBudgetReconciliationRequest,
    _opening_definition,
)
from novel_forge.modules.command_kernel.budget_runtime import canonical_budget_policy
from novel_forge.modules.command_kernel.errors import KernelError


def _request_values() -> dict[str, object]:
    started_at = datetime(2026, 8, 29, tzinfo=timezone.utc)
    return {
        "expected_opening_version": 7,
        "expected_frozen_request_digest": "sha256:" + "a" * 64,
        "idempotency_key": "legacy-budget:opening:1",
        "policy_contract_version": "book-opening-provider-budget.v1",
        "policy_snapshot": {
            "execution_mode": "PROVIDER_ALLOWED",
            "provider_call_limit": 40,
            "token_limit": 1_800_000,
            "cost_limit_usd": "20.00",
        },
        "policy_hash": "",
        "currency": "usd",
        "budget_timezone": "UTC",
        "started_at": started_at,
        "deadline_at": started_at + timedelta(hours=1),
        "reason": "operator supplied bounded recovery budget",
    }


def test_legacy_budget_reconciliation_request_canonicalizes_explicit_contract() -> None:
    values = _request_values()
    policy = canonical_budget_policy(values["policy_snapshot"])  # type: ignore[arg-type]
    request = BookOpeningBudgetReconciliationRequest(
        **{**values, "policy_hash": policy["policy_hash"]}
    )

    assert request.currency == "USD"
    assert request.policy_snapshot["cost_limit_usd"] == "20"
    assert request.policy_hash.startswith("sha256:")
    assert request.contract_hash.startswith("sha256:")
    assert request.to_dict()["started_at"] == "2026-08-29T00:00:00+00:00"


def test_legacy_budget_reconciliation_request_rejects_hash_or_snapshot_drift() -> None:
    values = _request_values()

    with pytest.raises(KernelError, match="policy hash"):
        BookOpeningBudgetReconciliationRequest(
            **{**values, "policy_hash": "sha256:" + "0" * 64}
        )
    with pytest.raises(KernelError, match="frozen request digest"):
        BookOpeningBudgetReconciliationRequest(
            **{**values, "expected_frozen_request_digest": "not-a-digest"}
        )
    with pytest.raises(KernelError, match="deadline"):
        BookOpeningBudgetReconciliationRequest(
            **{**values, "deadline_at": values["started_at"]}
        )


def test_legacy_budget_reconciliation_definition_requires_its_own_outbox() -> None:
    definition = _opening_definition(
        "book.opening.reconcile_legacy_budget_scope",
        application_build_id="legacy-budget-definition-test",
        commit_sha="f" * 40,
    )

    assert definition["completion_contract"]["required_outbox_events"] == [
        "book.opening.legacy_budget_reconciled"
    ]
