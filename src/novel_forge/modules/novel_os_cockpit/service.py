from __future__ import annotations

from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.chapter_production_bus.service import V1_SEQUENCE_REQUIRED_OUTPUTS
from novel_forge.modules.review_issue import list_review_issues
from novel_forge.modules.runtime_project_scope import asset_matches_project_scope
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
    context_governance_gate = _latest_gate_result(rows, "context_governance_runtime_coverage")
    production_governance_drift = _latest_metric_snapshot(rows, "production_governance_evidence_drift")
    production_governance_drift_gate = _latest_gate_result(rows, "production_governance_evidence_drift")
    workflow_governance = _workflow_governance_readiness(rows)
    approval_request_caller_readiness = _approval_request_caller_readiness(rows)
    source_guarded_apply_readiness = _source_guarded_apply_readiness(rows)
    source_governance_runtime_gate = _latest_gate_result(rows, "source_governance_runtime")
    source_governance_runtime_evidence = _source_governance_runtime_execution_evidence(storage, rows, project_id=project_id)
    chapter_runtime_growth = _chapter_runtime_growth_profile(rows)
    chapter_runtime_growth_threshold_gate = _latest_gate_result(rows, "chapter_runtime_growth_threshold")
    unified_acceptance_preflight = _latest_unified_acceptance_preflight_manifest(rows)
    quality_calibration_readiness = _quality_calibration_readiness(rows)
    quality_calibration_readiness_gate = _latest_gate_result(rows, "quality_calibration_readiness_gate")
    production_console = _production_control_console(
        rows,
        blocking_issues,
        release_status,
        long_chain_status,
        v1_artifact_coverage,
        approval_gate_summary,
        workflow_governance,
        approval_request_caller_readiness,
        source_guarded_apply_readiness,
        source_governance_runtime_gate,
        source_governance_runtime_evidence,
        chapter_runtime_growth,
        chapter_runtime_growth_threshold_gate,
        unified_acceptance_preflight,
        quality_calibration_readiness,
        quality_calibration_readiness_gate,
    )
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
            "latest_context_governance_status": context_governance_gate["status"],
            "production_governance_drift_count": production_governance_drift["drift_count"],
            "production_governance_drift_gate_status": production_governance_drift_gate["status"],
            "workflow_governance_status": workflow_governance["status"],
            "workflow_governance_dead_letter_count": workflow_governance["dead_letter_count"],
            "workflow_governance_failed_preflight_count": workflow_governance["failed_preflight_count"],
            "approval_request_caller_readiness_status": approval_request_caller_readiness["status"],
            "approval_request_missing_caller_count": approval_request_caller_readiness["summary"]["missing_dimension_count"],
            "source_guarded_apply_status": source_guarded_apply_readiness["status"],
            "source_stale_pending_regeneration_count": source_guarded_apply_readiness["summary"]["stale_pending_regeneration_count"],
            "source_governance_runtime_gate_status": source_governance_runtime_gate["status"],
            "source_governance_runtime_evidence_status": source_governance_runtime_evidence["status"],
            "source_governance_runtime_evidence_count": source_governance_runtime_evidence["count"],
            "chapter_runtime_growth_status": chapter_runtime_growth["status"],
            "chapter_runtime_growth_threshold_gate_status": chapter_runtime_growth_threshold_gate["status"],
            "chapter_runtime_growth_high_run_count": chapter_runtime_growth["summary"]["high_growth_run_count"],
            "chapter_runtime_growth_max_ref_count": chapter_runtime_growth["summary"]["max_linked_asset_ref_count"],
            "unified_acceptance_preflight_status": unified_acceptance_preflight["status"],
            "unified_acceptance_preflight_missing_count": unified_acceptance_preflight["missing_or_deferred_final_evidence_count"],
            "unified_acceptance_preflight_unready_count": unified_acceptance_preflight["unready_final_evidence_count"],
            "quality_calibration_readiness_status": quality_calibration_readiness["status"],
            "quality_calibration_readiness_gate_status": quality_calibration_readiness_gate["status"],
            "quality_calibration_missing_dimension_count": quality_calibration_readiness["summary"]["missing_dimension_count"],
            "quality_calibration_external_provider_judge_count": quality_calibration_readiness["summary"]["external_provider_judge_count"],
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
        "runtime_governance": {
            "context_governance_gate": context_governance_gate,
            "production_governance_drift": production_governance_drift,
            "production_governance_drift_gate": production_governance_drift_gate,
            "workflow_governance": workflow_governance,
            "approval_request_caller_readiness": approval_request_caller_readiness,
            "source_guarded_apply_readiness": source_guarded_apply_readiness,
            "source_governance_runtime_gate": source_governance_runtime_gate,
            "source_governance_runtime_evidence": source_governance_runtime_evidence,
            "chapter_runtime_growth": chapter_runtime_growth,
            "chapter_runtime_growth_threshold_gate": chapter_runtime_growth_threshold_gate,
            "unified_acceptance_preflight": unified_acceptance_preflight,
            "quality_calibration_readiness": quality_calibration_readiness,
            "quality_calibration_readiness_gate": quality_calibration_readiness_gate,
        },
        "production_control_console": production_console,
        "cockpit": {
            "book_production_state": production_console["book_state"]["status"],
            "today_chapter_queue": production_console["chapter_queue"],
            "risk_summary": production_console["risk_summary"],
            "artifact_coverage": production_console["artifact_coverage"],
            "approval_gate_summary": approval_gate_summary["summary"],
            "context_governance_gate": context_governance_gate,
            "production_governance_drift": production_governance_drift,
            "production_governance_drift_gate": production_governance_drift_gate,
            "workflow_governance": workflow_governance,
            "approval_request_caller_readiness": approval_request_caller_readiness,
            "source_guarded_apply_readiness": source_guarded_apply_readiness,
            "source_governance_runtime_gate": source_governance_runtime_gate,
            "source_governance_runtime_evidence": source_governance_runtime_evidence,
            "chapter_runtime_growth": chapter_runtime_growth,
            "chapter_runtime_growth_threshold_gate": chapter_runtime_growth_threshold_gate,
            "unified_acceptance_preflight": unified_acceptance_preflight,
            "quality_calibration_readiness": quality_calibration_readiness,
            "quality_calibration_readiness_gate": quality_calibration_readiness_gate,
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


def _latest_gate_result(rows: list[dict[str, Any]], gate_kind: str) -> dict[str, Any]:
    matches = []
    for row in rows:
        if row.get("type") != "gate_result":
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(content.get("gate_kind") or "") != gate_kind:
            continue
        matches.append(row)
    if not matches:
        return {"status": "missing", "gate_kind": gate_kind, "path": "", "gate_result_path": "", "blocking": False, "message": "no gate result recorded"}
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    result = content.get("result", {}) if isinstance(content.get("result", {}), dict) else {}
    return {
        "status": str(content.get("status") or "unknown"),
        "gate_kind": gate_kind,
        "path": str(row.get("path") or ""),
        "gate_result_path": str(row.get("path") or ""),
        "blocking": bool(content.get("blocking")) and str(content.get("status") or "") not in {"passed", "warning", "skipped"},
        "message": str(content.get("message") or ""),
        "coverage_report_path": str(result.get("coverage_report_path") or ""),
        "report_path": str(result.get("report_path") or ""),
        "readiness_report_path": str(result.get("readiness_report_path") or ""),
        "summary": result.get("summary", {}) if isinstance(result.get("summary", {}), dict) else {},
    }


def _latest_metric_snapshot(rows: list[dict[str, Any]], snapshot_kind: str) -> dict[str, Any]:
    matches = []
    for row in rows:
        if row.get("type") != "project_metric_snapshot":
            continue
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") == snapshot_kind:
            matches.append(row)
    if not matches:
        return {"snapshot_kind": snapshot_kind, "status": "missing", "path": "", "drift_count": 0, "blocking_drift_count": 0}
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    quality = content.get("quality", {}) if isinstance(content.get("quality", {}), dict) else {}
    task_health = content.get("task_health", {}) if isinstance(content.get("task_health", {}), dict) else {}
    drift_count = int(quality.get("drift_count") or 0)
    blocking_drift_count = int(task_health.get("blocking_drift_count") or 0)
    return {
        "snapshot_kind": snapshot_kind,
        "status": "blocked" if blocking_drift_count else "warning" if drift_count else "passed",
        "path": str(row.get("path") or ""),
        "drift_count": drift_count,
        "blocking_drift_count": blocking_drift_count,
        "summary": {
            "normalized_contract_coverage": quality.get("normalized_contract_coverage", 0.0),
            "drift_counts_by_type": quality.get("drift_counts_by_type", {}) if isinstance(quality.get("drift_counts_by_type", {}), dict) else {},
        },
    }


def _latest_assets(rows: list[dict[str, Any]], asset_type: str, *, limit: int) -> list[dict[str, str]]:
    matches = [row for row in rows if row.get("type") == asset_type]
    matches = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)[:limit]
    return [{"id": str(row.get("id") or ""), "title": str(row.get("title") or ""), "path": str(row.get("path") or "")} for row in matches]


def _workflow_governance_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest_gate = _latest_gate_result(rows, "workflow_governance_drift")
    preflights = _workflow_governance_preflight_rows(rows)
    dead_letters = _workflow_governance_dead_letter_rows(rows)
    failed_preflight_count = sum(1 for item in preflights if item["status"] == "failed" or item["gate_status"] == "failed" or item["blocking"])
    warning_preflight_count = sum(1 for item in preflights if item["gate_status"] == "warning")
    if bool(latest_gate.get("blocking")) or str(latest_gate.get("status") or "") == "failed" or failed_preflight_count or dead_letters:
        status = "blocked"
    elif str(latest_gate.get("status") or "") == "warning" or warning_preflight_count:
        status = "warning"
    elif str(latest_gate.get("status") or "") == "missing" and not preflights:
        status = "missing"
    else:
        status = "passed"
    latest_preflight = preflights[0] if preflights else {}
    return {
        "contract": "workflow-governance-cockpit-readiness-v1",
        "status": status,
        "gate_status": latest_gate["status"],
        "latest_gate_result": latest_gate,
        "preflight_count": len(preflights),
        "failed_preflight_count": failed_preflight_count,
        "warning_preflight_count": warning_preflight_count,
        "dead_letter_count": len(dead_letters),
        "latest_preflight": latest_preflight,
        "preflights": preflights[:20],
        "dead_letters": dead_letters[:20],
        "evidence_paths": _dedupe(
            [
                str(latest_gate.get("gate_result_path") or ""),
                str(latest_gate.get("coverage_report_path") or ""),
                str(latest_gate.get("report_path") or ""),
                *[str(item.get("gate_result_path") or "") for item in preflights],
                *[str(item.get("drift_report_path") or "") for item in preflights],
                *[str(item.get("ready_node_queue_path") or "") for item in dead_letters],
            ]
        ),
        "operator_action": _workflow_governance_operator_action(status),
    }


def _workflow_governance_preflight_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preflights: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "workflow_run":
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        lineage = content.get("lineage", {}) if isinstance(content.get("lineage", {}), dict) else {}
        preflight = lineage.get("workflow_governance_preflight", {}) if isinstance(lineage.get("workflow_governance_preflight", {}), dict) else {}
        if not preflight:
            continue
        preflights.append(
            {
                "workflow_run_id": str(content.get("run_id") or row.get("id") or ""),
                "workflow_run_path": str(row.get("path") or ""),
                "workflow_definition_path": str(content.get("workflow_definition_path") or ""),
                "status": str(preflight.get("status") or ""),
                "gate_status": str(preflight.get("gate_status") or ""),
                "blocking": bool(preflight.get("blocking", False)),
                "message": str(preflight.get("message") or ""),
                "environment": str(preflight.get("environment") or ""),
                "mode": str(preflight.get("mode") or ""),
                "gate_result_path": str(preflight.get("gate_result_path") or ""),
                "drift_report_path": str(preflight.get("drift_report_path") or ""),
                "summary": preflight.get("summary", {}) if isinstance(preflight.get("summary", {}), dict) else {},
                "recorded_at": str(row.get("updated_at") or row.get("created_at") or ""),
            }
        )
    return sorted(preflights, key=lambda item: item["recorded_at"], reverse=True)


def _workflow_governance_dead_letter_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dead_letters: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "ready_node_queue":
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(content.get("status") or "") != "dead_letter":
            continue
        evidence = content.get("dead_letter_evidence", {}) if isinstance(content.get("dead_letter_evidence", {}), dict) else {}
        preflight = evidence.get("workflow_governance_preflight", {}) if isinstance(evidence.get("workflow_governance_preflight", {}), dict) else {}
        if not preflight:
            continue
        dead_letters.append(
            {
                "ready_node_queue_path": str(row.get("path") or ""),
                "queue_id": str(content.get("queue_id") or row.get("id") or ""),
                "node_id": str(content.get("node_id") or ""),
                "workflow_run_path": str(content.get("workflow_run_path") or ""),
                "resume_workflow_run_path": str(evidence.get("resume_workflow_run_path") or ""),
                "last_error": str(content.get("last_error") or ""),
                "preflight_status": str(preflight.get("status") or ""),
                "gate_status": str(preflight.get("gate_status") or ""),
                "gate_result_path": str(preflight.get("gate_result_path") or ""),
                "drift_report_path": str(preflight.get("drift_report_path") or ""),
                "recorded_at": str(row.get("updated_at") or row.get("created_at") or ""),
            }
        )
    return sorted(dead_letters, key=lambda item: item["recorded_at"], reverse=True)


def _workflow_governance_operator_action(status: str) -> str:
    if status == "blocked":
        return "repair canonical workflow governance evidence before scheduler resume or chapter production"
    if status == "warning":
        return "review workflow governance drift warnings before production promotion"
    if status == "missing":
        return "run workflow governance drift gate for the canonical v1 chapter workflow"
    return "continue governed workflow execution"


def _source_governance_runtime_execution_evidence(storage: LocalStorage, rows: list[dict[str, Any]], *, project_id: str) -> dict[str, Any]:
    evidence_rows: list[dict[str, Any]] = []
    for row in rows:
        asset_type = row.get("type")
        if asset_type in {"agent_run", "agent_checkpoint", "node_run"} and not asset_matches_project_scope(storage, row, project_id):
            continue
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if asset_type == "agent_run":
            evidence = content.get("evidence", {}) if isinstance(content.get("evidence", {}), dict) else {}
            compact = _source_governance_runtime_execution_row(
                evidence.get("source_governance_runtime_gate"),
                source_type="agent_run",
                owner_path=str(row.get("path") or ""),
                owner_id=str(content.get("run_id") or row.get("id") or ""),
                operation=str(content.get("operation") or ""),
                recorded_at=str(row.get("updated_at") or row.get("created_at") or ""),
            )
            if compact:
                evidence_rows.append(compact)
        elif asset_type == "agent_checkpoint":
            state = content.get("state", {}) if isinstance(content.get("state", {}), dict) else {}
            gate = state.get("source_governance_runtime_gate")
            if not isinstance(gate, dict):
                service_result = state.get("service_result", {}) if isinstance(state.get("service_result", {}), dict) else {}
                gate = service_result.get("source_governance_runtime_gate")
            compact = _source_governance_runtime_execution_row(
                gate,
                source_type="agent_checkpoint",
                owner_path=str(row.get("path") or ""),
                owner_id=str(content.get("checkpoint_id") or row.get("id") or ""),
                operation=str(state.get("operation") or ""),
                recorded_at=str(row.get("updated_at") or row.get("created_at") or ""),
            )
            if compact:
                evidence_rows.append(compact)
        elif asset_type == "node_run":
            processor = content.get("processor", {}) if isinstance(content.get("processor", {}), dict) else {}
            runtime_evidence = processor.get("runtime_policy_evidence", {}) if isinstance(processor.get("runtime_policy_evidence", {}), dict) else {}
            gate_path = str(runtime_evidence.get("source_governance_runtime_gate_path") or runtime_evidence.get("source_governance_gate_result_path") or "")
            if not gate_path:
                continue
            status = str(runtime_evidence.get("source_governance_runtime_gate_status") or "missing")
            evidence_rows.append(
                {
                    "source_type": "node_run",
                    "owner_path": str(row.get("path") or ""),
                    "owner_id": str(content.get("node_id") or row.get("id") or ""),
                    "operation": str(content.get("operation") or ""),
                    "status": status,
                    "blocking": status == "failed",
                    "gate_result_path": gate_path,
                    "readiness_report_path": str(runtime_evidence.get("source_governance_readiness_report_path") or ""),
                    "recorded_at": str(row.get("updated_at") or row.get("created_at") or ""),
                }
            )
    evidence_rows = sorted(evidence_rows, key=lambda item: item["recorded_at"], reverse=True)
    failed_count = sum(1 for row in evidence_rows if row["status"] == "failed")
    warning_count = sum(1 for row in evidence_rows if row["status"] not in {"passed", "failed"})
    status = "failed" if failed_count else "warning" if warning_count else "passed" if evidence_rows else "missing"
    return {
        "contract": "source-governance-runtime-execution-evidence-v1",
        "status": status,
        "count": len(evidence_rows),
        "failed_count": failed_count,
        "warning_count": warning_count,
        "latest": evidence_rows[0] if evidence_rows else {},
        "rows": evidence_rows[:40],
        "evidence_paths": _dedupe([str(row.get("gate_result_path") or "") for row in evidence_rows]),
        "operator_action": "inspect source gate runtime evidence before production execution"
        if status in {"failed", "warning"}
        else "source gate runtime evidence is visible"
        if evidence_rows
        else "run a governed source-gated context or workflow entrypoint",
    }


def _source_governance_runtime_execution_row(
    gate: Any,
    *,
    source_type: str,
    owner_path: str,
    owner_id: str,
    operation: str,
    recorded_at: str,
) -> dict[str, Any]:
    if not isinstance(gate, dict) or not gate:
        return {}
    gate_result = gate.get("gate_result", {}) if isinstance(gate.get("gate_result", {}), dict) else {}
    readiness_report = gate.get("readiness_report", {}) if isinstance(gate.get("readiness_report", {}), dict) else {}
    gate_path = str(gate.get("gate_result_path") or gate_result.get("path") or "")
    if not gate_path:
        return {}
    status = str(gate.get("status") or "missing")
    return {
        "source_type": source_type,
        "owner_path": owner_path,
        "owner_id": owner_id,
        "operation": operation,
        "status": status,
        "blocking": bool(gate.get("blocking")) or status == "failed",
        "gate_result_path": gate_path,
        "readiness_report_path": str(gate.get("readiness_report_path") or readiness_report.get("path") or ""),
        "summary": gate.get("summary", {}) if isinstance(gate.get("summary", {}), dict) else {},
        "recorded_at": recorded_at,
    }


def _chapter_runtime_growth_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_kind = "chapter_runtime_growth_profile"
    matches = []
    for row in rows:
        if row.get("type") != "project_metric_snapshot":
            continue
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") == snapshot_kind:
            matches.append(row)
    if not matches:
        return {
            "snapshot_kind": snapshot_kind,
            "contract": "chapter-runtime-growth-profile-v1",
            "status": "missing",
            "path": "",
            "summary": {
                "chapter_run_count": 0,
                "high_growth_run_count": 0,
                "max_linked_asset_ref_count": 0,
                "average_linked_asset_ref_count": 0.0,
                "estimated_compacted_write_savings": 0,
            },
            "runtime_rows": [],
            "evidence_paths": [],
            "recommendations": ["Run chapter runtime growth profiler before final unified acceptance"],
            "operator_action": "run chapter runtime growth profiler before final unified acceptance",
        }
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    summary = content.get("summary", {}) if isinstance(content.get("summary", {}), dict) else {}
    quality = content.get("quality", {}) if isinstance(content.get("quality", {}), dict) else {}
    return {
        "snapshot_kind": snapshot_kind,
        "contract": str(content.get("contract") or "chapter-runtime-growth-profile-v1"),
        "status": str(content.get("status") or "unknown"),
        "path": str(row.get("path") or ""),
        "summary": {
            "chapter_run_count": int(summary.get("chapter_run_count") or 0),
            "high_growth_run_count": int(quality.get("high_growth_run_count") or 0),
            "max_linked_asset_ref_count": int(summary.get("max_linked_asset_ref_count") or 0),
            "average_linked_asset_ref_count": float(summary.get("average_linked_asset_ref_count") or 0.0),
            "estimated_compacted_write_savings": int(summary.get("estimated_compacted_write_savings") or 0),
        },
        "runtime_rows": content.get("runtime_rows", []) if isinstance(content.get("runtime_rows", []), list) else [],
        "evidence_paths": content.get("evidence_paths", []) if isinstance(content.get("evidence_paths", []), list) else [],
        "recommendations": content.get("recommendations", []) if isinstance(content.get("recommendations", []), list) else [],
        "operator_action": str(content.get("operator_action") or ""),
    }


def _latest_unified_acceptance_preflight_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [row for row in rows if row.get("type") == "long_chain_acceptance_report"]
    if not matches:
        return {
            "contract": "v1-unified-acceptance-preflight-manifest-v1",
            "status": "missing",
            "path": "",
            "enforced_failure_count": 0,
            "unready_final_evidence_count": 0,
            "missing_or_deferred_final_evidence_count": 0,
            "required_evidence": [],
            "operator_action": "run deferred v1 acceptance preflight helper before final unified acceptance",
        }
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    manifest = content.get("unified_acceptance_preflight_manifest", {}) if isinstance(content.get("unified_acceptance_preflight_manifest", {}), dict) else {}
    if not manifest:
        return {
            "contract": "v1-unified-acceptance-preflight-manifest-v1",
            "status": "missing",
            "path": str(row.get("path") or ""),
            "enforced_failure_count": 0,
            "unready_final_evidence_count": 0,
            "missing_or_deferred_final_evidence_count": 0,
            "required_evidence": [],
            "operator_action": "latest acceptance report has no unified preflight manifest",
        }
    evidence = manifest.get("required_evidence", []) if isinstance(manifest.get("required_evidence", []), list) else []
    return {
        "contract": str(manifest.get("contract") or "v1-unified-acceptance-preflight-manifest-v1"),
        "status": str(manifest.get("status") or "unknown"),
        "path": str(row.get("path") or ""),
        "enforced_failure_count": int(manifest.get("enforced_failure_count") or 0),
        "unready_final_evidence_count": int(
            manifest.get("unready_final_evidence_count") or manifest.get("missing_or_deferred_final_evidence_count") or 0
        ),
        "missing_or_deferred_final_evidence_count": int(manifest.get("missing_or_deferred_final_evidence_count") or 0),
        "required_evidence": evidence,
        "operator_action": str(manifest.get("operator_action") or ""),
    }


def _quality_calibration_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_kind = "quality_calibration_readiness"
    matches = []
    for row in rows:
        if row.get("type") != "project_metric_snapshot":
            continue
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") == snapshot_kind:
            matches.append(row)
    if not matches:
        return {
            "snapshot_kind": snapshot_kind,
            "contract": "quality-calibration-readiness-v1",
            "status": "missing",
            "path": "",
            "summary": {
                "quality_rubric_pack_count": 0,
                "quality_suite_report_count": 0,
                "model_judge_result_count": 0,
                "external_provider_judge_count": 0,
                "provider_route_approved_judge_count": 0,
                "fixture_or_mock_provider_judge_count": 0,
                "human_annotation_count": 0,
                "golden_set_count": 0,
                "provider_calibration_report_count": 0,
                "passed_provider_calibration_count": 0,
                "failed_provider_calibration_count": 0,
                "missing_dimension_count": 0,
                "missing_dimensions": [],
            },
            "dimensions": [],
            "evidence_paths": [],
            "operator_action": "run quality calibration readiness before final unified acceptance",
        }
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    summary = content.get("summary", {}) if isinstance(content.get("summary", {}), dict) else {}
    return {
        "snapshot_kind": snapshot_kind,
        "contract": str(content.get("contract") or "quality-calibration-readiness-v1"),
        "status": str(content.get("status") or "unknown"),
        "path": str(row.get("path") or ""),
        "summary": {
            "quality_rubric_pack_count": int(summary.get("quality_rubric_pack_count") or 0),
            "quality_suite_report_count": int(summary.get("quality_suite_report_count") or 0),
            "model_judge_result_count": int(summary.get("model_judge_result_count") or 0),
            "external_provider_judge_count": int(summary.get("external_provider_judge_count") or 0),
            "provider_route_approved_judge_count": int(summary.get("provider_route_approved_judge_count") or 0),
            "fixture_or_mock_provider_judge_count": int(summary.get("fixture_or_mock_provider_judge_count") or 0),
            "human_annotation_count": int(summary.get("human_annotation_count") or 0),
            "golden_set_count": int(summary.get("golden_set_count") or 0),
            "provider_calibration_report_count": int(summary.get("provider_calibration_report_count") or 0),
            "passed_provider_calibration_count": int(summary.get("passed_provider_calibration_count") or 0),
            "failed_provider_calibration_count": int(summary.get("failed_provider_calibration_count") or 0),
            "missing_dimension_count": int(summary.get("missing_dimension_count") or 0),
            "missing_dimensions": summary.get("missing_dimensions", []) if isinstance(summary.get("missing_dimensions", []), list) else [],
        },
        "dimensions": content.get("dimensions", []) if isinstance(content.get("dimensions", []), list) else [],
        "model_judge_rows": content.get("model_judge_rows", []) if isinstance(content.get("model_judge_rows", []), list) else [],
        "human_annotation_rows": content.get("human_annotation_rows", []) if isinstance(content.get("human_annotation_rows", []), list) else [],
        "golden_set_rows": content.get("golden_set_rows", []) if isinstance(content.get("golden_set_rows", []), list) else [],
        "calibration_report_rows": content.get("calibration_report_rows", []) if isinstance(content.get("calibration_report_rows", []), list) else [],
        "evidence_paths": content.get("evidence_paths", []) if isinstance(content.get("evidence_paths", []), list) else [],
        "operator_action": str(content.get("operator_action") or ""),
    }


def _approval_request_caller_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_kind = "approval_request_caller_readiness"
    matches = []
    for row in rows:
        if row.get("type") != "project_metric_snapshot":
            continue
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") == snapshot_kind:
            matches.append(row)
    if not matches:
        return {
            "snapshot_kind": snapshot_kind,
            "status": "missing",
            "path": "",
            "summary": {
                "required_dimension_count": 0,
                "covered_dimension_count": 0,
                "missing_dimension_count": 0,
                "pending_count": 0,
                "pending_blocking_count": 0,
                "terminal_unready_count": 0,
                "approval_request_count": 0,
                "missing_dimensions": [],
            },
            "caller_dimensions": [],
            "evidence_paths": [],
            "operator_action": "run ApprovalRequest caller readiness report before production promotion",
        }
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    summary = content.get("summary", {}) if isinstance(content.get("summary", {}), dict) else {}
    return {
        "snapshot_kind": snapshot_kind,
        "status": str(content.get("status") or "unknown"),
        "path": str(row.get("path") or ""),
        "summary": {
            "required_dimension_count": int(summary.get("required_dimension_count") or 0),
            "covered_dimension_count": int(summary.get("covered_dimension_count") or 0),
            "missing_dimension_count": int(summary.get("missing_dimension_count") or 0),
            "pending_count": int(summary.get("pending_count") or 0),
            "pending_blocking_count": int(summary.get("pending_blocking_count") or 0),
            "terminal_unready_count": int(summary.get("terminal_unready_count") or 0),
            "approval_request_count": int(summary.get("approval_request_count") or 0),
            "missing_dimensions": summary.get("missing_dimensions", []) if isinstance(summary.get("missing_dimensions", []), list) else [],
        },
        "caller_dimensions": content.get("caller_dimensions", []) if isinstance(content.get("caller_dimensions", []), list) else [],
        "evidence_paths": content.get("evidence_paths", []) if isinstance(content.get("evidence_paths", []), list) else [],
        "operator_action": str(content.get("operator_action") or ""),
    }


def _source_guarded_apply_readiness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_kind = "source_guarded_apply_readiness"
    matches = []
    for row in rows:
        if row.get("type") != "project_metric_snapshot":
            continue
        metadata = row.get("metadata", {}) if isinstance(row.get("metadata", {}), dict) else {}
        content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
        if str(metadata.get("snapshot_kind") or content.get("snapshot_kind") or "") == snapshot_kind:
            matches.append(row)
    if not matches:
        return {
            "snapshot_kind": snapshot_kind,
            "status": "missing",
            "path": "",
            "summary": {
                "repair_plan_count": 0,
                "pending_review_plan_count": 0,
                "applied_plan_count": 0,
                "approval_request_count": 0,
                "pending_approval_count": 0,
                "blocking_approval_count": 0,
                "stale_pending_regeneration_count": 0,
                "review_task_count": 0,
                "dispatch_ready_task_count": 0,
                "rollback_plan_count": 0,
                "rollback_result_count": 0,
            },
            "repair_plans": [],
            "stale_assets": [],
            "agent_tasks": [],
            "evidence_paths": [],
            "operator_action": "run source guarded apply readiness report before source-derived regeneration or context promotion",
        }
    row = sorted(matches, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))[-1]
    content = row.get("content", {}) if isinstance(row.get("content", {}), dict) else {}
    summary = content.get("summary", {}) if isinstance(content.get("summary", {}), dict) else {}
    return {
        "snapshot_kind": snapshot_kind,
        "status": str(content.get("status") or "unknown"),
        "path": str(row.get("path") or ""),
        "summary": {
            "repair_plan_count": int(summary.get("repair_plan_count") or 0),
            "pending_review_plan_count": int(summary.get("pending_review_plan_count") or 0),
            "applied_plan_count": int(summary.get("applied_plan_count") or 0),
            "approval_request_count": int(summary.get("approval_request_count") or 0),
            "pending_approval_count": int(summary.get("pending_approval_count") or 0),
            "blocking_approval_count": int(summary.get("blocking_approval_count") or 0),
            "stale_pending_regeneration_count": int(summary.get("stale_pending_regeneration_count") or 0),
            "review_task_count": int(summary.get("review_task_count") or 0),
            "dispatch_ready_task_count": int(summary.get("dispatch_ready_task_count") or 0),
            "rollback_plan_count": int(summary.get("rollback_plan_count") or 0),
            "rollback_result_count": int(summary.get("rollback_result_count") or 0),
        },
        "repair_plans": content.get("repair_plans", []) if isinstance(content.get("repair_plans", []), list) else [],
        "stale_assets": content.get("stale_assets", []) if isinstance(content.get("stale_assets", []), list) else [],
        "agent_tasks": content.get("agent_tasks", []) if isinstance(content.get("agent_tasks", []), list) else [],
        "evidence_paths": content.get("evidence_paths", []) if isinstance(content.get("evidence_paths", []), list) else [],
        "operator_action": str(content.get("operator_action") or ""),
    }


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


def _production_control_console(
    rows: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
    release_status: str,
    long_chain_status: str,
    v1_artifact_coverage: dict[str, Any],
    approval_gate_summary: dict[str, Any],
    workflow_governance: dict[str, Any],
    approval_request_caller_readiness: dict[str, Any],
    source_guarded_apply_readiness: dict[str, Any],
    source_governance_runtime_gate: dict[str, Any],
    source_governance_runtime_evidence: dict[str, Any],
    chapter_runtime_growth: dict[str, Any],
    chapter_runtime_growth_threshold_gate: dict[str, Any],
    unified_acceptance_preflight: dict[str, Any],
    quality_calibration_readiness: dict[str, Any],
    quality_calibration_readiness_gate: dict[str, Any],
) -> dict[str, Any]:
    chapter_queue = _latest_assets(rows, "chapter_plan", limit=20)
    draft_rows = _latest_assets(rows, "draft_chapter", limit=20)
    agent_queue = _latest_assets(rows, "agent_dispatch_queue", limit=20)
    feedback_proposals = _latest_assets(rows, "feedback_plan_mutation_proposal", limit=20)
    gate_status_board = {
        "context_builder": _latest_status(rows, asset_type="context_bundle"),
        "context_governance": _latest_gate_result(rows, "context_governance_runtime_coverage")["status"],
        "canon": _latest_status(rows, asset_type="canon_state_machine_snapshot"),
        "style": _latest_status(rows, asset_type="style_drift_report"),
        "quality": _latest_status(rows, asset_type="evaluation_gate"),
        "long_chain": long_chain_status,
        "workflow_governance": workflow_governance["status"],
        "approval_request_callers": approval_request_caller_readiness["status"],
        "source_guarded_apply": source_guarded_apply_readiness["status"],
        "source_governance_runtime": source_governance_runtime_gate["status"],
        "source_governance_runtime_evidence": source_governance_runtime_evidence["status"],
        "runtime_growth": chapter_runtime_growth["status"],
        "runtime_growth_threshold": chapter_runtime_growth_threshold_gate["status"],
        "unified_acceptance_preflight": unified_acceptance_preflight["status"],
        "quality_calibration": quality_calibration_readiness["status"],
        "quality_calibration_gate": quality_calibration_readiness_gate["status"],
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
            "workflow_governance": workflow_governance["status"],
            "approval_request_callers": approval_request_caller_readiness["status"],
            "source_guarded_apply": source_guarded_apply_readiness["status"],
            "source_governance_runtime": source_governance_runtime_gate["status"],
            "source_governance_runtime_evidence": source_governance_runtime_evidence["status"],
            "runtime_growth": chapter_runtime_growth["status"],
            "runtime_growth_threshold": chapter_runtime_growth_threshold_gate["status"],
            "unified_acceptance_preflight": unified_acceptance_preflight["status"],
            "quality_calibration": quality_calibration_readiness["status"],
            "quality_calibration_gate": quality_calibration_readiness_gate["status"],
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
        "workflow_governance": workflow_governance,
        "approval_request_caller_readiness": approval_request_caller_readiness,
        "source_guarded_apply_readiness": source_guarded_apply_readiness,
        "source_governance_runtime_gate": source_governance_runtime_gate,
        "source_governance_runtime_evidence": source_governance_runtime_evidence,
        "chapter_runtime_growth": chapter_runtime_growth,
        "chapter_runtime_growth_threshold_gate": chapter_runtime_growth_threshold_gate,
        "unified_acceptance_preflight": unified_acceptance_preflight,
        "quality_calibration_readiness": quality_calibration_readiness,
        "quality_calibration_readiness_gate": quality_calibration_readiness_gate,
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


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(str(item) for item in values if str(item or "").strip())]
