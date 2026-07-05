from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import PublishingLog, PublishingPlan, validate_common_fields
from novel_forge.storage.local import LocalStorage

PUBLISHING_TYPES = {"publish_gate_report", "release_package", "publishing_plan", "publishing_log"}


def create_publish_gate_report(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    chapter_audit_path: str | Path | None = None,
    human_override: bool = False,
    envelope: dict[str, Any] | None = None,
    environment: str = "",
    source_policy: dict[str, Any] | None = None,
) -> Path:
    from novel_forge.modules.publishing.publish_gate import create_publish_gate_report as _create_publish_gate_report

    return _create_publish_gate_report(
        storage,
        draft_path,
        workspace_path=workspace_path,
        chapter_audit_path=chapter_audit_path,
        human_override=human_override,
        envelope=envelope,
        environment=environment,
        source_policy=source_policy,
    )


def create_release_package(
    storage: LocalStorage,
    draft_path: str | Path,
    *,
    workspace_path: str | None = None,
    publish_gate_path: str | Path | None = None,
    channel: str = "local",
    human_override: bool = False,
    envelope: dict[str, Any] | None = None,
    environment: str = "",
    source_policy: dict[str, Any] | None = None,
) -> Path:
    from novel_forge.modules.publishing.release_package import create_release_package as _create_release_package

    return _create_release_package(
        storage,
        draft_path,
        workspace_path=workspace_path,
        publish_gate_path=publish_gate_path,
        channel=channel,
        human_override=human_override,
        envelope=envelope,
        environment=environment,
        source_policy=source_policy,
    )


def list_publishing_assets(storage: LocalStorage, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("publishing")):
        try:
            data = storage.read_json(path)
        except Exception as exc:
            require_recoverable_asset_scan_error(exc, context=f"publishing asset list: {path}")
            continue
        if not isinstance(data, dict) or data.get("type") not in PUBLISHING_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        calendar = content.get("calendar", []) if isinstance(content.get("calendar", []), list) else []
        chapter_queue = content.get("chapter_queue", []) if isinstance(content.get("chapter_queue", []), list) else []
        platform_targets = content.get("platform_targets", []) if isinstance(content.get("platform_targets", []), list) else []
        platform_rules = content.get("platform_rules", {}) if isinstance(content.get("platform_rules", {}), dict) else {}
        rollback_plan = content.get("rollback_plan", {}) if isinstance(content.get("rollback_plan", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "status": content.get("status", metadata.get("asset_status", "")),
                "decision": content.get("decision", ""),
                "channel": content.get("channel", ""),
                "release_version": content.get("release_version", ""),
                "version_key": content.get("version_key", ""),
                "draft_path": content.get("draft_path", ""),
                "calendar_count": len(calendar),
                "next_scheduled_at": _next_scheduled_at(calendar),
                "chapter_queue_count": len(chapter_queue),
                "platform_targets": platform_targets,
                "platform_rules": platform_rules,
                "metadata_optimization": content.get("metadata_optimization", {}) if isinstance(content.get("metadata_optimization", {}), dict) else {},
                "cover_asset": content.get("cover_asset", {}) if isinstance(content.get("cover_asset", {}), dict) else {},
                "platform_feedback": content.get("platform_feedback", {}) if isinstance(content.get("platform_feedback", {}), dict) else {},
                "gate_policy": content.get("gate_policy", {}) if isinstance(content.get("gate_policy", {}), dict) else {},
                "rollback_available": bool(rollback_plan.get("available")),
                "release_package_path": content.get("release_package_path", ""),
                "scheduled_at": content.get("scheduled_at", ""),
                "published_at": content.get("published_at", ""),
                "external_url": content.get("external_url", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def create_publishing_plan(
    storage: LocalStorage,
    *,
    release_package_paths: list[str | Path] | None = None,
    project_id: str | None = None,
    workspace_path: str | None = None,
    channel: str = "local",
    cadence: str = "daily",
    start_date: str = "",
) -> dict[str, Any]:
    packages = _release_packages(storage, release_package_paths or [], project_id=project_id)
    project = _project_from_packages(storage, packages, project_id=project_id, workspace_path=workspace_path)
    resolved_project_id = str(project.get("project_id", project_id or ""))
    workspace = str(project.get("workspace_path", workspace_path or ""))
    calendar = _calendar_rows(packages, start_date=start_date, cadence=cadence)
    chapter_queue = _chapter_queue(packages)
    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="create-publishing-plan",
        input_assets=[item["path"] for item in packages],
        output_types=["publishing_plan"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_publishing_plan", "publishing_plan")
        asset = PublishingPlan(
            title=f"Publishing plan {channel} {utc_now()}",
            tags=["publishing", "plan", channel],
            content={
                "plan_id": make_id("publishing_plan", resolved_project_id or channel),
                "project_id": resolved_project_id or "global",
                "calendar": calendar,
                "chapter_queue": chapter_queue,
                "platform_targets": [{"channel": channel or "local", "cadence": cadence or "daily", "status": "planned"}],
                "platform_rules": _publishing_platform_rules(channel or "local", cadence or "daily"),
                "gate_policy": {
                    "require_publish_gate_ready": True,
                    "require_originality_pass": True,
                    "blocked_packages": [item["path"] for item in packages if item.get("status") != "ready"],
                    "rollback_required": True,
                },
                "status": "active",
                "created_at": utc_now(),
            },
            metadata={"project_id": resolved_project_id, "workspace_path": workspace, "workflow": "publishing-plan", "channel": channel},
            references=filter_project_safe_references(storage, resolved_project_id, [item["id"] for item in packages] + [item["path"] for item in packages]),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_publishing_log(
    storage: LocalStorage,
    release_package_path: str | Path,
    *,
    publishing_plan_path: str | Path | None = None,
    channel: str = "local",
    status: str = "published",
    external_url: str = "",
    rollback_note: str = "",
) -> dict[str, Any]:
    package_file = resolve_path(storage.root, release_package_path)
    package = storage.read_asset(package_file)
    if package.type != "release_package":
        raise ValueError("release_package_path must point to a release_package asset")
    project = project_scope_from_asset(storage, package, input_path=package_file)
    project_id = str(project.get("project_id", ""))
    workspace = str(project.get("workspace_path", ""))
    plan_ref = ""
    if publishing_plan_path:
        plan_ref = _display_path(storage.root, resolve_path(storage.root, publishing_plan_path))
    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="create-publishing-log",
        input_assets=[package_file],
        output_types=["publishing_log"],
        workspace_path=workspace,
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_publishing_log", "publishing_log")
        content = package.content if isinstance(package.content, dict) else {}
        asset = PublishingLog(
            title=f"Publishing log for {package.title or package.id}",
            source=package.id,
            tags=["publishing", "log", status, channel],
            content={
                "log_id": make_id("publishing_log", package.id),
                "release_package_id": package.id,
                "release_package_path": _display_path(storage.root, package_file),
                "publishing_plan_path": plan_ref,
                "channel": channel or content.get("channel", "local"),
                "status": status,
                "published_at": utc_now() if status == "published" else "",
                "external_url": external_url,
                "platform_feedback": _platform_feedback(status=status, external_url=external_url),
                "rollback_plan": {
                    "available": True,
                    "status": "not_required" if status == "published" else "pending",
                    "note": rollback_note,
                    "source_release_package_path": _display_path(storage.root, package_file),
                },
                "gate_evidence": {
                    "publish_gate_report_path": content.get("publish_gate_report_path", ""),
                    "release_status": content.get("status", ""),
                },
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id, "workspace_path": workspace, "workflow": "publishing-log", "channel": channel, "asset_status": status},
            references=filter_project_safe_references(storage, project_id, [package.id, _display_path(storage.root, package_file), plan_ref]),
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def _release_packages(storage: LocalStorage, paths: list[str | Path], *, project_id: str | None = None) -> list[dict[str, Any]]:
    candidates = [resolve_path(storage.root, item) for item in paths] if paths else list(reversed(storage.list_json("publishing")))
    rows: list[dict[str, Any]] = []
    for path in candidates:
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "release_package":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if project_id and str(metadata.get("project_id", "")) != project_id:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "id": data.get("id", ""),
                "path": _display_path(storage.root, path),
                "title": data.get("title") or data.get("name", ""),
                "status": content.get("status", ""),
                "channel": content.get("channel", ""),
                "draft_path": content.get("draft_path", ""),
                "publish_gate_report_path": content.get("publish_gate_report_path", ""),
                "metadata": metadata,
            }
        )
    return rows[:200]


def _project_from_packages(
    storage: LocalStorage,
    packages: list[dict[str, Any]],
    *,
    project_id: str | None,
    workspace_path: str | None,
) -> dict[str, Any]:
    if workspace_path:
        return project_scope_from_asset(storage, {}, workspace_path=workspace_path)
    for item in packages:
        try:
            asset = storage.read_asset(resolve_path(storage.root, item["path"]))
            project = project_scope_from_asset(storage, asset, input_path=item["path"])
            if project.get("project_id") or project.get("workspace_path"):
                return project
        except Exception as exc:
            require_recoverable_asset_scan_error(exc, context=f"publishing package project resolution: {item.get('path', '')}")
            continue
    return {"project_id": project_id or "", "workspace_path": workspace_path or ""}


def _calendar_rows(packages: list[dict[str, Any]], *, start_date: str, cadence: str) -> list[dict[str, Any]]:
    return [
        {
            "slot": index,
            "scheduled_at": start_date or f"T+{index - 1} {cadence}",
            "release_package_path": item["path"],
            "status": "ready" if item.get("status") == "ready" else "blocked",
        }
        for index, item in enumerate(packages, start=1)
    ]


def _chapter_queue(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "order": index,
            "release_package_id": item["id"],
            "release_package_path": item["path"],
            "draft_path": item.get("draft_path", ""),
            "gate_path": item.get("publish_gate_report_path", ""),
            "status": item.get("status", ""),
        }
        for index, item in enumerate(packages, start=1)
    ]


def _publishing_platform_rules(channel: str, cadence: str) -> dict[str, Any]:
    return {
        "channel": channel,
        "cadence": cadence,
        "require_release_package_ready": True,
        "require_publish_gate_ready": True,
        "require_originality_pass": True,
        "rollback_record_required": True,
        "schedule_mode": "local_calendar",
    }


def _platform_feedback(*, status: str, external_url: str) -> dict[str, Any]:
    normalized = str(status or "").lower()
    feedback_status = "accepted" if normalized == "published" else "needs_followup" if normalized in {"failed", "rejected"} else "pending"
    return {
        "status": feedback_status,
        "external_url": external_url,
        "items": [],
        "strategy_backwrite": {
            "chapter_plan": normalized in {"failed", "rejected"},
            "review_rules": normalized in {"failed", "rejected"},
            "publishing_plan": True,
        },
        "next_action": "import platform feedback details when available" if feedback_status != "accepted" else "monitor reader feedback after release",
    }


def _next_scheduled_at(calendar: list[Any]) -> str:
    for item in calendar:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", ""))
        if status not in {"published", "completed", "cancelled"}:
            return str(item.get("scheduled_at", ""))
    return ""


def _write(storage: LocalStorage, asset: PublishingPlan | PublishingLog) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": data, "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
