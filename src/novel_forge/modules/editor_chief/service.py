from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.canon_graph import reason_canon_graph
from novel_forge.modules.longform_stability import longform_stability_dashboard
from novel_forge.modules.publishing import list_publishing_assets
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.storage.local import LocalStorage

EDITOR_CHIEF_ASSET_TYPES = {
    "arc_plan",
    "canon_database",
    "canon_graph_snapshot",
    "chapter_pattern_report",
    "chapter_state",
    "character_card",
    "character_state_ledger",
    "foreshadowing_graph",
    "foreshadowing_thread",
    "longform_recap_report",
    "motif_budget_report",
    "platform_adapter_report",
    "platform_retention_risk",
    "platform_strategy_pack",
    "publish_gate_report",
    "reader_fatigue_report",
    "release_package",
    "review_issue",
    "revision_task",
    "world_bible",
}

ACTIVE_REVIEW_ISSUE_STATUSES = {"open", "acknowledged", "in_revision"}


def build_editor_chief_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Build a read-only editor-in-chief governance snapshot.

    The console is intentionally a decision aggregation layer. It reads Canon,
    Character, Arc, Foreshadowing, ReviewIssue, Longform, Loop/Agent-adjacent,
    Publish and Platform Strategy evidence without mutating project state.
    """

    storage.ensure_layout()
    normalized_limit = max(50, min(2000, int(limit or 500)))
    assets = _asset_rows(storage, project_id=project_id, workspace_path=workspace_path, asset_types=EDITOR_CHIEF_ASSET_TYPES, limit=normalized_limit)
    counts = _count_by_type(assets)
    current_chapter = _current_chapter(assets)
    longform = _safe_longform_dashboard(storage, project_id=project_id, workspace_path=workspace_path, limit=min(normalized_limit, 500))
    canon_reasoning = _safe_canon_reasoning(storage, project_id=project_id, workspace_path=workspace_path, current_chapter=current_chapter)
    review_rows = list_review_issues(storage, project_id=project_id, limit=normalized_limit)
    active_issues = [row for row in review_rows if str(_content(row).get("status") or "open") in ACTIVE_REVIEW_ISSUE_STATUSES]
    blocking_issues = [row for row in active_issues if bool(_content(row).get("blocking"))]
    revision_tasks = _active_revision_tasks(assets)
    publishing_assets = list_publishing_assets(storage, project_id=project_id, limit=100)
    governance = _safe_governance_summary(storage, project_id=project_id)

    arc_progress = _arc_progress_section(assets, canon_reasoning=canon_reasoning, current_chapter=current_chapter, review_issues=active_issues)
    character_drift = _character_drift_section(assets, review_issues=active_issues)
    foreshadowing = _foreshadowing_section(assets, current_chapter=current_chapter, review_issues=active_issues)
    fatigue = _recent_fatigue_section(assets, current_chapter=current_chapter)
    publish_fit = _publish_fit_section(assets, publishing_assets=publishing_assets, blocking_issues=blocking_issues)
    next_strategy = _next_10_chapter_strategy(
        assets,
        current_chapter=current_chapter,
        arc_progress=arc_progress,
        character_drift=character_drift,
        foreshadowing=foreshadowing,
        fatigue=fatigue,
        blocking_issues=blocking_issues,
    )
    health = _overall_health(
        longform=longform,
        canon_reasoning=canon_reasoning,
        blocking_issues=blocking_issues,
        active_issues=active_issues,
        arc_progress=arc_progress,
        character_drift=character_drift,
        foreshadowing=foreshadowing,
        fatigue=fatigue,
        publish_fit=publish_fit,
        counts=counts,
    )
    decision = _executive_decision(health=health, publish_fit=publish_fit, blocking_issues=blocking_issues)
    return {
        "status": "ready",
        "generated_at": utc_now(),
        "project": _project_summary(storage, project_id=project_id, workspace_path=workspace_path),
        "executive_decision": decision,
        "overall_health": health,
        "arc_progress": arc_progress,
        "character_drift": character_drift,
        "foreshadowing": foreshadowing,
        "recent_fatigue": fatigue,
        "next_10_chapter_strategy": next_strategy,
        "blocking_repair_queue": _blocking_repair_queue(blocking_issues, revision_tasks),
        "publish_and_platform_fit": publish_fit,
        "governance_loop": governance,
        "source_dashboards": {
            "longform_stability": {
                "summary": longform.get("summary", {}),
                "acceptance": longform.get("acceptance", {}),
            },
            "canon_graph": canon_reasoning,
        },
        "control_links": _control_links(),
        "evidence": {
            "counts_by_type": counts,
            "recent_assets": [_asset_summary(row) for row in assets[:60]],
            "publishing_assets": publishing_assets[:20],
        },
    }


def _safe_longform_dashboard(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None, limit: int) -> dict[str, Any]:
    try:
        return longform_stability_dashboard(storage, project_id=project_id, workspace_path=workspace_path, limit=limit)
    except Exception as exc:
        return {"summary": {"acceptance_status": "unknown", "acceptance_score": 0}, "acceptance": {"status": "unknown", "checks": [], "recommendations": [str(exc)]}}


def _safe_canon_reasoning(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None, current_chapter: int) -> dict[str, Any]:
    try:
        return reason_canon_graph(
            storage,
            {
                "project_id": project_id or "",
                "workspace_path": workspace_path or "",
                "current_chapter": current_chapter or None,
                "persist_snapshot": False,
            },
        )
    except Exception as exc:
        return {"status": "unknown", "reasoning": {"issue_count": 0, "blocking_issue_count": 0, "issues": [], "obligations": []}, "summary": {}, "error": str(exc)}


def _safe_governance_summary(storage: LocalStorage, *, project_id: str | None) -> dict[str, Any]:
    try:
        from novel_forge.modules.agent_registry import agent_registry_coverage
        from novel_forge.modules.audit_log import audit_chain_summary
        from novel_forge.modules.clickhouse_analytics import agent_metrics, analytics_capabilities, evaluation_metrics
        from novel_forge.modules.evaluation_center import list_model_evaluation_assets
        from novel_forge.modules.pgvector_store import pgvector_capabilities

        evaluation_rows = list_model_evaluation_assets(storage, project_id=project_id, limit=200)
        return {
            "agent_registry": agent_registry_coverage(storage),
            "audit": audit_chain_summary(storage, project_id=project_id or ""),
            "evaluation": {
                "asset_count": len(evaluation_rows),
                "blocked_count": sum(1 for row in evaluation_rows if row.get("recommendation") == "block" or row.get("blocking")),
                "metrics": evaluation_metrics(storage, project_id=project_id or ""),
            },
            "analytics": {
                "capabilities": analytics_capabilities(storage, project_id=project_id or ""),
                "agent_metrics": agent_metrics(storage, project_id=project_id or ""),
            },
            "retrieval": pgvector_capabilities(storage, project_id=project_id or ""),
            "status": "ready",
        }
    except Exception as exc:
        return {"status": "unknown", "error": str(exc)}


def _overall_health(
    *,
    longform: dict[str, Any],
    canon_reasoning: dict[str, Any],
    blocking_issues: list[dict[str, Any]],
    active_issues: list[dict[str, Any]],
    arc_progress: dict[str, Any],
    character_drift: dict[str, Any],
    foreshadowing: dict[str, Any],
    fatigue: dict[str, Any],
    publish_fit: dict[str, Any],
    counts: dict[str, int],
) -> dict[str, Any]:
    summary = longform.get("summary", {}) if isinstance(longform.get("summary", {}), dict) else {}
    base_score = _int(summary.get("acceptance_score"), default=60)
    canon_reason = canon_reasoning.get("reasoning", {}) if isinstance(canon_reasoning.get("reasoning", {}), dict) else {}
    active_high = [row for row in active_issues if _severity_rank(str(_content(row).get("severity") or "")) >= _severity_rank("high")]
    evidence_gap_penalty = sum(10 for key in ["canon_database", "arc_plan"] if counts.get(key, 0) == 0)
    penalty = (
        len(blocking_issues) * 14
        + len(active_high) * 6
        + _int(canon_reason.get("blocking_issue_count")) * 10
        + _section_penalty(arc_progress)
        + _section_penalty(character_drift)
        + _section_penalty(foreshadowing)
        + _section_penalty(fatigue)
        + (14 if publish_fit.get("status") == "blocked" else 0)
        + evidence_gap_penalty
    )
    score = _clamp(base_score - penalty, 0, 100)
    risk_level = "critical" if blocking_issues or publish_fit.get("status") == "blocked" or canon_reasoning.get("status") == "blocked" else "high" if score < 70 else "medium" if score < 85 else "low"
    return {
        "quality_score": score,
        "risk_level": risk_level,
        "acceptance_status": summary.get("acceptance_status", longform.get("acceptance", {}).get("status", "unknown")),
        "active_issue_count": len(active_issues),
        "blocking_issue_count": len(blocking_issues),
        "canon_issue_count": _int(canon_reason.get("issue_count")),
        "evidence_gap_count": sum(1 for key in ["canon_database", "arc_plan", "character_state_ledger", "foreshadowing_graph"] if counts.get(key, 0) == 0),
        "headline": _health_headline(score, risk_level, len(blocking_issues)),
    }


def _executive_decision(*, health: dict[str, Any], publish_fit: dict[str, Any], blocking_issues: list[dict[str, Any]]) -> dict[str, Any]:
    score = _int(health.get("quality_score"))
    risk = str(health.get("risk_level") or "unknown")
    if blocking_issues or risk == "critical":
        decision = "pause_for_revision"
        summary = "需暂停主链生产，先处理阻断问题和对应 RevisionTask。"
    elif bool(publish_fit.get("can_publish")) and score >= 80:
        decision = "ready_to_publish"
        summary = "当前可进入发布门禁后的发布准备。"
    elif risk in {"high", "medium"}:
        decision = "continue_with_caution"
        summary = "可继续生产，但下一批章节需要按总编策略收束风险。"
    else:
        decision = "continue_production"
        summary = "当前健康，可以继续生产。"
    return {
        "decision": decision,
        "summary": summary,
        "can_continue": decision in {"continue_production", "continue_with_caution", "ready_to_publish"},
        "must_pause": decision == "pause_for_revision",
        "can_publish": decision == "ready_to_publish",
        "quality_score": score,
        "risk_level": risk,
    }


def _arc_progress_section(assets: list[dict[str, Any]], *, canon_reasoning: dict[str, Any], current_chapter: int, review_issues: list[dict[str, Any]]) -> dict[str, Any]:
    arc_rows = _rows_of_type(assets, "arc_plan")
    chapter_states = _rows_of_type(assets, "chapter_state")
    reason = canon_reasoning.get("reasoning", {}) if isinstance(canon_reasoning.get("reasoning", {}), dict) else {}
    canon_issues = reason.get("issues", []) if isinstance(reason.get("issues", []), list) else []
    issue_rows = [row for row in review_issues if str(_content(row).get("issue_type")) in {"canon_conflict", "plot_logic_gap"}]
    alerts = []
    for item in canon_issues[:8]:
        if isinstance(item, dict):
            alerts.append({"source": "canon_graph", "severity": item.get("severity", "high"), "message": item.get("message") or item.get("reason_type", "")})
    for row in issue_rows[:8]:
        content = _content(row)
        alerts.append({"source": "review_issue", "severity": content.get("severity", ""), "message": content.get("message", ""), "path": row.get("path", "")})
    status = "blocked" if any(_severity_rank(str(item.get("severity"))) >= _severity_rank("high") for item in alerts) else "warning" if not arc_rows else "healthy"
    latest_arc = _latest_by_chapter_or_updated(arc_rows)
    active_arc_names = _dedupe([str(_content(row).get("active_arc") or "") for row in chapter_states if str(_content(row).get("active_arc") or "").strip()])
    return {
        "status": status,
        "progress_score": _clamp(100 - len(alerts) * 12 - (15 if not arc_rows else 0), 0, 100),
        "current_chapter": current_chapter,
        "arc_plan_count": len(arc_rows),
        "chapter_state_count": len(chapter_states),
        "active_arc": active_arc_names[-1] if active_arc_names else _content(latest_arc).get("title", latest_arc.get("title", "")),
        "drift_alerts": alerts[:12],
        "latest_arc_plan": _asset_summary(latest_arc) if latest_arc else {},
    }


def _character_drift_section(assets: list[dict[str, Any]], *, review_issues: list[dict[str, Any]]) -> dict[str, Any]:
    ledgers = _rows_of_type(assets, "character_state_ledger")
    issue_rows = [row for row in review_issues if str(_content(row).get("issue_type")) == "character_drift"]
    total_liabilities = 0
    total_remaining_debt = 0
    character_states: list[dict[str, Any]] = []
    for ledger in ledgers[:20]:
        for character in _content(ledger).get("characters", []) if isinstance(_content(ledger).get("characters", []), list) else []:
            if not isinstance(character, dict):
                continue
            debt = character.get("debt_ledger", {}) if isinstance(character.get("debt_ledger", {}), dict) else {}
            liabilities = debt.get("new_liabilities", []) if isinstance(debt.get("new_liabilities", []), list) else []
            total_liabilities += len(liabilities)
            total_remaining_debt += _int(debt.get("remaining"))
            character_states.append(
                {
                    "character_id": character.get("character_id", ""),
                    "canonical_name": character.get("canonical_name", character.get("character_id", "")),
                    "status": character.get("status", ""),
                    "active_burdens": character.get("active_burdens", []),
                    "risk_count": len(character.get("risks", [])) if isinstance(character.get("risks", []), list) else 0,
                    "remaining_debt": debt.get("remaining", 0),
                }
            )
    status = "blocked" if any(_severity_rank(str(_content(row).get("severity"))) >= _severity_rank("high") for row in issue_rows) else "warning" if total_liabilities >= 4 else "healthy"
    return {
        "status": status,
        "drift_issue_count": len(issue_rows),
        "ledger_count": len(ledgers),
        "liability_count": total_liabilities,
        "remaining_debt_total": total_remaining_debt,
        "characters": character_states[:12],
        "drift_alerts": [_issue_summary(row) for row in issue_rows[:12]],
    }


def _foreshadowing_section(assets: list[dict[str, Any]], *, current_chapter: int, review_issues: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [*_rows_of_type(assets, "foreshadowing_graph"), *_rows_of_type(assets, "foreshadowing_thread")]
    dropped = 0
    open_count = 0
    expired = 0
    clues: list[dict[str, Any]] = []
    graph_issues: list[dict[str, Any]] = []
    for row in rows[:50]:
        content = _content(row)
        for issue in content.get("issues", []) if isinstance(content.get("issues", []), list) else []:
            if isinstance(issue, dict):
                graph_issues.append({"source": row.get("path", ""), **issue})
        for clue in content.get("clues", []) if isinstance(content.get("clues", []), list) else []:
            if not isinstance(clue, dict):
                continue
            status = str(clue.get("status") or "active").lower()
            planned = _int(clue.get("planned_payoff_chapter") or clue.get("due_chapter") or clue.get("payoff_chapter"))
            if status in {"dropped", "drop", "失效"}:
                dropped += 1
            elif status not in {"resolved", "closed", "paid_off", "recovered", "回收"}:
                open_count += 1
                if planned and current_chapter and planned < current_chapter:
                    expired += 1
            clues.append({"name": clue.get("name") or clue.get("clue_id", ""), "status": status, "planned_payoff_chapter": planned, "target_truth": clue.get("target_truth", "")})
    issue_rows = [row for row in review_issues if str(_content(row).get("issue_type")) == "foreshadowing_drop"]
    status = "blocked" if dropped or expired or issue_rows else "warning" if not rows else "healthy"
    return {
        "status": status,
        "graph_count": len(rows),
        "open_clue_count": open_count,
        "dropped_clue_count": dropped,
        "expired_clue_count": expired,
        "issue_count": len(graph_issues) + len(issue_rows),
        "clues": clues[:20],
        "alerts": [*graph_issues[:8], *[_issue_summary(row) for row in issue_rows[:8]]],
    }


def _recent_fatigue_section(assets: list[dict[str, Any]], *, current_chapter: int) -> dict[str, Any]:
    recent = [row for row in assets if _chapter(row) and (not current_chapter or _chapter(row) >= current_chapter - 9)]
    pattern_reports = [row for row in recent if row.get("type") == "chapter_pattern_report"]
    motif_reports = [row for row in recent if row.get("type") == "motif_budget_report"]
    fatigue_reports = [row for row in recent if row.get("type") == "reader_fatigue_report"]
    pattern_high = sum(1 for row in pattern_reports for issue in _list(_content(row).get("similarity_checks")) if isinstance(issue, dict) and _severity_rank(str(issue.get("severity"))) >= _severity_rank("high"))
    motif_high = sum(1 for row in motif_reports for issue in _list(_content(row).get("issues")) if isinstance(issue, dict) and _severity_rank(str(issue.get("severity"))) >= _severity_rank("high"))
    fatigue_scores = [_int(_content(row).get("fatigue_score")) for row in fatigue_reports]
    high_fatigue = sum(1 for row in fatigue_reports if str(_content(row).get("risk")) == "high" or _int(_content(row).get("fatigue_score")) >= 80)
    status = "blocked" if pattern_high or motif_high or high_fatigue else "warning" if not pattern_reports and not motif_reports and current_chapter >= 3 else "healthy"
    return {
        "status": status,
        "window": f"{max(1, current_chapter - 9)}-{current_chapter}" if current_chapter else "latest-10",
        "pattern_high_count": pattern_high,
        "motif_high_count": motif_high,
        "high_fatigue_count": high_fatigue,
        "average_fatigue_score": round(sum(fatigue_scores) / max(1, len(fatigue_scores))),
        "pattern_report_count": len(pattern_reports),
        "motif_report_count": len(motif_reports),
        "fatigue_report_count": len(fatigue_reports),
        "alerts": [_asset_summary(row) for row in [*pattern_reports, *motif_reports, *fatigue_reports][:12]],
    }


def _publish_fit_section(assets: list[dict[str, Any]], *, publishing_assets: list[dict[str, Any]], blocking_issues: list[dict[str, Any]]) -> dict[str, Any]:
    gate_rows = [row for row in [*_rows_of_type(assets, "publish_gate_report"), *publishing_assets] if row.get("type") == "publish_gate_report"]
    release_rows = [row for row in [*_rows_of_type(assets, "release_package"), *publishing_assets] if row.get("type") == "release_package"]
    platform_report = _latest_by_chapter_or_updated(_rows_of_type(assets, "platform_adapter_report"))
    retention_risk = _latest_by_chapter_or_updated(_rows_of_type(assets, "platform_retention_risk"))
    strategy_pack = _latest_by_chapter_or_updated(_rows_of_type(assets, "platform_strategy_pack"))
    latest_gate = _latest_by_chapter_or_updated(gate_rows)
    gate_decision = str(_content(latest_gate).get("decision") or latest_gate.get("decision") or latest_gate.get("status") or "")
    latest_release = _latest_by_chapter_or_updated(release_rows)
    release_status = str(_content(latest_release).get("status") or latest_release.get("status") or "")
    platform_status = str(_content(platform_report).get("status") or _content(retention_risk).get("risk_level") or "")
    blocked = gate_decision in {"blocked", "fail", "failed"} or bool(blocking_issues)
    can_publish = not blocked and (gate_decision in {"ready", "passed", "pass"} or release_status == "ready")
    status = "blocked" if blocked else "ready" if can_publish else "not_ready"
    return {
        "status": status,
        "can_publish": can_publish,
        "latest_gate_decision": gate_decision or "-",
        "release_status": release_status or "-",
        "platform_fit_status": platform_status or "unknown",
        "target_platform": _content(strategy_pack).get("platform_name") or _content(strategy_pack).get("platform_id") or "",
        "gate": _asset_summary(latest_gate) if latest_gate else {},
        "release_package": _asset_summary(latest_release) if latest_release else {},
        "platform_strategy_pack": _asset_summary(strategy_pack) if strategy_pack else {},
        "blocking_issue_count": len(blocking_issues),
    }


def _next_10_chapter_strategy(
    assets: list[dict[str, Any]],
    *,
    current_chapter: int,
    arc_progress: dict[str, Any],
    character_drift: dict[str, Any],
    foreshadowing: dict[str, Any],
    fatigue: dict[str, Any],
    blocking_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    strategy_pack = _latest_by_chapter_or_updated(_rows_of_type(assets, "platform_strategy_pack"))
    chapter_strategy = _content(strategy_pack).get("chapter_strategy", {}) if isinstance(_content(strategy_pack).get("chapter_strategy", {}), dict) else {}
    pillars = []
    if arc_progress.get("status") != "healthy":
        pillars.append("先让主线问题重新变成每章目标，不扩写无关支线。")
    if character_drift.get("status") != "healthy":
        pillars.append("冻结人物新负债，优先兑现动机、代价和关系选择。")
    if foreshadowing.get("status") != "healthy":
        pillars.append("清点未回收伏笔，未来 10 章至少回收或重绑定过期线索。")
    if fatigue.get("status") != "healthy":
        pillars.append("降低重复调查/重复意象，安排不同功能章节和新的冲突入口。")
    if not pillars:
        pillars.append("维持当前主线节奏，每章保留目标推进、角色选择和结尾钩子。")
    return {
        "chapter_range": {"from": current_chapter + 1 if current_chapter else 1, "to": current_chapter + 10 if current_chapter else 10},
        "target_platform": _content(strategy_pack).get("platform_name") or _content(strategy_pack).get("platform_id") or "",
        "platform_beats": chapter_strategy.get("beat_cadence", []),
        "required_beats": chapter_strategy.get("required_beats", []),
        "editorial_pillars": pillars,
        "must_fix_before_next_batch": [_issue_summary(row) for row in blocking_issues[:8]],
        "do_not": [
            "不要绕过 blocking ReviewIssue 直接进入 canonical chapter。",
            "不要新增未绑定 target_truth 的伏笔。",
            "不要用同一调查动作连续填充多章。",
        ],
    }


def _blocking_repair_queue(blocking_issues: list[dict[str, Any]], revision_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "blocking_issue_count": len(blocking_issues),
        "revision_task_count": len(revision_tasks),
        "issues": [_issue_summary(row) for row in blocking_issues[:20]],
        "revision_tasks": [_asset_summary(row) for row in revision_tasks[:20]],
    }


def _asset_rows(
    storage: LocalStorage,
    *,
    project_id: str | None,
    workspace_path: str | None,
    asset_types: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in reversed(storage.list_json(category)):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or str(data.get("type", "")) not in asset_types:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            row_project = str(metadata.get("project_id") or content.get("project_id") or "")
            row_workspace = str(metadata.get("workspace_path") or content.get("workspace_path") or "")
            if project_id and row_project and row_project != project_id:
                continue
            if workspace_path and row_workspace and row_workspace != workspace_path:
                continue
            rows.append(_row(storage.root, path, data))
            if len(rows) >= limit:
                return _sort_rows(rows)
    return _sort_rows(rows)


def _row(root: Path, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": _display_path(root, path),
        "id": str(data.get("id", "")),
        "type": str(data.get("type", "")),
        "title": str(data.get("title", "")),
        "content": content,
        "metadata": metadata,
        "status": str(content.get("status") or content.get("recommendation") or content.get("decision") or metadata.get("asset_status") or ""),
        "decision": str(content.get("decision") or ""),
        "chapter": _chapter({"content": content}),
        "updated_at": str(data.get("updated_at") or metadata.get("created_at") or content.get("created_at") or ""),
    }


def _project_summary(storage: LocalStorage, *, project_id: str | None, workspace_path: str | None) -> dict[str, Any]:
    if workspace_path:
        try:
            data = storage.read_json(storage.root / workspace_path)
            content = _content(data)
            memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
            return {"project_id": content.get("project_id", project_id or ""), "workspace_path": workspace_path, "title": data.get("title") or memory.get("project_title", "")}
        except Exception:
            pass
    for path in storage.list_json("workspaces"):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        content = _content(data)
        if project_id and str(content.get("project_id") or "") != project_id:
            continue
        if workspace_path and _display_path(storage.root, path) != workspace_path:
            continue
        if project_id or workspace_path:
            memory = content.get("memory", {}) if isinstance(content.get("memory", {}), dict) else {}
            return {"project_id": content.get("project_id", ""), "workspace_path": _display_path(storage.root, path), "title": data.get("title") or memory.get("project_title", "")}
    return {"project_id": project_id or "", "workspace_path": workspace_path or "", "title": "全部项目" if not project_id and not workspace_path else ""}


def _active_revision_tasks(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in _rows_of_type(assets, "revision_task") if str(_content(row).get("status") or row.get("status") or "open") not in {"resolved", "closed", "waived"}]


def _rows_of_type(assets: list[dict[str, Any]], asset_type: str) -> list[dict[str, Any]]:
    return [row for row in assets if row.get("type") == asset_type]


def _latest_by_chapter_or_updated(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(rows, key=lambda row: (_chapter(row), str(row.get("updated_at") or ""), str(row.get("path") or "")), reverse=True)[0] if rows else {}


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (str(row.get("updated_at") or ""), str(row.get("path") or "")), reverse=True)


def _content(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _chapter(row: dict[str, Any]) -> int:
    content = _content(row)
    for key in ["chapter_no", "chapter", "source_chapter"]:
        value = _int(content.get(key))
        if value:
            return value
    return _int(row.get("chapter"))


def _current_chapter(assets: list[dict[str, Any]]) -> int:
    return max([_chapter(row) for row in assets] or [0])


def _count_by_type(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("type", ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _asset_summary(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "id": row.get("id", ""),
        "path": row.get("path", ""),
        "type": row.get("type", ""),
        "title": row.get("title", ""),
        "chapter": _chapter(row),
        "status": row.get("status", ""),
        "decision": row.get("decision", ""),
    }


def _issue_summary(row: dict[str, Any]) -> dict[str, Any]:
    content = _content(row)
    return {
        "issue_id": content.get("issue_id", row.get("id", "")),
        "issue_type": content.get("issue_type", ""),
        "severity": content.get("severity", ""),
        "blocking": bool(content.get("blocking")),
        "status": content.get("status", ""),
        "message": content.get("message", row.get("title", "")),
        "fix_suggestion": content.get("fix_suggestion", ""),
        "path": row.get("path", ""),
    }


def _section_penalty(section: dict[str, Any]) -> int:
    status = str(section.get("status") or "")
    return 12 if status == "blocked" else 7 if status == "warning" else 0


def _health_headline(score: int, risk_level: str, blocking_count: int) -> str:
    if blocking_count:
        return "存在阻断问题，必须先修再继续主链。"
    if risk_level == "critical":
        return "系统处于高危状态，不建议继续生产。"
    if score >= 85:
        return "整体健康，允许继续生产。"
    if score >= 70:
        return "整体可控，但需要按下一阶段策略收束风险。"
    return "健康度不足，应先补齐治理证据和修订任务。"


def _severity_rank(value: str) -> int:
    return {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(str(value or "").lower(), 0)


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _control_links() -> dict[str, str]:
    return {
        "canon": "/canon-console",
        "character": "/character-console",
        "arc": "/arc-console",
        "foreshadowing": "/foreshadowing-console",
        "review_issues": "/review-issues",
        "longform_recap": "/longform-recap",
        "loop_runs": "/loop-runs",
        "agent_center": "/agent-center",
        "publish_gate": "/publish-gate",
        "platform_strategy": "/mkaos",
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
