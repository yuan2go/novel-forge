"""Exact-revision orchestration for P0 backend engineering qualification."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Protocol, Sequence

from novel_forge.tools.backend_qualification_contract import (
    QualificationContractError,
    build_backend_pytest_command,
    expected_migration_head,
    load_qualification_manifest,
    resolved_dependency_snapshot,
    sanitize_evidence,
    validate_backend_test_evidence,
    validate_postgres_test_evidence,
)
from novel_forge.tools.backend_qualification_resources import (
    DockerComposeClient,
    OwnedComposeProject,
    QualificationRunIdentity,
    ResourceOwnershipError,
    validate_disposable_database_url,
)
from novel_forge.tools.release_run_evidence import (
    build_p0_backend_qualification_report,
    build_p0_backend_qualification_failure_report,
    write_atomic_evidence,
)
from novel_forge.modules.provider_control.composition import (
    CHAPTER_PROVIDER_ENVIRONMENT_KEYS,
    normalize_provider_id,
)
from novel_forge.storage.migrations import get_migration_status


ROOT = Path(__file__).resolve().parents[3]
PASS = 0
QUALIFICATION_FAIL = 1
PREFLIGHT_FAIL = 2


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool

    @classmethod
    def success(
        cls, command: Sequence[str], stdout: str = ""
    ) -> "ProcessResult":
        return cls(
            command=tuple(command),
            returncode=0,
            stdout=stdout,
            stderr="",
            duration_seconds=0.0,
            timed_out=False,
        )


class ProcessRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: float,
        log_path: Path | None = None,
    ) -> ProcessResult: ...


class SubprocessProcessRunner:
    MAX_CAPTURE_CHARACTERS = 2_000_000

    @classmethod
    def _read_bounded(cls, handle: object) -> str:
        handle.seek(0)
        value = handle.read(cls.MAX_CAPTURE_CHARACTERS + 1)
        if len(value) <= cls.MAX_CAPTURE_CHARACTERS:
            return value
        return value[: cls.MAX_CAPTURE_CHARACTERS] + "\n[OUTPUT_TRUNCATED]\n"

    @staticmethod
    def _terminate_group(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (AttributeError, ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (AttributeError, ProcessLookupError):
            process.kill()
        process.wait(timeout=5)

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout: float,
        log_path: Path | None = None,
    ) -> ProcessResult:
        started = time.monotonic()
        with tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", errors="replace"
        ) as stdout_handle, tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8", errors="replace"
        ) as stderr_handle:
            try:
                process = subprocess.Popen(
                    list(command),
                    cwd=cwd,
                    env=dict(environment),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    start_new_session=True,
                )
            except OSError as exc:
                result = ProcessResult(
                    command=tuple(command),
                    returncode=127,
                    stdout="",
                    stderr=str(exc),
                    duration_seconds=round(time.monotonic() - started, 6),
                    timed_out=False,
                )
            else:
                timed_out = False
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate_group(process)
                stdout = self._read_bounded(stdout_handle)
                stderr = self._read_bounded(stderr_handle)
                result = ProcessResult(
                    command=tuple(command),
                    returncode=124 if timed_out else int(process.returncode),
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=round(time.monotonic() - started, 6),
                    timed_out=timed_out,
                )
        if log_path is not None:
            safe_log = sanitize_evidence(
                {"stdout": result.stdout, "stderr": result.stderr}
            )
            write_atomic_evidence(log_path, safe_log)
        return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _gate_result(
    gate_id: str,
    status: str,
    *,
    duration_seconds: float = 0.0,
    evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "gate_id": gate_id,
        "status": status,
        "duration_seconds": round(duration_seconds, 6),
        "evidence": dict(evidence or {}),
    }


def _run_process(
    runner: ProcessRunner,
    command: Sequence[str],
    *,
    root: Path,
    environment: Mapping[str, str],
    timeout: float,
    log_path: Path | None = None,
) -> ProcessResult:
    return runner.run(
        command,
        cwd=root,
        environment=environment,
        timeout=timeout,
        log_path=log_path,
    )


def _source_identity(
    runner: ProcessRunner,
    *,
    root: Path,
    environment: Mapping[str, str],
    timeout_resolver: Callable[[float], float],
) -> tuple[dict[str, object], float]:
    started = time.monotonic()

    def git(*arguments: str) -> str:
        result = _run_process(
            runner,
            ("git", "-C", str(root), *arguments),
            root=root,
            environment=environment,
            timeout=timeout_resolver(30),
        )
        if result.returncode:
            raise ValueError(f"Git source preflight failed: {' '.join(arguments)}")
        return result.stdout.strip()

    commit_sha = git("rev-parse", "HEAD").lower()
    source_tree = git("rev-parse", "HEAD^{tree}").lower()
    dirty_output = git("status", "--porcelain", "--untracked-files=all")
    branch = git("branch", "--show-current")
    if len(commit_sha) != 40 or any(value not in "0123456789abcdef" for value in commit_sha):
        raise ValueError("Git source preflight did not return a full lowercase SHA")
    if len(source_tree) != 40 or any(value not in "0123456789abcdef" for value in source_tree):
        raise ValueError("Git source preflight did not return a full tree SHA")
    if dirty_output:
        raise ValueError("P0 backend qualification requires a clean worktree")
    workflow_sha = environment.get("GITHUB_SHA", "").strip().lower()
    if workflow_sha and workflow_sha != commit_sha:
        raise ValueError("checked-out revision differs from GITHUB_SHA")
    return (
        {
            "commit_sha": commit_sha,
            "source_tree": source_tree,
            "branch": branch,
            "dirty": False,
            "workflow_sha": workflow_sha,
        },
        time.monotonic() - started,
    )


def _manifest_evidence(root: Path, manifest: object) -> dict[str, object]:
    paths = sorted((root / "architecture" / "manifests").glob("*.yaml"))
    return {
        "schema_version": getattr(manifest, "schema_version"),
        "required_gates": list(getattr(manifest, "required_gates")),
        "expected_migration_head": expected_migration_head(root),
        "manifest_digests": {
            path.relative_to(root).as_posix(): _digest(path) for path in paths
        },
        "evidence_ceilings": dict(getattr(manifest, "evidence_ceilings")),
    }


def _fill_remaining_gates(
    gates: list[dict[str, object]], required_gates: Sequence[str]
) -> None:
    completed = {str(item["gate_id"]) for item in gates}
    for gate_id in required_gates:
        if gate_id not in completed:
            gates.append(
                _gate_result(
                    gate_id,
                    "NOT_RUN",
                    evidence={"reason": "DEPENDENCY_GATE_FAILED"},
                )
            )


def _migration_evidence(database_url: str, expected_head: str) -> dict[str, object]:
    status = get_migration_status(database_url)
    applied = status.get("applied")
    if not status.get("ok") or not isinstance(applied, list):
        raise ValueError("PostgreSQL migration status is incomplete")
    applied_ids = [
        str(item.get("migration_id") or "")
        for item in applied
        if isinstance(item, Mapping)
    ]
    if expected_head not in applied_ids:
        raise ValueError("manifest-derived migration head is not applied")
    return {
        "expected_head": expected_head,
        "observed_head": expected_head,
        "applied_count": len(applied_ids),
        "missing": list(status.get("missing") or []),
        "extra": list(status.get("extra") or []),
    }


def _read_json_object(path: Path, *, evidence_name: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{evidence_name} is missing or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{evidence_name} must be a JSON object")
    return payload


def _cleanup_owned_project(
    owned: OwnedComposeProject | None,
    *,
    phase: str,
) -> dict[str, object]:
    if owned is None:
        return {
            "phase": phase,
            "status": "PASS",
            "remaining_resource_count": 0,
            "resource_count": 0,
        }
    try:
        result = owned.cleanup()
    except (ResourceOwnershipError, RuntimeError, ValueError) as exc:
        return {
            "phase": phase,
            "status": "FAIL",
            "remaining_resource_count": -1,
            "error": str(sanitize_evidence(exc)),
            "recovery": (
                "inspect the recorded project and ownership receipt; do not run an "
                "unscoped docker compose down"
            ),
        }
    return {"phase": phase, **result}


def _aggregate_cleanup(phases: Sequence[Mapping[str, object]]) -> dict[str, object]:
    failed = [item for item in phases if item.get("status") != "PASS"]
    remaining = sum(
        int(item.get("remaining_resource_count") or 0)
        for item in phases
        if isinstance(item.get("remaining_resource_count"), int)
        and int(item.get("remaining_resource_count") or 0) > 0
    )
    return {
        "status": "FAIL" if failed else "PASS",
        "remaining_resource_count": remaining if not failed else -1,
        "phases": [dict(item) for item in phases],
    }


def _failure_report(
    *,
    output: Path,
    source: Mapping[str, object],
    manifest_evidence: Mapping[str, object],
    dependency_snapshot: Mapping[str, object],
    identity: QualificationRunIdentity,
    profile: str,
    gates: list[dict[str, object]],
    required_gates: Sequence[str],
    cleanup: Mapping[str, object],
    failure_reason: str,
) -> int:
    _fill_remaining_gates(gates, required_gates)
    report = build_p0_backend_qualification_failure_report(
        tested_sha=str(source["commit_sha"]),
        source_tree=str(source["source_tree"]),
        source_identity=source,
        manifest=manifest_evidence,
        dependency_snapshot=dependency_snapshot,
        gates=gates,
        cleanup=cleanup,
        run_identity={
            "run_id": identity.run_id,
            "compose_project": identity.compose_project,
            "database_name": identity.database_name,
            "artifact_root": identity.artifact_root.name,
            "profile": profile,
        },
        failure_reason=failure_reason,
    )
    write_atomic_evidence(output, report)
    return QUALIFICATION_FAIL


def run_qualification(
    argv: Sequence[str] | None = None,
    *,
    process_runner: ProcessRunner | None = None,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--profile", choices=("local", "ci"), default="")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--total-timeout-seconds", type=float, default=28_800)
    parser.add_argument("--list-gates", action="store_true")
    args = parser.parse_args(argv)
    manifest = load_qualification_manifest(args.repo_root.resolve())
    if args.list_gates:
        print(
            json.dumps(
                {
                    "schema_version": "novel-forge.backend-qualification-gates.v1",
                    "profile": "inspection",
                    "gates": list(manifest.required_gates),
                },
                sort_keys=True,
            )
        )
        return PASS
    if not args.profile or args.output is None:
        parser.print_usage()
        return PREFLIGHT_FAIL
    if args.total_timeout_seconds <= 0:
        print("qualification total timeout must be positive", file=sys.stderr)
        return PREFLIGHT_FAIL
    root = args.repo_root.resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        print("qualification output must be outside the tracked repository", file=sys.stderr)
        return PREFLIGHT_FAIL
    environment = dict(os.environ)
    provider_routes = {
        key: normalize_provider_id(str(environment.get(key) or ""))
        for key in CHAPTER_PROVIDER_ENVIRONMENT_KEYS
    }
    provider_routes["NOVEL_FORGE_MODEL_PROVIDER"] = normalize_provider_id(
        str(environment.get("NOVEL_FORGE_MODEL_PROVIDER") or "mock")
    )
    if any(
        provider_id not in {"", "scripted", "scripted_provider_v2"}
        for provider_id in provider_routes.values()
    ):
        print("P0 backend qualification forbids a real Provider route", file=sys.stderr)
        return PREFLIGHT_FAIL
    forbidden_credentials = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "NOVEL_FORGE_PROVIDER_API_KEY",
    )
    if any(environment.get(name, "").strip() for name in forbidden_credentials):
        print("P0 backend qualification refuses Provider credentials", file=sys.stderr)
        return PREFLIGHT_FAIL

    runner = process_runner or SubprocessProcessRunner()
    qualification_started = time.monotonic()

    def timeout(limit: float) -> float:
        remaining = args.total_timeout_seconds - (
            time.monotonic() - qualification_started
        )
        return max(0.001, min(limit, remaining))
    gates: list[dict[str, object]] = []
    try:
        source, source_duration = _source_identity(
            runner,
            root=root,
            environment=environment,
            timeout_resolver=timeout,
        )
    except ValueError as exc:
        print(str(sanitize_evidence(exc)), file=sys.stderr)
        return PREFLIGHT_FAIL
    gates.append(
        _gate_result(
            "source-preflight",
            "PASS",
            duration_seconds=source_duration,
            evidence=source,
        )
    )
    identity = QualificationRunIdentity.create(
        commit_sha=str(source["commit_sha"]), artifact_parent=output.parent
    )
    manifest_evidence = _manifest_evidence(root, manifest)
    dependency_snapshot = resolved_dependency_snapshot(
        args.python, repo_root=root
    )
    static = _run_process(
        runner,
        ("make", "p0-backend-static"),
        root=root,
        environment=environment,
        timeout=timeout(900),
        log_path=identity.artifact_root / "static-and-manifests.json",
    )
    if static.returncode:
        gates.append(
            _gate_result(
                "static-and-manifests",
                "FAIL",
                duration_seconds=static.duration_seconds,
                evidence={
                    "returncode": static.returncode,
                    "timed_out": static.timed_out,
                    "stderr": static.stderr,
                },
            )
        )
        _fill_remaining_gates(gates, manifest.required_gates)
        cleanup = {
            "status": "PASS",
            "remaining_resource_count": 0,
            "phases": [],
        }
        report = build_p0_backend_qualification_failure_report(
            tested_sha=str(source["commit_sha"]),
            source_tree=str(source["source_tree"]),
            source_identity=source,
            manifest=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            gates=gates,
            cleanup=cleanup,
            run_identity={
                "run_id": identity.run_id,
                "compose_project": identity.compose_project,
                "database_name": identity.database_name,
                "artifact_root": identity.artifact_root.name,
                "profile": args.profile,
            },
            failure_reason="static-and-manifests failed",
        )
        write_atomic_evidence(output, report)
        return QUALIFICATION_FAIL
    gates.append(
        _gate_result(
            "static-and-manifests",
            "PASS",
            duration_seconds=static.duration_seconds,
            evidence={"returncode": 0},
        )
    )

    cleanup_phases: list[dict[str, object]] = []
    identity.artifact_root.mkdir(parents=True, exist_ok=True)

    backend_junit = identity.artifact_root / "backend-pytest.xml"
    backend_collection = identity.artifact_root / "backend-pytest-collection.json"
    backend_contracts = tuple(
        item
        for item in manifest.pytest_collections
        if item.classification == "BACKEND_NON_POSTGRESQL"
    )
    backend_command = build_backend_pytest_command(
        contracts=backend_contracts,
        python=args.python,
        junit_xml=backend_junit,
        collection_report=backend_collection,
    )
    backend_process = _run_process(
        runner,
        backend_command,
        root=root,
        environment=environment,
        timeout=timeout(7_200),
        log_path=identity.artifact_root / "backend-pytest-process.json",
    )
    try:
        backend_evidence = validate_backend_test_evidence(
            contracts=backend_contracts,
            junit_xml=backend_junit,
            collection_report=backend_collection,
            repo_root=root,
        )
    except (QualificationContractError, ValueError) as exc:
        backend_evidence = {
            "error": str(sanitize_evidence(exc)),
            "returncode": backend_process.returncode,
            "timed_out": backend_process.timed_out,
        }
    if backend_process.returncode or backend_evidence.get("status") != "PASS":
        gates.append(
            _gate_result(
                "pytest-backend",
                "FAIL",
                duration_seconds=backend_process.duration_seconds,
                evidence=backend_evidence,
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="pytest-backend failed",
        )
    gates.append(
        _gate_result(
            "pytest-backend",
            "PASS",
            duration_seconds=backend_process.duration_seconds,
            evidence=backend_evidence,
        )
    )

    docker = DockerComposeClient(repo_root=root)
    postgres_environment = {
        **environment,
        "NOVEL_FORGE_QUALIFICATION_RUN_ID": identity.run_id,
        "NOVEL_FORGE_POSTGRES_TEST_DATABASE": identity.database_name,
    }
    postgres_files = (root / "compose.postgres-test.yml",)
    postgres_owned = OwnedComposeProject(
        identity=identity,
        repo_root=root,
        compose_files=postgres_files,
        environment=postgres_environment,
        client=docker,
    )
    postgres_started = time.monotonic()
    postgres_captured = False
    try:
        postgres_owned.assert_unclaimed()
        docker.run_compose(
            project_name=identity.compose_project,
            compose_files=postgres_files,
            environment=postgres_environment,
            arguments=(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "180",
                "authority-postgres-test",
            ),
            timeout=timeout(300),
        )
        ownership_receipt = postgres_owned.capture()
        postgres_captured = True
        postgres_port = docker.published_port(
            project_name=identity.compose_project,
            compose_files=postgres_files,
            environment=postgres_environment,
            service="authority-postgres-test",
            container_port=5432,
        )
        database_url = (
            "postgresql://novel_forge:novel_forge@127.0.0.1:"
            f"{postgres_port}/{identity.database_name}"
        )
        safe_database_identity = validate_disposable_database_url(
            database_url,
            expected_database=identity.database_name,
        )
    except (RuntimeError, ValueError, TimeoutError) as exc:
        cleanup = (
            _cleanup_owned_project(postgres_owned, phase="postgresql")
            if postgres_captured
            else {
                "phase": "postgresql",
                "status": "FAIL",
                "remaining_resource_count": -1,
                "error": "PostgreSQL start failed before ownership capture",
            }
        )
        cleanup_phases.append(cleanup)
        gates.append(
            _gate_result(
                "postgresql-start",
                "FAIL",
                duration_seconds=time.monotonic() - postgres_started,
                evidence={"error": str(sanitize_evidence(exc))},
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="postgresql-start failed",
        )
    gates.append(
        _gate_result(
            "postgresql-start",
            "PASS",
            duration_seconds=time.monotonic() - postgres_started,
            evidence={
                "database_identity": safe_database_identity,
                "ownership_resource_count": len(ownership_receipt["resources"]),
                "dynamic_port": True,
            },
        )
    )

    database_environment = {
        **environment,
        "PYTHONPATH": str(root / "src"),
        "NOVEL_FORGE_DATABASE_URL": database_url,
        "NOVEL_FORGE_QUALIFICATION_DATABASE_NAME": identity.database_name,
        "NOVEL_FORGE_STORAGE_AUTHORITY": "postgresql",
        "NOVEL_FORGE_MODEL_PROVIDER": "mock",
    }
    migration_started = time.monotonic()
    migration_process = _run_process(
        runner,
        (
            args.python,
            "-m",
            "novel_forge.cli.authority",
            "authority-migrate",
        ),
        root=root,
        environment=database_environment,
        timeout=timeout(900),
        log_path=identity.artifact_root / "migration-fresh-process.json",
    )
    try:
        fresh_migration = _migration_evidence(
            database_url, str(manifest_evidence["expected_migration_head"])
        )
    except (RuntimeError, ValueError) as exc:
        fresh_migration = {"error": str(sanitize_evidence(exc))}
    if migration_process.returncode or "error" in fresh_migration:
        cleanup_phases.append(
            _cleanup_owned_project(postgres_owned, phase="postgresql")
        )
        gates.append(
            _gate_result(
                "migration-fresh",
                "FAIL",
                duration_seconds=time.monotonic() - migration_started,
                evidence={
                    **fresh_migration,
                    "returncode": migration_process.returncode,
                    "timed_out": migration_process.timed_out,
                },
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="migration-fresh failed",
        )
    gates.append(
        _gate_result(
            "migration-fresh",
            "PASS",
            duration_seconds=time.monotonic() - migration_started,
            evidence=fresh_migration,
        )
    )

    postgres_junit = identity.artifact_root / "postgresql-pytest.xml"
    postgres_collection = (
        identity.artifact_root / "postgresql-pytest-collection.json"
    )
    postgres_process = _run_process(
        runner,
        (
            args.python,
            "scripts/run_authority_postgres_tests.py",
            "--repo-root",
            str(root),
            "--python",
            args.python,
            "--junit-xml",
            str(postgres_junit),
            "--collection-report",
            str(postgres_collection),
            "--timeout-seconds",
            str(int(timeout(14_400))),
        ),
        root=root,
        environment=database_environment,
        timeout=timeout(14_700),
        log_path=identity.artifact_root / "postgresql-pytest-process.json",
    )
    postgres_contract = next(
        item for item in manifest.pytest_collections if item.name == "integration"
    )
    try:
        postgres_test_evidence = validate_postgres_test_evidence(
            contract=postgres_contract,
            junit_xml=postgres_junit,
            collection_report=postgres_collection,
            repo_root=root,
            semantic_slices=manifest.semantic_slices,
        )
    except (QualificationContractError, ValueError) as exc:
        postgres_test_evidence = {
            "error": str(sanitize_evidence(exc)),
            "returncode": postgres_process.returncode,
            "timed_out": postgres_process.timed_out,
        }
    if (
        postgres_process.returncode
        or postgres_test_evidence.get("status") != "PASS"
    ):
        cleanup_phases.append(
            _cleanup_owned_project(postgres_owned, phase="postgresql")
        )
        gates.append(
            _gate_result(
                "pytest-postgresql-integration",
                "FAIL",
                duration_seconds=postgres_process.duration_seconds,
                evidence=postgres_test_evidence,
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="pytest-postgresql-integration failed",
        )
    gates.append(
        _gate_result(
            "pytest-postgresql-integration",
            "PASS",
            duration_seconds=postgres_process.duration_seconds,
            evidence=postgres_test_evidence,
        )
    )

    migration_head_started = time.monotonic()
    try:
        current_migration = _migration_evidence(
            database_url, str(manifest_evidence["expected_migration_head"])
        )
    except (RuntimeError, ValueError) as exc:
        current_migration = {"error": str(sanitize_evidence(exc))}
    if "error" in current_migration:
        cleanup_phases.append(
            _cleanup_owned_project(postgres_owned, phase="postgresql")
        )
        gates.append(
            _gate_result(
                "migration-head",
                "FAIL",
                duration_seconds=time.monotonic() - migration_head_started,
                evidence=current_migration,
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="migration-head failed",
        )
    gates.append(
        _gate_result(
            "migration-head",
            "PASS",
            duration_seconds=time.monotonic() - migration_head_started,
            evidence=current_migration,
        )
    )

    query_output = identity.artifact_root / "query-plan.json"
    query_process = _run_process(
        runner,
        (
            args.python,
            "scripts/qualify_authority_query_plans.py",
            "--output",
            str(query_output),
            "--commit-sha",
            str(source["commit_sha"]),
        ),
        root=root,
        environment=database_environment,
        timeout=timeout(3_600),
        log_path=identity.artifact_root / "query-plan-process.json",
    )
    try:
        query_evidence = _read_json_object(
            query_output, evidence_name="query-plan evidence"
        )
        if (
            query_evidence.get("status") != "PASS"
            or query_evidence.get("tested_sha") != source["commit_sha"]
            or query_evidence.get("migration_head")
            != manifest_evidence["expected_migration_head"]
        ):
            raise ValueError("query-plan evidence identity or migration head differs")
        query_gate_evidence: dict[str, object] = {
            "artifact": query_output.name,
            "digest": _digest(query_output),
            "plan_count": len(query_evidence.get("plans") or []),
            "row_counts": query_evidence.get("row_counts") or {},
        }
    except (TypeError, ValueError) as exc:
        query_gate_evidence = {"error": str(sanitize_evidence(exc))}
    if query_process.returncode or "error" in query_gate_evidence:
        cleanup_phases.append(
            _cleanup_owned_project(postgres_owned, phase="postgresql")
        )
        gates.append(
            _gate_result(
                "query-plan-release",
                "FAIL",
                duration_seconds=query_process.duration_seconds,
                evidence={
                    **query_gate_evidence,
                    "returncode": query_process.returncode,
                },
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="query-plan-release failed",
        )
    gates.append(
        _gate_result(
            "query-plan-release",
            "PASS",
            duration_seconds=query_process.duration_seconds,
            evidence=query_gate_evidence,
        )
    )

    postgres_cleanup = _cleanup_owned_project(postgres_owned, phase="postgresql")
    cleanup_phases.append(postgres_cleanup)
    if postgres_cleanup["status"] != "PASS":
        gates.append(
            _gate_result(
                "compose-runtime",
                "FAIL",
                evidence={"error": "PostgreSQL qualification cleanup failed"},
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="PostgreSQL qualification cleanup failed",
        )

    compose_project = identity.compose_project + "-runtime"
    compose_output = identity.artifact_root / "compose-runtime.json"
    compose_environment = {
        **environment,
        "NOVEL_FORGE_MODEL_PROVIDER": "mock",
        "NOVEL_FORGE_AUTHORITY_API_PORT": "0",
        "NOVEL_FORGE_AUTHORITY_API_HOST_IP": "127.0.0.1",
        "NOVEL_FORGE_QUALIFICATION_RUN_ID": identity.run_id,
    }
    compose_process = _run_process(
        runner,
        (
            args.python,
            "scripts/verify_authority_compose.py",
            "--project-name",
            compose_project,
            "--run-id",
            identity.run_id,
            "--artifact-root",
            str(identity.artifact_root),
            "--output",
            str(compose_output),
        ),
        root=root,
        environment=compose_environment,
        timeout=timeout(5_400),
        log_path=identity.artifact_root / "compose-runtime-process.json",
    )
    try:
        compose_evidence = _read_json_object(
            compose_output, evidence_name="Compose runtime evidence"
        )
        required_steps = {
            "clean_compose_ready",
            "synthetic_operation_completed",
            "pending_operation_recovered_after_worker_restart",
            "post_restart_operation_completed",
            "graceful_drain_released_connections",
        }
        if (
            compose_evidence.get("status") != "PASS"
            or compose_evidence.get("commit_sha") != source["commit_sha"]
            or compose_evidence.get("run_id") != identity.run_id
            or not required_steps.issubset(set(compose_evidence.get("steps") or []))
        ):
            raise ValueError("Compose runtime proof is incomplete or identity-mismatched")
        compose_cleanup = compose_evidence.get("cleanup")
        if (
            not isinstance(compose_cleanup, Mapping)
            or compose_cleanup.get("status") != "PASS"
            or compose_cleanup.get("remaining_resource_count") != 0
        ):
            raise ValueError("Compose runtime ownership-checked cleanup did not pass")
        cleanup_phases.append({"phase": "compose-runtime", **dict(compose_cleanup)})
        compose_gate_evidence: dict[str, object] = {
            "artifact": compose_output.name,
            "digest": _digest(compose_output),
            "pre_restart_operation_id": (
                compose_evidence.get("normal_operation") or {}
            ).get("operation_id"),
            "recovered_operation_id": (
                compose_evidence.get("recovered_operation") or {}
            ).get("operation_id"),
            "post_restart_operation_id": (
                compose_evidence.get("post_restart_operation") or {}
            ).get("operation_id"),
            "authoritative_side_effect": True,
        }
    except (TypeError, ValueError) as exc:
        compose_gate_evidence = {"error": str(sanitize_evidence(exc))}
        if not any(item.get("phase") == "compose-runtime" for item in cleanup_phases):
            cleanup_phases.append(
                {
                    "phase": "compose-runtime",
                    "status": "FAIL",
                    "remaining_resource_count": -1,
                    "error": "Compose proof did not emit successful cleanup evidence",
                }
            )
    if compose_process.returncode or "error" in compose_gate_evidence:
        gates.append(
            _gate_result(
                "compose-runtime",
                "FAIL",
                duration_seconds=compose_process.duration_seconds,
                evidence={
                    **compose_gate_evidence,
                    "returncode": compose_process.returncode,
                    "timed_out": compose_process.timed_out,
                },
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=_aggregate_cleanup(cleanup_phases),
            failure_reason="compose-runtime failed",
        )
    gates.append(
        _gate_result(
            "compose-runtime",
            "PASS",
            duration_seconds=compose_process.duration_seconds,
            evidence=compose_gate_evidence,
        )
    )

    cleanup = _aggregate_cleanup(cleanup_phases)
    finalization_started = time.monotonic()
    if cleanup["status"] != "PASS":
        gates.append(
            _gate_result(
                "evidence-finalization",
                "FAIL",
                evidence={"error": "qualification cleanup did not pass"},
            )
        )
        return _failure_report(
            output=output,
            source=source,
            manifest_evidence=manifest_evidence,
            dependency_snapshot=dependency_snapshot,
            identity=identity,
            profile=args.profile,
            gates=gates,
            required_gates=manifest.required_gates,
            cleanup=cleanup,
            failure_reason="evidence-finalization failed",
        )
    gates.append(
        _gate_result(
            "evidence-finalization",
            "PASS",
            duration_seconds=time.monotonic() - finalization_started,
            evidence={"artifact": output.name, "atomic_write": True},
        )
    )
    report = build_p0_backend_qualification_report(
        tested_sha=str(source["commit_sha"]),
        source_tree=str(source["source_tree"]),
        source_identity=source,
        manifest=manifest_evidence,
        dependency_snapshot=dependency_snapshot,
        gates=gates,
        cleanup=cleanup,
        run_identity={
            "run_id": identity.run_id,
            "compose_project": identity.compose_project,
            "compose_runtime_project": compose_project,
            "database_name": identity.database_name,
            "artifact_root": identity.artifact_root.name,
            "profile": args.profile,
        },
    )
    write_atomic_evidence(output, report)
    print(
        json.dumps(
            {
                "status": "PASS",
                "tested_sha": source["commit_sha"],
                "report": str(output),
                "dependency_digest": dependency_snapshot["digest"],
                "migration_head": manifest_evidence["expected_migration_head"],
            },
            sort_keys=True,
        )
    )
    return PASS


def main() -> int:
    return run_qualification()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProcessResult",
    "ProcessRunner",
    "SubprocessProcessRunner",
    "main",
    "run_qualification",
]
