# Novel Forge V5

Novel Forge V5 is a local-first AI novel production platform.

It is not an AI chapter generator. It is designed to turn source materials, abstracted reference analysis, multidisciplinary knowledge, reusable creative assets, context bundles, review reports, revision tasks, reader feedback, and publishing gates into a controlled long-form fiction production workflow.

Internal architecture vision: Novel Operating System.

Repository/package/CLI name remains `novel-forge` in V5. Do not rename the project to Novel Operating System unless a separate migration task approves repository, package, command, path, and documentation changes.

Core executable pipeline:

```text
source material -> cleaned text -> decomposition -> knowledge/material assets -> topic -> world -> characters -> outline -> chapter plan -> draft -> review -> revision -> feedback insight
```

Target platform pipeline:

```text
project strategy -> analysis center -> context build plan -> context bundle -> versioned outline/chapter-plan/draft -> review pipeline -> editor patch/revision task -> continuity/publish gates -> publishing/feedback analytics -> next planning loop
```

## Principles

- Extract structure, rhythm, hooks, conflict mechanics, emotional curves, craft technique, and commercial logic from reference works.
- Do not copy original expression, character combinations, settings, scenes, or plot sequences from copyrighted works.
- Keep raw sources, decomposition/analysis reports, generated assets, drafts, reviews, publishing assets, feedback, and runs in separate directories.
- Treat prompts as node execution parameters, not the product architecture.
- Prefer workflow nodes, schema-backed artifacts, context replay, versioning, and quality gates.
- Use deterministic mock adapters for tests; real OpenAI-compatible providers are opt-in through environment variables.

## Quick Start

```bash
make test
make validate
make demo
./novel-forge --help
```

## Runtime Workspace Boundary

Runtime assets are intentionally kept out of Git. Daily local runs should write to the ignored `.local/workspace/` tree; `make demo`, `make api`, `make worker`, and `make local-up` use that boundary by default.

The repository keeps only deterministic fixtures:

- `examples/sample_inputs/` for small CLI/demo inputs.
- `tests/fixtures/` for stable test-only fixtures.

Generated assets under `data/` and generated sample outputs under `examples/sample_outputs/` are ignored runtime state. If you run CLI commands manually, either pass `--root .local/workspace` or export `NOVEL_FORGE_ROOT=.local/workspace`.

## Local Production Stack

For the local Mac production-style environment, use Docker for PostgreSQL, Redis, Qdrant, MinIO, FastAPI, Celery worker, and the Next.js console:

```bash
make local-up
```

The command creates `.env` from `.env.example` when needed, starts the full Docker Compose stack, initializes and syncs PostgreSQL, then runs a smoke test.

Docker mounts `.local/workspace/` into the containers as `/runtime`, so generated JSON assets, uploads, indexes, exports, and sample outputs remain local runtime state.

Open:

- Web console: `http://localhost:3000`
- FastAPI: `http://localhost:8000`
- MinIO console: `http://localhost:9001`

Useful controls:

```bash
make local-smoke
make local-logs
make local-down
```

## Real Model Providers

The default local path uses `MockModelAdapter`. To call a real OpenAI-compatible provider, set a provider and API key before running API, worker, or CLI commands:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=chatgpt
export OPENAI_API_KEY=...
```

Or use DeepSeek for draft/revision work:

```bash
export NOVEL_FORGE_DRAFT_PROVIDER=deepseek
export NOVEL_FORGE_REVISION_PROVIDER=deepseek
export DEEPSEEK_API_KEY=...
```

Model calls use strict JSON prompts and output validation. Invalid model output fails the step instead of writing malformed assets.

Local Codex CLI can also be used as an opt-in local worker. It remains disabled by default. Enable ordinary Codex with:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=codex
export NOVEL_FORGE_CODEX_CLI_ENABLED=1
```

Enable the Claude Code runtime backed by the local Codex CLI with an isolated Codex home:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=claude-code
export NOVEL_FORGE_CLAUDE_CODE_CLI_ENABLED=1
# internally launches equivalent to:
# CODEX_HOME=~/.codex-claude codex exec ...
```

Both local workers run `codex exec` non-interactively with JSON output schema validation, `read-only` sandbox by default, and `--ask-for-approval never`.

## Core Commands

```bash
./novel-forge init
./novel-forge ingest examples/sample_inputs/sample_novel.txt
./novel-forge clean --input data/raw/<file>.json
./novel-forge decompose --input data/cleaned/<file>.json
./novel-forge extract-knowledge --input data/decompositions/<file>.json
./novel-forge build-materials
./novel-forge generate-topic
./novel-forge topic-development
./novel-forge training-exercise
./novel-forge generate-world
./novel-forge generate-characters
./novel-forge generate-outline
./novel-forge generate-chapter-plan
./novel-forge draft
./novel-forge review --input data/drafts/<file>.json
./novel-forge compare-reviews --input data/drafts/<file>.json
./novel-forge revise --input data/reviews/<file>.json
./novel-forge import-feedback examples/sample_inputs/sample_feedback.csv
./novel-forge analyze-feedback
./novel-forge claude-deconstruct
./novel-forge claude-knowledge
./novel-forge build-index
./novel-forge search
./novel-forge build-vector-index
./novel-forge vector-search --query "..."
./novel-forge qdrant-index
./novel-forge qdrant-search --query "..."
./novel-forge minio-sync
./novel-forge init-workspace
./novel-forge workspace-status
./novel-forge run-pipeline --sample
./novel-forge industrial-status
./novel-forge status
./novel-forge validate
```

These commands default to the current directory unless `NOVEL_FORGE_ROOT` is set. For production-style local use, prefer `NOVEL_FORGE_ROOT=.local/workspace` or explicit `--root .local/workspace`.

## Industrial Stack

The default testable core still runs without third-party dependencies. Production-style infrastructure is available through optional adapters:

- PostgreSQL for asset indexes, projects, task statuses, and content-hash version records.
- FastAPI for backend API access.
- Redis + Celery for async batch and long-running workflow execution.
- Qdrant for real vector retrieval.
- MinIO for object copies of raw material, artifacts, and exports.
- Next.js for the product console under `web/admin/`.
- Neo4j remains opt-in for relationship-heavy graph queries.

```bash
make local-up
```

See [Industrial Stack](docs/01-architecture/industrial-stack.md) for service boundaries.

## Platform Migration Priorities

Current P0 direction:

1. Platform skeleton: workflow/node run, artifact version, context bundle, generation run, quality gate, revision task. First slice exists for `workflow_definition`, `workflow_node`, `node_run`, and the versioned production assets.
2. Context Builder: first schema/service/API/UI slice exists for `context_build_plan`, `context_bundle`, token budget, asset ranking, compression preview, and actual-context replay; next work is manual curation and invalidation.
3. Versioned production chain: `outline_version`, `chapter_plan_version`, `draft_version`, and `generation_run` now exist; next work is chapter queue, invalidation warnings, and parameter dashboards.
4. Analysis Center upgrade: first schema/service/UI/handoff slice exists for web fiction, published fiction, classic literature, common analysis core, and analysis-to-asset conversion; next work is semantic scoring and richer conversion gates.
5. Long-form stability: `change_impact_report` first slice exists; next work is timeline, foreshadowing placement/payoff, relationship/faction/map/prop systems, and invalidation visualization.
6. AI Editor: paragraph suggestions, `editor_patch`, apply/rollback, diff replay.
7. Agent industrialization: `agent_contract`, `agent_run`, `agent_dispatch_queue`, event/checkpoint/budget/gate/metric/failure assets, Agent Scheduler tick/loop, Workflow resume handoff, and Production Control visibility exist; next work is broader real-service operation registry, rollback, and deeper Agent Center UI.
8. Reader feedback, publishing operations, and model evaluation centers.

## Key Docs

- [CLAUDE.md](CLAUDE.md)
- [AGENTS.md](AGENTS.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [WORKFLOW.md](WORKFLOW.md)
- [TESTING.md](TESTING.md)
- [System Architecture](docs/01-architecture/system-architecture.md)
- [Main Pipeline](docs/02-workflows/main-pipeline.md)
- [Testing Strategy](docs/05-testing/testing-strategy.md)
- [Skills System](docs/09-skills/README.md)
- [Agent Skill Map](docs/09-skills/agent-skill-map.md)
- [Claude Code Runtime Skill Sync](docs/09-skills/runtime-sync.md)
- [Skills Architecture](docs/01-architecture/skills-system.md)
- [Skill Usage Workflow](docs/02-workflows/skill-usage.md)

## Skills

V5 includes repository-level Skills under `skills/`. Skills capture reusable creative capabilities and quality gates; they do not store source text or copyrighted content.

Preview runtime mapping:

```bash
make sync-skills-dry-run
```

Sync repository Skills to `.claude/skills/` when Claude Code runtime integration is needed:

```bash
make sync-skills
```

## Current Implementation Scope

V5 keeps the Python standard-library core, dataclass schemas, local JSON storage, deterministic mock adapters, and `unittest` tests. Industrial services and real model providers are opt-in so local validation remains fast and dependency-light.

Do not document target platform features as completed until schema, service, API/UI, tests, and validation exist.
