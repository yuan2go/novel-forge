from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from novel_forge.modules.book_followup_authority.domain import (
    READER_STATE_DIMENSIONS,
    evaluate_reader_outcome,
)
from novel_forge.modules.book_followup_authority.reader_policy import (
    ReaderProxyPolicy,
    policy_from_snapshot,
)
from novel_forge.modules.chapter_group_authority.policy import (
    ChapterGroupExecutionPolicy,
    chapter_group_execution_policy_definitions,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.versioned_policy_repository import policy_hash


@pytest.mark.parametrize("count", [1, 2, 9, 12, 30])
def test_execution_policy_has_positive_configurable_limits(count: int) -> None:
    policy = ChapterGroupExecutionPolicy("test-window-v1", count, count)
    assert policy.maximum_chapters == count


@pytest.mark.parametrize("commit_sha", ["z" * 40, "A" * 40, "a" * 39, ""])
def test_policy_definition_requires_exact_lowercase_git_identity(commit_sha: str) -> None:
    with pytest.raises(ValueError, match="exact implementation identity"):
        chapter_group_execution_policy_definitions(
            application_build_id="test", commit_sha=commit_sha
        )


@pytest.mark.parametrize("limits", [(0, 0), (8, 9), (8, -1), (True, 1)])
def test_execution_policy_rejects_invalid_limits(limits: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        ChapterGroupExecutionPolicy("test-window-v1", *limits)


def test_reader_threshold_change_changes_advisory_contract_without_mutation_authority() -> (
    None
):
    state = dict.fromkeys(READER_STATE_DIMENSIONS, 0.9)
    state.update(confusion=0.6, drop_risk=0.1, repetition_fatigue=0.1)
    evidence = [{"span": "explicit unresolved contradiction"}]
    original = evaluate_reader_outcome(state, evidence=evidence)
    stricter = evaluate_reader_outcome(
        state,
        evidence=evidence,
        policy=replace(ReaderProxyPolicy(), policy_version="review-v2", confusion=0.5),
    )
    assert original["gate"] == "PASS"
    assert stricter["gate"] == "REVISION_RECOMMENDED"
    assert stricter["reader_proxy_policy_version"] == "review-v2"
    assert stricter["issues"][0]["threshold"] == 0.5
    assert stricter["canon_mutation_allowed"] is False
    assert stricter["body_mutation_allowed"] is False


def test_reader_snapshot_integrity_is_required() -> None:
    content = asdict(ReaderProxyPolicy())
    snapshot = {
        "owner": "READER_PROXY",
        "policy": content,
        "policy_hash": policy_hash(content),
    }
    assert policy_from_snapshot(snapshot) == ReaderProxyPolicy()
    with pytest.raises(KernelError, match="READER_PROXY_POLICY_SNAPSHOT_INVALID"):
        policy_from_snapshot({**snapshot, "policy": {**content, "confusion": 0.1}})
    with pytest.raises(KernelError, match="READER_PROXY_POLICY_SNAPSHOT_INVALID"):
        policy_from_snapshot({})


@pytest.mark.parametrize(
    "change",
    [
        {"confusion": float("nan")},
        {"drop_risk": float("inf")},
        {"trust": -0.1},
        {"ordinal_high": 0.3},
        {"revision_required_issue_count": 0},
        {"human_review_major_count": True},
    ],
)
def test_reader_policy_rejects_invalid_thresholds(change: dict) -> None:
    with pytest.raises(ValueError):
        replace(ReaderProxyPolicy(), **change)
