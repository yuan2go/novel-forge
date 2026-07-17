from __future__ import annotations
import unittest
from novel_forge.modules.ending.domain import build_closure_plan, build_payoff_matrix, evaluate_ending_quality

class EndingDomainTests(unittest.TestCase):
    def plan(self):
        return {"main_problem_resolution": "archive opened", "protagonist_final_choice": "share the truth", "protagonist_cost": "loses private memories", "antagonist_end": "faces public judgment", "relationship_closures": ["trust rebuilt"], "reader_promises": ["clock explained"], "foreshadow_payoffs": ["broken bell"], "open_questions": ["who rebuilds"], "theme_reanswer": "loyalty must be chosen", "world_state_change": "memory monopoly ends", "aftertaste": "freedom is costly", "epilogue_policy": "short consequence scene"}
    def test_closure_requires_cost_and_all_dimensions(self):
        self.assertEqual(build_closure_plan(project_id="p1", ending_intent_version_id="ending-v1", plan=self.plan())["project_id"], "p1")
        bad = self.plan(); bad["protagonist_cost"] = "none"
        with self.assertRaisesRegex(ValueError, "requires protagonist cost"): build_closure_plan(project_id="p1", ending_intent_version_id="e", plan=bad)
    def test_unpaid_promise_foreshadow_and_mechanical_victory_block(self):
        matrix = build_payoff_matrix(project_id="p1", items=[{"type": "promise", "status": "OPEN", "asset_version_id": "promise-v1"}, {"type": "foreshadow", "status": "PAID", "asset_version_id": "thread-v2"}])
        report = evaluate_ending_quality(project_id="p1", closure_plan_version_id="closure-v1", payoff_matrix=matrix, evidence={"sudden_victory": True, "mechanical_summary": True})
        codes = {item["code"] for item in report["issues"]}
        self.assertIn("UNPAID_PROMISE", codes); self.assertIn("SUDDEN_VICTORY", codes); self.assertIn("MECHANICAL_ENDING", codes)
    def test_paid_or_justified_payoffs_pass(self):
        matrix = build_payoff_matrix(project_id="p1", items=[{"type": "promise", "status": "PAID", "asset_version_id": "p-v1"}, {"type": "mystery", "status": "SUBVERTED_WITH_JUSTIFICATION", "justification": "the ambiguity is the designed answer", "asset_version_id": "m-v1"}])
        self.assertTrue(evaluate_ending_quality(project_id="p1", closure_plan_version_id="c-v1", payoff_matrix=matrix, evidence={})["passed"])

if __name__ == "__main__": unittest.main()
