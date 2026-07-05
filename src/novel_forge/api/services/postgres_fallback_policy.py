from __future__ import annotations

from typing import Any

from novel_forge.modules.production_governance import record_fallback_decision
from novel_forge.storage.local import LocalStorage


def postgres_asset_read_fallback_policy(settings: Any, error: Exception | None = None) -> dict[str, Any]:
    database_url = str(getattr(settings, "database_url", "") or "")
    strict = bool(getattr(settings, "postgres_write_strict", False))
    base = {
        "fallback_type": "postgres_asset_read",
        "silent_fallback_allowed": False,
        "audit_event_type": "postgres_asset_read_fallback",
        "rollback_plan": {
            "rollback_action": "restore_postgres_asset_index",
            "requires_operator_review": True,
        },
    }
    if not database_url:
        return {
            **base,
            "mode": "local_only",
            "allow_local_fallback": True,
            "strict": strict,
            "audit_required": False,
            "http_status": 200,
            "message": "PostgreSQL is not configured; local asset index is the primary read source.",
        }
    if strict:
        return {
            **base,
            "mode": "postgres_strict_fail_closed",
            "allow_local_fallback": False,
            "strict": True,
            "audit_required": True,
            "http_status": 503,
            "message": f"PostgreSQL asset index failed in strict mode: {error}" if error else "PostgreSQL asset index is required in strict mode.",
        }
    return {
        **base,
        "mode": "postgres_read_fail_open",
        "allow_local_fallback": True,
        "strict": False,
        "audit_required": True,
        "http_status": 200,
        "message": f"PostgreSQL asset index failed; falling back to local asset index: {error}" if error else "PostgreSQL read fallback is allowed.",
    }


def handle_postgres_asset_read_fallback(
    storage: LocalStorage,
    settings: Any,
    error: Exception,
    *,
    operation: str,
    project_id: str = "",
    workspace_path: str = "",
    target_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate and persist Postgres read fallback evidence when audit is required."""

    policy = postgres_asset_read_fallback_policy(settings, error)
    if not policy.get("audit_required"):
        return policy
    decision = record_fallback_decision(
        storage,
        fallback_type=str(policy.get("fallback_type") or "postgres_asset_read"),
        mode=str(policy.get("mode") or "unknown"),
        allowed=bool(policy.get("allow_local_fallback")),
        reason=str(policy.get("message") or error),
        project_id=project_id,
        workspace_path=workspace_path,
        environment="production" if bool(policy.get("strict")) else "dev",
        approval_required=not bool(policy.get("allow_local_fallback")),
        approval_ref="",
        target_refs=target_refs or [operation],
        evidence_refs=evidence_refs or [],
        rollback_plan=policy.get("rollback_plan") if isinstance(policy.get("rollback_plan"), dict) else {},
        trace=trace,
        actor_type="system",
    )
    return {
        **policy,
        "fallback_decision_path": decision.get("path", ""),
        "fallback_audit_event_path": decision.get("audit_event_path", ""),
        "fallback_decision_status": decision.get("status", ""),
    }
