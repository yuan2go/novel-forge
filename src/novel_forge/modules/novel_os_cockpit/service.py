from __future__ import annotations

from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.chapter_production_bus.service import V1_SEQUENCE_REQUIRED_OUTPUTS
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
    v1_artifact_coverage = _v1_artifact_coverage(rows)
    approval_gate_summary = _approval_gate_summary(rows)
    production_console = _production_control_console(rows, blocking_issues, release_status, long_chain_status, v1_artifact_coverage, approval_gate_summary)
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
            "latest_v1_artifact_coverage": v1_artifact_coverage["summary"]["latest_coverage_ratio"],
            "blocking_approval_request_count": approval_gate_summary["blocking_pending_count"],
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
        "v1_artifact_coverage": v1_artifact_coverage,
        "approval_gate_summary": approval_gate_summary,
        "production_control_console": production_console,
        "cockpit": {
            "book_production_state": production_console["book_state"]["status"],
            "today_chapter_queue": production_console["chapter_queue"],
            "risk_summary": production_console["risk_summary"],
            "artifact_coverage": production_console["artifact_coverage"],
            "approval_gate_summary": approval_gate_summary["summary"],
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
        quality_score = _latest_quality_score(rows)
        cost = _project_cost(rows)
        book_rows.append(
            {
                "project_id": project_id,
                "draft_count": type_counts.get("draft_chapter", 0),
                "chapter_plan_count": type_counts.get("chapter_plan", 0),
                "blocking_review_issue_count": len(list_review_issues(storage, project_id=project_id or None, blocking=True, limit=500)),
                "latest_quality_score": quality_score,
                "model_cost": cost,
                "cost_quality_ratio": _cost_quality_ratio(quality_score, cost),
                "memory_isolation": "project_id_scoped",
                "contamination_detection": "requires cross-book canon/style comparison before shared context",
            }
        )
    cost_quality_dashboard = _cost_quality_dashboard(book_rows, provider_budget=provider_budget)
    content = {
        "project_id": "multi-book",
        "snapshot_at": utc_now(),
        "throughput": {"book_count": len(book_rows), "planned_daily_chapters": len(book_rows)},
        "quality": {"blocked_books": sum(1 for row in book_rows if row["blocking_review_issue_count"]), "quality_policy": "per-book gates remain isolated"},
        "task_health": {"book_level_scheduler": "planned", "book_rows": book_rows},
        "agent_health": {"capacity_plan": _capacity_plan(book_rows)},
        "storage_health": {"memory_isolation": "project_id/workspace_path", "cross_book_contamination_detection": "planned"},
        "recommendations": ["Run per-book production gates before scheduling provider work", "Keep provider budget per book and per operation"],
        "cost_quality_dashboard": cost_quality_dashboard,
        "multi_book_scheduler": {
            "books": book_rows,
            "provider_budget_plan": cost_quality_dashboard["provider_budget_plan"],
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


def build_multi_book_production_schedule(
    storage: LocalStorage,
    *,
    project_ids: list[str] | None = None,
    provider_budget: float = 0.0,
    max_parallel_books: int = 2,
    daily_chapter_goal: int = 1,
) -> dict[str, Any]:
    ids = project_ids or _known_project_ids(storage)
    book_rows: list[dict[str, Any]] = []
    for project_id in ids:
        rows = _project_assets(storage, project_id=project_id)
        type_counts = _type_counts(rows)
        blocking_count = len(list_review_issues(storage, project_id=project_id or None, blocking=True, limit=500))
        latest_quality = _latest_quality_score(rows)
        cost = _project_cost(rows)
        ready_chapter_plans = type_counts.get("chapter_plan", 0)
        draft_count = type_counts.get("draft_chapter", 0)
        recommended_action = "resolve_blocking_review_issues" if blocking_count else "generate_next_chapter" if ready_chapter_plans > draft_count else "build_next_chapter_plan"
        book_rows.append(
            {
                "project_id": project_id,
                "chapter_plan_count": ready_chapter_plans,
                "draft_count": draft_count,
                "blocking_review_issue_count": blocking_count,
                "latest_quality_score": latest_quality,
                "model_cost": cost,
                "cost_quality_ratio": _cost_quality_ratio(latest_quality, cost),
                "recommended_action": recommended_action,
                "daily_chapter_goal": daily_chapter_goal,
                "memory_isolation": "project_id_scoped",
            }
        )
    schedulable = [row for row in book_rows if row["recommended_action"] != "resolve_blocking_review_issues"]
    parallel_lanes = [
        {
            "lane": index,
            "project_id": row["project_id"],
            "action": row["recommended_action"],
            "daily_chapter_goal": row["daily_chapter_goal"],
            "budget_cap": round(float(provider_budget or 0.0) / max(1, len(book_rows)), 4),
            "requires_project_memory_scope": True,
            "requires_v7_quality_loop": True,
        }
        for index, row in enumerate(schedulable[: max(1, max_parallel_books)], start=1)
    ]
    provider_budget_plan = {"daily_budget": provider_budget, "per_book_budget": round(float(provider_budget or 0.0) / max(1, len(book_rows)), 4), "max_parallel_books": max_parallel_books}
    schedule = {
        "status": "ready" if parallel_lanes else "blocked",
        "books": book_rows,
        "parallel_lanes": parallel_lanes,
        "provider_budget_plan": provider_budget_plan,
        "cross_book_contamination_guard": {
            "enabled": True,
            "isolation_key": "project_id",
            "requires_context_builder_scope_check": True,
            "requires_canon_style_cross_book_diff_before_shared_assets": True,
        },
        "acceptance": {
            "per_chapter_quality_loop_required": True,
            "provider_runtime_gate_required": True,
            "release_gate_required": True,
            "human_gate_for_feedback_mutations": True,
        },
    }
    content = {
        "project_id": "multi-book",
        "snapshot_at": utc_now(),
        "throughput": {"book_count": len(book_rows), "planned_daily_chapters": len(parallel_lanes) * daily_chapter_goal},
        "quality": {"blocked_books": sum(1 for row in book_rows if row["blocking_review_issue_count"]), "quality_policy": "per-book V7 quality loop required"},
        "task_health": {"book_level_scheduler": schedule["status"], "parallel_lane_count": len(parallel_lanes)},
        "agent_health": {"capacity_plan": _capacity_plan(book_rows)},
        "storage_health": {"memory_isolation": "project_id/workspace_path", "cross_book_contamination_detection": "enabled"},
        "recommendations": _schedule_recommendations(schedule),
        "multi_book_parallel_schedule": schedule,
    }
    asset = ProjectMetricSnapshot(
        title="Multi-book parallel production schedule",
        tags=["novel-os-cockpit", "multi-book", "parallel-schedule", schedule["status"]],
        content=content,
        metadata={"project_id": "multi-book", "snapshot_kind": "multi_book_parallel_schedule"},
    )
    path = _write_asset(storage, asset)
    return {"path": path, "asset": storage.read_json(storage.root / path), "book_count": len(book_rows), "status": schedule["status"]}


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


def _schedule_recommendations(schedule: dict[str, Any]) -> list[str]:
    recommendations = []
    if schedule.get("status") == "blocked":
        recommendations.append("Resolve blocking ReviewIssue before scheduling provider work")
    if not schedule.get("parallel_lanes"):
        recommendations.append("Create chapter plans or clear blockers before the next scheduler tick")
    recommendations.append("Run each scheduled chapter through Context Builder, provider runtime guard, content quality loop, and release gate")
    recommendations.append("Keep per-book memory isolated by project_id unless shared assets pass cross-book contamination review")
    return recommendations


def _v1_artifact_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    run_rows = [row for row in rows if row.get("type") == "chapter_production_run"]
    run_rows = sorted(run_rows, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    runs: list[dict[str, Any]] = []
    for row in run_rows:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        outputs = content.get("outputs", {}) if isinstance(content.get("outputs", {}), dict) else {}
        present = [key for key in V1_SEQUENCE_REQUIRED_OUTPUTS if str(outputs.get(key, "") or "").strip()]
        missing = [key for key in V1_SEQUENCE_REQUIRED_OUTPUTS if key not in present]
        runs.append(
            {
                "run_id": str(content.get("run_id") or row.get("id") or ""),
                "path": str(row.get("path") or ""),
                "chapter": int(content.get("chapter") or 0),
                "status": str(content.get("status") or ""),
                "coverage_ratio": round(len(present) / max(1, len(V1_SEQUENCE_REQUIRED_OUTPUTS)), 4),
                "present_outputs": present,
                "missing_outputs": missing,
                "reducer": {
                    "ledger_path": str(outputs.get("canon_state_machine_ledger_path") or ""),
                    "snapshot_path": str(outputs.get("canon_state_machine_snapshot_path") or ""),
                    "diff_report_path": str(outputs.get("canon_state_machine_diff_report_path") or ""),
                    "status": "covered" if outputs.get("canon_state_machine_snapshot_path") and outputs.get("canon_state_machine_diff_report_path") else "missing",
                },
                "recap": {
                    "report_path": str(outputs.get("longform_recap_report_path") or ""),
                    "context_bundle_path": str(outputs.get("longform_recap_context_bundle_path") or ""),
                    "status": "covered" if outputs.get("longform_recap_report_path") else "missing",
                },
                "export": {
                    "package_path": str(outputs.get("export_package_path") or ""),
                    "markdown_path": str(outputs.get("export_markdown_path") or ""),
                    "manifest_path": str(outputs.get("export_manifest_path") or ""),
                    "status": "covered" if outputs.get("export_package_path") and outputs.get("export_manifest_path") else "missing",
                },
            }
        )
    latest = runs[-1] if runs else {}
    return {
        "contract": "v1-sequence-required-output-coverage",
        "required_outputs": list(V1_SEQUENCE_REQUIRED_OUTPUTS),
        "summary": {
            "run_count": len(runs),
            "full_coverage_run_count": sum(1 for row in runs if not row["missing_outputs"]),
            "latest_coverage_ratio": float(latest.get("coverage_ratio", 0.0) or 0.0),
            "latest_missing_outputs": latest.get("missing_outputs", list(V1_SEQUENCE_REQUIRED_OUTPUTS)),
            "latest_chapter": int(latest.get("chapter", 0) or 0),
        },
        "runs": runs[-20:],
    }


def _approval_gate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    requests = [row for row in rows if row.get("type") == "approval_request"]
    counts: dict[str, int] = {}
    pending_blocking: list[dict[str, str]] = []
    for row in requests:
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        status = str(content.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        if status == "pending" and bool(content.get("blocking")):
            pending_blocking.append(
                {
                    "request_id": str(content.get("request_id") or row.get("id") or ""),
                    "scope": str(content.get("scope") or ""),
                    "action": str(content.get("action") or ""),
                    "risk_level": str(content.get("risk_level") or ""),
                    "path": str(row.get("path") or ""),
                }
            )
    return {
        "summary": {
            "request_count": len(requests),
            "pending_count": counts.get("pending", 0),
            "approved_count": counts.get("approved", 0),
            "rejected_count": counts.get("rejected", 0),
            "expired_count": counts.get("expired", 0),
        },
        "status_counts": counts,
        "blocking_pending_count": len(pending_blocking),
        "blocking_pending": pending_blocking[:20],
    }


def _production_control_console(rows: list[dict[str, Any]], blocking_issues: list[dict[str, Any]], release_status: str, long_chain_status: str, v1_artifact_coverage: dict[str, Any], approval_gate_summary: dict[str, Any]) -> dict[str, Any]:
    chapter_queue = _latest_assets(rows, "chapter_plan", limit=20)
    draft_rows = _latest_assets(rows, "draft_chapter", limit=20)
    agent_queue = _latest_assets(rows, "agent_dispatch_queue", limit=20)
    feedback_proposals = _latest_assets(rows, "feedback_plan_mutation_proposal", limit=20)
    gate_status_board = {
        "context_builder": _latest_status(rows, asset_type="context_bundle"),
        "canon": _latest_status(rows, asset_type="canon_state_machine_snapshot"),
        "style": _latest_status(rows, asset_type="style_drift_report"),
        "quality": _latest_status(rows, asset_type="evaluation_gate"),
        "long_chain": long_chain_status,
        "release": release_status,
        "publish": _latest_status(rows, asset_type="publish_gate_report"),
    }
    return {
        "book_state": {
            "status": "blocked" if blocking_issues else "active",
            "blocking_review_issue_count": len(blocking_issues),
            "next_action": "resolve_blocking_review_issues" if blocking_issues else "continue_governed_chapter_production",
        },
        "chapter_queue": chapter_queue,
        "draft_queue": draft_rows,
        "agent_queue": agent_queue,
        "gate_status_board": gate_status_board,
        "risk_summary": {
            "context": gate_status_board["context_builder"],
            "canon": gate_status_board["canon"],
            "style": gate_status_board["style"],
            "quality": gate_status_board["quality"],
            "release": release_status,
        },
        "feedback_approval_queue": feedback_proposals,
        "rollback_recovery": {
            "resume_entry": "workflow resume APIs",
            "rollback_entry": "runtime rollback APIs",
            "requires_trace": True,
        },
        "artifact_coverage": {
            "contract": v1_artifact_coverage["contract"],
            "latest_coverage_ratio": v1_artifact_coverage["summary"]["latest_coverage_ratio"],
            "full_coverage_run_count": v1_artifact_coverage["summary"]["full_coverage_run_count"],
            "latest_missing_outputs": v1_artifact_coverage["summary"]["latest_missing_outputs"],
            "latest_chapter": v1_artifact_coverage["summary"]["latest_chapter"],
        },
        "approval_gate_summary": approval_gate_summary["summary"],
    }


def _latest_quality_score(rows: list[dict[str, Any]]) -> float:
    candidates = []
    for row in rows:
        if row.get("type") not in {"evaluation_result", "opening_3_report", "golden_10_report", "volume_30_report", "longform_100_report"}:
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        value = content.get("overall_score", content.get("overall", content.get("score", 0)))
        try:
            candidates.append((str(row.get("updated_at") or row.get("created_at") or ""), float(value or 0)))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return 0.0
    return round(sorted(candidates, key=lambda item: item[0])[-1][1], 4)


def _project_cost(rows: list[dict[str, Any]]) -> float:
    ledger_rows = [row for row in rows if row.get("type") == "cost_ledger"]
    if ledger_rows:
        return round(sum(_row_cost_amount(row) for row in ledger_rows), 4)
    total = 0.0
    for row in rows:
        if row.get("type") != "model_call_log":
            continue
        total += _row_cost_amount(row)
    return round(total, 4)


def _row_cost_amount(row: dict[str, Any]) -> float:
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    cost = content.get("cost", {}) if isinstance(content.get("cost", {}), dict) else content
    try:
        return float(cost.get("amount") or content.get("amount") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cost_quality_ratio(score: float, cost: float) -> float:
    return round(float(score or 0.0) / max(0.0001, float(cost or 0.0)), 4)


def _cost_quality_dashboard(book_rows: list[dict[str, Any]], *, provider_budget: float) -> dict[str, Any]:
    total_cost = round(sum(float(row.get("model_cost") or 0.0) for row in book_rows), 4)
    average_quality = round(sum(float(row.get("latest_quality_score") or 0.0) for row in book_rows) / max(1, len(book_rows)), 4)
    return {
        "total_cost": total_cost,
        "average_quality_score": average_quality,
        "budget_remaining": round(float(provider_budget or 0.0) - total_cost, 4),
        "provider_budget_plan": {"daily_budget": provider_budget, "per_book_budget": round(provider_budget / max(1, len(book_rows)), 4), "spent": total_cost},
        "books": book_rows,
        "risk_flags": [
            {"project_id": row["project_id"], "risk": "cost_over_budget_or_low_quality"}
            for row in book_rows
            if float(row.get("model_cost") or 0.0) > (float(provider_budget or 0.0) / max(1, len(book_rows))) or float(row.get("latest_quality_score") or 0.0) < 0.72
        ],
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
