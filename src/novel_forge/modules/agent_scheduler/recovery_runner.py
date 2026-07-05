from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import update_agent_run_status
from novel_forge.modules.agent_scheduler.queue_lifecycle import resolve_queue, update_queue_item
from novel_forge.storage.local import LocalStorage

RECOVERABLE_QUEUE_STATUSES = {"dead_letter", "retry_scheduled", "waiting_human", "claimed"}


def recover_dispatch(storage: LocalStorage, *, queue_path: str | Path, reason: str = "manual recovery") -> dict[str, Any]:
    path = resolve_queue(storage, queue_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
        raise ValueError(f"agent_dispatch_queue JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if str(content.get("status", "")) not in RECOVERABLE_QUEUE_STATUSES:
        raise ValueError("agent_dispatch_queue is not recoverable")
    updates: dict[str, Any] = {
        "available_at": utc_now(),
        "lease_owner": "",
        "lease_expires_at": "",
        "last_error": "",
        "recovered_at": utc_now(),
        "recovery_reason": reason,
    }
    try:
        update_agent_run_status(storage, str(content.get("agent_run_path", "")), status="prepared", event_type="agent_dispatch.recovered", message=reason)
    except (FileNotFoundError, ValueError):
        pass
    return update_queue_item(storage, path, status="queued", updates=updates)
