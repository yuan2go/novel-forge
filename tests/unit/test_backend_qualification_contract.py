from __future__ import annotations

import unittest
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from novel_forge.tools.backend_qualification_contract import (
    PytestCollectionContract,
    QualificationContractError,
    expected_migration_head,
    load_qualification_manifest,
    parse_junit_xml,
    resolved_dependency_snapshot,
    sanitize_evidence,
    validate_resolved_dependency_snapshot,
    validate_collection_report,
)
from novel_forge.tools.architecture_manifest import check_tests


ROOT = Path(__file__).resolve().parents[2]


class BackendQualificationManifestTests(unittest.TestCase):
    def test_integration_collection_is_complete_and_postgresql_required(self) -> None:
        manifest = load_qualification_manifest(ROOT)

        integration = next(
            item for item in manifest.pytest_collections if item.name == "integration"
        )

        self.assertEqual(integration.paths, ("tests/integration",))
        self.assertEqual(integration.classification, "POSTGRESQL_REQUIRED")
        self.assertTrue(integration.complete_collection)
        self.assertFalse(integration.allow_skips)

    def test_repository_test_collections_have_exactly_one_qualification_class(
        self,
    ) -> None:
        result = check_tests(ROOT)

        classifications = {
            item["name"]: item["qualification_class"]
            for item in result["collections"]
        }

        self.assertEqual(
            classifications,
            {
                "acceptance": "BACKEND_NON_POSTGRESQL",
                "architecture": "BACKEND_NON_POSTGRESQL",
                "integration": "POSTGRESQL_REQUIRED",
                "unit": "BACKEND_NON_POSTGRESQL",
            },
        )
        integration = next(
            item for item in result["collections"] if item["name"] == "integration"
        )
        self.assertTrue(integration["complete_collection"])
        self.assertEqual(integration["source_file_count"], integration["collected_file_count"])

    def test_junit_xml_is_the_authority_for_test_counts_and_duration(self) -> None:
        with TemporaryDirectory() as temporary:
            junit = Path(temporary) / "pytest.xml"
            junit.write_text(
                '<testsuites tests="4" failures="1" errors="0" skipped="1" '
                'time="1.250"><testsuite name="pytest" tests="4" failures="1" '
                'errors="0" skipped="1" time="1.250"/></testsuites>',
                encoding="utf-8",
            )

            summary = parse_junit_xml(junit)

        self.assertEqual(
            summary,
            {
                "tests": 4,
                "passed": 2,
                "failures": 1,
                "errors": 0,
                "skipped": 1,
                "duration_seconds": 1.25,
            },
        )

    def test_expected_migration_head_is_derived_from_canonical_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "architecture" / "manifests"
            manifest_path.mkdir(parents=True)
            (manifest_path / "migration-manifest.yaml").write_text(
                json.dumps(
                    {
                        "schema_version": "architecture-manifest.v1",
                        "head": "manifest-driven-head",
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "novel_forge.storage.migrations.runner.LATEST_MIGRATION_ID",
                "manifest-driven-head",
            ):
                observed = expected_migration_head(root)

        self.assertEqual(observed, "manifest-driven-head")

    def test_resolved_dependencies_are_sorted_hashed_and_not_sha_only_reproducible(
        self,
    ) -> None:
        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=json.dumps(
                {
                    "python_implementation": "CPython",
                    "python_version": "3.12.2",
                    "packages": [
                        {"name": "Zeta_Pkg", "version": "2.0"},
                        {"name": "alpha.pkg", "version": "1.0"},
                    ],
                }
            ),
            stderr="",
        )
        with TemporaryDirectory() as temporary, patch(
            "subprocess.run", return_value=completed
        ) as run:
            snapshot = resolved_dependency_snapshot(
                "qualification-python", repo_root=Path(temporary)
            )

        self.assertEqual(snapshot["packages"], ["alpha-pkg==1.0", "zeta-pkg==2.0"])
        self.assertEqual(snapshot["package_count"], 2)
        self.assertRegex(str(snapshot["digest"]), r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(snapshot["reproducibility_class"], "RESOLVED_SNAPSHOT")
        self.assertFalse(snapshot["git_sha_alone_reproducible"])
        self.assertEqual(validate_resolved_dependency_snapshot(snapshot), snapshot)
        tampered = dict(snapshot)
        tampered["packages"] = ["alpha-pkg==1.1", "zeta-pkg==2.0"]
        with self.assertRaisesRegex(QualificationContractError, "digest differs"):
            validate_resolved_dependency_snapshot(tampered)
        run.assert_called_once()

    def test_evidence_sanitizer_removes_secret_fields_and_dsn_values(self) -> None:
        sanitized = sanitize_evidence(
            {
                "database_url": "postgresql://operator:password@127.0.0.1:5432/private",
                "fencing_token": 7,
                "message": "failed for postgresql://user:secret@localhost:5432/db",
                "nested": {"provider_api_key": "sk-private-value"},
            }
        )

        self.assertEqual(sanitized["database_url"], "[REDACTED]")
        self.assertEqual(sanitized["fencing_token"], 7)
        self.assertEqual(sanitized["message"], "failed for [REDACTED_DATABASE_URL]")
        self.assertEqual(sanitized["nested"]["provider_api_key"], "[REDACTED]")
        self.assertNotIn("password", json.dumps(sanitized))
        self.assertNotIn("secret", json.dumps(sanitized))

    def test_complete_collection_report_fails_closed_when_a_test_file_is_absent(
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
            (tests / "test_first.py").write_text(
                "def test_first():\n    pass\n", encoding="utf-8"
            )
            (tests / "test_second.py").write_text(
                "def test_second():\n    pass\n", encoding="utf-8"
            )
            report = root / "collection.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "novel-forge.pytest-collection.v1",
                        "collected_count": 1,
                        "node_ids": ["tests/integration/test_first.py::test_first"],
                        "source_files": ["tests/integration/test_first.py"],
                        "collection_errors": [],
                        "pytest_exit_status": 0,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                QualificationContractError, "missing=.*test_second.py"
            ):
                validate_collection_report(
                    contract=contract, report_path=report, repo_root=root
                )


if __name__ == "__main__":
    unittest.main()
