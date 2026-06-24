from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "novel_forge.cli", *args],
            cwd=cwd or ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_help(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Novel Forge V5 CLI", result.stdout)

    def test_init_and_validate_temp_project_reports_missing_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("init", "--root", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            status = self.run_cli("status", "--root", tmp)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("raw: 0", status.stdout)


if __name__ == "__main__":
    unittest.main()
