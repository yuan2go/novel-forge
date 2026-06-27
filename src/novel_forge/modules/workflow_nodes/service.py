from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import NodeRun, WorkflowDefinition, WorkflowNode, validate_common_fields
from novel_forge.storage.local import LocalStorage


def create_workflow_definition(
    storage: LocalStorage,
    *,
    name: str,
    nodes: list[dict[str, Any]],
    entry_node_id: str,
    status: str = "active",
    version: str = "0.1.0",
) -> dict[str, Any]:
    workflow_id = make_id("workflow", name)
    asset = WorkflowDefinition(
        title=name,
        tags=["workflow-definition", status],
        content={
            "workflow_id": workflow_id,
            "name": name,
            "version": version,
            "nodes": nodes,
            "entry_node_id": entry_node_id,
            "status": status,
        },
        metadata={"created_by": "workflow_nodes"},
    )
    return _write(storage, asset)


def create_workflow_node(
    storage: LocalStorage,
    *,
    workflow_id: str,
    node_id: str,
    node_type: str,
    operation: str,
    input_types: list[str],
    output_types: list[str],
    processor: dict[str, Any] | None = None,
    quality_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset = WorkflowNode(
        title=f"{workflow_id}:{node_id}",
        source=workflow_id,
        tags=["workflow-node", node_type, operation],
        content={
            "node_id": node_id,
            "workflow_id": workflow_id,
            "node_type": node_type,
            "operation": operation,
            "input_types": input_types,
            "output_types": output_types,
            "processor": processor or {"kind": "local_service"},
            "quality_gate": quality_gate or {"required": False},
        },
        references=[workflow_id],
    )
    return _write(storage, asset)


def record_node_run(
    storage: LocalStorage,
    *,
    run_id: str,
    node_id: str,
    node_type: str,
    operation: str,
    status: str,
    input_assets: list[str | Path] | None = None,
    output_assets: list[str | Path] | None = None,
    processor: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    error: str = "",
    quality_gate: dict[str, Any] | None = None,
    human_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_rows = [_asset_ref(storage, item) for item in input_assets or []]
    output_rows = [_asset_ref(storage, item) for item in output_assets or []]
    project = _project_scope_from_refs(storage, [*input_rows, *output_rows])
    project_id = str(project.get("project_id", ""))
    workspace_path = str(project.get("workspace_path", ""))
    asset = NodeRun(
        title=f"{operation} {status}",
        source=run_id,
        tags=["node-run", node_type, operation, status],
        content={
            "run_id": run_id,
            "node_id": node_id,
            "node_type": node_type,
            "operation": operation,
            "status": status,
            "input_assets": input_rows,
            "output_assets": output_rows,
            "processor": processor or {"kind": "local_service", "name": operation},
            "started_at": started_at or utc_now(),
            "finished_at": finished_at or utc_now(),
            "error": error,
            "quality_gate": quality_gate or {"required": False, "status": "not_applicable"},
            "human_gate": human_gate or {"required": False, "status": "not_required"},
        },
        metadata={
            "project_id": project_id,
            "workspace_path": workspace_path,
            "recorded_at": utc_now(),
            "node_contract_version": "0.1.0",
        },
        references=filter_project_safe_references(
            storage,
            project_id,
            _dedupe([run_id, *[row.get("id", "") for row in input_rows], *[row.get("path", "") for row in input_rows], *[row.get("id", "") for row in output_rows], *[row.get("path", "") for row in output_rows]]),
        ),
    )
    return _write(storage, asset)


def list_node_runs(storage: LocalStorage, *, project_id: str | None = None, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "node_run":
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


def _write(storage: LocalStorage, asset: WorkflowDefinition | WorkflowNode | NodeRun) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _asset_ref(storage: LocalStorage, value: str | Path) -> dict[str, str]:
    path = resolve_path(storage.root, value)
    if path.exists() and path.is_file():
        try:
            asset = storage.read_asset(path)
            return {"id": asset.id, "type": asset.type, "title": asset.title, "path": _display_path(storage.root, path)}
        except Exception:
            pass
    return {"id": str(value), "type": "", "title": "", "path": str(value)}


def _project_scope_from_refs(storage: LocalStorage, refs: list[dict[str, str]]) -> dict[str, str]:
    for ref in refs:
        path = ref.get("path", "")
        if not path:
            continue
        try:
            asset = storage.read_asset(resolve_path(storage.root, path))
        except Exception:
            continue
        project = project_scope_from_asset(storage, asset, input_path=path)
        if project.get("project_id") or project.get("workspace_path"):
            return {"project_id": str(project.get("project_id", "")), "workspace_path": str(project.get("workspace_path", ""))}
    return {"project_id": "", "workspace_path": ""}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
