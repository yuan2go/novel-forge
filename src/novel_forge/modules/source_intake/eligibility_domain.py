"""Storage-free source eligibility, impact, and regeneration planning."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SourceGovernanceEvidence:
    source_asset_version_id: str
    project_id: str
    source_policy_version: str
    license_check_version: str
    source_risk_report_version: str
    source_snapshot_version: str
    copyright_clear: bool
    license_id: str
    commercial_use_allowed: bool
    generation_context_allowed: bool
    raw_text_allowed: bool
    structure_use_allowed: bool = True
    privacy_clear: bool = True
    prompt_injection_clear: bool = True
    source_trust: float = 1.0
    stale: bool = False
    quarantined: bool = False
    revoked: bool = False
    approval_required: bool = False


def decide_source_eligibility(
    *,
    project_id: str,
    evidence: SourceGovernanceEvidence,
    trust_threshold: float = 0.6,
) -> dict[str, Any]:
    if not project_id or not evidence.source_asset_version_id:
        raise ValueError("project and versioned source evidence are required")
    reasons: list[str] = []
    status = "ELIGIBLE"
    use_mode = "generation"
    # Decisions are evaluated in descending severity.  A cross-project or revoked
    # source is terminal and cannot be downgraded by a later stale/approval branch.
    if evidence.project_id != project_id:
        status, use_mode = "REVOKED", "quarantine"
        reasons.append("cross_project")
    elif evidence.revoked:
        status, use_mode = "REVOKED", "quarantine"
        reasons.append("eligibility_revoked")
    elif evidence.quarantined or not evidence.privacy_clear or not evidence.prompt_injection_clear:
        status, use_mode = "QUARANTINED", "quarantine"
        reasons.extend(
            name for name, clear in (
                ("source_quarantined", not evidence.quarantined),
                ("privacy_risk", evidence.privacy_clear),
                ("prompt_injection_risk", evidence.prompt_injection_clear),
            ) if not clear
        )
    elif evidence.stale:
        status, use_mode = "STALE", "review_only"
        reasons.append("source_snapshot_stale")
    elif evidence.approval_required:
        status, use_mode = "REQUIRES_APPROVAL", "review_only"
        reasons.append("operator_approval_required")
    elif evidence.source_trust < trust_threshold:
        status, use_mode = "REQUIRES_APPROVAL", "review_only"
        reasons.append("source_trust_below_threshold")
    elif not evidence.copyright_clear or not evidence.license_id:
        status = "REQUIRES_APPROVAL"
        use_mode = "structure_only" if evidence.structure_use_allowed else "quarantine"
        reasons.append("copyright_or_license_unproven")
    elif not evidence.commercial_use_allowed:
        status, use_mode = "REQUIRES_APPROVAL", "review_only"
        reasons.append("commercial_use_forbidden")
    elif not evidence.generation_context_allowed:
        status = "ELIGIBLE" if evidence.structure_use_allowed else "REQUIRES_APPROVAL"
        use_mode = "structure_only" if evidence.structure_use_allowed else "review_only"
        reasons.append("generation_context_forbidden")
    elif not evidence.raw_text_allowed:
        reasons.append("raw_text_forbidden_abstract_assets_only")
    return {
        "source_asset_version_id": evidence.source_asset_version_id,
        "project_id": project_id,
        "status": status,
        "use_mode": use_mode,
        "generation_allowed": status == "ELIGIBLE" and use_mode == "generation",
        "raw_text_allowed": evidence.raw_text_allowed and use_mode == "generation",
        "reasons": reasons or ["governance_clear"],
        "policy_versions": {
            "source_policy": evidence.source_policy_version,
            "license_check": evidence.license_check_version,
            "risk_report": evidence.source_risk_report_version,
            "snapshot": evidence.source_snapshot_version,
        },
        "eligibility_contract_version": "source-eligibility-v1",
    }


def build_change_impact_report(
    *,
    project_id: str,
    changed_asset_version_id: str,
    previous_snapshot_version: str,
    current_snapshot_version: str,
    affected_assets: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    all_affected = list(affected_assets)
    affected = [item for item in all_affected if item.get("project_id") == project_id]
    return {
        "project_id": project_id,
        "changed_asset_version_id": changed_asset_version_id,
        "previous_snapshot_version": previous_snapshot_version,
        "current_snapshot_version": current_snapshot_version,
        "affected_context_bundle_versions": sorted({str(item["asset_version_id"]) for item in affected if item.get("asset_type") == "context_bundle"}),
        "affected_knowledge_pack_versions": sorted({str(item["asset_version_id"]) for item in affected if item.get("asset_type") == "knowledge_pack"}),
        "affected_review_rule_versions": sorted({str(item["asset_version_id"]) for item in affected if item.get("asset_type") == "review_rule"}),
        "cross_project_assets_ignored": sum(item.get("project_id") != project_id for item in all_affected),
        "accepted_prose_mutation_allowed": False,
        "impact_contract_version": "source-change-impact-v1",
    }


def build_regeneration_plan(impact: dict[str, Any], *, risk_level: str) -> dict[str, Any]:
    high_risk = risk_level.lower() in {"high", "critical"}
    return {
        "project_id": impact["project_id"],
        "rebuild_context_bundle_versions": list(impact["affected_context_bundle_versions"]),
        "rebuild_knowledge_pack_versions": list(impact["affected_knowledge_pack_versions"]),
        "revalidate_review_rule_versions": list(impact["affected_review_rule_versions"]),
        "approval_request_required": high_risk,
        "allowed_automatic_actions": ["projection_rebuild"] if high_risk else ["projection_rebuild", "context_candidate_refresh"],
        "forbidden_automatic_actions": ["mutate_accepted_prose", "mutate_canon", "mutate_outline", "mutate_character_core"],
        "regeneration_contract_version": "source-regeneration-plan-v1",
    }


__all__ = [
    "SourceGovernanceEvidence",
    "build_change_impact_report",
    "build_regeneration_plan",
    "decide_source_eligibility",
]
