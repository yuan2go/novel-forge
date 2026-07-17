"""Storage-free aggregation of versioned chapter quality evidence."""
from __future__ import annotations

from typing import Any, Iterable

from novel_forge.modules.command_kernel.errors import KernelError


QUALITY_GATE_TYPES = (
    "structural_evidence_gate",
    "semantic_quality_gate",
    "commercial_readability_gate",
    "source_originality_gate",
    "longform_stability_gate",
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
    if review.get("decision") != "PASSED" or int(review.get("blocking_issue_count", 0)):
        raise KernelError("CHAPTER_QUALITY_GATE_FAILED", "Re-review has unresolved blockers")
    if canon.get("gate") != "PASSED" or canon.get("conflicts"):
        raise KernelError("CHAPTER_QUALITY_GATE_FAILED", "Canon evidence is blocked")
    if not str(revision.get("text") or "").strip():
        raise KernelError("CHAPTER_QUALITY_GATE_FAILED", "Revision has no content")

    dimensions: list[dict[str, Any]] = [
        _dimension(
            dimension="structural_evidence",
            gate_type="structural_evidence_gate",
            score=float(review.get("score", 0.0)),
            gate_status="PASSED",
            evidence_asset_version_id=review_asset_version_id,
            weight=.25,
            blocking=True,
            calibration_status=_review_calibration(review),
            source=_review_source(review),
        ),
        _dimension(
            dimension="canon_consistency",
            gate_type="longform_stability_gate",
            score=None,
            gate_status="PASSED",
            evidence_asset_version_id=canon_asset_version_id,
            weight=.15,
            blocking=True,
            calibration_status="DETERMINISTIC",
            source="deterministic_extractor",
        ),
    ]
    for report in evidence_reports:
        dimensions.append(_normalize_evidence_dimension(project_id, report))
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
        if item["blocking"] and item["gate_status"] not in {"PASSED", "PASSED_WITH_WARNINGS"}
    ]
    if blocking:
        raise KernelError("CHAPTER_QUALITY_GATE_FAILED", "blocking quality evidence failed")
    scored = [item for item in dimensions if isinstance(item["score"], (int, float)) and item["weight"] > 0]
    weight = sum(float(item["weight"]) for item in scored)
    aggregate_score = (
        round(sum(float(item["score"]) * float(item["weight"]) for item in scored) / weight, 4)
        if weight else None
    )
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
            if item["calibration_status"] == "UNCALIBRATED"
        ],
        "fixture": all(item["source"] in {"fixture", "none", "deterministic_extractor"} for item in dimensions),
        "production_verified": False,
        "gate": "PASSED_WITH_UNCALIBRATED" if any(item["calibration_status"] == "UNCALIBRATED" for item in dimensions) else "PASSED",
        "quality_contract_version": "chapter-quality-aggregate-v1",
    }


def _normalize_evidence_dimension(project_id: str, report: dict[str, Any]) -> dict[str, Any]:
    if report.get("project_id") != project_id:
        raise KernelError("CROSS_PROJECT_REFERENCE", "quality evidence belongs to another project")
    calibration = str(report.get("calibration_status") or "UNCALIBRATED").upper()
    source = str(report.get("source") or "fixture")
    if source == "fixture":
        calibration = "UNCALIBRATED"
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
    )


def _dimension(**values: Any) -> dict[str, Any]:
    return dict(values)


def _review_source(review: dict[str, Any]) -> str:
    evidence = review.get("provider_evidence", {})
    return "provider_judge" if evidence.get("real_model_call") else "fixture"


def _review_calibration(review: dict[str, Any]) -> str:
    return "PROVIDER_UNCALIBRATED" if _review_source(review) == "provider_judge" else "UNCALIBRATED"


__all__ = ["QUALITY_GATE_TYPES", "evaluate_quality_evidence"]
