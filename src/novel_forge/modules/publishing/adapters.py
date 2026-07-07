from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import PublishingLog, validate_common_fields
from novel_forge.storage.local import LocalStorage


@dataclass(frozen=True)
class PlatformAdapter:
    key: str
    label: str
    mode: str
    external: bool
    requires_endpoint: bool
    can_execute: bool
    description: str


ADAPTERS = {
    "local_file": PlatformAdapter(
        key="local_file",
        label="Local File Export",
        mode="local",
        external=False,
        requires_endpoint=False,
        can_execute=True,
        description="Prepare a local release payload and audit log without contacting external services.",
    ),
    "manual_web": PlatformAdapter(
        key="manual_web",
        label="Manual Web Publishing",
        mode="manual",
        external=True,
        requires_endpoint=False,
        can_execute=False,
        description="Prepare title, summary, tags, and checklist for manual copy into an external publishing platform.",
    ),
    "external_webhook": PlatformAdapter(
        key="external_webhook",
        label="External Webhook",
        mode="webhook",
        external=True,
        requires_endpoint=True,
        can_execute=False,
        description="Dry-run by default. Real webhook calls require explicit NOVEL_FORGE_ALLOW_EXTERNAL_PUBLISH=true.",
    ),
}


def publishing_adapter_status() -> list[dict[str, Any]]:
    endpoint = os.environ.get("NOVEL_FORGE_PUBLISH_WEBHOOK_URL", "")
    allow_external = _external_publish_allowed()
    return [
        {
            "key": adapter.key,
            "label": adapter.label,
            "mode": adapter.mode,
            "external": adapter.external,
            "requires_endpoint": adapter.requires_endpoint,
            "configured": (bool(endpoint) if adapter.requires_endpoint else True),
            "can_execute": adapter.can_execute or (adapter.key == "external_webhook" and bool(endpoint) and allow_external),
            "dry_run_default": adapter.external,
            "description": adapter.description,
        }
        for adapter in ADAPTERS.values()
    ]


def prepare_platform_release(
    storage: LocalStorage,
    release_package_path: str | Path,
    *,
    adapter_key: str = "manual_web",
    publishing_plan_path: str | Path | None = None,
    dry_run: bool = True,
    external_url: str = "",
) -> dict[str, Any]:
    adapter = ADAPTERS.get(adapter_key)
    if not adapter:
        raise ValueError(f"unknown publishing adapter: {adapter_key}")
    package_file = resolve_path(storage.root, release_package_path)
    package = storage.read_asset(package_file)
    if package.type != "release_package":
        raise ValueError("release_package_path must point to a release_package asset")
    content = package.content if isinstance(package.content, dict) else {}
    project = project_scope_from_asset(storage, package, input_path=package_file)
    plan_ref = _display_path(storage.root, resolve_path(storage.root, publishing_plan_path)) if publishing_plan_path else ""
    payload = _platform_payload(package, package_file, adapter, plan_ref=plan_ref)
    approval_request = _create_platform_publish_approval_request(
        storage,
        adapter=adapter,
        project_id=str(project.get("project_id") or "publishing"),
        release_package_path=_display_path(storage.root, package_file),
        publishing_plan_path=plan_ref,
        dry_run=dry_run,
    ) if adapter.external else {}
    approval_summary = _approval_request_summary(approval_request, required=adapter.external)
    executed = False
    execution_result: dict[str, Any] = {"status": "dry_run", "message": "external execution disabled"}
    if adapter.key == "external_webhook" and not dry_run:
        execution_result = {"status": "approval_required", "message": "external webhook publish requires approved ApprovalRequest before execution"}
    elif adapter.key == "local_file" and not dry_run:
        execution_result = {"status": "prepared", "message": "local payload prepared"}
        executed = True
    elif adapter.key == "manual_web":
        execution_result = {"status": "manual_required", "message": "copy prepared payload into the external platform manually"}

    with AgentExecutionContext(
        storage,
        agent_key="publishing",
        operation="prepare-platform-release",
        input_assets=[package_file],
        output_types=["publishing_log"],
        workspace_path=str(project.get("workspace_path", "")),
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        run.guard("write_publishing_log", "publishing_log")
        log_status = "published" if executed else "planned"
        log = PublishingLog(
            title=f"Publishing adapter preview for {package.title or package.id}",
            source=package.id,
            tags=["publishing", "adapter", adapter.key, "dry-run" if dry_run else "execute"],
            content={
                "log_id": make_id("publishing_log", f"{package.id}:{adapter.key}"),
                "release_package_id": package.id,
                "release_package_path": _display_path(storage.root, package_file),
                "publishing_plan_path": plan_ref,
                "channel": adapter.key,
                "status": log_status,
                "published_at": utc_now(),
                "external_url": external_url,
                "adapter": adapter.key,
                "dry_run": dry_run,
                "adapter_payload": payload,
                "adapter_result": execution_result,
                "approval_request": approval_summary,
                "rollback_plan": {
                    "available": True,
                    "status": "manual_required" if adapter.external else "local",
                    "source_release_package_path": _display_path(storage.root, package_file),
                },
                "created_at": utc_now(),
            },
            metadata={
                "project_id": project.get("project_id", ""),
                "workspace_path": project.get("workspace_path", ""),
                "workflow": "publishing-adapter",
                "channel": adapter.key,
                "asset_status": log_status,
            },
            references=filter_project_safe_references(storage, str(project.get("project_id", "")), [package.id, _display_path(storage.root, package_file), plan_ref]),
        )
        errors = validate_common_fields(log.to_dict())
        if errors:
            raise ValueError("; ".join(errors))
        output = storage.write_asset_auto(log)
        run.succeed(output_assets=[_display_path(storage.root, output)])
    return {"path": _display_path(storage.root, output), "adapter": adapter.key, "dry_run": dry_run, "payload": payload, "result": execution_result}


def _create_platform_publish_approval_request(
    storage: LocalStorage,
    *,
    adapter: PlatformAdapter,
    project_id: str,
    release_package_path: str,
    publishing_plan_path: str,
    dry_run: bool,
) -> dict[str, Any]:
    from novel_forge.modules.permission_center import create_approval_request

    return create_approval_request(
        storage,
        {
            "project_id": project_id or "publishing",
            "scope": "publish",
            "action": "approve_platform_publish",
            "risk_level": "high",
            "environment": "local" if dry_run else "production",
            "blocking": True,
            "target_type": "platform_publish_adapter",
            "target_id": adapter.key,
            "target_refs": _dedupe([release_package_path, publishing_plan_path]),
            "evidence_refs": _dedupe([release_package_path, publishing_plan_path]),
            "requested_by": "publishing-adapter",
            "subject_type": "agent",
            "subject_id": "publishing-agent",
            "reason": "external platform publishing requires operator approval before manual submission or webhook execution",
            "required_before": ["external_platform_submission", "platform_webhook_call", "manual_platform_publish"],
            "rollback_plan": {
                "automatic_publish_allowed": False,
                "rollback_action": "do not submit externally until approval request is approved",
                "release_package_path": release_package_path,
            },
        },
    )


def _approval_request_summary(approval_request: dict[str, Any], *, required: bool) -> dict[str, Any]:
    asset = approval_request.get("asset", {}) if isinstance(approval_request, dict) else {}
    content = asset.get("content", {}) if isinstance(asset, dict) and isinstance(asset.get("content", {}), dict) else {}
    return {
        "required": bool(required),
        "path": str(approval_request.get("path", "")) if isinstance(approval_request, dict) else "",
        "request_id": str(content.get("request_id") or ""),
        "scope": str(content.get("scope") or ("publish" if required else "")),
        "status": str(content.get("status") or ""),
    }


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _platform_payload(package: Any, package_file: Path, adapter: PlatformAdapter, *, plan_ref: str) -> dict[str, Any]:
    content = package.content if isinstance(package.content, dict) else {}
    return {
        "adapter": adapter.key,
        "release_package_id": package.id,
        "release_package_path": str(package_file),
        "release_version": content.get("release_version", ""),
        "title_candidates": content.get("title_candidates", []),
        "summary": content.get("summary", ""),
        "tags": content.get("tags", []),
        "channel": content.get("channel", adapter.key),
        "draft_path": content.get("draft_path", ""),
        "publish_gate_report_path": content.get("publish_gate_report_path", ""),
        "platform_rules": content.get("platform_rules", {}),
        "publishing_plan_path": plan_ref,
        "manual_checklist": [
            "confirm publish gate status is ready",
            "confirm originality report is acceptable",
            "copy title/summary/tags into the platform",
            "paste final draft from the referenced release package",
            "record external URL after publishing",
        ],
    }


def _call_external_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.environ.get("NOVEL_FORGE_PUBLISH_WEBHOOK_URL", "")
    if not endpoint:
        raise ValueError("NOVEL_FORGE_PUBLISH_WEBHOOK_URL is required for external_webhook execution")
    if not _external_publish_allowed():
        raise ValueError("external publishing is disabled; set NOVEL_FORGE_ALLOW_EXTERNAL_PUBLISH=true to execute")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=10) as response:  # nosec - endpoint is explicit local operator config.
        return {"status": "sent", "status_code": response.status, "message": response.read(512).decode("utf-8", errors="replace")}


def _external_publish_allowed() -> bool:
    return os.environ.get("NOVEL_FORGE_ALLOW_EXTERNAL_PUBLISH", "").lower() in {"1", "true", "yes"}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
