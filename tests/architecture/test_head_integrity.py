from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.tools.head_integrity import build_head_integrity_report, _pr_gate_delegates_to_p0


ROOT = Path(__file__).resolve().parents[2]


class HeadIntegrityTests(unittest.TestCase):
    def test_pr_gate_must_execute_and_validate_p0_inside_implementation_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "src/novel_forge/tools/pr_governance.py"
            path.parent.mkdir(parents=True)
            body = (
                "def run_pr_governance():\n"
                "    if report['implementation_changed']:\n"
                "        run(('make', 'p0-backend-qualification'))\n"
                "        validate_current_p0(evidence, plan=report)\n"
            )
            path.write_text(body, encoding="utf-8")
            self.assertTrue(_pr_gate_delegates_to_p0(root))
            path.write_text(body.replace("        validate_current_p0", "        # validate_current_p0"), encoding="utf-8")
            self.assertFalse(_pr_gate_delegates_to_p0(root))
            path.write_text(body.replace("report['implementation_changed']", "False"), encoding="utf-8")
            self.assertFalse(_pr_gate_delegates_to_p0(root))

    def test_tracked_import_cannot_target_untracked_runtime_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "src" / "novel_forge" / "sample"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                "from .runtime import Runtime\n__all__ = ['Runtime']\n",
                encoding="utf-8",
            )
            (package / "runtime.py").write_text(
                "class Runtime:\n    pass\n",
                encoding="utf-8",
            )

            report = build_head_integrity_report(
                root,
                tracked_paths={"src/novel_forge/sample/__init__.py"},
                required_imports=(),
            )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.untracked_required_paths,
            ("src/novel_forge/sample/runtime.py",),
        )

    def test_missing_all_export_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "src" / "novel_forge" / "sample"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                "__all__ = ['MissingContract']\n",
                encoding="utf-8",
            )

            report = build_head_integrity_report(
                root,
                tracked_paths={"src/novel_forge/sample/__init__.py"},
                required_imports=(),
            )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.missing_exports,
            ("novel_forge.sample:MissingContract",),
        )

    def test_current_authority_head_is_complete_and_ci_collects_all_suites(self) -> None:
        report = build_head_integrity_report(ROOT)

        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(report.missing_import_targets, ())
        self.assertEqual(report.untracked_required_paths, ())
        self.assertEqual(report.missing_exports, ())
        self.assertEqual(report.missing_registry_targets, ())
        self.assertEqual(report.missing_test_collection, ())


if __name__ == "__main__":
    unittest.main()
