"""CONSTRAINT: the local hash adapter is only an offline regression signal and cannot qualify semantic-model or prose-quality claims."""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from novel_forge.modules.production_execution import (
    RetrievalExecutionPort,
    execute_similarity_embedding_pair,
)
from novel_forge.modules.production_execution.security import execution_environment


class SimilarityEmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed_text(self, text: str) -> list[float]: ...

    def health_check(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class LocalHashSimilarityProvider:

    dimensions: int = 128
    name: str = "longform-local-hash"

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "model": self.name,
            "dimensions": self.dimensions,
            "semantic_model": False,
            "external_api": False,
        }


def resolve_similarity_provider(
    *,
    adapter: SimilarityEmbeddingProvider | None = None,
    execution_port: RetrievalExecutionPort | None = None,
    environment: str = "",
    env: Mapping[str, str] | None = None,
    strict: bool = False,
) -> tuple[SimilarityEmbeddingProvider | None, dict[str, Any]]:
    """CONSTRAINT: Resolve a semantic provider and describe whether evidence is verified.

    Local/offline runs deliberately use a deterministic hash. Remote embeddings
    are never resolved from environment variables inside the domain module.
    """
    values = os.environ if env is None else env
    requested = str(values.get("NOVEL_FORGE_EMBEDDING_PROVIDER") or "").strip().lower()
    if execution_port is not None:
        return None, {
            "kind": "production_execution",
            "name": execution_port.embedding_model,
            "dimensions": execution_port.embedding_dimension,
            "semantic_model": True,
            "external_api": True,
            "health": {"ok": True, "authority_bound": True},
            "fallback_used": False,
            "status": "execution_port_bound",
            "fallback_reason": "",
            "quality_claim_boundary": "semantic_similarity_is_regression_evidence_not_a_premium_quality_judgment",
        }
    if adapter is not None:
        info = _provider_info(adapter, fallback_used=False)
        if (
            execution_environment(environment).controlled
            and info["external_api"]
        ):
            raise RuntimeError(
                "controlled semantic similarity requires RetrievalExecutionPort"
            )
        info["status"] = "fixture_compatibility"
        if strict and not info["semantic_model"]:
            raise RuntimeError("strict semantic similarity requires a semantic embedding provider")
        return adapter, info

    if requested:
        raise RuntimeError(
            "configured remote semantic embedding requires RetrievalExecutionPort"
        )
    if strict:
        raise RuntimeError("strict semantic similarity requires RetrievalExecutionPort")
    local = LocalHashSimilarityProvider(
        dimensions=int(values.get("NOVEL_FORGE_HASH_EMBEDDING_DIMENSIONS", "128"))
    )
    return local, _provider_info(local, fallback_used=False, status="regression_only")


def score_similarity(
    current_text: str,
    previous_text: str,
    *,
    provider: SimilarityEmbeddingProvider | None,
    execution_port: RetrievalExecutionPort | None = None,
    environment: str = "",
    evidence_context: Mapping[str, Any] | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:

    current_embedding, previous_embedding, execution_evidence = (
        execute_similarity_embedding_pair(
            current_text,
            previous_text,
            execution_port=execution_port,
            legacy_provider=provider,
            environment=environment,
            evidence_context=evidence_context or {},
        )
    )
    lexical = _jaccard(_tokens(current_text), _tokens(previous_text))
    embedding = max(
        -1.0,
        min(1.0, _cosine_similarity(current_embedding, previous_embedding)),
    )
    # WHY: Cosine can be negative for unrelated text; normalize to a risk score.
    normalized_embedding = (embedding + 1.0) / 2.0
    score = (normalized_embedding * 0.65) + (lexical * 0.35)
    configured = thresholds if isinstance(thresholds, Mapping) else {}
    medium = float(configured.get("medium", 0.74) or 0.74)
    high = float(configured.get("high", 0.86) or 0.86)
    risk = "high" if score >= high else "medium" if score >= medium else "low"
    return {
        "semantic_similarity": round(score, 4),
        "embedding_similarity": round(normalized_embedding, 4),
        "lexical_similarity": round(lexical, 4),
        "risk": risk,
        "thresholds": {"medium": medium, "high": high},
        "production_execution": execution_evidence,
    }


def _provider_info(
    provider: SimilarityEmbeddingProvider,
    *,
    fallback_used: bool,
    status: str | None = None,
    fallback_reason: str = "",
) -> dict[str, Any]:
    try:
        health = provider.health_check()
    except Exception as exc:
        health = {"ok": False, "error": str(exc)}
    semantic_model = bool(health.get("semantic_model", False))
    return {
        "kind": "external_semantic" if semantic_model else "local_hash",
        "name": str(getattr(provider, "name", provider.__class__.__name__)),
        "dimensions": int(getattr(provider, "dimensions", 0) or 0),
        "semantic_model": semantic_model,
        "external_api": bool(health.get("external_api", False)),
        "health": health,
        "fallback_used": bool(fallback_used),
        "status": status or ("verified" if semantic_model and health.get("ok", False) else "unverified"),
        "fallback_reason": fallback_reason,
        "quality_claim_boundary": "semantic_similarity_is_regression_evidence_not_a_premium_quality_judgment",
    }


def _tokens(text: str) -> set[str]:
    return {char for char in str(text or "").lower() if char.isalnum() or "\u4e00" <= char <= "\u9fff"}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    return sum(a * b for a, b in zip(left, right))
