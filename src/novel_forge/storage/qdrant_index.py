from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from novel_forge.core.constants import DATA_DIRS
from novel_forge.core.ids import utc_now
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.model_adapters.embeddings import EmbeddingAdapter, embedding_adapter_from_env
from novel_forge.storage.local import LocalStorage

QDRANT_INDEX_VERSION = "0.2.0"
QDRANT_MANIFEST_RELATIVE_PATH = Path("data/indexes/qdrant-index-manifest.json")
QDRANT_VECTOR_CACHE_RELATIVE_PATH = Path("data/indexes/qdrant-vector-cache.json")


def build_qdrant_index(
    storage: LocalStorage,
    settings: IndustrialSettings,
    adapter: EmbeddingAdapter | None = None,
    recreate_collection: bool = False,
    batch_size: int = 32,
    resume: bool = True,
    force_reembed: bool = False,
    max_retries: int = 3,
) -> dict[str, Any]:
    adapter = adapter or embedding_adapter_from_env(require_semantic=True)
    _require_semantic_embedding(adapter)
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")
    client, models = _qdrant_client(settings)
    embedding = _embedding_metadata(adapter)
    collection = _ensure_collection(
        client,
        models,
        settings.qdrant_collection,
        embedding,
        storage,
        recreate_collection=recreate_collection,
    )
    cache = _load_vector_cache(storage) if resume and not force_reembed else _empty_vector_cache(embedding)
    records = _asset_records(storage)
    indexed = 0
    embedded = 0
    cache_hits = 0
    pending: list[dict[str, Any]] = []
    cache_records = cache.setdefault("vectors", {})
    for record in records:
        cache_row = cache_records.get(record["path"], {}) if isinstance(cache_records, dict) else {}
        if _cache_row_valid(cache_row, record, embedding):
            record["vector"] = [float(value) for value in cache_row.get("vector", [])]
            cache_hits += 1
            pending.append(record)
        else:
            pending.append(record)
        if len(pending) >= batch_size:
            batch_indexed, batch_embedded = _index_qdrant_batch(
                storage,
                client,
                models,
                settings.qdrant_collection,
                adapter,
                pending,
                embedding,
                cache,
                max_retries=max_retries,
            )
            indexed += batch_indexed
            embedded += batch_embedded
            pending = []
    if pending:
        batch_indexed, batch_embedded = _index_qdrant_batch(
            storage,
            client,
            models,
            settings.qdrant_collection,
            adapter,
            pending,
            embedding,
            cache,
            max_retries=max_retries,
        )
        indexed += batch_indexed
        embedded += batch_embedded
    _write_vector_cache(storage, cache)
    manifest = {
        "version": QDRANT_INDEX_VERSION,
        "collection": settings.qdrant_collection,
        "built_at": utc_now(),
        "indexed": indexed,
        "embedded": embedded,
        "cache_hits": cache_hits,
        "asset_count": len(records),
        "embedding": embedding,
        "collection_status": collection,
        "backend": "qdrant",
    }
    storage.write_json(QDRANT_MANIFEST_RELATIVE_PATH, manifest)
    return manifest


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
                "id": payload.get("id", ""),
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


def _ensure_collection(
    client: Any,
    models: Any,
    collection: str,
    embedding: dict[str, Any],
    storage: LocalStorage,
    recreate_collection: bool = False,
) -> dict[str, Any]:
    dimensions = int(embedding["dimensions"])
    manifest = _load_manifest(storage)
    exists = bool(hasattr(client, "collection_exists") and client.collection_exists(collection))
    original_exists = exists
    if exists:
        actual_dimensions = _collection_vector_size(client, collection)
        manifest_embedding = manifest.get("embedding", {}) if isinstance(manifest.get("embedding", {}), dict) else {}
        mismatches = []
        if actual_dimensions and actual_dimensions != dimensions:
            mismatches.append(f"dimension mismatch: collection={actual_dimensions}, embedding={dimensions}")
        for key in ["model", "provider"]:
            if manifest_embedding.get(key) and manifest_embedding.get(key) != embedding.get(key):
                mismatches.append(f"{key} mismatch: collection manifest={manifest_embedding.get(key)}, embedding={embedding.get(key)}")
        if mismatches:
            if not recreate_collection:
                raise RuntimeError(
                    f"Qdrant collection {collection!r} is incompatible; "
                    f"{'; '.join(mismatches)}. Re-run qdrant-index with --recreate to migrate."
                )
            if hasattr(client, "delete_collection"):
                client.delete_collection(collection_name=collection)
            exists = False
        else:
            return {"exists": True, "created": False, "recreated": False, "dimensions": actual_dimensions or dimensions}
    try:
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
        )
    except Exception as exc:
        if "already exists" not in str(exc).lower():
            raise
    return {"exists": original_exists, "created": True, "recreated": recreate_collection and original_exists, "dimensions": dimensions}


def _collection_vector_size(client: Any, collection: str) -> int:
    if not hasattr(client, "get_collection"):
        return 0
    try:
        info = client.get_collection(collection_name=collection)
    except TypeError:
        info = client.get_collection(collection)
    except Exception:
        return 0
    config = getattr(info, "config", None)
    params = getattr(getattr(config, "params", None), "vectors", None)
    if params is None:
        params = getattr(info, "vectors_config", None)
    if isinstance(params, dict):
        first = next(iter(params.values()), {})
        return int(getattr(first, "size", 0) or first.get("size", 0))
    return int(getattr(params, "size", 0) or 0)


def _asset_records(storage: LocalStorage) -> list[dict[str, Any]]:
    records = []
    for category in DATA_DIRS:
        for path in storage.list_json(category):
            data = storage.read_json(path)
            if not isinstance(data, dict):
                continue
            search_text = _search_text(data)
            relative = str(path.relative_to(storage.root))
            stat = path.stat()
            records.append(
                {
                    "path": relative,
                    "category": category,
                    "absolute_path": path,
                    "data": data,
                    "search_text": search_text,
                    "fingerprint": {
                        "mtime_ns": stat.st_mtime_ns,
                        "size": stat.st_size,
                        "sha256": hashlib.sha256(search_text.encode("utf-8")).hexdigest(),
                    },
                }
            )
    return records


def _index_qdrant_batch(
    storage: LocalStorage,
    client: Any,
    models: Any,
    collection: str,
    adapter: EmbeddingAdapter,
    records: list[dict[str, Any]],
    embedding: dict[str, Any],
    cache: dict[str, Any],
    max_retries: int,
) -> tuple[int, int]:
    missing = [record for record in records if "vector" not in record]
    embedded = 0
    if missing:
        vectors = _embed_batch_with_retries(adapter, [record["search_text"] for record in missing], max_retries=max_retries)
        embedded = len(vectors)
        for record, vector in zip(missing, vectors):
            record["vector"] = vector
            cache.setdefault("vectors", {})[record["path"]] = {
                "fingerprint": record["fingerprint"],
                "embedding": embedding,
                "vector": vector,
                "updated_at": utc_now(),
            }
    points = [
        models.PointStruct(
            id=_point_id(Path(record["path"])),
            vector=record["vector"],
            payload=_payload(storage, record["category"], record["absolute_path"], record["data"], record["search_text"], embedding),
        )
        for record in records
    ]
    _upsert_with_retries(client, collection, points, max_retries=max_retries)
    _write_vector_cache(storage, cache)
    return len(points), embedded


def _embed_batch_with_retries(adapter: EmbeddingAdapter, texts: list[str], max_retries: int) -> list[list[float]]:
    sleep_seconds = float(os.environ.get("NOVEL_FORGE_EMBEDDING_BATCH_SLEEP_SECONDS", "0"))
    last_error: Exception | None = None
    for attempt in range(max(1, max_retries)):
        try:
            vectors = adapter.embed_batch(texts)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            return vectors
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= max(1, max_retries):
                break
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"embedding batch failed after {max_retries} attempts: {last_error}") from last_error


def _upsert_with_retries(client: Any, collection: str, points: list[Any], max_retries: int) -> None:
    last_error: Exception | None = None
    for attempt in range(max(1, max_retries)):
        try:
            client.upsert(collection_name=collection, points=points)
            return
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= max(1, max_retries):
                break
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Qdrant upsert failed after {max_retries} attempts: {last_error}") from last_error


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
    embedding: dict[str, Any] | None = None,
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
        "embedding": embedding or {},
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


def _embedding_metadata(adapter: EmbeddingAdapter) -> dict[str, Any]:
    health = adapter.health_check()
    return {
        "model": str(health.get("model", getattr(adapter, "name", ""))),
        "provider": str(health.get("provider", health.get("model", getattr(adapter, "name", "")))),
        "dimensions": int(health.get("dimensions", adapter.dimensions)),
        "semantic_model": bool(health.get("semantic_model")),
        "external_api": bool(health.get("external_api")),
    }


def _load_manifest(storage: LocalStorage) -> dict[str, Any]:
    path = storage.root / QDRANT_MANIFEST_RELATIVE_PATH
    if not path.exists():
        return {}
    try:
        data = storage.read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _empty_vector_cache(embedding: dict[str, Any]) -> dict[str, Any]:
    return {"version": QDRANT_INDEX_VERSION, "embedding": embedding, "vectors": {}}


def _load_vector_cache(storage: LocalStorage) -> dict[str, Any]:
    path = storage.root / QDRANT_VECTOR_CACHE_RELATIVE_PATH
    if not path.exists():
        return {"version": QDRANT_INDEX_VERSION, "vectors": {}}
    try:
        data = storage.read_json(path)
    except Exception:
        return {"version": QDRANT_INDEX_VERSION, "vectors": {}}
    return data if isinstance(data, dict) else {"version": QDRANT_INDEX_VERSION, "vectors": {}}


def _write_vector_cache(storage: LocalStorage, cache: dict[str, Any]) -> None:
    cache["version"] = QDRANT_INDEX_VERSION
    cache["updated_at"] = utc_now()
    storage.write_json(QDRANT_VECTOR_CACHE_RELATIVE_PATH, cache)


def _cache_row_valid(row: dict[str, Any], record: dict[str, Any], embedding: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    vector = row.get("vector", [])
    if not isinstance(vector, list) or len(vector) != int(embedding["dimensions"]):
        return False
    return row.get("fingerprint") == record["fingerprint"] and row.get("embedding") == embedding
