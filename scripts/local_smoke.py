from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


API_BASE = "http://127.0.0.1:8000"
WEB_BASE = "http://127.0.0.1:3000"
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    checks = [
        ("api health", lambda: check_api_health()),
        ("postgres index", lambda: check_postgres_index()),
        ("task control", lambda: check_task_control()),
        ("asset list", lambda: check_asset_list()),
        ("web", lambda: check_web()),
    ]
    failed: list[str] = []
    for name, check in checks:
        try:
            check()
            print(f"ok: {name}")
        except Exception as exc:
            failed.append(f"{name}: {exc}")
            print(f"fail: {name}: {exc}", file=sys.stderr)
    if failed:
        print("\nlocal smoke failed:", file=sys.stderr)
        for item in failed:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("\nlocal production smoke passed")
    return 0


def check_api_health() -> None:
    health = wait_json(f"{API_BASE}/health", timeout=90)
    if "local_counts" not in health:
        raise AssertionError("health response missing local_counts")


def check_postgres_index() -> None:
    health = wait_json(f"{API_BASE}/health", timeout=15)
    postgresql = health.get("postgresql", {})
    if postgresql.get("api_index_mode") != "postgres-primary-json-fallback":
        raise AssertionError(f"unexpected api_index_mode: {postgresql.get('api_index_mode')}")
    projects = wait_json(f"{API_BASE}/product/projects", timeout=15)
    if projects and projects[0].get("index_source") != "postgres":
        raise AssertionError("project API did not read from postgres index")


def check_task_control() -> None:
    control = wait_json(f"{API_BASE}/product/tasks/control", timeout=15)
    if "celery" not in control:
        raise AssertionError("task control response missing celery")
    celery = control["celery"]
    if not celery.get("available"):
        raise AssertionError(f"celery unavailable: {celery.get('error', '')}")


def check_asset_list() -> None:
    assets = wait_json(f"{API_BASE}/assets?limit=1", timeout=15)
    if not isinstance(assets, list):
        raise AssertionError("assets response is not a list")


def check_web() -> None:
    text = wait_text(WEB_BASE, timeout=90)
    if "Production Console" not in text and "Novel Forge Admin" not in text:
        raise AssertionError("web response does not look like admin console")


def wait_json(url: str, timeout: int) -> Any:
    text = wait_text(url, timeout)
    return json.loads(text)


def wait_text(url: str, timeout: int) -> str:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with LOCAL_OPENER.open(url, timeout=5) as response:
                if response.status >= 400:
                    raise AssertionError(f"{url} returned HTTP {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, AssertionError) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
