from __future__ import annotations

import os
import hashlib
import json
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.runtime_ledger import record_trace_span
from novel_forge.storage.local import LocalStorage

OS_ENVELOPE_VERSION = "2.0.0"
LEGACY_OS_ENVELOPE_VERSION = "0.1.0"
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
    _reject_ref_conflicts(raw)
    resolved_environment = _environment(raw.get("environment") or environment)
    resolved_project_id = str(raw.get("project_ref") or raw.get("project_id") or project_id or "").strip()
    resolved_task_type = str(raw.get("task_type") or task_type or operation or "").strip()
    resolved_asset_type = str(raw.get("asset_type") or asset_type or "").strip()
    resolved_trace_id = str(raw.get("trace_id") or trace_id or "").strip()
    resolved_operation = str(raw.get("operation") or operation or "").strip()
    canonical_refs = _canonical_refs(raw, project_ref=resolved_project_id, context_bundle_id=context_bundle_id, provider=provider)
    correlation_id = str(raw.get("correlation_id") or resolved_trace_id or "").strip()
    envelope_seed = f"{resolved_project_id}:{resolved_task_type}:{resolved_asset_type}:{operation}:{resolved_trace_id}:{utc_now()}"
    resolved_source_policy = raw.get("source_policy") if isinstance(raw.get("source_policy"), dict) else (source_policy or {})
    if not resolved_source_policy:
        resolved_source_policy = {"raw_source_text_allowed": False, "generation_rag_allowed": False}
    trace_value = resolved_trace_id or make_id("trace", envelope_seed)
    correlation_value = correlation_id or trace_value
    input_refs = _strings(raw.get("input_refs"))
    expected_output_types = _strings(raw.get("expected_output_types"))
    idempotency_key = str(raw.get("idempotency_key") or _stable_idempotency_key(
        project_ref=resolved_project_id,
        operation=resolved_operation,
        task_ref=canonical_refs["task_ref"],
        input_refs=input_refs,
        expected_output_types=expected_output_types,
    ))
    native_v2 = _native_v2(raw)
    return {
        "schema_version": 2,
        "envelope_id": str(raw.get("envelope_id") or make_id("os_envelope", envelope_seed)),
        **canonical_refs,
        "correlation_id": correlation_value,
        "causation_id": str(raw.get("causation_id") or raw.get("parent_span_id") or ""),
        "idempotency_key": idempotency_key,
        "input_refs": input_refs,
        "expected_output_types": expected_output_types,
        "budget": raw.get("budget") if isinstance(raw.get("budget"), dict) else (
            raw.get("token_budget") if isinstance(raw.get("token_budget"), dict) else (token_budget or {})
        ),
        "legacy_derived": not native_v2,
        "legacy_schema_version": "" if native_v2 else str(raw.get("version") or LEGACY_OS_ENVELOPE_VERSION),
        "project_id": resolved_project_id,
        "task_type": resolved_task_type,
        "asset_type": resolved_asset_type,
        "actor_type": str(raw.get("actor_type") or actor_type or "service"),
        "actor_id": str(raw.get("actor_id") or actor_id or ""),
        "source": str(raw.get("source") or source or "novel_os"),
        "version": str(raw.get("version") or version or OS_ENVELOPE_VERSION),
        "context_bundle_id": str(raw.get("context_bundle_id") or context_bundle_id or ""),
        "trace_id": trace_value,
        "provider": str(raw.get("provider") or provider or ""),
        "model": str(raw.get("model") or model or ""),
        "cost_ledger": raw.get("cost_ledger") if isinstance(raw.get("cost_ledger"), dict) else (cost_ledger or {}),
        "token_budget": raw.get("token_budget") if isinstance(raw.get("token_budget"), dict) else (token_budget or {}),
        "source_policy": resolved_source_policy,
        "environment": resolved_environment,
        "bypass_reason": str(raw.get("bypass_reason") or bypass_reason or ""),
        "operation": resolved_operation,
        "created_at": str(raw.get("created_at") or utc_now()),
    }


def _native_v2(raw: dict[str, Any]) -> bool:
    try:
        return int(raw.get("schema_version") or 0) >= 2
    except (TypeError, ValueError):
        return False


def _reject_ref_conflicts(raw: dict[str, Any]) -> None:
    canonical = str(raw.get("project_ref") or "").strip()
    legacy = str(raw.get("project_id") or "").strip()
    if canonical and legacy and canonical != legacy:
        raise ValueError("OS envelope project_ref conflicts with project_id")


def _canonical_refs(
    raw: dict[str, Any],
    *,
    project_ref: str,
    context_bundle_id: str,
    provider: str,
) -> dict[str, str]:
    approval_refs = _strings(raw.get("approval_refs"))
    return {
        "project_ref": project_ref,
        "novel_ref": str(raw.get("novel_ref") or raw.get("novel_id") or ""),
        "workflow_ref": str(raw.get("workflow_ref") or raw.get("workflow_id") or ""),
        "run_ref": str(raw.get("run_ref") or raw.get("workflow_run_ref") or ""),
        "task_ref": str(raw.get("task_ref") or raw.get("task_id") or ""),
        "agent_ref": str(raw.get("agent_ref") or raw.get("agent_id") or ""),
        "artifact_ref": str(raw.get("artifact_ref") or ""),
        "asset_ref": str(raw.get("asset_ref") or ""),
        "context_ref": str(raw.get("context_ref") or raw.get("context_bundle_id") or context_bundle_id or ""),
        "approval_ref": str(raw.get("approval_ref") or (approval_refs[0] if approval_refs else "")),
        "provider_ref": str(raw.get("provider_ref") or raw.get("provider") or provider or ""),
    }


def _stable_idempotency_key(
    *,
    project_ref: str,
    operation: str,
    task_ref: str,
    input_refs: list[str],
    expected_output_types: list[str],
) -> str:
    payload = {
        "project_ref": project_ref,
        "operation": operation,
        "task_ref": task_ref,
        "input_refs": input_refs,
        "expected_output_types": expected_output_types,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"idem-{digest[:32]}"


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
        "os_envelope_schema_version": envelope.get("schema_version", 0),
        "correlation_id": envelope.get("correlation_id", ""),
        "causation_id": envelope.get("causation_id", ""),
        "idempotency_key": envelope.get("idempotency_key", ""),
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


def normalize_environment(value: Any = "", *, envelope_payload: dict[str, Any] | None = None) -> str:
    payload = envelope_payload if isinstance(envelope_payload, dict) else {}
    return _environment(value or payload.get("environment"))


def normalize_runtime_request_policy(
    *,
    envelope_payload: dict[str, Any] | None = None,
    environment: str = "",
    source_policy: dict[str, Any] | None = None,
    operation: str = "",
) -> dict[str, Any]:
    """Normalize API/service request policy before side effects.

    API callers historically passed ``environment`` and ``source_policy`` as
    optional fields beside an OS envelope. Production policy must treat the
    envelope value as authoritative when the top-level field is omitted.
    """

    payload = envelope_payload if isinstance(envelope_payload, dict) else {}
    envelope_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    merged_policy = {**envelope_policy, **(source_policy or {})}
    resolved_environment = normalize_environment(environment, envelope_payload=payload)
    production = is_production_environment(resolved_environment)
    if production:
        merged_policy.setdefault("production_fail_closed", True)
        merged_policy.setdefault("compat_warning_allowed", False)
        merged_policy.setdefault("mkaos_pack_required", True)
        merged_policy.setdefault("source_isolation_required", True)
        merged_policy.setdefault("empty_pack_policy", "block")
    else:
        merged_policy.setdefault("production_fail_closed", False)
        merged_policy.setdefault("compat_warning_allowed", True)
        merged_policy.setdefault("mkaos_pack_required", False)
        merged_policy.setdefault("source_isolation_required", True)
        merged_policy.setdefault("empty_pack_policy", "warn")
    normalized_payload = dict(payload)
    if normalized_payload:
        normalized_payload["environment"] = resolved_environment
        normalized_payload["source_policy"] = merged_policy
    return {
        "operation": operation,
        "environment": resolved_environment,
        "source_policy": merged_policy,
        "envelope": normalized_payload,
        "production": production,
        "strict": production,
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
