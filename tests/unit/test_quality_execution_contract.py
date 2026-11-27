from __future__ import annotations

from dataclasses import replace
import unittest

from novel_forge.modules.production_execution import (
    EvidenceSpan,
    JudgeExecutionEvidence,
    JudgeKind,
    capability_for_judge,
)


class QualityExecutionContractTests(unittest.TestCase):
    def test_all_judge_families_use_governed_capabilities(self) -> None:
        expected = {
            "intrinsic": "quality.intrinsic.judge",
            "originality": "quality.originality.judge",
            "platform": "quality.platform.judge",
            "style": "quality.intrinsic.judge",
            "semantic": "quality.intrinsic.judge",
            "reader_outcome": "quality.reader_outcome.judge",
            "pairwise": "quality.pairwise.judge",
            "mutation": "quality.pairwise.judge",
            "ood": "quality.intrinsic.judge",
        }
        self.assertEqual(
            {kind.value: capability_for_judge(kind) for kind in JudgeKind},
            expected,
        )

    def test_uncalibrated_judge_is_raw_score_not_probability(self) -> None:
        evidence = JudgeExecutionEvidence(
            judge_kind=JudgeKind.SEMANTIC,
            judge_profile_version="semantic-judge:v2",
            target_asset_version_id="asset-version-1",
            input_manifest_ref="input-1",
            route_snapshot_id="route-1",
            raw_score=82,
            ordinal_band="good",
            pairwise_preference="",
            evidence_spans=(EvidenceSpan(0, 12, "motivation"),),
            calibration_status="uncalibrated",
            disagreement={"judge_count": 1},
            usage_receipt_ref="usage-1",
            cost_receipt_ref="cost-1",
        )

        self.assertEqual(evidence.to_dict()["score_semantics"], "Raw Score")
        with self.assertRaisesRegex(ValueError, "cannot claim probability"):
            replace(evidence, score_semantics="probability")

    def test_pairwise_and_mutation_require_preference_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "pairwise judge"):
            JudgeExecutionEvidence(
                judge_kind=JudgeKind.MUTATION,
                judge_profile_version="mutation:v1",
                target_asset_version_id="asset-version-1",
                input_manifest_ref="input-1",
                route_snapshot_id="route-1",
                raw_score=None,
                ordinal_band="",
                pairwise_preference="",
                evidence_spans=(),
                calibration_status="uncalibrated",
                disagreement={},
                usage_receipt_ref="usage-1",
                cost_receipt_ref="cost-1",
            )


if __name__ == "__main__":
    unittest.main()
