from __future__ import annotations

from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.modules.common import resolve_path
from novel_forge.modules.os_envelope import envelope_asset_metadata
from novel_forge.modules.production_governance import record_fallback_decision
from novel_forge.schemas import PlatformReviewStatus, validate_common_fields
from novel_forge.storage.local import LocalStorage


def record_platform_publish_failure(
    storage: LocalStorage,
    *,
    upload_path: str,
    platform_id: str,
    error_message: str,
    envelope: dict[str, Any],
    environment: str,
    production_governance_path: str = "",
) -> dict[str, Any]:
    redacted_error = redact_error_text(error_message)
    status_path = _write_platform_failure_status(
        storage,
        upload_path=upload_path,
        platform_id=platform_id,
        message=redacted_error,
        envelope=envelope,
    )
    decision = record_fallback_decision(
        storage,
        fallback_type="external_platform_adapter",
        mode="platform_api_publish_failure",
        allowed=False,
        reason=redacted_error,
        project_id=str(envelope.get("project_id") or ""),
        workspace_path="",
        environment=str(envelope.get("environment") or environment),
        approval_required=True,
        target_refs=[upload_path],
        evidence_refs=[status_path, production_governance_path],
        rollback_plan={
            "rollback_action": "manual_platform_publish_reconciliation",
            "rollback_ref": status_path,
            "requires_operator_review": True,
        },
        trace={"trace_id": str(envelope.get("trace_id") or "")},
        actor_type="system",
    )
    return {"status_path": status_path, "fallback_decision": decision, "redacted_error": redacted_error}


def redact_error_text(value: str) -> str:
    redacted = str(value)
    for marker in ["token=", "api_key=", "apikey=", "authorization=", "password=", "secret="]:
        lower = redacted.lower()
        index = lower.find(marker)
        if index >= 0:
            end = redacted.find(" ", index)
            if end < 0:
                end = len(redacted)
            redacted = f"{redacted[:index]}{marker}[redacted]{redacted[end:]}"
    return redacted


def _write_platform_failure_status(storage: LocalStorage, *, upload_path: str, platform_id: str, message: str, envelope: dict[str, Any]) -> str:
    status_id = make_id("platform_review_status", f"{platform_id}-{upload_path}-failed")
    status = PlatformReviewStatus(
        title=f"{platform_id} platform API failure",
        source=upload_path,
        tags=["publishing-feedback-adapter", "review-status", "failed", "api-adapter"],
        content={
            "status_id": status_id,
            "platform_id": platform_id,
            "receipt_id": status_id,
            "review_status": "failed",
            "blocking_reasons": [message or "platform API publish failed"],
            "updated_at": utc_now(),
            "platform_api_evidence": {"mode": "api_adapter", "status": "failed_closed"},
        },
        metadata={"project_id": str(envelope.get("project_id") or ""), **envelope_asset_metadata(envelope)},
        references=[upload_path],
    )
    errors = validate_common_fields(status.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    return _display_path(storage.root, storage.write_asset_auto(status))


def _display_path(root: Path, path: str | Path) -> str:
    resolved = resolve_path(root, path)
    return str(resolved.relative_to(root)) if resolved.is_absolute() and resolved.is_relative_to(root) else str(resolved)
