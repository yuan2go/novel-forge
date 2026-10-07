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
    assert comparison["stop_reason"] == CandidateStopReason.COMPARISON_SUPPORTED


def test_unchanged_prose_cannot_claim_improvement_from_a_higher_score():
    from dataclasses import replace

    previous = _candidate("draft-v1", 70.0, ("CANON_CONFLICT",))
    challenger = replace(_candidate("revision-v2", 95.0), content=dict(previous.content))
    result = compare_candidates(project_id="p", chapter_root_operation_id="op", previous=previous,
        challenger=challenger, minimum_net_improvement=1.0)
    assert result["selected_asset_version_id"] == previous.asset_version_id
    assert result["previous"]["blocker_codes"] == ["CANON_CONFLICT"]
    assert not result["improved"]


def test_resolved_blocker_does_not_imply_literary_quality_above_a_fixed_score():
    result = compare_candidates(project_id="p", chapter_root_operation_id="op",
        previous=_candidate("draft", 90.0, ("CANON_CONFLICT",)),
        challenger=_candidate("revision", 75.0), minimum_net_improvement=1.0)
    assert result["selected_asset_version_id"] == "revision"
    assert result["stop_reason"] == "COMPARISON_SUPPORTED"


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


def test_native_retention_reuses_exact_review_without_prose_or_score_improvement():
    from novel_forge.modules.revision.domain import retain_reviewed_draft, reuse_unchanged_review
    from novel_forge.modules.review.diagnostics import prose_hash
    from novel_forge.modules.command_kernel.errors import KernelError
    from copy import deepcopy
    import pytest
    draft = {"text": "他没接话。", "chapter": 1, "title": "门", "scene_artifacts": []}
    review = {"decision": "PASSED", "review_decision_contract": "work-review-decision.v1", "issues": [], "score": 60,
        "target_asset_version_id": "draft", "target_text_hash": prose_hash(draft["text"]), "context_bundle_version_id": "context"}
    inputs = dict(draft=draft, draft_id="draft", draft_hash="dh", review=review, review_id="review", review_hash="rh", context_id="context", context_hash="ch")
    revision = retain_reviewed_draft(**inputs)
    rereview = reuse_unchanged_review(**inputs, revision=revision, revision_id="revision")
    assert revision["text"] == draft["text"]
    assert rereview["score"] == review["score"] and rereview["revision_quality_delta"]["score_delta"] == 0
    assert rereview["review_reuse_evidence"]["provider_dispatches"] == 0
    changed = deepcopy(revision);changed["text"] += "他点了头。"
    with pytest.raises(KernelError, match="REREVIEW_RETENTION_DRIFT"):
        reuse_unchanged_review(**inputs, revision=changed, revision_id="revision")
    with pytest.raises(KernelError, match="REVISION_DIAGNOSIS_STALE"):
        retain_reviewed_draft(**{**inputs, "context_id": "new-context"})
    blocked = {**review, "issues": [{"code": "contradiction", "severity": "blocking"}]}
    assert retain_reviewed_draft(**{**inputs, "review": blocked}) is None
