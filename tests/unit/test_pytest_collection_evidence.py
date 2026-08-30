from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PytestCollectionEvidenceTests(unittest.TestCase):
    def test_public_pytest_plugin_writes_atomic_machine_collection_report(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_sample.py").write_text(
                "def test_sample():\n    assert True\n", encoding="utf-8"
            )
            report_path = root / "collection.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "test_sample.py",
                    "-q",
                    "-p",
                    "novel_forge.tools.pytest_collection_evidence",
                    f"--novel-forge-collection-report={report_path}",
                ],
                cwd=root,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            temporary_siblings = list(root.glob(".collection.json.*.tmp"))

        self.assertEqual(
            report["schema_version"], "novel-forge.pytest-collection.v1"
        )
        self.assertEqual(report["collected_count"], 1)
        self.assertEqual(report["node_ids"], ["test_sample.py::test_sample"])
        self.assertEqual(report["source_files"], ["test_sample.py"])
        self.assertEqual(report["collection_errors"], [])
        self.assertEqual(report["pytest_exit_status"], 0)
        self.assertEqual(temporary_siblings, [])

    def test_collection_failure_is_preserved_as_machine_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test_invalid.py").write_text(
                "def test_invalid(:\n    pass\n", encoding="utf-8"
            )
            report_path = root / "collection.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "test_invalid.py",
                    "-q",
                    "-p",
                    "novel_forge.tools.pytest_collection_evidence",
                    f"--novel-forge-collection-report={report_path}",
                ],
                cwd=root,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                check=False,
                capture_output=True,
                text=True,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(report["collected_count"], 0)
        self.assertEqual(
            report["collection_errors"],
            [
                {
                    "node_id": "test_invalid.py",
                    "outcome": "failed",
                }
            ],
        )
        self.assertNotEqual(report["pytest_exit_status"], 0)


if __name__ == "__main__":
    unittest.main()
