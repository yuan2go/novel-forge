from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from novel_forge.core.constants import SKILL_NAMES, SKILL_REQUIRED_SECTIONS
from novel_forge.workflows.pipeline import validate_skills

ROOT = Path(__file__).resolve().parents[2]


class SkillTests(unittest.TestCase):
    def test_required_skills_exist(self):
        self.assertEqual(len(SKILL_NAMES), 18)
        for skill_name in SKILL_NAMES:
            with self.subTest(skill_name=skill_name):
                self.assertTrue((ROOT / "skills" / skill_name / "SKILL.md").exists())

    def test_skill_frontmatter_and_sections(self):
        for skill_name in SKILL_NAMES:
            path = ROOT / "skills" / skill_name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            with self.subTest(skill_name=skill_name):
                self.assertTrue(text.startswith("---\n"))
                self.assertIn(f"name: {skill_name}", text)
                self.assertIn("description:", text)
                for section in SKILL_REQUIRED_SECTIONS:
                    self.assertIn(section, text)

    def test_validate_skills_passes_for_repository_root(self):
        self.assertEqual(validate_skills(ROOT), [])

    def test_external_claude_resource_command_is_bounded(self):
        path = ROOT / ".claude" / "commands" / "evaluate-claude-resource.md"
        text = path.read_text(encoding="utf-8")

        self.assertIn("static, read-only review", text)
        self.assertIn("Do not run the target repository", text)
        self.assertIn("Execution Surfaces", text)
        self.assertIn("Import Decision", text)
        for decision in ["adopt", "adapt", "defer", "reject"]:
            self.assertIn(f"`{decision}`", text)
        for boundary in ["Do not import hooks by default", "Do not change `.claude/skills/` directly"]:
            self.assertIn(boundary, text)


if __name__ == "__main__":
    unittest.main()
