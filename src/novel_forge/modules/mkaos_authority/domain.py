"""Deterministic MKAOS candidate, evidence, approval and pack invariants."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


FORBIDDEN_SOURCE_KEYS = frozenset(
    {
        "raw",
        "raw_content",
        "raw_source",
        "raw_text",
        "clean_text",
        "source_content",
        "source_text",
        "original_sentence",
        "original_sentences",
        "excerpt",
        "excerpts",
        "quote",
        "quotes",
        "content_base64",
    }
)


@dataclass(frozen=True, slots=True)
class KnowledgeEvidenceSpan:
    source_chunk_asset_version_id: str
    chunk_byte_start: int
    chunk_byte_end: int
    evidence_hash: str

    def __post_init__(self) -> None:
        if not self.source_chunk_asset_version_id.strip():
            raise ValueError("source chunk AssetVersion identity is required")
        if self.chunk_byte_start < 0 or self.chunk_byte_end <= self.chunk_byte_start:
            raise ValueError("knowledge evidence span is invalid")
        _require_sha256(self.evidence_hash, "knowledge evidence Hash")


@dataclass(frozen=True, slots=True)
class KnowledgePackSelection:
    knowledge_card_asset_version_id: str
    usage_role: str
    frozen_weight: Decimal

    def __post_init__(self) -> None:
        if not self.knowledge_card_asset_version_id.strip():
            raise ValueError("KnowledgeCard AssetVersion identity is required")
        normalized_role = self.usage_role.strip().upper()
        if normalized_role not in {"PRINCIPLE", "CONSTRAINT", "CHECK", "REFERENCE"}:
            raise ValueError("KnowledgePack usage role is invalid")
        try:
            weight = Decimal(str(self.frozen_weight))
        except InvalidOperation as exc:
            raise ValueError("KnowledgePack weight is invalid") from exc
        if weight <= 0 or weight > 100:
            raise ValueError("KnowledgePack weight must be within (0, 100]")
        object.__setattr__(self, "usage_role", normalized_role)
        object.__setattr__(self, "frozen_weight", weight)


def validate_knowledge_candidate(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise KernelError("MKAOS_CANDIDATE_INVALID", "candidate must be an object")
    candidate = dict(payload)
    required_strings = (
        "concept_name",
        "discipline",
        "abstract_principle",
    )
    for field in required_strings:
        value = candidate.get(field)
        if not isinstance(value, str) or not value.strip():
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"candidate {field} is required"
            )
    for field in (
        "constraints",
        "conflict_generators",
        "review_checks",
        "copyright_boundaries",
    ):
        value = candidate.get(field)
        if not isinstance(value, list) or not value:
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"candidate {field} must be non-empty"
            )
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise KernelError(
                "MKAOS_CANDIDATE_INVALID", f"candidate {field} contains an invalid item"
            )
    _reject_forbidden_source_content(candidate)
    _validate_string_bounds(candidate)
    return candidate


def validate_evidence_spans(
    spans: tuple[KnowledgeEvidenceSpan, ...],
    *,
    source_chunk_sizes: Mapping[str, int],
) -> tuple[KnowledgeEvidenceSpan, ...]:
    if not spans or len(spans) > 1_000:
        raise KernelError(
            "MKAOS_EVIDENCE_INVALID", "candidate requires 1..1000 evidence spans"
        )
    ordered = tuple(
        sorted(
            spans,
            key=lambda item: (
                item.source_chunk_asset_version_id,
                item.chunk_byte_start,
                item.chunk_byte_end,
                item.evidence_hash,
            ),
        )
    )
    seen: set[tuple[str, int, int]] = set()
    for span in ordered:
        size = source_chunk_sizes.get(span.source_chunk_asset_version_id)
        if size is None:
            raise KernelError(
                "MKAOS_SOURCE_CHUNK_NOT_FOUND",
                "evidence references an unavailable SourceChunk AssetVersion",
            )
        identity = (
            span.source_chunk_asset_version_id,
            span.chunk_byte_start,
            span.chunk_byte_end,
        )
        if identity in seen:
            raise KernelError(
                "MKAOS_EVIDENCE_DUPLICATE", "duplicate evidence span is forbidden"
            )
        if span.chunk_byte_end > size:
            raise KernelError(
                "MKAOS_EVIDENCE_OUT_OF_BOUNDS",
                "evidence span exceeds the frozen SourceChunk byte size",
            )
        seen.add(identity)
    return ordered


def validate_pack_selections(
    selections: tuple[KnowledgePackSelection, ...],
) -> tuple[KnowledgePackSelection, ...]:
    if not selections or len(selections) > 500:
        raise KernelError(
            "MKAOS_PACK_SELECTION_INVALID", "KnowledgePack requires 1..500 items"
        )
    identities = [item.knowledge_card_asset_version_id for item in selections]
    if len(set(identities)) != len(identities):
        raise KernelError(
            "MKAOS_PACK_SELECTION_DUPLICATE",
            "KnowledgePack cannot contain the same KnowledgeCard version twice",
        )
    return tuple(
        sorted(
            selections,
            key=lambda item: (
                item.usage_role,
                item.knowledge_card_asset_version_id,
                str(item.frozen_weight),
            ),
        )
    )


def assert_abstract_content_safe(payload: Mapping[str, Any]) -> None:
    _reject_forbidden_source_content(payload)
    _validate_string_bounds(payload)


def _reject_forbidden_source_content(value: Any, *, path: str = "candidate") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_SOURCE_KEYS:
                raise KernelError(
                    "MKAOS_SOURCE_LEAKAGE_BLOCKED",
                    f"forbidden source-expression field at {path}.{normalized}",
                )
            _reject_forbidden_source_content(item, path=f"{path}.{normalized}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_source_content(item, path=f"{path}[{index}]")


def _validate_string_bounds(value: Any, *, path: str = "candidate") -> None:
    if isinstance(value, str):
        if len(value) > 2_000:
            raise KernelError(
                "MKAOS_ABSTRACTION_BOUNDARY_INVALID",
                f"abstract candidate string is too long at {path}",
            )
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _validate_string_bounds(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_string_bounds(item, path=f"{path}[{index}]")


def _require_sha256(value: str, label: str) -> None:
    digest = value.removeprefix("sha256:")
    if not value.startswith("sha256:") or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{label} must be canonical sha256")


__all__ = [
    "KnowledgeEvidenceSpan",
    "KnowledgePackSelection",
    "assert_abstract_content_safe",
    "validate_evidence_spans",
    "validate_knowledge_candidate",
    "validate_pack_selections",
]
