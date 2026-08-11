from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.agents import AGENT_RUNTIME_PROFILES, SKILL_AGENT_MAP, agent_runtime_profile, runtime_profile_for_skill


class AgentRuntimeProfileTests(unittest.TestCase):
    def test_target_agent_aliases_resolve_to_runtime_profiles(self):
        cases = {
            "Editor-in-Chief": "Chief Editor Agent",
            "Detailed Outline Agent": "Chapter Plan Agent",
            "Chapter Writer Agent": "Draft Agent",
            "Reviewer Agent": "Review Agent",
            "Revision Agent": "AI Editor Agent",
            "Canon Guardian Agent": "Continuity Agent",
            "Foreshadowing Agent": "Continuity Agent",
            "Character Consistency Agent": "Continuity Agent",
            "Multidisciplinary Knowledge Agent": "Knowledge Agent",
            "Longform Recap Agent": "Longform Recap Agent",
            "Platform Compliance Agent": "Platform Compliance Agent",
            "Eval Agent": "Model Evaluation Agent",
            "Release Gate Agent": "Publishing Agent",
        }

        for requested, expected_agent in cases.items():
            with self.subTest(requested=requested):
                self.assertEqual(agent_runtime_profile(requested)["agent"], expected_agent)

    def test_all_root_project_skills_have_explicit_agent_mapping(self):
        root = Path(__file__).resolve().parents[2]
        skill_names = {path.parent.name for path in (root / "skills").glob("*/SKILL.md")}

        self.assertTrue(skill_names)
        self.assertEqual(skill_names - set(SKILL_AGENT_MAP), set())
        for skill in sorted(skill_names):
            with self.subTest(skill=skill):
                agent_key = SKILL_AGENT_MAP[skill]
                self.assertIn(agent_key, AGENT_RUNTIME_PROFILES)
                profile = runtime_profile_for_skill(skill)
                self.assertEqual(profile["skill"], skill)
                self.assertNotEqual(profile["agent"], "Quality Agent", f"{skill} should not fall back to the default quality profile")

    def test_os_governance_skills_route_to_matching_agents(self):
        cases = {
            "agent-loop-governance": "Workflow Agent",
            "context-builder-source-isolation": "Context Agent",
            "provider-runtime-policy": "Model Evaluation Agent",
            "canon-continuity-graph": "Continuity Agent",
            "publish-release-gate-os": "Publishing Agent",
            "narrative-beat-design": "Outline Agent",
            "skill-governance": "Engineering Agent",
            "platform-strategy-os": "Platform Compliance Agent",
            "training-exercise": "Training Agent",
            "longform-temporal-query": "Context Agent",
            "multi-scale-pacing": "Review Agent",
            "world-consequence-modeling": "Worldbuilding Agent",
            "evidence-fact-verification": "Knowledge Agent",
        }

        for skill, expected_agent in cases.items():
            with self.subTest(skill=skill):
                self.assertEqual(runtime_profile_for_skill(skill)["agent"], expected_agent)


if __name__ == "__main__":
    unittest.main()
