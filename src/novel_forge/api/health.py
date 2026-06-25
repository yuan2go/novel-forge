from __future__ import annotations

from typing import Any

from novel_forge.core.ids import utc_now
from novel_forge.model_adapters import embedding_provider_health


def assemble_project_health_report(
    project_id: str,
    task_status: dict[str, Any],
    failed_status: dict[str, Any],
    audit: dict[str, Any],
    handoffs: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    local_counts: dict[str, int],
    postgres: dict[str, Any],
    control: dict[str, Any],
    backups: list[dict[str, Any]],
) -> dict[str, Any]:
    asset_count = len(assets) if project_id else sum(local_counts.values())
    return {
        "project_id": project_id,
        "heartbeat": utc_now(),
        "summary": {
            "asset_count": asset_count,
            "task_count": task_status["summary"]["task_count"],
            "failed_task_count": failed_status["page"]["total"],
            "pending_handoff_count": sum(1 for item in handoffs if item.get("status") in {"pending", "in_progress", "failed"}),
            "scope_issue_count": audit["summary"]["issue_count"],
            "dead_letter_count": control["dead_letters"]["count"],
        },
        "local_asset_counts": local_counts,
        "scope_audit": audit,
        "postgres": postgres,
        "embedding": embedding_provider_health(require_semantic=True),
        "celery": control["celery"],
        "task_control": control["config"],
        "queue_trend": control["queue_trend"],
        "recent_failures": failed_status["tasks"],
        "handoffs": handoffs[:20],
        "backups": backups,
    }
