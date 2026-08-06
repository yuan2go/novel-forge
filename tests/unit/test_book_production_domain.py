from __future__ import annotations

import pytest

from novel_forge.modules.book_production import (
    EndingReachability,
    EndingReachabilityInput,
    evaluate_ending_reachability,
    required_arc_contributions,
)


def test_ending_reachability_is_deterministic_and_reachable() -> None:
    value = EndingReachabilityInput(2, 10, 2, 2, 4, 2, 4, 2, 4)
    first = evaluate_ending_reachability(value)
    second = evaluate_ending_reachability(value)
    assert first == second
    assert first.status is EndingReachability.REACHABLE
    assert first.replan_required is False


def test_ending_reachability_requests_replan_when_capacity_is_exhausted() -> None:
    report = evaluate_ending_reachability(
        EndingReachabilityInput(9, 10, 2, 4, 1, 3, 1, 5, 1)
    )
    assert report.status is EndingReachability.UNREACHABLE
    assert report.replan_required is True
    assert "critical_arc_closure_path" in report.reasons


def test_arc_contribution_declarations_require_unique_identity() -> None:
    assert required_arc_contributions(
        {"required_arc_contributions": [{"arc_id": "arc-1", "beat": "turn"}]}
    ) == {"arc-1": {"arc_id": "arc-1", "beat": "turn"}}
    with pytest.raises(ValueError):
        required_arc_contributions(
            {"required_arc_contributions": [{"arc_id": "arc-1"}, {"arc_id": "arc-1"}]}
        )
