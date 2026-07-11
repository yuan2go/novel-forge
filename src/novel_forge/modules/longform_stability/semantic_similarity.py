from __future__ import annotations

"""Provider-aware cross-chapter similarity evidence.

The local hash adapter is intentionally retained as an offline regression
signal.  It is never labelled as a semantic model and its evidence cannot be
used to claim premium prose quality.  A configured embedding provider can be
injected without changing the chapter-pattern contract.
"""

import os
from typing import Any, Mapping, Protocol

from novel_forge.model_adapters import HashEmbeddingAdapter, cosine_similarity, embedding_adapter_from_env


class SimilarityEmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed_text(self, text: str) -> list[float]: ...

    def health_check(self) -> dict[str, Any]: ...


def resolve_similarity_provider(
    *,
    adapter: SimilarityEmbeddingProvider | None = None,
    environment: str = "",
    env: Mapping[str, str] | None = None,
    strict: bool = False,
) -> tuple[SimilarityEmbeddingProvider, dict[str, Any]]:
    """Resolve a semantic provider and describe whether evidence is verified.

    Local/offline runs deliberately use HashEmbedding.  When an external
    provider is configured but unavailable, local fallback is explicit and
    marked ``regression_only``; strict callers can fail closed instead.
    """

    values = os.environ if env is None else env
    requested = str(values.get("NOVEL_FORGE_EMBEDDING_PROVIDER") or "").strip().lower()
    production = str(environment or values.get("NOVEL_FORGE_ENV") or "").strip().lower() in {"production", "prod"}
    if adapter is not None:
        info = _provider_info(adapter, fallback_used=False)
        if strict and not info["semantic_model"]:
            raise RuntimeError("strict semantic similarity requires a semantic embedding provider")
        return adapter, info

    # Keep deterministic local behavior when no provider has been configured.
    if not requested and not production:
        local = HashEmbeddingAdapter(dimensions=int(values.get("NOVEL_FORGE_HASH_EMBEDDING_DIMENSIONS", "128")))
        return local, _provider_info(local, fallback_used=False, status="regression_only")

    try:
        candidate = embedding_adapter_from_env(env=values, require_semantic=True)
        info = _provider_info(candidate, fallback_used=False)
        if strict and not info["semantic_model"]:
            raise RuntimeError("configured embedding provider is not semantic")
        return candidate, info
    except Exception as exc:
        if strict:
            raise RuntimeError(f"semantic embedding provider unavailable: {exc}") from exc
        local = HashEmbeddingAdapter(dimensions=int(values.get("NOVEL_FORGE_HASH_EMBEDDING_DIMENSIONS", "128")))
        return local, _provider_info(
            local,
            fallback_used=True,
            status="regression_only",
            fallback_reason=str(exc),
        )


def score_similarity(
    current_text: str,
    previous_text: str,
    *,
    provider: SimilarityEmbeddingProvider,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return explainable lexical, embedding, and composite similarity scores."""

    current_embedding = provider.embed_text(current_text)
    previous_embedding = provider.embed_text(previous_text)
    lexical = _jaccard(_tokens(current_text), _tokens(previous_text))
    embedding = max(-1.0, min(1.0, cosine_similarity(current_embedding, previous_embedding)))
    # Cosine can be negative for unrelated text; normalize to a risk score.
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
