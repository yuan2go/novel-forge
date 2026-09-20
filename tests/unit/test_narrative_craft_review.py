from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRequest,
    ChapterInputAsset,
)
from novel_forge.modules.chapter_authority.domain_handlers import (
    normalize_review_result,
    normalize_rereview_result,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
    default_chapter_fixture_response,
)
from novel_forge.modules.chapter_authority.handlers import (
    _ReviewHandler,
    _RevisionHandler,
    _ReReviewHandler,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ModelProviderResult,
    normalize_model_output,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_task_view,
)
from novel_forge.modules.chapter_authority.realization_composition import (
    compile_realization_contract,
    integrate_realization,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import core_catalog, craft_hash
from novel_forge.modules.mkaos_authority.craft_selection import (
    DEFAULT_CRAFT_POLICY,
    build_craft_strategy,
)
from novel_forge.modules.review.craft import (
    PRESERVATION_DIMENSIONS,
    SIDE_EFFECTS,
    craft_review_targets,
    craft_trace_projection,
    extend_craft_provider_schema,
)
from novel_forge.modules.review.diagnostics import prose_hash
from novel_forge.modules.revision.domain import apply_revision_result


CORPUS = json.loads(
    (
        Path(__file__).parents[1] / "fixtures/narrative_craft/original_controls.json"
    ).read_text()
)
CASES = CORPUS["cases"]


def draft_for(case=CASES[0], mode="misuse", second_scene=False, with_craft=True):
    mechanism = next(
        item for item in core_catalog() if item["mechanism_id"] == case["mechanism_id"]
    )
    scenes = [
        {
            "scene_id": "scene:control",
            "goal": case["frozen_scene_contract"],
            "beats": [{"beat_id": "beat:one"}],
        }
    ]
    if second_scene:
        scenes.insert(
            0,
            {
                "scene_id": "scene:unrelated",
                "goal": "Keep prior action unchanged",
                "beats": [{"beat_id": "beat:zero"}],
            },
        )
    site = {
        "target_pointer": f"/scene_plan/{1 if second_scene else 0}/goal",
        "realization_excerpt": case["frozen_scene_contract"],
        "expected_application": "Implement the chosen original control without new story facts",
        "preservation_requirements": [case["preservation"]],
        "verification_checks": [case["expected_structural_signal"]],
        "craft_role": "PRIMARY",
        "craft_sequence": 1,
        "intended_reader_effect": mechanism["desired_reader_effect"],
    }
    translation = {
        "knowledge_card_asset_version_id": "card:control:v1",
        "decision": "ADAPT",
        "usage_role": "MECHANISM",
        "use_sites": [site],
        "rationale": "Original bounded control scene",
        "prerequisite_resolution": "The control supplies its frozen scene prerequisites",
    }
    strategy = build_craft_strategy(
        {"scene_plan": scenes, "knowledge_translations": [translation]},
        {
            "selection_digest": craft_hash({"card": craft_hash(mechanism)}),
            "craft_policy": DEFAULT_CRAFT_POLICY,
            "selected": [
                {
                    "knowledge_card_asset_version_id": "card:control:v1",
                    "content_hash": craft_hash(mechanism),
                    "selected_content": {"craft_mechanism": mechanism},
                }
            ],
        },
    )
    contract = compile_realization_contract(
        {"scene_plan": scenes, **({"craft_strategy": strategy} if with_craft else {})},
        {},
    )
    artifacts = [
        {
            "slot_id": slot["slot_id"],
            "text": case[mode] if slot["scene_id"] == "scene:control" else "雨还在下。",
            "used_fact_ids": [],
        }
        for slot in contract["slots"]
    ]
    text = "\n\n".join(item["text"] for item in artifacts)
    return {
        "chapter": 1,
        "title": case["category"],
        "text": text,
        **integrate_realization(contract=contract, artifacts=artifacts, text=text),
    }


def effect_check(draft, status="FAILED", side="MISUSE"):
    target = craft_review_targets(draft)[0]
    span = target["scene_ranges"][0]
    evidence = {**span, "quote": draft["text"][span["start"] : span["end"]]}
    issues = ["CRAFT_CONTROL"] if status == "FAILED" else []
    return {
        "use_id": target["use_id"],
        "effect_status": status,
        "evidence": evidence,
        "reason": "Scripted original control: semantic judgment is supplied by the test oracle, not independently measured.",
        "signals_checked": target["mechanism"]["success_signals"],
        "issue_codes": issues,
        "side_effects": [
            {
                "kind": kind,
                "status": "PRESENT" if kind == side and status == "FAILED" else "CLEAR",
                "evidence": evidence,
                "reason": "Original control rubric assessment; no reader evidence.",
                "issue_codes": issues if kind == side else [],
            }
            for kind in SIDE_EFFECTS
        ],
    }


def review_output(draft, status="FAILED", side="MISUSE"):
    check = effect_check(draft, status, side)
    return {
        "score": 70 if status == "FAILED" else 90,
        "issues": [
            {
                "code": "CRAFT_CONTROL",
                "severity": "minor",
                "message": "Control requires a bounded craft repair",
                "category": "CRAFT_EFFECT",
                "judgment_kind": "AESTHETIC_SUGGESTION",
                "evidence": check["evidence"],
                "violated_constraint": "The adopted effect was not observed",
                "revision_goal": "Repair this scene's chosen realization without altering its events",
                "preserve": craft_review_targets(draft)[0]["preservation_requirements"],
                "acceptance_criteria": [
                    "The scene realizes its chosen effect without the diagnosed misuse"
                ],
            }
        ]
        if status == "FAILED"
        else [],
        "resolution_checks": [],
        "knowledge_checks": [],
        "craft_checks": [check],
    }


def initial_review(draft, status="FAILED", side="MISUSE"):
    return normalize_review_result(
        draft=draft,
        draft_asset_version_id="draft:v1",
        result=normalize_model_output("review", review_output(draft, status, side)),
        provider_evidence={},
        project_id="project",
        context_bundle_version_id="context:v1",
    )


def repair_output(draft, case=CASES[0]):
    span = craft_review_targets(draft)[0]["scene_ranges"][0]
    artifacts = deepcopy(draft["scene_artifacts"])
    artifacts[-1]["text"] = case["targeted_repair"]
    text = "\n\n".join(item["text"] for item in artifacts)
    return {
        "text": text,
        "scene_artifacts": artifacts,
        "resolved_issue_codes": ["CRAFT_CONTROL"],
        "edits": [
            {
                **span,
                "quote": draft["text"][span["start"] : span["end"]],
                "replacement": case["targeted_repair"],
                "issue_codes": ["CRAFT_CONTROL"],
            }
        ],
    }


def apply_repair(draft, review, output):
    return apply_revision_result(
        project_id="project",
        draft=draft,
        review=review,
        draft_asset_version_id="draft:v1",
        review_asset_version_id="review:v1",
        context_bundle_version_id="context:v1",
        result=output,
        provider_evidence={},
    )


def rereview_output(revision, status="ACHIEVED", preservation="PRESERVED"):
    value = review_output(revision, status)
    evidence = effect_check(revision)["evidence"]
    value["resolution_checks"] = [
        {
            "code": "CRAFT_CONTROL",
            "status": "SATISFIED",
            "preservation": "PRESERVED",
            "evidence": evidence,
            "reason": "Original scripted control meets the repair rubric.",
        }
    ]
    value["craft_preservation_checks"] = [
        {
            "dimension": dimension,
            "status": preservation,
            "evidence": evidence,
            "reason": "Scripted control preserves original scene constraints.",
        }
        for dimension in PRESERVATION_DIMENSIONS
    ]
    return value


def rereview(review, revision, output):
    return normalize_rereview_result(
        draft_asset_version_id="draft:v1",
        review=review,
        review_asset_version_id="review:v1",
        revision=revision,
        revision_asset_version_id="revision:v1",
        context_bundle_version_id="context:v1",
        result=normalize_model_output("rereview", output),
        provider_evidence={},
        project_id="project",
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_original_controls_preserve_evidence_through_review_targeted_revision_and_rereview(
    case,
):
    assert CORPUS["origin"] == "REPOSITORY_ORIGINAL"
    assert not CORPUS["creative_quality_proven"] and not CORPUS["reader_effect_proven"]
    baseline = draft_for(case, "baseline", with_craft=False)
    assert craft_review_targets(baseline) == []
    assert "craft_review_targets" not in build_provider_task_view(
        "review", {"draft": baseline}
    )
    guided = draft_for(case, "craft_guided")
    guided_review = initial_review(guided, "ACHIEVED")
    draft = draft_for(case, second_scene=True)
    review = initial_review(draft)
    output = repair_output(draft, case)
    revised = apply_repair(draft, review, output)
    after = rereview(review, revised, rereview_output(revised))
    assert revised["text"].startswith("雨还在下。\n\n")
    assert revised["realization_contract"] == draft["realization_contract"]
    assert after["resolved_issue_codes"] == ["CRAFT_CONTROL"]
    assert after["craft_checks"][0]["effect_status"] == "ACHIEVED"
    for observed in [guided_review, review, after]:
        check = observed["craft_checks"][0]
        assert (
            check["evidence_class"] == "FIXTURE_SEMANTIC_REVIEW"
            and not check["reader_effect_proven"]
        )
        assert check["target_text_hash"] == observed["target_text_hash"]
        assert check["knowledge_card_asset_version_id"] == "card:control:v1"
    task = build_provider_task_view("revision", {"draft": draft, "review": review})
    assert (
        task["craft_targeted_repair"]["selection_digest"]
        == draft["realization_contract"]["craft_strategy"]["selection_digest"]
    )
    assert task["chapter"]["text"] == draft["text"]
    assert task["review_issues"][0]["evidence_locator"]["quote"] == case["misuse"]


def test_wrong_scene_literal_quote_does_not_count_as_selected_craft_effect():
    draft = draft_for(second_scene=True)
    raw = review_output(draft, "ACHIEVED")
    raw["craft_checks"][0]["evidence"] = {"start": 0, "end": 5, "quote": "雨还在下。"}
    with pytest.raises(KernelError, match="CRAFT_REVIEW_SCENE_MISMATCH"):
        normalize_review_result(
            draft=draft,
            draft_asset_version_id="draft:v1",
            result=normalize_model_output("review", raw),
            provider_evidence={},
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "omit",
        "foreign_use",
        "fabricated_quote",
        "unlinked_failure",
        "missing_side",
        "subjective_blocker",
    ],
)
def test_craft_review_fails_closed_on_incomplete_or_invalid_evidence(tamper):
    draft = draft_for()
    raw = review_output(draft)
    check = raw["craft_checks"][0]
    if tamper == "omit":
        raw["craft_checks"] = []
    if tamper == "foreign_use":
        check["use_id"] = "unselected"
    if tamper == "fabricated_quote":
        check["evidence"]["quote"] = "invented"
    if tamper == "unlinked_failure":
        check["issue_codes"] = []
    if tamper == "missing_side":
        check["side_effects"].pop()
    if tamper == "subjective_blocker":
        raw["issues"][0].update(severity="blocking", judgment_kind="SEMANTIC_CONFLICT")
    with pytest.raises(KernelError):
        normalize_review_result(
            draft=draft,
            draft_asset_version_id="draft:v1",
            result=normalize_model_output("review", raw),
            provider_evidence={},
        )


def test_frozen_selection_hash_drift_and_revision_outside_diagnosis_are_rejected():
    draft = draft_for(second_scene=True)
    review = initial_review(draft)
    output = repair_output(draft)
    output["edits"][0]["start"] = 0
    output["edits"][0]["quote"] = draft["text"]
    with pytest.raises(KernelError, match="outside diagnosed"):
        apply_repair(draft, review, output)
    changed = deepcopy(draft)
    changed["realization_contract"]["craft_strategy"]["uses"][0][
        "intended_reader_effect"
    ] = "replace approved effect"
    with pytest.raises(KernelError, match="CRAFT_STRATEGY_DRIFT"):
        craft_review_targets(changed)
    changed = deepcopy(review)
    changed["target_text_hash"] = "sha256:changed"
    with pytest.raises(KernelError, match="REVISION_DIAGNOSIS_STALE"):
        apply_repair(draft, changed, repair_output(draft))


@pytest.mark.parametrize("dimension", PRESERVATION_DIMENSIONS)
def test_rereview_cannot_close_issue_if_preservation_regressed(dimension):
    draft = draft_for()
    review = initial_review(draft)
    revised = apply_repair(draft, review, repair_output(draft))
    raw = rereview_output(revised)
    next(
        item
        for item in raw["craft_preservation_checks"]
        if item["dimension"] == dimension
    )["status"] = "REGRESSED"
    after = rereview(review, revised, raw)
    assert after["resolved_issue_codes"] == []
    assert after["remaining_issue_codes"] == ["CRAFT_CONTROL"]
    assert after["resolution_checks"][0]["preservation"] == "REGRESSED"


def test_review_schema_is_selected_from_actual_frozen_inputs_and_legacy_stays_compatible():
    gateway = object.__new__(PostgresChapterExecutionContractBinder)
    draft = draft_for()
    for stage in ("review", "revision", "rereview"):
        schema, ref = gateway._provider_output_contract(
            stage=stage, request_payload={"input": {"draft": draft}}
        )
        assert ref.endswith(":narrative-craft-v1")
        assert ("edits" if stage == "revision" else "craft_checks") in schema[
            "required"
        ]
        legacy, legacy_ref = gateway._provider_output_contract(
            stage=stage, request_payload={"input": {"draft": {"text": "旧正文"}}}
        )
        assert (
            "craft_checks" not in legacy["properties"]
            and "narrative-craft" not in legacy_ref
        )
    quality_schema, quality_ref = gateway._provider_output_contract(
        stage="revision",
        request_payload={
            "input": {
                "draft": draft,
                "required_actions": [{"observation": "chapter_length"}],
            }
        },
    )
    assert (
        "edits" not in quality_schema["required"]
        and "narrative-craft" not in quality_ref
    )
    raw = review_output(draft)
    schema = extend_craft_provider_schema(
        chapter_provider_output_schema("review"), "review"
    )
    assert validate_chapter_provider_output_against_schema("review", schema, raw) == raw
    raw.pop("craft_checks")
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema("review", schema, raw)


def test_scripted_transport_does_not_manufacture_reader_effect_or_preservation():
    draft = draft_for()
    raw = default_chapter_fixture_response("review", {"draft": draft})
    assert raw["craft_checks"][0]["effect_status"] == "UNCERTAIN"
    raw = default_chapter_fixture_response(
        "rereview", {"revision": draft, "review": {"issues": []}}
    )
    assert all(
        item["status"] == "UNCERTAIN" for item in raw["craft_preservation_checks"]
    )


class ControlledProvider:
    def __init__(self):
        self.calls = []

    def invoke(self, request, *, stage, payload):
        task = build_provider_task_view(stage, payload)
        self.calls.append((stage, task))
        if stage == "review":
            raw = review_output(payload["draft"])
        elif stage == "revision":
            raw = repair_output(payload["draft"])
        else:
            raw = rereview_output(payload["revision"])
        schema, _ = object.__new__(
            PostgresChapterExecutionContractBinder
        )._provider_output_contract(stage=stage, request_payload={"input": payload})
        validate_chapter_provider_output_against_schema(stage, schema, raw)
        return ModelProviderResult(
            output=normalize_model_output(stage, raw),
            provider_id="scripted-control",
            model_id="original-prose-control",
            prompt_version="control-v1",
            skill_version="control-v1",
            input_tokens=0,
            output_tokens=0,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
        )


def test_canonical_handlers_thread_exact_scene_checks_and_targeted_repair_to_real_provider_views():
    provider = ControlledProvider()
    draft = draft_for()

    def asset(kind, identity, content):
        return ChapterInputAsset(identity, kind, craft_hash(content), content)

    inputs = (
        asset("draft_chapter", "draft:v1", draft),
        asset("context_bundle", "context:v1", {}),
    )
    request = ChapterHandlerRequest(
        "operation", "project", "workspace", "trace", "root", {}, inputs
    )
    review = _ReviewHandler(provider).execute(request).content
    revision_request = replace(
        request, inputs=(*inputs, asset("review_report", "review:v1", review))
    )
    revision = _RevisionHandler(provider).execute(revision_request).content
    final = (
        _ReReviewHandler(provider)
        .execute(
            replace(
                revision_request,
                inputs=(
                    *revision_request.inputs,
                    asset("draft_version", "revision:v1", revision),
                ),
            )
        )
        .content
    )
    assert [stage for stage, task in provider.calls] == [
        "review",
        "revision",
        "rereview",
    ]
    assert (
        provider.calls[0][1]["craft_review_targets"][0]["scene_id"] == "scene:control"
    )
    assert (
        provider.calls[1][1]["craft_targeted_repair"]["contract_version"]
        == "narrative-craft-targeted-repair.v1"
    )
    assert provider.calls[2][1]["prior_craft_checks"][0]["effect_status"] == "FAILED"
    assert final["craft_checks"][0]["effect_status"] == "ACHIEVED" and final[
        "resolved_issue_codes"
    ] == ["CRAFT_CONTROL"]
    workspace = {
        "artifacts": {
            "candidates": [
                {
                    "asset_type": "draft_chapter",
                    "asset_version_id": "draft:v1",
                    "content": draft,
                }
            ],
            "diagnoses": [
                {
                    "asset_type": "review_report",
                    "asset_version_id": "review:v1",
                    "content": review,
                },
                {
                    "asset_type": "re_review_report",
                    "asset_version_id": "rereview:v1",
                    "content": final,
                },
            ],
        },
        "acceptance": None,
    }
    trace = craft_trace_projection(workspace)
    assert trace["candidates"][0]["text_hash"] == prose_hash(draft["text"])
    assert len(trace["reviews"]) == 2 and not trace["reader_effect_proven"]
    assert len(trace["effect_observations"]) == 2
    assert trace["effect_observations"][0]["effect_status"] == "FAILED"
    assert trace["effect_observations"][0]["actual_genre"] is None
    assert trace["reader_human_evidence"]["availability"] == "NOT_RECORDED"
    assert (
        trace["effect_observations"][0]["review_model_id"] == "original-prose-control"
    )
    assert trace["effect_observations"][0]["accepted_lineage"] is None
    assert trace["effect_observations"][0]["declared_mechanism_affinity"]


def test_cross_chapter_resolution_cannot_erase_craft_preservation_regression():
    from tests.unit.test_cross_chapter_prose_review import window
    from novel_forge.modules.review.prose_window import (
        PRESERVATION_DIMENSIONS as CROSS_DIMENSIONS,
    )

    draft = draft_for()
    raw = review_output(draft)
    raw["issues"][0]["evidence"] = {
        **raw["issues"][0]["evidence"],
        "asset_version_id": "draft:v1",
        "text_hash": prose_hash(draft["text"]),
    }
    review = normalize_review_result(
        draft=draft,
        draft_asset_version_id="draft:v1",
        result=normalize_model_output("review", raw),
        provider_evidence={},
        project_id="project",
        context_bundle_version_id="context:v1",
        cross_chapter_window=window(),
    )
    revision = apply_repair(draft, review, repair_output(draft))
    raw = rereview_output(revision)
    evidence = raw["craft_checks"][0]["evidence"]
    raw["resolution_checks"][0].update(status="RESOLVED", supporting_evidence=[])
    raw["preservation_checks"] = [
        {
            "dimension": dimension,
            "status": "PRESERVED",
            "evidence": evidence,
            "reason": "Scripted cross-chapter control",
        }
        for dimension in CROSS_DIMENSIONS
    ]
    raw["craft_preservation_checks"][0]["status"] = "REGRESSED"
    after = rereview(review, revision, raw)
    assert after["resolution_checks"][0]["status"] == "SATISFIED"
    assert after["resolution_checks"][0]["preservation"] == "REGRESSED"
    assert after["resolved_issue_codes"] == []


def test_previously_achieved_craft_cannot_be_lost_while_claiming_preservation():
    draft = draft_for(mode="craft_guided")
    review = initial_review(draft, "ACHIEVED")
    raw = rereview_output(draft, "UNCERTAIN")
    raw["resolution_checks"] = []
    with pytest.raises(KernelError, match="CRAFT_PRESERVATION_CONFLICT"):
        rereview(review, draft, raw)
    next(
        item
        for item in raw["craft_preservation_checks"]
        if item["dimension"] == "SATISFIED_CRAFT"
    )["status"] = "UNCERTAIN"
    after = rereview(review, draft, raw)
    assert after["craft_regressed_use_ids"] == [review["craft_targets"][0]["use_id"]]
    assert after["craft_preservation_status"] == "UNCERTAIN"
