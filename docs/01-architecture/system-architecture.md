# System Architecture

## Architecture

V5 is a CLI-first Python system using local filesystem storage and schema-backed JSON assets. Industrial services are optional adapters around that core, not replacements for validation or storage boundaries.

```text
CLI -> workflows -> schemas -> local storage
              -> model adapters
              -> evaluation rules
```

Industrial runtime:

```text
Next.js -> FastAPI -> workflows -> local JSON assets
                        -> PostgreSQL write-through asset/project/task/version index
                        -> Redis/Celery async workers
                        -> Qdrant vector retrieval
                        -> MinIO object storage
```

## Why This Architecture

V4 documented a large industrial writing system but implementation was scattered and mostly skeletal. V5 uses a smaller executable core so each module can be tested before adding external systems.

## Extension Points

- Model adapters for Claude, Codex, ChatGPT, DeepSeek, MockModel, and local rules.
- PostgreSQL is the primary API index for JSON assets, projects, task statuses, and content-hash versions when configured.
- FastAPI exposes asset, retrieval, workflow, and task endpoints.
- Redis/Celery runs batch ingestion, pipeline runs, and long indexing tasks asynchronously.
- Qdrant provides real vector retrieval while local hash-vector search remains the offline fallback.
- MinIO stores object copies for raw material, generated artifacts, and exports.
- Neo4j remains gated until relationship-heavy projects require graph queries.

## Model Adapter Boundary

`MockModelAdapter` and `LocalRuleEngine` are executable locally. ChatGPT and DeepSeek are opt-in OpenAI-compatible JSON chat providers with strict output validation. Claude Code and Codex remain manual/operator adapters; they do not run as in-process model APIs.
