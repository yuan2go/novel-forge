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
        module_counts = {
            str(item["path"]): int(item["count"])
            for item in report["module_collections"]
        }
        self.assertGreater(
            module_counts["tests/integration/test_core_functional_loops_postgres.py"],
            0,
        )
        self.assertTrue(all(count > 0 for count in module_counts.values()))

    def test_ci_regenerates_ignored_runtime_skills_before_drift_check(self) -> None:
        workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")
        sync_position = workflow.find("make sync-skills")
        check_position = workflow.find("make check-skills")

        self.assertGreaterEqual(sync_position, 0)
        self.assertGreater(check_position, sync_position)
        self.assertIn(".claude/skills/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_ci_architecture_job_installs_test_collection_dependencies(self) -> None:
        workflow = (ROOT / ".github/workflows/core-os-ci.yml").read_text(encoding="utf-8")

        self.assertIn('python -m pip install -e ".[api,postgres,test]"', workflow)


if __name__ == "__main__":
    unittest.main()
