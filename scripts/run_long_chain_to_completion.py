from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume the real long-chain web novel until the target chapter count is reached.")
    parser.add_argument("--root", default=".local/longchain-workspace")
    parser.add_argument("--reference-analysis", required=True)
    parser.add_argument("--classical-modern-root", required=True)
    parser.add_argument("--chapters", type=int, default=400)
    parser.add_argument("--target-chars", type=int, default=5000)
    parser.add_argument("--export-dir", default="generated/longchain-webnovel")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-batches", type=int, default=0, help="0 means run until completion.")
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument("--codex-command", default=os.environ.get("NOVEL_FORGE_CLAUDE_CODE_COMMAND", "codex"))
    parser.add_argument("--codex-home", default=os.environ.get("NOVEL_FORGE_CLAUDE_CODE_CODEX_HOME", "~/.codex-claude"))
    parser.add_argument("--ignore-pressure-block", action="store_true")
    args = parser.parse_args()

    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    target = max(1, int(args.chapters))
    batch_size = max(1, int(args.batch_size))
    completed_batches = 0
    started_at = _now()
    last_error = ""
    status = "running"

    while True:
        progress = _load_progress(export_dir)
        generated = int(progress.get("generated_chapters", 0) or 0)
        if generated >= target:
            status = "completed"
            break
        if args.max_batches and completed_batches >= int(args.max_batches):
            status = "paused_after_max_batches"
            break

        next_batch = min(batch_size, target - generated)
        batch_started = time.monotonic()
        command = _runner_command(args, next_batch)
        print(
            json.dumps(
                {
                    "event": "batch_started",
                    "generated_chapters": generated,
                    "target_chapters": target,
                    "batch_size": next_batch,
                    "command": command,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_runner_env(args),
        )
        elapsed_seconds = round(time.monotonic() - batch_started, 2)
        if completed.returncode != 0:
            last_error = (completed.stderr or completed.stdout or "").strip()
            status = "failed"
            _write_status(
                export_dir,
                status=status,
                target=target,
                started_at=started_at,
                batch_size=batch_size,
                completed_batches=completed_batches,
                last_error=last_error,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            print(
                json.dumps(
                    {"event": "batch_failed", "returncode": completed.returncode, "elapsed_seconds": elapsed_seconds, "error": last_error[-2000:]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return completed.returncode

        completed_batches += 1
        progress = _load_progress(export_dir)
        report = _load_report(export_dir)
        generated_after = int(progress.get("generated_chapters", 0) or 0)
        _write_status(
            export_dir,
            status="running",
            target=target,
            started_at=started_at,
            batch_size=batch_size,
            completed_batches=completed_batches,
            last_error="",
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        print(
            json.dumps(
                {
                    "event": "batch_completed",
                    "generated_chapters": generated_after,
                    "target_chapters": target,
                    "completion": report.get("completion"),
                    "pressure_acceptance": report.get("pressure_acceptance", {}),
                    "elapsed_seconds": elapsed_seconds,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        pressure = report.get("pressure_acceptance", {}) if isinstance(report.get("pressure_acceptance", {}), dict) else {}
        if not args.ignore_pressure_block and (pressure.get("recommendation") == "block" or pressure.get("status") == "failed"):
            status = "blocked_by_pressure_gate"
            last_error = json.dumps(pressure, ensure_ascii=False)
            _write_status(
                export_dir,
                status=status,
                target=target,
                started_at=started_at,
                batch_size=batch_size,
                completed_batches=completed_batches,
                last_error=last_error,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            print(
                json.dumps(
                    {
                        "event": "pressure_gate_blocked",
                        "generated_chapters": generated_after,
                        "target_chapters": target,
                        "pressure_acceptance": pressure,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return 2

    _write_status(
        export_dir,
        status=status,
        target=target,
        started_at=started_at,
        batch_size=batch_size,
        completed_batches=completed_batches,
        last_error=last_error,
        stdout="",
        stderr="",
    )
    print(json.dumps({"event": "completion_driver_finished", "status": status, "target_chapters": target}, ensure_ascii=False), flush=True)
    return 0


def _runner_command(args: argparse.Namespace, batch_size: int) -> list[str]:
    return [
        sys.executable,
        "scripts/run_long_chain_webnovel.py",
        "--root",
        str(args.root),
        "--reference-analysis",
        str(args.reference_analysis),
        "--classical-modern-root",
        str(args.classical_modern_root),
        "--chapters",
        str(args.chapters),
        "--target-chars",
        str(args.target_chars),
        "--export-dir",
        str(args.export_dir),
        "--max-chapters-this-run",
        str(batch_size),
        "--codex-timeout-seconds",
        str(args.codex_timeout_seconds),
    ]


def _runner_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = "src" if not existing else f"src{os.pathsep}{existing}"
    env["NOVEL_FORGE_CLAUDE_CODE_COMMAND"] = str(args.codex_command)
    env["NOVEL_FORGE_CLAUDE_CODE_CODEX_HOME"] = str(args.codex_home)
    env["NOVEL_FORGE_CLAUDE_CODE_TIMEOUT_SECONDS"] = str(args.codex_timeout_seconds)
    return env


def _load_progress(export_dir: Path) -> dict[str, Any]:
    path = export_dir / "progress.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_report(export_dir: Path) -> dict[str, Any]:
    path = export_dir / "quality_report.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_status(
    export_dir: Path,
    *,
    status: str,
    target: int,
    started_at: str,
    batch_size: int,
    completed_batches: int,
    last_error: str,
    stdout: str,
    stderr: str,
) -> None:
    progress = _load_progress(export_dir)
    report = _load_report(export_dir)
    payload = {
        "status": status,
        "started_at": started_at,
        "updated_at": _now(),
        "target_chapters": target,
        "generated_chapters": int(progress.get("generated_chapters", 0) or 0),
        "batch_size": batch_size,
        "completed_batches": completed_batches,
        "completion": report.get("completion"),
        "pressure_acceptance": report.get("pressure_acceptance", {}),
        "quality_drift": report.get("quality_drift", {}),
        "cost_drift": report.get("cost_drift", {}),
        "foreshadowing_lifecycle": report.get("foreshadowing_lifecycle", {}),
        "feedback_backflow": report.get("feedback_backflow", {}),
        "last_error": last_error[-4000:],
        "last_stdout_tail": stdout[-4000:],
        "last_stderr_tail": stderr[-4000:],
    }
    (export_dir / "completion_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (export_dir / "completion_status.md").write_text(_status_markdown(payload), encoding="utf-8")


def _status_markdown(payload: dict[str, Any]) -> str:
    target = int(payload.get("target_chapters", 0) or 0)
    generated = int(payload.get("generated_chapters", 0) or 0)
    pressure = payload.get("pressure_acceptance", {}) if isinstance(payload.get("pressure_acceptance", {}), dict) else {}
    return "\n".join(
        [
            "# Long-chain Completion Status",
            "",
            f"- Status: `{payload.get('status')}`",
            f"- Generated chapters: {generated}/{target}",
            f"- Completion: {payload.get('completion')}",
            f"- Batch size: {payload.get('batch_size')}",
            f"- Completed batches: {payload.get('completed_batches')}",
            f"- Pressure acceptance: {pressure.get('status', 'unknown')} / {pressure.get('recommendation', 'unknown')}",
            f"- Updated at: {payload.get('updated_at')}",
            "",
            "## Drift Coverage",
            "",
            f"- Cost drift: {payload.get('cost_drift', {}).get('status', 'unknown') if isinstance(payload.get('cost_drift', {}), dict) else 'unknown'}",
            f"- Quality drift: {payload.get('quality_drift', {}).get('status', 'unknown') if isinstance(payload.get('quality_drift', {}), dict) else 'unknown'}",
            f"- Foreshadow lifecycle: {payload.get('foreshadowing_lifecycle', {}).get('overall_status', 'unknown') if isinstance(payload.get('foreshadowing_lifecycle', {}), dict) else 'unknown'}",
            f"- Feedback backflow: {payload.get('feedback_backflow', {}).get('status', 'unknown') if isinstance(payload.get('feedback_backflow', {}), dict) else 'unknown'}",
            "",
            "## Last Error",
            "",
            "```text",
            str(payload.get("last_error", "")),
            "```",
            "",
        ]
    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
