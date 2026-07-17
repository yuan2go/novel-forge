"""Storage-free review decisions and schema-shaped ReviewIssue payloads."""
from __future__ import annotations

import hashlib
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def evaluate_review_result(
    *,
    project_id: str,
    target_asset_version_id: str,
    context_bundle_version_id: str,
    chapter: int,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not project_id or not target_asset_version_id or not context_bundle_version_id:
        raise KernelError("REVIEW_INPUT_INVALID", "project, target and context versions are required")
    decision = str(result.get("decision") or "").upper()
    if decision not in {"PASSED", "NEEDS_REVISION", "BLOCKED"}:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review decision is unsupported")
    score = result.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 100:
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review score must be between 0 and 100")
    issues = result.get("issues")
    if not isinstance(issues, list) or any(not isinstance(item, dict) for item in issues):
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review issues must be objects")
    normalized: list[dict[str, Any]] = []
    for ordinal, item in enumerate(issues, start=1):
        code = str(item.get("code") or "").strip()
        severity = str(item.get("severity") or "").lower()
        message = str(item.get("message") or "").strip()
        if not code or severity not in {"blocking", "major", "minor"} or not message:
            raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "review issue is incomplete")
        evidence = item.get("evidence", {}) if isinstance(item.get("evidence"), dict) else {}
        fingerprint = f"{project_id}:{target_asset_version_id}:{code}:{ordinal}".encode()
        normalized.append(
            {
                "review_issue_id": "review-issue:" + hashlib.sha256(fingerprint).hexdigest()[:24],
                "code": code,
                "severity": severity,
                "message": message,
                "status": "OPEN",
                "qualification": "ELIGIBLE",
                "target_asset_version_id": target_asset_version_id,
                "context_bundle_version_id": context_bundle_version_id,
                "evidence_locator": {
                    "chapter": chapter,
                    "start": evidence.get("start"),
                    "end": evidence.get("end"),
                    "excerpt_digest": str(evidence.get("excerpt_digest") or ""),
                },
                "revision_strategy": str(item.get("revision_strategy") or message),
            }
        )
    blocking_count = sum(item["severity"] == "blocking" for item in normalized)
    if decision == "PASSED" and blocking_count:
        raise KernelError("REVIEW_DECISION_CONFLICT", "PASSED review cannot contain blocking issues")
    return {
        "project_id": project_id,
        "chapter": chapter,
        "target_asset_version_id": target_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "decision": decision,
        "score": float(score),
        "issues": normalized,
        "blocking_issue_count": blocking_count,
        "provider_evidence": dict(provider_evidence),
        "review_contract_version": "review-domain-v2",
    }


__all__ = ["evaluate_review_result"]
