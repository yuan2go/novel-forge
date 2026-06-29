from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from novel_forge.core.ids import make_id, utc_now
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.common import resolve_path
from novel_forge.modules.long_memory import retrieve_memory
from novel_forge.modules.production_context import filter_project_safe_references, project_scope_from_asset
from novel_forge.schemas import (
    ArtifactEmbedding,
    EmbeddingJob,
    EntityMemoryChunk,
    HybridRetrievalReport,
    KnowledgeChunk,
    MemoryChunk,
    PgVectorSchemaPlan,
    ReviewMemoryChunk,
    validate_common_fields,
)
from novel_forge.storage.local import LocalStorage

VECTOR_DIMENSION = 64
CHUNK_TYPES = {
    "memory_record": MemoryChunk,
    "knowledge_card": KnowledgeChunk,
    "review_report": ReviewMemoryChunk,
    "character_card": EntityMemoryChunk,
    "world_bible": EntityMemoryChunk,
    "novel_kg_snapshot": EntityMemoryChunk,
}


def create_pgvector_schema_plan(storage: LocalStorage, *, status: str = "planned", project_id: str = "", workspace_path: str = "") -> dict[str, Any]:
    tables = {
        "memory_chunks": "L0-L5 memory chunks with vector embeddings",
        "knowledge_chunks": "knowledge card chunks and reusable craft abstractions",
        "artifact_embeddings": "generic artifact-level embedding rows",
        "review_memory_chunks": "review issues, quality rubrics, and rework learnings",
        "entity_memory_chunks": "entity, faction, location, prop, timeline, and KG chunks",
    }
    ddl = [
        "create extension if not exists vector;",
        "create table if not exists memory_chunks (id text primary key, project_id text, level text, source_path text, content text, embedding vector(64), metadata jsonb);",
        "create table if not exists knowledge_chunks (id text primary key, project_id text, source_path text, content text, embedding vector(64), metadata jsonb);",
        "create table if not exists artifact_embeddings (id text primary key, project_id text, asset_type text, source_path text, embedding vector(64), metadata jsonb);",
        "create table if not exists review_memory_chunks (id text primary key, project_id text, source_path text, content text, embedding vector(64), metadata jsonb);",
        "create table if not exists entity_memory_chunks (id text primary key, project_id text, entity_id text, source_path text, content text, embedding vector(64), metadata jsonb);",
    ]
    content = {
        "plan_id": make_id("pgvector_schema_plan", f"{project_id or 'global'}-{utc_now()}"),
        "tables": tables,
        "ddl": ddl,
        "status": status,
        "created_at": utc_now(),
    }
    asset = PgVectorSchemaPlan(
        title="PostgreSQL pgvector schema plan",
        tags=["pgvector", "schema-plan", status],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "status": status},
    )
    return _write(storage, asset)


def build_embedding_job(
    storage: LocalStorage,
    *,
    source_paths: list[str],
    backend: str = "local_hash_embedding",
    project_id: str = "",
    workspace_path: str = "",
    chunk_size: int = 900,
) -> dict[str, Any]:
    chunks = []
    errors = []
    for source_path in source_paths:
        try:
            chunks.extend(_chunk_asset(storage, source_path, backend=backend, chunk_size=chunk_size, project_id=project_id, workspace_path=workspace_path))
        except Exception as exc:
            errors.append({"source_path": source_path, "error": f"{type(exc).__name__}: {exc}"})
    online_sync = _sync_pgvector_online(storage, chunks, project_id=project_id, backend=backend) if _pgvector_online_enabled(backend) else {"status": "disabled"}
    content = {
        "job_id": make_id("embedding_job", f"{backend}-{utc_now()}"),
        "source_paths": source_paths,
        "backend": backend,
        "status": "completed_with_errors" if errors or online_sync.get("status") == "failed" else "completed",
        "chunk_count": len(chunks),
        "chunks": chunks,
        "errors": errors,
        "online_pgvector": online_sync,
        "created_at": utc_now(),
    }
    asset = EmbeddingJob(
        title=f"Embedding job {len(chunks)} chunks",
        tags=["embedding-job", backend, content["status"]],
        content=content,
        metadata={"project_id": project_id, "workspace_path": workspace_path, "backend": backend},
        references=filter_project_safe_references(storage, project_id, source_paths),
    )
    written = _write(storage, asset)
    return {**written, "chunks": chunks, "errors": errors}


def hybrid_retrieve(
    storage: LocalStorage,
    *,
    query: str,
    project_id: str = "",
    retrieval_backend: str = "hybrid",
    limit: int = 12,
    levels: list[str] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    query_vector = _embed(query)
    online = _pgvector_online_rows(storage, query_vector=query_vector, project_id=project_id, limit=limit) if _pgvector_online_enabled(retrieval_backend) else {"status": "disabled", "rows": []}
    vector_rows = online.get("rows", []) if online.get("status") == "succeeded" else _vector_rows(storage, project_id=project_id)
    if retrieval_backend == "pgvector" and online.get("status") == "failed" and _pgvector_strict():
        raise RuntimeError(str(online.get("error", "pgvector online query failed")))
    scored = []
    for row in vector_rows:
        score = float(row["vector_score"]) if "vector_score" in row else _cosine(query_vector, row["embedding"])
        lexical = _lexical_score(query, row.get("text", ""))
        scored.append({**row, "vector_score": round(score, 4), "lexical_score": round(lexical, 4), "score": round((score * 0.65) + (lexical * 0.35), 4)})
    memory = retrieve_memory(storage, query=query, project_id=project_id, levels=levels or [], limit=limit, persist_report=False)
    for item in memory.get("results", []):
        scored.append({**item, "backend": "memory_record", "score": max(float(item.get("score", 0) or 0), 0.01)})
    results = sorted(scored, key=lambda row: (-float(row.get("score", 0) or 0), str(row.get("path", ""))))[: int(limit or 12)]
    report = {
        "report_id": make_id("hybrid_retrieval", f"{project_id}-{query}-{utc_now()}"),
        "query": query,
        "retrieval_backend": retrieval_backend,
        "vector_backend": "pgvector_online" if online.get("status") == "succeeded" else "local_hash_embedding",
        "online_pgvector": {key: value for key, value in online.items() if key != "rows"},
        "results": results,
        "created_at": utc_now(),
    }
    if not persist:
        return report
    asset = HybridRetrievalReport(
        title=f"Hybrid retrieval {query[:48]}",
        tags=["hybrid-retrieval", retrieval_backend],
        content=report,
        metadata={"project_id": project_id, "retrieval_backend": retrieval_backend},
        references=filter_project_safe_references(storage, project_id, [str(item.get("path", "")) for item in results]),
    )
    written = _write(storage, asset)
    return {**report, "path": written["path"], "asset": written["asset"], "validation": written["validation"]}


def _chunk_asset(storage: LocalStorage, source_path: str, *, backend: str, chunk_size: int, project_id: str, workspace_path: str) -> list[dict[str, Any]]:
    source_file = resolve_path(storage.root, source_path)
    asset = storage.read_asset(source_file)
    data = asset.to_dict()
    project = project_scope_from_asset(storage, asset, input_path=source_file, workspace_path=workspace_path or None)
    resolved_project_id = project_id or str(project.get("project_id", ""))
    resolved_workspace = workspace_path or str(project.get("workspace_path", ""))
    text = _asset_text(data)
    chunks = [_clip(text[index : index + chunk_size]) for index in range(0, len(text), chunk_size)] or [_clip(text)]
    written_chunks = []
    for index, chunk_text in enumerate(chunks):
        chunk_id = make_id("chunk", f"{asset.id}-{index}-{backend}")
        embedding = _embed(chunk_text)
        cls = CHUNK_TYPES.get(asset.type)
        if cls is None:
            chunk_asset = ArtifactEmbedding(
                title=f"Embedding {asset.title or asset.id} #{index + 1}",
                tags=["artifact-embedding", asset.type, backend],
                content={
                    "embedding_id": chunk_id,
                    "source_asset_id": asset.id,
                    "source_path": _display_path(storage.root, source_file),
                    "backend": backend,
                    "embedding": embedding,
                    "text": chunk_text,
                    "metadata": {"asset_type": asset.type, "chunk_index": index, "project_id": resolved_project_id},
                },
                metadata={"project_id": resolved_project_id, "workspace_path": resolved_workspace, "asset_type": asset.type},
                references=filter_project_safe_references(storage, resolved_project_id, [asset.id, _display_path(storage.root, source_file)]),
            )
        else:
            content_key = "memory_id" if asset.type == "memory_record" else ("entity_id" if cls is EntityMemoryChunk else "source_asset_id")
            chunk_asset = cls(
                title=f"Chunk {asset.title or asset.id} #{index + 1}",
                tags=["vector-chunk", asset.type, backend],
                content={
                    "chunk_id": chunk_id,
                    content_key: asset.id,
                    "source_asset_id": asset.id,
                    "source_path": _display_path(storage.root, source_file),
                    "text": chunk_text,
                    "embedding": embedding,
                    "metadata": {"asset_type": asset.type, "chunk_index": index, "project_id": resolved_project_id},
                },
                metadata={"project_id": resolved_project_id, "workspace_path": resolved_workspace, "asset_type": asset.type},
                references=filter_project_safe_references(storage, resolved_project_id, [asset.id, _display_path(storage.root, source_file)]),
            )
        written = _write(storage, chunk_asset)
        written_chunks.append({"path": written["path"], "chunk_id": chunk_id, "asset_type": asset.type, "embedding_dim": len(embedding)})
    return written_chunks


def _vector_rows(storage: LocalStorage, *, project_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in ["contexts", "knowledge", "reviews", "continuity"]:
        for path in storage.list_json(category):
            try:
                data = storage.read_json(path)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") not in {"memory_chunk", "knowledge_chunk", "artifact_embedding", "review_memory_chunk", "entity_memory_chunk"}:
                continue
            metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
            if project_id and str(metadata.get("project_id", "")) != project_id:
                continue
            content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
            embedding = content.get("embedding", [])
            if not isinstance(embedding, list):
                continue
            rows.append(
                {
                    "path": _display_path(storage.root, path),
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "backend": "pgvector_local_projection",
                    "text": str(content.get("text", "")),
                    "embedding": [float(value) for value in embedding],
                    "source_asset_id": content.get("source_asset_id", ""),
                }
            )
    return rows


def _sync_pgvector_online(storage: LocalStorage, chunks: list[dict[str, Any]], *, project_id: str, backend: str) -> dict[str, Any]:
    if not chunks:
        return {"status": "skipped", "reason": "no chunks"}
    try:
        with _pgvector_connect(storage) as conn:
            _ensure_pgvector_online_schema(conn)
            count = 0
            for chunk in chunks:
                row = _chunk_row_for_online(storage, chunk)
                if not row:
                    continue
                _execute(
                    conn,
                    """
                    insert into nf_pgvector_chunks
                    (id, project_id, chunk_type, source_path, source_asset_id, content, embedding, metadata, updated_at)
                    values (%s, %s, %s, %s, %s, %s, %s::vector, %s, now())
                    on conflict (id) do update set
                      project_id = excluded.project_id,
                      chunk_type = excluded.chunk_type,
                      source_path = excluded.source_path,
                      source_asset_id = excluded.source_asset_id,
                      content = excluded.content,
                      embedding = excluded.embedding,
                      metadata = excluded.metadata,
                      updated_at = now()
                    """,
                    (
                        row["id"],
                        row["project_id"] or project_id,
                        row["type"],
                        row["path"],
                        row["source_asset_id"],
                        row["text"],
                        _vector_literal(row["embedding"]),
                        json.dumps(row["metadata"], ensure_ascii=False),
                    ),
                )
                count += 1
            _commit(conn)
        return {"status": "succeeded", "backend": backend, "upserted": count, "table": "nf_pgvector_chunks"}
    except Exception as exc:
        if _pgvector_strict():
            raise
        return {"status": "failed", "backend": backend, "error": f"{type(exc).__name__}: {exc}", "table": "nf_pgvector_chunks"}


def _pgvector_online_rows(storage: LocalStorage, *, query_vector: list[float], project_id: str, limit: int) -> dict[str, Any]:
    try:
        with _pgvector_connect(storage) as conn:
            _ensure_pgvector_online_schema(conn)
            rows = _fetchall(
                conn,
                """
                select id, project_id, chunk_type, source_path, source_asset_id, content, metadata,
                       1 - (embedding <=> %s::vector) as vector_score
                from nf_pgvector_chunks
                where (%s = '' or project_id = %s)
                order by embedding <=> %s::vector
                limit %s
                """,
                (_vector_literal(query_vector), project_id, project_id, _vector_literal(query_vector), int(limit or 12)),
            )
        return {"status": "succeeded", "row_count": len(rows), "rows": [_online_row_payload(row) for row in rows]}
    except Exception as exc:
        if _pgvector_strict():
            raise
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "rows": []}


def _chunk_row_for_online(storage: LocalStorage, chunk: dict[str, Any]) -> dict[str, Any] | None:
    path_value = str(chunk.get("path", ""))
    if not path_value:
        return None
    try:
        data = storage.read_json(resolve_path(storage.root, path_value))
    except Exception:
        return None
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    embedding = content.get("embedding", [])
    if not isinstance(embedding, list):
        return None
    return {
        "id": str(content.get("chunk_id") or content.get("embedding_id") or data.get("id", "")),
        "path": path_value,
        "type": str(data.get("type", "")),
        "project_id": str(metadata.get("project_id", "")),
        "source_asset_id": str(content.get("source_asset_id") or content.get("memory_id") or content.get("entity_id") or ""),
        "text": str(content.get("text", "")),
        "embedding": [float(value) for value in embedding],
        "metadata": {**metadata, "asset_type": metadata.get("asset_type", ""), "local_chunk_path": path_value},
    }


def _online_row_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        values = row
    else:
        try:
            values = dict(row)
        except Exception:
            values = {
                "id": row[0],
                "project_id": row[1],
                "chunk_type": row[2],
                "source_path": row[3],
                "source_asset_id": row[4],
                "content": row[5],
                "metadata": row[6],
                "vector_score": row[7],
            }
    metadata = values.get("metadata", {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {"raw": metadata}
    return {
        "path": str(values.get("source_path", "")),
        "id": str(values.get("id", "")),
        "type": str(values.get("chunk_type", "")),
        "backend": "pgvector_online",
        "text": str(values.get("content", "")),
        "embedding": [],
        "source_asset_id": str(values.get("source_asset_id", "")),
        "project_id": str(values.get("project_id", "")),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "vector_score": float(values.get("vector_score", 0.0) or 0.0),
    }


def _ensure_pgvector_online_schema(conn: Any) -> None:
    for statement in [
        "create extension if not exists vector",
        """
        create table if not exists nf_pgvector_chunks (
          id text primary key,
          project_id text not null default '',
          chunk_type text not null,
          source_path text not null,
          source_asset_id text not null default '',
          content text not null,
          embedding vector(64) not null,
          metadata jsonb not null default '{}'::jsonb,
          updated_at timestamptz not null default now()
        )
        """,
        "create index if not exists nf_pgvector_chunks_project_idx on nf_pgvector_chunks(project_id)",
        "create index if not exists nf_pgvector_chunks_embedding_idx on nf_pgvector_chunks using ivfflat (embedding vector_cosine_ops)",
    ]:
        _execute(conn, statement, ())


def _pgvector_connect(storage: LocalStorage) -> Any:
    settings = IndustrialSettings.from_env(root=storage.root)
    if not settings.database_url:
        raise RuntimeError("NOVEL_FORGE_DATABASE_URL is required for pgvector online backend")
    try:
        import psycopg
    except Exception as exc:
        raise RuntimeError("pgvector online backend requires optional dependency: psycopg[binary]") from exc
    return psycopg.connect(settings.database_url, connect_timeout=2)


def _execute(conn: Any, sql: str, params: tuple[Any, ...]) -> Any:
    cursor = conn.cursor()
    try:
        return cursor.execute(sql, params)
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()


def _fetchall(conn: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        return list(cursor.fetchall())
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            close()


def _commit(conn: Any) -> None:
    commit = getattr(conn, "commit", None)
    if callable(commit):
        commit()


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _pgvector_online_enabled(backend: str) -> bool:
    value = os.environ.get("NOVEL_FORGE_PGVECTOR_ONLINE", "")
    if value == "":
        return str(backend).lower() in {"pgvector_online", "postgres_pgvector"}
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _pgvector_strict() -> bool:
    return os.environ.get("NOVEL_FORGE_PGVECTOR_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}


def _asset_text(data: dict[str, Any]) -> str:
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    parts = [str(data.get("title") or data.get("name") or ""), str(data.get("type", ""))]
    for key in ["summary", "text", "actual_context", "template", "objective", "hook"]:
        value = content.get(key)
        if isinstance(value, str):
            parts.append(value)
    parts.append(json.dumps(content, ensure_ascii=False, sort_keys=True))
    return _clip("\n".join(part for part in parts if part.strip()), 8000)


def _embed(text: str) -> list[float]:
    buckets = [0.0] * VECTOR_DIMENSION
    tokens = [token.lower() for token in "".join(ch if ch.isalnum() else " " for ch in str(text)).split() if token]
    if not tokens:
        return buckets
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % VECTOR_DIMENSION
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        buckets[index] += sign
    norm = math.sqrt(sum(value * value for value in buckets)) or 1.0
    return [round(value / norm, 6) for value in buckets]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _lexical_score(query: str, text: str) -> float:
    left = {token.lower() for token in "".join(ch if ch.isalnum() else " " for ch in str(query)).split() if token}
    right = {token.lower() for token in "".join(ch if ch.isalnum() else " " for ch in str(text)).split() if token}
    if not left:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _clip(text: str, limit: int = 4000) -> str:
    return " ".join(str(text).split())[:limit]


def _write(
    storage: LocalStorage,
    asset: PgVectorSchemaPlan | EmbeddingJob | HybridRetrievalReport | MemoryChunk | KnowledgeChunk | ArtifactEmbedding | ReviewMemoryChunk | EntityMemoryChunk,
) -> dict[str, Any]:
    errors = validate_common_fields(asset.to_dict())
    if errors:
        raise ValueError("; ".join(errors))
    path = storage.write_asset_auto(asset)
    return {"path": _display_path(storage.root, path), "id": asset.id, "asset": asset.to_dict(), "validation": {"ok": True, "errors": []}}


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
