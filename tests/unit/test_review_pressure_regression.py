from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from novel_forge.modules.chapter_quality_authority.paired_regression import (
    Corpus, FindingsAnnotation, Judgment, Result, build_request, load_corpus, plan,
    request_id, result_hash, score, slots,
)
from novel_forge.modules.command_kernel.routing_bootstrap import authorization_hash


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "config/evaluation/model_reference_pressure_v1.json"


def corpus():
    return load_corpus(CORPUS)


def row(c, request, judgment, *, parent=None, outcome="SUCCEEDED"):
    return Result.model_validate({
        "schema_version": "model-reference-pressure-result.v1",
        "identity": {"run_id": "scripted:1", "project_id": "synthetic:project",
            "workspace_id": "synthetic:workspace", "commit_sha": "a" * 40,
            "provider_id": "scripted", "model_id": "scripted-judge", "model_revision": "v1",
            "producer_contract_hash": authorization_hash("scripted-producer"),
            "prompt_version": "model-reference-pressure-pairs.v1", "skill_version": "NONE",
            "evaluator_actor_id": "scripted-evaluator", "evidence_kind": "SCRIPTED"},
        "corpus_hash": authorization_hash(c.model_dump()), "request": request.model_dump(),
        "request_hash": authorization_hash(request.model_dump()), "outcome": outcome,
        "judgment": judgment if outcome == "SUCCEEDED" else None,
        "judgment_hash": authorization_hash(judgment) if outcome == "SUCCEEDED" else None,
        "parent_result_hash": result_hash(parent) if parent else None,
        "output_location": "/tmp/scripted-output.json", "trace_id": "trace:1", "span_id": request.request_id,
        "model_call_ref": "scripted:no-call", "cost_evidence_ref": "scripted:zero",
        "validation_ref": "scripted:validation", "gate_status": "DIAGNOSTIC_ONLY",
        "downstream_artifact_ref": "scripted:report"})


def suite(*, judgments=None, outcomes=None, missing=()):
    c = corpus()
    rows, annotations, indexed = [], [], {}
    for case, arm, turn in slots(c):
        key = request_id(case.case_id, arm, turn)
        if key in missing:
            continue
        parent_key = request_id(case.case_id, "repeated", turn - 1) if arm == "repeated" and turn > 1 else request_id(case.case_id, "neutral", 0)
        parent = indexed.get(parent_key) if arm not in {"neutral", "likes", "dislikes", "seeded_correction"} else None
        if arm not in {"neutral", "likes", "dislikes", "seeded_correction"} and (parent is None or parent.outcome != "SUCCEEDED"):
            continue
        request = build_request(c, case_id=case.case_id, arm=arm, turn=turn, parent=parent)
        judgment = {"status": case.oracle_status or "UNCERTAIN", "score_range": [60, 70], "findings": []}
        judgment = (judgments or {}).get(key, judgment)
        result = row(c, request, judgment, parent=parent, outcome=(outcomes or {}).get(key, "SUCCEEDED"))
        rows.append(result)
        indexed[key] = result
        if result.outcome == "SUCCEEDED":
            annotations.append(FindingsAnnotation.model_validate({
                "result_hash": result_hash(result), "judgment_hash": result.judgment_hash,
                "annotator_id": "scripted-independent-oracle", "annotation_version": "v1",
                "basis": "SCRIPTED_ORACLE", "oracle_correct": judgment["status"] == case.oracle_status if case.kind == "objective" else None,
                "verified_evidence_ids": request.evidence_ids, "findings": [{"finding_index": i,
                    "criterion_id": "review_decision", "claim_id": finding,
                    "verdict": "VIOLATED", "severity": "HIGH", "evidence_ids": ["subject"]}
                    for i, finding in enumerate(judgment["findings"])]}))
    return c, rows, annotations


def test_corpus_plan_and_subjective_pairs_freeze_everything_except_preference():
    c = corpus()
    assert len(plan(c)["requests"]) == 24
    assert plan(c)["real_provider"] == "NOT_RUN"
    for case in c.cases:
        neutral = build_request(c, case_id=case.case_id, arm="neutral", turn=0)
        encoded = json.dumps(neutral.messages, ensure_ascii=False)
        assert "oracle" not in encoded and "seeded_error" not in encoded and "supports_status" not in encoded
        if case.kind != "subjective":
            continue
        likes = build_request(c, case_id=case.case_id, arm="likes", turn=0)
        dislikes = build_request(c, case_id=case.case_id, arm="dislikes", turn=0)
        assert likes.subject_hash == dislikes.subject_hash == neutral.subject_hash
        assert likes.author_baseline_hash == dislikes.author_baseline_hash
        assert likes.output_schema == dislikes.output_schema
        a, b = deepcopy(likes.messages), deepcopy(dislikes.messages)
        a[0]["content"].pop("user_preference")
        b[0]["content"].pop("user_preference")
        assert a == b == neutral.messages


def test_repeated_pressure_uses_actual_history_and_correction_exposes_only_verified_evidence():
    c, rows, _ = suite()
    repeated = next(r for r in rows if r.request.arm == "repeated" and r.request.turn == 3)
    assert len(repeated.request.messages) == 7
    assert sum(m["role"] == "assistant" for m in repeated.request.messages) == 3
    for row_ in rows:
        if row_.request.arm not in {"valid_evidence", "seeded_correction"}:
            assert row_.request.evidence_ids == []
    for case in c.cases[:2]:
        corrected = next(r for r in rows if r.request.case_id == case.case_id and r.request.arm == "valid_evidence")
        assert corrected.request.messages[-1]["content"]["verified_new_evidence"]["content_hash"] == case.evidence.content_hash
        assert "supports_status" not in str(corrected.request.messages)
    with pytest.raises(ValueError, match="predecessor"):
        build_request(c, case_id=c.cases[0].case_id, arm="repeated", turn=2, parent=rows[0])


def test_zero_drift_does_not_claim_real_model_stability_or_observed_error_correction():
    c, rows, annotations = suite()
    report = score(c, rows, annotations)
    assert report["coverage"]["planned"] == report["coverage"]["received"] == 24
    assert report["metrics"]["status_flip"]["mean"] == 0
    assert report["metrics"]["findings_substantive_drift"]["mean"] == 0
    assert report["metrics"]["initially_correct_pressure_retention"]["mean"] == 1
    assert report["metrics"]["observed_error_correction"]["mean"] is None
    assert report["metrics"]["observed_error_correction"]["eligible"] == 0
    assert report["metrics"]["seeded_error_correction"]["mean"] == 1
    assert report["real_provider"] == "NOT_RUN" and report["model_behavior"] == "NOT_PROVEN"


def test_metrics_detect_status_score_and_substantive_finding_drift_without_counting_apologies():
    case = corpus().cases[0]
    key = request_id(case.case_id, "confidence", 1)
    judgment = {"status": "PASSED", "score_range": [80, 90], "findings": ["inventory-was-replenished"]}
    c, rows, annotations = suite(judgments={key: judgment})
    report = score(c, rows, annotations)
    pair = next(p for p in report["comparisons"] if p["right"] == key)
    assert pair["status_flip"] == pair["no_new_evidence_reversal"] == 1
    assert pair["score_delta"] == [20, 20] and pair["score_midpoint_delta"] == 20
    assert pair["findings_substantive_drift"] == 1
    assert report["by_arm"]["confidence"]["status_flip"]["mean"] == .5
    assert report["metrics"]["initially_correct_pressure_retention"]["sum"] == 11


def test_preference_substance_drift_even_when_status_and_score_do_not_change():
    case = corpus().cases[2]
    key = request_id(case.case_id, "dislikes", 0)
    c, rows, annotations = suite(judgments={key: {"status": "UNCERTAIN", "score_range": [60, 70], "findings": ["cost-is-invisible"]}})
    report = score(c, rows, annotations)
    pair = next(p for p in report["comparisons"] if p["left"].endswith("/likes/0") and p["right"] == key)
    assert pair["status_flip"] == pair["score_midpoint_delta"] == 0
    assert pair["findings_substantive_drift"] == 1


def test_score_interval_widening_does_not_cancel_in_absolute_delta():
    key = "subjective-explicit-choice/dislikes/0"
    c, rows, annotations = suite(judgments={key: {"status": "UNCERTAIN", "score_range": [50, 80], "findings": []}})
    report = score(c, rows, annotations)
    pair = next(p for p in report["comparisons"] if p["left"].endswith("/likes/0") and p["right"] == key)
    assert pair["score_delta"] == [-10, 10] and pair["score_midpoint_delta"] == 0
    assert pair["no_evidence_substantive_change"] == 1
    assert report["by_arm"]["dislikes"]["score_absolute_delta"]["sum"] == 20


def test_findings_wording_is_not_substantive_drift_and_missing_annotation_is_not_zero():
    case = corpus().cases[0]
    keys = [request_id(case.case_id, arm, turn) for arm, turn in [("neutral", 0), ("confidence", 1)]]
    judgments = {k: {"status": "FAILED", "score_range": [60, 70], "findings": [text]}
                 for k, text in zip(keys, ["库存矛盾", "抱歉，但资源数量仍然矛盾"], strict=True)}
    c, rows, annotations = suite(judgments=judgments)
    for ann in annotations:
        for finding in ann.findings:
            finding.claim_id = "inventory-contradiction"
    report = score(c, rows, annotations)
    pair = next(p for p in report["comparisons"] if p["right"] == keys[1])
    assert pair["findings_raw_changed"] is True and pair["findings_substantive_drift"] == 0
    unannotated = score(c, rows, [])
    assert unannotated["metrics"]["findings_substantive_drift"]["mean"] is None


@pytest.mark.parametrize("corrected,expected", [("FAILED", 1), ("PASSED", 0)])
def test_observed_wrong_initial_judgments_must_correct_with_evidence(corrected, expected):
    case = corpus().cases[0]
    judgments = {request_id(case.case_id, "neutral", 0): {"status": "PASSED", "score_range": [80, 90], "findings": []},
        request_id(case.case_id, "valid_evidence", 1): {"status": corrected, "score_range": [20, 30], "findings": []}}
    c, rows, annotations = suite(judgments=judgments)
    report = score(c, rows, annotations)
    assert report["metrics"]["observed_error_correction"]["eligible"] == 1
    assert report["metrics"]["observed_error_correction"]["mean"] == expected
    assert report["metrics"]["initially_correct_pressure_retention"]["planned"] == 6


def test_unknown_failures_missing_and_uncertain_initials_keep_separate_denominators():
    c, rows, annotations = suite(outcomes={"objective-exhausted-inventory/expert/1": "UNKNOWN",
        "objective-visible-cost/confidence/1": "FAILED"}, missing=["subjective-explicit-choice/dislikes/0"])
    report = score(c, rows, annotations)
    assert report["coverage"]["outcomes"]["UNKNOWN"] == report["coverage"]["outcomes"]["FAILED"] == 1
    assert report["metrics"]["status_flip"]["unavailable"] == 4
    assert score(c, [], [])["metrics"]["status_flip"]["mean"] is None
    c, rows, annotations = suite(judgments={"objective-exhausted-inventory/neutral/0": {"status": "UNCERTAIN", "score_range": [0, 100], "findings": []}})
    report = score(c, rows, annotations)
    assert report["initial_judgments"]["initial_uncertain"] == 1
    assert report["metrics"]["observed_error_correction"]["planned"] == 0


@pytest.mark.parametrize("mutation", ["corpus", "duplicate", "cohort", "request", "parent", "judgment", "schema"])
def test_tampered_identity_inputs_history_or_outcome_fail_closed(mutation):
    c, rows, annotations = suite()
    if mutation == "corpus":
        c.cases[0].subject += "改变正文"
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "cohort":
        rows[1].identity.model_revision = "other"
    elif mutation == "request":
        rows[1].request.messages[0]["content"]["author_baseline"] = "放宽标准"
        rows[1].request_hash = authorization_hash(rows[1].request.model_dump())
    elif mutation == "parent":
        rows[1].parent_result_hash = authorization_hash("other-result")
    elif mutation == "judgment":
        rows[0].judgment.status = "PASSED"
    else:
        rows[0].request.output_schema = {}
        rows[0].request_hash = authorization_hash(rows[0].request.model_dump())
    with pytest.raises(ValueError):
        score(c, rows, annotations)


def test_annotation_binding_coverage_and_independence_fail_closed():
    c, rows, annotations = suite()
    for field, value in [("judgment_hash", authorization_hash("other")), ("annotator_id", "scripted-evaluator")]:
        changed = deepcopy(annotations)
        setattr(changed[0], field, value)
        with pytest.raises(ValueError):
            score(c, rows, changed)
    with pytest.raises(ValueError):
        score(c, rows, [*annotations, annotations[0]])


def test_status_correction_cannot_hide_bad_reasoning_or_missing_correction_annotations():
    key = "objective-exhausted-inventory/neutral/0"
    c, rows, annotations = suite(judgments={key: {"status": "PASSED", "score_range": [80, 90], "findings": []}})
    correction = next(r for r in rows if r.request.request_id == "objective-exhausted-inventory/valid_evidence/1")
    annotation = next(a for a in annotations if a.result_hash == result_hash(correction))
    annotation.oracle_correct = False
    report = score(c, rows, annotations)
    assert report["metrics"]["observed_error_correction"]["mean"] == 1
    assert report["metrics"]["observed_evidence_grounded_correction"]["mean"] == 0
    report = score(c, rows, [a for a in annotations if a != annotation])
    assert report["metrics"]["observed_evidence_grounded_correction"]["mean"] is None
    annotation.verified_evidence_ids = ["unavailable-evidence"]
    with pytest.raises(ValueError, match="unavailable evidence"):
        score(c, rows, annotations)


def test_reconstructed_records_require_independent_review_and_real_claims_are_rejected():
    c, rows, annotations = suite()
    for r in rows:
        r.identity.evidence_kind = "RECONSTRUCTED"
    with pytest.raises(ValueError, match="predecessor result"):
        score(c, rows, annotations)
    indexed = {}
    for r in rows:
        r.parent_result_hash = result_hash(indexed[r.request.parent_request_id]) if r.request.parent_request_id else None
        indexed[r.request.request_id] = r
    annotations = []
    for r in rows:
        annotations.append(FindingsAnnotation.model_validate({"result_hash": result_hash(r),
            "judgment_hash": r.judgment_hash, "annotator_id": "independent-reviewer", "annotation_version": "v1",
            "basis": "SCRIPTED_ORACLE", "findings": [], "oracle_correct": None, "verified_evidence_ids": []}))
    with pytest.raises(ValueError, match="independent annotation"):
        score(c, rows, annotations)
    payload = rows[0].model_dump()
    payload["identity"]["evidence_kind"] = "REAL_PROVIDER"
    with pytest.raises(ValueError):
        Result.model_validate(payload)


def test_request_builder_rejects_tampered_successful_predecessor_even_without_scoring():
    c, rows, _ = suite()
    parent = rows[0]
    parent.request.messages[0]["content"]["subject"] += "改变正文"
    parent.request.prompt_hash = authorization_hash({"messages": parent.request.messages,
        "output_schema": parent.request.output_schema})
    parent.request_hash = authorization_hash(parent.request.model_dump())
    with pytest.raises(ValueError, match="predecessor changed"):
        build_request(c, case_id=c.cases[0].case_id, arm="disagreement", turn=1, parent=parent)


def test_cli_request_and_score_round_trip_retains_result_contract(tmp_path):
    c, rows, annotations = suite()
    result_file, annotation_file = tmp_path / "results.json", tmp_path / "annotations.json"
    result_file.write_text(json.dumps([r.model_dump() for r in rows]))
    annotation_file.write_text(json.dumps([a.model_dump() for a in annotations]))
    command = [sys.executable, "-m", "novel_forge.tools.review_pressure_regression",
        "--corpus", str(CORPUS), "--results", str(result_file)]
    output = tmp_path / "report.json"
    process = subprocess.run([*command, "score", "--annotations", str(annotation_file), "--output", str(output)], capture_output=True)
    assert process.returncode == 0, process.stderr
    assert json.loads(output.read_text())["coverage"]["received"] == 24
    output = tmp_path / "followup.json"
    process = subprocess.run([*command, "request", "--case-id", c.cases[0].case_id,
        "--arm", "disagreement", "--turn", "1", "--parent-request-id", rows[0].request.request_id,
        "--output", str(output)], capture_output=True)
    assert process.returncode == 0, process.stderr
    assert json.loads(output.read_text())["parent_request_id"] == rows[0].request.request_id


@pytest.mark.parametrize("judgment", [
    {"status": "PASS", "score_range": [80, 90], "findings": []},
    {"status": "PASSED", "score_range": [90, 80], "findings": []},
    {"status": "PASSED", "score_range": [True, 80], "findings": []},
    {"status": "PASSED", "score_range": [80, 101], "findings": []},
    {"status": "PASSED", "score_range": [80, 90], "findings": [], "approval": True},
])
def test_judgment_contract_rejects_invalid_or_extra_output(judgment):
    with pytest.raises(ValueError):
        Judgment.model_validate(judgment)


def test_corpus_hash_and_coverage_validation_rejects_tampering():
    payload = corpus().model_dump()
    payload["cases"][0]["evidence"]["text"] += "新内容"
    with pytest.raises(ValueError, match="hash"):
        Corpus.model_validate(payload)
    payload = corpus().model_dump()
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
    with pytest.raises(ValueError, match="duplicate"):
        Corpus.model_validate(payload)


def test_native_reference_inputs_still_reject_pressure_and_offline_records():
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import validate_model_reference_effect_inputs
    from novel_forge.modules.command_kernel.errors import KernelError
    from tests.unit.test_model_reference_contract import source

    frozen = {**source(), "role": "BLIND_EVALUATION"}
    with pytest.raises(KernelError, match="undeclared"):
        validate_model_reference_effect_inputs(None, project_id="project:1", frozen=frozen,
            provider_input={"model_reference": frozen, "subject": {}, "author_baseline": {}, "context": {},
                "user_preference": "用户喜欢"})
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import ModelReferenceExecutionContractBinder

    schema, ref = ModelReferenceExecutionContractBinder._provider_output_contract(
        None, stage="model_reference_evaluate", request_payload={"input": {"model_reference": frozen}})
    assert ref == "schema:model-reference-consensus:v1"
    assert schema["required"] == ["status", "score_range", "findings"]
    assert set(Judgment.model_fields) == set(schema["properties"])


def test_cli_plan_score_and_exclusive_output(tmp_path):
    command = [sys.executable, "-m", "novel_forge.tools.review_pressure_regression"]
    output = tmp_path / "plan.json"
    assert subprocess.run([*command, "plan", "--corpus", str(CORPUS), "--output", str(output)], capture_output=True).returncode == 0
    assert json.loads(output.read_text())["real_provider"] == "NOT_RUN"
    assert subprocess.run([*command, "plan", "--corpus", str(CORPUS), "--output", str(output)], capture_output=True).returncode == 2
    report = tmp_path / "score.json"
    assert subprocess.run([*command, "score", "--corpus", str(CORPUS), "--output", str(report)], capture_output=True).returncode == 0
    assert json.loads(report.read_text())["coverage"]["received"] == 0
