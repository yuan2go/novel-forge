from __future__ import annotations
import unittest
from novel_forge.modules.characters.domain import build_character, build_relationship_state

class CharacterDomainTests(unittest.TestCase):
    def profile(self):
        fields = ("desire", "need", "fear", "wound", "false_belief", "value_hierarchy", "moral_boundary", "capability", "weakness", "agency", "voice", "public_identity", "private_identity", "secret", "relationship_goals", "conflict_style", "growth_arc", "failure_arc", "reader_charm_mechanism")
        return {"project_id": "p1", **{key: key for key in fields}, "capability_cost": "loses one trusted memory"}
    def test_character_requires_project_goal_agency_and_capability_cost(self):
        character = build_character(project_id="p1", creative_brief_version_id="brief-v1", world_bible_version_id="world-v1", theme_question_version_id="theme-v1", profile=self.profile())
        self.assertEqual(character["world_bible_version_id"], "world-v1")
        missing = self.profile(); missing.pop("desire")
        with self.assertRaisesRegex(ValueError, "desire"): build_character(project_id="p1", creative_brief_version_id="b", world_bible_version_id="w", theme_question_version_id="t", profile=missing)
        costless = self.profile(); costless["capability_cost"] = ""
        with self.assertRaisesRegex(ValueError, "requires a cost"): build_character(project_id="p1", creative_brief_version_id="b", world_bible_version_id="w", theme_question_version_id="t", profile=costless)
    def test_relationship_state_is_dynamic_and_complete(self):
        state = build_relationship_state(project_id="p1", left_character_version_id="a-v1", right_character_version_id="b-v1", previous_state_version_id="rel-v1", state={"relationship_edge": "rivals", "power_relation": "asymmetric", "trust_state": 0.2, "debt": "life", "dependency": "access", "hidden_conflict": "betrayal", "relationship_arc": "rivals-to-allies"})
        self.assertEqual(state["previous_state_version_id"], "rel-v1")
        with self.assertRaisesRegex(ValueError, "distinct"): build_relationship_state(project_id="p1", left_character_version_id="a", right_character_version_id="a", state={"relationship_edge": "self", "power_relation": "equal", "trust_state": 1, "debt": "none", "dependency": "none", "hidden_conflict": "none", "relationship_arc": "none"})

if __name__ == "__main__": unittest.main()
