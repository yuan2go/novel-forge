"""Storage-free quality evidence aggregation."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def evaluate_quality_evidence(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle_version_id: str,
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, review_asset_version_id, canon_asset_version_id, context_bundle_version_id)):
        raise KernelError("QUALITY_INPUT_INVALID", "versioned quality lineage is required")
    eligible_blockers = [
        item for item in review.get("issues", [])
        if item.get("severity") == "blocking"
        and item.get("qualification", "ELIGIBLE") == "ELIGIBLE"
        and item.get("code") not in set(revision.get("resolved_issue_codes", []))
    ]
    checks = {
        "revision_has_content": bool(str(revision.get("text") or "").strip()),
        "review_evidence_present": bool(review.get("issues")) or review.get("decision") == "PASSED",
        "blocking_review_issue_resolved": not eligible_blockers,
        "canon_conflict_free": canon.get("gate") == "PASSED" and not canon.get("conflicts"),
        "context_bundle_versioned": bool(context_bundle_version_id),
    }
    if not all(checks.values()):
        raise KernelError(
            "CHAPTER_QUALITY_GATE_FAILED",
            "Quality output cannot be qualified while a blocking check fails",
        )
    return {
        "project_id": project_id,
        "chapter": revision["chapter"],
        "target_asset_version_id": revision_asset_version_id,
        "review_asset_version_id": review_asset_version_id,
        "canon_patch_version_id": canon_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "score": 100.0,
        "checks": checks,
        "gate": "PASSED",
        "quality_contract_version": "quality-domain-v2",
    }


__all__ = ["evaluate_quality_evidence"]
