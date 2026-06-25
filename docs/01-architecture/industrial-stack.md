# Industrial Stack

Novel Forge V5 keeps JSON assets as the auditable interchange format and adds service-backed indexes around them.

## Services

| Service | Role | Boundary |
|---|---|---|
| PostgreSQL | Primary API index for assets, projects, task statuses, and content-hash version records | JSON asset files remain the auditable interchange format; writes use PG write-through when configured |
| FastAPI | Backend API for assets, workflow commands, task status, and retrieval | Calls the existing workflow layer instead of bypassing modules |
| Redis + Celery | Async execution for pipeline runs, batch ingestion, long indexing jobs | Workers must write schema-backed task/run assets through existing services |
| Qdrant | Real vector database for asset retrieval | Stores vectors and metadata only; source assets stay in `data/` or object storage |
| MinIO | Object storage for raw material, generated artifacts, and exports | Object copies do not erase local audit assets |
| Next.js | Web operations console | Talks to FastAPI only |
| Neo4j | Optional graph projection for relationship-heavy projects | Disabled by default until relationship queries justify the added system |

## Runtime Flow

```text
Next.js -> FastAPI -> workflows -> local JSON assets
                        |-> PostgreSQL write-through asset/project/task/version index
                        |-> Celery workers via Redis
                        |-> Qdrant vector retrieval
                        |-> MinIO object copies
                        |-> Neo4j graph projection when explicitly enabled
```

## Product Loop

The web console now exposes the end-to-end product loop through `/product/*` API routes:

| Product Area | API | Output |
|---|---|---|
| Project space | `GET/POST /product/projects`, `GET /product/series`, `PATCH /product/projects/{id}/config`, `POST /product/projects/{id}/duplicate`, `POST /product/projects/{id}/archive`, `POST /product/projects/{id}/pause`, `POST /product/projects/{id}/restore`, `DELETE /product/projects/{id}` | Postgres-primary project index from `nf_projects`, `ProjectWorkspaceState` audit assets, lifecycle events, soft deletion, project configuration, project summaries, and series/multi-book grouping |
| Project assets | `GET /product/projects/{id}/assets` | Postgres-primary project-scoped asset rows derived from metadata, references, and workspace chapter state, with JSON fallback |
| Upload and import | `POST /product/uploads` | browser-uploaded source files under `data/uploads/`, duplicate previews, rights metadata, and best-effort MinIO raw-object copies |
| Task center | `GET /product/tasks`, `GET /product/tasks/timeline`, `GET /product/tasks/recovery`, `POST /product/tasks/retry`, `GET/PATCH /product/tasks/control`, `POST /product/tasks/cancel`, `GET /product/tasks/events`, `GET/POST /product/tasks/dead-letters` | Postgres-primary task status rows, workflow run rows, progress logs, failed-task recovery reports, retry/cancel controls, queue/worker health, concurrency limits, dead-letter inspection/retry, idempotent dispatch, and SSE updates |
| Asset workbench | `GET /product/assets/detail?path=...`, `PATCH /product/assets/detail`, `GET /product/assets/versions`, `GET /product/assets/graph`, `POST /product/assets/collections` | asset payload, summary, lineage references, safe metadata edits, local backup diff, reference graph, and saved `AssetCollection` task-input sets |
| Batch deconstruction | `POST /product/batch/deconstruct`, `GET /product/batch/items`, `POST /product/batch/items/retry`, `PATCH /product/batch/items/review` | raw, cleaned, decomposition, knowledge, material assets, per-source `BatchTaskItem` records, item/step-level Celery execution for async runs, independent retries, and item-level review gates |
| Draft workbench | `GET /product/drafts`, `GET /product/drafts/editor`, `POST /product/drafts/generate`, `POST /product/drafts/save`, `GET /product/drafts/diff`, `POST /product/drafts/export` | chapter plans, editable draft versions, diff summaries, exports, and workspace updates |
| Review and revision | `POST /product/reviews/run`, `PATCH /product/reviews/issues`, `POST /product/revisions/plan`, `POST /product/revisions/apply` | review reports, comparison reviews, issue states, revision plans, confirmation-gated revised drafts, and post-revision score comparison |

The product API is still a thin orchestration layer. It calls the existing workflow and module services so schema validation, copyright boundary metadata, and storage layout stay consistent. When PostgreSQL is configured, local asset writes use PostgreSQL write-through, and project, task, and asset listing APIs read from PostgreSQL first before falling back to JSON scans.

Project-scoped product actions attach generated assets to the selected workspace by writing:

- `metadata.project_id`
- `metadata.workspace_id`
- `metadata.workspace_path`
- `metadata.project_asset_role`

The workspace also records attached asset ids in `references`, so project views can be rebuilt from JSON assets without a database.

Project lifecycle actions are state transitions on the workspace asset. `DELETE` is intentionally a soft-delete transition to `deleted`, preserving traceable project history and recoverable JSON state.

The task center treats `TaskStatus` and `WorkflowRun` JSON assets as the audit trail while PostgreSQL is the primary API index when configured. Retry requests resolve the failed status or run step, execute the matching workflow/module operation through the existing service layer, and write new schema-backed status records instead of mutating the failed record in place.

Celery dispatch is idempotent for matching task arguments, uses the configured default queue, applies soft/hard timeouts, and writes schema-backed `TaskDeadLetter` assets under `data/runs/` when a worker task fails.

Batch deconstruction records one `BatchTaskItem` per discovered source file. Synchronous runs process each item through the same step engine in process. Asynchronous runs enqueue an item-step Celery task for `ingest`, then chain `clean`, `decompose`, `extract-knowledge`, and `build-materials` after each successful step. A failed item can be retried independently after fixing the source file or environment issue.

## Model Providers

Mock models remain the default for tests and deterministic local demos. Real provider calls are opt-in through `NOVEL_FORGE_MODEL_PROVIDER` or operation-specific overrides such as `NOVEL_FORGE_DRAFT_PROVIDER`, `NOVEL_FORGE_REVIEW_PROVIDER`, and `NOVEL_FORGE_REVISION_PROVIDER`.

`chatgpt` and `deepseek` use OpenAI-compatible chat-completions JSON responses. Prompt builders require strict JSON outputs, and model responses are validated before any asset is written.

Draft saves are append-only: manual edits create new `DraftChapter` assets with version metadata instead of overwriting the previous draft. Revision application is confirmation-gated; preview mode returns the planned change without writing a revised draft.

## Local Infrastructure

One-command local production-style stack:

```bash
make local-up
```

This starts Docker Compose services for PostgreSQL, Redis, Qdrant, MinIO, FastAPI, Celery worker, and the Next.js web console. It also creates `.env` when missing, runs `postgres-init`, runs `postgres-sync`, and executes `scripts/local_smoke.py`.

Service URLs:

- Web console: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- Qdrant: `http://localhost:6333`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

Operational commands:

```bash
make local-smoke
make local-logs
make local-down
```

## Neo4j Gate

Neo4j remains opt-in. Enable it only when character relationships, world rules, foreshadowing networks, or continuity dependencies require graph queries that are painful in PostgreSQL and JSON indexes.

```bash
docker compose --profile graph up -d neo4j
export NOVEL_FORGE_ENABLE_NEO4J=true
```

The graph projection must remain derived data. JSON assets and PostgreSQL version records remain the traceable source of truth.
