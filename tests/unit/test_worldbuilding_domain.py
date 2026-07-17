from __future__ import annotations
import unittest
from novel_forge.modules.worldbuilding.domain import build_world_bible, validate_world_rules

class WorldbuildingDomainTests(unittest.TestCase):
    def rule(self, text="magic costs memory", cost="one memory", **extra):
        return {"rule": text, "rule_key": "magic", "scope": "all", "cost": cost, "exception": "none", "observable_consequence": "forgetting", "narrative_function": "force choices", "conflict_potential": "identity loss", "failure_mode": "amnesia", "canon_policy": "immutable"} | extra
    def test_world_rule_requires_cost_and_detects_conflict(self):
        report = validate_world_rules(project_id="p1", rules=[self.rule(), self.rule("magic restores memory")])
        self.assertFalse(report["passed"]); self.assertEqual(report["issues"][0]["code"], "WORLD_RULE_CONFLICT")
        unlimited = validate_world_rules(project_id="p1", rules=[self.rule(cost="unlimited")])
        self.assertEqual(unlimited["issues"][0]["code"], "UNLIMITED_CAPABILITY")
    def test_world_bible_is_goal_and_version_scoped(self):
        bible = build_world_bible(project_id="p1", creative_brief_version_id="brief-v1", rules=[self.rule()], entities={"factions": [{"name": "Archive"}], "daily_life_impacts": [{"impact": "names are rationed"}]})
        self.assertTrue(bible["validation"]["passed"]); self.assertEqual(bible["creative_brief_version_id"], "brief-v1")

if __name__ == "__main__": unittest.main()
