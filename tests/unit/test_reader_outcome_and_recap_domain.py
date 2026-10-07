from __future__ import annotations



import unittest

from novel_forge.modules.book_followup_authority.domain import (
    LongformCheckpointType,
    ReaderOutcomeGate,
    build_longform_recap_outputs,
    evaluate_reader_outcome,
    should_trigger_longform_recap,
)
from novel_forge.modules.book_followup_authority.query import (
    _diagnostic_risk,
    _reader_state_trend,
)


class ReaderOutcomeAndRecapDomainTests(unittest.TestCase):
    def test_reader_diagnostics_and_trend_are_derived_from_evidence(self) -> None:
        self.assertFalse(_diagnostic_risk("AGREED", safe={"AGREED", "PASSED"}))
        self.assertTrue(_diagnostic_risk("NOT_MEASURED", safe={"AGREED", "PASSED"}))
        trend = _reader_state_trend(
            {
                "continue_intent": 0.8,
                "confusion": 0.2,
                "repetition_fatigue": 0.2,
            },
            {
                "continue_intent": 0.7,
                "confusion": 0.27,
                "repetition_fatigue": 0.2,
            },
        )

        self.assertTrue(trend["declining"])
        self.assertEqual(
            trend["declining_dimensions"],
            ["confusion", "continue_intent"],
        )
        self.assertFalse(trend["comparison_status"].startswith("NO_PREVIOUS"))

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
        self.assertEqual(result["evidence_class"], "READER_PROXY_ADVISORY")
        self.assertFalse(result["canon_mutation_allowed"])
        self.assertFalse(result["future_intent_actualization_allowed"])
        self.assertEqual(
            set(result["reader_state"]),
            {
                "continue_intent",
                "curiosity",
                "satisfaction",
                "confusion",
                "trust",
                "character_attachment",
                "antagonist_pressure",
                "promise_expectation",
                "payoff_satisfaction",
                "drop_risk",
                "repetition_fatigue",
            },
        )
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

        self.assertEqual(
            cadence["checkpoint_type"], LongformCheckpointType.CHAPTER_CADENCE.value
        )
        self.assertEqual(cadence["level"], "FORMAL")
        self.assertEqual(risk["reasons"], ["READER_OUTCOME_CONTINUOUS_DECLINE"])

    def test_accepted_realization_deviation_requests_future_group_replan(self) -> None:
        evidence = {"contract_version": "accepted-realization-deviations.v1",
                    "deviations": [{"deviation_id": "deviation:1", "future_from_chapter": 2}],
                    "accepted_history_mutation_allowed": False}
        outputs = build_longform_recap_outputs(
            project_id="project:1", book_id="book:1", chapter_range=(1, 1),
            checkpoint_type=LongformCheckpointType.BOOK_AUTHORITY_REQUEST,
            observations={"accepted_realization_deviations": evidence},
        )
        request = outputs["replan_request"]
        self.assertEqual(request["reason_refs"], ["ACCEPTED_REALIZATION_DEVIATION"])
        self.assertEqual(request["affected_scope"], "CHAPTER_GROUP")
        self.assertTrue(request["impact_scope"]["future_only"])
        self.assertEqual(request["decision_evidence"][0]["evidence"], evidence)
        self.assertFalse(outputs["recap"]["plan_mutation_allowed"])
        self.assertIn("executed_chapter_history", request["preserved_invariants"])

    def test_recap_emits_proposals_and_never_plan_mutation(self) -> None:
        outputs = build_longform_recap_outputs(
            project_id="project:1",
            book_id="book:1",
            chapter_range=(1, 10),
            checkpoint_type=LongformCheckpointType.ARC_CHECKPOINT,
            observations={
                "reader_state": {"confusion": 0.8, "repetition_fatigue": 0.7},
                "reader_qualification": {
                    "qualification_status": "QUALIFIED",
                    "sample_size": 100,
                    "confidence": 0.9,
                    "recent_reports": [{"declining": True}] * 3,
                    "disagreement": False,
                    "position_bias": False,
                    "ood": False,
                    "drift_detected": False,
                },
                "quality_trend": {"direction": "DECLINING"},
                "canon": {"conflicts": [{"id": "canon-conflict:1"}]},
                "reward_ledger": {"overdue": 2},
                "promise_ledger": {"overdue": 1},
            },
        )

        self.assertFalse(outputs["recap"]["plan_mutation_allowed"])
        self.assertEqual(
            outputs["recap"]["reader_evidence_class"],
            "READER_PROXY_ADVISORY",
        )
        deviation_types = {
            item["type"] for item in outputs["deviation_report"]["deviations"]
        }
        self.assertTrue(
            {"CANON_CONFLICT", "READER_CONFUSION_RISE", "QUALITY_TREND_DECLINE"}
            <= deviation_types
        )
        self.assertEqual(
            outputs["adjustment_proposal"]["decision_status"], "AUTHORITY_PENDING"
        )
        self.assertTrue(outputs["adjustment_proposal"]["reader_activation_eligible"])
        self.assertFalse(outputs["adjustment_proposal"]["activation_allowed"])
        self.assertIsNotNone(outputs["replan_request"])
        actions = outputs["adjustment_proposal"]["proposed_actions"]
        self.assertIn(
            "CHAPTER_ADJUSTMENT",
            {item["requested_action"] for item in actions},
        )
        self.assertEqual(outputs["replan_request"]["affected_scope"], "ARC")
        self.assertTrue(outputs["replan_request"]["impact_scope"]["future_only"])
        self.assertIn(
            "accepted_canon", outputs["replan_request"]["preserved_invariants"]
        )

    def test_unqualified_reader_trend_can_advise_but_cannot_activate(self) -> None:
        outputs = build_longform_recap_outputs(
            project_id="project:1",
            book_id="book:1",
            chapter_range=(1, 4),
            checkpoint_type=LongformCheckpointType.CHAPTER_GROUP_COMPLETE,
            observations={
                "reader_state": {"confusion": 0.8, "repetition_fatigue": 0.7},
                "reader_qualification": {
                    "qualification_status": "SHADOW",
                    "sample_size": 4,
                    "confidence": 0.0,
                    "recent_reports": [{"declining": True}] * 3,
                    "disagreement": True,
                    "position_bias": True,
                    "ood": True,
                    "drift_detected": False,
                },
            },
        )

        consumption = outputs["recap"]["reader_outcome_consumption"]
        self.assertEqual(consumption["decision"], "ADVISORY_RECOMMENDATION")
        self.assertTrue(consumption["advisory_recommendation_allowed"])
        self.assertFalse(consumption["activation_eligible"])
        self.assertFalse(consumption["future_production_influence_allowed"])
        self.assertEqual(
            {item["type"] for item in outputs["deviation_report"]["deviations"]},
            {"READER_CONFUSION_RISE", "REPETITION_FATIGUE"},
        )
        self.assertFalse(outputs["adjustment_proposal"]["activation_allowed"])
        self.assertEqual(
            outputs["adjustment_proposal"]["required_authority"],
            "PLAN_CHANGE_AUTHORITY",
        )

    def test_ending_reachability_checkpoint_is_a_blocking_replan_reason(self) -> None:
        outputs = build_longform_recap_outputs(
            project_id="project:1",
            book_id="book:1",
            chapter_range=(1, 1),
            checkpoint_type=LongformCheckpointType.BOOK_AUTHORITY_REQUEST,
            observations={
                "ending_reachability": {
                    "report_id": "ending:1",
                    "replan_required": True,
                    "ending_contract_reachable": False,
                    "reasons": ["CHAPTER_BUDGET_INSUFFICIENT"],
                }
            },
        )

        self.assertIsNotNone(outputs["replan_request"])
        self.assertEqual(
            outputs["replan_request"]["reason_refs"],
            ["ENDING_REACHABILITY_AT_RISK"],
        )
        self.assertEqual(outputs["replan_request"]["affected_scope"], "BOOK")
        self.assertEqual(
            outputs["replan_request"]["required_authority"],
            "PLAN_CHANGE_AUTHORITY",
        )

    def test_accepted_arc_checkpoint_emits_future_only_revision_candidate(self) -> None:
        outputs = build_longform_recap_outputs(
            project_id="project:1",
            book_id="book:1",
            chapter_range=(4, 8),
            checkpoint_type=LongformCheckpointType.ARC_CHECKPOINT,
            observations={
                "accepted_arc_checkpoint": {
                    "checkpoint_id": "checkpoint:arc:8",
                    "projection_set_id": "projection:8",
                    "decision": "CORRECT",
                    "target_plan_version_ids": ["arc-plan:v1"],
                    "reason_evidence": {"reasons": ["OBLIGATION_OVERDUE"]},
                }
            },
        )

        revision = outputs["replan_request"]
        self.assertEqual(revision["type"], "ArcRevisionCandidate")
        self.assertEqual(revision["based_on_checkpoint_id"], "checkpoint:arc:8")
        self.assertEqual(revision["future_from_chapter"], 9)
        self.assertEqual(revision["target_plan_version_ids"], ["arc-plan:v1"])
        self.assertFalse(revision["plan_mutation_allowed"])


if __name__ == "__main__":
    unittest.main()


def test_reader_capacity_successor_requires_output_only_failure():
    from novel_forge.modules.book_followup_authority.reader_recovery import output_capacity_contract_failure

    decision = {"task": {"input_tokens": 16302, "output_tokens": 239232}, "candidates": [{
        "candidate": {"output_limit": 32768, "context_limit": 272000}, "rejected_reasons": ["CONTEXT_CAPACITY_EXCEEDED"]}]}
    assert output_capacity_contract_failure(decision)
    decision["candidates"][0]["rejected_reasons"].append("BUDGET_EXCEEDED")
    assert not output_capacity_contract_failure(decision)
    decision["candidates"][0]["rejected_reasons"] = ["CONTEXT_CAPACITY_EXCEEDED"]
    decision["task"]["output_tokens"] = 8192
    assert not output_capacity_contract_failure(decision)
