from __future__ import annotations

from typing import Any


def normalize_workflow_control_action(action: str, allowed_actions: set[str]) -> str:
    normalized = str(action or "").strip().lower()
    if normalized not in allowed_actions:
        raise ValueError(f"workflow control action must be one of: {', '.join(sorted(allowed_actions))}")
    return normalized


def build_pause_control_update(
    content: dict[str, Any],
    *,
    reason: str = "",
    operator: str = "workflow_control",
    next_node_id: str = "",
    terminal_statuses: set[str] | None = None,
) -> dict[str, Any]:
    status = str(content.get("status", ""))
    if status in (terminal_statuses or set()):
        raise ValueError(f"terminal workflow_run cannot be paused: {status}")
    blocked = content.get("blocked", {}) if isinstance(content.get("blocked", {}), dict) else {}
    if not blocked.get("node_id"):
        blocked = {"node_id": next_node_id, "status": "paused", "reason": reason or "workflow paused"}
    else:
        blocked = {**blocked, "status": "paused", "reason": reason or blocked.get("reason") or "workflow paused"}
    return {
        "status": "paused",
        "blocked": blocked,
        "control": {"action": "pause", "operator": operator, "reason": reason},
        "finish": False,
    }


def build_cancel_control_update(
    content: dict[str, Any],
    *,
    reason: str = "",
    operator: str = "workflow_control",
    blocked_status: str = "cancelled",
) -> dict[str, Any]:
    status = str(content.get("status", ""))
    if status in {"completed", "superseded"}:
        raise ValueError(f"workflow_run cannot be cancelled from status: {status}")
    blocked = content.get("blocked", {}) if isinstance(content.get("blocked", {}), dict) else {}
    blocked = {**blocked, "status": blocked_status, "reason": reason or "workflow cancelled"}
    return {
        "status": "cancelled",
        "blocked": blocked,
        "control": {"action": "cancel", "operator": operator, "reason": reason},
        "finish": True,
    }


def build_retry_control_evidence(action: str, reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"workflow_control_action": action, "reason": reason, **(evidence or {})}
