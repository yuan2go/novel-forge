from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProductionInputRole(StrEnum):
    PLAN = "plan"
    PROFILE = "profile"
    STATE = "state"
    CONTEXT = "context"
    GOVERNANCE = "governance"
    APPROVAL = "approval"


class ProductionPreparationDecision(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


@dataclass(frozen=True, slots=True)
class ProductionPreparationRequest:
    project_id: str
    workspace_id: str
    chapter: int
    idempotency_key: str
    book_id: str = ""
    title_override: str = ""
    premise_override: str = ""
    explicit_asset_version_overrides: dict[str, str | list[str]] = field(default_factory=dict)
    requested_quality_profile: str = "default"
    requested_platform_profile: str = "default"
    operator_decision: dict[str, Any] = field(default_factory=dict)
    context_token_budget: int = 6000
    context_profile_version: str = "draft-context-profile-v2"
    stage: str = "draft"
    capability_required_asset_types: tuple[str, ...] = ()
    knowledge_access_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProductionInputRequirement:
    asset_type: str
    role: ProductionInputRole
    required: bool
    cardinality: str = "one"
    minimum_count: int = 1


@dataclass(frozen=True, slots=True)
class ResolvedProductionAsset:
    project_id: str
    asset_id: str
    asset_version_id: str
    asset_type: str
    content_hash: str
    content: dict[str, Any]
    qualification: str
    selected_reason: str


@dataclass(frozen=True, slots=True)
class ProductionInputCandidate:
    asset_version_id: str
    asset_type: str
    role: str
    entity_id: str
    scope: dict[str, Any]
    priority: int


@dataclass(frozen=True, slots=True)
class ProductionInputSelection:
    asset_version_id: str
    asset_type: str
    role: str
    selection_reason: str
    entity_id: str = ""


@dataclass(frozen=True, slots=True)
class ProductionInputRejection:
    asset_version_id: str
    asset_type: str
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProductionPreparationRisk:
    code: str
    severity: str
    approval_type: str
    target_asset_version_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductionPreparationRepairAction:
    code: str
    action: str
    asset_type: str = ""


@dataclass(frozen=True, slots=True)
class ProductionInputManifest:
    project_id: str
    book_id: str
    workspace_id: str
    chapter: int
    stage: str
    quality_profile_version_id: str
    platform_profile_version_id: str
    style_policy_version_id: str
    chapter_plan_version_id: str
    outline_version_id: str
    volume_arc_version_id: str
    world_bible_version_id: str
    canon_snapshot_version_id: str
    context_profile_version_id: str
    selected_asset_versions: tuple[dict[str, Any], ...]
    rejected_asset_versions: tuple[dict[str, Any], ...]
    entity_scopes: dict[str, list[str]]
    selection_reasons: dict[str, str]
    rejection_reasons: dict[str, str]
    source_governance: dict[str, Any]
    qualification_evidence: dict[str, str]
    token_budget: int
    provider_budget: dict[str, Any]
    approval_requirements: tuple[dict[str, Any], ...]
    risk_summary: tuple[dict[str, Any], ...]
    knowledge_access_policy: dict[str, Any]
    manifest_digest: str
    created_by_operation_id: str
    contract_version: str = "production-input-manifest-v2"


@dataclass(frozen=True, slots=True)
class ProductionPreparationReport:
    project_id: str
    chapter: int
    decision: str
    selected_asset_version_ids: tuple[str, ...]
    selection_reasons: dict[str, str]
    missing_required_asset_types: tuple[str, ...]
    blocked_assets: tuple[dict[str, str], ...]
    approval_requirements: tuple[str, ...]
    context_digest: str
    estimated_token_budget: int
    estimated_provider_budget: dict[str, Any]
    repair_actions: tuple[str, ...]
    idempotency_key: str
    production_input_manifest: dict[str, Any] = field(default_factory=dict)
    risks: tuple[dict[str, Any], ...] = ()
    chapter_plan_qualification_profile: dict[str, Any] = field(default_factory=dict)
    stage_context_profile_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChapterAuthorityCommand:
    project_id: str
    book_id: str
    workspace_id: str
    chapter: int
    chapter_plan_asset_version_id: str
    chapter_plan_content_hash: str
    title: str
    premise: str
    context_candidates: tuple[dict[str, Any], ...]
    context_version_refs: dict[str, Any]
    context_token_budget: int
    preparation_report: dict[str, Any]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ProductionPreparationResult:
    report: ProductionPreparationReport
    command: ChapterAuthorityCommand | None
