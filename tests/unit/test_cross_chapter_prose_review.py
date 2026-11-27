from copy import deepcopy
from dataclasses import replace

import pytest

from novel_forge.modules.chapter_authority.candidate_selection import (
    CandidateEvidence,
    compare_candidates,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_task_view,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.cross_chapter import (
    apply_targeted_edits,
    extend_provider_schema,
    paired_diagnosis,
)
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.review.domain import (
    evaluate_review_result,
    evaluate_rereview_result,
)
from novel_forge.modules.review.prose_window import (
    CROSS_CHAPTER_CATEGORIES,
    PRESERVATION_DIMENSIONS,
    WINDOW_POLICY,
    digest,
    freeze_review_window,
    validate_source_snapshot,
    validate_support,
)


SOURCE = "沈舟左臂中箭，最后一枚雷符已经耗尽。\n他退入东门，许霜答应守住后路。"
TARGET = "沈舟左臂完好，掏出雷符。\n他推开东门。"


def source_snapshot(chapter=2, texts=(SOURCE,), budget=4000):
    scope = dict(project_id="p", workspace_id="w", book_id="b", book_run_id="br")
    value = {
        **scope,
        "contract_version": "accepted-prose-snapshot.v1",
        "target_chapter_number": chapter,
        "accepted_through_chapter": chapter - 1,
        "window_policy": {
            "version": WINDOW_POLICY,
            "maximum_previous_chapters": 2,
            "source_token_budget": budget,
        },
        "sources": [
            {
                **scope,
                "chapter_number": i,
                "asset_version_id": f"accepted:{i}",
                "content_hash": digest({"text": text}),
                "text_hash": prose_hash(text),
                "text": text,
                "acceptance_status": "COMMITTED",
                "acceptance_operation_id": f"accept:{i}",
            }
            for i, text in enumerate(texts, max(1, chapter - len(texts)))
        ],
    }
    value["snapshot_hash"] = digest(value)
    return value


def window(snapshot=None):
    return freeze_review_window(
        snapshot or source_snapshot(),
        candidate_id="draft:2",
        text=TARGET,
        context_token_budget=16000,
        protected_context={"approved_hard_constraints": []},
    )


def support(frozen=None):
    source = (frozen or window())["sources"][-1]
    return {
        **{
            key: source[key]
            for key in (
                "chapter_number",
                "asset_version_id",
                "content_hash",
                "text_hash",
            )
        },
        "start": 0,
        "end": 7,
        "quote": SOURCE[:7],
        "relation_to_issue": "伤势应有承接",
    }


def issue(category="CAUSAL_CARRYOVER", start=0, end=7):
    return {
        "code": category,
        "severity": "blocking",
        "message": "伤势无因消失",
        "category": category,
        "judgment_kind": "SEMANTIC_CONTRADICTION",
        "confidence": "HIGH",
        "interpretation": "CONTINUITY_PROBLEM",
        "evidence": {
            "asset_version_id": "draft:2",
            "text_hash": prose_hash(TARGET),
            "start": start,
            "end": end,
            "quote": TARGET[start:end],
        },
        "supporting_evidence": [support()],
        "lineage_code": None,
        "violated_constraint": "承接伤势",
        "revision_goal": "呈现伤势代价",
        "preserve": ["推开东门"],
        "acceptance_criteria": ["伤势限制动作"],
    }


def initial(issues=None):
    return evaluate_review_result(
        project_id="p",
        target_asset_version_id="draft:2",
        context_bundle_version_id="ctx",
        chapter=2,
        result={
            "diagnostic_contract_version": "actionable-diagnostics.v1",
            "decision": "NEEDS_REVISION",
            "score": 60,
            "issues": [issue()] if issues is None else issues,
        },
        provider_evidence={},
        prose_text=TARGET,
        cross_chapter_window=window(),
    )


def rereview_result(initial_review, text=TARGET, status="RESOLVED"):
    location = {"start": 0, "end": len(text), "quote": text}
    return {
        "diagnostic_contract_version": "actionable-diagnostics.v1",
        "decision": "PASSED",
        "score": 99,
        "issues": [],
        "resolution_checks": [
            {
                "code": item["code"],
                "status": status,
                "preservation": "PRESERVED",
                "evidence": location,
                "supporting_evidence": item["supporting_evidence"],
                "reason": "核对伤势与正文",
            }
            for item in initial_review["issues"]
        ],
        "preservation_checks": [
            {
                "dimension": dimension,
                "status": "PRESERVED",
                "evidence": location,
                "reason": "与冻结约束及前稿比对",
            }
            for dimension in PRESERVATION_DIMENSIONS
        ],
        "knowledge_checks": [],
    }


def rereview(review, result):
    return evaluate_rereview_result(
        project_id="p",
        original_draft_version_id="draft:2",
        initial_review_version_id="review:2",
        revision_version_id="revision:2",
        context_bundle_version_id="ctx",
        initial_review=review,
        revision={"chapter": 2, "text": TARGET},
        result=result,
        provider_evidence={},
    )


def test_first_chapter_empty_window_and_frozen_replay():
    snapshot = source_snapshot(chapter=1, texts=())
    frozen = window(snapshot)
    assert frozen["sources"] == []
    assert frozen == window(deepcopy(snapshot))
    assert frozen["target_candidate_text_hash"] == prose_hash(TARGET)


@pytest.mark.parametrize(
    "field,value",
    [
        ("chapter_number", 2),
        ("book_id", "other"),
        ("project_id", "other"),
        ("workspace_id", "other"),
        ("acceptance_status", "CANDIDATE"),
        ("text_hash", "wrong"),
    ],
)
def test_source_rejects_future_unaccepted_foreign_and_changed_prose(field, value):
    snapshot = source_snapshot()
    snapshot["sources"][0][field] = value
    snapshot["snapshot_hash"] = digest(
        {k: v for k, v in snapshot.items() if k != "snapshot_hash"}
    )
    with pytest.raises(KernelError):
        validate_source_snapshot(snapshot)


def test_full_excerpt_exclusion_and_overflow_are_explicit():
    full = window()
    assert full["sources"][0]["coverage"] == "FULL"
    long = "远处的往事。" * 100 + "\n动作承接。\n当前结尾。"
    partial = window(source_snapshot(chapter=3, texts=(SOURCE, long), budget=40))
    assert [s["coverage"] for s in partial["sources"]] == ["NOT_INCLUDED", "EXCERPT"]
    assert partial["sources"][1]["excerpts"][0]["text"] == "动作承接。\n当前结尾。"
    assert partial["sources"][1]["excluded_ranges"]
    with pytest.raises(KernelError, match="CROSS_CHAPTER_REVIEW_CONTEXT_INSUFFICIENT"):
        window(source_snapshot(budget=1))
    with pytest.raises(KernelError):
        freeze_review_window(
            source_snapshot(),
            candidate_id="draft",
            text=TARGET,
            context_token_budget=1,
            protected_context={},
        )


def test_exact_quote_outside_frozen_excerpt_is_not_reviewed_evidence():
    prose = "前文真话。" * 100 + "\n动作承接。\n当前结尾。"
    frozen = window(source_snapshot(texts=(prose,), budget=40))
    source = frozen["sources"][0]
    evidence = {
        **support(),
        **{
            key: source[key]
            for key in ("asset_version_id", "content_hash", "text_hash")
        },
        "start": 0,
        "end": 5,
        "quote": prose[:5],
    }
    with pytest.raises(KernelError, match="outside reviewed coverage"):
        validate_support([evidence], frozen)


def test_current_candidate_support_is_located_without_claiming_earlier_acceptance():
    local = issue("SPATIAL_ACTION_CONTINUITY")
    local["supporting_evidence"] = [{"asset_version_id": "draft:2", "quote": TARGET[-7:],
        "relation_to_issue": "A second action within the same current candidate."}]
    result = paired_diagnosis(local, text=TARGET, window=window())
    assert result["supporting_evidence"] == []
    support = result["candidate_supporting_evidence"][0]
    assert support["evidence_scope"] == "CURRENT_CANDIDATE" and support["text_hash"] == prose_hash(TARGET)
    assert TARGET[support["start"]:support["end"]] == support["quote"]
    with pytest.raises(KernelError):
        validate_support(local["supporting_evidence"], window())


def test_mixed_current_and_earlier_support_preserves_separate_exact_sources():
    local = issue("SPATIAL_ACTION_CONTINUITY")
    local["supporting_evidence"].append({"asset_version_id": "revision:2", "quote": TARGET[-7:],
        "relation_to_issue": "Current revised action."})
    result = paired_diagnosis(local, text=TARGET, window=window(), target_asset_version_id="revision:2")
    assert result["supporting_evidence"][0]["asset_version_id"] == "accepted:1"
    assert result["candidate_supporting_evidence"][0]["asset_version_id"] == "revision:2"
    local["supporting_evidence"][-1]["quote"] = "fabricated passage"
    with pytest.raises(KernelError):
        paired_diagnosis(local, text=TARGET, window=window(), target_asset_version_id="revision:2")


@pytest.mark.parametrize(
    "field,value",
    [
        ("quote", "虚构引文"),
        ("start", -1),
        ("end", 999),
        ("asset_version_id", "unaccepted"),
        ("text_hash", "wrong"),
        ("content_hash", "wrong"),
        ("chapter_number", 99),
    ],
)
def test_support_requires_exact_source_hash_unicode_span_and_quote(field, value):
    evidence = support()
    evidence[field] = value
    with pytest.raises(KernelError):
        validate_support([evidence], window())


def test_unicode_code_points_and_target_hash_are_checked():
    text = "甲😀乙"
    snapshot = source_snapshot(texts=(text,))
    frozen = window(snapshot)
    source = frozen["sources"][0]
    evidence = {
        **support(),
        **{k: source[k] for k in ("asset_version_id", "content_hash", "text_hash")},
        "start": 1,
        "end": 2,
        "quote": "😀",
    }
    assert (
        validate_support([evidence], frozen)[0]["offset_unit"] == "UNICODE_CODE_POINT"
    )
    bad = issue()
    bad["evidence"]["text_hash"] = "wrong"
    with pytest.raises(KernelError):
        initial([bad])


@pytest.mark.parametrize("category", sorted(CROSS_CHAPTER_CATEGORIES))
def test_all_cross_chapter_categories_retain_paired_evidence(category):
    reviewed = initial([issue(category)])
    assert reviewed["issues"][0]["supporting_evidence"][0]["quote"] == SOURCE[:7]
    assert (
        reviewed["cross_chapter_coverage"]["reviewed_sources"][0]["coverage"] == "FULL"
    )


def test_same_category_locations_are_distinct_and_lineage_survives_candidate_change():
    review = initial([issue(), issue(start=8, end=12)])
    assert len({item["code"] for item in review["issues"]}) == 2
    relocated = issue(start=8, end=12)
    relocated["lineage_code"] = review["issues"][0]["code"]
    assert (
        paired_diagnosis(relocated, text=TARGET, window=window(), prior=review)["code"]
        == review["issues"][0]["code"]
    )
    relocated["supporting_evidence"][0].update(start=1, quote=SOURCE[1:7])
    unmatched = paired_diagnosis(relocated, text=TARGET, window=window(), prior=review)
    assert unmatched["code"] != review["issues"][0]["code"]
    assert unmatched["lineage_status"] == "UNVERIFIED"


def test_changed_valid_support_preserves_old_issue_and_records_unverified_lineage():
    review = initial([issue()])
    changed = issue(start=8, end=12)
    changed["lineage_code"] = review["issues"][0]["code"]
    changed["supporting_evidence"][0].update(start=1, end=7, quote=SOURCE[1:7])
    current = paired_diagnosis(changed, text=TARGET, window=window(), prior=review)
    assert current["code"] != review["issues"][0]["code"]
    assert current["unverified_lineage_code"] == review["issues"][0]["code"]
    assert current["lineage_status"] == "UNVERIFIED"
    assert review["issues"][0]["supporting_evidence"][0]["quote"] == SOURCE[:7]


def test_reassessment_cannot_replace_prior_contradiction_with_uncertainty_at_the_same_spans():
    review = initial([issue()])
    changed = issue()
    changed.update(lineage_code=review["issues"][0]["code"], judgment_kind="UNCERTAIN",
        severity="major", confidence="MEDIUM", interpretation="UNCERTAIN")
    current = paired_diagnosis(changed, text=TARGET, window=window(), prior=review)
    assert current["code"] != review["issues"][0]["code"]
    assert current["lineage_status"] == "UNVERIFIED"
    assert review["issues"][0]["judgment_kind"] == "SEMANTIC_CONTRADICTION"


@pytest.mark.parametrize("field", ["violated_constraint", "revision_goal", "preserve", "acceptance_criteria", "repair"])
def test_same_support_cannot_rebind_an_existing_problem_to_a_different_repair_goal(field):
    review = initial([issue()])
    changed = issue()
    changed["lineage_code"] = review["issues"][0]["code"]
    changed[field] = {"repair_scope": "CHAPTER_REVISION"} if field == "repair" else ["另一目标"] if field in {"preserve", "acceptance_criteria"} else "另一目标"
    if field == "repair":
        changed[field] = {"root_cause": "CHAPTER_STRUCTURE", "problem_owner": "PROSE", "repair_scope": "CHAPTER_REVISION",
            "revision_goal": "另一目标", "preserve": ["原事实"], "resolution_criteria": ["另一标准"]}
    current = paired_diagnosis(changed, text=TARGET, window=window(), prior=review)
    assert current["code"] != review["issues"][0]["code"]
    assert current["unverified_lineage_code"] == review["issues"][0]["code"]
    assert current["lineage_status"] == "UNVERIFIED"


@pytest.mark.parametrize("status", ["UNRESOLVED", "PARTIALLY_RESOLVED", "RESOLVED"])
def test_incomplete_original_support_keeps_resolution_unverified_and_preserves_evidence(status):
    from novel_forge.modules.review.cross_chapter import resolution_checks

    review = initial([issue()])
    result = deepcopy(rereview_result(review))
    check = result["resolution_checks"][0]
    check["status"] = status
    check["supporting_evidence"][0].update(start=1, end=7, quote=SOURCE[1:7])
    normalized = resolution_checks(result, review, TARGET)[0]
    assert normalized["status"] == ("UNRESOLVED" if status == "RESOLVED" else status)
    assert normalized["claimed_resolution_status"] == status
    assert normalized["supporting_evidence"] == review["issues"][0]["supporting_evidence"]
    assert normalized["reassessment_supporting_evidence"][0]["quote"] == SOURCE[1:7]
    actual = rereview(review, result)
    assert not actual["resolved_issue_codes"]
    assert review["issues"][0]["code"] in actual["remaining_issue_codes"]


@pytest.mark.parametrize(
    "interpretation",
    ["INTENTIONAL_RECAP", "MOTIF", "REINTERPRETATION", "MOTIVATED_CHANGE"],
)
def test_intentional_repetition_or_change_cannot_become_blocker(interpretation):
    value = issue("REDUNDANT_RETELLING")
    value["interpretation"] = interpretation
    with pytest.raises(KernelError):
        initial([value])
    assert initial([])["issues"] == []


def test_targeted_edit_cannot_rewrite_unrelated_prose():
    review = initial()
    edit = {
        "start": 0,
        "end": 7,
        "quote": TARGET[:7],
        "replacement": "沈舟左臂带伤，",
        "issue_codes": [review["issues"][0]["code"]],
    }
    result = {"edits": [edit], "text": edit["replacement"] + TARGET[7:]}
    assert apply_targeted_edits(draft={"text": TARGET}, review=review, result=result)[
        "targeted_edits"
    ] == [edit]
    result["text"] += "无关大改。"
    with pytest.raises(KernelError):
        apply_targeted_edits(draft={"text": TARGET}, review=review, result=result)


def test_rereview_requires_every_prior_issue_and_preservation_dimension():
    review = initial()
    result = rereview_result(review)
    after = rereview(review, result)
    assert after["cross_chapter_window"] == review["cross_chapter_window"]
    assert after["resolved_issue_codes"] == [review["issues"][0]["code"]]
    result["resolution_checks"] = []
    with pytest.raises(KernelError):
        rereview(review, result)
    result = rereview_result(review)
    result["preservation_checks"].pop()
    with pytest.raises(KernelError):
        rereview(review, result)


def test_high_score_cannot_replace_unresolved_or_regressed_candidate():
    previous = CandidateEvidence("a", {"text": "original prose"}, 60, ("issue",), "review")
    challenger = CandidateEvidence(
        "b",
        {"text": "revised prose"},
        99,
        ("issue",),
        "rereview",
        "actionable-diagnostics.v1",
        ({"code": "issue", "status": "SATISFIED", "preservation": "PRESERVED", "evidence": {"quote": "revised prose"},
          "reason": "The diagnosed problem is repaired in the cited passage."},),
        cross_chapter_review=True,
        resolved_issue_codes=("issue",),
        preservation_checks=tuple(
            {"dimension": dimension, "status": "PRESERVED", "reason": "The revised passage retains this dimension.",
             "evidence": {"quote": "revised prose"}} for dimension in PRESERVATION_DIMENSIONS
        ),
    )

    def selected(value):
        return compare_candidates(
            project_id="p",
            chapter_root_operation_id="root",
            previous=previous,
            challenger=value,
            minimum_net_improvement=1,
        )["selected_asset_version_id"]

    assert selected(challenger) == "a"
    challenger = replace(challenger, blocker_codes=())
    assert selected(challenger) == "b"
    assert (
        selected(replace(challenger, preservation_checks=({"status": "REGRESSED"},)))
        == "a"
    )
    assert selected(replace(challenger, preservation_checks=tuple(
        {**check, "dimension": PRESERVATION_DIMENSIONS[0]} for check in challenger.preservation_checks))) == "a"
    for status in ("UNCERTAIN", "REGRESSED"):
        assert selected(replace(challenger, preservation_checks=tuple(
            {**check, "status": status} if index == 0 else check
            for index, check in enumerate(challenger.preservation_checks)))) == "a"


def test_provider_views_isolate_history_and_schema_keeps_legacy_contract():
    payload = {
        "draft": {"text": TARGET},
        "cross_chapter_window": window(),
        "target_candidate_asset_version_id": "draft:2",
    }
    review = build_provider_task_view("review", payload)
    assert review["cross_chapter_window"]["sources"][0]["excerpts"][0]["text"] == SOURCE
    assert SOURCE not in str(build_provider_task_view("draft", payload))
    old = chapter_provider_output_schema("review", legacy_contract=True)
    new = extend_provider_schema(old, "review", legacy_contract=True)
    assert "preservation_checks" not in old["properties"]
    response = {
        "score": 60,
        "issues": [issue()],
        "resolution_checks": [],
        "knowledge_checks": [],
        "preservation_checks": [],
    }
    assert (
        validate_chapter_provider_output_against_schema("review", new, response)
        == response
    )
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema("review", old, response)


def test_normal_chinese_chapter_uses_token_estimate_then_complete_admission():
    text = "沈舟沿着石阶退到东门，左臂的旧伤仍使他不能举剑。" * 120
    frozen = freeze_review_window(source_snapshot(), candidate_id="draft", text=text,
                                 context_token_budget=6000, protected_context={},
                                 required_context={"craft": "交代目标、空间和代价。" * 20})
    assert len(text.encode()) > 6000
    assert frozen["sources"][0]["coverage"] == "FULL"
    meter = frozen["selection_meter"]
    assert meter["precision"] == "ESTIMATE_ONLY"
    assert meter["required_context_tokens"] + meter["source_tokens"] + meter["safety_margin_tokens"] <= 6000
    with pytest.raises(KernelError, match="CONTEXT_INSUFFICIENT"):
        freeze_review_window(source_snapshot(), candidate_id="draft", text=text * 3,
                             context_token_budget=6000, protected_context={})


def test_schema_normalization_and_domain_agree_on_judgment_combinations():
    from itertools import product
    from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
    schema = extend_provider_schema(chapter_provider_output_schema("review", legacy_contract=True), "review", legacy_contract=True)
    judgments = ["SEMANTIC_CONFLICT", "SEMANTIC_CONTRADICTION", "LIKELY_CONTINUITY_PROBLEM", "AESTHETIC_SUGGESTION", "UNCERTAIN"]
    for category, judgment, severity, confidence, interpretation in product(
        ["CRAFT_EFFECT", "CAUSAL_CARRYOVER"], judgments, ["blocking", "major", "minor"],
        ["HIGH", "LOW"], ["CONTINUITY_PROBLEM", "MOTIVATED_CHANGE"],
    ):
        value = {**issue(category), "judgment_kind": judgment, "severity": severity,
                 "confidence": confidence, "interpretation": interpretation}
        raw = {"score": 70, "issues": [value], "knowledge_checks": [], "resolution_checks": [], "preservation_checks": []}
        try:
            validate_chapter_provider_output_against_schema("review", schema, raw)
            structural = True
        except KernelError:
            structural = False
        try:
            normalized = normalize_model_output("review", raw)
            evaluate_review_result(project_id="p", target_asset_version_id="draft:2", context_bundle_version_id="ctx",
                                   chapter=2, result=normalized, provider_evidence={}, prose_text=TARGET, cross_chapter_window=window())
            domain = True
        except KernelError:
            domain = False
        assert structural == domain, (category, judgment, severity, confidence, interpretation)


def test_rereview_materialized_task_retains_exact_before_and_changed_target():
    original = " \n沈舟😀走到门边。\r\n他没有回头。 "
    revised = original.replace("走到", "退到")
    task = build_provider_task_view("rereview", {
        "original_draft": {"text": original}, "original_draft_asset_version_id": "before:v1",
        "revision": {"text": revised}, "target_candidate_asset_version_id": "after:v1",
        "review": {"issues": []}, "cross_chapter_window": window(),
    })
    comparison = task["prose_comparison"]
    assert comparison["original"] == {"asset_version_id": "before:v1", "text_hash": prose_hash(original), "text": original}
    assert comparison["revised"]["asset_version_id"] == task["target_identity"]["asset_version_id"] == "after:v1"
    assert task["cross_chapter_window"]["target_candidate_asset_version_id"] == "draft:2"
    assert comparison["coverage"] == "COMPLETE_BEFORE_AND_AFTER"
    for span in comparison["unchanged_ranges"]:
        before = original[span["before_start"]:span["before_end"]]
        after = revised[span["after_start"]:span["after_end"]]
        assert before == after and prose_hash(before) == span["text_hash"]


def test_compact_rereview_comparison_preserves_complete_bodies_and_derivable_changes():
    from novel_forge.modules.review.prose_comparison import prose_comparison
    original = " \n沈舟😀走到门边。\r\n他没有回头。 "
    revised = original.replace("走到", "退到").replace("他没有回头。", "他没有回头。他先把门推开。")
    task = build_provider_task_view("rereview", {
        "original_draft": {"text": original}, "original_draft_asset_version_id": "before:v1",
        "revision": {"text": revised}, "target_candidate_asset_version_id": "after:v1",
        "review": {"issues": []},
    }, compact_contract=True)
    comparison = task["prose_comparison"]
    canonical = prose_comparison({"text": original}, {"text": revised}, original_id="before:v1", revised_id="after:v1")
    assert comparison["contract_version"] == "exact-prose-comparison-view.v1"
    assert comparison["original"] == canonical["original"]
    assert comparison["revised"] == canonical["revised"]
    assert task["revised_chapter"]["text"] == revised
    assert comparison["coverage"] == "COMPLETE_BEFORE_AND_AFTER"
    assert comparison["semantic_preservation"] == "REQUIRES_REVIEW"
    for span, full in zip(comparison["edits"], canonical["edits"], strict=True):
        assert original[span["before_start"]:span["before_end"]] == full["before"]
        assert revised[span["after_start"]:span["after_end"]] == full["after"]
        assert set(span) == {"before_start", "before_end", "after_start", "after_end"}
    for span in comparison["unchanged_ranges"]:
        assert original[span["before_start"]:span["before_end"]] == revised[span["after_start"]:span["after_end"]]


def test_unresolved_issue_moves_to_exact_new_span_without_losing_origin():
    review = initial()
    text = "雨落了下来。" + TARGET
    result = rereview_result(review, text=text, status="UNRESOLVED")
    result["resolution_checks"][0]["evidence"] = {"start": 6, "end": 13, "quote": text[6:13]}
    after = evaluate_rereview_result(project_id="p", original_draft_version_id="draft:2",
        initial_review_version_id="review:2", revision_version_id="revision:2", context_bundle_version_id="ctx",
        initial_review=review, revision={"chapter": 2, "text": text}, result=result, provider_evidence={})
    carried = after["unresolved_issues"][0]
    assert carried["code"] == review["issues"][0]["code"]
    assert carried["evidence_locator"]["quote"] == text[6:13]
    assert carried["target_text_hash"] == prose_hash(text)
    assert carried["origin_evidence_locator"] == review["issues"][0]["evidence_locator"]
    assert after["blocking_issue_count"] == 1


@pytest.mark.parametrize('sampling', [False, True])
def test_native_review_preflight_and_handler_keep_exact_incumbent_and_sample_target(sampling):
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset
    from novel_forge.modules.chapter_authority.review_window import prepare_native_review

    selected_review = {'score': 80, 'issues': [], 'selection_review_source_asset_version_id': 'kept-review:v1'}
    incumbent = {'text': '沈舟伤臂仍然不能抬起。', 'selected_source_asset_version_id': 'kept:v1',
                 'selected_review': selected_review, 'candidate_comparison': {
                     'selected_asset_version_id': 'kept:v1',
                     'previous': {'asset_version_id': 'kept:v1', 'score': 80, 'blocker_codes': [], 'review_asset_version_id': 'kept-review:v1'},
                     'challenger': {'asset_version_id': 'rejected:v1'}}}
    target = {'text': '沈舟用右手推开东门。'}
    target_id = 'sample:v1' if sampling else 'revision:v1'
    target_content = {'sampled_asset_type': 'draft_version', 'sampled_output': target, 'production_eligible': False} if sampling else target
    command = {'chapter': 2, **({'chapter_sampling': {'generation_sample': {
        'asset_version_id': target_id, 'content_hash': digest(target_content)}}} if sampling else {})}
    values = [('original:v1', 'draft_chapter', {'text': TARGET}), ('review:v1', 'review_report', {'issues': []}),
              ('context:v1', 'context_bundle', {}), ('incumbent:v1', 'best_draft_candidate', incumbent),
              (target_id, 'chapter_provider_sample' if sampling else 'draft_version', target_content)]
    request = ChapterHandlerRequest('operation', 'p', 'w', 'trace', 'correlation', command,
        tuple(ChapterInputAsset(identity, kind, digest(content), content) for identity, kind, content in values))
    _, _, _, _, payload = prepare_native_review(request, stage='rereview')
    assert payload['original_draft_asset_version_id'] == 'kept:v1'
    assert payload['original_draft']['text'] == incumbent['text']
    assert payload['review'] == selected_review
    assert payload['target_candidate_asset_version_id'] == target_id
    assert payload['draft'] == payload['revision'] == target
