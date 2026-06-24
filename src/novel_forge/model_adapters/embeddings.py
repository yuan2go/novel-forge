from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class EmbeddingAdapter(Protocol):
    name: str
    dimensions: int

    def embed_text(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    def health_check(self) -> dict: ...


@dataclass(frozen=True)
class HashEmbeddingAdapter:
    """Deterministic local embedding adapter for tests and offline retrieval plumbing.

    This is not a semantic model. It creates stable hashed bag-of-token vectors so
    vector indexing, cosine scoring, cache invalidation, and CLI contracts can be
    tested without network calls or third-party dependencies.
    """

    dimensions: int = 64
    name: str = "hash-embedding"

    def embed_text(self, text: str) -> list[float]:
        if self.dimensions < 8:
            raise ValueError("embedding dimensions must be at least 8")
        vector = [0.0] * self.dimensions
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def health_check(self) -> dict:
        return {
            "model": self.name,
            "ok": True,
            "dimensions": self.dimensions,
            "external_api": False,
            "semantic_model": False,
        }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    return sum(a * b for a, b in zip(left, right))


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)]


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 8) for value in vector]
