"""Shared storage-free context value objects without package import side effects."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    asset_version_id: str
    asset_type: str
    project_id: str
    estimated_tokens: int
    relevance_score: float = 0.0
    qualification: str = "ELIGIBLE"
    governance_status: str = "CLEAR"
    source_use_mode: str = "generation"
    source_risk: int = 0
    raw_source: bool = False
    content_digest: str = ""
    policy_version: str = ""
    invalidation_keys: tuple[str, ...] = ()
    narrative_function: str = ""
    safe_summary: str = ""
    structured_facts: tuple[dict[str, Any], ...] = ()
    allowed_use: str = "generation"
    compression_method: str = "safe_summary"
    physical_asset_type: str = ""


__all__ = ["ContextCandidate"]
