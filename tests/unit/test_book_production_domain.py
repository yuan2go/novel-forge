from __future__ import annotations

import pytest

from novel_forge.modules.book_production import (
    EndingReachability,
    EndingReachabilityInput,
    evaluate_ending_reachability,
    required_arc_contributions,
)
from novel_forge.modules.book_authority.input_resolver import (
    BookProductionInputResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError


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


def test_volume_portfolio_resolves_one_runtime_current_volume() -> None:
    volumes = [
        {"asset_version_id": "volume-1", "content": {"chapter_range": [1, 30]}},
        {"asset_version_id": "volume-2", "content": {"chapter_range": [31, 60]}},
        {"asset_version_id": "volume-3", "content": {"chapter_range": [61, 90]}},
    ]

    current = BookProductionInputResolver._select_current_volume(
        volumes, chapter_cursor=31
    )

    assert current["asset_version_id"] == "volume-2"


def test_volume_portfolio_rejects_overlapping_ranges() -> None:
    with pytest.raises(KernelError, match="BOOK_PRODUCTION_VOLUME_PORTFOLIO_OVERLAP"):
        BookProductionInputResolver._select_current_volume(
            [
                {"asset_version_id": "volume-1", "content": {"chapter_range": [1, 30]}},
                {"asset_version_id": "volume-2", "content": {"chapter_range": [30, 60]}},
            ],
            chapter_cursor=30,
        )


def test_volume_portfolio_rejects_a_strategic_gap() -> None:
    with pytest.raises(KernelError, match="BOOK_PRODUCTION_VOLUME_PORTFOLIO_OVERLAP"):
        BookProductionInputResolver._select_current_volume(
            [
                {"asset_version_id": "volume-1", "content": {"chapter_range": [1, 30]}},
                {"asset_version_id": "volume-2", "content": {"chapter_range": [32, 60]}},
            ],
            chapter_cursor=1,
        )
