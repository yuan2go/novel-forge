from novel_forge.modules.chapter_authority.candidate_selection import (
    CandidateEvidence,
    CandidateStopReason,
    build_best_candidate,
    compare_candidates,
)


def _candidate(identity: str, score: float, blockers: tuple[str, ...] = ()) -> CandidateEvidence:
    return CandidateEvidence(
        asset_version_id=identity,
        content={"text": identity},
        score=score,
        blocker_codes=blockers,
        review_asset_version_id=f"review:{identity}",
    )


def test_newer_revision_does_not_replace_best_below_minimum_improvement() -> None:
    previous = _candidate("draft-v1", 80.0)
    challenger = _candidate("revision-v2", 80.4)
    comparison = compare_candidates(
        project_id="project-1",
        chapter_root_operation_id="chapter-op",
        previous=previous,
        challenger=challenger,
        minimum_net_improvement=1.0,
    )
    best, snapshot = build_best_candidate(
        comparison=comparison,
        candidates={
            previous.asset_version_id: previous.content,
            challenger.asset_version_id: challenger.content,
        },
    )

    assert comparison["selected_asset_version_id"] == "draft-v1"
    assert comparison["stop_reason"] == CandidateStopReason.MARGINAL_IMPROVEMENT
    assert best["text"] == "draft-v1"
    assert snapshot["rollback_asset_version_id"] == "draft-v1"


def test_new_deterministic_blocker_rolls_back_even_when_score_increases() -> None:
    comparison = compare_candidates(
        project_id="project-1",
        chapter_root_operation_id="chapter-op",
        previous=_candidate("draft-v1", 70.0),
        challenger=_candidate("revision-v2", 90.0, ("CANON_CONFLICT",)),
        minimum_net_improvement=1.0,
    )

    assert comparison["selected_asset_version_id"] == "draft-v1"
    assert comparison["stop_reason"] == CandidateStopReason.DETERMINISTIC_BLOCKER


def test_substantive_blocker_free_revision_becomes_best() -> None:
    comparison = compare_candidates(
        project_id="project-1",
        chapter_root_operation_id="chapter-op",
        previous=_candidate("draft-v1", 70.0, ("PACING",)),
        challenger=_candidate("revision-v2", 82.0),
        minimum_net_improvement=2.0,
    )

    assert comparison["selected_asset_version_id"] == "revision-v2"
    assert comparison["stop_reason"] == CandidateStopReason.QUALITY_SATISFIED
