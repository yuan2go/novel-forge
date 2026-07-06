from __future__ import annotations

from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


def build_project_cockpit_snapshot(storage: LocalStorage, *, project_id: str = "local-project") -> dict[str, Any]:
    rows = _project_assets(storage, project_id=project_id)
    type_counts = _type_counts(rows)
    blocking_issues = list_review_issues(storage, project_id=project_id or None, blocking=True, limit=500)
    queue_status = _status_counts(rows, asset_type="agent_dispatch_queue", status_path=["content", "status"])
    release_status = _latest_status(rows, asset_type="release_package")
    long_chain_status = _latest_status(rows, asset_type="long_chain_acceptance_report")
    content = {
        "project_id": project_id,
        "snapshot_at": utc_now(),
        "throughput": {
            "outline_count": type_counts.get("outline", 0),
            "chapter_plan_count": type_counts.get("chapter_plan", 0),
            "draft_count": type_counts.get("draft_chapter", 0),
            "review_count": type_counts.get("review_report", 0),
            "release_package_count": type_counts.get("release_package", 0),
        },
        "quality": {
            "blocking_review_issue_count": len(blocking_issues),
            "latest_long_chain_status": long_chain_status,
            "latest_release_status": release_status,
        },
        "task_health": {
            "agent_queue_status": queue_status,
            "ready_or_running": queue_status.get("ready", 0) + queue_status.get("running", 0),
        },
        "agent_health": {
            "agent_run_count": type_counts.get("agent_run", 0),
            "dispatch_queue_count": type_counts.get("agent_dispatch_queue", 0),
        },
        "storage_health": {
            "asset_count": len(rows),
            "asset_type_count": len(type_counts),
            "data_dirs_scanned": len(DATA_DIRS),
        },
        "recommendations": _cockpit_recommendations(blocking_issues, release_status, long_chain_status),
        "cockpit": {
            "book_production_state": "blocked" if blocking_issues else "active",
            "today_chapter_queue": _latest_assets(rows, "chapter_plan", limit=10),
            "risk_summary": {
                "context": "inspect latest context_bundle",
                "canon": "inspect canon_state_machine_snapshot",
                "style": "inspect latest style_drift_report",
                "quality": long_chain_status,
            },
            "rollback_recovery_entry": "use runtime rollback and workflow resume APIs with trace evidence",
        },
    }
    asset = ProjectMetricSnapshot(
        title=f"Novel OS cockpit snapshot {project_id}",
        tags=["novel-os-cockpit", project_id],
        content=content,
        metadata={"project_id": project_id, "snapshot_kind": "novel_os_cockpit"},
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(storage.root / path), "summary": content["cockpit"]}


def build_multi_book_daily_production_report(storage: LocalStorage, *, project_ids: list[str] | None = None, provider_budget: float = 0.0) -> dict[str, Any]:
    ids = project_ids or _known_project_ids(storage)
    book_rows = []
    for project_id in ids:
        rows = _project_assets(storage, project_id=project_id)
        type_counts = _type_counts(rows)
        book_rows.append(
            {
                "project_id": project_id,
                "draft_count": type_counts.get("draft_chapter", 0),
                "chapter_plan_count": type_counts.get("chapter_plan", 0),
                "blocking_review_issue_count": len(list_review_issues(storage, project_id=project_id or None, blocking=True, limit=500)),
                "memory_isolation": "project_id_scoped",
                "contamination_detection": "requires cross-book canon/style comparison before shared context",
            }
        )
    content = {
        "project_id": "multi-book",
        "snapshot_at": utc_now(),
        "throughput": {"book_count": len(book_rows), "planned_daily_chapters": len(book_rows)},
        "quality": {"blocked_books": sum(1 for row in book_rows if row["blocking_review_issue_count"]), "quality_policy": "per-book gates remain isolated"},
        "task_health": {"book_level_scheduler": "planned", "book_rows": book_rows},
        "agent_health": {"capacity_plan": _capacity_plan(book_rows)},
        "storage_health": {"memory_isolation": "project_id/workspace_path", "cross_book_contamination_detection": "planned"},
        "recommendations": ["Run per-book production gates before scheduling provider work", "Keep provider budget per book and per operation"],
        "multi_book_scheduler": {
            "books": book_rows,
            "provider_budget_plan": {"daily_budget": provider_budget, "per_book_budget": round(provider_budget / max(1, len(book_rows)), 4)},
            "daily_production_report": "schema-backed project_metric_snapshot",
        },
    }
    asset = ProjectMetricSnapshot(
        title="Multi-book daily production report",
        tags=["novel-os-cockpit", "multi-book", "daily-production"],
        content=content,
        metadata={"project_id": "multi-book", "snapshot_kind": "multi_book_daily_production"},
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(storage.root / path), "book_count": len(book_rows)}


def _project_assets(storage: LocalStorage, *, project_id: str) -> list[dict[str, Any]]:
    rows = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = _read_json_safe(storage, path)
            if not data:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            if project_id and row_project and row_project != project_id:
                continue
            rows.append({**data, "path": _display_path(storage.root, path)})
    return rows


def _known_project_ids(storage: LocalStorage) -> list[str]:
    ids = set()
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = _read_json_safe(storage, path)
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            project_id = str(metadata.get("project_id") or content.get("project_id") or "")
            if project_id:
                ids.add(project_id)
    return sorted(ids) or ["local-project"]


def _type_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        asset_type = str(row.get("type") or "")
        counts[asset_type] = counts.get(asset_type, 0) + 1
    return counts


def _status_counts(rows: list[dict[str, Any]], *, asset_type: str, status_path: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("type") != asset_type:
            continue
        value: Any = row
        for key in status_path:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        status = str(value or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _latest_status(rows: list[dict[str, Any]], *, asset_type: str) -> str:
    matches = [row for row in rows if row.get("type") == asset_type]
    if not matches:
        return "missing"
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    return str(content.get("status") or content.get("recommendation") or content.get("decision") or "available")


def _latest_assets(rows: list[dict[str, Any]], asset_type: str, *, limit: int) -> list[dict[str, str]]:
    matches = [row for row in rows if row.get("type") == asset_type]
    matches = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)[:limit]
    return [{"id": str(row.get("id") or ""), "title": str(row.get("title") or ""), "path": str(row.get("path") or "")} for row in matches]


def _capacity_plan(book_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "agent_capacity_units": max(1, len(book_rows)),
        "provider_parallelism": min(4, max(1, len(book_rows))),
        "scheduling_policy": "book-level queue with per-book memory isolation",
    }


def _cockpit_recommendations(blocking_issues: list[dict[str, Any]], release_status: str, long_chain_status: str) -> list[str]:
    recommendations = []
    if blocking_issues:
        recommendations.append("Resolve blocking ReviewIssue before release or regeneration")
    if release_status not in {"ready", "published"}:
        recommendations.append("Run release gate and release package readiness checks")
    if long_chain_status not in {"ready", "pass"}:
        recommendations.append("Run long-chain proof before scaling production")
    return recommendations or ["Project cockpit is clear for the next governed production step"]


def _read_json_safe(storage: LocalStorage, path) -> dict[str, Any]:
    try:
        data = storage.read_json(path)
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_asset(storage: LocalStorage, asset: ProjectMetricSnapshot) -> str:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(asset))


def _display_path(root, path) -> str:
    candidate = path if hasattr(path, "is_absolute") else root / str(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)
