from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.tools.documentation_reality import (
    CANONICAL_DOCUMENTS,
    SCHEMA_VERSION,
    STATUS_VOCABULARY,
    check_repository,
)
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)


class DocumentationRealityTests(unittest.TestCase):
    def test_minimal_evidence_inventory_is_verified_against_real_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)

            report = check_repository(root)

            self.assertEqual(report["status"], "PASS", report)
            self.assertEqual(report["capability_count"], 1)

    def test_unlisted_document_cannot_become_parallel_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            stale = root / "docs" / "adr" / "old-decision.md"
            stale.parent.mkdir(parents=True)
            stale.write_text("# Old decision\n", encoding="utf-8")

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "non-canonical documentation file", "\n".join(report["errors"])
            )

    def test_missing_symbol_fails_the_evidence_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            inventory_path = root / "architecture" / "reality-evidence.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["capabilities"][0]["implementation"][0]["symbol"] = "missing"
            inventory_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn("symbol does not exist", "\n".join(report["errors"]))

    def test_narrative_module_docstring_and_work_package_comment_are_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            (root / "src/example.py").write_text(
                '"""Example architecture."""\n\n'
                "def run() -> str:\n"
                '    """Describe the operation."""\n'
                "    # WP-OLD explains the former flow.\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            errors = "\n".join(report["errors"])
            self.assertIn("docstring must explain an invariant", errors)
            self.assertIn("historical or speculative comment", errors)
            self.assertIn("module docstring is not allowlisted", errors)

    def test_qualified_status_requires_a_current_passing_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            inventory_path = root / "architecture" / "reality-evidence.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["qualification_runs"][0]["implementation_tree_sha"] = (
                "sha256:" + "f" * 64
            )
            inventory_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "does not qualify the current implementation tree",
                "\n".join(report["errors"]),
            )

    def test_generated_web_dependencies_are_outside_repository_comment_policy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            dependency = root / "web/admin/node_modules/example/index.js"
            dependency.parent.mkdir(parents=True)
            dependency.write_text("// TODO: third-party text\n", encoding="utf-8")

            report = check_repository(root)

            self.assertEqual(report["status"], "PASS", report)

    def test_current_repository_satisfies_its_own_reality_contract(self) -> None:
        root = Path(__file__).resolve().parents[2]

        report = check_repository(root)

        self.assertEqual(report["status"], "PASS", report)

    @staticmethod
    def _write_valid_repository(root: Path) -> None:
        for relative in CANONICAL_DOCUMENTS:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Current\n", encoding="utf-8")
        (root / "src").mkdir(exist_ok=True)
        (root / "tests").mkdir(exist_ok=True)
        (root / "migrations").mkdir(exist_ok=True)
        (root / "src/example.py").write_text(
            "def run() -> str:\n    return 'ok'\n", encoding="utf-8"
        )
        (root / "tests/test_example.py").write_text(
            "def test_run() -> None:\n    assert True\n", encoding="utf-8"
        )
        (root / "migrations/v0001.py").write_text(
            'MIGRATION_ID = "0001"\n', encoding="utf-8"
        )
        inventory = {
            "schema_version": SCHEMA_VERSION,
            "authority_order": [
                "executable_code",
                "schema_and_migrations",
                "runtime_wiring",
                "tests",
            ],
            "status_vocabulary": STATUS_VOCABULARY,
            "canonical_documents": CANONICAL_DOCUMENTS,
            "migration_head": "0001",
            "comment_policy": {
                "max_source_comments": 0,
                "max_source_docstrings": 0,
                "allowed_module_docstrings": [],
            },
            "qualification_runs": [
                {
                    "id": "example-qualification",
                    "gate": "pytest",
                    "observed_at_sha": "0" * 40,
                    "collected": 1,
                    "passed": 1,
                    "failed": 0,
                    "implementation_tree_sha": build_implementation_tree_identity(
                        root
                    )["implementation_tree_sha"],
                    "qualification_evidence": [
                        {"path": "tests/test_example.py", "symbol": "test_run"}
                    ],
                }
            ],
            "qualification_failures": [],
            "capabilities": [
                {
                    "concept": "example",
                    "owner": "example owner",
                    "status": "QUALIFIED",
                    "implementation": [{"path": "src/example.py", "symbol": "run"}],
                    "runtime_entries": [{"path": "src/example.py", "symbol": "run"}],
                    "persistence": [
                        {"path": "migrations/v0001.py", "locator": "MIGRATION_ID"}
                    ],
                    "migrations": [
                        {
                            "id": "0001",
                            "path": "migrations/v0001.py",
                            "locator": 'MIGRATION_ID = "0001"',
                        }
                    ],
                    "qualification": [
                        {"path": "tests/test_example.py", "symbol": "test_run"}
                    ],
                    "qualification_run_ids": ["example-qualification"],
                    "proof_ceiling": "ENGINEERING_QUALIFIED",
                }
            ],
            "negative_boundaries": [],
        }
        inventory_path = root / "architecture" / "reality-evidence.json"
        inventory_path.parent.mkdir(parents=True)
        inventory_path.write_text(
            json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
