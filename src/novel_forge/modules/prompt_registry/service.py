from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.schemas import PromptNodeBinding, PromptRelease, PromptTemplate, PromptVersion, validate_common_fields
from novel_forge.storage.local import LocalStorage

PROMPT_ASSET_TYPES = {"prompt_template", "prompt_version", "prompt_release", "prompt_node_binding"}


def create_prompt_template(
    storage: LocalStorage,
    *,
    prompt_id: str,
    task_type: str,
    template: str,
    variables: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    status: str = "draft",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "prompt_id": prompt_id,
        "task_type": task_type,
        "template": template,
        "variables": variables or {},
        "output_schema": output_schema or {},
        "status": _status(status),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = PromptTemplate(
        title=f"{prompt_id} template",
        tags=["prompt-template", task_type, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type, "status": content["status"]},
    )
    return _write(storage, asset)


def create_prompt_version_asset(
    storage: LocalStorage,
    *,
    prompt_id: str,
    version: str,
    task_type: str,
    template: str,
    variables: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    status: str = "draft",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "prompt_id": prompt_id,
        "version": version,
        "task_type": task_type,
        "template": template,
        "variables": variables or {},
        "output_schema": output_schema or {},
        "status": _status(status),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    asset = PromptVersion(
        title=f"{prompt_id} {version}",
        tags=["prompt-version", task_type, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type, "status": content["status"]},
    )
    return _write(storage, asset)


def release_prompt_version(
    storage: LocalStorage,
    *,
    prompt_id: str,
    version: str,
    task_type: str,
    status: str = "active",
    release_note: str = "",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    prompt = _find_prompt_version(storage, prompt_id=prompt_id, version=version, task_type=task_type, project_id=project_id)
    references = [str(prompt.get("path", ""))] if prompt else []
    content = {
        "prompt_id": prompt_id,
        "version": version,
        "task_type": task_type,
        "status": _status(status),
        "release_note": release_note,
        "released_at": utc_now(),
    }
    asset = PromptRelease(
        title=f"Prompt release {prompt_id} {version}",
        tags=["prompt-release", task_type, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type, "status": content["status"]},
        references=filter_project_safe_references(storage, project_id, references),
    )
    return _write(storage, asset)


def bind_prompt_to_node(
    storage: LocalStorage,
    *,
    prompt_id: str,
    workflow_node_id: str,
    task_type: str,
    version: str = "",
    status: str = "active",
    project_id: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    content = {
        "binding_id": make_id("prompt_binding", f"{prompt_id}-{workflow_node_id}-{task_type}"),
        "prompt_id": prompt_id,
        "version": version,
        "workflow_node_id": workflow_node_id,
        "task_type": task_type,
        "status": _status(status),
        "created_at": utc_now(),
    }
    asset = PromptNodeBinding(
        title=f"Prompt binding {prompt_id} -> {workflow_node_id}",
        tags=["prompt-node-binding", task_type, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "task_type": task_type, "status": content["status"]},
    )
    return _write(storage, asset)


def resolve_prompt(
    storage: LocalStorage,
    *,
    prompt_id: str = "",
    task_type: str = "",
    version: str = "",
    workflow_node_id: str = "",
    project_id: str = "",
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding = _find_binding(storage, workflow_node_id=workflow_node_id, task_type=task_type, project_id=project_id) if workflow_node_id else None
    resolved_prompt_id = str(binding.get("content", {}).get("prompt_id", "")) if binding else prompt_id
    resolved_task_type = str(binding.get("content", {}).get("task_type", "")) if binding else task_type
    resolved_version = version or (str(binding.get("content", {}).get("version", "")) if binding else "")
    release = None if resolved_version else _find_release(storage, prompt_id=resolved_prompt_id, task_type=resolved_task_type, project_id=project_id)
    if release and not resolved_version:
        resolved_version = str(release.get("content", {}).get("version", ""))
    prompt = _find_prompt_version(storage, prompt_id=resolved_prompt_id, version=resolved_version, task_type=resolved_task_type, project_id=project_id)
    if not prompt:
        prompt = _find_prompt_template(storage, prompt_id=resolved_prompt_id, task_type=resolved_task_type, project_id=project_id)
    result = {
        "status": "resolved" if prompt else "missing",
        "prompt_id": resolved_prompt_id,
        "task_type": resolved_task_type,
        "version": resolved_version,
        "source": "prompt_version" if prompt and prompt.get("type") == "prompt_version" else ("prompt_template" if prompt else ""),
        "prompt_path": prompt.get("path", "") if prompt else "",
        "binding_path": binding.get("path", "") if binding else "",
        "release_path": release.get("path", "") if release else "",
        "template": str(prompt.get("content", {}).get("template", "")) if prompt else "",
        "variables": prompt.get("content", {}).get("variables", {}) if prompt else {},
        "output_schema": prompt.get("content", {}).get("output_schema", {}) if prompt else {},
    }
    trace_payload = dict(trace or {})
    if trace_payload.get("trace_id"):
        record_trace_span(
            storage,
            trace_id=str(trace_payload["trace_id"]),
            span_type="prompt",
            name="resolve_prompt",
            status="succeeded" if prompt else "failed",
            parent_span_id=str(trace_payload.get("span_id") or trace_payload.get("parent_span_id") or trace_payload["trace_id"]),
            attributes={key: value for key, value in result.items() if key != "template"},
            references=[value for value in [result.get("prompt_path", ""), result.get("binding_path", ""), result.get("release_path", "")] if value],
            project_id=project_id,
        )
    return result


def list_prompt_registry_assets(storage: LocalStorage, *, project_id: str | None = None, task_type: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("runs"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in PROMPT_ASSET_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        if task_type and str(content.get("task_type", metadata.get("task_type", ""))) != task_type:
            continue
        rows.append({**data, "path": _display_path(storage.root, path)})
    return sorted(rows, key=lambda row: str(row.get("updated_at", "")), reverse=True)[:limit]


def _find_binding(storage: LocalStorage, *, workflow_node_id: str, task_type: str, project_id: str) -> dict[str, Any] | None:
    for row in list_prompt_registry_assets(storage, project_id=project_id or None, task_type=task_type or None, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") == "prompt_node_binding" and content.get("status") == "active" and str(content.get("workflow_node_id", "")) == workflow_node_id:
            return row
    return None


def _find_release(storage: LocalStorage, *, prompt_id: str, task_type: str, project_id: str) -> dict[str, Any] | None:
    candidates = []
    for row in list_prompt_registry_assets(storage, project_id=project_id or None, task_type=task_type or None, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") == "prompt_release" and content.get("status") == "active" and str(content.get("prompt_id", "")) == prompt_id:
            candidates.append(row)
    return sorted(candidates, key=lambda row: str(row.get("updated_at", "")), reverse=True)[0] if candidates else None


def _find_prompt_version(storage: LocalStorage, *, prompt_id: str, version: str, task_type: str, project_id: str) -> dict[str, Any] | None:
    candidates = []
    for row in list_prompt_registry_assets(storage, project_id=project_id or None, task_type=task_type or None, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") != "prompt_version":
            continue
        if str(content.get("prompt_id", "")) != prompt_id:
            continue
        if version and str(content.get("version", "")) != version:
            continue
        if str(content.get("status", "")) not in {"active", "released", "draft"}:
            continue
        candidates.append(row)
    return sorted(candidates, key=lambda row: str(row.get("updated_at", "")), reverse=True)[0] if candidates else None


def _find_prompt_template(storage: LocalStorage, *, prompt_id: str, task_type: str, project_id: str) -> dict[str, Any] | None:
    candidates = []
    for row in list_prompt_registry_assets(storage, project_id=project_id or None, task_type=task_type or None, limit=1000):
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if row.get("type") == "prompt_template" and str(content.get("prompt_id", "")) == prompt_id and str(content.get("task_type", "")) == task_type:
            candidates.append(row)
    return sorted(candidates, key=lambda row: str(row.get("updated_at", "")), reverse=True)[0] if candidates else None


def _status(value: str) -> str:
    normalized = str(value or "draft").strip().lower().replace(" ", "_")
    return normalized if normalized in {"draft", "active", "released", "deprecated", "archived"} else "draft"


def _write(storage: LocalStorage, asset: PromptTemplate | PromptVersion | PromptRelease | PromptNodeBinding) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
