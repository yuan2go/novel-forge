"""Storage-free internal release gate and export manifest builder."""
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
    dimensions = quality.get("dimensions", [])
    source_gate = [
        item for item in dimensions
        if item.get("gate_type") == "source_originality_gate" and item.get("blocking")
    ]
    evidence_types = {
        str(item.get("asset_type")): item
        for item in context_bundle.get("context_segments", [])
    }
    checklist = evidence_types.get("operator_checklist", {})
    checklist_facts = {
        str(item.get("key")): item.get("value")
        for item in checklist.get("structured_facts", [])
    }
    operator_approval = evidence_types.get("operator_approval", {})
    approval_facts = {
        str(item.get("key")): item.get("value")
        for item in operator_approval.get("structured_facts", [])
    }
    checks = {
        "quality_evidence_current": quality.get("gate") in {"PASSED", "PASSED_WITH_UNCALIBRATED"},
        "latest_rereview_passed": review.get("report_type") == "ReReviewReport" and review.get("decision") == "PASSED" and int(review.get("blocking_issue_count", 0)) == 0,
        "canon_consistent": canon.get("gate") == "PASSED" and not canon.get("conflicts"),
        "source_eligible_and_leakage_clear": bool(source_gate) and all(item.get("gate_status") == "PASSED" for item in source_gate),
        "originality_risk_clear_or_approved": (
            any(item.get("dimension") == "originality_risk" and item.get("gate_status") == "PASSED" for item in dimensions)
            or approval_facts.get("approved") is True
        ),
        "anti_ai_clear_or_approved": (
            "anti_ai_report" in evidence_types or approval_facts.get("approved") is True
        ),
        "platform_rules_clear_or_approved": (
            "platform_rule_report" in evidence_types or approval_facts.get("approved") is True
        ),
        "operator_checklist_approved": (
            bool(checklist.get("asset_version_id"))
            and checklist_facts.get("completed") is True
        ),
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
            "operator_checklist_version_id": checklist.get("asset_version_id", ""),
            "operator_approval_version_id": operator_approval.get("asset_version_id", ""),
            "blob_verification_required": True,
            "blob_verification_status": "PENDING_EXPORT",
        },
        "rollback_metadata": {
            "rollback_to_asset_version_id": revision.get("source_draft_version_id", ""),
            "release_not_externally_published": True,
        },
        "publish_gate_contract_version": "internal-publish-gate-v3",
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
