"""INVARIANT: importing shared context value objects must not trigger package side effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ContextClass(StrEnum):

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
    book_id: str = ""
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
    logical_context_kind: str = ""
    source_identity: str = ""
    logical_narrative_identity: str = ""
    semantic_representation_identity: str = ""
    source_revision: str = ""
    accepted_boundary: dict[str, Any] | None = None
    section: str = "NARRATIVE"
    bucket: str = "GENERAL"
    required: bool = False
    representation_status: str = "ACTIVE"
    read_generation_id: str = ""
    active_read_generation_id: str = ""
    truncation_strategy: str = ""
    truncation_version: str = ""

    def __post_init__(self) -> None:
        try:
            context_class = ContextClass(str(self.context_class).upper())
        except ValueError as exc:
            raise ValueError(
                "context candidate class must be PROTECTED, COMPRESSIBLE, "
                "RETRIEVABLE, or EPHEMERAL"
            ) from exc
        object.__setattr__(self, "context_class", context_class)
        object.__setattr__(
            self,
            "logical_context_kind",
            self.logical_context_kind.strip() or self.asset_type,
        )
        object.__setattr__(
            self,
            "source_identity",
            self.source_identity.strip() or self.asset_version_id,
        )
        object.__setattr__(
            self,
            "source_revision",
            self.source_revision.strip() or self.content_digest,
        )
        object.__setattr__(self, "section", self.section.strip().upper())
        object.__setattr__(self, "bucket", self.bucket.strip() or self.asset_type)
        object.__setattr__(
            self,
            "accepted_boundary",
            dict(self.accepted_boundary or {}),
        )
        if not self.section or not self.bucket:
            raise ValueError("context candidate section and bucket are required")
        if context_class is ContextClass.EPHEMERAL and (
            self.memory_layer or self.retrieval_reasons or self.retrieval_scores
        ):
            raise ValueError(
                "ephemeral context cannot participate in Memory or Search projection"
            )


__all__ = ["ContextCandidate", "ContextClass"]
