from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.model_adapters.embeddings import EmbeddingAdapter, embedding_adapter_from_env
from novel_forge.storage.local import LocalStorage


def build_qdrant_index(
    storage: LocalStorage,
    settings: IndustrialSettings,
    adapter: EmbeddingAdapter | None = None,
) -> dict[str, Any]:
    adapter = adapter or embedding_adapter_from_env(require_semantic=True)
    _require_semantic_embedding(adapter)
    client, models = _qdrant_client(settings)
    _ensure_collection(client, models, settings.qdrant_collection, adapter.dimensions)
    points = []
    indexed = 0
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            search_text = _search_text(data)
            points.append(
                models.PointStruct(
                    id=_point_id(path.relative_to(storage.root)),
                    vector=adapter.embed_text(search_text),
                    payload=_payload(storage, category, path, data, search_text),
                )
            )
            indexed += 1
            if len(points) >= 100:
                client.upsert(collection_name=settings.qdrant_collection, points=points)
                points = []
    if points:
        client.upsert(collection_name=settings.qdrant_collection, points=points)
    return {
        "collection": settings.qdrant_collection,
        "indexed": indexed,
        "embedding": adapter.health_check(),
        "backend": "qdrant",
    }


def qdrant_search_assets(
    storage: LocalStorage,
    settings: IndustrialSettings,
    query: str,
    category: str | None = None,
    asset_type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
    adapter: EmbeddingAdapter | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    adapter = adapter or embedding_adapter_from_env(require_semantic=True)
    _require_semantic_embedding(adapter)
    client, models = _qdrant_client(settings)
    query_vector = adapter.embed_text(query)
    query_filter = _build_filter(models, category, asset_type, tags or [])
    hits = _search(client, settings.qdrant_collection, query_vector, query_filter, limit)
    results: list[dict[str, Any]] = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        results.append(
            {
                "path": payload.get("path", ""),
                "category": payload.get("category", ""),
                "type": payload.get("type", ""),
                "title": payload.get("title", ""),
                "tags": payload.get("tags", []),
                "source": payload.get("source", ""),
                "score": round(float(getattr(hit, "score", 0.0)), 6),
                "ranker": "qdrant-vector",
            }
        )
    return results


def _require_semantic_embedding(adapter: EmbeddingAdapter) -> None:
    health = adapter.health_check()
    if not health.get("semantic_model"):
        raise RuntimeError("Qdrant indexing/search requires a semantic embedding provider, not hash embeddings")
    if not health.get("ok"):
        missing = ", ".join(str(item) for item in health.get("missing_env_vars", []))
        suffix = f": missing {missing}" if missing else ""
        raise RuntimeError(f"Qdrant embedding provider is not configured{suffix}")


def _qdrant_client(settings: IndustrialSettings):
    try:
        from qdrant_client import QdrantClient, models
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("Qdrant support requires the optional dependency: qdrant-client") from exc
    kwargs: dict[str, Any] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs), models


def _ensure_collection(client: Any, models: Any, collection: str, dimensions: int) -> None:
    if hasattr(client, "collection_exists") and client.collection_exists(collection):
        return
    try:
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
        )
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise


def _search(client: Any, collection: str, query_vector: list[float], query_filter: Any, limit: int) -> list[Any]:
    if hasattr(client, "search"):
        return client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
        )
    response = client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=query_filter,
        limit=limit,
    )
    return list(getattr(response, "points", []))


def _build_filter(models: Any, category: str | None, asset_type: str | None, tags: list[str]) -> Any:
    conditions = []
    if category:
        conditions.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    if asset_type:
        conditions.append(models.FieldCondition(key="type", match=models.MatchValue(value=asset_type)))
    for tag in tags:
        conditions.append(models.FieldCondition(key="tags", match=models.MatchValue(value=tag)))
    if not conditions:
        return None
    return models.Filter(must=conditions)


def _payload(
    storage: LocalStorage,
    category: str,
    path: Path,
    data: dict[str, Any],
    search_text: str,
) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(storage.root)),
        "category": category,
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "tags": [str(tag) for tag in data.get("tags", [])],
        "source": data.get("source", ""),
        "version": data.get("version", ""),
        "text_preview": search_text[:500],
    }


def _search_text(data: dict[str, Any]) -> str:
    payload = {
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title", ""),
        "name": data.get("name", ""),
        "source": data.get("source", ""),
        "tags": data.get("tags", []),
        "content": data.get("content", {}),
        "metadata": data.get("metadata", {}),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()


def _point_id(path: Path) -> int:
    digest = hashlib.sha256(str(path).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)
