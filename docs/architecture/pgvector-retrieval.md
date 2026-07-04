# PostgreSQL + pgvector Retrieval

日期：2026-07-04

## 功能目标

pgvector 是 Novel OS 内部知识 / 记忆检索底座。Qdrant 仍是可选高性能向量服务，pgvector 不替代 Qdrant，也不替代 LocalStorage 业务主数据。

## 当前实现

核心模块：

- `src/novel_forge/modules/pgvector_store/service.py`
- `src/novel_forge/api/routers/os_capabilities.py`
- `src/novel_forge/storage/rag_context.py`

能力：

- pgvector schema plan。
- online migration dry-run / opt-in migrate。
- local hash embedding fallback。
- embedding job。
- hybrid retrieval。
- source isolation。
- high-risk source rejection。
- dirty index rebuild plan。
- pgvector vs Qdrant comparison report。
- Context Builder 可通过 `build_rag_context()` 优先尝试 pgvector。

## 增强字段

- `source_type`
- `source_risk_level`
- `license_policy`
- `permission_scope`
- `flow_allowlist`
- `raw_text_allowed`
- `evidence_span`
- `content_hash`
- `embedding_model`
- `embedding_version`
- `dirty_index`
- `quality_score`

## API

- `GET /product/os/retrieval/pgvector-capabilities`
- `GET /product/os/retrieval/pgvector-operations-plan`
- `POST /product/os/retrieval/pgvector-migrate`
- `POST /product/os/retrieval/pgvector-verify`
- `POST /product/os/retrieval/embedding-job`
- `POST /product/os/retrieval/hybrid`
- `POST /product/os/retrieval/rebuild-dirty-index`
- `GET /product/os/retrieval/pgvector-qdrant-comparison`

## 环境变量

- `NOVEL_FORGE_PGVECTOR_ONLINE`
- `NOVEL_FORGE_PGVECTOR_STRICT`
- `NOVEL_FORGE_DATABASE_URL`

默认不需要真实 PostgreSQL。开启 online 后使用 optional `psycopg`。

## 本地 Docker 验证

`docker-compose.yml` 的默认 `postgres` 服务已使用 `pgvector/pgvector:pg16`，因此本地 PostgreSQL 具备 `vector` extension。

启动和验证：

```bash
make online-backends-up
make online-backends-smoke
```

等价手动命令：

```bash
docker compose --profile analytics up -d postgres clickhouse
NOVEL_FORGE_PGVECTOR_ONLINE=1 \
NOVEL_FORGE_DATABASE_URL=postgresql://novel_forge:novel_forge@localhost:5432/novel_forge \
PYTHONPATH=src python3 scripts/verify_online_backends.py --project-id local-online --require-online
```

## Source Isolation

- `source_document`、`source_chunk`、`cleaned_text` 默认 high risk。
- high-risk source 不进入 generation retrieval projection。
- hybrid report 声明 `raw_source_text_included=false`。
- prose/publish 等生成链路不得读取 `source_chunk.raw_text`。

## 测试

- `tests/unit/test_pgvector_source_isolation.py`
- `tests/unit/test_os_new_capabilities.py`
- `tests/integration/test_novel_os_governance_loop.py`

## 当前限制

- online PostgreSQL 真实迁移仍是 opt-in，但本地 Docker 已提供 pgvector-capable PostgreSQL。
- local hash embedding 是 deterministic PoC，不代表生产向量质量。
- dirty index 当前生成 rebuild plan，不自动重算所有在线向量。

## 后续扩展

- CI 增加 disposable PostgreSQL + pgvector online smoke。
- 增加 retrieval eval set 和 recall regression。
- 长篇压力下的 p95 query、index rebuild、connection pool proof。
