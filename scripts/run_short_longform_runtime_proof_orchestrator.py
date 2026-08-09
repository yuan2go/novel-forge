#!/usr/bin/env python3
"""Run Planning and Book phases in two fresh Python processes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROOF_SCRIPT = ROOT / "scripts" / "run_short_longform_runtime_proof.py"


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run_phase(
    command: list[str], log_path: Path, *, accepted_codes: tuple[int, ...] = (0,)
) -> int:
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if completed.returncode not in accepted_codes:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return completed.returncode


def _base_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(PROOF_SCRIPT),
        "--database-url",
        args.database_url,
        "--codex-executable",
        args.codex_executable,
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--minio-endpoint",
        args.minio_endpoint,
        "--minio-access-key",
        args.minio_access_key,
        "--minio-secret-key",
        args.minio_secret_key,
    ]
    if args.minio_secure:
        command.append("--minio-secure")
    if args.allow_dirty:
        command.append("--allow-dirty")
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--runtime-root", default="")
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--minio-endpoint", default="127.0.0.1:59039")
    parser.add_argument("--minio-access-key", default="novel_forge")
    parser.add_argument("--minio-secret-key", default="novel_forge_secret")
    parser.add_argument("--minio-secure", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    commit_sha = _git("rev-parse", "HEAD")
    root = (
        Path(args.runtime_root).expanduser().resolve()
        if args.runtime_root
        else ROOT / ".local" / "runtime-proof" / f"short-longform-{commit_sha}"
    )
    root.mkdir(parents=True, exist_ok=False)
    planning_output = root / "planning-checkpoint.json"
    final_output = root / f"short-longform-{commit_sha}.json"
    base = _base_command(args)
    planning_command = [
        *base,
        "--runtime-root",
        str(root / "planning-process"),
        "--output",
        str(planning_output),
        "--stop-after-planning",
    ]
    book_command = [
        *base,
        "--runtime-root",
        str(root / "book-process"),
        "--output",
        str(final_output),
        "--resume-planning-output",
        str(planning_output),
    ]
    _run_phase(planning_command, root / "planning-process.log")
    _run_phase(book_command, root / "book-process.log", accepted_codes=(0, 2))
    report: dict[str, Any] = json.loads(final_output.read_text(encoding="utf-8"))
    summary = {
        "schema_version": "novel-forge.short-longform-proof-run.v1",
        "commit_sha": commit_sha,
        "planning_checkpoint": str(planning_output),
        "final_report": str(final_output),
        "proof_flags": dict(report.get("proof_flags") or {}),
        "usage_cost_summary": dict(
            (report.get("evidence_snapshot") or {}).get("usage_cost_summary") or {}
        ),
    }
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if all(summary["proof_flags"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
