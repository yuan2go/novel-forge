from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from novel_forge.tools.backend_qualification_contract import (
    PytestCollectionContract,
    QualificationContractError,
    build_postgres_pytest_command,
    load_qualification_manifest,
    validate_postgres_test_evidence,
)
from scripts import run_authority_postgres_tests


ROOT = Path(__file__).resolve().parents[2]


class PostgreSQLQualificationRunnerTests(unittest.TestCase):
    def test_command_executes_the_complete_integration_root_with_machine_evidence(
        self,
    ) -> None:
        manifest = load_qualification_manifest(ROOT)
        contract = next(
            item for item in manifest.pytest_collections if item.name == "integration"
        )

        command = build_postgres_pytest_command(
            contract=contract,
            python=sys.executable,
            junit_xml=Path("/tmp/postgresql.xml"),
            collection_report=Path("/tmp/postgresql-collection.json"),
        )

        self.assertIn("tests/integration", command)
        self.assertFalse(any("*" in argument for argument in command))
        self.assertIn("--junitxml=/tmp/postgresql.xml", command)
        self.assertIn("novel_forge.tools.pytest_collection_evidence", command)
        self.assertIn(
            "--novel-forge-collection-report=/tmp/postgresql-collection.json",
            command,
        )

    def test_evidence_rejects_any_skip_in_the_complete_postgresql_collection(
        self,
    ) -> None:
        contract = PytestCollectionContract(
            name="integration",
            paths=("tests/integration",),
            classification="POSTGRESQL_REQUIRED",
            complete_collection=True,
            allow_skips=False,
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests = root / "tests" / "integration"
            tests.mkdir(parents=True)
            for name in ("test_first.py", "test_second.py"):
                (tests / name).write_text("def test_case():\n    pass\n", encoding="utf-8")
            collection = root / "collection.json"
            collection.write_text(
                json.dumps(
                    {
                        "schema_version": "novel-forge.pytest-collection.v1",
                        "collected_count": 2,
                        "node_ids": [
                            "tests/integration/test_first.py::test_case",
                            "tests/integration/test_second.py::test_case",
                        ],
                        "source_files": [
                            "tests/integration/test_first.py",
                            "tests/integration/test_second.py",
                        ],
                        "collection_errors": [],
                        "pytest_exit_status": 0,
                    }
                ),
                encoding="utf-8",
            )
            junit = root / "pytest.xml"
            junit.write_text(
                '<testsuites tests="2" failures="0" errors="0" skipped="1" '
                'time="0.5"><testsuite tests="2" failures="0" errors="0" '
                'skipped="1" time="0.5"/></testsuites>',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(QualificationContractError, "skips"):
                validate_postgres_test_evidence(
                    contract=contract,
                    junit_xml=junit,
                    collection_report=collection,
                    repo_root=root,
                    semantic_slices={
                        "migration": ("tests/integration/test_first.py",),
                    },
                )
            junit.write_text(
                '<testsuites tests="2" failures="0" errors="0" skipped="0" '
                'time="0.5"><testsuite tests="2" failures="0" errors="0" '
                'skipped="0" time="0.5"/></testsuites>',
                encoding="utf-8",
            )
            evidence = validate_postgres_test_evidence(
                contract=contract,
                junit_xml=junit,
                collection_report=collection,
                repo_root=root,
                semantic_slices={
                    "migration": ("tests/integration/test_first.py",),
                },
            )

        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["junit"]["passed"], 2)
        self.assertEqual(
            evidence["semantic_slices"]["migration"],
            ["tests/integration/test_first.py"],
        )

    def test_public_runner_fails_preflight_without_an_explicit_run_owned_dsn(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                key: value
                for key, value in os.environ.items()
                if key
                not in {
                    "NOVEL_FORGE_DATABASE_URL",
                    "NOVEL_FORGE_QUALIFICATION_DATABASE_NAME",
                }
            },
            clear=True,
        ), patch("subprocess.run") as run:
            result = run_authority_postgres_tests.main(
                [
                    "--junit-xml",
                    str(Path(temporary) / "pytest.xml"),
                    "--collection-report",
                    str(Path(temporary) / "collection.json"),
                ]
            )

        self.assertEqual(result, 2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
