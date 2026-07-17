from __future__ import annotations
import unittest
from novel_forge.modules.theme.domain import build_theme_arc, evaluate_anti_preaching, validate_theme_question

class ThemeDomainTests(unittest.TestCase):
    def conflict(self):
        return {"conflicting_values": ["loyalty", "safety"], "character_initial_position": "loyalty first", "pressure_event": "betray or die", "choice": "refuse betrayal", "immediate_cost": "loses shelter", "longterm_cost": "becomes hunted", "relationship_consequence": "ally distrust", "world_consequence": "regime escalates", "belief_change": "loyalty needs consent", "unresolved_tension": "can family survive"}
    def test_theme_question_is_concrete_and_value_choice_has_cost(self):
        with self.assertRaisesRegex(ValueError, "concrete"): validate_theme_question("freedom")
        self.assertIn("question", validate_theme_question("When safety requires betrayal, is loyalty still worth its cost?"))
        arc = build_theme_arc(project_id="p1", theme_question_version_id="theme-v1", conflicts=[self.conflict()])
        self.assertEqual(arc["theme_beats"][0]["choice"], "refuse betrayal")
        bad = self.conflict(); bad["immediate_cost"] = "none"
        with self.assertRaisesRegex(ValueError, "requires an immediate cost"): build_theme_arc(project_id="p1", theme_question_version_id="t", conflicts=[bad])
    def test_anti_preaching_returns_located_review_issues(self):
        report = evaluate_anti_preaching(project_id="p1", target_asset_version_id="draft-v1", passages=[{"start": 10, "end": 90, "excerpt_digest": "sha256:x", "author_summary": True, "choice_without_cost": True}])
        self.assertFalse(report["passed"]); self.assertEqual(len(report["issues"]), 2)
        self.assertEqual(report["issues"][0]["evidence_locator"]["start"], 10)

if __name__ == "__main__": unittest.main()
