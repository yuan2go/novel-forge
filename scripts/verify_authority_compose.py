#!/usr/bin/env python3
"""Destructive-to-its-own-project Authority Compose smoke and recovery drill."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKERS = (
    "chapter-authority-worker",
    "agent-authority-worker",
    "content-authority-worker",
    "source-authority-worker",
    "source-import-worker",
    "mkaos-authority-worker",
    "book-authority-worker",
    "outbox-worker",
    "maintenance-worker",
)
COMPOSE_BIN = tuple(
    shlex.split(os.environ.get("NOVEL_FORGE_DOCKER_COMPOSE_BIN") or "docker compose")
)


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: float = 300,
    capture: bool = True,
) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
    )
    return (completed.stdout or "").strip()


def _compose(project: str, *args: str) -> list[str]:
    return [*COMPOSE_BIN, "-p", project, "-f", "compose.yml", *args]


def _exec_probe(
    project: str, env: dict[str, str], *args: str
) -> dict[str, Any]:
    output = _run(
        _compose(
            project,
            "exec",
            "-T",
            "authority-api",
            "python",
            "-m",
            "novel_forge.tools.authority_compose_probe",
            *args,
        ),
        env=env,
        timeout=90,
    )
    return json.loads(output.splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", default="")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    commit_sha = _run(
        ["git", "rev-parse", "HEAD"], env=dict(os.environ), timeout=10
    )
    project = args.project_name or f"novel-forge-authority-smoke-{os.getpid()}"
    env = {
        **os.environ,
        "NOVEL_FORGE_COMMIT_SHA": commit_sha,
        "NOVEL_FORGE_APPLICATION_BUILD_ID": f"compose-smoke-{commit_sha[:12]}",
        "NOVEL_FORGE_ENVIRONMENT": "development",
        "NOVEL_FORGE_MODEL_PROVIDER": "mock",
    }
    started = time.monotonic()
    evidence: dict[str, Any] = {
        "type": "AuthorityComposeSmokeEvidence",
        "project_name": project,
        "commit_sha": commit_sha,
        "fixture": True,
        "real_provider_proven": False,
        "longform_proven": False,
        "production_verified": False,
        "steps": [],
    }
    up_args = ["up", "-d"]
    if not args.no_build:
        up_args.append("--build")
    up_args.extend(["--wait", "--wait-timeout", "300"])
    try:
        _run(_compose(project, "down", "--volumes"), env=env, timeout=90)
        _run(_compose(project, *up_args), env=env, timeout=600)
        evidence["steps"].append("clean_compose_ready")
        readiness = json.loads(
            _run(
                _compose(
                    project,
                    "exec",
                    "-T",
                    "authority-api",
                    "curl",
                    "-fsS",
                    "http://localhost:8000/readiness",
                ),
                env=env,
            )
        )
        evidence["readiness"] = readiness
        runtime_readiness = json.loads(
            _run(
                _compose(
                    project,
                    "exec",
                    "-T",
                    "authority-api",
                    "curl",
                    "-fsS",
                    "http://localhost:8000/runtime/readiness",
                ),
                env=env,
            )
        )
        if not runtime_readiness.get("runtime_ready"):
            raise RuntimeError(
                "worker fleet did not reach runtime readiness: "
                f"{runtime_readiness}"
            )
        evidence["runtime_readiness"] = runtime_readiness
        evidence["steps"].append("required_worker_fleet_ready")

        first = _exec_probe(project, env, "submit", "--suffix", "normal")
        first_result = _exec_probe(
            project,
            env,
            "verify",
            "--project-id",
            first["project_id"],
            "--operation-id",
            first["operation_id"],
        )
        evidence["normal_operation"] = first_result
        evidence["steps"].append("synthetic_operation_completed")

        _run(
            _compose(project, "stop", "-t", "45", "content-authority-worker"),
            env=env,
            timeout=90,
        )
        recovery = _exec_probe(project, env, "submit", "--suffix", "recovery")
        crashed_lease = _exec_probe(
            project,
            env,
            "prepare-expiring-lease",
            "--project-id",
            recovery["project_id"],
            "--operation-id",
            recovery["operation_id"],
        )
        time.sleep(1.5)
        _run(
            _compose(
                project,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                "content-authority-worker",
            ),
            env=env,
            timeout=180,
        )
        recovery_result = _exec_probe(
            project,
            env,
            "verify",
            "--project-id",
            recovery["project_id"],
            "--operation-id",
            recovery["operation_id"],
            "--min-fencing-token",
            "2",
        )
        evidence["recovered_operation"] = recovery_result
        evidence["expired_lease"] = crashed_lease
        evidence["stale_fence"] = _exec_probe(
            project,
            env,
            "assert-stale-fence",
            "--project-id",
            recovery["project_id"],
            "--operation-id",
            recovery["operation_id"],
            "--attempt-id",
            crashed_lease["attempt_id"],
            "--worker-id",
            crashed_lease["worker_id"],
            "--fencing-token",
            str(crashed_lease["fencing_token"]),
        )
        evidence["steps"].append("pending_operation_recovered_after_worker_restart")

        _run(
            _compose(project, "restart", "-t", "45", "content-authority-worker"),
            env=env,
            timeout=120,
        )
        _run(
            _compose(
                project,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                "content-authority-worker",
            ),
            env=env,
            timeout=180,
        )
        evidence["steps"].append("forced_worker_restart_ready")

        _run(
            _compose(project, "stop", "-t", "45", *WORKERS),
            env=env,
            timeout=180,
        )
        governance = _run(
            _compose(
                project,
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
                "SELECT json_build_object("
                "'idle_in_transaction',COUNT(*) FILTER (WHERE state='idle in transaction'),"
                "'active_transactions',COUNT(*) FILTER (WHERE xact_start IS NOT NULL),"
                "'worker_connections',COUNT(*) FILTER (WHERE application_name IN ("
                "'chapter-authority-worker','content-authority-worker',"
                "'source-authority-worker','source-import-worker',"
                "'mkaos-authority-worker',"
                "'book-authority-worker','outbox-worker','maintenance-worker'))) "
                "FROM pg_stat_activity WHERE pid<>pg_backend_pid();",
            ),
            env=env,
        )
        evidence["shutdown_database_governance"] = json.loads(governance)
        stopped = _run(
            _compose(
                project,
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
                "SELECT COUNT(*) FROM authority_worker_health_projection "
                "WHERE status='STOPPED' AND drain_status='DRAINED';",
            ),
            env=env,
        )
        evidence["drained_worker_count"] = int(stopped)
        if evidence["shutdown_database_governance"] != {
            "idle_in_transaction": 0,
            "active_transactions": 0,
            "worker_connections": 0,
        }:
            raise RuntimeError(
                "worker shutdown left transactions or connections: "
                f"{evidence['shutdown_database_governance']}"
            )
        if evidence["drained_worker_count"] < len(WORKERS):
            raise RuntimeError(
                f"expected {len(WORKERS)} drained workers, got "
                f"{evidence['drained_worker_count']}"
            )
        evidence["steps"].append("graceful_drain_released_connections")
        evidence["status"] = "PASS"
        evidence["evidence_level"] = "FAULT_INJECTION_PROVEN"
        evidence["duration_seconds"] = round(time.monotonic() - started, 3)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 0
    except subprocess.CalledProcessError as exc:
        evidence["status"] = "FAIL"
        evidence["failed_command"] = exc.cmd
        evidence["stdout"] = exc.stdout
        evidence["stderr"] = exc.stderr
        evidence["duration_seconds"] = round(time.monotonic() - started, 3)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 1
    finally:
        if not args.keep:
            subprocess.run(
                _compose(project, "down", "--volumes", "--timeout", "45"),
                cwd=ROOT,
                env=env,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )


if __name__ == "__main__":
    raise SystemExit(main())
