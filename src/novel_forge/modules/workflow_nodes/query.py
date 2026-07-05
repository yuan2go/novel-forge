from __future__ import annotations

from typing import Any

from novel_forge.core.asset_scan import iter_json_objects
from novel_forge.storage.local import LocalStorage


def list_node_runs(storage: LocalStorage, *, project_id: str | None = None, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, data in iter_json_objects(storage, "runs", reverse=True, context="workflow node run list"):
        if data.get("type") != "node_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if run_id and str(content.get("run_id", "")) != run_id:
            continue
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "run_id": content.get("run_id", ""),
                "node_id": content.get("node_id", ""),
                "node_type": content.get("node_type", ""),
                "operation": content.get("operation", ""),
                "status": content.get("status", ""),
                "input_count": len(content.get("input_assets", []) if isinstance(content.get("input_assets", []), list) else []),
                "output_count": len(content.get("output_assets", []) if isinstance(content.get("output_assets", []), list) else []),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "started_at": content.get("started_at", ""),
                "finished_at": content.get("finished_at", ""),
                "error": content.get("error", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def list_workflow_definitions(storage: LocalStorage, *, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, data in iter_json_objects(storage, "runs", reverse=True, context="workflow definition list"):
        if data.get("type") != "workflow_definition":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "workflow_id": content.get("workflow_id", ""),
                "name": content.get("name", data.get("title", "")),
                "version": content.get("version", ""),
                "entry_node_id": content.get("entry_node_id", ""),
                "status": content.get("status", ""),
                "node_count": len(content.get("nodes", []) if isinstance(content.get("nodes", []), list) else []),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def list_workflow_runs(storage: LocalStorage, *, project_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path, data in iter_json_objects(storage, "runs", reverse=True, context="workflow run list"):
        if data.get("type") != "workflow_run":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if status and str(content.get("status", "")) != status:
            continue
        blocked = content.get("blocked", {}) if isinstance(content.get("blocked", {}), dict) else {}
        trace = content.get("trace", {}) if isinstance(content.get("trace", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "run_id": content.get("run_id", ""),
                "workflow_id": content.get("workflow_id", ""),
                "status": content.get("status", ""),
                "blocked_node_id": blocked.get("node_id", ""),
                "blocked_status": blocked.get("status", ""),
                "blocked_reason": blocked.get("reason", ""),
                "node_run_count": len(content.get("node_runs", []) if isinstance(content.get("node_runs", []), list) else []),
                "agent_run_count": len(content.get("agent_runs", []) if isinstance(content.get("agent_runs", []), list) else []),
                "output_count": len(content.get("outputs", []) if isinstance(content.get("outputs", []), list) else []),
                "trace_id": trace.get("trace_id", content.get("run_id", "")),
                "project_id": metadata.get("project_id", ""),
                "workspace_path": metadata.get("workspace_path", ""),
                "started_at": content.get("started_at", ""),
                "finished_at": content.get("finished_at", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _display_path(root, path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
