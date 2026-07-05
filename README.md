# Novel Forge v6

Novel Forge v6 is a local-first AI novel production platform and early Novel Operating System runtime.

It is not an AI chapter generator. It is designed to turn source materials, abstracted reference analysis, multidisciplinary knowledge, reusable creative assets, context bundles, review reports, revision tasks, reader feedback, publishing gates, workflow runs, agent runs, trace spans, and cost ledgers into a controlled long-form fiction production workflow.

Internal architecture vision: Novel Operating System.

Repository/package/CLI name remains `novel-forge` in v6. Novel Operating System is the architecture target, not an approved repository/package rename, unless a separate migration task approves repository, package, command, path, and documentation changes.

Core executable pipeline:

```text
source material -> cleaned text -> decomposition -> knowledge/material assets -> topic -> world -> characters -> outline -> chapter plan -> draft -> review -> revision -> feedback insight
```

Target platform pipeline:

```text
project strategy -> analysis center -> context build plan -> context bundle -> versioned outline/chapter-plan/draft -> review pipeline -> editor patch/revision task -> continuity/publish gates -> publishing/feedback analytics -> next planning loop
```

Novel Operating System acceptance chain:

```text
project fixture
  -> WorkflowDefinition
  -> execute_workflow
  -> workflow / agent scheduler tick or loop
  -> context bundle
  -> model call through the runtime boundary
  -> node_run / agent_run
  -> trace_span / gate_result / model_call_log / cost_ledger
  -> Novel KG gate / continuity preflight
  -> review_issue -> revision_task -> editor_patch -> draft_version
  -> re-review -> publish_gate
  -> invalidation / resume
  -> cost_quality_dashboard / acceptance report
```

This OS acceptance chain is not the same thing as generating a complete long novel. The P0 acceptance target is a minimal vertical slice, usually one project and one chapter-sized fixture, that proves workflow, agent dispatch, KG gates, trace, cost, review rework, invalidation, and resume all run through the same operating layer. Full-novel generation is a slower long-chain acceptance scenario after the runtime is stable.

## Principles

- Extract structure, rhythm, hooks, conflict mechanics, emotional curves, craft technique, and commercial logic from reference works.
- Do not copy original expression, character combinations, settings, scenes, or plot sequences from copyrighted works.
- Keep raw sources, decomposition/analysis reports, generated assets, drafts, reviews, publishing assets, feedback, and runs in separate directories.
- Treat prompts as node execution parameters, not the product architecture.
- Prefer workflow nodes, schema-backed artifacts, context replay, versioning, and quality gates.
- Use deterministic mock adapters for tests; production agent model calls default to the local Claude Code Codex worker, and external OpenAI-compatible providers are opt-in through environment variables.

## Quick Start

```bash
make test
make validate
make demo
PYTHONPATH=src python3 -m novel_forge.cli --help
```

Core Novel OS validation:

```bash
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_acceptance
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_smoke
npm --prefix web/admin test
npm --prefix web/admin run lint
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

Agent model calls default to the local Claude Code runtime backed by Codex CLI:

```bash
CODEX_HOME=~/.codex-claude codex exec ...
```

To call a real OpenAI-compatible provider instead, set a provider and API key before running API, worker, or CLI commands:

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

The deterministic offline adapter is still available for tests and demos:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=mock
```

Ordinary Codex can also be used as an explicit local worker:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=codex
export NOVEL_FORGE_CODEX_CLI_ENABLED=1
```

The default Claude Code runtime can be reselected explicitly with:

```bash
export NOVEL_FORGE_MODEL_PROVIDER=claude-code
```

Both local workers run `codex exec` non-interactively with JSON output schema validation and `read-only` sandbox by default.

## Core Commands

```bash
PYTHONPATH=src python3 -m novel_forge.cli init
PYTHONPATH=src python3 -m novel_forge.cli ingest examples/sample_inputs/sample_novel.txt
PYTHONPATH=src python3 -m novel_forge.cli clean --input data/raw/<file>.json
PYTHONPATH=src python3 -m novel_forge.cli decompose --input data/cleaned/<file>.json
PYTHONPATH=src python3 -m novel_forge.cli extract-knowledge --input data/decompositions/<file>.json
PYTHONPATH=src python3 -m novel_forge.cli build-materials
PYTHONPATH=src python3 -m novel_forge.cli generate-topic
PYTHONPATH=src python3 -m novel_forge.cli topic-development
PYTHONPATH=src python3 -m novel_forge.cli training-exercise
PYTHONPATH=src python3 -m novel_forge.cli generate-world
PYTHONPATH=src python3 -m novel_forge.cli generate-characters
PYTHONPATH=src python3 -m novel_forge.cli generate-outline
PYTHONPATH=src python3 -m novel_forge.cli generate-chapter-plan
PYTHONPATH=src python3 -m novel_forge.cli draft
PYTHONPATH=src python3 -m novel_forge.cli review --input data/drafts/<file>.json
PYTHONPATH=src python3 -m novel_forge.cli compare-reviews --input data/drafts/<file>.json
PYTHONPATH=src python3 -m novel_forge.cli revise --input data/reviews/<file>.json
PYTHONPATH=src python3 -m novel_forge.cli import-feedback examples/sample_inputs/sample_feedback.csv
PYTHONPATH=src python3 -m novel_forge.cli analyze-feedback
PYTHONPATH=src python3 -m novel_forge.cli claude-deconstruct
PYTHONPATH=src python3 -m novel_forge.cli claude-knowledge
PYTHONPATH=src python3 -m novel_forge.cli build-index
PYTHONPATH=src python3 -m novel_forge.cli search
PYTHONPATH=src python3 -m novel_forge.cli build-vector-index
PYTHONPATH=src python3 -m novel_forge.cli vector-search --query "..."
PYTHONPATH=src python3 -m novel_forge.cli qdrant-index
PYTHONPATH=src python3 -m novel_forge.cli qdrant-search --query "..."
PYTHONPATH=src python3 -m novel_forge.cli minio-sync
PYTHONPATH=src python3 -m novel_forge.cli init-workspace
PYTHONPATH=src python3 -m novel_forge.cli workspace-status
PYTHONPATH=src python3 -m novel_forge.cli run-pipeline --sample
PYTHONPATH=src python3 -m novel_forge.cli industrial-status
PYTHONPATH=src python3 -m novel_forge.cli status
PYTHONPATH=src python3 -m novel_forge.cli validate
```

These commands default to the current directory unless `NOVEL_FORGE_ROOT` is set. If the package is installed, the shorter `novel-forge ...` console script is also available. For production-style local use, prefer `NOVEL_FORGE_ROOT=.local/workspace` or explicit `--root .local/workspace`.

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

## Novel OS Runtime Priorities

Current P0/P1 closure status:

1. Universal Runtime Policy now has strict/compat checks, `RuntimePolicyEnvelope`, KG-context requirements, enforcement reporting, zero review-required legacy entrypoint audit, guarded model-call logging, and budget/gate/cost evidence checks.
2. Provider runtime guard now normalizes usage, emits runtime events, supports OpenAI-compatible SSE and SDK streaming usage, streaming token cutoff, request/process cancel and timeout checks, polling-based live cancel for local Codex/Claude Code workers, provider guard gate results, and failed model-call evidence.
3. Checkpoint and rollback now have durable stage checkpoints, GuardedModelAdapter/ModelGateway prompt-provider-output checkpoints, raw provider output segments, validation-stage resume plans, resume chains, rollback transactions/plans/results, version-restore and physical multi-asset rollback actions, two-phase coordinated rollback, ledger compensation, dirty-index markers, preview/apply/verify/coordinate APIs, and rollback verification.
4. Semantic quality now includes Novel KG evidence/confidence, model-assisted extraction validation, identity merge queues, KG-backed context propagation from context plan to bundle, continuity/KG gates, and feedback-to-plan backflow first slice.
5. Web OS operations now expose workflow, agent, KG, trace, cost, invalidation, review-rework, runtime policy coverage, legacy bypass audit, DAG graph, Agent timeline, KG relation table, cost trend, rollback preview/apply/verify/coordinate, KG identity queues, fixture-backed Playwright cockpit smoke, opt-in CI Chromium smoke, and opt-in long-chain 12/50 chapter pressure acceptance.
6. P1/P2 OS capabilities now include ModelRouter/ModelGateway, PromptRegistry, ToolGateway with HTTP JSON-RPC MCP discovery/invocation, StateBus, AgentMessageBus, L0-L5 memory, pgvector-first Context Builder retrieval, pgvector schema/capability planning plus online PostgreSQL/pgvector sync/query/migration dry-run and operations plan, deterministic local embedding projection, Qdrant as an optional high-performance vector service, `/product/os/*` APIs, and Workflow/Agent operation contracts for these services.
7. Reference intake now detects common Chinese text encodings such as GB18030/GBK, and `analyze-reference` creates abstract web-fiction analysis reports with oral-performance style signals while preserving the no-copy boundary.
8. Context Builder now records policy rejections in bundles and RAG quality reports, so manually selected raw sources, analysis reports, or high-risk assets are blocked with auditable reasons instead of silently entering generation context.

## Key Docs

- [CLAUDE.md](CLAUDE.md)
- [AGENTS.md](AGENTS.md)
- [Docs Index](docs/README.md)
- [Current Project State](docs/project-current-state.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Module Map](docs/architecture/module-map.md)
- [Capability Map](docs/product/capability-map.md)
- [Extension Guide](docs/engineering/extension-guide.md)
- [Regression Tests](docs/quality/regression-tests.md)
- [Current Roadmap](docs/roadmap/current-roadmap.md)
- [Novel Operating System Target](docs/00-product/novel-operating-system.md)
- [Novel OS New Capabilities](docs/architecture/novel-operating-system-new-capabilities.md)
- [Novel OS Remaining Closure Plan](docs/08-roadmap/novel-os-remaining-closure-plan.md)
- [System Architecture](docs/01-architecture/system-architecture.md)
- [Main Pipeline](docs/02-workflows/main-pipeline.md)
- [Testing Strategy](docs/05-testing/testing-strategy.md)
- [Skills System](docs/09-skills/README.md)
- [Agent Skill Map](docs/09-skills/agent-skill-map.md)
- [Claude Code Runtime Skill Sync](docs/09-skills/runtime-sync.md)
- [Skills Architecture](docs/01-architecture/skills-system.md)
- [Skill Usage Workflow](docs/02-workflows/skill-usage.md)

## Skills

v6 includes repository-level Skills under `skills/`. Skills capture reusable creative capabilities and quality gates; they do not store source text or copyrighted content.

Preview runtime mapping:

```bash
make sync-skills-dry-run
```

Sync repository Skills to `.claude/skills/` when Claude Code runtime integration is needed:

```bash
make sync-skills
```

## Current Implementation Scope

v6 keeps the Python standard-library core, dataclass schemas, local JSON storage, deterministic mock adapters, and `unittest` tests. Industrial services and external real model providers are opt-in so local validation remains fast and dependency-light; the default production agent boundary is the local Claude Code Codex worker.

Do not document target platform features as completed until schema, service, API/UI, tests, and validation exist.
