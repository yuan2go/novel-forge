"""Retrieval execution contracts; index governance remains in retrieval storage."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True, slots=True)
class EmbeddingExecutionEvidence:
    embedding_model: str
    embedding_dimension: int
    source_chunk_hashes: tuple[str, ...]
    source_eligibility: str
    batch_identity: str
    index_version: str
    usage_receipt_ref: str
    cost_receipt_ref: str
    partial_failure: bool
    dirty_index: bool

    def __post_init__(self) -> None:
        if not all(
            (
                self.embedding_model,
                self.source_chunk_hashes,
                self.source_eligibility,
                self.batch_identity,
                self.index_version,
                self.usage_receipt_ref,
                self.cost_receipt_ref,
            )
        ) or self.embedding_dimension <= 0:
            raise ValueError("embedding execution evidence is incomplete")


@dataclass(frozen=True, slots=True)
class EmbeddingCandidate:
    vectors: tuple[tuple[float, ...], ...]
    evidence: EmbeddingExecutionEvidence

    def __post_init__(self) -> None:
        if not self.vectors or any(
            len(vector) != self.evidence.embedding_dimension for vector in self.vectors
        ):
            raise ValueError("embedding candidate dimensions do not match evidence")


@dataclass(frozen=True, slots=True)
class RerankExecutionEvidence:
    candidate_set_version: str
    route_snapshot_id: str
    input_manifest_ref: str
    ordered_scores: tuple[tuple[str, float], ...]
    usage_receipt_ref: str
    cost_receipt_ref: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.candidate_set_version,
                self.route_snapshot_id,
                self.input_manifest_ref,
                self.ordered_scores,
                self.usage_receipt_ref,
                self.cost_receipt_ref,
            )
        ):
            raise ValueError("rerank execution evidence is incomplete")
        scores = [score for _, score in self.ordered_scores]
        if scores != sorted(scores, reverse=True):
            raise ValueError("rerank evidence must preserve descending score order")


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    ordered_candidate_ids: tuple[str, ...]
    evidence: RerankExecutionEvidence

    def __post_init__(self) -> None:
        evidence_ids = tuple(item[0] for item in self.evidence.ordered_scores)
        if not self.ordered_candidate_ids or self.ordered_candidate_ids != evidence_ids:
            raise ValueError(
                "rerank candidate order must match the frozen scoring evidence"
            )


class RetrievalExecutionPort(Protocol):
    embedding_model: str
    embedding_dimension: int

    def embed_batch(
        self,
        texts: list[str],
        *,
        evidence_context: Mapping[str, Any],
    ) -> EmbeddingCandidate: ...

    def rerank(
        self,
        query: str,
        candidate_ids: tuple[str, ...],
        *,
        evidence_context: Mapping[str, Any],
    ) -> RerankCandidate: ...


__all__ = [
    "EmbeddingCandidate",
    "EmbeddingExecutionEvidence",
    "RerankCandidate",
    "RerankExecutionEvidence",
    "RetrievalExecutionPort",
]
