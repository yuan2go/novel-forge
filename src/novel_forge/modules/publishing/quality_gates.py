from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from novel_forge.modules.runtime_ledger import record_gate_result
from novel_forge.storage.local import LocalStorage


def record_release_quality_gates(
    storage: LocalStorage,
    *,
    target: Any,
    target_path: str | Path,
    chapter_audit: dict[str, Any],
    project_id: str,
    workspace_path: str,
    production: bool,
    trace: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Persist independent integrity and content-quality release evidence.

    Integrity answers whether the candidate is a valid, scoped artifact. Content
    quality answers whether its body is publishable; neither result substitutes
    for the other.
    """
    target_data = target.to_dict() if hasattr(target, "to_dict") else target
    text = _asset_text(target_data)
    integrity = _asset_integrity(target_data, text=text, project_id=project_id)
    quality = _content_quality(storage, target_data, text=text, audit=chapter_audit, project_id=project_id)
    integrity_status = "passed" if not integrity["issues"] else "failed" if production else "warning"
    quality_status = "passed" if not quality["issues"] else "failed" if production else "warning"
    target_ref = str(target_path)
    integrity_gate = record_gate_result(
        storage,
        gate_kind="release_asset_integrity",
        status=integrity_status,
        target_paths=[target_ref],
        result=integrity,
        trace=trace,
        project_id=project_id,
        workspace_path=workspace_path,
        message="release asset integrity passed" if not integrity["issues"] else "release asset integrity requires repair",
        blocking=production,
    )
    quality_gate = record_gate_result(
        storage,
        gate_kind="release_content_quality",
        status=quality_status,
        target_paths=[target_ref],
        result=quality,
        trace=trace,
        project_id=project_id,
        workspace_path=workspace_path,
        message="release content quality passed" if not quality["issues"] else "release content quality requires revision",
        blocking=production,
    )
    return {
        "asset_integrity": {"status": integrity_status, "blocking": production and bool(integrity["issues"]), "path": integrity_gate["path"], **integrity},
        "content_quality": {"status": quality_status, "blocking": production and bool(quality["issues"]), "path": quality_gate["path"], **quality},
    }


def _asset_integrity(target: dict[str, Any], *, text: str, project_id: str) -> dict[str, Any]:
    metadata = target.get("metadata", {}) if isinstance(target.get("metadata", {}), dict) else {}
    issues: list[dict[str, str]] = []
    if str(target.get("type") or "") != "draft_chapter":
        issues.append(_issue("asset_type", "release target must be a draft_chapter"))
    if not str(target.get("id") or "").strip():
        issues.append(_issue("asset_id", "release target is missing an immutable asset id"))
    if not project_id or str(metadata.get("project_id") or "") != project_id:
        issues.append(_issue("project_scope", "release target project scope does not match the release project"))
    if not text.strip():
        issues.append(_issue("content_completeness", "release target has no readable chapter body"))
    return {"contract": "release-asset-integrity-v1", "issues": issues, "checks": {"asset_type": not any(row["dimension"] == "asset_type" for row in issues), "asset_id": not any(row["dimension"] == "asset_id" for row in issues), "project_scope": not any(row["dimension"] == "project_scope" for row in issues), "content_completeness": not any(row["dimension"] == "content_completeness" for row in issues)}}


def _content_quality(storage: LocalStorage, target: dict[str, Any], *, text: str, audit: dict[str, Any], project_id: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    normalized = _normalize_body(text)
    if len(normalized) < 80:
        issues.append(_issue("content_completeness", "chapter body is too short for release quality review"))
    if normalized and _duplicate_body(storage, target_id=str(target.get("id") or ""), body=normalized, project_id=project_id):
        issues.append(_issue("body_uniqueness", "chapter body duplicates an earlier project draft"))
    audit_content = audit.get("content", {}) if isinstance(audit.get("content", {}), dict) else {}
    gate_results = audit_content.get("gate_results", {}) if isinstance(audit_content.get("gate_results", {}), dict) else {}
    semantic = gate_results.get("semantic_integrity", {}) if isinstance(gate_results.get("semantic_integrity", {}), dict) else {}
    stability = gate_results.get("stability_preflight", {}) if isinstance(gate_results.get("stability_preflight", {}), dict) else {}
    if semantic and not bool(semantic.get("passed", False)):
        issues.append(_issue("chapter_progression", "chapter audit found semantic/progression failure"))
    if stability and not bool(stability.get("passed", False)):
        issues.append(_issue("state_consistency", "chapter audit found continuity or stability failure"))
    return {"contract": "release-content-quality-v1", "issues": issues, "checks": {"body_uniqueness": not any(row["dimension"] == "body_uniqueness" for row in issues), "chapter_progression": not any(row["dimension"] == "chapter_progression" for row in issues), "state_consistency": not any(row["dimension"] == "state_consistency" for row in issues), "content_completeness": not any(row["dimension"] == "content_completeness" for row in issues)}}


def _duplicate_body(storage: LocalStorage, *, target_id: str, body: str, project_id: str) -> bool:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    for path in storage.list_json("drafts"):
        data = storage.read_json(path)
        if not isinstance(data, dict) or data.get("type") != "draft_chapter" or str(data.get("id") or "") == target_id:
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
        if str(metadata.get("project_id") or "") != project_id:
            continue
        if hashlib.sha256(_normalize_body(_asset_text(data)).encode("utf-8")).hexdigest() == digest:
            return True
    return False


def _asset_text(asset: dict[str, Any]) -> str:
    content = asset.get("content", {}) if isinstance(asset.get("content", {}), dict) else {}
    return str(content.get("text") or content.get("body") or "")


def _normalize_body(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _issue(dimension: str, message: str) -> dict[str, str]:
    return {"dimension": dimension, "severity": "high", "message": message, "recommendation": "revise the release candidate and rerun the release quality gate"}
