from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCheckDocsStructureScript(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.script = self.root / "scripts" / "check_docs_structure.py"

    def test_script_passes_for_repository_root(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.script), "--root", str(self.root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("NovelForge structure check passed.", result.stdout)

    def test_script_fails_with_clear_missing_file_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [sys.executable, str(self.script), "--root", temp_dir],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NovelForge structure check failed.", result.stderr)
        self.assertIn("- README.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
