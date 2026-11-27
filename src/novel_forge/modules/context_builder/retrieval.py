from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


_TOKEN = re.compile(r"[\w\u3400-\u9fff]+", re.UNICODE)

RANKING_POLICY_VERSION = "accepted-lexical-first-ranking-v4"
RANKING_WEIGHTS = {
    "postgresql_fts": 0.16,
    "lexical_overlap": 0.06,
    "embedding": 0.18,
    "entity": 0.10,
    "relationship": 0.10,
    "character_timeline": 0.10,
    "temporal": 0.08,
    "arc": 0.11,
    "obligation": 0.11,
}


@dataclass(frozen=True, slots=True)
class HybridRetrievalQuery:
    text: str
    accepted_through_chapter: int
    entity_ids: tuple[str, ...] = ()
    relationship_ids: tuple[str, ...] = ()
    character_ids: tuple[str, ...] = ()
    arc_plan_version_ids: tuple[str, ...] = ()
    obligation_ids: tuple[str, ...] = ()
    query_embedding: tuple[float, ...] = ()
    limit: int = 24


def _tokens(value: str) -> set[str]:
    return {item.lower() for item in _TOKEN.findall(value)}


def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
    a, b = tuple(left), tuple(right)
    if not a or len(a) != len(b):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in a)) * math.sqrt(sum(v * v for v in b))
    return (
        0.0
        if denominator == 0
        else sum(x * y for x, y in zip(a, b, strict=True)) / denominator
    )


def hybrid_retrieve(
    query: HybridRetrievalQuery,
    documents: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """INVARIANT: Rank one already-bounded lexical/structured candidate set.

    Embeddings can only rerank documents supplied by discovery. This pure
    function never performs semantic candidate discovery.
    """
    query_tokens = _tokens(query.text)
    ranked: list[dict[str, Any]] = []
    for raw in documents:
        document = dict(raw)
        accepted_from = int(document.get("accepted_from_chapter") or 0)
        accepted_to = document.get("accepted_to_chapter")
        if accepted_from > query.accepted_through_chapter or (
            accepted_to is not None
            and query.accepted_through_chapter > int(accepted_to)
        ):
            continue
        content_tokens = _tokens(str(document.get("content_text") or ""))
        lexical_overlap = (
            len(query_tokens & content_tokens) / max(1, len(query_tokens))
            if query_tokens
            else 0.0
        )
        postgresql_fts = max(
            0.0, min(1.0, float(document.get("postgresql_fts_rank") or 0.0))
        )
        embedding = _cosine(
            query.query_embedding,
            tuple(float(item) for item in document.get("embedding") or ()),
        )
        entity = _overlap(query.entity_ids, document.get("entity_ids") or ())
        relationship = _overlap(
            query.relationship_ids, document.get("relationship_ids") or ()
        )
        character = _overlap(query.character_ids, document.get("character_ids") or ())
        arc = _overlap(
            query.arc_plan_version_ids, document.get("arc_plan_version_ids") or ()
        )
        obligation = _overlap(
            query.obligation_ids, document.get("obligation_ids") or ()
        )
        distance = max(0, query.accepted_through_chapter - accepted_from)
        temporal = 1.0 / (1.0 + distance)
        scores = {
            "postgresql_fts": postgresql_fts,
            "lexical_overlap": lexical_overlap,
            "lexical": lexical_overlap,
            "embedding": embedding,
            "entity": entity,
            "relationship": relationship,
            "character_timeline": character,
            "temporal": temporal,
            "arc": arc,
            "obligation": obligation,
        }
        total = sum(
            scores[signal] * weight for signal, weight in RANKING_WEIGHTS.items()
        )
        reasons = [key for key, value in scores.items() if value > 0]
        ranked.append(
            {
                **document,
                "retrieval_scores": scores,
                "retrieval_score": total,
                "retrieval_reasons": reasons,
            }
        )
    ranked.sort(
        key=lambda item: (
            -float(item["retrieval_score"]),
            -int(item.get("accepted_from_chapter") or 0),
            str(item.get("retrieval_document_id") or ""),
        )
    )
    return tuple(ranked[: max(0, query.limit)])


def _overlap(expected: Iterable[str], actual: Iterable[str]) -> float:
    left = {str(item) for item in expected if str(item)}
    if not left:
        return 0.0
    right = {str(item) for item in actual if str(item)}
    return len(left & right) / len(left)


__all__ = [
    "RANKING_POLICY_VERSION",
    "RANKING_WEIGHTS",
    "HybridRetrievalQuery",
    "hybrid_retrieve",
]
