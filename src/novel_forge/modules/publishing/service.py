from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.exception_policy import require_recoverable_asset_scan_error
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment, normalize_runtime_request_policy
from novel_forge.modules.publishing.release_gate import release_package_gate_evidence
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references, project_scope_from_asset
from novel_forge.modules.review_issue import assert_no_blocking_review_issues
from novel_forge.schemas import PublishingLog, PublishingPlan, ReleasePackage, validate_common_fields
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
    """Publishing-domain facade for the existing publish gate implementation."""
    from novel_forge.modules.audit import create_publish_gate_report as _create_publish_gate_report

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
    from novel_forge.modules.audit.service import (
        _asset_id,
        _asset_text,
        _assert_publish_envelope_before_side_effect,
        _cover_asset_requirements,
        _dedupe,
        _gate_has_mkaos_blocker,
        _publish_source_policy,
        _publishing_metadata_optimization,
        _read_asset_dict,
        _related_review_issue_asset_ids,
        _release_platform_rules,
        _release_tags,
        _summary,
        _title_candidates,
    )

    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=envelope,
        environment=environment,
        source_policy=_publish_source_policy(source_policy),
        operation="publishing.release_package",
    )
    environment = str(runtime_request["environment"])
    envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    resolved_source_policy = _publish_source_policy(runtime_request["source_policy"])
    _assert_publish_envelope_before_side_effect(
        storage,
        envelope=envelope,
        environment=environment,
        project_id=str(project.get("project_id", "")),
        asset_type="release_package",
        source_policy=resolved_source_policy,
        operation="publishing.release_package",
    )
    gate_path = resolve_path(storage.root, publish_gate_path) if publish_gate_path else create_publish_gate_report(
        storage,
        path,
        workspace_path=workspace_path,
        human_override=human_override,
        envelope=envelope,
        environment=environment,
        source_policy=resolved_source_policy,
    )
    gate = _read_asset_dict(storage, gate_path)
    decision = gate.get("content", {}).get("decision", "blocked") if isinstance(gate.get("content", {}), dict) else "blocked"
    if decision == "blocked" and _gate_has_mkaos_blocker(gate):
        raise ValueError("release_package blocked by MKAOS high/critical risk")
    gate_content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    release_gate_evidence = release_package_gate_evidence(gate, production=is_production_environment(environment))
    if is_production_environment(environment) and release_gate_evidence["blocking"]:
        dimensions = ", ".join(str(issue.get("dimension", "")) for issue in release_gate_evidence["blocking_issues"])
        raise ValueError(f"release_package blocked by gate evidence: {dimensions}")
    if is_production_environment(environment) and decision != "ready":
        raise ValueError(f"release_package blocked by publish gate decision: {decision}")
    status = "ready" if decision == "ready" else "blocked"
    gate_envelope = gate.get("metadata", {}).get("os_envelope", {}) if isinstance(gate.get("metadata", {}), dict) and isinstance(gate.get("metadata", {}).get("os_envelope", {}), dict) else {}
    os_envelope = enforce_os_envelope(
        storage,
        envelope_payload=envelope or gate_envelope,
        operation="publishing.release_package",
        project_id=str(project.get("project_id", "")),
        task_type="publish",
        asset_type="release_package",
        actor_type="publishing_service",
        source="publishing.create_release_package",
        context_bundle_id=str(gate_content.get("context_bundle_id", "")),
        source_policy=resolved_source_policy,
        environment=environment or str(gate_envelope.get("environment", "")),
        bypass_reason="release package local compatibility path",
        require_for_production=True,
    )
    assert_no_blocking_review_issues(
        storage,
        target_asset_id=target.id,
        project_id=str(project.get("project_id", "")) or None,
        related_asset_ids=_related_review_issue_asset_ids(target.to_dict()),
        gate="release_package",
    )
    text = _asset_text(target)
    release_version = make_id("release_version", f"{target.id}:{channel}:{utc_now()}")
    asset = ReleasePackage(
        title=f"Release package for {target.title}",
        source=target.id,
        tags=["release-package", str(channel or "local")],
        content={
            "release_version": release_version,
            "version_key": f"{target.id}:{release_version}",
            "target_asset_id": target.id,
            "publish_gate_report_id": _asset_id(gate),
            "title_candidates": _title_candidates(target.title, context),
            "summary": _summary(text),
            "tags": _release_tags(context, target),
            "metadata_optimization": _publishing_metadata_optimization(target.title, text, context),
            "cover_asset": _cover_asset_requirements(context, channel or "local"),
            "platform_review_feedback": {
                "status": "not_submitted",
                "feedback_source": "manual_or_webhook_adapter",
                "feedback_items": [],
                "回流说明": "平台审核反馈进入 publishing_log 后，再回流到审稿规则、章节计划和发布策略。",
            },
            "channel": channel or "local",
            "status": status,
            "draft_path": _display_path(storage.root, path),
            "publish_gate_report_path": _display_path(storage.root, Path(gate_path)),
            "platform_rules": _release_platform_rules(context, channel or "local"),
            "known_risks": gate_content.get("blocking_issues", []),
            "review_report": gate_content.get("required_reports", {}),
            "context_bundle_id": gate_content.get("context_bundle_id", ""),
            "context_bundle_path": gate_content.get("context_bundle_path", ""),
            "mkaos_risk": gate_content.get("mkaos_risk", {}),
            "evaluation_gate": gate_content.get("evaluation_gate", {}),
            "provider_runtime_gate": gate_content.get("provider_runtime_gate", {}),
            "platform_strategy_gate": gate_content.get("platform_strategy_gate", {}),
            "release_gate_evidence": release_gate_evidence,
            "source_isolation": {
                "source_chunk_raw_text_allowed": False,
                "runtime_assets_in_generation_rag_allowed": False,
                "raw_source_text_allowed": False,
                "release_package_raw_text_included": False,
            },
            "rollback_snapshot": {
                "draft_path": _display_path(storage.root, path),
                "publish_gate_report_path": _display_path(storage.root, Path(gate_path)),
                "created_at": utc_now(),
            },
            "os_envelope_id": os_envelope.get("envelope_id", ""),
            "created_at": utc_now(),
        },
        metadata={
            "workflow": "release-package",
            "project_id": project.get("project_id", ""),
            "workspace_path": project.get("workspace_path", ""),
            "created_at": utc_now(),
            "risk_level": "low" if status == "ready" else "high",
            **envelope_asset_metadata(os_envelope),
        },
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), _dedupe([target.id, _asset_id(gate)])),
    )
    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="create-release-package",
        input_assets=[path, gate_path],
        output_types=["release_package"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_release_package", "release_package")
        output = storage.write_asset("publishing", asset)
        run.succeed(output_assets=[_display_path(storage.root, output)])
        return output


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
