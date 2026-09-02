from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import signal
import sys
from tempfile import TemporaryDirectory
from typing import Sequence
import unittest
from unittest.mock import patch

from novel_forge.tools.backend_qualification_contract import (
    PytestCollectionContract,
    QualificationContractError,
    build_backend_pytest_command,
    build_postgres_pytest_command,
    load_qualification_manifest,
    validate_compose_runtime_evidence,
    validate_postgres_test_evidence,
)
from novel_forge.tools.backend_qualification import (
    ProcessResult,
    SubprocessProcessRunner,
    run_qualification,
)
from scripts import run_authority_postgres_tests


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


def _documentation_report() -> str:
    return json.dumps(
        {
            "schema_version": "novel-forge.documentation-reality-check.v1",
            "evidence_class": "reality_inventory",
            "status": "PASS",
            "tested_sha": SHA,
            "inventory_sha256": "sha256:" + "d" * 64,
            "canonical_document_count": 5,
            "capability_count": 13,
            "source_comment_count": 1,
            "module_docstring_count": 1,
            "source_docstring_count": 1,
            "errors": [],
        }
    )


def _compose_operation(operation_id: str, *, fencing_token: int = 1) -> dict[str, object]:
    return {
        "status": "PASS",
        "operation_id": operation_id,
        "operation_status": "SUCCEEDED",
        "attempt_count": 1,
        "lease_count": 1,
        "max_fencing_token": fencing_token,
        "output_asset_count": 1,
        "audit_count": 1,
        "published_outbox_count": 1,
        "fixture": True,
        "real_provider_proven": False,
    }


def _compose_evidence() -> dict[str, object]:
    return {
        "schema_version": "novel-forge.compose-runtime-evidence.v1",
        "status": "PASS",
        "commit_sha": SHA,
        "run_id": "p0-" + "1" * 32,
        "project_name": "nf-p0-" + "1" * 32 + "-runtime",
        "steps": [
            "clean_compose_ready",
            "required_worker_fleet_ready",
            "synthetic_operation_completed",
            "pending_operation_recovered_after_worker_restart",
            "post_restart_operation_completed",
            "graceful_drain_released_connections",
        ],
        "normal_operation": _compose_operation("operation:normal"),
        "recovered_operation": _compose_operation(
            "operation:recovered", fencing_token=2
        ),
        "post_restart_operation": _compose_operation("operation:post"),
        "expired_lease": {
            "attempt_id": "attempt:expired",
            "worker_id": "content-crashed-worker",
            "fencing_token": 1,
        },
        "stale_fence": {
            "status": "PASS",
            "rejected_error_code": "ATTEMPT_FENCING_TOKEN_STALE",
        },
        "worker_restart": {
            "worker_id": "content-authority-worker-1",
            "worker_kind": "content",
            "before_stop": {
                "status": "READY",
                "drain_status": "ACCEPTING",
                "updated_at": "2026-08-30T01:00:00Z",
                "last_heartbeat_at": "2026-08-30T01:00:00Z",
            },
            "stopped": {
                "status": "STOPPED",
                "drain_status": "DRAINED",
                "updated_at": "2026-08-30T01:01:00Z",
                "last_heartbeat_at": "2026-08-30T01:01:00Z",
            },
            "after_recovery_start": {
                "status": "READY",
                "drain_status": "ACCEPTING",
                "updated_at": "2026-08-30T01:02:00Z",
                "last_heartbeat_at": "2026-08-30T01:02:00Z",
            },
            "before_forced_restart": {
                "status": "READY",
                "drain_status": "ACCEPTING",
                "updated_at": "2026-08-30T01:03:00Z",
                "last_heartbeat_at": "2026-08-30T01:02:00Z",
            },
            "after_forced_restart": {
                "status": "READY",
                "drain_status": "ACCEPTING",
                "updated_at": "2026-08-30T01:04:00Z",
                "last_heartbeat_at": "2026-08-30T01:02:00Z",
            },
            "container_before_forced_restart": {
                "container_id": "container:content",
                "started_at": "2026-08-30T01:00:00Z",
            },
            "container_after_forced_restart": {
                "container_id": "container:content",
                "started_at": "2026-08-30T01:03:30Z",
            },
            "projection_changed": True,
        },
        "shutdown_database_governance": {
            "idle_in_transaction": 0,
            "active_transactions": 0,
            "worker_connections": 0,
        },
        "drained_worker_count": 10,
        "cleanup": {
            "status": "PASS",
            "resource_count": 2,
            "remaining_resource_count": 0,
            "run_id": "p0-" + "1" * 32,
            "compose_project": "nf-p0-" + "1" * 32 + "-runtime",
            "receipt": (
                "compose-resource-ownership-nf-p0-"
                + "1" * 32
                + "-runtime.json"
            ),
        },
        "fixture": True,
        "real_provider_proven": False,
        "longform_proven": False,
        "production_verified": False,
    }


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
                '<testsuites tests="3" failures="0" errors="0" skipped="0" '
                'time="0.5"><testsuite tests="3" failures="0" errors="0" '
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
        self.assertEqual(evidence["junit"]["passed"], 3)
        self.assertEqual(
            evidence["case_accounting"],
            {
                "authority": "JUNIT_XML",
                "junit_case_count": 3,
                "collected_node_count": 2,
                "additional_junit_case_count": 1,
            },
        )
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


class BackendQualificationCliTests(unittest.TestCase):
    def test_compose_proof_requires_post_restart_authoritative_side_effect(
        self,
    ) -> None:
        evidence = _compose_evidence()
        validated = validate_compose_runtime_evidence(
            evidence,
            expected_sha=SHA,
            expected_run_id="p0-" + "1" * 32,
            expected_project="nf-p0-" + "1" * 32 + "-runtime",
        )
        self.assertEqual(validated["status"], "PASS")

        invalid = dict(evidence)
        invalid["post_restart_operation"] = {
            **invalid["post_restart_operation"],
            "output_asset_count": 0,
        }
        with self.assertRaisesRegex(
            QualificationContractError, "post-restart authoritative side effect"
        ):
            validate_compose_runtime_evidence(
                invalid,
                expected_sha=SHA,
                expected_run_id="p0-" + "1" * 32,
                expected_project="nf-p0-" + "1" * 32 + "-runtime",
            )

        for field, value in (
            ("remaining_resource_count", False),
            ("resource_count", False),
            ("receipt", ""),
        ):
            with self.subTest(cleanup_field=field):
                malformed_cleanup = copy.deepcopy(_compose_evidence())
                malformed_cleanup["cleanup"][field] = value
                with self.assertRaisesRegex(
                    QualificationContractError, "cleanup"
                ):
                    validate_compose_runtime_evidence(
                        malformed_cleanup,
                        expected_sha=SHA,
                        expected_run_id="p0-" + "1" * 32,
                        expected_project="nf-p0-" + "1" * 32 + "-runtime",
                    )

    def test_compose_proof_requires_changed_container_start_identity(self) -> None:
        evidence = _compose_evidence()
        restart = dict(evidence["worker_restart"])
        restart["container_after_forced_restart"] = dict(
            restart["container_before_forced_restart"]
        )
        evidence["worker_restart"] = restart

        with self.assertRaisesRegex(
            QualificationContractError, "container lifecycle"
        ):
            validate_compose_runtime_evidence(
                evidence,
                expected_sha=SHA,
                expected_run_id="p0-" + "1" * 32,
                expected_project="nf-p0-" + "1" * 32 + "-runtime",
            )

    def test_preflight_rejects_any_real_provider_route_before_commands(self) -> None:
        class ForbiddenRunner:
            def run(self, command: Sequence[str], **_kwargs: object) -> ProcessResult:
                raise AssertionError(f"command must not run: {command}")

        with TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "NOVEL_FORGE_MODEL_PROVIDER": "mock",
                "NOVEL_FORGE_DRAFT_PROVIDER": "openai",
            },
        ):
            result = run_qualification(
                [
                    "--repo-root",
                    str(ROOT),
                    "--profile",
                    "local",
                    "--output",
                    str(Path(temporary) / "report.json"),
                ],
                process_runner=ForbiddenRunner(),
            )

        self.assertEqual(result, 2)

    def test_list_gates_is_read_only_and_manifest_ordered(self) -> None:
        with patch("builtins.print") as output:
            result = run_qualification(
                ["--repo-root", str(ROOT), "--list-gates"]
            )

        self.assertEqual(result, 0)
        payload = json.loads(output.call_args.args[0])
        manifest = load_qualification_manifest(ROOT)
        self.assertEqual(payload["gates"], list(manifest.required_gates))
        self.assertEqual(payload["profile"], "inspection")

    def test_documentation_reality_failure_is_an_explicit_fail_fast_gate(
        self,
    ) -> None:
        commands: list[tuple[str, ...]] = []

        class FailingDocumentationRunner:
            def run(self, command: Sequence[str], **_kwargs: object) -> ProcessResult:
                parts = tuple(command)
                commands.append(parts)
                if parts[-2:] == ("rev-parse", "HEAD"):
                    return ProcessResult.success(parts, SHA + "\n")
                if parts[-2:] == ("rev-parse", "HEAD^{tree}"):
                    return ProcessResult.success(parts, "c" * 40 + "\n")
                if "status" in parts:
                    return ProcessResult.success(parts, "")
                if "--show-current" in parts:
                    return ProcessResult.success(parts, "feature\n")
                if "novel_forge.tools.documentation_reality" in parts:
                    return ProcessResult(
                        command=parts,
                        returncode=1,
                        stdout=json.dumps(
                            {
                                **json.loads(_documentation_report()),
                                "status": "FAIL",
                                "errors": ["stale reality inventory"],
                            }
                        ),
                        stderr="",
                        duration_seconds=0.1,
                        timed_out=False,
                    )
                raise AssertionError(f"gate ran after documentation failure: {parts}")

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "p0-report.json"
            result = run_qualification(
                [
                    "--repo-root",
                    str(ROOT),
                    "--profile",
                    "local",
                    "--output",
                    str(output),
                ],
                process_runner=FailingDocumentationRunner(),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        statuses = {item["gate_id"]: item["status"] for item in report["gates"]}
        self.assertEqual(statuses["source-preflight"], "PASS")
        self.assertEqual(statuses["documentation-reality"], "FAIL")
        self.assertEqual(statuses["static-and-manifests"], "NOT_RUN")
        self.assertFalse(any("p0-backend-static" in command for command in commands))

    def test_failed_static_gate_writes_partial_report_and_marks_dependents_not_run(
        self,
    ) -> None:
        commands: list[tuple[str, ...]] = []

        class FailingStaticRunner:
            def run(self, command: Sequence[str], **_kwargs: object) -> ProcessResult:
                parts = tuple(command)
                commands.append(parts)
                if parts[-2:] == ("rev-parse", "HEAD"):
                    return ProcessResult.success(parts, SHA + "\n")
                if parts[-2:] == ("rev-parse", "HEAD^{tree}"):
                    return ProcessResult.success(parts, "c" * 40 + "\n")
                if "status" in parts:
                    return ProcessResult.success(parts, "")
                if "--show-current" in parts:
                    return ProcessResult.success(parts, "feature\n")
                if "novel_forge.tools.documentation_reality" in parts:
                    return ProcessResult.success(parts, _documentation_report())
                return ProcessResult(
                    command=parts,
                    returncode=1,
                    stdout="",
                    stderr="static gate failed",
                    duration_seconds=0.2,
                    timed_out=False,
                )

        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "p0-report.json"
            result = run_qualification(
                [
                    "--repo-root",
                    str(ROOT),
                    "--profile",
                    "local",
                    "--output",
                    str(output),
                ],
                process_runner=FailingStaticRunner(),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result, 1)
        self.assertEqual(report["decision"], "FAIL")
        statuses = {item["gate_id"]: item["status"] for item in report["gates"]}
        self.assertEqual(statuses["source-preflight"], "PASS")
        self.assertEqual(statuses["documentation-reality"], "PASS")
        self.assertEqual(statuses["static-and-manifests"], "FAIL")
        self.assertEqual(statuses["pytest-backend"], "NOT_RUN")
        self.assertEqual(report["cleanup"]["status"], "PASS")
        self.assertEqual(report["proof_scope"]["ceiling"], "LOCAL_BACKEND_ENGINEERING")
        self.assertIn("ADMIN_UI_EXECUTION", report["proof_scope"]["does_not_establish"])
        self.assertTrue(any("p0-backend-static" in command for command in commands))

    def test_migration_compatibility_passes_before_complete_postgresql_failure(
        self,
    ) -> None:
        commands: list[tuple[str, ...]] = []

        class FakeRunner:
            def run(self, command: Sequence[str], **_kwargs: object) -> ProcessResult:
                parts = tuple(command)
                commands.append(parts)
                if parts[-2:] == ("rev-parse", "HEAD"):
                    return ProcessResult.success(parts, SHA + "\n")
                if parts[-2:] == ("rev-parse", "HEAD^{tree}"):
                    return ProcessResult.success(parts, "c" * 40 + "\n")
                if "status" in parts:
                    return ProcessResult.success(parts, "")
                if "--show-current" in parts:
                    return ProcessResult.success(parts, "feature\n")
                if "novel_forge.tools.documentation_reality" in parts:
                    return ProcessResult.success(parts, _documentation_report())
                if "scripts/run_authority_postgres_tests.py" in parts:
                    return ProcessResult(
                        command=parts,
                        returncode=1,
                        stdout="",
                        stderr="current PostgreSQL failure",
                        duration_seconds=0.1,
                        timed_out=False,
                    )
                return ProcessResult.success(parts)

        class FakeDocker:
            def run_compose(self, **_kwargs: object) -> None:
                return None

            def published_port(self, **_kwargs: object) -> int:
                return 49152

        class FakeOwned:
            instances: list["FakeOwned"] = []

            def __init__(self, **_kwargs: object) -> None:
                self.cleanup_calls = 0
                self.__class__.instances.append(self)

            def assert_unclaimed(self) -> None:
                return None

            def capture(self) -> dict[str, object]:
                return {"resources": [{"id": "postgres"}]}

            def cleanup_discovered(self) -> dict[str, object]:
                self.cleanup_calls += 1
                return {
                    "status": "PASS",
                    "resource_count": 1,
                    "remaining_resource_count": 0,
                }

        manifest = load_qualification_manifest(ROOT)
        migration_paths = tuple(manifest.semantic_slices["migration_matrix"])
        migration_evidence = {
            "status": "PASS",
            "junit": {"tests": 1, "passed": 1, "skipped": 0},
            "collection": {"complete_collection": True},
        }
        with TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"NOVEL_FORGE_MODEL_PROVIDER": "scripted"},
            clear=True,
        ), patch(
            "novel_forge.tools.backend_qualification.DockerComposeClient.from_environment",
            return_value=FakeDocker(),
        ), patch(
            "novel_forge.tools.backend_qualification.OwnedComposeProject", FakeOwned
        ), patch(
            "novel_forge.tools.backend_qualification._migration_evidence",
            side_effect=lambda _database_url, head: {
                "expected_head": head,
                "observed_head": head,
                "applied_count": 1,
                "missing": [],
                "extra": [],
            },
        ), patch(
            "novel_forge.tools.backend_qualification.validate_backend_test_evidence",
            return_value={"status": "PASS"},
        ), patch(
            "novel_forge.tools.backend_qualification.validate_postgres_test_evidence",
            side_effect=(migration_evidence, {"status": "FAIL"}),
        ):
            output = Path(temporary) / "p0-report.json"
            result = run_qualification(
                [
                    "--repo-root",
                    str(ROOT),
                    "--profile",
                    "local",
                    "--output",
                    str(output),
                ],
                process_runner=FakeRunner(),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        migration_command = next(
            command
            for command in commands
            if set(migration_paths).issubset(set(command))
        )
        self.assertTrue(set(migration_paths).issubset(migration_command))
        statuses = {item["gate_id"]: item["status"] for item in report["gates"]}
        self.assertEqual(result, 1)
        self.assertEqual(statuses["migration-compatibility"], "PASS")
        self.assertEqual(statuses["pytest-postgresql-integration"], "FAIL")
        self.assertEqual(statuses["resource-cleanup"], "PASS")
        self.assertEqual(FakeOwned.instances[0].cleanup_calls, 1)

    def test_unexpected_gate_exception_writes_failure_and_cleans_owned_resources(
        self,
    ) -> None:
        class FakeRunner:
            def run(self, command: Sequence[str], **_kwargs: object) -> ProcessResult:
                parts = tuple(command)
                if parts[-2:] == ("rev-parse", "HEAD"):
                    return ProcessResult.success(parts, SHA + "\n")
                if parts[-2:] == ("rev-parse", "HEAD^{tree}"):
                    return ProcessResult.success(parts, "c" * 40 + "\n")
                if "status" in parts:
                    return ProcessResult.success(parts, "")
                if "--show-current" in parts:
                    return ProcessResult.success(parts, "feature\n")
                if "novel_forge.tools.documentation_reality" in parts:
                    return ProcessResult.success(parts, _documentation_report())
                return ProcessResult.success(parts)

        class FakeDocker:
            def run_compose(self, **_kwargs: object) -> None:
                return None

            def published_port(self, **_kwargs: object) -> int:
                return 49152

        class FakeOwned:
            cleanup_calls = 0

            def __init__(self, **_kwargs: object) -> None:
                return None

            def assert_unclaimed(self) -> None:
                return None

            def capture(self) -> dict[str, object]:
                return {"resources": [{"id": "postgres"}]}

            def cleanup_discovered(self) -> dict[str, object]:
                self.__class__.cleanup_calls += 1
                return {
                    "status": "PASS",
                    "resource_count": 1,
                    "remaining_resource_count": 0,
                }

        with TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"NOVEL_FORGE_MODEL_PROVIDER": "scripted"},
            clear=True,
        ), patch(
            "novel_forge.tools.backend_qualification.DockerComposeClient.from_environment",
            return_value=FakeDocker(),
        ), patch(
            "novel_forge.tools.backend_qualification.OwnedComposeProject", FakeOwned
        ), patch(
            "novel_forge.tools.backend_qualification._migration_evidence",
            side_effect=lambda _database_url, head: {
                "expected_head": head,
                "observed_head": head,
                "applied_count": 1,
                "missing": [],
                "extra": [],
            },
        ), patch(
            "novel_forge.tools.backend_qualification.validate_backend_test_evidence",
            return_value={"status": "PASS"},
        ), patch(
            "novel_forge.tools.backend_qualification.validate_postgres_test_evidence",
            side_effect=LookupError("unexpected validator failure"),
        ):
            output = Path(temporary) / "p0-report.json"
            result = run_qualification(
                [
                    "--repo-root",
                    str(ROOT),
                    "--profile",
                    "local",
                    "--output",
                    str(output),
                ],
                process_runner=FakeRunner(),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        statuses = {item["gate_id"]: item["status"] for item in report["gates"]}
        self.assertEqual(result, 1)
        self.assertEqual(statuses["migration-compatibility"], "FAIL")
        self.assertEqual(statuses["resource-cleanup"], "PASS")
        self.assertIn("unexpected LookupError", report["failure_reason"])
        self.assertEqual(FakeOwned.cleanup_calls, 1)

    def test_backend_pytest_gate_is_complete_machine_readable_and_non_postgresql(
        self,
    ) -> None:
        manifest = load_qualification_manifest(ROOT)
        contracts = tuple(
            item
            for item in manifest.pytest_collections
            if item.classification == "BACKEND_NON_POSTGRESQL"
        )

        command = build_backend_pytest_command(
            contracts=contracts,
            python=sys.executable,
            junit_xml=Path("/tmp/backend.xml"),
            collection_report=Path("/tmp/backend-collection.json"),
        )

        self.assertTrue(
            {"tests/unit", "tests/architecture", "tests/acceptance"}.issubset(command)
        )
        self.assertNotIn("tests/integration", command)
        self.assertFalse(any("*" in argument for argument in command))
        self.assertIn("--junitxml=/tmp/backend.xml", command)

    def test_total_timeout_bounds_source_and_static_subprocesses(self) -> None:
        observed_timeouts: list[float] = []

        class TimeoutRecordingRunner:
            def run(self, command: Sequence[str], **kwargs: object) -> ProcessResult:
                observed_timeouts.append(float(kwargs["timeout"]))
                parts = tuple(command)
                if parts[-2:] == ("rev-parse", "HEAD"):
                    return ProcessResult.success(parts, SHA + "\n")
                if parts[-2:] == ("rev-parse", "HEAD^{tree}"):
                    return ProcessResult.success(parts, "c" * 40 + "\n")
                if "status" in parts:
                    return ProcessResult.success(parts, "")
                if "--show-current" in parts:
                    return ProcessResult.success(parts, "feature\n")
                if "novel_forge.tools.documentation_reality" in parts:
                    return ProcessResult.success(parts, _documentation_report())
                return ProcessResult(
                    command=parts,
                    returncode=1,
                    stdout="",
                    stderr="static gate failed",
                    duration_seconds=0.1,
                    timed_out=False,
                )

        with TemporaryDirectory() as temporary:
            result = run_qualification(
                [
                    "--repo-root",
                    str(ROOT),
                    "--profile",
                    "local",
                    "--output",
                    str(Path(temporary) / "report.json"),
                    "--total-timeout-seconds",
                    "2",
                ],
                process_runner=TimeoutRecordingRunner(),
            )

        self.assertEqual(result, 1)
        self.assertGreaterEqual(len(observed_timeouts), 5)
        self.assertTrue(all(0 < value <= 2 for value in observed_timeouts))

    def test_timeout_terminates_the_qualification_owned_process_group(self) -> None:
        runner = SubprocessProcessRunner()
        result = runner.run(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    "print(child.pid, flush=True); time.sleep(30)"
                ),
            ],
            cwd=ROOT,
            environment=os.environ,
            timeout=0.3,
        )
        match = re.search(r"\d+", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        child_pid = int(match.group(0))
        child_alive = True
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            child_alive = False
        finally:
            if child_alive:
                os.kill(child_pid, signal.SIGKILL)

        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, 124)
        self.assertFalse(child_alive)


if __name__ == "__main__":
    unittest.main()
