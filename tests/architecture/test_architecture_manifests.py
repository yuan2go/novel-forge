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
            "reachability",
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
        reality = report["reality"]
        self.assertEqual(
            sum(reality["classification_file_counts"].values()),
            reality["test_file_count"],
        )
        self.assertEqual(
            reality["classification_file_counts"]["HISTORICAL_REDUNDANT"],
            0,
        )

    def test_backend_static_regenerates_runtime_skills_before_drift_check(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        target = makefile.split("p0-backend-static:", 1)[1].split("\n", 1)[0]
        sync_position = target.find("sync-skills")
        check_position = target.find("check-skills")

        self.assertGreaterEqual(sync_position, 0)
        self.assertGreater(check_position, sync_position)
        self.assertIn(".claude/skills/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_ci_backend_job_installs_complete_qualification_dependencies(self) -> None:
        workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")

        self.assertIn('python -m pip install -e ".[test,industrial]"', workflow)


if __name__ == "__main__":
    unittest.main()
