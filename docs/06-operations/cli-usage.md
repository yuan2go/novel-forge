# CLI Usage

## Initialize

```bash
./novel-forge init
```

## Single-Step Commands

```bash
./novel-forge ingest examples/sample_inputs/sample_novel.txt
./novel-forge ingest examples/sample_inputs/
./novel-forge clean
./novel-forge decompose
./novel-forge extract-knowledge
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
./novel-forge build-vector-index
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

EPUB extraction uses the Python standard library to read text/html/xhtml entries. MOBI and AZW3 support is fixture-level text extraction without external dependencies; full proprietary ebook parsing is deferred.

`clean` normalizes imported text before downstream decomposition. Current cleaning rules:

- Normalize newlines and repeated inline spaces.
- Remove conservative advertisement, watermark, source-link, and platform-promo lines.
- Normalize common OCR artifacts such as zero-width characters, BOM, non-breaking spaces, and obvious repeated punctuation.
- Collapse repeated blank lines.
- Detect chapter headings like `第一章 标题`, `第2章 标题`, and `Chapter 1`.

Detected chapters are stored in `CleanedText.content.chapters`; cleaning stats are stored in metadata.

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

`build-vector-index` writes `data/indexes/vector-index.json` using the local `HashEmbeddingAdapter`. `vector-search` ranks assets by cosine similarity over deterministic hash vectors and returns `score` plus `ranker`. This validates vector retrieval plumbing without external APIs; it is not a true semantic embedding model.

`topic-development` is the explicit Skill-aligned topic workflow. It reads the latest `data/materials/*.json` asset by default, or an asset passed through `--input`, and writes a schema-backed `TopicSeed` to `data/topics/`. `generate-topic` remains as the compatibility alias.

`training-exercise` reads the latest `data/topics/*.json` asset by default, or an asset passed through `--input`, and writes a schema-backed `TrainingExercise` to `data/training/`. Training assets are practice prompts and rubrics; they are not canonical novel output.

`compare-reviews` reads the latest `data/drafts/*.json` asset by default, or an asset passed through `--input`, and writes a schema-backed `ReviewReport` tagged `review-comparison`. The first implementation runs deterministic local mock reviewers for structure, commercial readability, and originality boundary, then records model reviews, score summary, consensus, disagreements, and revision priorities.

`init-workspace` creates a schema-backed `ProjectWorkspaceState` under `data/workspaces/`. `update-workspace` reads a draft or review asset and updates chapter state, memory, open hooks, and open issues. `workspace-status` prints a JSON summary with chapter count, latest chapter, open hook count, open issue count, and references.

`analyze-feedback` writes a schema-backed `FeedbackInsight`. It now aggregates reader feedback across imported `ReaderFeedback` assets, computes per-chapter rating trends, retention risk, sentiment keyword signals, and a plot adjustment plan with next-generation constraints.

## End To End

```bash
./novel-forge run-pipeline --sample
./novel-forge status
./novel-forge validate
```

## Sample Run Cleanup

`run-pipeline --sample` reads `examples/sample_outputs/pipeline-summary.json` before running. If the summary exists, it removes only the previous sample output paths listed in that summary, then generates a new sample run. This prevents repeated demo runs from accumulating duplicate sample assets.

## Failure Recovery

If a pipeline step fails, inspect the failed `WorkflowRun` under `data/runs/`. The run content includes:

- `run_log`
- `error_message`
- `recovery_instruction`
- `recovery_path`

The recovery note path points to a Markdown file under `data/runs/` with the failed step, inputs, outputs, and recommended recovery action.

## Model Adapter Operations

Current runnable workflows use `MockModelAdapter` and `LocalRuleEngine`.

Provider adapters for Claude Code, Codex, ChatGPT, and DeepSeek are contract skeletons. Their `health_check()` methods can be inspected by code/tests, but generation/review methods intentionally fail closed until a real provider implementation is added through an ADR, dependency policy, and secret policy.
