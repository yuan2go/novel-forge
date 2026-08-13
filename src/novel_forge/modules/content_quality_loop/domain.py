"""Storage-free aggregation of versioned chapter quality evidence."""
from __future__ import annotations

from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


QUALITY_GATE_TYPES = (
    "structural_quality_gate",
    "commercial_quality_gate",
    "source_originality_quality_gate",
    "longform_quality_gate",
    "platform_quality_gate",
)


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
    evidence_reports: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    if not all((project_id, revision_asset_version_id, review_asset_version_id, canon_asset_version_id, context_bundle_version_id)):
        raise KernelError("QUALITY_INPUT_INVALID", "versioned quality lineage is required")
    if review.get("report_type") != "ReReviewReport":
        raise KernelError("QUALITY_REREVIEW_REQUIRED", "latest eligible Re-review is required")
    if not str(revision.get("text") or "").strip():
        raise KernelError("QUALITY_REVISION_CONTENT_MISSING", "Revision has no content")

    rereview_passed = (
        review.get("decision") == "PASSED"
        and not int(review.get("blocking_issue_count", 0))
    )
    canon_passed = canon.get("gate") == "PASSED" and not canon.get("conflicts")

    dimensions: list[dict[str, Any]] = [
        _dimension(
            dimension="structural_evidence",
            gate_type="structural_quality_gate",
            score=float(review.get("score", 0.0)),
            gate_status="PASSED" if rereview_passed else "FAILED",
            evidence_asset_version_id=review_asset_version_id,
            weight=.25,
            blocking=True,
            calibration_status=_review_calibration(review),
            source=_review_source(review),
            source_gate=str(review.get("decision") or "UNKNOWN"),
            issue_codes=sorted(
                {
                    str(item.get("code") or "REREVIEW_BLOCKER")
                    for item in review.get("issues", [])
                    if isinstance(item, dict)
                }
            ),
        ),
        _dimension(
            dimension="canon_consistency",
            gate_type="longform_quality_gate",
            score=None,
            gate_status="PASSED" if canon_passed else "FAILED",
            evidence_asset_version_id=canon_asset_version_id,
            weight=.15,
            blocking=True,
            calibration_status="DETERMINISTIC",
            source="deterministic_extractor",
            source_gate=str(canon.get("gate") or "UNKNOWN"),
            issue_codes=sorted(
                {
                    str(item.get("conflict_code") or "CANON_CONFLICT")
                    for item in canon.get("conflicts", [])
                    if isinstance(item, dict)
                }
            ),
        ),
    ]
    for report in evidence_reports:
        dimensions.append(
            _normalize_evidence_dimension(
                project_id,
                revision_asset_version_id,
                report,
            )
        )
    present_gates = {item["gate_type"] for item in dimensions}
    for gate_type in QUALITY_GATE_TYPES:
        if gate_type not in present_gates:
            dimensions.append(
                _dimension(
                    dimension=gate_type.removesuffix("_gate"),
                    gate_type=gate_type,
                    score=None,
                    gate_status="UNCALIBRATED",
                    evidence_asset_version_id="",
                    weight=0.0,
                    blocking=False,
                    calibration_status="UNCALIBRATED",
                    source="none",
                )
            )
    blocking = [
        item for item in dimensions
        if item["blocking"] and item["gate_status"] not in {
            "PASSED",
            "PASSED_WITH_WARNINGS",
            "PASSED_WITH_UNCALIBRATED",
            "WAIVED_BY_APPROVAL",
        }
    ]
    scored = [item for item in dimensions if isinstance(item["score"], (int, float)) and item["weight"] > 0]
    weight = sum(float(item["weight"]) for item in scored)
    aggregate_score = (
        round(sum(float(item["score"]) * float(item["weight"]) for item in scored) / weight, 4)
        if weight else None
    )
    required_actions = derive_quality_actions(dimensions)
    return {
        "project_id": project_id,
        "chapter": revision["chapter"],
        "target_asset_version_id": revision_asset_version_id,
        "review_asset_version_id": review_asset_version_id,
        "canon_patch_version_id": canon_asset_version_id,
        "context_bundle_version_id": context_bundle_version_id,
        "aggregate_score": aggregate_score,
        "dimensions": dimensions,
        "uncalibrated_dimensions": [
            item["dimension"] for item in dimensions
            if item["calibration_status"] in {
                "UNCALIBRATED", "FIXTURE_UNCALIBRATED", "PROVIDER_UNCALIBRATED"
            }
        ],
        "fixture": any(
            item["calibration_status"] == "FIXTURE_UNCALIBRATED"
            for item in dimensions
        ),
        "production_verified": False,
        "provider_verified": any(bool(item.get("provider_verified")) for item in dimensions),
        "human_verified": any(bool(item.get("human_verified")) for item in dimensions),
        "gate": "FAILED" if blocking else "PASSED_WITH_UNCALIBRATED" if any(
            item["calibration_status"] in {
                "UNCALIBRATED", "FIXTURE_UNCALIBRATED", "PROVIDER_UNCALIBRATED"
            }
            for item in dimensions
        ) else "PASSED",
        "blocking_dimensions": [item["dimension"] for item in blocking],
        "decision_chain": {
            "contract_version": "quality-decision-chain-v1",
            "observations": [item["dimension"] for item in dimensions],
            "evidence_asset_version_ids": sorted(
                {
                    str(item.get("evidence_asset_version_id") or "")
                    for item in dimensions
                    if str(item.get("evidence_asset_version_id") or "")
                }
            ),
            "issues": [item["issue"] for item in required_actions],
            "required_actions": required_actions,
            "reevaluation_gate": "chapter.quality.aggregate",
            "source_gate_failures": {
                "rereview": (
                    ""
                    if rereview_passed
                    else str(review.get("decision") or "UNKNOWN")
                ),
                "canon": (
                    "" if canon_passed else str(canon.get("gate") or "UNKNOWN")
                ),
            },
        },
        "required_actions": required_actions,
        "quality_contract_version": "chapter-quality-aggregate-v4",
    }


def derive_quality_actions(dimensions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn failed evidence into bounded, traceable work; never infer broad replans."""
    actions: list[dict[str, Any]] = []
    passing = {
        "PASSED",
        "PASSED_WITH_WARNINGS",
        "PASSED_WITH_UNCALIBRATED",
        "WAIVED_BY_APPROVAL",
    }
    for item in dimensions:
        status = str(item.get("gate_status") or "UNCALIBRATED").upper()
        if status in passing or not bool(item.get("blocking")):
            continue
        dimension = str(item.get("dimension") or "unknown")
        evidence_id = str(item.get("evidence_asset_version_id") or "")
        action = "CHAPTER_ADJUSTMENT" if dimension in {
            "commercial",
            "commercial_quality",
            "longform",
            "longform_quality",
        } else "LOCAL_REPAIR"
        actions.append(
            {
                "observation": dimension,
                "evidence_asset_version_ids": [evidence_id] if evidence_id else [],
                "issue": {
                    "code": f"QUALITY_{dimension.upper()}_FAILED",
                    "severity": "BLOCKING",
                    "status": "OPEN",
                },
                "required_action": action,
                "permitted_change_scope": "CHAPTER",
                "required_authority": "CHAPTER_AUTHORITY",
                "preserved_invariants": [
                    "accepted_canon",
                    "executed_chapter_history",
                    "active_parent_plan_identity",
                ],
                "reevaluation_gate": str(item.get("gate_type") or ""),
            }
        )
    return actions


def _normalize_evidence_dimension(
    project_id: str,
    revision_asset_version_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    if report.get("project_id") != project_id:
        raise KernelError("CROSS_PROJECT_REFERENCE", "quality evidence belongs to another project")
    target_version = str(report.get("target_asset_version_id") or "")
    if target_version and target_version != revision_asset_version_id:
        raise KernelError(
            "QUALITY_TARGET_VERSION_CONFLICT",
            "quality evidence targets another Revision AssetVersion",
        )
    calibration = str(
        report.get("calibration_status") or "PROVIDER_UNCALIBRATED"
    ).upper()
    source = str(report.get("source") or "fixture")
    if source == "fixture":
        calibration = "FIXTURE_UNCALIBRATED"
    status = str(report.get("gate_status") or "UNCALIBRATED").upper()
    return _dimension(
        dimension=str(report["dimension"]),
        gate_type=str(report["gate_type"]),
        score=report.get("score"),
        gate_status=status,
        evidence_asset_version_id=str(report.get("asset_version_id") or ""),
        weight=float(report.get("weight", 0.0)),
        blocking=bool(report.get("blocking", False)),
        calibration_status=calibration,
        source=source,
        provider_verified=bool(report.get("provider_verified")),
        human_verified=bool(report.get("human_verified")),
        quality_profile_version_id=str(report.get("quality_profile_version_id") or ""),
        platform_profile_version_id=str(report.get("platform_profile_version_id") or ""),
        waiver=dict(report.get("waiver") or {}),
    )


def _dimension(**values: Any) -> dict[str, Any]:
    return dict(values)


def _review_source(review: dict[str, Any]) -> str:
    evidence = review.get("provider_evidence", {})
    return "provider_judge" if evidence.get("real_model_call") else "fixture"


def _review_calibration(review: dict[str, Any]) -> str:
    return "PROVIDER_UNCALIBRATED" if _review_source(review) == "provider_judge" else "UNCALIBRATED"


__all__ = [
    "QUALITY_GATE_TYPES",
    "derive_quality_actions",
    "evaluate_quality_evidence",
]
