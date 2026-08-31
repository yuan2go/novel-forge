from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from novel_forge.tools.backend_qualification_contract import (
    P0_EVIDENCE_CEILINGS,
    REQUIRED_GATE_ORDER,
)
from novel_forge.tools.documentation_reality import (
    CANONICAL_DOCUMENTS,
    SCHEMA_VERSION,
    STATUS_VOCABULARY,
    check_repository,
)
from novel_forge.tools.implementation_tree_identity import (
    build_implementation_tree_identity,
)
from novel_forge.tools.release_run_evidence import (
    build_p0_backend_qualification_report,
)


_DIGEST = "sha256:" + "b" * 64


def _build_valid_p0_report(
    *,
    tested_sha: str,
    source_tree: str,
    implementation_tree_sha: str,
    migration_head: str,
    artifact_root: str,
    artifact_name: str,
) -> dict[str, object]:
    run_id = "p0-" + "2" * 32
    compose_project = "nf-p0-" + "2" * 32
    runtime_project = compose_project + "-runtime"
    database_name = "nf_p0_" + "2" * 32 + "_test"
    manifest = {
        "schema_version": "novel-forge.backend-qualification-manifest.v1",
        "required_gates": list(REQUIRED_GATE_ORDER),
        "expected_migration_head": migration_head,
        "manifest_digests": {
            "architecture/manifests/migration-manifest.yaml": _DIGEST
        },
        "evidence_ceilings": dict(P0_EVIDENCE_CEILINGS),
    }
    pytest_evidence = {
        "schema_version": "novel-forge.backend-pytest-evidence.v1",
        "status": "PASS",
        "junit": {
            "tests": 1,
            "passed": 1,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "duration_seconds": 0.1,
            "artifact": "backend.xml",
            "digest": _DIGEST,
        },
        "collection": {
            "complete_collection": True,
            "collected_count": 1,
            "source_file_count": 1,
            "pytest_exit_status": 0,
            "report_digest": _DIGEST,
        },
        "case_accounting": {
            "authority": "JUNIT_XML",
            "junit_case_count": 1,
            "collected_node_count": 1,
            "additional_junit_case_count": 0,
        },
    }
    postgres_evidence = {
        **pytest_evidence,
        "schema_version": "novel-forge.postgresql-pytest-evidence.v1",
        "semantic_slices": {
            "migration_matrix": [
                "tests/integration/test_authority_migrations_postgres.py"
            ]
        },
    }
    documentation_evidence = {
        "schema_version": "novel-forge.documentation-reality-check.v1",
        "evidence_class": "reality_inventory",
        "status": "PASS",
        "tested_sha": tested_sha,
        "inventory_sha256": _DIGEST,
        "canonical_document_count": len(CANONICAL_DOCUMENTS),
        "capability_count": 1,
        "source_comment_count": 0,
        "module_docstring_count": 0,
        "source_docstring_count": 0,
        "errors": [],
        "artifact": "documentation-reality.json",
        "digest": _DIGEST,
    }
    cleanup = {
        "status": "PASS",
        "remaining_resource_count": 0,
        "phases": [
            {
                "phase": "postgresql",
                "status": "PASS",
                "resource_count": 1,
                "remaining_resource_count": 0,
                "run_id": run_id,
                "compose_project": compose_project,
                "receipt": f"compose-resource-ownership-{compose_project}.json",
            },
            {
                "phase": "compose-runtime",
                "status": "PASS",
                "resource_count": 1,
                "remaining_resource_count": 0,
                "run_id": run_id,
                "compose_project": runtime_project,
                "receipt": f"compose-resource-ownership-{runtime_project}.json",
            },
        ],
    }
    gates = [
        {
            "gate_id": gate_id,
            "status": "PASS",
            "duration_seconds": 0.1,
            "evidence": (
                {
                    "commit_sha": tested_sha,
                    "source_tree": source_tree,
                    "dirty": False,
                    "implementation_tree_sha": implementation_tree_sha,
                }
                if gate_id == "source-preflight"
                else documentation_evidence
                if gate_id == "documentation-reality"
                else pytest_evidence
                if gate_id == "pytest-backend"
                else {"returncode": 0}
                if gate_id == "static-and-manifests"
                else {
                    "database_identity": {
                        "database_name": database_name,
                        "host_class": "LOOPBACK",
                        "port": 55432,
                        "server_identity_digest": _DIGEST,
                    },
                    "dynamic_port": True,
                    "ownership_resource_count": 2,
                }
                if gate_id == "postgresql-start"
                else postgres_evidence
                if gate_id
                in {"migration-compatibility", "pytest-postgresql-integration"}
                else {
                    "expected_head": migration_head,
                    "observed_head": migration_head,
                    "applied_count": 1,
                    "missing": [],
                    "extra": [],
                }
                if gate_id in {"migration-fresh", "migration-head"}
                else {"artifact": "query-plan.json", "digest": _DIGEST}
                if gate_id == "query-plan-release"
                else {
                    "artifact": "compose-runtime.json",
                    "digest": _DIGEST,
                    "pre_restart_operation_id": "operation-pre",
                    "recovered_operation_id": "operation-recovered",
                    "post_restart_operation_id": "operation-post",
                    "authoritative_side_effect": True,
                }
                if gate_id == "compose-runtime"
                else cleanup
                if gate_id == "resource-cleanup"
                else {"artifact": artifact_name, "atomic_write": True}
                if gate_id == "evidence-finalization"
                else {}
            ),
        }
        for gate_id in REQUIRED_GATE_ORDER
    ]
    dependency = {
        "schema_version": "novel-forge.resolved-dependency-snapshot.v1",
        "python_implementation": "CPython",
        "python_version": "3.12.2",
        "package_count": 2,
        "packages": ["alpha==1", "beta==2"],
        "provenance_files": [],
        "digest": (
            "sha256:da996a55bccd5c2080004a0d3c9636153d5a8980cb1aebbeb9d2e0e466a5f78d"
        ),
        "git_sha_alone_reproducible": False,
        "reproducibility_class": "RESOLVED_SNAPSHOT",
    }
    return build_p0_backend_qualification_report(
        tested_sha=tested_sha,
        source_tree=source_tree,
        source_identity={
            "commit_sha": tested_sha,
            "source_tree": source_tree,
            "dirty": False,
            "branch": "test",
            "workflow_sha": "",
            "implementation_tree_sha": implementation_tree_sha,
        },
        manifest=manifest,
        dependency_snapshot=dependency,
        gates=gates,
        cleanup=cleanup,
        run_identity={
            "run_id": run_id,
            "compose_project": compose_project,
            "compose_runtime_project": runtime_project,
            "database_name": database_name,
            "artifact_root": artifact_root,
        },
    )


def _bind_retained_p0_report(root: Path, inventory_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Novel Forge Test",
            "-c",
            "user.email=novel-forge-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=root,
        check=True,
    )
    tested_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    token = "2" * 32
    artifact_name = f"p0-backend-qualification-{tested_sha}.json"
    artifact_root = f"novel-forge-p0-{tested_sha[:12]}-{token}"
    implementation_tree_sha = build_implementation_tree_identity(root)[
        "implementation_tree_sha"
    ]
    report = _build_valid_p0_report(
        tested_sha=tested_sha,
        source_tree=source_tree,
        implementation_tree_sha=implementation_tree_sha,
        migration_head="0001",
        artifact_root=artifact_root,
        artifact_name=artifact_name,
    )
    report_path = root / "architecture/evidence" / artifact_name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_bytes = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    report_path.write_bytes(report_bytes)

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    run = inventory["qualification_runs"][0]
    run.update(
        {
            "observed_at_sha": tested_sha,
            "source_tree": source_tree,
            "dependency_snapshot_digest": report["dependency_snapshot"]["digest"],
            "qualification_report": {
                "run_id": "p0-" + token,
                "artifact_root": artifact_root,
                "artifact": artifact_name,
                "repository_path": f"architecture/evidence/{artifact_name}",
                "sha256": "sha256:" + hashlib.sha256(report_bytes).hexdigest(),
                "retention": "REPOSITORY_CURRENT_QUALIFICATION_ARTIFACT",
            },
            "implementation_tree_sha": implementation_tree_sha,
        }
    )
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")


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

    def test_malformed_qualification_counts_fail_closed_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            inventory_path = root / "architecture" / "reality-evidence.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["qualification_runs"][0]["failed"] = "not-an-int"
            inventory_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            errors = "\n".join(report["errors"])
            self.assertIn("result counts must be non-negative integers", errors)
            self.assertIn("references a run with invalid results", errors)

    def test_boolean_qualification_counts_do_not_qualify_as_integers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            inventory_path = root / "architecture" / "reality-evidence.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            inventory["qualification_runs"][0].update(
                {"collected": True, "passed": True, "failed": False}
            )
            inventory_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            errors = "\n".join(report["errors"])
            self.assertIn("result counts must be non-negative integers", errors)
            self.assertIn("references a run with invalid results", errors)

    def test_qualified_status_fails_closed_on_invalid_p0_projection(self) -> None:
        mutations = (
            (
                "gate",
                lambda run: run["gates"][1].update(status="FAIL"),
                "gates contain a non-passing result",
            ),
            (
                "collection-completeness",
                lambda run: run["collections"][0].update(complete=False),
                "is not a complete collection",
            ),
            (
                "unexpected-skip",
                lambda run: run["collections"][2].update(skipped=1),
                "contains skipped cases",
            ),
            (
                "migration-head",
                lambda run: run["migration"].update(observed_head="0002"),
                "migration does not prove the inventory head",
            ),
            (
                "cleanup",
                lambda run: run["cleanup"].update(remaining_resource_count=1),
                "cleanup is not zero-residue receipt-bound PASS",
            ),
            (
                "boolean-cleanup-count",
                lambda run: run["cleanup"].update(remaining_resource_count=False),
                "cleanup is not zero-residue receipt-bound PASS",
            ),
            (
                "duplicate-cleanup-phase",
                lambda run: run["cleanup"]["phases"].__setitem__(
                    1, dict(run["cleanup"]["phases"][0])
                ),
                "cleanup is not zero-residue receipt-bound PASS",
            ),
            (
                "missing-cleanup-receipt",
                lambda run: run["cleanup"]["phases"][1].pop("receipt"),
                "cleanup is not zero-residue receipt-bound PASS",
            ),
            (
                "dependency-digest",
                lambda run: run.update(dependency_snapshot_digest="not-a-digest"),
                "dependency_snapshot_digest must be a SHA-256 digest",
            ),
            (
                "report-digest",
                lambda run: run["qualification_report"].update(sha256="bad"),
                "qualification_report.sha256 must be a SHA-256 digest",
            ),
            (
                "report-digest-mismatch",
                lambda run: run["qualification_report"].update(
                    sha256="sha256:" + "c" * 64
                ),
                "qualification_report artifact digest differs",
            ),
            (
                "git-tree-mismatch",
                lambda run: run.update(source_tree="f" * 40),
                "source_tree differs from the observed Git commit",
            ),
            (
                "fabricated-git-commit",
                lambda run: run.update(observed_at_sha="f" * 40),
                "observed_at_sha is not an ancestor Git commit",
            ),
            (
                "report-projection-mismatch",
                lambda run: (
                    run["cleanup"]["phases"][0].update(resource_count=2),
                    run["cleanup"].update(owned_resource_count=3),
                ),
                "cleanup differs from the retained qualification report",
            ),
        )
        for label, mutate, expected in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_valid_repository(root)
                inventory_path = root / "architecture" / "reality-evidence.json"
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                mutate(inventory["qualification_runs"][0])
                inventory_path.write_text(
                    json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
                )

                report = check_repository(root)

                self.assertEqual(report["status"], "FAIL")
                errors = "\n".join(report["errors"])
                self.assertIn(expected, errors)
                self.assertIn("references a run with invalid results", errors)

    def test_missing_or_unreferenced_retained_report_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            inventory = json.loads(
                (root / "architecture/reality-evidence.json").read_text(
                    encoding="utf-8"
                )
            )
            repository_path = inventory["qualification_runs"][0][
                "qualification_report"
            ]["repository_path"]
            (root / repository_path).unlink()

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "qualification_report artifact is missing",
                "\n".join(report["errors"]),
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            stale = root / "architecture/evidence/stale.json"
            stale.write_text("{}\n", encoding="utf-8")

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "unreferenced retained qualification artifact",
                "\n".join(report["errors"]),
            )

    def test_old_report_cannot_be_rebound_to_a_new_implementation_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            (root / "src/example.py").write_text(
                "def run() -> str:\n    return 'changed'\n", encoding="utf-8"
            )
            subprocess.run(["git", "add", "src/example.py"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Novel Forge Test",
                    "-c",
                    "user.email=novel-forge-test@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "implementation change",
                ],
                cwd=root,
                check=True,
            )
            inventory_path = root / "architecture/reality-evidence.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            run = inventory["qualification_runs"][0]
            implementation_tree_sha = build_implementation_tree_identity(root)[
                "implementation_tree_sha"
            ]
            run["implementation_tree_sha"] = implementation_tree_sha
            artifact = run["qualification_report"]
            report_path = root / artifact["repository_path"]
            retained = json.loads(report_path.read_text(encoding="utf-8"))
            retained["implementation_tree_sha"] = implementation_tree_sha
            retained["source_identity"][
                "implementation_tree_sha"
            ] = implementation_tree_sha
            source_preflight = next(
                gate
                for gate in retained["gates"]
                if gate["gate_id"] == "source-preflight"
            )
            source_preflight["evidence"][
                "implementation_tree_sha"
            ] = implementation_tree_sha
            report_bytes = (
                json.dumps(retained, indent=2, sort_keys=True) + "\n"
            ).encode()
            report_path.write_bytes(report_bytes)
            artifact["sha256"] = "sha256:" + hashlib.sha256(report_bytes).hexdigest()
            inventory_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "does not match the observed Git implementation tree",
                "\n".join(report["errors"]),
            )

    def test_retained_report_must_prove_a_clean_fresh_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_valid_repository(root)
            inventory_path = root / "architecture/reality-evidence.json"
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            artifact = inventory["qualification_runs"][0]["qualification_report"]
            report_path = root / artifact["repository_path"]
            retained = json.loads(report_path.read_text(encoding="utf-8"))
            migration_fresh = next(
                gate
                for gate in retained["gates"]
                if gate["gate_id"] == "migration-fresh"
            )
            migration_fresh["evidence"].update(
                observed_head="wrong-head",
                missing=["0001"],
                extra=["wrong-head"],
            )
            report_bytes = (
                json.dumps(retained, indent=2, sort_keys=True) + "\n"
            ).encode()
            report_path.write_bytes(report_bytes)
            artifact["sha256"] = "sha256:" + hashlib.sha256(report_bytes).hexdigest()
            inventory_path.write_text(
                json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
            )

            report = check_repository(root)

            self.assertEqual(report["status"], "FAIL")
            self.assertIn(
                "fresh migration does not prove the canonical migration head",
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
                    "evidence_class": "p0_backend_engineering_qualification",
                    "observed_at_sha": "0" * 40,
                    "source_tree": "1" * 40,
                    "dependency_snapshot_digest": "sha256:" + "d" * 64,
                    "qualification_report": {
                        "run_id": "p0-" + "2" * 32,
                        "artifact_root": (
                            "novel-forge-p0-000000000000-" + "2" * 32
                        ),
                        "artifact": "p0-backend-qualification-" + "0" * 40 + ".json",
                        "sha256": "sha256:" + "e" * 64,
                        "retention": "EXTERNAL_QUALIFICATION_ARTIFACT",
                    },
                    "result_count_scope": "UNIQUE_COMPLETE_COLLECTION_JUNIT_CASES",
                    "collected": 2,
                    "passed": 2,
                    "failed": 0,
                    "collections": [
                        {
                            "classification": "BACKEND_NON_POSTGRESQL",
                            "collected_nodes": 1,
                            "junit_cases": 1,
                            "passed": 1,
                            "skipped": 0,
                            "complete": True,
                        },
                        {
                            "classification": "MIGRATION_COMPATIBILITY",
                            "collected_nodes": 1,
                            "junit_cases": 1,
                            "passed": 1,
                            "skipped": 0,
                            "complete": True,
                            "repeated_in_postgresql_collection": True,
                        },
                        {
                            "classification": "POSTGRESQL_REQUIRED",
                            "collected_nodes": 1,
                            "junit_cases": 1,
                            "passed": 1,
                            "skipped": 0,
                            "complete": True,
                        },
                    ],
                    "gates": [
                        {"id": gate_id, "status": "PASS"}
                        for gate_id in REQUIRED_GATE_ORDER
                    ],
                    "migration": {
                        "applied_count": 1,
                        "expected_head": "0001",
                        "observed_head": "0001",
                    },
                    "cleanup": {
                        "status": "PASS",
                        "owned_resource_count": 2,
                        "remaining_resource_count": 0,
                        "phases": [
                            {
                                "phase": "postgresql",
                                "status": "PASS",
                                "resource_count": 1,
                                "remaining_resource_count": 0,
                                "run_id": "p0-" + "2" * 32,
                                "compose_project": "nf-p0-" + "2" * 32,
                                "receipt": (
                                    "compose-resource-ownership-nf-p0-"
                                    + "2" * 32
                                    + ".json"
                                ),
                            },
                            {
                                "phase": "compose-runtime",
                                "status": "PASS",
                                "resource_count": 1,
                                "remaining_resource_count": 0,
                                "run_id": "p0-" + "2" * 32,
                                "compose_project": (
                                    "nf-p0-" + "2" * 32 + "-runtime"
                                ),
                                "receipt": (
                                    "compose-resource-ownership-nf-p0-"
                                    + "2" * 32
                                    + "-runtime.json"
                                ),
                            },
                        ],
                    },
                    "evidence_ceilings": P0_EVIDENCE_CEILINGS,
                    "implementation_tree_sha": build_implementation_tree_identity(root)[
                        "implementation_tree_sha"
                    ],
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
        _bind_retained_p0_report(root, inventory_path)


if __name__ == "__main__":
    unittest.main()
