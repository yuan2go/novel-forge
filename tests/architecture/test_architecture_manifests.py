from __future__ import annotations

from pathlib import Path
import unittest

from novel_forge.tools.architecture_manifest import run


ROOT = Path(__file__).resolve().parents[2]


class ArchitectureManifestTests(unittest.TestCase):
    def test_all_repository_manifests_pass(self) -> None:
        for kind in (
            "modules",
            "migrations",
            "workers",
            "tests",
            "console-scripts",
        ):
            with self.subTest(kind=kind):
                report = run(kind, ROOT)
                self.assertEqual(report["status"], "PASS", report)

    def test_required_test_manifest_collects_non_zero_suites(self) -> None:
        report = run("tests", ROOT)
        self.assertEqual(report["status"], "PASS", report)
        counts = {
            str(item["name"]): int(item["count"])
            for item in report["collections"]
        }
        self.assertEqual(set(counts), {"architecture", "unit", "acceptance", "integration"})
        self.assertTrue(all(count > 0 for count in counts.values()))


if __name__ == "__main__":
    unittest.main()
