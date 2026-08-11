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
    BaseAsset,
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
        "nf_pgvector_chunks": "Unified OS knowledge/memory chunk table for local PostgreSQL + pgvector retrieval",
        "memory_chunks": "Logical L0-L5 memory chunk projection",
        "knowledge_chunks": "Logical knowledge card and reusable craft abstraction projection",
        "artifact_embeddings": "Logical generic artifact-level embedding projection",
        "review_memory_chunks": "Logical review issue, quality rubric, and rework learning projection",
        "entity_memory_chunks": "Logical entity, faction, location, prop, timeline, and KG projection",
    }
    ddl = [
        "create extension if not exists vector;",
        "create table if not exists nf_pgvector_chunks (id text primary key, project_id text not null default '', chunk_type text not null, source_path text not null, source_asset_id text not null default '', source_type text not null default '', source_risk_level text not null default 'low', license_policy text not null default 'project_owned', permission_scope text not null default 'internal', flow_allowlist text[] not null default array[]::text[], raw_text_allowed boolean not null default false, evidence_span jsonb not null default '{}'::jsonb, content_hash text not null default '', embedding_model text not null default 'local_hash_embedding', embedding_version text not null default 'v1', dirty_index boolean not null default false, quality_score double precision not null default 0, content text not null, embedding vector(64) not null, metadata jsonb not null default '{}'::jsonb, updated_at timestamptz not null default now());",
        "create index if not exists nf_pgvector_chunks_project_idx on nf_pgvector_chunks(project_id);",
        "create index if not exists nf_pgvector_chunks_type_idx on nf_pgvector_chunks(chunk_type);",
        "create index if not exists nf_pgvector_chunks_risk_idx on nf_pgvector_chunks(source_risk_level);",
        "create index if not exists nf_pgvector_chunks_dirty_idx on nf_pgvector_chunks(dirty_index);",
        "create index if not exists nf_pgvector_chunks_embedding_idx on nf_pgvector_chunks using ivfflat (embedding vector_cosine_ops);",
    ]
    content = {
        "plan_id": make_id("pgvector_schema_plan", f"{project_id or 'global'}-{utc_now()}"),
        "architecture_role": "os_internal_knowledge_memory_base",
        "qdrant_role": "optional_high_performance_vector_service",
        "vector_dimension": VECTOR_DIMENSION,
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


def pgvector_capabilities(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    online_enabled = _pgvector_online_enabled("pgvector_online")
    local_rows = _vector_rows(storage, project_id=project_id)
    settings = IndustrialSettings.from_env(root=storage.root)
    return {
        "role": "os_internal_knowledge_memory_retrieval_base",
        "qdrant_role": "optional_high_performance_vector_service",
        "default_context_builder_order": ["pgvector", "qdrant", "local"],
        "vector_dimension": VECTOR_DIMENSION,
        "online_enabled": online_enabled,
        "strict": _pgvector_strict(),
        "database_configured": bool(settings.database_url),
        "online_table": "nf_pgvector_chunks",
        "local_projection_chunk_count": len(local_rows),
        "supported_asset_types": sorted(CHUNK_TYPES),
        "source_isolation": {
            "reject_high_risk_sources_by_default": True,
            "raw_source_text_for_generation": False,
            "raw_text_allowed_flows": ["research", "evaluation_method_extraction"],
        },
        "fallbacks": ["local_hash_embedding_projection", "local_json_memory"],
        "status": "online_ready" if online_enabled and settings.database_url else ("local_projection_ready" if local_rows else "configured_no_chunks"),
    }


def pgvector_operations_plan(
    storage: LocalStorage,
    *,
    project_id: str = "",
    target_chunk_count: int = 500_000,
    target_qps: int = 20,
    persist: bool = True,
) -> dict[str, Any]:
    capabilities = pgvector_capabilities(storage, project_id=project_id)
    migration_steps = [
        {"step": "ensure_extension", "command": "create extension if not exists vector", "blocking": True},
        {"step": "ensure_table", "command": "create table if not exists nf_pgvector_chunks (... embedding vector(64) ...)", "blocking": True},
        {"step": "ensure_project_index", "command": "create index if not exists nf_pgvector_chunks_project_idx on nf_pgvector_chunks(project_id)", "blocking": False},
        {"step": "ensure_type_index", "command": "create index if not exists nf_pgvector_chunks_type_idx on nf_pgvector_chunks(chunk_type)", "blocking": False},
        {"step": "ensure_vector_index", "command": "create index if not exists nf_pgvector_chunks_embedding_idx on nf_pgvector_chunks using ivfflat (embedding vector_cosine_ops)", "blocking": False},
        {"step": "backfill_chunks", "command": "run embedding_job for memory, knowledge, review, entity, and artifact assets", "blocking": False},
        {"step": "verify_context_builder", "command": "run Context Builder backend=auto and verify pgvector appears before qdrant in backend_attempts", "blocking": True},
    ]
    maintenance = {
        "analyze": "analyze nf_pgvector_chunks after large backfills",
        "vacuum": "vacuum analyze nf_pgvector_chunks after delete-heavy rollback batches",
        "reindex": "reindex index concurrently nf_pgvector_chunks_embedding_idx when vector recall degrades after major model changes",
        "connection_pool": "use API/worker process pooling or external pgbouncer for concurrent long-chain runs",
    }
    pressure_plan = {
        "target_chunk_count": int(target_chunk_count or 0),
        "target_qps": int(target_qps or 0),
        "scenarios": [
            {"name": "single_project_100_chapters", "chapters": 100, "expected_chunks": min(max(int(target_chunk_count or 0), 10_000), 500_000), "checks": ["p95_query_ms", "recall_top_k", "context_policy_rejections"]},
            {"name": "rollback_backfill_recovery", "checks": ["dirty_index_count", "rebuild_seconds", "context_builder_backend_attempts"]},
            {"name": "qdrant_optional_comparison", "checks": ["pgvector_recall", "qdrant_recall", "cost_per_context_bundle"]},
        ],
        "pass_thresholds": {"p95_query_ms": 800, "context_builder_pgvector_first": True, "fallback_without_data_loss": True},
    }
    report = {
        "type": "pgvector_operations_plan",
        "id": make_id("pgvector_ops", f"{project_id}-{target_chunk_count}-{utc_now()}"),
        "title": "Pgvector operations plan",
        "source": project_id,
        "tags": ["pgvector", "operations", "migration", "pressure"],
        "content": {
            "role": "os_internal_knowledge_memory_retrieval_base",
            "qdrant_role": "optional_high_performance_vector_service",
            "capabilities": capabilities,
            "migration_steps": migration_steps,
            "maintenance": maintenance,
            "pressure_plan": pressure_plan,
            "created_at": utc_now(),
        },
        "metadata": {"project_id": project_id},
        "references": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    if not persist:
        return {"path": "", "asset": report, "content": report["content"]}
    path = storage.root / "data" / "runs" / f"{report['id']}.json"
    storage.write_json(path, report)
    return {"path": _display_path(storage.root, path), "asset": report, "content": report["content"]}


def migrate_pgvector_online(storage: LocalStorage, *, dry_run: bool = True, project_id: str = "") -> dict[str, Any]:
    statements = _pgvector_schema_statements()
    if dry_run:
        return {
            "status": "planned",
            "dry_run": True,
            "statements": statements,
            "capabilities": pgvector_capabilities(storage, project_id=project_id),
        }
    with _pgvector_connect(storage) as conn:
        _ensure_pgvector_online_schema(conn)
        _commit(conn)
        counts = _pgvector_counts(conn)
    return {
        "status": "migrated",
        "dry_run": False,
        "statements": statements,
        "counts": counts,
        "capabilities": pgvector_capabilities(storage, project_id=project_id),
    }


def verify_pgvector_migration(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    """Verify pgvector readiness without requiring an online PostgreSQL server by default."""

    statements = _pgvector_schema_statements()
    local_rows = _vector_rows(storage, project_id=project_id)
    required_fields = {
        "source_type",
        "source_risk_level",
        "license_policy",
        "permission_scope",
        "flow_allowlist",
        "raw_text_allowed",
        "evidence_span",
        "content_hash",
        "embedding_model",
        "embedding_version",
        "dirty_index",
        "quality_score",
    }
    local_field_coverage = {
        field: sum(1 for row in local_rows if field in row and row.get(field) not in ("", None, []))
        for field in sorted(required_fields)
    }
    online = {"status": "disabled"}
    if _pgvector_online_enabled("pgvector_online"):
        try:
            with _pgvector_connect(storage) as conn:
                _ensure_pgvector_online_schema(conn)
                online = {"status": "verified", "counts": _pgvector_counts(conn)}
        except Exception as exc:
            if _pgvector_strict():
                raise
            online = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    high_risk_in_projection = sum(1 for row in local_rows if str(row.get("source_risk_level", "low")) == "high")
    return {
        "status": "verified" if online.get("status") in {"disabled", "verified"} and high_risk_in_projection == 0 else "attention_required",
        "project_id": project_id,
        "schema_field_count": len(required_fields),
        "schema_fields": sorted(required_fields),
        "statement_count": len(statements),
        "local_projection_chunk_count": len(local_rows),
        "local_field_coverage": local_field_coverage,
        "source_isolation": {
            "high_risk_in_generation_projection": high_risk_in_projection,
            "raw_source_text_allowed": False,
            "status": "passed" if high_risk_in_projection == 0 else "failed",
        },
        "online_pgvector": online,
        "capabilities": pgvector_capabilities(storage, project_id=project_id),
    }


def pgvector_online_e2e_smoke(storage: LocalStorage, *, project_id: str = "", require_online: bool = False) -> dict[str, Any]:
    capabilities = pgvector_capabilities(storage, project_id=project_id)
    explicit_online = os.environ.get("NOVEL_FORGE_PGVECTOR_ONLINE", "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
    scenarios = [
        {
            "name": "capabilities",
            "online_enabled": explicit_online,
            "capability_default_online_enabled": capabilities["online_enabled"],
            "explicit_online": explicit_online,
            "database_configured": capabilities["database_configured"],
        },
        {"name": "migration_verify"},
        {"name": "hybrid_retrieve", "source_isolation_required": True},
    ]
    results: list[dict[str, Any]] = []
    status = "passed"
    if require_online and not explicit_online:
        status = "failed"
        results.append({"scenario": "online_required", "status": "failed", "message": "NOVEL_FORGE_PGVECTOR_ONLINE is not enabled"})
    previous_online = os.environ.get("NOVEL_FORGE_PGVECTOR_ONLINE")
    if not explicit_online:
        os.environ["NOVEL_FORGE_PGVECTOR_ONLINE"] = "0"
    try:
        verification = verify_pgvector_migration(storage, project_id=project_id)
        results.append({"scenario": "migration_verify", "status": verification["status"], "online_pgvector": verification.get("online_pgvector", {})})
        retrieval = hybrid_retrieve(storage, query="pgvector online smoke", project_id=project_id, retrieval_backend="pgvector", limit=3, persist=True)
        results.append(
            {
                "scenario": "hybrid_retrieve",
                "status": "passed",
                "path": retrieval.get("path", ""),
                "vector_backend": retrieval.get("vector_backend", ""),
                "source_isolation": retrieval.get("source_isolation", {}),
            }
        )
    except Exception as exc:
        if require_online or _pgvector_strict():
            raise
        status = "warning"
        results.append({"scenario": "online_query", "status": "warning", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if not explicit_online:
            if previous_online is None:
                os.environ.pop("NOVEL_FORGE_PGVECTOR_ONLINE", None)
            else:
                os.environ["NOVEL_FORGE_PGVECTOR_ONLINE"] = previous_online
    if not explicit_online and status == "passed":
        status = "warning"
        results.append({"scenario": "online_service", "status": "warning", "message": "online pgvector disabled; local projection proof only"})
    content = {
        "drill_id": make_id("pgvector_online_smoke", f"{project_id}-{utc_now()}"),
        "scenarios": scenarios,
        "results": results,
        "recovery_actions": [
            "set NOVEL_FORGE_PGVECTOR_ONLINE=1 and configure NOVEL_FORGE_DATABASE_URL for real service verification",
            "run pgvector migrate and verify before production traffic",
        ],
        "status": status,
        "created_at": utc_now(),
    }
    asset = BaseAsset(
        type="local_ops_drill_report",
        title="Pgvector online E2E smoke proof",
        tags=["pgvector", "online-smoke", status],
        content=content,
        metadata={"project_id": project_id, "backend": "pgvector", "online_enabled": capabilities["online_enabled"]},
    )
    written = _write(storage, asset)
    return {**written, "status": status, "content": content}


def rebuild_dirty_index(storage: LocalStorage, *, project_id: str = "", persist: bool = True) -> dict[str, Any]:
    rows = _vector_rows(storage, project_id=project_id)
    dirty_rows = [row for row in rows if row.get("dirty_index")]
    plan = {
        "status": "clean" if not dirty_rows else "rebuild_planned",
        "project_id": project_id,
        "dirty_index_count": len(dirty_rows),
        "rebuild_plan": [
            {
                "chunk_path": row.get("chunk_path", ""),
                "source_asset_id": row.get("source_asset_id", ""),
                "embedding_model": row.get("embedding_model", ""),
                "content_hash": row.get("content_hash", ""),
            }
            for row in dirty_rows[:500]
        ],
        "source_isolation": {
            "raw_source_text_included": False,
            "policy": "rebuild references chunk assets; raw source documents remain excluded",
        },
        "created_at": utc_now(),
    }
    if not persist:
        return plan
    asset = BaseAsset(
        type="embedding_job",
        title=f"Pgvector dirty index rebuild {plan['status']}",
        tags=["pgvector", "dirty-index", str(plan["status"])],
        content={
            "job_id": make_id("embedding_job", f"dirty-index-{project_id}-{utc_now()}"),
            "source_paths": [str(row.get("chunk_path", "")) for row in dirty_rows if row.get("chunk_path")],
            "backend": "pgvector_dirty_index_rebuild",
            "status": plan["status"],
            "chunk_count": len(dirty_rows),
            "chunks": [],
            "errors": [],
            "dirty_index_rebuild_plan": plan,
            "created_at": utc_now(),
        },
        metadata={"project_id": project_id, "backend": "pgvector_dirty_index_rebuild", "dirty_index_count": len(dirty_rows)},
        references=filter_project_safe_references(storage, project_id, [str(row.get("chunk_path", "")) for row in dirty_rows if row.get("chunk_path")]),
    )
    written = _write(storage, asset)
    return {**plan, "path": written["path"], "asset": written["asset"], "validation": written["validation"]}


def pgvector_qdrant_comparison_report(storage: LocalStorage, *, project_id: str = "") -> dict[str, Any]:
    capabilities = pgvector_capabilities(storage, project_id=project_id)
    return {
        "project_id": project_id,
        "pgvector": {
            "role": capabilities["role"],
            "default_enabled": True,
            "online_enabled": capabilities["online_enabled"],
            "local_projection_chunk_count": capabilities["local_projection_chunk_count"],
            "strengths": ["PostgreSQL-native governance metadata", "Context Builder first retrieval base", "local hash fallback"],
            "limits": ["P0/P1 PoC dimension", "online mode requires opt-in PostgreSQL + pgvector"],
        },
        "qdrant": {
            "role": capabilities["qdrant_role"],
            "default_enabled": False,
            "strengths": ["high-performance vector service", "large-scale ANN retrieval"],
            "limits": ["optional service", "not the business source of truth"],
        },
        "recommendation": "Use pgvector/local projection as the Novel OS governance base and keep Qdrant as opt-in high-performance retrieval.",
        "source_isolation": capabilities["source_isolation"],
    }


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
    rejected_sources = []
    for source_path in source_paths:
        try:
            chunks.extend(_chunk_asset(storage, source_path, backend=backend, chunk_size=chunk_size, project_id=project_id, workspace_path=workspace_path))
        except PermissionError as exc:
            rejected_sources.append({"source_path": source_path, "reason": str(exc), "source_isolation": "rejected"})
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
        "rejected_sources": rejected_sources,
        "source_isolation": {
            "high_risk_rejected": bool(rejected_sources),
            "raw_text_allowed": False,
            "generation_flows_exclude_raw_sources": True,
        },
        "dirty_index": False,
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
    return {**written, "chunks": chunks, "errors": errors, "rejected_sources": rejected_sources}


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
    results = _dedupe_ranked_rows(sorted(scored, key=lambda row: (-float(row.get("score", 0) or 0), str(row.get("path", "")))))[: int(limit or 12)]
    report = {
        "report_id": make_id("hybrid_retrieval", f"{project_id}-{query}-{utc_now()}"),
        "query": query,
        "retrieval_backend": retrieval_backend,
        "vector_backend": "pgvector_online" if online.get("status") == "succeeded" else "local_hash_embedding",
        "online_pgvector": {key: value for key, value in online.items() if key != "rows"},
        "results": results,
        "source_isolation": {
            "raw_source_text_included": False,
            "high_risk_results_rejected": True,
            "forbidden_flows": ["prose", "publish"],
        },
        "context_builder_evidence": {
            "retrieval_backend": retrieval_backend,
            "vector_backend": "pgvector_online" if online.get("status") == "succeeded" else "local_hash_embedding",
            "result_count": len(results),
            "result_refs": [str(item.get("chunk_path") or item.get("path") or "") for item in results],
        },
        "pgvector_qdrant_comparison": {
            "pgvector_role": "os_internal_knowledge_memory_base",
            "qdrant_role": "optional_high_performance_vector_service",
            "default_order": ["pgvector", "qdrant", "local"],
        },
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
    source_policy = _source_policy_for_asset(data)
    if source_policy["source_risk_level"] == "high" and not source_policy["raw_text_allowed"]:
        raise PermissionError(f"high-risk source rejected for pgvector embedding: {asset.type}")
    text = _asset_text(data)
    chunks = [_clip(text[index : index + chunk_size]) for index in range(0, len(text), chunk_size)] or [_clip(text)]
    written_chunks = []
    for index, chunk_text in enumerate(chunks):
        chunk_id = make_id("chunk", f"{asset.id}-{index}-{backend}")
        embedding = _embed(chunk_text)
        content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        chunk_metadata = {
            "asset_type": asset.type,
            "chunk_index": index,
            "project_id": resolved_project_id,
            "source_policy": source_policy,
            "content_hash": content_hash,
            "embedding_model": backend,
            "embedding_version": "v1",
            "dirty_index": False,
            "quality_score": source_policy["quality_score"],
        }
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
                    "metadata": chunk_metadata,
                },
                metadata={"project_id": resolved_project_id, "workspace_path": resolved_workspace, "asset_type": asset.type, **source_policy},
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
                    "metadata": chunk_metadata,
                },
                metadata={"project_id": resolved_project_id, "workspace_path": resolved_workspace, "asset_type": asset.type, **source_policy},
                references=filter_project_safe_references(storage, resolved_project_id, [asset.id, _display_path(storage.root, source_file)]),
            )
        written = _write(storage, chunk_asset)
        written_chunks.append({"path": written["path"], "chunk_id": chunk_id, "asset_type": asset.type, "embedding_dim": len(embedding), **source_policy, "content_hash": content_hash})
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
            chunk_meta = content.get("metadata", {}) if isinstance(content.get("metadata", {}), dict) else {}
            source_policy = chunk_meta.get("source_policy", {}) if isinstance(chunk_meta.get("source_policy", {}), dict) else {}
            if str(source_policy.get("source_risk_level") or metadata.get("source_risk_level") or "low") == "high":
                continue
            embedding = content.get("embedding", [])
            if not isinstance(embedding, list):
                continue
            rows.append(
                {
                    "path": str(content.get("source_path") or _display_path(storage.root, path)),
                    "chunk_path": _display_path(storage.root, path),
                    "id": data.get("id", ""),
                    "type": data.get("type", ""),
                    "backend": "pgvector_local_projection",
                    "text": str(content.get("text", "")),
                    "embedding": [float(value) for value in embedding],
                    "source_asset_id": content.get("source_asset_id", ""),
                    "source_type": source_policy.get("source_type", metadata.get("source_type", "")),
                    "source_risk_level": source_policy.get("source_risk_level", metadata.get("source_risk_level", "low")),
                    "license_policy": source_policy.get("license_policy", metadata.get("license_policy", "project_owned")),
                    "permission_scope": source_policy.get("permission_scope", metadata.get("permission_scope", "internal")),
                    "flow_allowlist": source_policy.get("flow_allowlist", metadata.get("flow_allowlist", [])),
                    "raw_text_allowed": bool(source_policy.get("raw_text_allowed", metadata.get("raw_text_allowed", False))),
                    "content_hash": chunk_meta.get("content_hash", ""),
                    "embedding_model": chunk_meta.get("embedding_model", ""),
                    "embedding_version": chunk_meta.get("embedding_version", ""),
                    "dirty_index": bool(chunk_meta.get("dirty_index", False)),
                    "quality_score": float(chunk_meta.get("quality_score", 0) or 0),
                }
            )
    return rows


def _source_policy_for_asset(data: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(data.get("type", ""))
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata", {}), dict) else {}
    content = data.get("content", {}) if isinstance(data.get("content", {}), dict) else {}
    source_type = str(metadata.get("source_type") or asset_type)
    high_risk_types = {
        "source_document",
        "source_chunk",
        "source_deconstruction_observation",
        "source_reprocessing_plan",
        "cleaned_text",
    }
    source_risk_level = str(metadata.get("source_risk_level") or ("high" if asset_type in high_risk_types else "low"))
    license_policy = str(metadata.get("license_policy") or metadata.get("rights_status") or "project_owned")
    permission_scope = str(metadata.get("permission_scope") or "internal")
    flow_allowlist = metadata.get("flow_allowlist", []) if isinstance(metadata.get("flow_allowlist", []), list) else []
    if not flow_allowlist:
        flow_allowlist = ["research", "evaluation", "review"] if source_risk_level == "high" else ["outline", "chapter_outline", "prose", "review", "revision", "recap", "publish", "feedback"]
    raw_text_allowed = bool(metadata.get("raw_text_allowed", False)) and source_risk_level != "high"
    quality_score = float(metadata.get("quality_score", content.get("quality_score", 0.7)) or 0.7)
    return {
        "source_type": source_type,
        "source_risk_level": source_risk_level,
        "license_policy": license_policy,
        "permission_scope": permission_scope,
        "flow_allowlist": flow_allowlist,
        "raw_text_allowed": raw_text_allowed,
        "evidence_span": metadata.get("evidence_span", {}) if isinstance(metadata.get("evidence_span", {}), dict) else {},
        "quality_score": round(quality_score, 4),
    }


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
                    (id, project_id, chunk_type, source_path, source_asset_id, source_type, source_risk_level,
                     license_policy, permission_scope, flow_allowlist, raw_text_allowed, evidence_span,
                     content_hash, embedding_model, embedding_version, dirty_index, quality_score,
                     content, embedding, metadata, updated_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, now())
                    on conflict (id) do update set
                      project_id = excluded.project_id,
                      chunk_type = excluded.chunk_type,
                      source_path = excluded.source_path,
                      source_asset_id = excluded.source_asset_id,
                      source_type = excluded.source_type,
                      source_risk_level = excluded.source_risk_level,
                      license_policy = excluded.license_policy,
                      permission_scope = excluded.permission_scope,
                      flow_allowlist = excluded.flow_allowlist,
                      raw_text_allowed = excluded.raw_text_allowed,
                      evidence_span = excluded.evidence_span,
                      content_hash = excluded.content_hash,
                      embedding_model = excluded.embedding_model,
                      embedding_version = excluded.embedding_version,
                      dirty_index = excluded.dirty_index,
                      quality_score = excluded.quality_score,
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
                        row.get("source_type", ""),
                        row.get("source_risk_level", "low"),
                        row.get("license_policy", "project_owned"),
                        row.get("permission_scope", "internal"),
                        row.get("flow_allowlist", []),
                        bool(row.get("raw_text_allowed", False)),
                        json.dumps(row.get("evidence_span", {}), ensure_ascii=False),
                        row.get("content_hash", ""),
                        row.get("embedding_model", backend),
                        row.get("embedding_version", "v1"),
                        bool(row.get("dirty_index", False)),
                        float(row.get("quality_score", 0) or 0),
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
                select id, project_id, chunk_type, source_path, source_asset_id, source_type, source_risk_level,
                       license_policy, permission_scope, flow_allowlist, raw_text_allowed, evidence_span,
                       content_hash, embedding_model, embedding_version, dirty_index, quality_score,
                       content, metadata,
                       1 - (embedding <=> %s::vector) as vector_score
                from nf_pgvector_chunks
                where (%s = '' or project_id = %s)
                  and source_risk_level <> 'high'
                  and raw_text_allowed = false
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
    chunk_meta = content.get("metadata", {}) if isinstance(content.get("metadata", {}), dict) else {}
    source_policy = chunk_meta.get("source_policy", {}) if isinstance(chunk_meta.get("source_policy", {}), dict) else {}
    embedding = content.get("embedding", [])
    if not isinstance(embedding, list):
        return None
    if str(source_policy.get("source_risk_level") or metadata.get("source_risk_level") or "low") == "high":
        return None
    source_path = str(content.get("source_path") or path_value)
    return {
        "id": str(content.get("chunk_id") or content.get("embedding_id") or data.get("id", "")),
        "path": source_path,
        "chunk_path": path_value,
        "type": str(data.get("type", "")),
        "project_id": str(metadata.get("project_id", "")),
        "source_asset_id": str(content.get("source_asset_id") or content.get("memory_id") or content.get("entity_id") or ""),
        "text": str(content.get("text", "")),
        "embedding": [float(value) for value in embedding],
        "source_type": source_policy.get("source_type", metadata.get("source_type", "")),
        "source_risk_level": source_policy.get("source_risk_level", metadata.get("source_risk_level", "low")),
        "license_policy": source_policy.get("license_policy", metadata.get("license_policy", "project_owned")),
        "permission_scope": source_policy.get("permission_scope", metadata.get("permission_scope", "internal")),
        "flow_allowlist": source_policy.get("flow_allowlist", metadata.get("flow_allowlist", [])),
        "raw_text_allowed": bool(source_policy.get("raw_text_allowed", metadata.get("raw_text_allowed", False))),
        "evidence_span": source_policy.get("evidence_span", metadata.get("evidence_span", {})),
        "content_hash": chunk_meta.get("content_hash", ""),
        "embedding_model": chunk_meta.get("embedding_model", ""),
        "embedding_version": chunk_meta.get("embedding_version", ""),
        "dirty_index": bool(chunk_meta.get("dirty_index", False)),
        "quality_score": float(chunk_meta.get("quality_score", 0) or 0),
        "metadata": {**metadata, "asset_type": metadata.get("asset_type", ""), "local_chunk_path": path_value, "source_path": source_path},
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
                "source_type": row[5],
                "source_risk_level": row[6],
                "license_policy": row[7],
                "permission_scope": row[8],
                "flow_allowlist": row[9],
                "raw_text_allowed": row[10],
                "evidence_span": row[11],
                "content_hash": row[12],
                "embedding_model": row[13],
                "embedding_version": row[14],
                "dirty_index": row[15],
                "quality_score": row[16],
                "content": row[17],
                "metadata": row[18],
                "vector_score": row[19],
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
        "source_type": str(values.get("source_type", "")),
        "source_risk_level": str(values.get("source_risk_level", "low")),
        "license_policy": str(values.get("license_policy", "project_owned")),
        "permission_scope": str(values.get("permission_scope", "internal")),
        "flow_allowlist": values.get("flow_allowlist", []) if isinstance(values.get("flow_allowlist", []), list) else [],
        "raw_text_allowed": bool(values.get("raw_text_allowed", False)),
        "content_hash": str(values.get("content_hash", "")),
        "embedding_model": str(values.get("embedding_model", "")),
        "embedding_version": str(values.get("embedding_version", "")),
        "dirty_index": bool(values.get("dirty_index", False)),
        "quality_score": float(values.get("quality_score", 0) or 0),
        "vector_score": float(values.get("vector_score", 0.0) or 0.0),
    }


def _dedupe_ranked_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("path", "") or row.get("source_asset_id", "") or row.get("id", ""))
        if not key:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)[:200]
        existing = by_path.get(key)
        if existing is None:
            by_path[key] = row
            continue
        winner, loser = (row, existing) if _backend_priority(row) > _backend_priority(existing) else (existing, row)
        winner = dict(winner)
        winner["score"] = max(float(existing.get("score", 0) or 0), float(row.get("score", 0) or 0))
        winner["merged_backends"] = _dedupe_strings([str(existing.get("backend", "")), str(row.get("backend", "")), *[str(item) for item in existing.get("merged_backends", []) if str(item).strip()], *[str(item) for item in row.get("merged_backends", []) if str(item).strip()]])
        winner["merged_duplicate_count"] = int(existing.get("merged_duplicate_count", 1) or 1) + int(loser.get("merged_duplicate_count", 1) or 1)
        by_path[key] = winner
    return sorted(by_path.values(), key=lambda row: (-float(row.get("score", 0) or 0), -_backend_priority(row), str(row.get("path", ""))))


def _backend_priority(row: dict[str, Any]) -> int:
    backend = str(row.get("backend", ""))
    if "pgvector_online" in backend:
        return 40
    if "pgvector" in backend:
        return 30
    if "memory_record" in backend:
        return 20
    return 10


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _ensure_pgvector_online_schema(conn: Any) -> None:
    for statement in _pgvector_schema_statements():
        _execute(conn, statement, ())


def _pgvector_schema_statements() -> list[str]:
    return [
        "create extension if not exists vector",
        """
        create table if not exists nf_pgvector_chunks (
          id text primary key,
          project_id text not null default '',
          chunk_type text not null,
          source_path text not null,
          source_asset_id text not null default '',
          source_type text not null default '',
          source_risk_level text not null default 'low',
          license_policy text not null default 'project_owned',
          permission_scope text not null default 'internal',
          flow_allowlist text[] not null default array[]::text[],
          raw_text_allowed boolean not null default false,
          evidence_span jsonb not null default '{}'::jsonb,
          content_hash text not null default '',
          embedding_model text not null default 'local_hash_embedding',
          embedding_version text not null default 'v1',
          dirty_index boolean not null default false,
          quality_score double precision not null default 0,
          content text not null,
          embedding vector(64) not null,
          metadata jsonb not null default '{}'::jsonb,
          updated_at timestamptz not null default now()
        )
        """,
        "create index if not exists nf_pgvector_chunks_project_idx on nf_pgvector_chunks(project_id)",
        "create index if not exists nf_pgvector_chunks_type_idx on nf_pgvector_chunks(chunk_type)",
        "create index if not exists nf_pgvector_chunks_risk_idx on nf_pgvector_chunks(source_risk_level)",
        "create index if not exists nf_pgvector_chunks_dirty_idx on nf_pgvector_chunks(dirty_index)",
        "create index if not exists nf_pgvector_chunks_embedding_idx on nf_pgvector_chunks using ivfflat (embedding vector_cosine_ops)",
    ]


def _pgvector_counts(conn: Any) -> dict[str, Any]:
    rows = _fetchall(
        conn,
        """
        select coalesce(chunk_type, '') as chunk_type, count(*) as row_count
        from nf_pgvector_chunks
        group by chunk_type
        order by chunk_type
        """,
        (),
    )
    counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            counts[str(row.get("chunk_type", ""))] = int(row.get("row_count", 0) or 0)
        else:
            counts[str(row[0])] = int(row[1] or 0)
    return {"by_chunk_type": counts, "total": sum(counts.values())}


def _pgvector_connect(storage: LocalStorage) -> Any:
    settings = IndustrialSettings.from_env(root=storage.root)
    if not settings.database_url:
        raise RuntimeError("NOVEL_FORGE_DATABASE_URL is required for pgvector online backend")
    from novel_forge.storage.database_runtime import get_database_runtime

    return get_database_runtime(settings.database_url).connection(timeout=2)


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
    asset: BaseAsset,
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
