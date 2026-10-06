from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS
from novel_forge.modules.review.diagnostics import review_covers_candidate


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
    required_dimensions = set(QUALITY_DIMENSIONS)
    by_dimension = {str(item.get("dimension")): item for item in dimensions}
    source_gate = [
        item
        for item in dimensions
        if item.get("gate_type") == "source_originality_quality_gate"
        and item.get("blocking")
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
    operator_approval = evidence_types.get("approval_decision") or evidence_types.get(
        "operator_approval", {}
    )
    approval_facts = {
        str(item.get("key")): item.get("value")
        for item in operator_approval.get("structured_facts", [])
    }
    approval_requirements = list(
        context_bundle.get("production_input_manifest", {}).get(
            "approval_requirements", []
        )
    )
    approval_required = bool(approval_requirements)

    def real_provider_uncalibrated_pass(item: dict[str, Any]) -> bool:
        return (
            quality.get("fixture") is False
            and item.get("gate_status") == "PASSED_WITH_UNCALIBRATED"
            and item.get("provider_verified") is True
            and item.get("calibration_status") == "PROVIDER_UNCALIBRATED"
        )

    def cleared(dimension: str) -> bool:
        item = by_dimension.get(dimension, {})
        status = item.get("gate_status")
        return (
            status in {"PASSED", "PASSED_WITH_WARNINGS"}
            or real_provider_uncalibrated_pass(item)
            or (
                status == "WAIVED_BY_APPROVAL"
                and _fixture_waiver_is_valid(
                    item,
                    evidence_types=evidence_types,
                    project_id=project_id,
                    target_asset_version_id=revision_asset_version_id,
                )
            )
        )

    checks = {
        "quality_evidence_current": (
            quality.get("gate") in {"PASSED", "PASSED_WITH_UNCALIBRATED"}
            and quality.get("target_asset_version_id") == revision_asset_version_id
            and required_dimensions.issubset(by_dimension)
        ),
        "latest_rereview_passed": review_covers_candidate(review, text=str(revision.get("text") or ""), source_id=str(revision.get("selected_source_asset_version_id") or ""))
        and review.get("decision") == "PASSED"
        and int(review.get("blocking_issue_count", 0)) == 0,
        "canon_consistent": canon.get("gate") == "PASSED"
        and not canon.get("conflicts"),
        "source_eligible_and_leakage_clear": (
            bool(source_gate) and cleared("source_leakage")
        ),
        "originality_risk_clear": cleared("originality"),
        "anti_ai_clear_or_approved": cleared("anti_ai"),
        "platform_rules_clear_or_approved": (
            all(
                cleared(item)
                for item in (
                    "chapter_length",
                    "format",
                    "sensitive_content",
                    "ai_content_policy",
                    "publish_metadata",
                )
            )
        ),
        "all_blocking_dimensions_passed": all(
            item.get("gate_status") in {"PASSED", "PASSED_WITH_WARNINGS"}
            or real_provider_uncalibrated_pass(item)
            or (
                item.get("gate_status") == "WAIVED_BY_APPROVAL"
                and _fixture_waiver_is_valid(
                    item,
                    evidence_types=evidence_types,
                    project_id=project_id,
                    target_asset_version_id=revision_asset_version_id,
                )
            )
            for item in dimensions
            if item.get("blocking")
        ),
        "operator_checklist_approved": (
            bool(checklist.get("asset_version_id"))
            and checklist_facts.get("completed") is True
        ),
        "risk_approval_satisfied": (
            not approval_required
            or approval_facts.get("approved") is True
            or approval_facts.get("decision") == "APPROVED"
        ),
    }
    strict_checks = dict(checks)
    validation = quality.get("internal_admission")
    if validation is not None:
        checks = {"quality_internal_admission": validation.get("version") in {"creative-quality-admission.v1", "creative-quality-admission.v2"}
                and validation.get("status") == "INTERNAL_ADMITTED" and not validation.get("blocked_dimensions")
                and validation.get("target_asset_version_id") == revision_asset_version_id,
            "latest_rereview_passed": strict_checks["latest_rereview_passed"],
            "canon_consistent": strict_checks["canon_consistent"]}
    if not project_id or not all(checks.values()):
        failed = sorted(key for key, passed in checks.items() if not passed)
        return {
            "project_id": project_id,
            "chapter": revision["chapter"],
            "gate": "PUBLISH_GATE_BLOCKED",
            "release_readiness": "BLOCKED",
            "external_publish_permitted": False,
            "production_verified": False,
            "fixture_protocol_only": bool(quality.get("fixture")),
            "checks": checks,
            "failed_checks": failed,
            "release_manifest": {},
            "rollback_metadata": {
                "rollback_to_asset_version_id": ((revision.get("best_candidate_snapshot") or {}).get("rollback_asset_version_id") or revision.get("source_draft_version_id", "")),
                "release_not_externally_published": True,
            },
            "publish_gate_contract_version": "creative-internal-publish.v1" if validation is not None else "internal-publish-gate-v3",
        }
    return {
        "project_id": project_id,
        "chapter": revision["chapter"],
        "gate": "INTERNAL_ADMITTED" if validation is not None else "PASSED",
        **({"internal_admission": validation, "strict_publish_checks": strict_checks,
            "omitted_checks": {"publication_approval": {"status": "NOT_RUN", "reason": "internal creative validation"},
                "literary_calibration": {"status": "NOT_RUN", "reason": "native template excludes literary calibration"}}} if validation is not None else {}),
        "release_readiness": "INTERNAL_CREATIVE_VALIDATION" if validation is not None else "INTERNAL_REVIEW_RELEASE",
        "external_publish_permitted": False,
        "production_verified": False,
        "fixture_protocol_only": bool(quality.get("fixture"))
        or any(item.get("gate_status") == "WAIVED_BY_APPROVAL" for item in dimensions),
        "checks": checks,
        "release_manifest": {
            "revision_asset_version_id": revision_asset_version_id,
            "quality_asset_version_id": quality_asset_version_id,
            "review_asset_version_id": review_asset_version_id,
            "canon_asset_version_id": canon_asset_version_id,
            "context_bundle_version_id": context_bundle_version_id,
            "operator_checklist_version_id": checklist.get("asset_version_id", ""),
            "operator_approval_version_id": operator_approval.get(
                "asset_version_id", ""
            ),
            "blob_verification_required": True,
            "blob_verification_status": "PENDING_EXPORT",
        },
        "rollback_metadata": {
            "rollback_to_asset_version_id": ((revision.get("best_candidate_snapshot") or {}).get("rollback_asset_version_id") or revision.get("source_draft_version_id", "")),
            "release_not_externally_published": True,
        },
        "publish_gate_contract_version": "creative-internal-publish.v1" if validation is not None else "internal-publish-gate-v3",
    }


def _fixture_waiver_is_valid(
    dimension: dict[str, Any],
    *,
    evidence_types: dict[str, dict[str, Any]],
    project_id: str,
    target_asset_version_id: str,
) -> bool:
    waiver = dimension.get("waiver")
    if not isinstance(waiver, dict):
        return False
    approval = evidence_types.get("approval_decision") or evidence_types.get(
        "operator_approval", {}
    )
    checklist = evidence_types.get("operator_checklist", {})
    expiry = str(waiver.get("expiry") or "")
    try:
        expires_at = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return False
    scope = waiver.get("scope")
    return (
        expires_at.tzinfo is not None
        and expires_at > datetime.now(timezone.utc)
        and waiver.get("contract_version") == "fixture-quality-waiver-v1"
        and waiver.get("fixture_protocol_only") is True
        and waiver.get("production_verified") is False
        and waiver.get("dimension") == dimension.get("dimension")
        and waiver.get("approval_asset_version_id") == approval.get("asset_version_id")
        and waiver.get("checklist_asset_version_id")
        == checklist.get("asset_version_id")
        and isinstance(scope, dict)
        and scope.get("project_id") == project_id
        and scope.get("scope_type") == "PROJECT_FIXTURE"
        and waiver.get("target_asset_version_id") == target_asset_version_id
        and scope.get("release_readiness") == "INTERNAL_REVIEW_RELEASE"
    )


def build_export_blob_manifest(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    publish_gate: dict[str, Any],
    publish_gate_asset_version_id: str,
) -> dict[str, Any]:
    validation = publish_gate.get("internal_admission")
    internal = (publish_gate.get("gate") == "INTERNAL_ADMITTED" and validation is not None
        and validation.get("status") == "INTERNAL_ADMITTED"
        and validation.get("target_asset_version_id") == revision_asset_version_id
        and publish_gate.get("publish_gate_contract_version") == "creative-internal-publish.v1")
    if publish_gate.get("gate") != "PASSED" and not internal:
        failed = ", ".join(
            str(item) for item in publish_gate.get("failed_checks") or ()
        )
        detail = f"; failed checks: {failed}" if failed else ""
        raise KernelError(
            "CHAPTER_QUALITY_GATE_BLOCKED",
            f"Export requires a passed publish gate{detail}",
        )
    return {
        "chapter": revision["chapter"],
        "title": revision["title"],
        "rendered_text": revision["text"],
        "selected_source_asset_version_id": str(revision.get("selected_source_asset_version_id") or ""),
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
    content_blobs = [item for item in export_blobs if item.get("role") == "content"]
    if len(content_blobs) != 1:
        raise KernelError(
            "FINAL_RELEASE_BLOB_EVIDENCE_INVALID",
            "final release requires exactly one frozen content Blob binding",
        )
    blob = content_blobs[0]
    validation = quality.get("internal_admission")
    internal = (validation is not None and validation == publish_gate.get("internal_admission")
        and validation.get("status") == "INTERNAL_ADMITTED"
        and publish_gate.get("publish_gate_contract_version") == "creative-internal-publish.v1"
        and publish_gate.get("gate") == "INTERNAL_ADMITTED")
    checks = {
        "pre_release_gate_passed": publish_gate.get("gate") == "PASSED" or internal,
        "quality_gate_passed": internal or quality.get("gate")
        in {
            "PASSED",
            "PASSED_WITH_UNCALIBRATED",
        },
        "latest_rereview_passed": (
            review_covers_candidate(review, text=str(export_package.get("rendered_text") or ""), source_id=str(export_package.get("selected_source_asset_version_id") or ""))
            and review.get("decision") == "PASSED"
            and int(review.get("blocking_issue_count", 0)) == 0
        ),
        "canon_consistent": canon.get("gate") == "PASSED"
        and not canon.get("conflicts"),
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
        "gate": "INTERNAL_ADMITTED" if internal else "PASSED",
        "release_status": "INTERNAL_VALIDATION_FINALIZED" if internal else "INTERNAL_RELEASE_FINALIZED",
        **({"internal_admission": validation, "final_gate_contract_version": "creative-internal-finalize.v1",
            "strict_certification_eligible": False} if internal else {}),
        "release_readiness": "INTERNAL_REVIEW_RELEASE",
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
                "blob_id",
                "provider",
                "object_key",
                "expected_hash",
                "actual_hash",
                "expected_size",
                "actual_size",
                "media_type",
                "external_effect_id",
                "dispatch_id",
                "receipt_id",
                "receipt_status",
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
