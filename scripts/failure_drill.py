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

from novel_forge.api.product import indexed_task_center, postgres_strict_local_prod_check, project_health_report, retry_task, task_recovery_report
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.local import LocalStorage
from novel_forge.workers.runtime import list_dead_letters, write_dead_letter
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
    dependency_drills = run_dependency_drills(root)
    return {
        "ok": all(assertions.values()) and dependency_drills["ok"],
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
        "dependency_drills": dependency_drills,
    }


def run_dependency_drills(root: Path) -> dict[str, Any]:
    worker_path = write_dead_letter(
        root=root,
        task_name="novel_forge.worker_lost_simulation",
        task_id="worker-lost-drill",
        args=(str(root),),
        kwargs={},
        exc=RuntimeError("simulated worker lost"),
        traceback="simulated worker kill / lost acknowledgement path",
        sync_postgres=False,
    )
    dead_letters = list_dead_letters(root, limit=10)
    postgres_strict = postgres_strict_local_prod_check(
        IndustrialSettings(root=root, database_url="", postgres_write_strict=True, postgres_write_through=True),
        raise_on_failure=False,
    )
    redis_short_outage = _redis_outage_drill(root)
    qdrant_mismatch = _qdrant_mismatch_drill(root)
    minio_unavailable = _minio_unavailable_drill(root)
    assertions = {
        "worker_lost_dead_letter": any(row["task_id"] == "worker-lost-drill" for row in dead_letters),
        "postgres_strict_blocks_without_database_url": postgres_strict["ready"] is False,
        "redis_short_outage_degrades_without_crashing": redis_short_outage["ok"],
        "qdrant_dimension_mismatch_detected": qdrant_mismatch["detected"],
        "qdrant_dimension_mismatch_recreate_available": qdrant_mismatch["recreate_available"],
        "minio_unavailable_detected": minio_unavailable["ok"],
    }
    return {
        "ok": all(assertions.values()),
        "assertions": assertions,
        "worker_lost": {"dead_letter_path": _relative(root, worker_path), "dead_letter_count": len(dead_letters)},
        "postgres_strict": {"ready": postgres_strict["ready"], "errors": postgres_strict["errors"]},
        "redis_short_outage": redis_short_outage,
        "qdrant_dimension_mismatch": qdrant_mismatch,
        "minio_unavailable": minio_unavailable,
    }


def _redis_outage_drill(root: Path) -> dict[str, Any]:
    try:
        from novel_forge.workers.dispatch import _redis_client

        settings = IndustrialSettings(root=root, redis_url="redis://127.0.0.1:1/0")
        client = _redis_client(settings)
        if client is None:
            return {"ok": True, "mode": "invalid redis url returns no client"}
        try:
            client.ping()
        except Exception:
            return {"ok": True, "mode": "redis ping failed as expected for outage drill"}
        return {"ok": False, "mode": "unexpected redis ping success against outage endpoint"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _qdrant_mismatch_drill(root: Path) -> dict[str, Any]:
    try:
        from novel_forge.storage.qdrant_index import _ensure_collection

        client = _FakeQdrantClient(existing_size=64)
        models = _FakeQdrantModels()
        embedding = {"model": "text-embedding-3-small", "provider": "openai-compatible", "dimensions": 1536}
        detected = False
        try:
            _ensure_collection(client, models, "drill", embedding, LocalStorage(root), recreate_collection=False)
        except RuntimeError:
            detected = True
        recreated = _ensure_collection(client, models, "drill", embedding, LocalStorage(root), recreate_collection=True)
        return {"detected": detected, "recreate_available": bool(recreated.get("recreated")), "status": recreated}
    except Exception as exc:
        return {"detected": False, "recreate_available": False, "error": str(exc)}


def _minio_unavailable_drill(root: Path) -> dict[str, Any]:
    settings = IndustrialSettings(root=root, minio_endpoint="", minio_access_key="", minio_secret_key="")
    configured = settings.configured_services()["minio"]
    return {"ok": configured is False, "configured": configured, "mode": "missing endpoint/access keys detected before sync"}


class _FakeQdrantClient:
    def __init__(self, existing_size: int) -> None:
        self.existing_size = existing_size
        self.deleted = False
        self.created = False

    def collection_exists(self, collection: str) -> bool:
        return not self.deleted

    def get_collection(self, collection_name: str):
        return _FakeQdrantInfo(self.existing_size)

    def delete_collection(self, collection_name: str) -> None:
        self.deleted = True

    def create_collection(self, collection_name: str, vectors_config: Any) -> None:
        self.created = True


class _FakeQdrantInfo:
    def __init__(self, size: int) -> None:
        self.config = type("Config", (), {"params": type("Params", (), {"vectors": type("Vectors", (), {"size": size})()})()})()


class _FakeQdrantModels:
    class Distance:
        COSINE = "Cosine"

    class VectorParams:
        def __init__(self, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance


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
