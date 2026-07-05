from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import create_agent_failure_report, update_agent_run_status
from novel_forge.modules.agent_scheduler.queue_lifecycle import resolve_queue, update_queue_item, utc_datetime_after
from novel_forge.storage.local import LocalStorage


def fail_queue_item(
    storage: LocalStorage,
    queue_path: str | Path,
    *,
    reason: str,
    retry_delay_seconds: int = 0,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = resolve_queue(storage, queue_path)
    data = storage.read_json(path)
    if not isinstance(data, dict) or data.get("type") != "agent_dispatch_queue":
        raise ValueError(f"agent_dispatch_queue JSON must be an object: {path}")
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    attempt_count = int(content.get("attempt_count", 0) or 0)
    max_attempts = int(content.get("max_attempts", 3) or 3)
    if attempt_count >= max_attempts:
        try:
            update_agent_run_status(
                storage,
                str(content.get("agent_run_path", "")),
                status="dead_letter",
                error=reason,
                event_type="agent_dispatch.dead_letter",
                message=reason,
            )
        except (FileNotFoundError, ValueError):
            pass
        updates = {"dead_lettered_at": utc_now(), "last_error": reason}
        if result is not None:
            updates["result"] = result
        return update_queue_item(storage, path, status="dead_letter", updates=updates)
    try:
        create_agent_failure_report(
            storage,
            agent_run_path=str(content.get("agent_run_path", "")),
            error_type="AgentSchedulerExecutionFailed",
            error_message=reason,
            recovery_instruction="Agent scheduler will retry after the queue backoff, or recover the dispatch manually from the Agent Scheduler console.",
        )
    except (FileNotFoundError, ValueError):
        pass
    updates = {"available_at": utc_datetime_after(max(0, retry_delay_seconds)), "last_error": reason}
    if result is not None:
        updates["result"] = result
    return update_queue_item(storage, path, status="retry_scheduled", updates=updates)
