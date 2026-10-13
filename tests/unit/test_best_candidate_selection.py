from novel_forge.modules.chapter_authority.candidate_selection import (
    CandidateEvidence,
    CandidateStopReason,
    build_best_candidate,
    compare_candidates,
)


def _length_candidates():
    from dataclasses import replace
    from novel_forge.modules.review.diagnostics import prose_hash
    previous = replace(_candidate("draft", 80), content={"text": "山" * 3520})
    challenger = replace(_candidate("revision", 80), content={"text": "河" * 4500},
        diagnostic_contract_version="actionable-diagnostics.v1")
    scope = {"contract_version": "chapter-length-repair.v1", "unit": "HAN_CHARACTERS_V1",
        "scope": "WHOLE_CHAPTER_LENGTH_CORRECTION", "source_asset_version_id": "draft",
        "source_text_hash": prose_hash(previous.content["text"]), "source_han_characters": 3520,
        "context_asset_version_id": "context", "minimum": 4000, "maximum": 5000}
    return previous, challenger, scope


def test_measured_length_correction_does_not_require_a_model_score_gain():
    previous, challenger, scope = _length_candidates()
    result = compare_candidates(project_id="p", chapter_root_operation_id="root", previous=previous,
        challenger=challenger, minimum_net_improvement=3, length_repair_scope=scope)
    assert result["selected_asset_version_id"] == "revision"
    assert result["length_measurement"]["challenger"] == 4500
    assert result["resolution_checks"] == [] and not result["literary_quality_proven"]


def test_measured_length_correction_cannot_hide_new_major_problem():
    from dataclasses import replace
    previous, challenger, scope = _length_candidates()
    result = compare_candidates(project_id="p", chapter_root_operation_id="root", previous=previous,
        challenger=replace(challenger, blocker_codes=("CANON_CONFLICT",)),
        minimum_net_improvement=3, length_repair_scope=scope)
    assert result["selected_asset_version_id"] == "draft"


def test_measured_length_correction_requires_exact_source():
    import pytest
    from novel_forge.modules.command_kernel.errors import KernelError
    previous, challenger, scope = _length_candidates()
    for drift in ({"source_asset_version_id": "other"}, {"source_text_hash": "sha256:" + "f" * 64}):
        with pytest.raises(KernelError, match="exact out-of-bounds"):
            compare_candidates(project_id="p", chapter_root_operation_id="root", previous=previous,
                challenger=challenger, minimum_net_improvement=3, length_repair_scope={**scope, **drift})


def test_partial_scope_repair_with_unchanged_uncertainty_uses_the_same_preservation_rule_as_propagation():
    from dataclasses import replace
    from novel_forge.modules.review.diagnostics import prose_hash
    from novel_forge.modules.review.prose_window import PRESERVATION_DIMENSIONS
    text = "赴约日期尚待核实。\n\n他把练习的方法问清了。"
    start = text.index("他把")
    proposal = {"contract_version": "working-prose-scope-proposal.v1", "target_text_hash": prose_hash(text),
        "issue_codes": ["repeat"], "changed_target_ranges": [{"start": start, "end": len(text)}]}
    dimensions = [{"dimension": key, "status": "PRESERVED", "reason": "核对修改和未改段。",
        "evidence": {"quote": text[start:]}} for key in PRESERVATION_DIMENSIONS]
    dimensions[0] = {**dimensions[0], "status": "UNCERTAIN", "evidence": {"quote": text[:9]}}
    challenger = CandidateEvidence("new", {"text": text, "prose_scope_proposal": proposal}, 88, (), "rereview",
        diagnostic_contract_version="actionable-diagnostics.v1", cross_chapter_review=True,
        resolution_checks=({"code": "repeat", "status": "PARTIALLY_RESOLVED", "preservation": "PRESERVED",
            "reason": "合并有效，仍有余项。", "evidence": {"quote": text[start:]}},
            {"code": "timeline", "status": "UNRESOLVED", "preservation": "UNCERTAIN",
             "reason": "未改的日期疑问保留。", "evidence": {"quote": text[:9]}}),
        preservation_checks=tuple(dimensions), remaining_issue_codes=("repeat", "timeline"),
        review_target_text_hash=prose_hash(text), review_report_type="ReReviewReport")
    previous = _candidate("old", 95)
    def selected(candidate):
        return compare_candidates(project_id="p", chapter_root_operation_id="root", previous=previous,
            challenger=candidate, minimum_net_improvement=100)["selected_asset_version_id"]
    assert selected(challenger) == "new"
    assert selected(replace(challenger, review_target_text_hash="other")) == "old"
    assert selected(replace(challenger, preservation_checks=tuple({**check, "status": "REGRESSED"}
        if index == 1 else check for index, check in enumerate(dimensions)))) == "old"
    assert selected(replace(challenger, blocker_codes=("NEW_CONTRADICTION",))) == "old"


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


def test_located_repair_and_preservation_support_selection_without_a_score_gain_or_lifetime_count():
    from dataclasses import replace
    previous = _candidate('draft',95)
    challenger = replace(_candidate('revision',90),diagnostic_contract_version='actionable-diagnostics.v1',
        resolved_issue_codes=('REPETITION',),
        resolution_checks=({'code':'REPETITION','status':'SATISFIED','preservation':'PRESERVED',
            'evidence':{'quote':'revision'},'reason':'The duplicate demonstration is combined while the prior choice remains.'},))
    result = compare_candidates(project_id='p',chapter_root_operation_id='root',previous=previous,
        challenger=challenger,minimum_net_improvement=3,correction_generation=12,maximum_correction_generations=1)
    assert result['selected_asset_version_id']=='revision' and result['stop_reason']=='COMPARISON_SUPPORTED'
    assert result['net_improvement']==-5 and not result['literary_quality_proven']


def test_supported_partial_repair_keeps_remaining_problem_without_count_escalation():
    from dataclasses import replace
    previous = _candidate('draft',95,('REMAINING',))
    challenger = replace(_candidate('revision',90,('REMAINING',)),diagnostic_contract_version='actionable-diagnostics.v1',
        resolved_issue_codes=('REPETITION',),remaining_issue_codes=('REMAINING',),
        resolution_checks=({'code':'REPETITION','status':'SATISFIED','preservation':'PRESERVED',
            'evidence':{'quote':'revision'},'reason':'One repeated passage is combined; the other diagnosis remains open.'},))
    result = compare_candidates(project_id='p',chapter_root_operation_id='root',previous=previous,
        challenger=challenger,minimum_net_improvement=3,correction_generation=12,maximum_correction_generations=1)
    assert result['selected_asset_version_id']=='revision' and result['stop_reason']=='CONTINUE_CORRECTION'
    assert result['challenger']['blocker_codes']==['REMAINING']


def test_located_resolution_claim_cannot_select_an_issue_the_host_keeps_open():
    from dataclasses import replace
    for score in (90, 100):
        challenger = replace(_candidate('revision', score), diagnostic_contract_version='actionable-diagnostics.v1',
            remaining_issue_codes=('REPETITION',),
            resolution_checks=({'code':'REPETITION','status':'SATISFIED','preservation':'PRESERVED',
                'evidence':{'quote':'revision'},'reason':'A real passage alone does not close the diagnosis.'},))
        result = compare_candidates(project_id='p', chapter_root_operation_id='root',
            previous=_candidate('draft',95), challenger=challenger, minimum_net_improvement=3)
        assert result['selected_asset_version_id'] == 'draft' and not result['improved']
        assert result['challenger']['remaining_issue_codes'] == ['REPETITION']


def test_high_score_and_self_report_without_real_passage_do_not_select_a_revision():
    from dataclasses import replace
    challenger = replace(_candidate('revision',100),diagnostic_contract_version='actionable-diagnostics.v1',
        resolution_checks=({'code':'REPETITION','status':'SATISFIED','preservation':'PRESERVED',
            'evidence':{'quote':'invented source passage'},'reason':'The model says it is resolved.'},))
    result = compare_candidates(project_id='p',chapter_root_operation_id='root',previous=_candidate('draft',80),
        challenger=challenger,minimum_net_improvement=3)
    assert result['selected_asset_version_id']=='draft' and not result['improved']


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
