from __future__ import annotations

import unittest

from novel_forge.modules.book_followup_authority.domain import (
    LongformCheckpointType,
    ReaderOutcomeGate,
    build_longform_recap_outputs,
    evaluate_reader_outcome,
    should_trigger_longform_recap,
)


class ReaderOutcomeAndRecapDomainTests(unittest.TestCase):
    def test_reader_outcome_is_multidimensional_and_explainable(self) -> None:
        result = evaluate_reader_outcome(
            {
                "continue_intent": 0.91,
                "curiosity": 0.88,
                "satisfaction": 0.82,
                "confusion": 0.12,
                "trust": 0.86,
                "character_attachment": 0.83,
                "antagonist_pressure": 0.74,
                "promise_expectation": 0.80,
                "payoff_satisfaction": 0.78,
                "drop_risk": 0.09,
                "repetition_fatigue": 0.10,
            },
            evidence=[{"asset_version_id": "draft:v1", "location": "paragraph:4"}],
        )

        self.assertEqual(result["gate"], ReaderOutcomeGate.PASS.value)
        self.assertEqual(set(result["reader_state"]), {
            "continue_intent", "curiosity", "satisfaction", "confusion", "trust",
            "character_attachment", "antagonist_pressure", "promise_expectation",
            "payoff_satisfaction", "drop_risk", "repetition_fatigue",
        })
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["evidence"])

    def test_reader_outcome_blocking_dimensions_are_not_hidden_by_average(self) -> None:
        result = evaluate_reader_outcome(
            {
                "continue_intent": 0.8,
                "curiosity": 0.8,
                "satisfaction": 0.8,
                "confusion": 0.92,
                "trust": 0.8,
                "character_attachment": 0.8,
                "antagonist_pressure": 0.8,
                "promise_expectation": 0.8,
                "payoff_satisfaction": 0.8,
                "drop_risk": 0.91,
                "repetition_fatigue": 0.1,
            },
            evidence=[{"asset_version_id": "draft:v1", "location": "chapter"}],
        )

        self.assertEqual(result["gate"], ReaderOutcomeGate.REVISION_REQUIRED.value)
        self.assertEqual(
            {issue["code"] for issue in result["issues"]},
            {"READER_CONFUSION_RISE", "DROP_RISK_HIGH"},
        )

    def test_recap_trigger_supports_cadence_and_risk(self) -> None:
        cadence = should_trigger_longform_recap(
            chapter_number=10,
            light_cadence=5,
            formal_cadence=10,
        )
        risk = should_trigger_longform_recap(
            chapter_number=7,
            light_cadence=5,
            formal_cadence=10,
            reader_outcome_declining=True,
        )

        self.assertEqual(cadence["checkpoint_type"], LongformCheckpointType.CHAPTER_CADENCE.value)
        self.assertEqual(cadence["level"], "FORMAL")
        self.assertEqual(risk["reasons"], ["READER_OUTCOME_CONTINUOUS_DECLINE"])

    def test_recap_emits_proposals_and_never_plan_mutation(self) -> None:
        outputs = build_longform_recap_outputs(
            project_id="project:1",
            book_id="book:1",
            chapter_range=(1, 10),
            checkpoint_type=LongformCheckpointType.ARC_CHECKPOINT,
            observations={
                "reader_state": {"confusion": 0.8, "repetition_fatigue": 0.7},
                "quality_trend": {"direction": "DECLINING"},
                "canon": {"conflicts": [{"id": "canon-conflict:1"}]},
                "reward_ledger": {"overdue": 2},
                "promise_ledger": {"overdue": 1},
            },
        )

        self.assertFalse(outputs["recap"]["plan_mutation_allowed"])
        deviation_types = {item["type"] for item in outputs["deviation_report"]["deviations"]}
        self.assertTrue(
            {"CANON_CONFLICT", "READER_CONFUSION_RISE", "QUALITY_TREND_DECLINE"}
            <= deviation_types
        )
        self.assertEqual(outputs["adjustment_proposal"]["decision_status"], "AUTHORITY_PENDING")
        self.assertIsNotNone(outputs["replan_request"])


if __name__ == "__main__":
    unittest.main()
