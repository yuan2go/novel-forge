"""Shared storage-free context value objects without package import side effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ContextClass(StrEnum):
    """Governed lifecycle class for content sent to a model task."""

    PROTECTED = "PROTECTED"
    COMPRESSIBLE = "COMPRESSIBLE"
    RETRIEVABLE = "RETRIEVABLE"
    EPHEMERAL = "EPHEMERAL"


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
    authority_freshness: str = "CURRENT"
    semantic_projection: bool = True
    context_class: ContextClass | str = ContextClass.RETRIEVABLE
    memory_layer: str = ""
    retrieval_reasons: tuple[str, ...] = ()
    retrieval_scores: dict[str, float] | None = None
    provenance: dict[str, Any] | None = None
    compression_trace: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        try:
            context_class = ContextClass(str(self.context_class).upper())
        except ValueError as exc:
            raise ValueError(
                "context candidate class must be PROTECTED, COMPRESSIBLE, "
                "RETRIEVABLE, or EPHEMERAL"
            ) from exc
        object.__setattr__(self, "context_class", context_class)
        if context_class is ContextClass.EPHEMERAL and (
            self.memory_layer or self.retrieval_reasons or self.retrieval_scores
        ):
            raise ValueError(
                "ephemeral context cannot participate in Memory or Search projection"
            )


__all__ = ["ContextCandidate", "ContextClass"]
