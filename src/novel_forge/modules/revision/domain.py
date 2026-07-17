"""Storage-free controlled revision and ReviewIssue resolution."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def apply_revision_result(
    *,
    project_id: str,
    draft: dict[str, Any],
    review: dict[str, Any],
    draft_asset_version_id: str,
    review_asset_version_id: str,
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not all((project_id, draft_asset_version_id, review_asset_version_id, context_bundle_version_id)):
        raise KernelError("REVISION_INPUT_INVALID", "versioned revision lineage is required")
    text = str(result.get("text") or "").strip()
    resolved = sorted({str(item) for item in result.get("resolved_issue_codes", []) if str(item).strip()})
    open_blocking = {
        str(item.get("code") or "")
        for item in review.get("issues", [])
        if item.get("severity") == "blocking"
        and item.get("status", "OPEN") == "OPEN"
        and item.get("qualification", "ELIGIBLE") == "ELIGIBLE"
    }
    if not text or not open_blocking.issubset(set(resolved)):
        raise KernelError(
            "CHAPTER_REVISION_INCOMPLETE",
            "revision must provide text and resolve every eligible blocking issue",
        )
    resolutions = [
        {
            "code": str(item.get("code") or ""),
            "review_issue_id": str(item.get("review_issue_id") or ""),
            "from_status": item.get("status", "OPEN"),
            "to_status": "RESOLVED" if item.get("code") in resolved else item.get("status", "OPEN"),
        }
        for item in review.get("issues", [])
    ]
    assertions = result.get("canon_assertions", [])
    if not isinstance(assertions, list) or any(not isinstance(item, dict) for item in assertions):
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "canon_assertions must be objects")
    return {
        "project_id": project_id,
        "chapter": draft["chapter"],
        "title": draft["title"],
        "text": text,
        "source_draft_version_id": draft_asset_version_id,
        "review_version_id": review_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "resolved_issue_codes": resolved,
        "issue_resolutions": resolutions,
        "canon_assertions": assertions,
        "provider_evidence": dict(provider_evidence),
        "revision_contract_version": "revision-domain-v2",
    }


__all__ = ["apply_revision_result"]
