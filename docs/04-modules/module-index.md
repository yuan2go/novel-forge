# Module Index

V5 creates package directories for all production modules. The P0 path is orchestrated by `novel_forge.workflows.pipeline` and implemented through `src/novel_forge/modules/<module>/service.py`.

## First Implemented Path

`ingestion -> cleaning -> decomposition -> knowledge -> materials -> topics -> worldbuilding -> characters -> outline -> chapter_plan -> drafting -> review -> revision -> feedback`

`ingestion` supports single-file and directory batch import for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3` fixtures.

`cleaning` removes conservative advertisement/watermark lines, normalizes OCR-style spacing and punctuation noise, collapses repeated blank lines, and records detected chapter headings in `CleanedText.content.chapters`.

`materials` now writes searchable production tags such as `hook`, `conflict`, `reader-retention`, and `chapter-ending`. Local asset search can list/filter JSON assets by category, schema type, tags, and keyword.

`storage` now includes a reusable local retrieval index at `data/indexes/retrieval-index.json`. The `search` command uses the index by default, auto-refreshes it when asset fingerprints change, and can fall back to direct JSON scanning with `--no-index`.

`storage` also includes a local vector index at `data/indexes/vector-index.json`. `build-vector-index` and `vector-search` use deterministic hash embeddings and cosine scoring, which proves the vector retrieval contract without introducing external APIs or vector database dependencies.

`topics` exposes both the compatibility `generate-topic` command and the Skill-aligned `topic-development` command. Both produce schema-backed `TopicSeed` assets with logline, reader attraction, differentiation, market positioning, trope variation, source tags, and an explicit originality boundary.

`training` exposes `training-exercise`, which turns a topic asset into a schema-backed practice prompt and rubric under `data/training/`. This module is for reusable training tasks, not final story canon.

`review` exposes both single-pass `review` and multi-review `compare-reviews`. `compare-reviews` uses local mock reviewer profiles for structure, commercial readability, and originality boundary, then writes a schema-backed `ReviewReport` with `model_reviews`, `score_summary`, `consensus`, and `disagreements`.

`feedback` imports CSV reader feedback and writes `FeedbackInsight` assets with cross-chapter `chapter_trends`, `retention_risk`, `sentiment_signals`, and `plot_adjustment_plan`. This keeps feedback as decision support, not direct reader control.

`workspace` exposes `init-workspace`, `update-workspace`, and `workspace-status`. It stores long-project memory under `data/workspaces/`, tracks multiple chapter states, preserves open hooks and unresolved quality issues, and provides a continuation surface for later multi-chapter production.

## Deferred Deepening

Individual module services should later receive deeper domain logic once task status, logs, deterministic demo behavior, and recovery contracts are stable.
