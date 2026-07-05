from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import enforce_os_envelope, envelope_asset_metadata, is_production_environment, normalize_runtime_request_policy
from novel_forge.modules.production_context import build_production_context, filter_project_safe_references
from novel_forge.modules.publishing.publish_gate import (
    assert_publish_envelope_before_side_effect,
    asset_id,
    dedupe,
    display_path,
    publish_source_policy,
    read_asset_dict,
    related_review_issue_asset_ids,
)
from novel_forge.modules.publishing.release_gate import release_package_gate_evidence
from novel_forge.modules.review_issue import assert_no_blocking_review_issues
from novel_forge.schemas import ReleasePackage
from novel_forge.storage.local import LocalStorage


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
    from novel_forge.modules.publishing.publish_gate import create_publish_gate_report

    path = resolve_path(storage.root, draft_path)
    target = storage.read_asset(path)
    context = build_production_context(storage, target, input_path=path, workspace_path=workspace_path)
    project = context["project"]
    runtime_request = normalize_runtime_request_policy(
        envelope_payload=envelope,
        environment=environment,
        source_policy=publish_source_policy(source_policy),
        operation="publishing.release_package",
    )
    environment = str(runtime_request["environment"])
    envelope = runtime_request["envelope"] if runtime_request.get("envelope") else None
    resolved_source_policy = publish_source_policy(runtime_request["source_policy"])
    assert_publish_envelope_before_side_effect(
        storage,
        envelope=envelope,
        environment=environment,
        project_id=str(project.get("project_id", "")),
        asset_type="release_package",
        source_policy=resolved_source_policy,
        operation="publishing.release_package",
    )
    gate_path = (
        resolve_path(storage.root, publish_gate_path)
        if publish_gate_path
        else create_publish_gate_report(
            storage,
            path,
            workspace_path=workspace_path,
            human_override=human_override,
            envelope=envelope,
            environment=environment,
            source_policy=resolved_source_policy,
        )
    )
    gate = read_asset_dict(storage, gate_path)
    decision = gate.get("content", {}).get("decision", "blocked") if isinstance(gate.get("content", {}), dict) else "blocked"
    if decision == "blocked" and gate_has_mkaos_blocker(gate):
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
        related_asset_ids=related_review_issue_asset_ids(target.to_dict()),
        gate="release_package",
    )
    text = asset_text(target)
    release_version = make_id("release_version", f"{target.id}:{channel}:{utc_now()}")
    asset = ReleasePackage(
        title=f"Release package for {target.title}",
        source=target.id,
        tags=["release-package", str(channel or "local")],
        content={
            "release_version": release_version,
            "version_key": f"{target.id}:{release_version}",
            "target_asset_id": target.id,
            "publish_gate_report_id": asset_id(gate),
            "title_candidates": title_candidates(target.title, context),
            "summary": summary(text),
            "tags": release_tags(context, target),
            "metadata_optimization": publishing_metadata_optimization(target.title, text, context),
            "cover_asset": cover_asset_requirements(context, channel or "local"),
            "platform_review_feedback": {
                "status": "not_submitted",
                "feedback_source": "manual_or_webhook_adapter",
                "feedback_items": [],
                "回流说明": "平台审核反馈进入 publishing_log 后，再回流到审稿规则、章节计划和发布策略。",
            },
            "channel": channel or "local",
            "status": status,
            "draft_path": display_path(storage.root, path),
            "publish_gate_report_path": display_path(storage.root, Path(gate_path)),
            "platform_rules": release_platform_rules(context, channel or "local"),
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
                "draft_path": display_path(storage.root, path),
                "publish_gate_report_path": display_path(storage.root, Path(gate_path)),
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
        references=filter_project_safe_references(storage, str(project.get("project_id", "")), dedupe([target.id, asset_id(gate)])),
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
        run.succeed(output_assets=[display_path(storage.root, output)])
        return output


def gate_has_mkaos_blocker(gate: dict[str, Any]) -> bool:
    content = gate.get("content", {}) if isinstance(gate.get("content", {}), dict) else {}
    mkaos_risk = content.get("mkaos_risk", {}) if isinstance(content.get("mkaos_risk", {}), dict) else {}
    return bool(mkaos_risk.get("blocking"))


def release_platform_rules(context: dict[str, Any], channel: str) -> dict[str, Any]:
    project = context.get("project", {}) if isinstance(context.get("project", {}), dict) else {}
    config = project.get("project_config", {}) if isinstance(project.get("project_config", {}), dict) else {}
    return {
        "channel": channel,
        "target_platform": config.get("target_platform", channel),
        "require_chapter_audit": True,
        "require_originality_pass": True,
        "require_publish_gate_ready": True,
        "title_candidate_count": 3,
        "min_hook_score": config.get("publish_min_hook_score", 0.7),
        "max_risk_level": config.get("publish_max_risk_level", "medium"),
    }


def asset_text(asset: Any) -> str:
    data = asset.to_dict() if hasattr(asset, "to_dict") else asset
    content = data.get("content", {}) if isinstance(data, dict) and isinstance(data.get("content", {}), dict) else {}
    for key in ["text", "summary", "logline"]:
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(content, dict):
        return " ".join(str(value) for value in content.values() if isinstance(value, str))
    return str(data.get("title", "") if isinstance(data, dict) else "")


def title_candidates(title: str, context: dict[str, Any]) -> list[str]:
    project_title = str(context.get("project", {}).get("title", "") if isinstance(context.get("project", {}), dict) else "")
    base = title or project_title or "Untitled Chapter"
    return dedupe([base, f"{base} - publish draft", f"{project_title} {base}".strip()])


def summary(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:220] if compact else "No draft text available."


def release_tags(context: dict[str, Any], target: Any) -> list[str]:
    tags = ["release"]
    data = target.to_dict() if hasattr(target, "to_dict") else target
    if isinstance(data, dict):
        tags.extend(str(item) for item in data.get("tags", []) if str(item).strip())
    config = context.get("project_config", {}) if isinstance(context.get("project_config", {}), dict) else {}
    for key in ["genre", "target_platform"]:
        if config.get(key):
            tags.append(str(config[key]))
    return dedupe(tags)


def publishing_metadata_optimization(title: str, text: str, context: dict[str, Any]) -> dict[str, Any]:
    config = context.get("project_config", {}) if isinstance(context.get("project_config", {}), dict) else {}
    genre = str(config.get("genre") or "")
    target_platform = str(config.get("target_platform") or "")
    hook = summary(text)[:80]
    base = title or str(context.get("project", {}).get("title", "Untitled") if isinstance(context.get("project", {}), dict) else "Untitled")
    candidate_titles = dedupe(
        [
            base,
            f"{base}: {hook[:18]}",
            f"{genre}新章 - {base}".strip(" -"),
        ]
    )
    synopsis = summary(text)
    return {
        "title_candidates": candidate_titles[:5],
        "synopsis_candidates": [synopsis, f"{synopsis} 下一章将兑现当前悬念。"],
        "tag_candidates": dedupe([genre, target_platform, "原创", "连载", "章节钩子"])[:12],
        "hook_check": {"opening_signal": hook, "status": "needs_manual_review" if len(hook) < 12 else "ready"},
        "platform_notes": [
            "标题和简介只做本地建议，不自动提交外部平台。",
            "平台审核反馈需通过 publishing_log 或 adapter payload 回填。",
        ],
    }


def cover_asset_requirements(context: dict[str, Any], channel: str) -> dict[str, Any]:
    profiles = context.get("profiles", {}) if isinstance(context.get("profiles", {}), dict) else {}
    platform = profiles.get("platform_profile", {}) if isinstance(profiles.get("platform_profile", {}), dict) else {}
    content = platform.get("content", {}) if isinstance(platform.get("content", {}), dict) else {}
    return {
        "required": bool(content.get("cover_required", channel not in {"local", "manual"})),
        "status": "missing",
        "asset_path": "",
        "requirements": content.get("cover_requirements", {"safe_text": True, "no_infringing_source_art": True}),
    }
