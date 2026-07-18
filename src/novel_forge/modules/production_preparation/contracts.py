from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProductionPreparationRequest:
    project_id: str
    workspace_id: str
    chapter: int
    idempotency_key: str
    title_override: str = ""
    premise_override: str = ""
    explicit_asset_version_overrides: dict[str, str] = field(default_factory=dict)
    requested_quality_profile: str = "default"
    requested_platform_profile: str = "default"
    operator_decision: dict[str, Any] = field(default_factory=dict)
    context_token_budget: int = 6000


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


@dataclass(frozen=True, slots=True)
class ChapterAuthorityCommand:
    project_id: str
    workspace_id: str
    chapter: int
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
