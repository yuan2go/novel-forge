from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.production_context import project_scope_from_asset
from novel_forge.schemas import ProjectMetricSnapshot, validate_common_fields
from novel_forge.storage.local import LocalStorage


def list_project_metric_snapshots(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in reversed(storage.list_json("runs")):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "project_metric_snapshot":
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(metadata.get("project_id", content.get("project_id", ""))) != project_id:
            continue
        rows.append(_snapshot_row(storage, path, data))
        if len(rows) >= limit:
            break
    return rows


def create_project_metric_snapshot(
    storage: LocalStorage,
    *,
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    project = project_scope_from_asset(storage, {"metadata": {"project_id": project_id or ""}}, workspace_path=workspace_path)
    resolved_project_id = str(project.get("project_id") or project_id or "")
    workspace = str(project.get("workspace_path") or workspace_path or "")
    with AgentExecutionContext(
        storage,
        agent_key="metrics",
        operation="create-project-metric-snapshot",
        output_types=["project_metric_snapshot"],
        workspace_path=workspace,
        sla_seconds=180,
    ) as run:
        run.guard("collect_metrics")
        metrics = _collect_metrics(storage, project_id=resolved_project_id)
        previous = _latest_snapshot(storage, project_id=resolved_project_id)
        asset = ProjectMetricSnapshot(
            title=f"Metric snapshot {project.get('title') or resolved_project_id or 'local'} {utc_now()}",
            tags=["metric", "snapshot", "production-observability"],
            content={
                "project_id": resolved_project_id or "local",
                "workspace_path": workspace,
                "snapshot_at": utc_now(),
                "throughput": metrics["throughput"],
                "quality": metrics["quality"],
                "task_health": metrics["task_health"],
                "agent_health": metrics["agent_health"],
                "storage_health": metrics["storage_health"],
                "trends": _trend_metrics(metrics, previous),
                "model_cost": metrics["model_cost"],
                "originality": metrics["originality"],
                "recommendations": _recommendations(metrics),
            },
            metadata={
                "project_id": resolved_project_id,
                "workspace_path": workspace,
                "workflow": "project-metric-snapshot",
                "risk_level": _risk_level(metrics),
            },
            references=[workspace] if workspace else [],
        )
        run.guard("write_project_metric_snapshot", "project_metric_snapshot")
        result = _write(storage, asset)
        run.succeed(output_assets=[result["path"]])
        return result


def _collect_metrics(storage: LocalStorage, *, project_id: str) -> dict[str, Any]:
    assets = _project_assets(storage, project_id)
    by_type: dict[str, int] = {}
    for item in assets:
        by_type[item.get("type", "")] = by_type.get(item.get("type", ""), 0) + 1
    task_rows = [item for item in assets if item.get("type") in {"task_status", "batch_task_item", "task_dead_letter"}]
    agent_rows = [item for item in assets if str(item.get("type", "")).startswith("agent_")]
    reviews = [item for item in assets if item.get("type") in {"review_report", "quality_score_report", "chapter_audit_report"}]
    originality = [item for item in assets if item.get("type") == "originality_report"]
    publish_gates = [item for item in assets if item.get("type") == "publish_gate_report"]
    benchmark_runs = [item for item in assets if item.get("type") == "model_benchmark_run"]
    return {
        "throughput": {
            "asset_count": len(assets),
            "draft_count": by_type.get("draft_chapter", 0) + by_type.get("draft_version", 0),
            "chapter_plan_count": by_type.get("chapter_plan", 0) + by_type.get("chapter_plan_version", 0),
            "review_count": len(reviews),
            "publish_package_count": by_type.get("release_package", 0),
            "feedback_report_count": by_type.get("reader_sentiment_report", 0) + by_type.get("feedback_insight", 0),
        },
        "quality": _quality_metrics(reviews, originality, publish_gates),
        "task_health": _task_metrics(task_rows),
        "agent_health": _agent_metrics(agent_rows),
        "storage_health": {
            "data_dirs": len(DATA_DIRS),
            "asset_types": len([key for key, value in by_type.items() if key and value]),
            "project_scoped_asset_count": len([item for item in assets if _project_id(item) == project_id and project_id]),
            "global_asset_count": len([item for item in assets if not _project_id(item)]),
        },
        "model_cost": _model_cost_metrics(agent_rows, benchmark_runs),
        "originality": _originality_metrics(originality),
    }


def _project_assets(storage: LocalStorage, project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if project_id and _project_id(data) != project_id:
                continue
            rows.append({"path": _display_path(storage.root, path), **data})
    return rows


def _quality_metrics(reviews: list[dict[str, Any]], originality: list[dict[str, Any]], publish_gates: list[dict[str, Any]]) -> dict[str, Any]:
    scores: list[float] = []
    pass_count = 0
    for item in reviews:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        if isinstance(content.get("overall_score"), (int, float)):
            scores.append(float(content["overall_score"]))
        if isinstance(item.get("score"), (int, float)):
            scores.append(float(item["score"]))
        if content.get("recommendation") in {"pass", "pass_publish_gate"}:
            pass_count += 1
    high_originality = 0
    for item in originality:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        if content.get("risk_level") == "high":
            high_originality += 1
    ready_gates = 0
    for item in publish_gates:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        if content.get("decision") == "ready":
            ready_gates += 1
    return {
        "average_review_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "review_pass_rate": round(pass_count / len(reviews), 4) if reviews else 0.0,
        "originality_risk_rate": round(high_originality / len(originality), 4) if originality else 0.0,
        "publish_gate_ready_rate": round(ready_gates / len(publish_gates), 4) if publish_gates else 0.0,
    }


def _task_metrics(task_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"failed": 0, "running": 0, "waiting_handoff": 0, "dead_letters": 0, "completed": 0}
    for item in task_rows:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        status = str(content.get("status", ""))
        if item.get("type") == "task_dead_letter":
            counts["dead_letters"] += 1
        if status in counts:
            counts[status] += 1
    return counts


def _agent_metrics(agent_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"runs": 0, "failed": 0, "dead_letter": 0, "waiting_human": 0, "succeeded": 0, "sla_breaches": 0}
    for item in agent_rows:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        if item.get("type") == "agent_run":
            counts["runs"] += 1
            status = str(content.get("status", ""))
            if status in counts:
                counts[status] += 1
        if item.get("type") == "agent_sla_report" and content.get("breach") is True:
            counts["sla_breaches"] += 1
    return counts


def _model_cost_metrics(agent_rows: list[dict[str, Any]], benchmark_runs: list[dict[str, Any]]) -> dict[str, Any]:
    token_used = 0
    cost_estimate = 0.0
    ledger_cost = 0.0
    ledger_count = 0
    provider_counts: dict[str, int] = {}
    for item in agent_rows:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        if item.get("type") == "cost_ledger":
            ledger_count += 1
            try:
                ledger_cost += float(content.get("amount") or 0)
            except (TypeError, ValueError):
                pass
            metadata = content.get("metadata", {}) if isinstance(content.get("metadata", {}), dict) else {}
            provider = str(metadata.get("provider") or "ledger")
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            continue
        if item.get("type") != "agent_run":
            continue
        token_used += int(content.get("token_used") or 0)
        try:
            cost_estimate += float(content.get("cost_estimate") or 0)
        except (TypeError, ValueError):
            pass
        provider = str(content.get("model_provider") or "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1
    benchmark_cost = 0.0
    for item in benchmark_runs:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        scores = content.get("scores", {}) if isinstance(content.get("scores", {}), dict) else {}
        benchmark_cost += float(scores.get("cost_estimate", 0) or 0)
    return {
        "token_used": token_used,
        "cost_estimate": round((ledger_cost if ledger_count else cost_estimate) + benchmark_cost, 6),
        "ledger_cost": round(ledger_cost, 6),
        "ledger_count": ledger_count,
        "provider_counts": provider_counts,
        "benchmark_run_count": len(benchmark_runs),
    }


def _originality_metrics(originality: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for item in originality:
        content = item.get("content", {}) if isinstance(item.get("content", {}), dict) else {}
        risk = str(content.get("risk_level") or content.get("overall_risk") or "unknown")
        if risk not in counts:
            risk = "unknown"
        counts[risk] += 1
    total = sum(counts.values())
    return {
        "risk_counts": counts,
        "high_or_medium_count": counts["high"] + counts["medium"],
        "risk_rate": round((counts["high"] + counts["medium"]) / total, 4) if total else 0.0,
    }


def _latest_snapshot(storage: LocalStorage, *, project_id: str) -> dict[str, Any] | None:
    for path in reversed(storage.list_json("runs")):
        try:
            data = storage.read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("type") != "project_metric_snapshot":
            continue
        if project_id and _project_id(data) != project_id:
            continue
        return data
    return None


def _trend_metrics(metrics: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    previous_content = previous.get("content", {}) if isinstance(previous, dict) and isinstance(previous.get("content", {}), dict) else {}
    return {
        "asset_delta": _delta(metrics["throughput"].get("asset_count", 0), previous_content.get("throughput", {}).get("asset_count", 0)),
        "draft_delta": _delta(metrics["throughput"].get("draft_count", 0), previous_content.get("throughput", {}).get("draft_count", 0)),
        "quality_delta": _delta(metrics["quality"].get("average_review_score", 0), previous_content.get("quality", {}).get("average_review_score", 0)),
        "failed_task_delta": _delta(metrics["task_health"].get("failed", 0), previous_content.get("task_health", {}).get("failed", 0)),
        "agent_failure_delta": _delta(metrics["agent_health"].get("failed", 0), previous_content.get("agent_health", {}).get("failed", 0)),
        "originality_risk_delta": _delta(metrics["originality"].get("high_or_medium_count", 0), previous_content.get("originality", {}).get("high_or_medium_count", 0)),
    }


def _delta(current: Any, previous: Any) -> float:
    try:
        return round(float(current or 0) - float(previous or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def _recommendations(metrics: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    task = metrics["task_health"]
    agent = metrics["agent_health"]
    quality = metrics["quality"]
    if task["failed"] or task["dead_letters"]:
        recommendations.append("repair failed tasks and dead letters before starting large batch runs")
    if task["waiting_handoff"]:
        recommendations.append("complete waiting handoffs to unblock batch processing")
    if agent["failed"] or agent["dead_letter"]:
        recommendations.append("inspect failed agent runs and retry from checkpoint or rollback outputs")
    if quality["average_review_score"] and quality["average_review_score"] < 75:
        recommendations.append("raise chapter quality before publishing by regenerating revision plans")
    if quality["originality_risk_rate"] > 0:
        recommendations.append("resolve high originality risk reports before release")
    return recommendations or ["current project metrics do not show blocking production risks"]


def _risk_level(metrics: dict[str, Any]) -> str:
    if metrics["task_health"]["dead_letters"] or metrics["quality"]["originality_risk_rate"] > 0:
        return "high"
    if metrics["task_health"]["failed"] or metrics["agent_health"]["failed"]:
        return "medium"
    return "low"


def _snapshot_row(storage: LocalStorage, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    return {
        "path": _display_path(storage.root, path),
        "id": data.get("id", ""),
        "title": data.get("title") or data.get("name", ""),
        "project_id": metadata.get("project_id", content.get("project_id", "")),
        "workspace_path": metadata.get("workspace_path", content.get("workspace_path", "")),
        "snapshot_at": content.get("snapshot_at", data.get("updated_at", "")),
        "throughput": content.get("throughput", {}),
        "quality": content.get("quality", {}),
        "task_health": content.get("task_health", {}),
        "agent_health": content.get("agent_health", {}),
        "storage_health": content.get("storage_health", {}),
        "trends": content.get("trends", {}),
        "model_cost": content.get("model_cost", {}),
        "originality": content.get("originality", {}),
        "recommendations": content.get("recommendations", []),
        "risk_level": metadata.get("risk_level", "unknown"),
        "updated_at": data.get("updated_at", ""),
    }


def _project_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    if data.get("type") == "project_workspace_state":
        return str(content.get("project_id") or data.get("id") or "")
    return str(metadata.get("project_id") or content.get("project_id") or "")


def _write(storage: LocalStorage, asset: Any) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": data, "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
