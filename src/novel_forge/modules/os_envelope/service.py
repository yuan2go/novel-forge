from __future__ import annotations

import os
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.storage.local import LocalStorage

OS_ENVELOPE_VERSION = "0.1.0"
PRODUCTION_ENVIRONMENTS = {"production", "prod", "operating_system", "strict"}
COMPAT_ENVIRONMENTS = {"", "dev", "development", "test", "sample", "fixture", "compat", "local"}
REQUIRED_PRODUCTION_FIELDS = ("project_id", "task_type", "asset_type", "actor_type", "source", "trace_id", "source_policy", "environment")


def normalize_os_envelope(
    payload: dict[str, Any] | None,
    *,
    operation: str,
    project_id: str = "",
    task_type: str = "",
    asset_type: str = "",
    actor_type: str = "service",
    actor_id: str = "",
    source: str = "novel_os",
    version: str = OS_ENVELOPE_VERSION,
    context_bundle_id: str = "",
    trace_id: str = "",
    provider: str = "",
    model: str = "",
    cost_ledger: dict[str, Any] | None = None,
    token_budget: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    environment: str = "",
    bypass_reason: str = "",
) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    resolved_environment = _environment(raw.get("environment") or environment)
    resolved_project_id = str(raw.get("project_id") or project_id or "").strip()
    resolved_task_type = str(raw.get("task_type") or task_type or operation or "").strip()
    resolved_asset_type = str(raw.get("asset_type") or asset_type or "").strip()
    resolved_trace_id = str(raw.get("trace_id") or trace_id or "").strip()
    envelope_seed = f"{resolved_project_id}:{resolved_task_type}:{resolved_asset_type}:{operation}:{resolved_trace_id}:{utc_now()}"
    resolved_source_policy = raw.get("source_policy") if isinstance(raw.get("source_policy"), dict) else (source_policy or {})
    if not resolved_source_policy:
        resolved_source_policy = {"raw_source_text_allowed": False, "generation_rag_allowed": False}
    return {
        "envelope_id": str(raw.get("envelope_id") or make_id("os_envelope", envelope_seed)),
        "project_id": resolved_project_id,
        "task_type": resolved_task_type,
        "asset_type": resolved_asset_type,
        "actor_type": str(raw.get("actor_type") or actor_type or "service"),
        "actor_id": str(raw.get("actor_id") or actor_id or ""),
        "source": str(raw.get("source") or source or "novel_os"),
        "version": str(raw.get("version") or version or OS_ENVELOPE_VERSION),
        "context_bundle_id": str(raw.get("context_bundle_id") or context_bundle_id or ""),
        "trace_id": resolved_trace_id or make_id("trace", envelope_seed),
        "provider": str(raw.get("provider") or provider or ""),
        "model": str(raw.get("model") or model or ""),
        "cost_ledger": raw.get("cost_ledger") if isinstance(raw.get("cost_ledger"), dict) else (cost_ledger or {}),
        "token_budget": raw.get("token_budget") if isinstance(raw.get("token_budget"), dict) else (token_budget or {}),
        "source_policy": resolved_source_policy,
        "environment": resolved_environment,
        "bypass_reason": str(raw.get("bypass_reason") or bypass_reason or ""),
        "operation": str(raw.get("operation") or operation or ""),
        "created_at": str(raw.get("created_at") or utc_now()),
    }


def enforce_os_envelope(
    storage: LocalStorage,
    *,
    envelope_payload: dict[str, Any] | None,
    operation: str,
    project_id: str = "",
    task_type: str = "",
    asset_type: str = "",
    actor_type: str = "service",
    actor_id: str = "",
    source: str = "novel_os",
    context_bundle_id: str = "",
    trace_id: str = "",
    provider: str = "",
    model: str = "",
    cost_ledger: dict[str, Any] | None = None,
    token_budget: dict[str, Any] | None = None,
    source_policy: dict[str, Any] | None = None,
    environment: str = "",
    bypass_reason: str = "",
    require_for_production: bool = True,
    record_trace: bool = True,
) -> dict[str, Any]:
    supplied = isinstance(envelope_payload, dict) and bool(envelope_payload)
    envelope = normalize_os_envelope(
        envelope_payload,
        operation=operation,
        project_id=project_id,
        task_type=task_type,
        asset_type=asset_type,
        actor_type=actor_type,
        actor_id=actor_id,
        source=source,
        context_bundle_id=context_bundle_id,
        trace_id=trace_id,
        provider=provider,
        model=model,
        cost_ledger=cost_ledger,
        token_budget=token_budget,
        source_policy=source_policy,
        environment=environment,
        bypass_reason=bypass_reason,
    )
    production = _is_production(envelope["environment"])
    if require_for_production and production and not supplied:
        raise ValueError(f"OS envelope required for production operation {operation}")
    missing = _missing_production_fields(envelope)
    if require_for_production and production and missing:
        raise ValueError(f"OS envelope missing required fields for production operation {operation}: {', '.join(missing)}")
    if not production and not supplied and envelope.get("bypass_reason"):
        envelope["status"] = "bypassed"
    elif not production and not supplied:
        envelope["status"] = "compat"
    else:
        envelope["status"] = "enforced"
    if record_trace and (supplied or production or envelope.get("bypass_reason")):
        trace = record_trace_span(
            storage,
            trace_id=envelope["trace_id"],
            span_type="os_envelope",
            name=operation,
            status="succeeded" if envelope["status"] != "blocked" else "failed",
            attributes={
                "envelope_id": envelope["envelope_id"],
                "operation": operation,
                "asset_type": asset_type,
                "environment": envelope["environment"],
                "status": envelope["status"],
                "bypass_reason": envelope.get("bypass_reason", ""),
                "source_policy": envelope.get("source_policy", {}),
            },
            references=[envelope["envelope_id"]],
            project_id=envelope["project_id"],
            workspace_path="",
        )
        envelope["trace_span_path"] = trace.get("path", "")
    return envelope


def envelope_asset_metadata(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict) or not envelope:
        return {}
    return {
        "os_envelope": envelope,
        "os_envelope_id": envelope.get("envelope_id", ""),
        "trace_id": envelope.get("trace_id", ""),
        "source_policy": envelope.get("source_policy", {}),
        "environment": envelope.get("environment", ""),
        "bypass_reason": envelope.get("bypass_reason", ""),
    }


def envelope_response(data: Any, envelope: dict[str, Any] | None = None, *, success: bool = True, error: dict[str, Any] | None = None) -> dict[str, Any]:
    env = envelope if isinstance(envelope, dict) else {}
    return {
        "success": bool(success),
        "request_id": str(env.get("envelope_id") or make_id("request", utc_now())),
        "trace_id": str(env.get("trace_id") or ""),
        "envelope": env,
        "data": data,
        "error": error or {},
    }


def _environment(value: Any) -> str:
    raw = str(value or os.environ.get("NOVEL_FORGE_ENVIRONMENT", "dev")).strip().lower()
    if raw in PRODUCTION_ENVIRONMENTS:
        return "production"
    if raw in COMPAT_ENVIRONMENTS:
        return raw or "dev"
    return raw


def _is_production(environment: str) -> bool:
    return _environment(environment) == "production"


def is_production_environment(environment: str | None = None) -> bool:
    return _is_production(_environment(environment or ""))


def _missing_production_fields(envelope: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_PRODUCTION_FIELDS:
        value = envelope.get(field)
        if field == "source_policy":
            if not isinstance(value, dict) or not value:
                missing.append(field)
        elif not str(value or "").strip():
            missing.append(field)
    return missing
