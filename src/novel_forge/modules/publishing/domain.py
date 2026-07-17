"""Storage-free internal publish gate and release manifest builder."""
from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


def prepare_internal_release(
    *,
    project_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle: dict[str, Any],
    context_bundle_version_id: str,
) -> dict[str, Any]:
    blockers = [
        item for item in review.get("issues", [])
        if item.get("severity") == "blocking"
        and item.get("qualification", "ELIGIBLE") == "ELIGIBLE"
        and item.get("code") not in set(revision.get("resolved_issue_codes", []))
    ]
    source_clear = bool(context_bundle.get("source_isolation_result", {}).get("passed"))
    originality_clear = context_bundle.get("copyright_boundary") == "abstract_or_project_owned_only"
    checks = {
        "quality_evidence_current": quality.get("gate") == "PASSED",
        "review_issues_resolved": not blockers,
        "canon_consistent": canon.get("gate") == "PASSED" and not canon.get("conflicts"),
        "source_eligible": source_clear,
        "originality_risk_clear": originality_clear,
        "operator_checklist_present": True,
    }
    if not project_id or not all(checks.values()):
        raise KernelError("PUBLISH_GATE_BLOCKED", "release evidence is missing or blocked")
    return {
        "project_id": project_id,
        "chapter": revision["chapter"],
        "gate": "PASSED",
        "checks": checks,
        "release_manifest": {
            "revision_asset_version_id": revision_asset_version_id,
            "quality_asset_version_id": quality_asset_version_id,
            "review_asset_version_id": review_asset_version_id,
            "canon_asset_version_id": canon_asset_version_id,
            "context_bundle_version_id": context_bundle_version_id,
            "content_hash_pending_blob": True,
        },
        "operator_checklist": [
            "confirm_title_and_summary",
            "confirm_review_and_quality_evidence",
            "verify_export_blob_checksum",
        ],
        "rollback_metadata": {
            "rollback_to_asset_version_id": revision.get("source_draft_version_id", ""),
            "release_not_externally_published": True,
        },
        "publish_gate_contract_version": "internal-publish-gate-v2",
    }


def build_export_blob_manifest(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    publish_gate: dict[str, Any],
    publish_gate_asset_version_id: str,
) -> dict[str, Any]:
    if publish_gate.get("gate") != "PASSED":
        raise KernelError("CHAPTER_QUALITY_GATE_BLOCKED", "Export requires a passed publish gate")
    return {
        "chapter": revision["chapter"],
        "title": revision["title"],
        "rendered_text": revision["text"],
        "source_asset_version_id": revision_asset_version_id,
        "publish_gate_asset_version_id": publish_gate_asset_version_id,
        "release_status": "READY_FOR_BLOB_VERIFICATION",
        "media_type": "text/plain",
        "blob_verification": {"required": True, "status": "PENDING"},
    }


__all__ = ["build_export_blob_manifest", "prepare_internal_release"]
