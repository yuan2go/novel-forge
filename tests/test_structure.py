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
        required = ["docs", "scripts", "tests", "templates"]
        for relative_path in required:
            with self.subTest(relative_path=relative_path):
                self.assertTrue((self.root / relative_path).is_dir())

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


if __name__ == "__main__":
    unittest.main()
