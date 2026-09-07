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


def test_native_selection_preserves_prose_identity_across_three_workspaces() -> None:
    import copy
    import pytest
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset, ChapterNode
    from novel_forge.modules.chapter_authority.handlers import build_chapter_handler_registry, DeterministicFixtureChapterProvider
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.review.domain import evaluate_review_result

    handler = build_chapter_handler_registry(DeterministicFixtureChapterProvider()).require(ChapterNode.BEST_CANDIDATE)
    source = {"chapter": 1, "text": "她选择留下，错过了末班船。"}
    review = evaluate_review_result(project_id="p", target_asset_version_id="draft:1",
        context_bundle_version_id="context:1", chapter=1,
        result={"diagnostic_contract_version": "actionable-diagnostics.v1", "decision": "PASSED", "score": 85, "issues": []},
        provider_evidence={}, prose_text=source["text"])
    original = ChapterInputAsset("draft:1", "draft_chapter", "hash", source)
    incumbent = original
    for generation in range(3):
        revision_id = f"revision:{generation}"
        challenger_review = {**review, "target_asset_version_id": revision_id, "revision_version_id": revision_id,
                             "score": 86, "resolution_checks": []}
        inputs = (incumbent, ChapterInputAsset(revision_id, "draft_version", "hash", source),
                  ChapterInputAsset(f"rereview:{generation}", "re_review_report", "hash", challenger_review))
        if generation == 0:
            inputs += (ChapterInputAsset("review:1", "review_report", "hash", review),)
        request = ChapterHandlerRequest("op", "p", "w", "trace", "root", {"correction_generation": generation}, inputs)
        output = handler.execute(request)
        assert output.content["selected_source_asset_version_id"] == "draft:1"
        assert output.content["candidate_comparison"]["previous"]["asset_version_id"] == "draft:1"
        assert output.content["candidate_comparison"]["previous"]["score"] == 85
        assert output.content["selected_review"]["selection_review_source_asset_version_id"] == "review:1"
        incumbent = ChapterInputAsset(f"workspace:{generation}", "best_draft_candidate", "hash", output.content)
    broken = copy.deepcopy(incumbent.content)
    broken["candidate_comparison"].pop("previous")
    request = ChapterHandlerRequest("op", "p", "w", "trace", "root", {},
        (ChapterInputAsset("broken", "best_draft_candidate", "hash", broken), *inputs[1:]))
    with pytest.raises(KernelError, match="BEST_CANDIDATE_EVIDENCE_REQUIRED"):
        handler.execute(request)
