from __future__ import annotations

import unittest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration.application import PostgresReaderCalibrationAuthority
from novel_forge.modules.reader_calibration import (
    CalibrationCandidate,
    CalibrationScope,
    CalibrationStatus,
    JudgeMode,
    blind_pair_order,
    calibrated_probability,
    calibration_metrics,
    human_agreement_report,
    mode_after_drift,
    preference_bias_report,
    reader_decision_policy,
    resolve_calibration_profile,
)


class ReaderCalibrationDomainTests(unittest.TestCase):
    def test_behavior_calibration_requires_dataset_lineage_before_database_or_admission(self) -> None:
        authority = PostgresReaderCalibrationAuthority(
            "postgresql://unreachable.invalid/no-database", application_build_id="unit", commit_sha="a" * 40
        )
        principal = Principal(
            principal_id="operator", principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"book.authority.execute"}), project_scope=frozenset({"project"}),
            authentication_source="unit-test",
        )
        with self.assertRaisesRegex(KernelError, "READER_CALIBRATION_DATASET_LINEAGE_REQUIRED"):
            authority.run_calibration(
                project_id="project", scope=self._scope(), observations=[(0.9, 1)], minimum_sample_size=1,
                input_manifest_version_id="caller-manifest", evidence_level="BEHAVIOR_CALIBRATED",
                idempotency_key="calibration", principal=principal,
            )
        self.assertIsNone(authority.resolve_profile("project", self._scope()))

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
