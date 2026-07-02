from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

ROOT = Path(os.environ.get("NOVEL_FORGE_ROOT", ".local/workspace")).resolve()
API_BASE = os.environ.get("NOVEL_FORGE_API_BASE", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("NOVEL_FORGE_WEB_BASE", "http://127.0.0.1:3000")
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    checks: list[tuple[str, Callable[[], None]]] = [
        ("backend import", check_backend_import),
        ("FastAPI startup and API contract", check_fastapi_contract),
        ("DB migration dry-run", check_db_migration_dry_run),
        ("worker / scheduler smoke", check_scheduler_smoke),
        ("unit tests", check_unit_tests),
        ("key integration tests", check_integration_tests),
        ("Web Admin smoke or build", check_web_admin),
    ]
    failed: list[str] = []
    for name, check in checks:
        try:
            check()
            print(f"ok: {name}")
        except Exception as exc:
            failed.append(f"{name}: {exc}")
            print(f"fail: {name}: {exc}", file=sys.stderr)
    report = {
        "status": "failed" if failed else "passed",
        "root": str(ROOT),
        "failed": failed,
        "checks": [name for name, _ in checks],
    }
    report_path = Path("docs/reports/local-smoke-report.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_markdown_report(report), encoding="utf-8")
    if failed:
        print("\nlocal smoke failed:", file=sys.stderr)
        for item in failed:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("\nlocal production smoke passed")
    return 0


def check_backend_import() -> None:
    from novel_forge.api.app import create_app  # noqa: F401
    from novel_forge.infrastructure.settings import IndustrialSettings  # noqa: F401
    from novel_forge.modules.runtime_policy import runtime_policy_surface_coverage_report  # noqa: F401


def check_fastapi_contract() -> None:
    try:
        health = wait_json(f"{API_BASE}/health", timeout=5)
        if "local_counts" not in health:
            raise AssertionError("health response missing local_counts")
        for path in [
            "/product/projects",
            "/product/runtime/policy/status",
            "/product/runtime/policy/surface-coverage",
            "/product/runtime/provider-hard-stop-evidence",
            "/product/agents/center",
            "/product/longform-stability/dashboard",
        ]:
            wait_json(f"{API_BASE}{path}", timeout=5)
        return
    except Exception:
        pass

    from fastapi.testclient import TestClient
    from novel_forge.api.app import create_app
    from novel_forge.infrastructure.settings import IndustrialSettings

    settings = IndustrialSettings.from_env(root=ROOT)
    client = TestClient(create_app(settings))
    for path in [
        "/health",
        "/product/projects",
        "/product/runtime/policy/status",
        "/product/runtime/policy/surface-coverage",
        "/product/runtime/provider-hard-stop-evidence",
        "/product/agents/center",
        "/product/longform-stability/dashboard",
    ]:
        response = client.get(path)
        if response.status_code >= 400:
            raise AssertionError(f"{path} returned {response.status_code}: {response.text[:500]}")


def check_db_migration_dry_run() -> None:
    from novel_forge.modules.pgvector_store import migrate_pgvector_online, pgvector_operations_plan
    from novel_forge.storage.local import LocalStorage

    storage = LocalStorage(ROOT)
    storage.ensure_layout()
    migration = migrate_pgvector_online(storage, dry_run=True)
    if migration.get("status") != "planned":
        raise AssertionError(f"unexpected pgvector dry-run status: {migration.get('status')}")
    plan = pgvector_operations_plan(storage, persist=False)
    if "migration_steps" not in plan.get("content", {}):
        raise AssertionError("pgvector operations plan missing migration_steps")


def check_scheduler_smoke() -> None:
    from novel_forge.modules.agent_scheduler import agent_center_snapshot, run_agent_scheduler_tick, scheduler_status
    from novel_forge.modules.workflow_nodes import build_workflow_runtime_console, create_workflow_definition
    from novel_forge.storage.local import LocalStorage

    storage = LocalStorage(ROOT)
    storage.ensure_layout()
    status = scheduler_status(storage)
    if "queue_count" not in status:
        raise AssertionError("agent scheduler status missing queue_count")
    tick = run_agent_scheduler_tick(storage, dry_run=True, limit=1)
    if tick.get("status") not in {"completed", "skipped"}:
        raise AssertionError(f"unexpected scheduler dry-run status: {tick.get('status')}")
    center = agent_center_snapshot(storage)
    if "summary" not in center:
        raise AssertionError("agent center snapshot missing summary")
    workflow = create_workflow_definition(
        storage,
        name="Local Smoke Workflow",
        entry_node_id="policy",
        nodes=[
            {
                "node_id": "policy",
                "node_type": "service",
                "operation": "runtime_policy_enforcement_report",
                "input_types": [],
                "output_types": ["gate_result"],
                "processor": {"kind": "service", "operation": "runtime_policy_enforcement_report"},
            }
        ],
    )
    console = build_workflow_runtime_console(storage, workflow_path_or_id=workflow["path"])
    if "processor_contracts" not in console or "state_machine" not in console:
        raise AssertionError("workflow runtime console missing contracts or state machine")


def check_unit_tests() -> None:
    run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.unit.test_runtime_policy",
            "tests.unit.test_provider_runtime_guard",
            "tests.unit.test_agent_scheduler",
            "tests.unit.test_longform_stability",
            "tests.unit.test_product_api_routes",
        ]
    )


def check_integration_tests() -> None:
    run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.integration.test_longform_quality_gate_e2e",
            "tests.integration.test_novel_os_long_chain_smoke",
        ]
    )


def check_web_admin() -> None:
    if _remote_web_available():
        text = wait_text(WEB_BASE, timeout=5)
        if "Production Console" not in text and "Novel Forge Admin" not in text:
            raise AssertionError("web response does not look like admin console")
        return
    run_command(["npm", "--prefix", "web/admin", "test"])
    run_command(["npm", "--prefix", "web/admin", "run", "build"])


def run_command(args: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["NOVEL_FORGE_ROOT"] = str(ROOT)
    completed = subprocess.run(args, cwd=Path.cwd(), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed with {completed.returncode}\n{completed.stdout[-4000:]}")


def wait_json(url: str, timeout: int) -> Any:
    return json.loads(wait_text(url, timeout))


def wait_text(url: str, timeout: int) -> str:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with LOCAL_OPENER.open(url, timeout=3) as response:
                if response.status >= 400:
                    raise AssertionError(f"{url} returned HTTP {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, AssertionError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def _remote_web_available() -> bool:
    try:
        wait_text(WEB_BASE, timeout=2)
        return True
    except Exception:
        return False


def _markdown_report(report: dict[str, Any]) -> str:
    failed = report.get("failed", [])
    lines = [
        "# Local Smoke Report",
        "",
        f"Status: {report['status']}",
        f"Root: `{report['root']}`",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- {name}" for name in report.get("checks", []))
    lines.extend(["", "## Failures", ""])
    if failed:
        lines.extend(f"- {item}" for item in failed)
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
