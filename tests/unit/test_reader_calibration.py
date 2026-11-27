from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest

import pytest

from novel_forge.modules.reader_calibration.manuscript_blind import (
    build_unassigned_manuscript_pack, extract_manuscript_chapter,
    validate_manuscript_human_response,
    normalize_manuscript_model_diagnosis, MANUSCRIPT_DIMENSIONS, content_digest,
    text_digest, public_from_private_mapping, validate_manuscript_write,
    manuscript_reading_input, require_manuscript_reading_input,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    CalibrationCandidate, CalibrationScope, CalibrationStatus, JudgeMode, blind_pair_order,
    calibrated_probability, calibration_metrics, human_agreement_report, mode_after_drift,
    preference_bias_report, reader_decision_policy, resolve_calibration_profile,
)


def test_unassigned_contiguous_manuscripts_keep_parent_selectors_private_and_no_fake_human():
    native = extract_manuscript_chapter(asset_type="draft_chapter", content={
        "chapter": 1, "title": "初章", "text": "人物停下，检查来路。"}, chapter_number=1, selector="/text")
    reference = extract_manuscript_chapter(asset_type="execution_evidence", content={
        "kind": "normalized-output", "payload": {"action": "FINAL", "final_response": {
            "contract_version": "controlled-reference-manuscript.v1", "chapters": [
                {"chapter_number": 1, "title": "第一章", "body": "他先问清目的。"}]} }},
        chapter_number=1, selector="/payload/final_response/chapters/0/body")
    manuscripts = [{"manuscript_key": "private-A", "chapters": [{**native,
        "parent_asset_version_id": "native-version", "parent_content_hash": "sha256:" + "a" * 64, "selector": "/text"}]},
        {"manuscript_key": "private-C", "chapters": [{**reference,
        "parent_asset_version_id": "reference-version", "parent_content_hash": "sha256:" + "c" * 64,
        "selector": "/payload/final_response/chapters/0/body"}]}]
    public, private = build_unassigned_manuscript_pack(manuscripts, secret="test-only-blind-secret", pack_key="comparison")
    assert len(public["manuscripts"]) == 2
    assert private["human_feedback_status"] == "PENDING_HUMAN_FEEDBACK"
    assert all("parent_asset_version_id" not in chapter for row in public["manuscripts"] for chapter in row["chapters"])
    assert {row["parent_asset_version_id"] for row in private["mapping"]} == {"native-version", "reference-version"}
    assert (public, private) == build_unassigned_manuscript_pack(manuscripts, secret="test-only-blind-secret", pack_key="comparison")
    response = deepcopy(public["response_template"])
    with pytest.raises(ValueError, match="ACTUAL_HUMAN_DECLARATION_REQUIRED"):
        validate_manuscript_human_response(public, response)
    response.update(reviewer_id="test-human-declaration", human_attestation=True, was_blinded=True,
        reading_notes="此处信息清楚，但后续选择仍需观察。")
    chapter = public["manuscripts"][0]["chapters"][0]
    response["evidence_spans"] = [{"chapter_token": chapter["chapter_token"], "start": 0, "end": 2,
        "quote": chapter["text"][:2], "observation": "这里能辨认说话者。"}]
    feedback = validate_manuscript_human_response(public, response)
    assert feedback["evaluator_origin"] == "HUMAN_SUBMISSION"
    assert feedback["identity_verification"] == "DECLARED_NOT_INDEPENDENTLY_VERIFIED"
    assert feedback["book_mutation_authorized"] is False
    response["evidence_spans"][0]["quote"] = "伪造位置"
    with pytest.raises(ValueError, match="READING_LOCATION_INVALID"):
        validate_manuscript_human_response(public, response)
    manuscripts[1]["chapters"][0]["chapter_number"] = 2
    with pytest.raises(ValueError, match="COMPARISON_SCOPE_MISMATCH"):
        build_unassigned_manuscript_pack(manuscripts, secret="test-only-blind-secret", pack_key="comparison")
    with pytest.raises(ValueError, match="SOURCE_TYPE_FORBIDDEN"):
        extract_manuscript_chapter(asset_type="raw_source_document", content={"text": "受保护原文"},
            chapter_number=1, selector="/text")

def test_model_reading_preserves_unresolved_quotes_and_cannot_become_human_feedback():
    manuscripts = [{"manuscript_key": key, "chapters": [{
        "chapter_number": 1, "title": "试读", "text": "回头。他终于离开。又回头。是是是。",
        "text_sha256": text_digest("回头。他终于离开。又回头。是是是。"), "parent_asset_version_id": key,
        "parent_content_hash": "sha256:" + "f" * 64, "selector": "/text",
    }]} for key in ("first", "second")]
    public, _ = build_unassigned_manuscript_pack(manuscripts, secret="test-only-reader-secret", pack_key="diagnosis")
    raw = {"contract_version": "reader-manuscript-model-diagnosis.v1", "pack_token": public["pack_token"],
        "public_content_hash": content_digest(public), "evaluator_origin": "HUMAN_SUBMISSION", "assessments": []}
    for row in public["manuscripts"]:
        raw["assessments"].append({"manuscript_token": row["manuscript_token"],
            "scores": {dimension: None for dimension in MANUSCRIPT_DIMENSIONS},
            "reading_experience": "角色改变了去留，但此段尚不足以判定长程效果。",
            "evidence_spans": [{"chapter_token": row["chapters"][0]["chapter_token"], "quote": quote,
                "observation": "保留可判断和无法定位的诊断。", "start": 99, "end": 100}
                for quote in ("他终于离开", "回头", "不在正文", "是是") ]})
    result = normalize_manuscript_model_diagnosis(public, raw)
    assert result["evaluator_origin"] == "MODEL_AUXILIARY_DIAGNOSIS" and result["human_feedback"] is False
    locations = result["assessments"][0]["evidence_spans"]
    assert [item["location_status"] for item in locations] == ["LOCATED", "AMBIGUOUS", "NOT_FOUND", "AMBIGUOUS"]
    assert locations[0]["start"] == 3
    assert "start" not in locations[1] and "start" not in locations[2]
    assert result["raw_diagnosis"] == raw
    raw["assessments"][0]["evidence_spans"][0]["chapter_token"] = "foreign-reading-chapter"
    with pytest.raises(ValueError, match="LOCATION_SCOPE_INVALID"):
        normalize_manuscript_model_diagnosis(public, raw)


def test_kernel_manuscript_mapping_rebuild_prevents_replacement_of_saved_prose():
    sources, manuscripts = [], []
    for key in ("private-first", "private-second"):
        chapters = []
        for number in (1, 2):
            content = {"chapter": number, "title": "原稿标题", "text": f"原稿第{number}章仍保留。"}
            source = SimpleNamespace(asset_version_id=f"{key}-{number}", asset_type="draft_chapter",
                content=content, content_hash=content_digest(content))
            sources.append(source)
            chapters.append({**extract_manuscript_chapter(asset_type=source.asset_type, content=content,
                chapter_number=number, selector="/text"), "book_id": key,
                "parent_asset_version_id": source.asset_version_id, "parent_content_hash": source.content_hash,
                "selector": "/text", "producer_operation_id": f"operation-{key}-{number}", "source_kind": "draft_chapter"})
        manuscripts.append({"manuscript_key": key, "chapters": chapters})
    public, private = build_unassigned_manuscript_pack(manuscripts, secret="test-only-frozen-originals", pack_key="native")
    assert public_from_private_mapping(private) == public
    validate_manuscript_write("reader.manuscript.mapping.record", private, sources)
    parent = SimpleNamespace(asset_type="manuscript_blind_private_mapping", content=private)
    for field, value in (("text", "改写原稿"), ("title", "改写标题"), ("chapter_number", 9)):
        rewritten = deepcopy(public)
        rewritten["manuscripts"][0]["chapters"][0][field] = value
        declared = deepcopy(private)
        declared["public_content_hash"] = content_digest(rewritten)
        with pytest.raises(ValueError, match="PUBLIC_SNAPSHOT_DRIFT"):
            validate_manuscript_write("reader.manuscript.mapping.record", declared, sources)
        with pytest.raises(ValueError, match="PUBLIC_SNAPSHOT_DRIFT"):
            validate_manuscript_write("reader.manuscript.pack.export", {
                "public": rewritten, "public_content_hash": content_digest(rewritten)}, [parent])
    for mutation in ("same-book", "chapter-gap", "repeated-source"):
        declared = deepcopy(private)
        if mutation == "same-book":
            for row in declared["mapping"]:
                row["book_id"] = "same-book"
        elif mutation == "chapter-gap":
            declared["mapping"][1]["chapter_number"] = 3
        else:
            declared["mapping"][1].update(parent_asset_version_id=declared["mapping"][0]["parent_asset_version_id"])
        with pytest.raises(ValueError):
            public_from_private_mapping(declared)
    marked = manuscript_reading_input(public, "public-pack-version")
    require_manuscript_reading_input("先阅读正文。\n" + marked, public, "public-pack-version")
    with pytest.raises(ValueError, match="COMPLETE_INPUT_REQUIRED"):
        require_manuscript_reading_input(str({"pack_token": public["pack_token"],
            "public_content_hash": content_digest(public)}), public, "public-pack-version")
    altered = deepcopy(public)
    altered["manuscripts"][0]["chapters"][0]["text"] = "输入中替换的正文"
    with pytest.raises(ValueError, match="INPUT_SNAPSHOT_DRIFT"):
        require_manuscript_reading_input(manuscript_reading_input(altered, "public-pack-version"), public, "public-pack-version")


class ReaderCalibrationDomainTests(unittest.TestCase):
    def test_human_preference_blind_pair(self) -> None:
        left, right = blind_pair_order(
            "draft:a", "draft:b", randomization_key="pair:1"
        )
        self.assertEqual({left, right}, {"draft:a", "draft:b"})
        self.assertEqual(
            (left, right),
            blind_pair_order(
                "draft:a", "draft:b", randomization_key="pair:1"
            ),
        )

    def test_position_bias_detection(self) -> None:
        decisions = [
            {
                "choice": "A",
                "asset_a_position": "LEFT",
                "asset_b_position": "RIGHT",
                "canonical_pair_key": f"pair:{index}",
                "presentation_order": "AB",
                "preferred_asset_version_id": f"draft:{index}:a",
            }
            for index in range(8)
        ]
        self.assertTrue(
            preference_bias_report(decisions)["position_bias_detected"]
        )

    def test_human_agreement_report(self) -> None:
        report = human_agreement_report(
            [
                {"pair_id": "p1", "choice": "A"},
                {"pair_id": "p1", "choice": "A"},
                {"pair_id": "p2", "choice": "B"},
                {"pair_id": "p2", "choice": "A"},
            ]
        )
        self.assertEqual(report["agreement_rate"], 0.5)
        self.assertEqual(report["status"], "MEASURED")

    def test_insufficient_samples_block_probability(self) -> None:
        metrics = calibration_metrics(
            [(0.8, 1)] * 9, minimum_sample_size=10
        )
        self.assertEqual(
            metrics["calibration_status"], "INSUFFICIENT_DATA"
        )
        self.assertFalse(metrics["behavior_probability_allowed"])
        with self.assertRaisesRegex(
            KernelError, "CALIBRATED_PROBABILITY_FORBIDDEN"
        ):
            calibrated_probability(
                0.8,
                calibration_status=CalibrationStatus.INSUFFICIENT_DATA,
            )

    def test_calibration_profile_resolution_prefers_specific_valid_scope(
        self,
    ) -> None:
        requested = self._scope()
        broad = CalibrationCandidate(
            "broad",
            CalibrationScope(
                "platform-a", "fantasy", "*", "*", "*", "judge-v1", "m1"
            ),
            100,
            50,
            CalibrationStatus.VALID,
        )
        specific = CalibrationCandidate(
            "specific",
            requested,
            50,
            50,
            CalibrationStatus.VALID,
        )
        insufficient = CalibrationCandidate(
            "insufficient",
            requested,
            49,
            50,
            CalibrationStatus.VALID,
        )
        resolved = resolve_calibration_profile(
            requested, [broad, insufficient, specific]
        )
        self.assertEqual(resolved.profile_id, "specific")

    def test_drift_downgrades_judge_to_shadow(self) -> None:
        self.assertEqual(
            mode_after_drift(
                JudgeMode.BOUNDED_PRODUCTION, severe_drift=True
            ),
            JudgeMode.SHADOW,
        )

    def test_reader_outcome_cannot_override_hard_gate(self) -> None:
        decision = reader_decision_policy(
            hard_gate_passed=False,
            blocking_quality_issues=0,
            calibration_status=CalibrationStatus.VALID,
            ood=False,
            disagreement=False,
            long_term_outcome="HIGH",
            short_term_outcome="HIGH",
        )
        self.assertEqual(decision, {"decision": "BLOCKED", "reason": "HARD_GATE"})

    @staticmethod
    def _scope() -> CalibrationScope:
        return CalibrationScope(
            "platform-a",
            "fantasy",
            "progression",
            "payoff",
            "segment-new",
            "judge-v1",
            "m1",
        )


if __name__ == "__main__":
    unittest.main()
