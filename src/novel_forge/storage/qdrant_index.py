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
from novel_forge.modules.production_execution import (
    ExternalActionExecutionPort,
    ExternalActionKind,
    RetrievalExecutionPort,
    execute_external_action,
)
from novel_forge.modules.production_execution.security import (
    assert_legacy_execution_allowed,
    execution_environment,
)
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
    execution_port: RetrievalExecutionPort | None = None,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> dict[str, Any]:
    _require_controlled_retrieval_port(
        environment,
        execution_port,
        external_action_execution_port,
    )
    if execution_port is None:
        adapter = adapter or embedding_adapter_from_env(require_semantic=True)
        _require_semantic_embedding(adapter)
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero")
    if external_action_execution_port is not None:
        return _build_qdrant_index_via_execution(
            storage,
            settings,
            adapter=adapter,
            batch_size=batch_size,
            resume=resume,
            force_reembed=force_reembed,
            max_retries=max_retries,
            execution_port=execution_port,
            external_action_execution_port=external_action_execution_port,
        )
    client, models = _qdrant_client(settings)
    embedding = (
        _retrieval_execution_metadata(execution_port)
        if execution_port is not None
        else _embedding_metadata(adapter)
    )
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
                execution_port=execution_port,
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
            execution_port=execution_port,
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
    project_id: str | None = None,
    workspace_path: str | None = None,
    limit: int = 50,
    adapter: EmbeddingAdapter | None = None,
    execution_port: RetrievalExecutionPort | None = None,
    external_action_execution_port: ExternalActionExecutionPort | None = None,
    environment: str = "",
) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    _require_controlled_retrieval_port(
        environment,
        execution_port,
        external_action_execution_port,
    )
    if execution_port is None:
        adapter = adapter or embedding_adapter_from_env(require_semantic=True)
        _require_semantic_embedding(adapter)
    query_vector = (
        list(
            execution_port.embed_batch(
                [query],
                evidence_context={
                    "capability": "retrieval.embed",
                    "index_version": QDRANT_INDEX_VERSION,
                    "source_eligibility": "NOT_SOURCE_DERIVED",
                    "query": True,
                },
            ).vectors[0]
        )
        if execution_port is not None
        else adapter.embed_text(query)  # type: ignore[union-attr]
    )
    if external_action_execution_port is not None:
        return _query_qdrant_via_execution(
            settings,
            query_vector=query_vector,
            category=category,
            asset_type=asset_type,
            tags=tags or [],
            project_id=project_id,
            workspace_path=workspace_path,
            limit=limit,
            external_action_execution_port=external_action_execution_port,
        )
    client, models = _qdrant_client(settings)
    query_filter = _build_filter(models, category, asset_type, tags or [], project_id=project_id, workspace_path=workspace_path)
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
                "project_id": payload.get("project_id", ""),
                "workspace_path": payload.get("workspace_path", ""),
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
    adapter: EmbeddingAdapter | None,
    records: list[dict[str, Any]],
    embedding: dict[str, Any],
    cache: dict[str, Any],
    max_retries: int,
    execution_port: RetrievalExecutionPort | None,
) -> tuple[int, int]:
    missing = [record for record in records if "vector" not in record]
    embedded = 0
    if missing:
        vectors = _embed_batch_with_retries(
            adapter,
            [record["search_text"] for record in missing],
            max_retries=max_retries,
            execution_port=execution_port,
            evidence_context={
                "capability": "retrieval.embed",
                "index_version": QDRANT_INDEX_VERSION,
                "source_eligibility": "PRODUCTION_ELIGIBLE",
                "source_chunk_hashes": [
                    record["fingerprint"]["sha256"] for record in missing
                ],
            },
        )
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


def _embed_batch_with_retries(
    adapter: EmbeddingAdapter | None,
    texts: list[str],
    max_retries: int,
    *,
    execution_port: RetrievalExecutionPort | None = None,
    evidence_context: dict[str, Any] | None = None,
) -> list[list[float]]:
    if execution_port is not None:
        candidate = execution_port.embed_batch(
            texts,
            evidence_context=evidence_context or {},
        )
        if candidate.evidence.partial_failure or candidate.evidence.dirty_index:
            raise RuntimeError(
                "embedding execution returned partial or dirty-index evidence"
            )
        return [list(vector) for vector in candidate.vectors]
    if adapter is None:
        raise RuntimeError("embedding adapter is required for legacy development execution")
    assert_legacy_execution_allowed(
        component="Qdrant embedding adapter",
        gateway_backed=False,
    )
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


def _require_controlled_retrieval_port(
    environment: str,
    execution_port: RetrievalExecutionPort | None,
    external_action_execution_port: ExternalActionExecutionPort | None,
) -> None:
    if execution_environment(environment) in {
        "production",
        "validation",
        "provider-validation",
    } and (
        execution_port is None or external_action_execution_port is None
    ):
        raise RuntimeError(
            "controlled Qdrant retrieval requires RetrievalExecutionPort and "
            "Authority-bound ExternalActionExecutionPort"
        )


def _build_qdrant_index_via_execution(
    storage: LocalStorage,
    settings: IndustrialSettings,
    *,
    adapter: EmbeddingAdapter | None,
    batch_size: int,
    resume: bool,
    force_reembed: bool,
    max_retries: int,
    execution_port: RetrievalExecutionPort | None,
    external_action_execution_port: ExternalActionExecutionPort,
) -> dict[str, Any]:
    embedding = (
        _retrieval_execution_metadata(execution_port)
        if execution_port is not None
        else _embedding_metadata(adapter)  # type: ignore[arg-type]
    )
    cache = (
        _load_vector_cache(storage)
        if resume and not force_reembed
        else _empty_vector_cache(embedding)
    )
    records = _asset_records(storage)
    cache_records = cache.setdefault("vectors", {})
    embedded = 0
    for offset in range(0, len(records), batch_size):
        batch = records[offset : offset + batch_size]
        missing = []
        for record in batch:
            cache_row = (
                cache_records.get(record["path"], {})
                if isinstance(cache_records, dict)
                else {}
            )
            if _cache_row_valid(cache_row, record, embedding):
                record["vector"] = [
                    float(value) for value in cache_row.get("vector", [])
                ]
            else:
                missing.append(record)
        if missing:
            vectors = _embed_batch_with_retries(
                adapter,
                [record["search_text"] for record in missing],
                max_retries=max_retries,
                execution_port=execution_port,
                evidence_context={
                    "capability": "retrieval.embed",
                    "index_version": QDRANT_INDEX_VERSION,
                    "source_eligibility": "PRODUCTION_ELIGIBLE",
                    "source_chunk_hashes": [
                        record["fingerprint"]["sha256"]
                        for record in missing
                    ],
                },
            )
            embedded += len(vectors)
            for record, vector in zip(missing, vectors):
                record["vector"] = vector
                cache.setdefault("vectors", {})[record["path"]] = {
                    "fingerprint": record["fingerprint"],
                    "embedding": embedding,
                    "vector": vector,
                    "updated_at": utc_now(),
                }
    points = [
        {
            "id": _point_id(Path(record["path"])),
            "vector": record["vector"],
            "payload": _payload(
                storage,
                record["category"],
                record["absolute_path"],
                record["data"],
                record["search_text"],
                embedding,
            ),
        }
        for record in records
    ]
    identity = hashlib.sha256(
        json.dumps(
            [
                {
                    "id": point["id"],
                    "source_hash": record["fingerprint"]["sha256"],
                }
                for point, record in zip(points, records)
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    candidate = execute_external_action(
        capability=ExternalActionKind.RETRIEVAL_INDEX_UPSERT,
        request_payload={
            "collection": settings.qdrant_collection,
            "index_version": QDRANT_INDEX_VERSION,
            "embedding": embedding,
            "points": points,
            "batch_identity": "sha256:" + identity,
        },
        stable_idempotency_key=f"retrieval.index.upsert:{identity}",
        data_classification="INTERNAL_CONTENT_INDEX",
        privacy_policy_ref="privacy-policy:retrieval-index:v1",
        rate_limit_policy_ref="rate-limit-policy:qdrant:v1",
        quota_policy_ref="quota-policy:qdrant:v1",
        execution_port=external_action_execution_port,
    )
    _write_vector_cache(storage, cache)
    manifest = {
        "version": QDRANT_INDEX_VERSION,
        "collection": settings.qdrant_collection,
        "built_at": utc_now(),
        "indexed": len(points),
        "embedded": embedded,
        "cache_hits": len(points) - embedded,
        "asset_count": len(records),
        "embedding": embedding,
        "collection_status": dict(candidate.raw_output),
        "backend": "production-execution",
        "execution_evidence": candidate.evidence.to_dict(),
    }
    storage.write_json(QDRANT_MANIFEST_RELATIVE_PATH, manifest)
    return manifest


def _query_qdrant_via_execution(
    settings: IndustrialSettings,
    *,
    query_vector: list[float],
    category: str | None,
    asset_type: str | None,
    tags: list[str],
    project_id: str | None,
    workspace_path: str | None,
    limit: int,
    external_action_execution_port: ExternalActionExecutionPort,
) -> list[dict[str, Any]]:
    request_payload = {
        "collection": settings.qdrant_collection,
        "query_vector": query_vector,
        "filter": {
            "category": category or "",
            "asset_type": asset_type or "",
            "tags": tags,
            "project_id": project_id or "",
            "workspace_path": workspace_path or "",
        },
        "limit": limit,
        "index_version": QDRANT_INDEX_VERSION,
    }
    identity = hashlib.sha256(
        json.dumps(
            request_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    candidate = execute_external_action(
        capability=ExternalActionKind.RETRIEVAL_INDEX_QUERY,
        request_payload=request_payload,
        stable_idempotency_key=f"retrieval.index.query:{identity}",
        data_classification="INTERNAL_CONTENT_INDEX",
        privacy_policy_ref="privacy-policy:retrieval-index:v1",
        rate_limit_policy_ref="rate-limit-policy:qdrant:v1",
        quota_policy_ref="quota-policy:qdrant:v1",
        execution_port=external_action_execution_port,
    )
    raw = candidate.raw_output
    result = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    hits = result.get("hits", []) if isinstance(result, dict) else []
    if not isinstance(hits, list):
        raise RuntimeError("Qdrant execution result hits must be a list")
    evidence = candidate.evidence.to_dict()
    return [
        {
            **dict(hit),
            "execution_evidence": evidence,
        }
        for hit in hits
        if isinstance(hit, dict)
    ]


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


def _build_filter(
    models: Any,
    category: str | None,
    asset_type: str | None,
    tags: list[str],
    project_id: str | None = None,
    workspace_path: str | None = None,
) -> Any:
    conditions = []
    if category:
        conditions.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    if asset_type:
        conditions.append(models.FieldCondition(key="type", match=models.MatchValue(value=asset_type)))
    if project_id:
        conditions.append(models.FieldCondition(key="project_id", match=models.MatchValue(value=project_id)))
    if workspace_path:
        conditions.append(models.FieldCondition(key="workspace_path", match=models.MatchValue(value=workspace_path)))
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
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    return {
        "path": str(path.relative_to(storage.root)),
        "category": category,
        "id": data.get("id", ""),
        "type": data.get("type", ""),
        "title": data.get("title") or data.get("name", ""),
        "tags": [str(tag) for tag in data.get("tags", [])],
        "source": data.get("source", ""),
        "version": data.get("version", ""),
        "project_id": str(metadata.get("project_id") or content.get("project_id") or ""),
        "workspace_path": str(metadata.get("workspace_path") or ""),
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


def _retrieval_execution_metadata(
    execution_port: RetrievalExecutionPort,
) -> dict[str, Any]:
    return {
        "model": execution_port.embedding_model,
        "provider": "production-execution",
        "dimensions": execution_port.embedding_dimension,
        "semantic_model": True,
        "external_api": True,
        "authority_bound": True,
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
