from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync_claude_skills.py"


class SkillSyncTests(unittest.TestCase):
    def test_dry_run_lists_skills_without_writing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "runtime-skills"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(ROOT), "--target", str(target), "--dry-run"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("dry-run:", result.stdout)
            self.assertIn("copy: hot-novel-deconstruction", result.stdout)
            self.assertFalse(target.exists())

    def test_sync_copies_skill_files_to_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "runtime-skills"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(ROOT), "--target", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((target / "quality-review" / "SKILL.md").exists())
            self.assertTrue((target / "reader-feedback" / "SKILL.md").exists())

    def test_check_detects_runtime_skill_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "runtime-skills"
            sync = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(ROOT), "--target", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(sync.returncode, 0, sync.stderr)
            skill = target / "quality-review" / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8") + "\nlocal drift\n", encoding="utf-8")

            check = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(ROOT), "--target", str(target), "--check"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(check.returncode, 1)
            self.assertIn("drift: quality-review", check.stdout)


if __name__ == "__main__":
    unittest.main()
