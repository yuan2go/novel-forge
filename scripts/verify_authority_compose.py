#!/usr/bin/env python3
"""Run-scoped Authority Compose execution, recovery, restart, and cleanup proof."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import time
from typing import Any, Callable, Mapping

from novel_forge.tools.backend_qualification_contract import (
    QualificationContractError,
    sanitize_evidence,
    validate_compose_runtime_evidence,
)
from novel_forge.tools.backend_qualification_resources import (
    DockerCommandError,
    DockerComposeClient,
    OwnedComposeProject,
    QualificationRunIdentity,
    ResourceOwnershipError,
)
from novel_forge.tools.release_run_evidence import write_atomic_evidence


ROOT = Path(__file__).resolve().parents[1]
WORKERS = (
    "chapter-authority-worker",
    "agent-authority-worker",
    "content-authority-worker",
    "source-authority-worker",
    "source-import-worker",
    "mkaos-authority-worker",
    "book-authority-worker",
    "book-followup-authority-worker",
    "outbox-worker",
    "maintenance-worker",
)
TARGET_WORKER_SERVICE = "content-authority-worker"
TARGET_WORKER_ID = "content-authority-worker-1"
TARGET_WORKER_KIND = "content"


def _failure_evidence(exc: BaseException) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    if isinstance(exc, DockerCommandError):
        payload["command"] = {
            "returncode": exc.returncode,
            "stdout": exc.stdout,
            "stderr": exc.stderr,
        }
    sanitized = sanitize_evidence(payload)
    if not isinstance(sanitized, dict):
        raise RuntimeError("failure evidence sanitizer returned invalid output")
    return sanitized


def _json_object(value: str, *, evidence_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{evidence_name} did not emit JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{evidence_name} did not emit a JSON object")
    return payload


def _poll(
    label: str,
    read: Callable[[], dict[str, Any]],
    accepted: Callable[[Mapping[str, Any]], bool],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = read()
        if accepted(last):
            return last
        time.sleep(0.25)
    raise RuntimeError(f"{label} did not converge: {last}")


def _compose(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
    arguments: tuple[str, ...],
    timeout: float,
) -> str:
    return client.run_compose(
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        arguments=arguments,
        timeout=timeout,
    )


def _exec_probe(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
    arguments: tuple[str, ...],
) -> dict[str, Any]:
    output = _compose(
        client,
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        arguments=(
            "exec",
            "-T",
            "authority-api",
            "python",
            "-m",
            "novel_forge.tools.authority_compose_probe",
            *arguments,
        ),
        timeout=150,
    )
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Authority Compose probe emitted no result")
    return _json_object(lines[-1], evidence_name="Authority Compose probe")


def _readiness(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
    route: str,
) -> dict[str, Any]:
    output = _compose(
        client,
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        arguments=(
            "exec",
            "-T",
            "authority-api",
            "curl",
            "-fsS",
            f"http://localhost:8000{route}",
        ),
        timeout=90,
    )
    return _json_object(output, evidence_name=f"Authority readiness {route}")


def _postgres_json(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
    sql: str,
) -> dict[str, Any]:
    output = _compose(
        client,
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        arguments=(
            "exec",
            "-T",
            "postgresql",
            "psql",
            "-U",
            "novel_forge",
            "-d",
            "novel_forge",
            "-At",
            "-c",
            sql,
        ),
        timeout=90,
    )
    return _json_object(output, evidence_name="PostgreSQL projection query")


def _worker_projection(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    return _postgres_json(
        client,
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        sql=(
            "SELECT json_build_object("
            "'worker_id',worker_id,'worker_kind',worker_kind,'status',status,"
            "'drain_status',drain_status,'last_heartbeat_at',last_heartbeat_at,"
            "'completed_operation_count',completed_operation_count,"
            "'updated_at',updated_at) "
            "FROM authority_worker_health_projection "
            f"WHERE worker_id='{TARGET_WORKER_ID}' "
            f"AND worker_kind='{TARGET_WORKER_KIND}';"
        ),
    )


def _wait_worker_projection(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
    stopped: bool,
    changed_from: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected_statuses = {"STOPPED"} if stopped else {"READY", "BUSY"}
    expected_drain = "DRAINED" if stopped else "ACCEPTING"
    return _poll(
        "content worker health projection",
        lambda: _worker_projection(
            client,
            project_name=project_name,
            compose_files=compose_files,
            environment=environment,
        ),
        lambda item: (
            item.get("status") in expected_statuses
            and item.get("drain_status") == expected_drain
            and bool(item.get("updated_at"))
            and bool(item.get("last_heartbeat_at"))
            and (
                changed_from is None
                or (
                    item.get("updated_at") != changed_from.get("updated_at")
                    and item.get("last_heartbeat_at")
                    != changed_from.get("last_heartbeat_at")
                )
            )
        ),
        timeout_seconds=120,
    )


def _verify_operation(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
    submitted: Mapping[str, Any],
    minimum_fencing_token: int = 1,
) -> dict[str, Any]:
    return _exec_probe(
        client,
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        arguments=(
            "verify",
            "--project-id",
            str(submitted["project_id"]),
            "--operation-id",
            str(submitted["operation_id"]),
            "--min-fencing-token",
            str(minimum_fencing_token),
            "--timeout-seconds",
            "120",
        ),
    )


def _database_governance(
    client: DockerComposeClient,
    *,
    project_name: str,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    worker_names = ",".join(f"'{service}'" for service in WORKERS)
    return _postgres_json(
        client,
        project_name=project_name,
        compose_files=compose_files,
        environment=environment,
        sql=(
            "SELECT json_build_object("
            "'idle_in_transaction',COUNT(*) FILTER (WHERE state='idle in transaction'),"
            "'active_transactions',COUNT(*) FILTER (WHERE xact_start IS NOT NULL),"
            "'worker_connections',COUNT(*) FILTER "
            f"(WHERE application_name IN ({worker_names})),"
            "'drained_worker_count',(SELECT COUNT(*) "
            "FROM authority_worker_health_projection "
            "WHERE status='STOPPED' AND drain_status='DRAINED')) "
            "FROM pg_stat_activity WHERE pid<>pg_backend_pid();"
        ),
    )


def _cleanup(
    owned: OwnedComposeProject,
    *,
    captured: bool,
) -> dict[str, Any]:
    try:
        if not captured:
            discovered = owned.client.discover(owned.identity.compose_project)
            if not discovered.resources:
                return {
                    "status": "PASS",
                    "remaining_resource_count": 0,
                    "resource_count": 0,
                    "ownership_capture": "NO_RESOURCES_CREATED",
                }
            owned.capture()
        return dict(owned.cleanup())
    except (DockerCommandError, ResourceOwnershipError, RuntimeError, ValueError) as exc:
        return {
            "status": "FAIL",
            "remaining_resource_count": -1,
            "error": str(sanitize_evidence(exc)),
            "recovery": (
                "inspect the run-scoped ownership receipt and labels; do not run "
                "an unscoped Docker cleanup"
            ),
        }


def _write_failure_logs(
    client: DockerComposeClient,
    *,
    identity: QualificationRunIdentity,
    compose_files: tuple[Path, ...],
    environment: Mapping[str, str],
) -> None:
    try:
        logs = _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("logs", "--no-color", "--tail", "300"),
            timeout=120,
        )
    except (DockerCommandError, RuntimeError, ValueError) as exc:
        logs = f"Compose logs unavailable: {type(exc).__name__}: {exc}"
    write_atomic_evidence(
        identity.artifact_root / "compose-runtime-logs.json",
        sanitize_evidence({"logs": logs}),
    )


def _git_commit_sha() -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode:
        raise RuntimeError("Compose proof cannot resolve the checked-out Git SHA")
    commit_sha = completed.stdout.strip().lower()
    status = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status.returncode or status.stdout.strip():
        raise RuntimeError("Compose proof requires a clean exact-revision worktree")
    workflow_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if workflow_sha and workflow_sha != commit_sha:
        raise RuntimeError("Compose proof checkout differs from GITHUB_SHA")
    return commit_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args(argv)

    artifact_root = args.artifact_root.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(artifact_root):
        parser.error("Compose evidence output must be under the run artifact root")
    identity = QualificationRunIdentity.bind(
        commit_sha=_git_commit_sha(),
        run_id=args.run_id,
        compose_project=args.project_name,
        artifact_root=artifact_root,
    )
    compose_command = tuple(
        shlex.split(
            os.environ.get("NOVEL_FORGE_DOCKER_COMPOSE_BIN") or "docker compose"
        )
    )
    client = DockerComposeClient(repo_root=ROOT, compose_command=compose_command)
    compose_files = (ROOT / "compose.yml", ROOT / "compose.qualification.yml")
    environment = {
        **os.environ,
        "NOVEL_FORGE_COMMIT_SHA": identity.commit_sha,
        "NOVEL_FORGE_APPLICATION_BUILD_ID": (
            f"p0-compose-{identity.commit_sha[:12]}"
        ),
        "NOVEL_FORGE_ENVIRONMENT": "development",
        "NOVEL_FORGE_MODEL_PROVIDER": "mock",
        "NOVEL_FORGE_AUTHORITY_API_HOST_IP": "127.0.0.1",
        "NOVEL_FORGE_AUTHORITY_API_PORT": "0",
        "NOVEL_FORGE_QUALIFICATION_RUN_ID": identity.run_id,
    }
    owned = OwnedComposeProject(
        identity=identity,
        repo_root=ROOT,
        compose_files=compose_files,
        environment=environment,
        client=client,
    )
    started = time.monotonic()
    captured = False
    proof_succeeded = False
    evidence: dict[str, Any] = {
        "type": "AuthorityComposeRuntimeEvidence",
        "schema_version": "novel-forge.compose-runtime-evidence.v1",
        "status": "RUNNING",
        "project_name": identity.compose_project,
        "run_id": identity.run_id,
        "commit_sha": identity.commit_sha,
        "fixture": True,
        "real_provider_proven": False,
        "longform_proven": False,
        "production_verified": False,
        "steps": [],
    }
    try:
        owned.assert_unclaimed()
        up_arguments = ["up", "-d"]
        if not args.no_build:
            up_arguments.append("--build")
        up_arguments.extend(("--wait", "--wait-timeout", "300"))
        _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=tuple(up_arguments),
            timeout=900,
        )
        evidence["ownership"] = owned.capture()
        captured = True
        evidence["steps"].append("clean_compose_ready")

        evidence["readiness"] = _readiness(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            route="/readiness",
        )
        runtime_readiness = _readiness(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            route="/runtime/readiness",
        )
        if runtime_readiness.get("runtime_ready") is not True:
            raise RuntimeError("required Authority worker fleet is not runtime-ready")
        evidence["runtime_readiness"] = runtime_readiness
        evidence["steps"].append("required_worker_fleet_ready")

        before_stop = _wait_worker_projection(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            stopped=False,
        )
        normal = _exec_probe(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("submit", "--suffix", f"normal-{identity.run_id}"),
        )
        evidence["normal_operation"] = _verify_operation(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            submitted=normal,
        )
        evidence["steps"].append("synthetic_operation_completed")

        _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("stop", "-t", "45", TARGET_WORKER_SERVICE),
            timeout=120,
        )
        stopped = _wait_worker_projection(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            stopped=True,
            changed_from=before_stop,
        )
        recovery = _exec_probe(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("submit", "--suffix", f"recovery-{identity.run_id}"),
        )
        expired_lease = _exec_probe(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=(
                "prepare-expiring-lease",
                "--project-id",
                str(recovery["project_id"]),
                "--operation-id",
                str(recovery["operation_id"]),
            ),
        )
        evidence["expired_lease"] = expired_lease
        time.sleep(1.5)
        _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                TARGET_WORKER_SERVICE,
            ),
            timeout=240,
        )
        evidence["recovered_operation"] = _verify_operation(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            submitted=recovery,
            minimum_fencing_token=2,
        )
        after_recovery_start = _wait_worker_projection(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            stopped=False,
            changed_from=stopped,
        )
        evidence["stale_fence"] = _exec_probe(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=(
                "assert-stale-fence",
                "--project-id",
                str(recovery["project_id"]),
                "--operation-id",
                str(recovery["operation_id"]),
                "--attempt-id",
                str(expired_lease["attempt_id"]),
                "--worker-id",
                str(expired_lease["worker_id"]),
                "--fencing-token",
                str(expired_lease["fencing_token"]),
            ),
        )
        evidence["steps"].append(
            "pending_operation_recovered_after_worker_restart"
        )

        before_forced_restart = _wait_worker_projection(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            stopped=False,
            changed_from=after_recovery_start,
        )
        _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("restart", "-t", "45", TARGET_WORKER_SERVICE),
            timeout=180,
        )
        _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                TARGET_WORKER_SERVICE,
            ),
            timeout=240,
        )
        after_forced_restart = _wait_worker_projection(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            stopped=False,
            changed_from=before_forced_restart,
        )
        evidence["worker_restart"] = {
            "worker_id": TARGET_WORKER_ID,
            "worker_kind": TARGET_WORKER_KIND,
            "before_stop": before_stop,
            "stopped": stopped,
            "after_recovery_start": after_recovery_start,
            "before_forced_restart": before_forced_restart,
            "after_forced_restart": after_forced_restart,
            "projection_changed": True,
        }
        evidence["steps"].append("forced_worker_restart_ready")

        post_restart = _exec_probe(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("submit", "--suffix", f"post-restart-{identity.run_id}"),
        )
        evidence["post_restart_operation"] = _verify_operation(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            submitted=post_restart,
        )
        evidence["steps"].append("post_restart_operation_completed")

        _compose(
            client,
            project_name=identity.compose_project,
            compose_files=compose_files,
            environment=environment,
            arguments=("stop", "-t", "45", *WORKERS),
            timeout=300,
        )
        governance = _poll(
            "Authority worker graceful drain",
            lambda: _database_governance(
                client,
                project_name=identity.compose_project,
                compose_files=compose_files,
                environment=environment,
            ),
            lambda item: (
                item.get("idle_in_transaction") == 0
                and item.get("active_transactions") == 0
                and item.get("worker_connections") == 0
                and int(item.get("drained_worker_count") or 0) >= len(WORKERS)
            ),
            timeout_seconds=120,
        )
        evidence["shutdown_database_governance"] = {
            key: governance[key]
            for key in (
                "idle_in_transaction",
                "active_transactions",
                "worker_connections",
            )
        }
        evidence["drained_worker_count"] = int(
            governance["drained_worker_count"]
        )
        evidence["steps"].append("graceful_drain_released_connections")
        proof_succeeded = True
    except (
        DockerCommandError,
        QualificationContractError,
        ResourceOwnershipError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        evidence["failure"] = _failure_evidence(exc)
        _write_failure_logs(
            client,
            identity=identity,
            compose_files=compose_files,
            environment=environment,
        )
    finally:
        evidence["cleanup"] = _cleanup(owned, captured=captured)
        evidence["duration_seconds"] = round(time.monotonic() - started, 6)

    if proof_succeeded and evidence["cleanup"].get("status") == "PASS":
        evidence["status"] = "PASS"
        try:
            validate_compose_runtime_evidence(
                evidence,
                expected_sha=identity.commit_sha,
                expected_run_id=identity.run_id,
                expected_project=identity.compose_project,
            )
        except QualificationContractError as exc:
            evidence["status"] = "FAIL"
            evidence["failure"] = {
                "type": type(exc).__name__,
                "message": str(sanitize_evidence(exc)),
            }
    else:
        evidence["status"] = "FAIL"

    sanitized = sanitize_evidence(evidence)
    if not isinstance(sanitized, dict):
        raise RuntimeError("Compose evidence sanitizer returned invalid output")
    write_atomic_evidence(output, sanitized)
    print(json.dumps(sanitized, ensure_ascii=False, sort_keys=True))
    return 0 if sanitized.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
