from __future__ import annotations
import unittest
from novel_forge.modules.longform_stability.semantic_domain import *

class LongformSemanticDomainTests(unittest.TestCase):
    def test_motivation_growth_and_unsupported_drift_are_distinct(self):
        states = [{"asset_version_id": "char-v1", "long_term_goal": "save sister"}]
        growth = detect_motivation_drift(project_id="p1", character_state_versions=states, current_behavior={"asset_version_id": "behavior-v2", "implied_goal": "expose prison to save sister", "change_evidence": ["sister transferred"]})
        drift = detect_motivation_drift(project_id="p1", character_state_versions=states, current_behavior={"asset_version_id": "behavior-v3", "implied_goal": "join jailers", "change_evidence": []})
        self.assertEqual(growth["classification"], "event_driven_growth"); self.assertFalse(growth["review_issue"])
        self.assertEqual(drift["classification"], "unsupported_motivation_drift"); self.assertTrue(drift["review_issue"])
    def test_alias_merge_needs_evidence_approval_and_rejects_cross_project(self):
        left = {"project_id": "p1", "entity_id": "e1", "entity_type": "character", "name": "Iron Judge", "aliases": ["Judge"]}
        right = {"project_id": "p1", "entity_id": "e2", "entity_type": "character", "name": "Judge", "aliases": []}
        proposal = propose_entity_merge(project_id="p1", left=left, right=right, mentions=[])
        self.assertEqual(proposal["decision"], "REQUIRES_APPROVAL"); self.assertLess(proposal["confidence"], .9)
        with self.assertRaisesRegex(ValueError, "cross-project"): propose_entity_merge(project_id="p1", left=left, right={**right, "project_id": "p2"}, mentions=[])
    def test_foreshadow_quality_distinguishes_excellent_and_mechanical(self):
        fields = ("setup_clarity", "reader_memory", "timing", "causal_relevance", "surprise", "fairness", "emotional_payoff", "plot_consequence", "character_consequence", "theme_relevance")
        excellent = evaluate_foreshadow_payoff(project_id="p1", thread_version_id="f-v1", scores={key: .85 for key in fields})
        mechanical_scores = {key: .8 for key in fields}; mechanical_scores["plot_consequence"] = .1; mechanical_scores["character_consequence"] = .1
        mechanical = evaluate_foreshadow_payoff(project_id="p1", thread_version_id="f-v2", scores=mechanical_scores)
        self.assertEqual(excellent["classification"], "excellent_payoff"); self.assertEqual(mechanical["classification"], "mechanical_explanation_only")
    def test_world_rule_and_power_conflicts_are_semantic(self):
        world = detect_world_rule_conflicts(project_id="p1", rule_versions=[{"asset_version_id": "r1", "rule_key": "magic", "scope": "all", "definition": "costs memory"}, {"asset_version_id": "r2", "rule_key": "magic", "scope": "all", "definition": "free"}], events=[{"asset_version_id": "event-v1", "sudden_immunity": True}])
        power = detect_power_conflicts(project_id="p1", previous_state={"asset_version_id": "p1", "power_tier": 1}, current_state={"asset_version_id": "p2", "power_tier": 5, "change_reasons": [], "new_capabilities": ["time stop"], "cost": "none", "scale_growth": 5})
        self.assertIn("RULE_DEFINITION_DRIFT", {item["code"] for item in world["issues"]})
        self.assertEqual(set(power["issues"]), {"UNEXPLAINED_POWER_INCREASE", "COSTLESS_CAPABILITY", "POWER_INFLATION"})
    def test_pattern_repetition_arc_stall_and_overdue_debt(self):
        fingerprint = {"conflict_trigger": "insult", "antagonist_entry": "door kick", "resolution": "duel", "reward": "rank", "misunderstanding": "identity", "humiliation": "public", "chapter_ending": "new challenger", "revelation": "hidden tier", "character_reaction": "shock"}
        report = detect_pattern_repetition(project_id="p1", fingerprints=[fingerprint] * 3)
        debt = evaluate_narrative_debt(project_id="p1", current_chapter=12, debts=[{"type": "main_plot", "opened_chapter": 1, "payoff_window_end": 8}])
        self.assertEqual(report["trope_fatigue_risk"], "HIGH"); self.assertEqual(debt["arc_progress"], "STALLED"); self.assertEqual(debt["breached_count"], 1)
    def test_recap_consumes_all_semantic_reports_without_mutation(self):
        reports = {key: {} for key in ("motivation", "relationships", "canon", "world_rules", "power", "foreshadow", "promise_debt", "reward_cadence", "antagonist_pressure", "patterns", "theme", "quality")}
        reports["constraints"] = ["advance antagonist pressure in chapters 13-14"]
        recap = build_enhanced_recap(project_id="p1", reports=reports)
        self.assertFalse(recap["next_window_production_policy"]["mutate_accepted_chapters"])
        self.assertEqual(recap["chapter_plan_constraints"], reports["constraints"])

if __name__ == "__main__": unittest.main()
