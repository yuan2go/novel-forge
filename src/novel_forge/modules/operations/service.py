from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import resolve_path
from novel_forge.schemas import LocalOpsDrillReport, LongChainAcceptanceReport, validate_common_fields
from novel_forge.storage.local import LocalStorage

OPERATION_REPORT_TYPES = {"local_ops_drill_report", "long_chain_acceptance_report"}


def list_operation_reports(storage: LocalStorage, *, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") not in OPERATION_REPORT_TYPES:
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        rows.append(
            {
                "path": _display_path(storage.root, path),
                "id": data.get("id", ""),
                "type": data.get("type", ""),
                "title": data.get("title") or data.get("name", ""),
                "status": content.get("status", ""),
                "recommendation": content.get("recommendation", ""),
                "chapter_count": content.get("chapter_count", ""),
                "updated_at": data.get("updated_at", ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def create_local_ops_drill_report(storage: LocalStorage, *, settings: IndustrialSettings | None = None) -> dict[str, Any]:
    storage.ensure_layout()
    scenarios = _ops_scenarios(storage, settings=settings)
    results = [_scenario_result(storage, scenario) for scenario in scenarios]
    status = "failed" if any(item["status"] == "failed" for item in results) else "warning" if any(item["status"] == "warning" for item in results) else "passed"
    actions = _recovery_actions(results)
    with AgentExecutionContext(
        storage,
        agent_key="metrics",
        operation="create-local-ops-drill-report",
        output_types=["local_ops_drill_report"],
        sla_seconds=300,
    ) as run:
        run.guard("run_failure_drill")
        run.guard("write_local_ops_drill_report", "local_ops_drill_report")
        asset = LocalOpsDrillReport(
            title=f"Local ops drill {utc_now()}",
            tags=["ops", "failure-drill", status],
            content={
                "drill_id": make_id("local_ops_drill", status),
                "scenarios": scenarios,
                "results": results,
                "recovery_actions": actions,
                "status": status,
                "created_at": utc_now(),
            },
            metadata={"workflow": "local-production-ops-drill", "risk_level": "high" if status == "failed" else "medium" if status == "warning" else "low"},
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def create_long_chain_acceptance_report(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    chapter_count: int = 10,
    acceptance_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chapter_count = max(1, int(chapter_count or 10))
    checks = _long_chain_checks(storage, project_id=project_id, chapter_count=chapter_count)
    evidence = acceptance_evidence if isinstance(acceptance_evidence, dict) else {}
    os_checks = _operating_acceptance_checks(storage, evidence) if evidence else []
    checks = [*checks, *os_checks]
    trends = _quality_trends(storage, project_id=project_id)
    canon_conflicts = _canon_conflicts(storage, project_id=project_id)
    publish_summary = _publish_gate_summary(storage, project_id=project_id)
    scale_metrics = _scale_acceptance_metrics(storage, project_id=project_id, chapter_count=chapter_count)
    if evidence:
        require_publish_ready = bool(evidence.get("require_publish_ready", False))
        require_no_canon_conflicts = bool(evidence.get("require_no_canon_conflicts", False))
        recommendation = (
            "block"
            if any(item["status"] == "failed" for item in os_checks)
            or (require_publish_ready and publish_summary.get("blocked", 0))
            or (require_no_canon_conflicts and canon_conflicts)
            else "revise"
            if any(item["status"] == "warning" for item in os_checks)
            else "pass"
        )
    else:
        recommendation = "block" if canon_conflicts or publish_summary.get("blocked", 0) else "revise" if any(item["status"] == "warning" for item in checks) else "pass"
    with AgentExecutionContext(
        storage,
        agent_key="metrics",
        operation="create-long-chain-acceptance-report",
        output_types=["long_chain_acceptance_report"],
        sla_seconds=600,
    ) as run:
        run.guard("run_long_chain_acceptance")
        run.guard("write_long_chain_acceptance_report", "long_chain_acceptance_report")
        asset = LongChainAcceptanceReport(
            title=f"Long-chain acceptance {chapter_count} chapters",
            tags=["acceptance", "long-chain", recommendation],
            content={
                "run_id": make_id("long_chain_acceptance", f"{project_id or 'global'}-{chapter_count}"),
                "project_id": project_id or "",
                "chapter_count": chapter_count,
                "checks": checks,
                "quality_trends": trends,
                "scale_metrics": scale_metrics,
                "canon_conflicts": canon_conflicts,
                "publish_gate_summary": publish_summary,
                "acceptance_mode": "operating_system" if evidence else "long_chain",
                "acceptance_evidence": _json_safe(evidence),
                "recommendation": recommendation,
                "created_at": utc_now(),
            },
            metadata={"project_id": project_id or "", "workflow": "long-chain-acceptance", "risk_level": "high" if recommendation == "block" else "medium" if recommendation == "revise" else "low"},
        )
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def _ops_scenarios(storage: LocalStorage, *, settings: IndustrialSettings | None) -> list[dict[str, Any]]:
    return [
        {"scenario": "backup_restore_inventory", "target": "data/backups", "expected": "at least one backup or backup command available"},
        {"scenario": "postgres_strict_available", "target": "local-prod postgres", "expected": "strict mode can fail closed when enabled", "enabled": bool(settings and settings.postgres.strict_local_prod)},
        {"scenario": "qdrant_index_consistency", "target": "data/indexes/qdrant_index_state.json", "expected": "index state is readable when present"},
        {"scenario": "minio_object_consistency", "target": "data/indexes/minio_object_state.json", "expected": "object state is readable when present"},
        {"scenario": "long_task_dead_letter_recovery", "target": "data/tasks", "expected": "dead-letter files can be enumerated"},
        {"scenario": "chapter_bus_resume", "target": "chapter_production_run assets", "expected": "failed or paused runs are visible"},
        {"scenario": "worker_kill_recovery", "target": "chapter_production_run control", "expected": "celery-backed runs have pause/cancel/recover evidence"},
        {"scenario": "redis_short_outage_recovery", "target": "task_status retry metadata", "expected": "failed async task statuses can be retried without losing outputs"},
        {"scenario": "postgres_strict_outage_fail_closed", "target": "postgres strict local-prod", "expected": "strict mode fails closed instead of silent fallback", "enabled": bool(settings and settings.postgres.strict_local_prod)},
        {"scenario": "qdrant_dimension_mismatch_rebuild", "target": "qdrant metadata", "expected": "dimension/model metadata exists or rebuild action is explicit"},
        {"scenario": "minio_unavailable_resync", "target": "minio object status", "expected": "missing objects can be detected and resynced"},
        {"scenario": "idempotency_key_coverage", "target": "task and workflow run metadata", "expected": "long-running operations include idempotency or run ids"},
        {"scenario": "queue_pressure_trend", "target": "queue trend samples", "expected": "queue pressure can be inspected before batch runs"},
        {"scenario": "batch_recovery_ui", "target": "batch_task_item failures", "expected": "failed batch items are enumerable for bulk recovery"},
    ]


def _scenario_result(storage: LocalStorage, scenario: dict[str, Any]) -> dict[str, Any]:
    name = scenario["scenario"]
    if name == "backup_restore_inventory":
        backups = list((storage.root / "data" / "backups").glob("*")) if (storage.root / "data" / "backups").exists() else []
        return {"scenario": name, "status": "passed" if backups else "warning", "evidence": {"backup_count": len(backups)}}
    if name in {"qdrant_index_consistency", "minio_object_consistency"}:
        state_file = storage.root / scenario["target"]
        return {"scenario": name, "status": "passed" if state_file.exists() else "warning", "evidence": {"state_file": str(state_file), "exists": state_file.exists()}}
    if name == "long_task_dead_letter_recovery":
        dead_letters = [path for path in storage.list_json("tasks") if "dead" in path.name]
        return {"scenario": name, "status": "passed", "evidence": {"dead_letter_count": len(dead_letters)}}
    if name == "chapter_bus_resume":
        runs = _assets_by_type(storage, "chapter_production_run", "runs")
        recoverable = [item for item in runs if item.get("content", {}).get("status") in {"failed", "paused", "cancelled"}]
        return {"scenario": name, "status": "passed" if runs else "warning", "evidence": {"run_count": len(runs), "recoverable_count": len(recoverable)}}
    if name == "worker_kill_recovery":
        runs = _assets_by_type(storage, "chapter_production_run", "runs")
        celery_runs = [item for item in runs if item.get("content", {}).get("control", {}).get("execution_mode") == "celery" or item.get("content", {}).get("celery_task_id")]
        recoverable = [item for item in runs if item.get("content", {}).get("status") in {"failed", "paused", "cancelled", "planned"}]
        return {"scenario": name, "status": "passed" if celery_runs and recoverable else "warning", "evidence": {"celery_run_count": len(celery_runs), "recoverable_count": len(recoverable)}}
    if name == "redis_short_outage_recovery":
        statuses = _assets_by_type(storage, "task_status", "runs")
        failed = [item for item in statuses if item.get("content", {}).get("status") in {"failed", "dead_letter", "cancelled"}]
        retryable = [item for item in failed if item.get("content", {}).get("run_id") or item.get("content", {}).get("input_paths")]
        return {"scenario": name, "status": "passed" if retryable else "warning", "evidence": {"failed_count": len(failed), "retryable_count": len(retryable)}}
    if name == "postgres_strict_outage_fail_closed":
        enabled = bool(scenario.get("enabled"))
        return {"scenario": name, "status": "passed" if enabled else "warning", "evidence": {"strict_local_prod_enabled": enabled, "fail_closed_required": True}}
    if name == "qdrant_dimension_mismatch_rebuild":
        index_dir = storage.root / "data" / "indexes"
        qdrant_files = list(index_dir.glob("*qdrant*.json")) if index_dir.exists() else []
        metadata_files = [path for path in qdrant_files if "metadata" in path.name or "state" in path.name]
        return {"scenario": name, "status": "passed" if metadata_files else "warning", "evidence": {"qdrant_metadata_files": [str(path.relative_to(storage.root)) for path in metadata_files[:8]]}}
    if name == "minio_unavailable_resync":
        state_file = storage.root / "data" / "indexes" / "minio_object_state.json"
        missing_count = 0
        if state_file.exists():
            try:
                data = storage.read_json(state_file)
                objects = data.get("objects", []) if isinstance(data, dict) and isinstance(data.get("objects", []), list) else []
                missing_count = len([item for item in objects if isinstance(item, dict) and not item.get("exists", True)])
            except Exception:
                missing_count = 0
        return {"scenario": name, "status": "passed" if state_file.exists() and missing_count == 0 else "warning", "evidence": {"state_exists": state_file.exists(), "missing_count": missing_count}}
    if name == "idempotency_key_coverage":
        runs = _assets_by_type(storage, "workflow_run", "runs") + _assets_by_type(storage, "chapter_production_run", "runs")
        covered = [item for item in runs if item.get("content", {}).get("run_id") or item.get("metadata", {}).get("idempotency_key")]
        return {"scenario": name, "status": "passed" if runs and len(covered) == len(runs) else "warning", "evidence": {"run_count": len(runs), "covered_count": len(covered)}}
    if name == "queue_pressure_trend":
        statuses = _assets_by_type(storage, "task_status", "runs")
        active = len([item for item in statuses if item.get("content", {}).get("status") in {"pending", "running", "reserved", "scheduled"}])
        failed = len([item for item in statuses if item.get("content", {}).get("status") in {"failed", "dead_letter"}])
        return {"scenario": name, "status": "passed" if statuses else "warning", "evidence": {"status_count": len(statuses), "active_pressure": active, "failed_pressure": failed}}
    if name == "batch_recovery_ui":
        items = _assets_by_type(storage, "batch_task_item", "tasks") + _assets_by_type(storage, "batch_task_item", "runs")
        failed = [item for item in items if item.get("content", {}).get("status") in {"failed", "waiting_handoff", "cancelled"}]
        return {"scenario": name, "status": "passed" if items else "warning", "evidence": {"item_count": len(items), "recoverable_count": len(failed)}}
    if name == "postgres_strict_available":
        enabled = bool(scenario.get("enabled"))
        return {"scenario": name, "status": "passed" if enabled else "warning", "evidence": {"strict_local_prod_enabled": enabled}}
    return {"scenario": name, "status": "warning", "evidence": {"reason": "unknown scenario"}}


def _recovery_actions(results: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in results:
        if item.get("status") == "passed":
            continue
        scenario = item.get("scenario", "")
        if scenario == "backup_restore_inventory":
            actions.append("run POST /product/system/backups before long generation sessions")
        elif scenario == "qdrant_index_consistency":
            actions.append("run POST /product/qdrant/index with recreate=false, then rerun RAG gate")
        elif scenario == "minio_object_consistency":
            actions.append("run POST /product/minio/sync and inspect missing objects")
        elif scenario == "postgres_strict_available":
            actions.append("start local postgres and enable strict local-prod before production chains")
        elif scenario == "chapter_bus_resume":
            actions.append("create a chapter production run and verify pause/resume/recover before batch generation")
        elif scenario == "worker_kill_recovery":
            actions.append("run an async chapter production task, kill the worker, then verify recover endpoint resumes from the failed step")
        elif scenario == "redis_short_outage_recovery":
            actions.append("simulate Redis interruption and confirm failed task_status rows can be retried or dead-lettered")
        elif scenario == "postgres_strict_outage_fail_closed":
            actions.append("enable strict local-prod and confirm API startup fails closed when Postgres is unavailable")
        elif scenario == "qdrant_dimension_mismatch_rebuild":
            actions.append("run qdrant recreate/migrate when embedding model or vector dimension changes")
        elif scenario == "minio_unavailable_resync":
            actions.append("rerun MinIO sync after outage and verify missing object count returns to zero")
        elif scenario == "idempotency_key_coverage":
            actions.append("record run_id/idempotency_key for every long task before enabling large batch generation")
        elif scenario == "queue_pressure_trend":
            actions.append("inspect task center queue pressure before starting more batch or chapter bus jobs")
        elif scenario == "batch_recovery_ui":
            actions.append("use batch item bulk retry for failed/waiting_handoff items")
    return actions or ["no recovery action required"]


def _long_chain_checks(storage: LocalStorage, *, project_id: str | None, chapter_count: int) -> list[dict[str, Any]]:
    runs = _project_assets(storage, "chapter_production_run", "runs", project_id=project_id)
    drafts = _project_assets(storage, "draft_version", "drafts", project_id=project_id)
    context = _project_assets(storage, "context_bundle", "contexts", project_id=project_id)
    reports = _project_assets(storage, "chapter_continuity_report", "continuity", project_id=project_id)
    feedback = _project_assets(storage, "feedback_backflow_plan", "feedback", project_id=project_id)
    return [
        {"check": "chapter_production_runs", "status": "passed" if len(runs) >= min(chapter_count, 1) else "warning", "observed": len(runs), "expected": chapter_count},
        {"check": "draft_versions", "status": "passed" if len(drafts) >= min(chapter_count, 1) else "warning", "observed": len(drafts), "expected": chapter_count},
        {"check": "context_bundles", "status": "passed" if len(context) >= min(chapter_count, 1) else "warning", "observed": len(context), "expected": chapter_count},
        {"check": "continuity_reports", "status": "passed" if len(reports) >= min(chapter_count, 1) else "warning", "observed": len(reports), "expected": chapter_count},
        {"check": "feedback_backflow", "status": "passed" if feedback else "warning", "observed": len(feedback), "expected": 1},
    ]


def _operating_acceptance_checks(storage: LocalStorage, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    required_paths = {
        "workflow_run": ("workflow_run_path", "workflow_run"),
        "context_bundle": ("context_bundle_path", "context_bundle"),
        "kg_gate": ("kg_gate_path", "gate_result"),
        "budget_policy": ("budget_policy_path", "budget_policy"),
        "model_call_log": ("model_call_log_path", "model_call_log"),
        "review_rework": ("revision_task_path", "revision_task"),
        "cost_ledger": ("cost_ledger_path", "cost_ledger"),
        "invalidation": ("invalidation_report_path", "change_impact_report"),
        "resume": ("resume_workflow_run_path", "workflow_run"),
        "publish_gate": ("publish_gate_report_path", "publish_gate_report"),
        "cost_quality_dashboard": ("cost_quality_dashboard_path", "cost_quality_dashboard"),
    }
    checks: list[dict[str, Any]] = []
    for check, (key, expected_type) in required_paths.items():
        value = str(evidence.get(key, "") or "")
        exists = _path_exists(storage, value)
        actual_type = _path_asset_type(storage, value) if exists else ""
        type_ok = exists and (not expected_type or actual_type == expected_type)
        checks.append(
            {
                "check": check,
                "status": "passed" if type_ok else "failed",
                "evidence_key": key,
                "path": value,
                "observed": 1 if type_ok else 0,
                "expected": 1,
                "expected_type": expected_type,
                "actual_type": actual_type,
            }
        )
    scheduler = evidence.get("agent_scheduler_loop", {}) if isinstance(evidence.get("agent_scheduler_loop", {}), dict) else {}
    checks.append(
        {
            "check": "agent_scheduler_loop",
            "status": "passed" if int(scheduler.get("acked_count", 0) or 0) > 0 and int(scheduler.get("error_count", 0) or 0) == 0 else "failed",
            "observed": int(scheduler.get("acked_count", 0) or 0),
            "expected": 1,
            "error_count": int(scheduler.get("error_count", 0) or 0),
        }
    )
    timeline = evidence.get("trace_timeline_summary", {}) if isinstance(evidence.get("trace_timeline_summary", {}), dict) else {}
    by_type = timeline.get("by_type", {}) if isinstance(timeline.get("by_type", {}), dict) else {}
    required_span_types = {"node_run", "agent_run", "model_call", "cost", "gate"}
    missing_span_types = sorted(required_span_types - {str(key) for key, count in by_type.items() if int(count or 0) > 0})
    checks.append(
        {
            "check": "trace_span_coverage",
            "status": "passed" if not missing_span_types else "failed",
            "observed": len(required_span_types) - len(missing_span_types),
            "expected": len(required_span_types),
            "missing_span_types": missing_span_types,
        }
    )
    return checks


def _path_exists(storage: LocalStorage, value: str | Path) -> bool:
    if not str(value).strip():
        return False
    path = Path(value)
    resolved = path if path.is_absolute() else storage.root / path
    return resolved.exists() and resolved.is_file()


def _path_asset_type(storage: LocalStorage, value: str | Path) -> str:
    if not str(value).strip():
        return ""
    try:
        return storage.read_asset(resolve_path(storage.root, value)).type
    except Exception:
        return ""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _quality_trends(storage: LocalStorage, *, project_id: str | None) -> dict[str, Any]:
    reports = _project_assets(storage, "quality_score_report", "reviews", project_id=project_id)
    scores = []
    for item in reports:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        score = content.get("overall_score") or content.get("score") or content.get("total_score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    return {"report_count": len(reports), "average_score": round(sum(scores) / len(scores), 2) if scores else 0, "trend": "insufficient_data" if len(scores) < 2 else ("improving" if scores[-1] >= scores[0] else "declining")}


def _scale_acceptance_metrics(storage: LocalStorage, *, project_id: str | None, chapter_count: int) -> dict[str, Any]:
    runs = _project_assets(storage, "chapter_production_run", "runs", project_id=project_id)
    succeeded_runs = [item for item in runs if str((item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}).get("status", "")) == "succeeded"]
    drafts = _project_assets(storage, "draft_version", "drafts", project_id=project_id)
    contexts = _project_assets(storage, "context_bundle", "contexts", project_id=project_id)
    reviews = _project_assets(storage, "review_report", "reviews", project_id=project_id)
    continuity_reports = _project_assets(storage, "chapter_continuity_report", "continuity", project_id=project_id)
    model_calls = _project_assets(storage, "model_call_log", "runs", project_id=project_id)
    cost_ledgers = _project_assets(storage, "cost_ledger", "runs", project_id=project_id)
    rollbacks = _project_assets(storage, "rollback_result", "runs", project_id=project_id)
    feedback_backflows = _project_assets(storage, "feedback_backflow_plan", "feedback", project_id=project_id)
    review_scores = [
        float(item.get("score", 0))
        for item in reviews
        if isinstance(item.get("score"), (int, float))
    ]
    continuity_conflicts = 0
    unresolved_foreshadowing = 0
    for item in continuity_reports:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        continuity_conflicts += len(content.get("blocking_violations", [])) if isinstance(content.get("blocking_violations", []), list) else 0
        dimensions = content.get("dimensions", {}) if isinstance(content.get("dimensions", {}), dict) else {}
        foreshadowing = dimensions.get("foreshadowing_lifecycle", {}) if isinstance(dimensions.get("foreshadowing_lifecycle", {}), dict) else {}
        unresolved_foreshadowing += int(foreshadowing.get("open_count", 0) or 0) if isinstance(foreshadowing.get("open_count", 0), (int, float)) else 0
    total_cost = 0.0
    for item in cost_ledgers:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        amount = content.get("amount", 0)
        if isinstance(amount, (int, float)):
            total_cost += float(amount)
    dirty_count = _novel_kg_dirty_count(storage, project_id=project_id)
    observed_chapters = max(
        len({str((item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}).get("chapter", "")) for item in runs if (item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}).get("chapter", "")}),
        len(drafts),
        len(contexts),
    )
    return {
        "target_chapter_count": chapter_count,
        "observed_chapter_count": observed_chapters,
        "workflow_success_rate": round(len(succeeded_runs) / len(runs), 4) if runs else 0,
        "chapter_production_run_count": len(runs),
        "draft_version_count": len(drafts),
        "context_bundle_count": len(contexts),
        "review_report_count": len(reviews),
        "average_review_score": round(sum(review_scores) / len(review_scores), 2) if review_scores else 0,
        "quality_drift": "insufficient_data" if len(review_scores) < 2 else ("improving" if review_scores[-1] >= review_scores[0] else "declining"),
        "continuity_conflict_count": continuity_conflicts,
        "kg_dirty_count": dirty_count,
        "unresolved_foreshadowing_count": unresolved_foreshadowing,
        "cost_total": round(total_cost, 6),
        "cost_per_chapter": round(total_cost / max(observed_chapters, 1), 6),
        "model_call_count": len(model_calls),
        "rollback_recovery_count": len(rollbacks),
        "feedback_backflow_count": len(feedback_backflows),
    }


def _canon_conflicts(storage: LocalStorage, *, project_id: str | None) -> list[dict[str, Any]]:
    reports = _project_assets(storage, "chapter_continuity_report", "continuity", project_id=project_id)
    conflicts: list[dict[str, Any]] = []
    for item in reports:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        for violation in content.get("blocking_violations", []) if isinstance(content.get("blocking_violations", []), list) else []:
            conflicts.append({"report_id": item.get("id", ""), "severity": violation.get("severity", ""), "message": violation.get("message", "")})
    return conflicts[:50]


def _novel_kg_dirty_count(storage: LocalStorage, *, project_id: str | None) -> int:
    path = storage.data_root / "indexes" / "novel_kg_dirty.json"
    if not path.exists():
        return 0
    try:
        data = storage.read_json(path)
    except Exception:
        return 0
    entries = data.get("entries", []) if isinstance(data, dict) and isinstance(data.get("entries", []), list) else []
    if not project_id:
        return len(entries)
    return len([entry for entry in entries if isinstance(entry, dict) and str(entry.get("project_id", "")) == project_id])


def _publish_gate_summary(storage: LocalStorage, *, project_id: str | None) -> dict[str, int]:
    reports = _project_assets(storage, "publish_gate_report", "publishing", project_id=project_id)
    summary = {"ready": 0, "needs_revision": 0, "blocked": 0}
    for item in reports:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        decision = str(content.get("decision", "blocked"))
        if decision in summary:
            summary[decision] += 1
    return summary


def _assets_by_type(storage: LocalStorage, asset_type: str, category: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in storage.list_json(category):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("type") == asset_type:
            rows.append(data)
    return rows


def _project_assets(storage: LocalStorage, asset_type: str, category: str, *, project_id: str | None) -> list[dict[str, Any]]:
    rows = _assets_by_type(storage, asset_type, category)
    if not project_id:
        return rows
    return [item for item in rows if isinstance(item.get("metadata", {}), dict) and str(item["metadata"].get("project_id", "")) == project_id]


def _write(storage: LocalStorage, asset: LocalOpsDrillReport | LongChainAcceptanceReport) -> dict[str, Any]:
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
