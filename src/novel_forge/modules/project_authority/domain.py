"""Deterministic Project/Workspace lifecycle rules."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


PROJECT_STATUSES = frozenset({"ACTIVE", "PAUSED", "ARCHIVED", "DELETED"})
PROJECT_STAGES = frozenset(
    {"DESIGN", "PLANNING", "PRODUCTION", "REVIEW", "PUBLISHING", "COMPLETED"}
)
PROJECT_HEALTH = frozenset({"UNKNOWN", "HEALTHY", "DEGRADED", "BLOCKED"})

_TRANSITIONS = {
    "ACTIVE": frozenset({"PAUSED", "ARCHIVED", "DELETED"}),
    "PAUSED": frozenset({"ACTIVE", "ARCHIVED", "DELETED"}),
    "ARCHIVED": frozenset({"ACTIVE", "DELETED"}),
    "DELETED": frozenset(),
}


def build_project_snapshot(
    *, project_id: str, workspace_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    _reject_path_authority(payload)
    title = str(payload.get("title") or "").strip()
    if not project_id or not workspace_id or not title:
        raise KernelError(
            "PROJECT_COMMAND_INVALID", "project_id, workspace_id, and title are required"
        )
    book_number = payload.get("book_number")
    if book_number is not None and (not isinstance(book_number, int) or book_number <= 0):
        raise KernelError("PROJECT_COMMAND_INVALID", "book_number must be positive")
    return {
        "schema_version": "project-authority.v1",
        "project_id": project_id,
        "workspace_id": workspace_id,
        "title": title,
        "series_title": str(payload.get("series_title") or "").strip(),
        "book_number": book_number,
        "status": "ACTIVE",
        "stage": _enum(payload.get("stage") or "DESIGN", PROJECT_STAGES, "stage"),
        "health": _enum(payload.get("health") or "UNKNOWN", PROJECT_HEALTH, "health"),
        "config": _config(payload.get("config")),
    }


def build_workspace_snapshot(
    *, project_id: str, workspace_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    _reject_path_authority(payload)
    return {
        "schema_version": "workspace-authority.v1",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "book_id": str(payload.get("book_id") or "").strip(),
        "status": "ACTIVE",
        "config": _config(payload.get("workspace_config")),
    }


def update_project_snapshot(
    current: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    _reject_path_authority(payload)
    if current.get("status") == "DELETED":
        raise KernelError("PROJECT_LIFECYCLE_TERMINAL", "deleted project cannot be updated")
    updated = dict(current)
    for key in ("title", "series_title"):
        if key in payload and payload[key] is not None:
            value = str(payload[key]).strip()
            if key == "title" and not value:
                raise KernelError("PROJECT_COMMAND_INVALID", "title must not be empty")
            updated[key] = value
    if "book_number" in payload:
        number = payload["book_number"]
        if number is not None and (not isinstance(number, int) or number <= 0):
            raise KernelError("PROJECT_COMMAND_INVALID", "book_number must be positive")
        updated["book_number"] = number
    if payload.get("stage") is not None:
        updated["stage"] = _enum(payload["stage"], PROJECT_STAGES, "stage")
    if payload.get("health") is not None:
        updated["health"] = _enum(payload["health"], PROJECT_HEALTH, "health")
    if payload.get("config") is not None:
        updated["config"] = {**_config(current.get("config")), **_config(payload["config"])}
    return updated


def transition_project_snapshot(
    current: dict[str, Any], *, target_status: str
) -> dict[str, Any]:
    source = _enum(current.get("status"), PROJECT_STATUSES, "status")
    target = _enum(target_status, PROJECT_STATUSES, "target_status")
    if target == source:
        return dict(current)
    if target not in _TRANSITIONS[source]:
        raise KernelError(
            "PROJECT_LIFECYCLE_CONFLICT", f"project cannot transition {source} -> {target}"
        )
    return {**current, "status": target}


def _enum(value: Any, allowed: frozenset[str], name: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in allowed:
        raise KernelError("PROJECT_COMMAND_INVALID", f"unsupported {name}: {normalized}")
    return normalized


def _config(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise KernelError("PROJECT_COMMAND_INVALID", "config must be an object")
    _reject_path_authority(value)
    return dict(value)


def _reject_path_authority(value: Any, prefix: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if str(key).lower().endswith(("_path", "_file", "_directory")) and child:
                raise KernelError(
                    "FILESYSTEM_AUTHORITY_FORBIDDEN",
                    f"{path} cannot be used as a production business identity",
                )
            _reject_path_authority(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_path_authority(child, f"{prefix}[{index}]")


__all__ = [
    "PROJECT_HEALTH",
    "PROJECT_STAGES",
    "PROJECT_STATUSES",
    "build_project_snapshot",
    "build_workspace_snapshot",
    "transition_project_snapshot",
    "update_project_snapshot",
]
