from __future__ import annotations

import unittest
from dataclasses import replace

from novel_forge.modules.chapter_quality_authority.calibration import (
    QualityCalibrationProfile,
    QualityCalibrationRun,
    QualityCalibrationStatus,
    QualityGoldenSample,
    QualityProviderDecision,
    evaluate_calibration_run,
)
from novel_forge.modules.command_kernel.errors import KernelError


class QualityCalibrationFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = QualityGoldenSample(
            sample_id="sample-1", project_scope="fixture", dimension="readability",
            input_asset_version_ids=("revision-v1",), expected_status="PASSED",
            expected_score_range=(75, 90), human_evidence=({"span": [0, 10]},),
            annotator="human-fixture", adjudication_status="ADJUDICATED",
            dataset_version="golden-v1",
        )
        self.decision = QualityProviderDecision(
            sample_id="sample-1", dimension="readability", status="PASSED",
            score=82, confidence=.9,
            provider_evidence_asset_version_id="provider-decision-v1",
        )
        self.profile = QualityCalibrationProfile(
            profile_id="profile-v1", dimension="readability",
            dataset_version="golden-v1", threshold_policy_version_id="quality-policy-v1",
            status=QualityCalibrationStatus.UNCALIBRATED,
        )
        self.run = QualityCalibrationRun(
            run_id="run-v1", profile_id="profile-v1", dimension="readability",
            dataset_version="golden-v1",
            provider_decision_asset_version_ids=("provider-decision-v1",),
            sample_ids=("sample-1",),
        )

    def test_deterministic_golden_fixture_report(self) -> None:
        report = evaluate_calibration_run(
            run=self.run, profile=self.profile,
            samples=(self.sample,), decisions=(self.decision,),
        )
        self.assertEqual(report.status_accuracy, 1)
        self.assertEqual(report.score_in_range_rate, 1)
        self.assertEqual(report.calibration_status, QualityCalibrationStatus.GOLDEN_SET_CALIBRATED)
        self.assertFalse(report.production_verified)
        self.assertFalse(report.real_provider_proven)

    def test_stale_and_revoked_profiles_remain_explicit(self) -> None:
        stale = evaluate_calibration_run(
            run=self.run, profile=replace(self.profile, stale=True),
            samples=(self.sample,), decisions=(self.decision,),
        )
        revoked = evaluate_calibration_run(
            run=self.run, profile=replace(self.profile, revoked=True),
            samples=(self.sample,), decisions=(self.decision,),
        )
        self.assertEqual(stale.calibration_status, QualityCalibrationStatus.CALIBRATION_STALE)
        self.assertEqual(revoked.calibration_status, QualityCalibrationStatus.CALIBRATION_REVOKED)

    def test_wrong_dimension_is_rejected(self) -> None:
        with self.assertRaisesRegex(KernelError, "wrong dimension"):
            evaluate_calibration_run(
                run=self.run, profile=self.profile,
                samples=(self.sample,),
                decisions=(replace(self.decision, dimension="originality"),),
            )

    def test_provider_confidence_cannot_self_upgrade_calibration(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot self-assert"):
            replace(
                self.decision,
                calibration_status=QualityCalibrationStatus.HUMAN_CALIBRATED,
            )


if __name__ == "__main__":
    unittest.main()
