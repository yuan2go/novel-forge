#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novel_forge.api.product import indexed_task_center, project_health_report, retry_task, task_recovery_report
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.local import LocalStorage
from novel_forge.workflows import pipeline
from novel_forge.workflows.status import write_task_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local production failure drills for Novel Forge.")
    parser.add_argument("--root", default="", help="workspace root to drill; defaults to an isolated temporary workspace")
    parser.add_argument("--api-base", default=os.environ.get("NOVEL_FORGE_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--skip-api", action="store_true", help="skip live API health probes")
    parser.add_argument("--require-api", action="store_true", help="fail if live API probes cannot reach the server")
    args = parser.parse_args()

    if args.root:
        root = Path(args.root).resolve()
        result = run_storage_drill(root)
    else:
        with tempfile.TemporaryDirectory(prefix="novel-forge-failure-drill-") as tmp:
            result = run_storage_drill(Path(tmp).resolve())

    if not args.skip_api:
        result["api_probe"] = run_api_probe(args.api_base)
        if args.require_api and not result["api_probe"]["ok"]:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_storage_drill(root: Path) -> dict[str, Any]:
    storage = pipeline.ensure_project(root)
    source_file = root / "failure_drill_source.txt"
    source_file.write_text("第一章 演练源文件\n\n钟声线索推动主角做出选择。", encoding="utf-8")
    raw = pipeline.ingest(
        root,
        str(source_file),
        title="Failure drill source",
        rights_authorization="test_fixture",
        copyright_note="self-authored failure drill fixture",
        allow_downstream_generation=True,
    )
    failed_status = write_task_status(
        storage,
        "failure-drill-run",
        "clean",
        "failed",
        input_paths=[raw],
        error_message="InjectedFailure: local failure drill",
    )
    settings = IndustrialSettings(root=root)
    failed_center = indexed_task_center(settings, storage, status="failed", limit=10)
    health = project_health_report(settings)
    recovery = task_recovery_report(storage, status_path=str(failed_status))
    retry = retry_task(root, status_path=str(failed_status))
    retry_statuses = [storage.read_json(root / path) for path in retry["status_paths"]]
    completed_retry = [item for item in retry_statuses if item.get("content", {}).get("status") == "completed"]
    assertions = {
        "failed_task_visible": bool(failed_center["tasks"]),
        "recent_failures_are_failed_only": all(task.get("status") == "failed" for task in health["recent_failures"]),
        "recovery_identifies_failed_step": recovery["failed_step"] == "clean",
        "retry_completed": bool(completed_retry),
    }
    return {
        "ok": all(assertions.values()),
        "root": str(root),
        "drill": "task_failure_recovery",
        "assertions": assertions,
        "failed_status_path": _relative(root, failed_status),
        "retry_run_id": retry["retry_run_id"],
        "retry_output_path": retry["output_path"],
        "health_summary": health["summary"],
        "recovery": {
            "failed_step": recovery["failed_step"],
            "failed_status_path": recovery["failed_status_path"],
            "retry_request": recovery["retry_request"],
        },
    }


def run_api_probe(api_base: str) -> dict[str, Any]:
    endpoints = ["/health", "/product/health", "/product/tasks/recovery"]
    checks = []
    for endpoint in endpoints:
        url = api_base.rstrip("/") + endpoint
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                checks.append({"endpoint": endpoint, "ok": 200 <= response.status < 500, "status": response.status})
        except urllib.error.URLError as exc:
            checks.append({"endpoint": endpoint, "ok": False, "error": str(exc)})
    return {
        "ok": all(check["ok"] for check in checks),
        "api_base": api_base,
        "checks": checks,
    }


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
