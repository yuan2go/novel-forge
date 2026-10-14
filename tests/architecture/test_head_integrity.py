from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
from pathlib import Path

from novel_forge.tools.head_integrity import build_head_integrity_report, _pr_gate_delegates_to_p0


ROOT = Path(__file__).resolve().parents[2]


class HeadIntegrityTests(unittest.TestCase):
    def test_retained_migration_imports_require_exact_tracked_manifest_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "src/novel_forge/storage/migrations"
            versions = package / "versions"
            archive = package / "historical/craft_test"
            versions.mkdir(parents=True)
            archive.mkdir(parents=True)
            filename = "v20261014_0205_source_observation_generation_isolation.py"
            (versions / "__init__.py").write_text(f"from .{filename[:-3]} import UPGRADE_STATEMENTS\n")
            (versions / "v20261009_0185_pure_generation_isolation.py").write_text("UPGRADE_STATEMENTS=[]\n")
            retained = archive / filename
            retained.write_text("from .v20261009_0185_pure_generation_isolation import UPGRADE_STATEMENTS\n")
            manifest = archive / "manifest.json"
            manifest.write_text(json.dumps({"contract_version":"published-craft-migration-retention.v1",
                "registered_on_main":False,"modules":[{"original_path":str((versions/filename).relative_to(root)),
                    "retained_path":str(retained.relative_to(root)),"sha256":hashlib.sha256(retained.read_bytes()).hexdigest()}]}))
            tracked = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
            complete = build_head_integrity_report(root, tracked_paths=tracked, required_imports=())
            self.assertEqual(complete.missing_import_targets, ())
            incomplete = build_head_integrity_report(root, tracked_paths=tracked-{str(manifest.relative_to(root))}, required_imports=())
            self.assertIn(str(manifest.relative_to(root)), incomplete.untracked_required_paths)
            retained.write_text(retained.read_text()+"ALTERED=True\n")
            altered = build_head_integrity_report(root, tracked_paths=tracked, required_imports=())
            self.assertTrue(altered.missing_import_targets)

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
