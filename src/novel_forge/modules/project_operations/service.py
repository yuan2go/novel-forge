from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.storage.local import LocalStorage

PROFILE_KEYS = (
    "platform_profile_path",
    "genre_market_profile_path",
    "quality_standard_profile_path",
    "style_profile_path",
    "continuity_bible_path",
)


def project_operating_dashboard(storage: LocalStorage, *, limit: int = 20) -> dict[str, Any]:
    projects = _project_rows(storage)
    asset_rows = _asset_rows(storage)
    task_rows = [row for row in asset_rows if row["type"] == "task_status"]
    handoff_rows = [row for row in asset_rows if row["type"] == "claude_code_handoff"]
    scored = [
        _operating_row(
            project,
            asset_rows=[row for row in asset_rows if row["project_id"] == project["project_id"]],
            task_rows=[row for row in task_rows if row["project_id"] == project["project_id"]],
            handoff_rows=[row for row in handoff_rows if row["project_id"] == project["project_id"]],
        )
        for project in projects
    ]
    scored.sort(key=lambda item: (item["today_priority_rank"], -item["investment_score"], item["title"]))
    return {
        "summary": {
            "project_count": len(projects),
            "active_project_count": len([item for item in scored if item["status"] == "active"]),
            "high_risk_project_count": len([item for item in scored if item["risk_score"] >= 60]),
            "blocked_project_count": len([item for item in scored if item["bottleneck"]["severity"] == "blocking"]),
            "average_investment_score": round(sum(item["investment_score"] for item in scored) / len(scored), 1) if scored else 0,
        },
        "projects": scored[: max(1, int(limit))],
        "today_priorities": [
            _priority_card(item)
            for item in scored
            if item["today_action"]["action"] != "observe"
        ][:8],
        "bottlenecks": [
            {
                "project_id": item["project_id"],
                "title": item["title"],
                **item["bottleneck"],
            }
            for item in scored
            if item["bottleneck"]["severity"] != "none"
        ][:8],
    }


def _operating_row(
    project: dict[str, Any],
    *,
    asset_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    handoff_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    config = project["project_config"]
    binding_count = len([key for key in PROFILE_KEYS if config.get(key)])
    draft_count = len([row for row in asset_rows if row["type"] in {"draft_chapter", "draft_version"}])
    review_count = len([row for row in asset_rows if row["type"] in {"review_report", "chapter_audit_report"}])
    failed_task_count = len([row for row in task_rows if _task_status(row["data"]) in {"failed", "dead_letter"}])
    running_task_count = len([row for row in task_rows if _task_status(row["data"]) in {"running", "queued", "pending"}])
    pending_handoff_count = len([row for row in handoff_rows if _handoff_status(row["data"]) in {"pending", "waiting_human", "waiting_handoff"}])
    open_issue_count = int(project.get("open_issue_count", 0) or 0)
    chapter_count = int(project.get("chapter_count", 0) or 0)
    asset_count = len(asset_rows)
    profile_gap = len(PROFILE_KEYS) - binding_count
    risk_score = _clamp(profile_gap * 10 + failed_task_count * 16 + pending_handoff_count * 9 + open_issue_count * 7)
    momentum_score = _clamp(min(asset_count, 80) * 0.6 + min(chapter_count, 80) * 2 + review_count * 2 + running_task_count * 3)
    investment_score = _clamp(35 + binding_count * 9 + momentum_score * 0.45 - risk_score * 0.35)
    bottleneck = _bottleneck(profile_gap, failed_task_count, pending_handoff_count, open_issue_count, draft_count, chapter_count)
    today_action = _today_action(profile_gap, failed_task_count, pending_handoff_count, open_issue_count, draft_count, review_count, chapter_count)
    return {
        "project_id": project["project_id"],
        "path": project["path"],
        "title": project["title"],
        "status": project["status"],
        "series_title": project.get("series_title", ""),
        "chapter_count": chapter_count,
        "asset_count": asset_count,
        "draft_count": draft_count,
        "review_count": review_count,
        "profile_binding_count": binding_count,
        "profile_binding_total": len(PROFILE_KEYS),
        "missing_profiles": [key for key in PROFILE_KEYS if not config.get(key)],
        "risk_score": int(round(risk_score)),
        "momentum_score": int(round(momentum_score)),
        "investment_score": int(round(investment_score)),
        "open_issue_count": open_issue_count,
        "failed_task_count": failed_task_count,
        "pending_handoff_count": pending_handoff_count,
        "bottleneck": bottleneck,
        "today_action": today_action,
        "today_priority_rank": _priority_rank(today_action["action"], risk_score, investment_score),
        "updated_at": project.get("updated_at", ""),
    }


def _project_rows(storage: LocalStorage) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json("workspaces"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "project_workspace_state":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        config = content.get("project_config", {}) if isinstance(content.get("project_config", {}), dict) else {}
        if config.get("status") == "deleted":
            continue
        chapter_states = content.get("chapter_states", []) if isinstance(content.get("chapter_states", []), list) else []
        open_issues = content.get("open_issues", []) if isinstance(content.get("open_issues", []), list) else []
        rows.append(
            {
                "project_id": str(content.get("project_id") or data.get("id", "")),
                "path": _display_path(storage.root, path),
                "title": str(data.get("title") or data.get("name") or ""),
                "status": str(config.get("status") or "active"),
                "series_title": str(content.get("memory", {}).get("series_title", "") if isinstance(content.get("memory", {}), dict) else ""),
                "chapter_count": len(chapter_states),
                "open_issue_count": len(open_issues),
                "project_config": config,
                "updated_at": str(data.get("updated_at", "")),
            }
        )
    return rows


def _asset_rows(storage: LocalStorage) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            rows.append(
                {
                    "path": _display_path(storage.root, path),
                    "type": str(data.get("type", "")),
                    "project_id": str(metadata.get("project_id") or content.get("project_id") or ""),
                    "updated_at": str(data.get("updated_at", "")),
                    "data": data,
                }
            )
    return rows


def _bottleneck(profile_gap: int, failed_tasks: int, pending_handoffs: int, open_issues: int, draft_count: int, chapter_count: int) -> dict[str, str]:
    if failed_tasks:
        return {"severity": "blocking", "kind": "failed_tasks", "label": "失败任务阻塞", "suggestion": "进入任务中心恢复失败步骤。"}
    if pending_handoffs:
        return {"severity": "high", "kind": "waiting_handoff", "label": "Handoff 等待验收", "suggestion": "完成 Claude Code/Codex 输出绑定。"}
    if profile_gap:
        return {"severity": "high", "kind": "missing_profiles", "label": "项目配置未绑定完整", "suggestion": "补齐平台、题材、精品标准、文风和连续性设定。"}
    if open_issues >= 3:
        return {"severity": "medium", "kind": "open_issues", "label": "开放问题过多", "suggestion": "先处理设定/审稿问题再继续生成。"}
    if not draft_count and chapter_count:
        return {"severity": "medium", "kind": "needs_draft", "label": "有计划但缺稿件", "suggestion": "构建上下文并生成下一章。"}
    return {"severity": "none", "kind": "none", "label": "无明显阻塞", "suggestion": "可推进下一生产步骤。"}


def _today_action(profile_gap: int, failed_tasks: int, pending_handoffs: int, open_issues: int, draft_count: int, review_count: int, chapter_count: int) -> dict[str, str]:
    if failed_tasks:
        return {"action": "recover_task", "label": "恢复失败任务", "href": "/tasks", "reason": "失败任务会阻断生产链。"}
    if pending_handoffs:
        return {"action": "accept_handoff", "label": "完成 Handoff 验收", "href": "/handoffs", "reason": "拆解/知识产物等待人工确认。"}
    if profile_gap:
        return {"action": "bind_profiles", "label": "补齐项目配置", "href": "/projects", "reason": "缺少 profile 会降低生成和审稿稳定性。"}
    if open_issues >= 3:
        return {"action": "resolve_issues", "label": "处理开放问题", "href": "/impact", "reason": "开放问题过多，继续生成会放大风险。"}
    if not chapter_count:
        return {"action": "create_outline", "label": "启动大纲/细纲", "href": "/production?stage=outline", "reason": "项目还没有进入章节生产。"}
    if not draft_count:
        return {"action": "generate_draft", "label": "生成下一章", "href": "/manuscript", "reason": "已有章节计划，需要推进正文。"}
    if review_count < draft_count:
        return {"action": "review_draft", "label": "审稿最新章节", "href": "/review", "reason": "草稿多于审稿，质量门禁滞后。"}
    return {"action": "observe", "label": "观察并推进", "href": "/control", "reason": "当前项目可按生产总控继续推进。"}


def _priority_rank(action: str, risk_score: float, investment_score: float) -> int:
    order = {
        "recover_task": 1,
        "accept_handoff": 2,
        "bind_profiles": 3,
        "resolve_issues": 4,
        "review_draft": 5,
        "generate_draft": 6,
        "create_outline": 7,
        "observe": 8,
    }
    return order.get(action, 9) * 100 - int(investment_score) + int(risk_score)


def _priority_card(item: dict[str, Any]) -> dict[str, Any]:
    action = item["today_action"]
    return {
        "project_id": item["project_id"],
        "title": item["title"],
        "action": action["action"],
        "label": action["label"],
        "reason": action["reason"],
        "href": action["href"],
        "risk_score": item["risk_score"],
        "investment_score": item["investment_score"],
        "bottleneck": item["bottleneck"]["label"],
    }


def _task_status(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return str(content.get("status", ""))


def _handoff_status(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return str(content.get("status") or metadata.get("handoff_status") or metadata.get("asset_status") or "")


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
