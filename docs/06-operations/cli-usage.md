# CLI Usage

## Local Production Stack

Start the full local Mac production-style stack with Docker:

```bash
make local-up
```

This starts PostgreSQL, Redis, Qdrant, MinIO, FastAPI, Celery worker, and the Next.js admin console. It also initializes and syncs PostgreSQL, then runs `scripts/local_smoke.py`.

Useful local stack commands:

```bash
make local-smoke
make local-logs
make local-down
```

The web console runs at `http://localhost:3000`; FastAPI runs at `http://localhost:8000`.

Local production runtime data lives under the ignored `.local/workspace/` directory. Docker mounts that directory into API and worker containers as `/runtime`; repository-root `data/` is not a fixture source and should not be committed.

## Initialize

```bash
./novel-forge init
```

CLI commands default to `NOVEL_FORGE_ROOT` when it is set, otherwise the current directory. For local production-style work, use:

```bash
export NOVEL_FORGE_ROOT=.local/workspace
```

## Single-Step Commands

```bash
./novel-forge ingest examples/sample_inputs/sample_novel.txt
./novel-forge ingest examples/sample_inputs/
./novel-forge clean
./novel-forge decompose
./novel-forge extract-knowledge
./novel-forge claude-deconstruct --input data/cleaned/example.json --genre "urban suspense"
./novel-forge claude-knowledge --input data/raw/domain-note.json --discipline "forensic accounting"
./novel-forge build-materials
./novel-forge generate-topic
./novel-forge topic-development
./novel-forge training-exercise
./novel-forge generate-world
./novel-forge generate-characters
./novel-forge generate-outline
./novel-forge generate-chapter-plan
./novel-forge draft
./novel-forge review
./novel-forge compare-reviews
./novel-forge revise
./novel-forge import-feedback examples/sample_inputs/sample_feedback.csv
./novel-forge analyze-feedback
./novel-forge build-index
./novel-forge build-manifest
./novel-forge manifest-status
./novel-forge build-vector-index
./novel-forge industrial-status
./novel-forge postgres-init
./novel-forge postgres-sync
./novel-forge qdrant-index
./novel-forge qdrant-search --category materials --query "chapter hook obligation"
./novel-forge minio-sync --category raw --category drafts
./novel-forge neo4j-status
./novel-forge serve-api
./novel-forge worker
./novel-forge search --category materials --type material_card --tag hook --keyword obligation
./novel-forge search --category materials --keyword hook --rank relevance
./novel-forge vector-search --category materials --query "chapter hook obligation"
./novel-forge init-workspace --title "Echo Clock Project"
./novel-forge update-workspace --input data/drafts/example.json --chapter 1
./novel-forge workspace-status
```

`ingest` accepts a single source file or a directory. Directory import recursively imports supported source fixtures:

- `.txt`
- `.md`
- `.epub`
- `.mobi`
- `.azw3`

TXT/MD extraction detects common Chinese encodings including UTF-8, GB18030, GBK, and Big5, then records `detected_encoding`, `encoding_confidence`, candidates, and warnings in source metadata. EPUB extraction uses the Python standard library and prefers `META-INF/container.xml` plus OPF spine order before falling back to sorted text/html/xhtml entries. Source metadata records extraction method, EPUB spine items, EPUB metadata when available, and extraction warnings. MOBI and AZW3 support remains limited binary-readable-text extraction without external dependencies; full proprietary ebook parsing is deferred.

`clean` normalizes imported text before downstream decomposition. Current cleaning rules:

- Normalize newlines and repeated inline spaces.
- Remove conservative advertisement, watermark, source-link, and platform-promo lines.
- Normalize common OCR artifacts such as zero-width characters, BOM, non-breaking spaces, and obvious repeated punctuation.
- Collapse repeated blank lines.
- Detect chapter headings like `第一章 标题`, `第2章 标题`, and `Chapter 1`.

Detected chapters are stored in `CleanedText.content.chapters`; cleaning stats are stored in metadata.

`analyze-reference` creates a schema-backed abstract analysis report from a source or cleaned asset:

```bash
CODEX_HOME=~/.codex-claude NOVEL_FORGE_MODEL_PROVIDER=claude-code \
  novel-forge analyze-reference \
  --root .local/workspace \
  --input data/cleaned/example.json \
  --analysis-type web_fiction_business
```

Reference analysis is for structural learning only. Reports include metrics such as chapter markers, hook signals, and oral-performance style signals for pingshu/xiangsheng-like narration, but they are marked `use_in_generation_rag=false` and must not copy protected prose, names, scenes, settings, jokes, or plot sequence.

`search` lists and filters local JSON assets. Supported filters:

- `--category`: data directory such as `materials`, `drafts`, or `reviews`.
- `--type`: schema type such as `material_card`.
- `--tag`: required tag; can be repeated.
- `--keyword`: searches title, name, source, tags, content, and metadata.
- `--limit`: maximum number of JSON results.
- `--rank path|relevance`: `path` keeps deterministic path order; `relevance` applies local title/tag/source/content weighting and returns `score`.
- `--rebuild-index`: rebuilds the local retrieval index before searching.
- `--no-index`: bypasses the retrieval index and scans JSON assets directly.

`build-index` writes the reusable local retrieval index to `data/indexes/retrieval-index.json`. `search` uses that index by default and automatically rebuilds it when asset fingerprints change. Search output is JSON so it can be consumed by scripts.

`build-manifest` writes `data/indexes/asset-manifest.sqlite`, a SQLite audit/index table for local JSON assets. `manifest-status` reads the manifest and reports asset counts by category. This is the first industrialization layer above raw JSON files: JSON remains the source asset format, while SQLite supports scalable inventory and audit checks.

`build-vector-index` writes `data/indexes/vector-index.json` using the local `HashEmbeddingAdapter`. `vector-search` ranks assets with a hybrid local ranker: deterministic hash-vector cosine similarity plus BM25-style lexical scoring. The tokenizer includes ASCII tokens and Chinese unigram/bigram features. This is stronger than the first hash-only proof, but it is still not a true semantic embedding model or vector database.

`claude-deconstruct` and `claude-knowledge` create schema-backed `ClaudeCodeHandoff` assets under `data/runs/`. Use them when web-novel deconstruction or multidisciplinary knowledge parsing should be performed by the current Claude Code session using Codex, rather than by an in-process provider API. The handoff references the input asset path and required skill files, but does not copy source text into the handoff. After Claude Code writes the expected `DecompositionReport` or `KnowledgeCard`, run `make validate`.

## Industrial Service Commands

`industrial-status` reports local asset counts, configured service URLs, optional dependency availability, model provider health, PostgreSQL mode, and the Neo4j gate state.

`postgres-init` creates PostgreSQL tables for `nf_assets`, `nf_asset_versions`, `nf_task_statuses`, and `nf_projects`. `postgres-sync` scans local JSON assets and mirrors their index rows, content-hash versions, task statuses, project rows, and project-scoped asset columns into PostgreSQL.

`qdrant-index` builds the Qdrant collection from local assets. `qdrant-search` queries Qdrant with the same category/type/tag filters as local vector search.

`minio-sync` uploads local JSON assets into the MinIO artifact bucket. Repeat `--category` to restrict the upload set.

`serve-api` starts the FastAPI backend. `worker` starts the Celery worker. Both require optional dependencies from `.[industrial]` and the services in `docker-compose.yml`.

Online PostgreSQL/pgvector retrieval is opt-in. Local hash-vector retrieval remains the default deterministic path. To sync/query the online pgvector table, install PostgreSQL with the `vector` extension and the optional `psycopg` dependency, then set:

```bash
export NOVEL_FORGE_DATABASE_URL=postgresql://...
export NOVEL_FORGE_PGVECTOR_ONLINE=1
```

Set `NOVEL_FORGE_PGVECTOR_STRICT=1` only when pgvector write/query failures should fail the operation instead of falling back to local retrieval. The online backend maintains `nf_pgvector_chunks` with `vector(64)` embeddings and an ivfflat cosine index.

Neo4j is intentionally not part of the default runtime. `neo4j-status` explains whether graph projection is disabled, unconfigured, or explicitly enabled.

## Web Product Console

Run the backend and web console:

```bash
python -m pip install -e '.[api]'
./novel-forge serve-api
cd web/admin
npm install
npm run dev
```

The console opens at `http://localhost:3000` and calls FastAPI at `http://localhost:8000` by default. Set `NEXT_PUBLIC_NOVEL_FORGE_API_URL` for another backend URL.

Product console areas:

- `Projects`: project workspace creation, project selection, project configuration, lifecycle actions, soft deletion, and continuity status.
- `Tasks`: task status and workflow run inspection, Postgres-backed task index when configured, progress logs, failed-task recovery instructions, retry/cancel actions, worker and queue health, dead-letter inspection/retry, concurrency limits, SSE updates, and project-level timelines scoped to the selected project when available.
- `Assets`: selected-project asset catalog through the Postgres asset index when configured, plus detail, lineage view, local backup diff, reference graph, saved asset collections, and safe title/tag/status/risk/notes editing.
- `Batch`: browser file upload, local path import, source preview, duplicate detection, rights metadata capture, best-effort MinIO raw upload, source deconstruction into raw/cleaned/decomposition/knowledge/material assets, per-source item status, and failed item retry.
- `Drafts`: chapter-plan selection, draft generation, editable draft text, append-only manual saves, draft version metadata, Markdown/DOCX/EPUB export, and workspace update under the selected project.
- `Review`: single review, comparison review, review issue status tracking, revision-plan creation, confirmation-gated revision application, revised draft generation, and post-revision review comparison under the selected project.

`topic-development` is the explicit Skill-aligned topic workflow. It reads the latest `data/materials/*.json` asset by default, or an asset passed through `--input`, and writes a schema-backed `TopicSeed` to `data/topics/`. `generate-topic` remains as the compatibility alias.

`training-exercise` reads the latest `data/topics/*.json` asset by default, or an asset passed through `--input`, and writes a schema-backed `TrainingExercise` to `data/training/`. Training assets are practice prompts and rubrics; they are not canonical novel output.

`compare-reviews` reads the latest `data/drafts/*.json` asset by default, or an asset passed through `--input`, and writes a schema-backed `ReviewReport` tagged `review-comparison`. The first implementation runs deterministic local mock reviewers for structure, commercial readability, and originality boundary, then records model reviews, score summary, consensus, disagreements, and revision priorities.

`init-workspace` creates a schema-backed `ProjectWorkspaceState` under `data/workspaces/`. It also accepts `--series` and `--book` for multi-book project memory. `update-workspace` reads a draft or review asset and updates chapter state, memory, open hooks, and open issues. `workspace-status` prints a JSON summary with chapter count, latest chapter, series/book identifiers, open hook count, open issue count, and references.

`analyze-feedback` writes a schema-backed `FeedbackInsight`. It now aggregates reader feedback across imported `ReaderFeedback` assets, computes per-chapter rating trends, trend metrics, retention risk score, sentiment keyword signals, and a plot adjustment plan with next-generation constraints.

## End To End

```bash
export NOVEL_FORGE_ROOT=.local/demo-workspace
./novel-forge run-pipeline --sample
./novel-forge status
./novel-forge validate
```

## Sample Run Cleanup

`make demo` runs the sample pipeline in `.local/demo-workspace/`. `run-pipeline --sample` reads `<workspace>/examples/sample_outputs/pipeline-summary.json` before running. If the summary exists, it removes only the previous sample output paths listed in that summary, then generates a new sample run. This prevents repeated demo runs from accumulating duplicate sample assets.

## Failure Recovery

If a pipeline step fails, inspect the failed `WorkflowRun` under `data/runs/`. The run content includes:

- `run_log`
- `error_message`
- `recovery_instruction`
- `recovery_path`

The recovery note path points to a Markdown file under `data/runs/` with the failed step, inputs, outputs, and recommended recovery action.

The web task center also reads failed `TaskStatus` assets and exposes recovery reports through `GET /product/tasks/recovery`. Use `POST /product/tasks/retry` with a failed `status_path`, or a `run_id` plus `step`, to re-run the matching operation. The retry writes fresh pending/running/completed or failed status assets, so the project timeline keeps the original failure and the recovery attempt.

When `NOVEL_FORGE_DATABASE_URL` is configured, `postgres-init` creates `nf_assets`, `nf_asset_versions`, `nf_task_statuses`, and `nf_projects`. New local JSON writes use PostgreSQL write-through by default, controlled by `NOVEL_FORGE_POSTGRES_WRITE_THROUGH=true|false`. Set `NOVEL_FORGE_POSTGRES_WRITE_STRICT=true` only when a PostgreSQL write failure should fail the local write. The API reads project, task, and asset lists from PostgreSQL first, then falls back to local JSON if PostgreSQL is unavailable. Successful POST/PATCH/DELETE requests also trigger a best-effort index refresh so local Web usage stays consistent.

Celery dispatch uses `NOVEL_FORGE_CELERY_DEFAULT_QUEUE`, `NOVEL_FORGE_CELERY_TASK_SOFT_TIME_LIMIT`, `NOVEL_FORGE_CELERY_TASK_TIME_LIMIT`, and `NOVEL_FORGE_CELERY_IDEMPOTENCY_TTL_SECONDS`. Duplicate async requests with the same task name and arguments return the remembered task id while the idempotency key is live in Redis.

Worker failures write schema-backed `TaskDeadLetter` assets under `data/runs/`. Inspect them through `GET /product/tasks/dead-letters` or the Web task center, then retry with `POST /product/tasks/dead-letters/retry` after correcting the underlying issue.

Batch deconstruction writes `BatchTaskItem` assets under `data/runs/`. Synchronous runs process the same item-step engine in process. Asynchronous runs create one item per source file, then Celery executes `ingest`, `clean`, `decompose`, `extract-knowledge`, and `build-materials` as chained item-step tasks. Inspect items through `GET /product/batch/items`; retry a failed item with `POST /product/batch/items/retry` after correcting the input file or environment.

Browser uploads are saved under `data/uploads/<upload-id>/`. The upload API parses multipart requests without requiring `python-multipart`; MinIO raw-object upload is attempted when MinIO dependencies and service credentials are available, but local upload remains usable when MinIO is offline.

Draft export writes generated files under `data/exports/`. DOCX and EPUB exports are minimal dependency-free packages intended for handoff and review, not full publishing layout.

## Model Adapter Operations

Agent model calls default to the local Claude Code Codex worker:

```bash
CODEX_HOME=~/.codex-claude codex exec ...
```

Use explicit provider environment variables only when a different route is required:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=chatgpt
export OPENAI_API_KEY=...
```

Operation-specific overrides are available:

- `NOVEL_FORGE_ANALYZE_PROVIDER`
- `NOVEL_FORGE_TOPIC_PROVIDER`
- `NOVEL_FORGE_DRAFT_PROVIDER`
- `NOVEL_FORGE_REVIEW_PROVIDER`
- `NOVEL_FORGE_REVISION_PROVIDER`

Supported providers:

- `chatgpt`: uses `OPENAI_API_KEY`, optional `OPENAI_MODEL`, optional `OPENAI_CHAT_COMPLETIONS_URL`.
- `deepseek`: uses `DEEPSEEK_API_KEY`, optional `DEEPSEEK_MODEL`, optional `DEEPSEEK_CHAT_COMPLETIONS_URL`.
- `codex`: disabled by default; set `NOVEL_FORGE_CODEX_CLI_ENABLED=1` to run local `codex exec`.
- `claude-code`: default agent runtime; runs local `codex exec` with `CODEX_HOME=~/.codex-claude`.
- `mock`: explicit deterministic offline adapter for tests and demos.

Local Codex workers run with automation isolation by default: `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, and `--sandbox read-only`. Override only when deliberately validating a trusted local profile.

OpenAI-compatible providers support raw HTTP SSE streaming and optional SDK streaming. Enable SDK streaming only when the `openai` Python package is installed and you want provider-native stream iteration/cancel behavior:

```bash
export NOVEL_FORGE_PROVIDER_SDK_STREAMING=1
```

Provider-specific toggles are also supported, for example `NOVEL_FORGE_CHATGPT_SDK_STREAMING=1` or `NOVEL_FORGE_DEEPSEEK_SDK_STREAMING=1`.

Every provider call uses a strict JSON prompt contract and validates output before writing assets. Draft/topic generation requires `text`; decomposition/reference analysis requires `summary`, `word_count`, and `patterns`; review requires score, strengths, weaknesses, issues, risk level, revision suggestions, and next action; revision requires an ordered `plan`.

Claude Code still supports manual handoff through `ClaudeCodeAdapter.create_handoff_packet()`. For deterministic offline test or demo runs, override the runtime explicitly:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=mock
```

For high-judgment analysis, prefer handoff packets unless the local worker has been validated for the target schema:

```bash
./novel-forge claude-deconstruct --input data/cleaned/example.json --genre "urban suspense"
./novel-forge claude-knowledge --input data/raw/domain-note.json --discipline "forensic accounting"
```

## Remote Tool And Cockpit Smoke Operations

ToolGateway can register HTTP JSON-RPC MCP servers through the OS tools API. Registered servers can materialize remote `tool_definition` assets, discover remote tools with `mcp.discover_tools`, and invoke remote tools through MCP `tools/call`. Set `NOVEL_FORGE_MCP_TIMEOUT_SECONDS` to bound remote tool calls; the default is 30 seconds.

The browser cockpit smoke is optional in default tests and strict only when explicitly requested:

```bash
NOVEL_FORGE_WEB_BASE_URL=http://127.0.0.1:3000 \
NOVEL_FORGE_API_BASE_URL=http://127.0.0.1:8000 \
NOVEL_FORGE_REQUIRE_PLAYWRIGHT=1 \
npm --prefix web/admin run smoke:browser
```

Strict smoke checks a live backend fixture for Workflow, Agent, KG, Trace, Cost, Runtime Policy, and Publishing JSON endpoints before opening the cockpit routes.
