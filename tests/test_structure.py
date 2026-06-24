from __future__ import annotations

import unittest
from pathlib import Path


class TestRepositoryStructure(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_required_top_level_files_exist(self) -> None:
        required = [
            "README.md",
            "AGENTS.md",
            "CLAUDE.md",
            "PROJECT_STATE.md",
            "CURRENT_GOAL.md",
            "DECISIONS.md",
            "ROADMAP.md",
            "CHANGELOG.md",
            ".env.example",
            ".gitignore",
            "pyproject.toml",
            "Makefile",
        ]
        for relative_path in required:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((self.root / relative_path).exists())

    def test_required_directories_exist(self) -> None:
        required = ["docs", "skills", "scripts", "tests", "templates", "tasks", "schemas"]
        for relative_path in required:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((self.root / relative_path).is_dir())

    def test_required_v4_doc_directories_exist(self) -> None:
        required = [
            "docs/ai-workflow",
            "docs/architecture",
            "docs/audits",
            "docs/progress",
            "docs/skills",
        ]
        for relative_path in required:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((self.root / relative_path).is_dir())

    def test_required_progress_files_exist(self) -> None:
        required = [
            "v4-goal-pool.md",
            "v4-test-log.md",
            "v4-loop-report.md",
            "v4-open-issues.md",
        ]
        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((self.root / "docs" / "progress" / filename).exists())

    def test_required_templates_exist(self) -> None:
        required = [
            "project_constitution.md",
            "reader_attraction_gate.md",
            "project_differentiation_gate.md",
            "task_card.md",
            "chapter_plan.md",
            "review_report.md",
            "project_registry.md",
        ]
        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((self.root / "templates" / filename).exists())

    def test_required_schema_files_exist(self) -> None:
        required = [
            "material.schema.json",
            "dissection.schema.json",
            "topic.schema.json",
            "chapter_plan.schema.json",
            "review.schema.json",
        ]
        for filename in required:
            with self.subTest(filename=filename):
                self.assertTrue((self.root / "schemas" / filename).exists())

    def test_required_skill_files_exist(self) -> None:
        required = [
            "hot-novel-deconstruction",
            "anti-copy-abstraction",
            "character-design",
            "worldbuilding",
            "long-outline",
            "chapter-outline",
            "prose-generation",
            "quality-review",
        ]
        for skill_name in required:
            with self.subTest(skill_name=skill_name):
                self.assertTrue((self.root / "skills" / skill_name / "SKILL.md").exists())

    def test_skill_files_have_frontmatter_and_required_sections(self) -> None:
        required_sections = [
            "## 适用场景",
            "## 输入要求",
            "## 操作流程",
            "## 输出格式",
            "## 质量标准",
            "## 禁止事项",
            "## 与其他模块的关系",
        ]
        for skill_file in sorted((self.root / "skills").glob("*/SKILL.md")):
            with self.subTest(skill_file=skill_file):
                text = skill_file.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\nname: "))
                self.assertIn("\ndescription: ", text)
                for section in required_sections:
                    self.assertIn(section, text)


if __name__ == "__main__":
    unittest.main()
