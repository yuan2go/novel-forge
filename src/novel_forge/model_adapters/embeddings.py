from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Mapping, Protocol
import urllib.error
import urllib.request

from novel_forge.model_adapters.base import AdapterNotConfiguredError

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", re.UNICODE)
CJK_PATTERN = re.compile(r"^[\u4e00-\u9fff]+$")


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


class OpenAICompatibleEmbeddingAdapter:
    """Embedding adapter for OpenAI-compatible `/v1/embeddings` APIs."""

    api_key_env = "OPENAI_API_KEY"
    model_env = "OPENAI_EMBEDDING_MODEL"
    base_url_env = "OPENAI_EMBEDDINGS_URL"
    dimensions_env = "OPENAI_EMBEDDING_DIMENSIONS"
    request_dimensions_env = "OPENAI_EMBEDDING_REQUEST_DIMENSIONS"
    default_model = "text-embedding-3-small"
    default_base_url = "https://api.openai.com/v1/embeddings"
    timeout_seconds = 90

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env
        self.name = "openai-compatible-embedding"
        self.dimensions = int(self.env.get(self.dimensions_env, "1536"))

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        api_key = self._api_key()
        if not api_key:
            raise AdapterNotConfiguredError(f"embedding adapter cannot run: missing {self.api_key_env}")
        payload: dict[str, object] = {
            "model": self._model(),
            "input": texts,
        }
        requested_dimensions = self.env.get(self.request_dimensions_env, "")
        if requested_dimensions:
            payload["dimensions"] = int(requested_dimensions)
        request = urllib.request.Request(
            self._base_url(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"embedding API returned HTTP {exc.code}: {detail[:500]}") from exc
        except Exception as exc:
            raise RuntimeError(f"embedding API call failed: {exc}") from exc

        rows = response_data.get("data", [])
        if not isinstance(rows, list):
            raise RuntimeError("embedding API response missing data list")
        ordered = sorted(rows, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
        vectors: list[list[float]] = []
        for row in ordered:
            if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
                raise RuntimeError("embedding API response row missing embedding vector")
            vector = [float(value) for value in row["embedding"]]
            if self.dimensions and len(vector) != self.dimensions:
                raise RuntimeError(
                    f"embedding API returned {len(vector)} dimensions, expected {self.dimensions}; "
                    f"set {self.dimensions_env} to the provider's actual vector size"
                )
            vectors.append(vector)
        if len(vectors) != len(texts):
            raise RuntimeError(f"embedding API returned {len(vectors)} vectors for {len(texts)} inputs")
        return vectors

    def health_check(self) -> dict:
        missing = [self.api_key_env] if not self._api_key() else []
        return {
            "model": self._model(),
            "provider": "openai-compatible",
            "ok": not missing,
            "configured": not missing,
            "dimensions": self.dimensions,
            "external_api": True,
            "semantic_model": True,
            "base_url": self._base_url(),
            "required_env_vars": [self.api_key_env],
            "missing_env_vars": missing,
            "message": "ready for semantic embeddings" if not missing else "missing API key",
        }

    def _api_key(self) -> str:
        return self.env.get(self.api_key_env, "")

    def _model(self) -> str:
        return self.env.get(self.model_env, self.default_model)

    def _base_url(self) -> str:
        return self.env.get(self.base_url_env, self.default_base_url)


def embedding_adapter_from_env(
    env: Mapping[str, str] | None = None,
    require_semantic: bool = False,
) -> EmbeddingAdapter:
    values = os.environ if env is None else env
    default_provider = "openai" if require_semantic else "hash"
    provider = values.get("NOVEL_FORGE_EMBEDDING_PROVIDER", default_provider).strip().lower()
    if provider in {"openai", "openai-compatible", "chatgpt"}:
        return OpenAICompatibleEmbeddingAdapter(values)
    if provider == "hash":
        if require_semantic and values.get("NOVEL_FORGE_ALLOW_HASH_QDRANT", "").strip().lower() not in {"1", "true", "yes"}:
            raise AdapterNotConfiguredError(
                "Qdrant requires a real semantic embedding provider. "
                "Set NOVEL_FORGE_EMBEDDING_PROVIDER=openai and OPENAI_API_KEY, "
                "or set NOVEL_FORGE_ALLOW_HASH_QDRANT=true only for tests."
            )
        return HashEmbeddingAdapter(dimensions=int(values.get("NOVEL_FORGE_HASH_EMBEDDING_DIMENSIONS", "64")))
    raise ValueError(f"unknown embedding provider: {provider}")


def embedding_provider_health(env: Mapping[str, str] | None = None, require_semantic: bool = True) -> dict:
    try:
        adapter = embedding_adapter_from_env(env=env, require_semantic=require_semantic)
        return adapter.health_check()
    except Exception as exc:
        return {
            "ok": False,
            "configured": False,
            "external_api": True,
            "semantic_model": require_semantic,
            "error": str(exc),
        }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    return sum(a * b for a, b in zip(left, right))


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(text):
        token = match.group(0).lower()
        tokens.append(token)
        if CJK_PATTERN.match(token):
            tokens.extend(_cjk_ngrams(token))
    return tokens


def _cjk_ngrams(token: str) -> list[str]:
    if len(token) <= 1:
        return []
    grams = list(token)
    grams.extend(token[index : index + 2] for index in range(len(token) - 1))
    return grams


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 8) for value in vector]
