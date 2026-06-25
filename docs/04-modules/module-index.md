# Module Index

V5 creates package directories for all production modules. The P0 path is orchestrated by `novel_forge.workflows.pipeline` and implemented through `src/novel_forge/modules/<module>/service.py`.

## First Implemented Path

`ingestion -> cleaning -> decomposition -> knowledge -> materials -> topics -> worldbuilding -> characters -> outline -> chapter_plan -> drafting -> review -> revision -> feedback`

`ingestion` supports single-file and directory batch import for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3` fixtures.

`cleaning` removes conservative advertisement/watermark lines, normalizes OCR-style spacing and punctuation noise, collapses repeated blank lines, and records detected chapter headings in `CleanedText.content.chapters`.

`materials` now writes searchable production tags such as `hook`, `conflict`, `reader-retention`, and `chapter-ending`. Local asset search can list/filter JSON assets by category, schema type, tags, and keyword.

`storage` now includes a reusable local retrieval index at `data/indexes/retrieval-index.json`. The `search` command uses the index by default, auto-refreshes it when asset fingerprints change, and can fall back to direct JSON scanning with `--no-index`.

`storage` also includes a local vector index at `data/indexes/vector-index.json`. `build-vector-index` and `vector-search` use deterministic hash embeddings plus BM25-style lexical scoring, with ASCII and Chinese unigram/bigram tokenization. This improves local ranking without introducing external APIs or vector database dependencies.

`storage` now has optional industrial adapters for PostgreSQL, Qdrant, MinIO, and Neo4j. PostgreSQL is the write-through primary API index for asset rows, project rows, task statuses, and content-hash versions when configured. Qdrant provides real vector-database retrieval. MinIO stores object copies for raw material, artifacts, and exports. Neo4j stays gated for relationship-heavy projects only.

`api` exposes the FastAPI backend for status, assets, vector search, workflow runs, and task status. When PostgreSQL is configured, asset, project, and task list APIs use PostgreSQL as the primary index and fall back to local JSON. The product API under `/product/*` adds project space, series/multi-book grouping, project lifecycle actions, project configuration, browser uploads, project-scoped asset/task views, task retry/recovery/cancel/control/SSE APIs, dead-letter inspection/retry, safe asset metadata editing, local asset version diff, reference graph lookup, saved asset collections, item-level batch deconstruction with review gates, editable draft versions with export, and confirmation-gated review/revision orchestration without bypassing workflow services.

`workers` exposes Celery tasks for full pipeline runs, single-step execution, item/step-level batch deconstruction, batch ingestion, and infrastructure sync jobs. Dispatch is idempotent through Redis keys, workers use configured soft/hard timeouts, and task failures write schema-backed `TaskDeadLetter` assets.

`topics` exposes both the compatibility `generate-topic` command and the Skill-aligned `topic-development` command. Both produce schema-backed `TopicSeed` assets with logline, reader attraction, differentiation, market positioning, trope variation, source tags, and an explicit originality boundary.

`training` exposes `training-exercise`, which turns a topic asset into a schema-backed practice prompt and rubric under `data/training/`. This module is for reusable training tasks, not final story canon.

`review` exposes both single-pass `review` and multi-review `compare-reviews`. `compare-reviews` uses local mock reviewer profiles for structure, commercial readability, and originality boundary, then writes a schema-backed `ReviewReport` with `model_reviews`, `score_summary`, `consensus`, and `disagreements`.

`feedback` imports CSV reader feedback and writes `FeedbackInsight` assets with cross-chapter `chapter_trends`, statistical `trend_metrics`, scored `retention_risk`, `sentiment_signals`, and `plot_adjustment_plan`. This keeps feedback as decision support, not direct reader control.

`source_intake` records external source policies and registered GitHub knowledge sources. It separates official data packages, APIs, robot endpoints, manual references, research-only datasets, forum corpora, and crawler-tool references before any source reaches `multidisciplinary-knowledge`. The product API exposes `/product/sources/policies`, `/product/sources/github`, and `/product/handoffs/github-knowledge`; the last endpoint creates a metadata-only source note and a Claude Code/Codex handoff instead of cloning or crawling repositories automatically.

`workspace` exposes `init-workspace`, `update-workspace`, and `workspace-status`. It stores long-project memory under `data/workspaces/`, tracks multiple chapter states, preserves open hooks and unresolved quality issues, and provides a continuation surface for later multi-chapter production.

`handoff` exposes `claude-deconstruct` and `claude-knowledge`. These commands create `ClaudeCodeHandoff` assets in `data/runs/` for Claude Code/Codex execution of web-novel deconstruction and multidisciplinary knowledge parsing. Handoffs reference source asset paths and required skill files without embedding source text, then require schema-backed output and validation.

## Deferred Deepening

Individual module services should later receive deeper domain logic once task status, logs, deterministic demo behavior, and recovery contracts are stable.
