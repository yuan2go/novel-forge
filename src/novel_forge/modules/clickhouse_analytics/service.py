from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.infrastructure.legacy_http import (
    LegacyHttpRequestError,
    development_only_http_request,
)
from novel_forge.modules.common import resolve_path
from novel_forge.modules.production_context import filter_project_safe_references
from novel_forge.modules.production_execution import (
    ExternalActionExecutionPort,
    ExternalActionKind,
    execute_external_action,
)
from novel_forge.schemas import BaseAsset, validate_common_fields
from novel_forge.storage.local import LocalStorage

ANALYTICS_SOURCE_CATEGORIES = [
    "runs",
    "reviews",
    "publishing",
    "feedback",
    "contexts",
    "loops",
    "continuity",
]

ANALYTICS_SOURCE_TYPES = {
    "agent_run",
    "agent_event",
    "agent_budget",
    "agent_failure_report",
    "agent_rollback_report",
    "trace_span",
    "gate_result",
    "model_call_log",
    "cost_ledger",
    "review_issue",
    "evaluation_result",
    "evaluation_run",
    "evaluation_gate",
    "model_benchmark_run",
    "context_bundle",
    "rag_quality_report",
    "hybrid_retrieval_report",
    "publish_gate_report",
    "release_package",
    "feedback_insight",
    "reader_sentiment_report",
    "reader_feedback_backflow_report",
    "loop_run",
    "loop_step",
    "loop_report",
    "longform_recap_report",
    "quality_score_report",
    "chapter_audit_report",
}


def analytics_capabilities(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    online = _online_enabled()
    return {
        "role": "optional_olap_analytics_layer",
        "local_first": True,
        "online_enabled": online,
        "strict": _strict(),
        "url_configured": bool(os.environ.get("NOVEL_FORGE_CLICKHOUSE_URL", "")),
        "database": os.environ.get("NOVEL_FORGE_CLICKHOUSE_DATABASE", "novel_forge"),
        "default_mode": "offline_snapshot",
        "business_writeback": False,
        "project_id": project_id,
        "source_types": sorted(ANALYTICS_SOURCE_TYPES),
        "local_event_count": len(_analytics_events(storage, project_id=project_id)),
        "status": "online_ready" if online and os.environ.get("NOVEL_FORGE_CLICKHOUSE_URL") else "offline_ready",
    }


def clickhouse_schema_plan(storage: LocalStorage, *, persist: bool = True) -> dict[str, Any]:
    statements = [
        "create table if not exists analytics_events (event_id String, event_type String, source_asset_id String, source_asset_type String, project_id String, trace_id String, metric_name String, metric_value Float64, occurred_at DateTime64(3), payload_json String) engine = MergeTree order by (project_id, occurred_at, event_type)",
        "create table if not exists analytics_daily_metrics (project_id String, metric_name String, metric_date Date, metric_value Float64, source_event_count UInt64) engine = SummingMergeTree order by (project_id, metric_name, metric_date)",
    ]
    content = {
        "metric_id": "clickhouse-schema-plan",
        "name": "ClickHouse analytics schema plan",
        "query": "\n".join(statements),
        "status": "planned",
        "statements": statements,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="analytics_metric_definition",
        title="ClickHouse analytics schema plan",
        tags=["analytics", "clickhouse", "schema-plan"],
        content=content,
        metadata={"backend": "clickhouse", "online_enabled": _online_enabled()},
    )
    if not persist:
        return {"path": "", "asset": asset.to_dict(), "content": content}
    return _write(storage, asset)


def migrate_clickhouse(
    storage: LocalStorage,
    *,
    dry_run: bool = True,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> dict[str, Any]:
    plan = clickhouse_schema_plan(storage, persist=False)
    if dry_run or not _online_enabled():
        if _strict() and not dry_run and not _online_enabled():
            raise RuntimeError("ClickHouse strict mode requires NOVEL_FORGE_CLICKHOUSE_ONLINE=1")
        return {
            "status": "planned" if dry_run else "offline_skipped",
            "dry_run": dry_run,
            "online_enabled": _online_enabled(),
            "statements": plan["content"]["statements"],
            "capabilities": analytics_capabilities(storage),
        }
    responses = []
    for statement in plan["content"]["statements"]:
        responses.append(
            _clickhouse_execute(
                statement,
                external_action_execution_port=external_action_execution_port,
                environment=environment,
            )
        )
    return {"status": "migrated", "dry_run": False, "responses": responses, "capabilities": analytics_capabilities(storage)}


def project_analytics_events(storage: LocalStorage, *, project_id: str = "", limit: int = 2000, persist: bool = True) -> list[dict[str, Any]]:
    rows = []
    for path in _source_paths(storage):
        data = _read_json_safe(storage, path)
        if data.get("type") not in ANALYTICS_SOURCE_TYPES:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        resolved_project_id = str(metadata.get("project_id") or content.get("project_id") or "")
        if project_id and resolved_project_id != project_id:
            continue
        event = _event_from_asset(storage, data, path, project_id=resolved_project_id)
        if persist:
            written = _write(storage, _analytics_event_asset(storage, event, source_path=path))
            event["path"] = written["path"]
        rows.append(event)
        if len(rows) >= max(1, int(limit or 2000)):
            break
    return rows


def sync_analytics(
    storage: LocalStorage,
    *,
    project_id: str = "",
    online: bool | None = None,
    limit: int = 2000,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> dict[str, Any]:
    events = project_analytics_events(storage, project_id=project_id, limit=limit, persist=True)
    requested_online = _online_enabled() if online is None else bool(online)
    online_status = {"status": "disabled"}
    if requested_online:
        if not _online_enabled():
            if _strict():
                raise RuntimeError("ClickHouse online sync requested but NOVEL_FORGE_CLICKHOUSE_ONLINE is not enabled")
            online_status = {"status": "skipped", "reason": "online not enabled"}
        else:
            online_status = _sync_online(
                events,
                external_action_execution_port=external_action_execution_port,
                environment=environment,
            )
    status = "completed" if online_status.get("status") in {"disabled", "skipped", "inserted"} else "completed_with_online_error"
    asset = BaseAsset(
        type="analytics_sync_job",
        title=f"Analytics sync {status}",
        tags=["analytics", "sync", status],
        content={
            "job_id": make_id("analytics_sync", f"{project_id}-{utc_now()}"),
            "status": status,
            "project_id": project_id or "local-system",
            "event_count": len(events),
            "online_clickhouse": online_status,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "status": status, "event_count": len(events), "online_enabled": requested_online},
        references=filter_project_safe_references(storage, project_id, [str(event.get("source_path", "")) for event in events]),
    )
    written = _write(storage, asset)
    return {**written, "event_count": len(events), "online_clickhouse": online_status}


def clickhouse_online_e2e_smoke(
    storage: LocalStorage,
    *,
    project_id: str = "",
    require_online: bool = False,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> dict[str, Any]:
    capabilities = analytics_capabilities(storage, project_id=project_id)
    results: list[dict[str, Any]] = [{"scenario": "capabilities", "status": capabilities["status"], "online_enabled": capabilities["online_enabled"]}]
    status = "passed"
    if require_online and not capabilities["online_enabled"]:
        status = "failed"
        results.append({"scenario": "online_required", "status": "failed", "message": "NOVEL_FORGE_CLICKHOUSE_ONLINE is not enabled"})
    try:
        migration = migrate_clickhouse(
            storage,
            dry_run=not capabilities["online_enabled"],
            external_action_execution_port=external_action_execution_port,
            environment=environment,
        )
        results.append({"scenario": "migrate", "status": migration["status"], "dry_run": migration["dry_run"]})
        sync = sync_analytics(
            storage,
            project_id=project_id,
            online=capabilities["online_enabled"],
            limit=200,
            external_action_execution_port=external_action_execution_port,
            environment=environment,
        )
        results.append({"scenario": "sync", "status": sync["asset"]["content"]["status"], "event_count": sync["event_count"], "online_clickhouse": sync["online_clickhouse"]})
        if capabilities["online_enabled"] and sync["online_clickhouse"].get("status") != "inserted":
            status = "failed" if require_online else "warning"
        snapshot = analytics_dashboard_snapshot(storage, project_id=project_id)
        results.append({"scenario": "dashboard_snapshot", "status": "passed", "path": snapshot["path"]})
    except Exception as exc:
        if require_online or _strict():
            raise
        status = "warning"
        results.append({"scenario": "online_service", "status": "warning", "error": f"{type(exc).__name__}: {exc}"})
    if not capabilities["online_enabled"] and status == "passed":
        status = "warning"
        results.append({"scenario": "online_service", "status": "warning", "message": "online ClickHouse disabled; offline dashboard proof only"})
    content = {
        "drill_id": make_id("clickhouse_online_smoke", f"{project_id}-{utc_now()}"),
        "scenarios": [
            {"name": "capabilities"},
            {"name": "migrate", "online_required": require_online},
            {"name": "sync_analytics"},
            {"name": "offline_dashboard_snapshot"},
        ],
        "results": results,
        "recovery_actions": [
            "set NOVEL_FORGE_CLICKHOUSE_ONLINE=1 and NOVEL_FORGE_CLICKHOUSE_URL for real OLAP verification",
            "keep ClickHouse read-only/analytics-only; do not write back business state",
        ],
        "status": status,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="local_ops_drill_report",
        title="ClickHouse online E2E smoke proof",
        tags=["clickhouse", "online-smoke", status],
        content=content,
        metadata={"project_id": project_id, "backend": "clickhouse", "online_enabled": capabilities["online_enabled"]},
    )
    written = _write(storage, asset)
    return {**written, "status": status, "content": content}


def analytics_dashboard_snapshot(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    events = _analytics_events(storage, project_id=project_id)
    metrics = {
        "quality_trend": quality_trends(storage, project_id=project_id),
        "agent": agent_metrics(storage, project_id=project_id),
        "evaluation": evaluation_metrics(storage, project_id=project_id),
        "cost": cost_metrics(storage, project_id=project_id),
        "feedback": feedback_metrics(storage, project_id=project_id),
        "event_count": len(events),
    }
    asset = BaseAsset(
        type="analytics_dashboard_snapshot",
        title="Analytics dashboard snapshot",
        tags=["analytics", "dashboard", "offline"],
        content={
            "snapshot_id": make_id("analytics_dashboard", f"{project_id}-{utc_now()}"),
            "project_id": project_id or "local-system",
            "metrics": metrics,
            "source": "local_storage_projection",
            "clickhouse_online": _online_enabled(),
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "event_count": len(events), "online_enabled": _online_enabled()},
        references=filter_project_safe_references(storage, project_id, [str(event.get("path", "")) for event in events if event.get("path")]),
    )
    return _write(storage, asset)


def quality_trends(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    scores = []
    for event in _analytics_events(storage, project_id=project_id):
        if event.get("content", {}).get("metric_name") in {"quality_score", "evaluation_score"}:
            scores.append(float(event.get("content", {}).get("metric_value", 0) or 0))
    return {"count": len(scores), "average": _avg(scores), "latest": scores[-10:]}


def agent_metrics(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    events = [event for event in _analytics_events(storage, project_id=project_id) if event.get("content", {}).get("source_asset_type") in {"agent_run", "agent_event", "agent_failure_report"}]
    statuses: dict[str, int] = {}
    for event in events:
        payload = event.get("content", {}).get("payload", {}) if isinstance(event.get("content", {}).get("payload", {}), dict) else {}
        status = str(payload.get("status") or event.get("content", {}).get("event_type") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    failed = sum(count for status, count in statuses.items() if status in {"failed", "dead_letter", "cancelled"})
    return {"event_count": len(events), "by_status": statuses, "failure_rate": round(failed / max(1, len(events)), 4)}


def evaluation_metrics(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    values = [
        float(event.get("content", {}).get("metric_value", 0) or 0)
        for event in _analytics_events(storage, project_id=project_id)
        if event.get("content", {}).get("event_type") == "evaluation"
    ]
    return {"result_count": len(values), "average_score": _avg(values), "block_count": sum(1 for value in values if value < 0.55)}


def cost_metrics(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    costs = [
        float(event.get("content", {}).get("metric_value", 0) or 0)
        for event in _analytics_events(storage, project_id=project_id)
        if event.get("content", {}).get("metric_name") == "cost"
    ]
    return {"event_count": len(costs), "total_cost": round(sum(costs), 6), "average_cost": _avg(costs)}


def feedback_metrics(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    events = [
        event
        for event in _analytics_events(storage, project_id=project_id)
        if event.get("content", {}).get("source_asset_type") in {"feedback_insight", "reader_sentiment_report", "reader_feedback_backflow_report"}
    ]
    return {"event_count": len(events), "backflow_event_count": sum(1 for event in events if event.get("content", {}).get("source_asset_type") == "reader_feedback_backflow_report")}


def _event_from_asset(storage: LocalStorage, data: dict[str, Any], path: Path, *, project_id: str) -> dict[str, Any]:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    asset_type = str(data.get("type", ""))
    metric_name, metric_value = _metric_for_asset(asset_type, content, metadata)
    event_type = _event_type(asset_type)
    return {
        "event_id": make_id("analytics_event", f"{data.get('id', '')}-{metric_name}-{utc_now()}"),
        "event_type": event_type,
        "source_asset_id": str(data.get("id", "")),
        "source_asset_type": asset_type,
        "source_path": _display_path(storage.root, path),
        "project_id": project_id,
        "trace_id": str(metadata.get("trace_id") or content.get("trace_id") or ""),
        "metric_name": metric_name,
        "metric_value": metric_value,
        "payload": _summarize_payload(content, metadata),
        "occurred_at": str(content.get("created_at") or data.get("created_at") or utc_now()),
    }


def _analytics_event_asset(storage: LocalStorage, event: dict[str, Any], *, source_path: Path) -> BaseAsset:
    return BaseAsset(
        type="analytics_event",
        title=f"Analytics event {event['event_type']}",
        source=event["source_asset_id"],
        tags=["analytics", event["event_type"], event["source_asset_type"]],
        content=event,
        metadata={"project_id": event["project_id"], "trace_id": event["trace_id"], "event_type": event["event_type"], "source_asset_type": event["source_asset_type"]},
        references=filter_project_safe_references(storage, event["project_id"], [event["source_asset_id"], _display_path(storage.root, source_path)]),
    )


def _metric_for_asset(asset_type: str, content: dict[str, Any], metadata: dict[str, Any]) -> tuple[str, float]:
    if asset_type in {"evaluation_result", "model_benchmark_run"}:
        scores = content.get("scores", {}) if isinstance(content.get("scores", {}), dict) else {}
        return "evaluation_score", float(content.get("overall_score", scores.get("overall", 0)) or 0)
    if asset_type == "quality_score_report":
        return "quality_score", float(content.get("overall_score", content.get("score", 0)) or 0)
    if asset_type == "cost_ledger":
        return "cost", float(content.get("cost", content.get("amount", 0)) or 0)
    if asset_type in {"model_call_log", "agent_budget"}:
        usage = content.get("usage", {}) if isinstance(content.get("usage", {}), dict) else {}
        return "tokens", float(usage.get("total_tokens", content.get("total_tokens", 0)) or 0)
    if asset_type in {"review_issue", "gate_result", "publish_gate_report"}:
        return "blocking", 1.0 if bool(content.get("blocking") or metadata.get("blocking") or content.get("status") in {"failed", "blocked"}) else 0.0
    if asset_type == "loop_run":
        return "loop_status", 1.0 if str(content.get("status")) == "succeeded" else 0.0
    return "event_count", 1.0


def _event_type(asset_type: str) -> str:
    if asset_type in {"evaluation_result", "evaluation_run", "evaluation_gate", "model_benchmark_run"}:
        return "evaluation"
    if asset_type.startswith("agent_") or asset_type == "agent_run":
        return "agent"
    if asset_type in {"cost_ledger", "model_call_log"}:
        return "cost"
    if asset_type in {"feedback_insight", "reader_sentiment_report", "reader_feedback_backflow_report"}:
        return "feedback"
    if asset_type in {"context_bundle", "rag_quality_report", "hybrid_retrieval_report"}:
        return "retrieval"
    if asset_type in {"publish_gate_report", "release_package"}:
        return "publish"
    if asset_type in {"loop_run", "loop_step", "loop_report"}:
        return "loop"
    return "governance"


def _summarize_payload(content: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "status",
        "operation",
        "agent_key",
        "provider",
        "model_name",
        "recommendation",
        "blocking",
        "severity",
        "issue_type",
        "latency_ms",
        "cost_estimate",
        "retrieval_backend",
    ]
    return {key: content.get(key, metadata.get(key)) for key in keys if content.get(key, metadata.get(key)) not in (None, "")}


def _analytics_events(storage: LocalStorage, *, project_id: str = "") -> list[dict[str, Any]]:
    events = []
    for path in storage.list_json("runs"):
        data = _read_json_safe(storage, path)
        if data.get("type") != "analytics_event":
            continue
        content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
        if project_id and str(content.get("project_id", "")) != project_id:
            continue
        events.append({**data, "path": _display_path(storage.root, path)})
    return sorted(events, key=lambda row: str(row.get("content", {}).get("occurred_at", "")))


def _source_paths(storage: LocalStorage) -> list[Path]:
    paths: list[Path] = []
    for category in ANALYTICS_SOURCE_CATEGORIES:
        paths.extend(storage.list_json(category))
    return sorted(paths, key=lambda path: path.stat().st_mtime)


def _sync_online(
    events: list[dict[str, Any]],
    *,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> dict[str, Any]:
    if not events:
        return {"status": "inserted", "row_count": 0}
    try:
        rows = "\n".join(json.dumps(_clickhouse_event_row(event), ensure_ascii=False) for event in events)
        _clickhouse_execute(
            "insert into analytics_events format JSONEachRow\n" + rows,
            external_action_execution_port=external_action_execution_port,
            environment=environment,
        )
        return {"status": "inserted", "row_count": len(events)}
    except Exception as exc:
        if _strict():
            raise
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "row_count": 0}


def _clickhouse_event_row(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id", ""),
        "event_type": event.get("event_type", ""),
        "source_asset_id": event.get("source_asset_id", ""),
        "source_asset_type": event.get("source_asset_type", ""),
        "project_id": event.get("project_id", ""),
        "trace_id": event.get("trace_id", ""),
        "metric_name": event.get("metric_name", ""),
        "metric_value": float(event.get("metric_value", 0) or 0),
        "occurred_at": _clickhouse_datetime(event.get("occurred_at", utc_now())),
        "payload_json": json.dumps(event.get("payload", {}), ensure_ascii=False, sort_keys=True),
    }


def _clickhouse_execute(
    query: str,
    *,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> dict[str, Any]:
    database = os.environ.get("NOVEL_FORGE_CLICKHOUSE_DATABASE", "novel_forge")
    if external_action_execution_port is not None:
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        candidate = execute_external_action(
            capability=ExternalActionKind.ANALYTICS_QUERY_EXECUTE,
            request_payload={
                "database": database,
                "query": query,
                "query_hash": "sha256:" + query_hash,
            },
            stable_idempotency_key=f"analytics.query.execute:{query_hash}",
            data_classification="INTERNAL_ANALYTICS",
            privacy_policy_ref="privacy-policy:analytics:v1",
            rate_limit_policy_ref="rate-limit-policy:clickhouse:v1",
            quota_policy_ref="quota-policy:clickhouse:v1",
            execution_port=external_action_execution_port,
        )
        return {
            **dict(candidate.raw_output),
            "production_execution": candidate.evidence.to_dict(),
        }
    url = os.environ.get("NOVEL_FORGE_CLICKHOUSE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("NOVEL_FORGE_CLICKHOUSE_URL is required for ClickHouse online mode")
    user = os.environ.get("NOVEL_FORGE_CLICKHOUSE_USER", "default")
    password = os.environ.get("NOVEL_FORGE_CLICKHOUSE_PASSWORD", "")
    try:
        response = development_only_http_request(
            component="ClickHouse HTTP",
            url=f"{url}/?database={database}",
            method="POST",
            body=query.encode("utf-8"),
            headers={
                "X-ClickHouse-User": user,
                "X-ClickHouse-Key": password,
            },
            timeout_seconds=2,
            environment=environment,
        )
        return {
            "status": "ok",
            "code": response.status,
            "body": response.body.decode("utf-8")[:500],
            "legacy_development_only": True,
        }
    except LegacyHttpRequestError as exc:
        body = exc.body.decode("utf-8", errors="replace")[:500]
        if exc.status:
            raise RuntimeError(
                f"ClickHouse request failed: HTTP {exc.status}: {body}"
            ) from exc
        raise RuntimeError(f"ClickHouse request failed: {exc}") from exc


def _clickhouse_datetime(value: Any) -> str:
    raw = str(value or utc_now()).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw.replace("T", " ").replace("+00:00", "")[:23]
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]


def _write(storage: LocalStorage, asset: BaseAsset) -> dict[str, Any]:
    data = asset.to_dict()
    errors = validate_common_fields(data)
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "asset": data, "validation": {"ok": True, "errors": []}}


def _read_json_safe(storage: LocalStorage, path: Path) -> dict[str, Any]:
    try:
        data = storage.read_json(resolve_path(storage.root, path))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _display_path(root: Path, path: Path | str) -> str:
    candidate = Path(path)
    try:
        return str(candidate.relative_to(root))
    except ValueError:
        return str(candidate)


def _avg(values: list[float]) -> float:
    return round(sum(values) / max(1, len(values)), 4)


def _online_enabled() -> bool:
    return os.environ.get("NOVEL_FORGE_CLICKHOUSE_ONLINE", "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _strict() -> bool:
    return os.environ.get("NOVEL_FORGE_CLICKHOUSE_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}
