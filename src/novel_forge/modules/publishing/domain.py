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
    required_dimensions = {
        "readability", "golden_opening", "chapter_economy", "reader_promise",
        "reward", "toxic_point", "protagonist_charm", "antagonist_pressure",
        "mobile_reading", "style_drift", "originality", "source_leakage",
        "anti_ai", "platform_rules", "longform_stability",
    }
    by_dimension = {str(item.get("dimension")): item for item in dimensions}
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
        "quality_evidence_current": (
            quality.get("gate") in {"PASSED", "PASSED_WITH_UNCALIBRATED"}
            and quality.get("target_asset_version_id") == revision_asset_version_id
            and required_dimensions.issubset(by_dimension)
        ),
        "latest_rereview_passed": review.get("report_type") == "ReReviewReport" and review.get("decision") == "PASSED" and int(review.get("blocking_issue_count", 0)) == 0,
        "canon_consistent": canon.get("gate") == "PASSED" and not canon.get("conflicts"),
        "source_eligible_and_leakage_clear": (
            bool(source_gate)
            and by_dimension.get("source_leakage", {}).get("gate_status") == "PASSED"
        ),
        "originality_risk_clear": (
            by_dimension.get("originality", {}).get("gate_status") == "PASSED"
        ),
        "anti_ai_clear_or_approved": (
            by_dimension.get("anti_ai", {}).get("gate_status") == "PASSED"
            or approval_facts.get("approved") is True
        ),
        "platform_rules_clear_or_approved": (
            by_dimension.get("platform_rules", {}).get("gate_status") == "PASSED"
            or approval_facts.get("approved") is True
        ),
        "all_blocking_dimensions_passed": all(
            item.get("gate_status") in {"PASSED", "PASSED_WITH_WARNINGS"}
            for item in dimensions
            if item.get("blocking")
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


def finalize_blob_verified_release(
    *,
    project_id: str,
    export_package: dict[str, Any],
    export_asset_version_id: str,
    export_blobs: tuple[dict[str, Any], ...],
    publish_gate: dict[str, Any],
    publish_gate_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle_version_id: str,
) -> dict[str, Any]:
    """Bind final internal release readiness to authoritative post-upload evidence."""
    content_blobs = [item for item in export_blobs if item.get("role") == "content"]
    if len(content_blobs) != 1:
        raise KernelError(
            "FINAL_RELEASE_BLOB_EVIDENCE_INVALID",
            "final release requires exactly one frozen content Blob binding",
        )
    blob = content_blobs[0]
    checks = {
        "pre_release_gate_passed": publish_gate.get("gate") == "PASSED",
        "quality_gate_passed": quality.get("gate") in {
            "PASSED",
            "PASSED_WITH_UNCALIBRATED",
        },
        "latest_rereview_passed": (
            review.get("report_type") == "ReReviewReport"
            and review.get("decision") == "PASSED"
            and int(review.get("blocking_issue_count", 0)) == 0
        ),
        "canon_consistent": canon.get("gate") == "PASSED" and not canon.get("conflicts"),
        "export_awaited_blob_verification": (
            export_package.get("release_status") == "READY_FOR_BLOB_VERIFICATION"
        ),
        "blob_available": blob.get("status") == "AVAILABLE",
        "blob_hash_verified": (
            bool(blob.get("expected_hash"))
            and blob.get("expected_hash") == blob.get("actual_hash")
            and blob.get("actual_hash") == blob.get("content_hash")
        ),
        "blob_size_verified": (
            blob.get("actual_size") is not None
            and int(blob["expected_size"]) == int(blob["actual_size"])
        ),
        "blob_provider_verified": (
            bool(blob.get("provider"))
            and blob.get("provider") == blob.get("receipt_provider")
        ),
        "upload_effect_succeeded": (
            blob.get("capability") == "object_store.put"
            and blob.get("effect_status") == "SUCCEEDED"
            and blob.get("dispatch_status") == "SUCCEEDED"
            and blob.get("receipt_status") == "VERIFIED"
        ),
        "rollback_metadata_present": bool(
            publish_gate.get("rollback_metadata", {}).get(
                "rollback_to_asset_version_id"
            )
        ),
    }
    if not project_id or not all(checks.values()):
        failed = sorted(key for key, passed in checks.items() if not passed)
        raise KernelError(
            "FINAL_RELEASE_GATE_BLOCKED",
            f"post-Blob final release evidence failed: {', '.join(failed)}",
        )
    return {
        "project_id": project_id,
        "chapter": export_package["chapter"],
        "gate": "PASSED",
        "release_status": "INTERNAL_RELEASE_FINALIZED",
        "external_publish_permitted": False,
        "checks": checks,
        "accepted_asset_version_ids": {
            "export": export_asset_version_id,
            "publish_gate": publish_gate_asset_version_id,
            "quality": quality_asset_version_id,
            "rereview": review_asset_version_id,
            "canon": canon_asset_version_id,
            "context_bundle": context_bundle_version_id,
        },
        "blob_receipt": {
            key: blob.get(key)
            for key in (
                "blob_id", "provider", "object_key", "expected_hash", "actual_hash",
                "expected_size", "actual_size", "media_type", "external_effect_id",
                "dispatch_id", "receipt_id", "receipt_status",
            )
        },
        "rollback_metadata": {
            **publish_gate["rollback_metadata"],
            "release_asset_version_id": export_asset_version_id,
            "blob_id": blob["blob_id"],
            "external_publish_permitted": False,
        },
        "resume_metadata": {
            "verified_export_asset_version_id": export_asset_version_id,
            "verified_blob_id": blob["blob_id"],
            "verified_effect_id": blob["external_effect_id"],
        },
        "final_release_gate_contract_version": "post-blob-final-release-v1",
    }


__all__ = [
    "build_export_blob_manifest",
    "finalize_blob_verified_release",
    "prepare_internal_release",
]
