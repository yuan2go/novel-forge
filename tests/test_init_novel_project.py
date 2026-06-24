from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestInitNovelProject(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.script = self.root / "scripts" / "init_novel_project.py"

    def run_script(self, temp_root: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--root",
                str(temp_root),
                "--project-id",
                "project_sample",
                "--title",
                "示例项目",
                "--genre",
                "都市悬疑",
                *extra_args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_dry_run_does_not_create_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            result = self.run_script(temp_root, "--dry-run")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("NovelForge project initialization dry run.", result.stdout)
            self.assertIn("Directories to create:", result.stdout)
            self.assertIn("Files to write:", result.stdout)
            self.assertFalse((temp_root / "04_novel_projects").exists())

    def test_dry_run_force_does_not_delete_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            existing_project = temp_root / "04_novel_projects" / "project_sample"
            existing_project.mkdir(parents=True)
            sentinel = existing_project / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")

            result = self.run_script(temp_root, "--dry-run", "--force")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("would remove existing project directory because --force is set", result.stdout)
            self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_existing_project_without_force_fails_and_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            existing_project = temp_root / "04_novel_projects" / "project_sample"
            existing_project.mkdir(parents=True)
            sentinel = existing_project / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")

            result = self.run_script(temp_root)

            self.assertEqual(result.returncode, 1)
            self.assertIn("Project already exists", result.stderr)
            self.assertTrue(sentinel.exists())

    def test_init_project_creates_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)

            result = self.run_script(temp_root)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            project_file = temp_root / "04_novel_projects" / "project_sample" / "PROJECT.md"
            self.assertTrue(project_file.exists())
            self.assertIn("示例项目", project_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
