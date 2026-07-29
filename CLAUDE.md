# CLAUDE.md

This is the long-lived operating manual for Claude Code, Codex, and other coding agents working in this repository.

Autonomous Novel OS is the product target: a local-first operating system for long-term, low-manual-intervention, quality-gated premium web-novel production. The repository, package, and CLI remain `novel-forge` / Novel Forge v6 until a dedicated rename migration is approved.

The current stage priority is v1 single-book production closure:

```text
topic -> world -> characters -> outline -> chapter plan
-> draft -> review -> revision -> canon update -> longform recap -> export
```

Do not skip v1 in favor of broader multi-book, SaaS, or platform automation work unless the task explicitly requires it.

## Source Of Truth

Code is the truth source. Old docs are historical intent until verified against current files.

When making architecture, product, roadmap, or implementation claims, check the relevant evidence first:

- source code under `src/novel_forge/`;
- schemas under `src/novel_forge/schemas/`;
- CLI entrypoint `src/novel_forge/cli.py`;
- API entrypoint `src/novel_forge/api/app.py` and routers under `src/novel_forge/api/routers/`;
- UI routes under `web/admin/app/`;
- tests under `tests/`;
- scripts, Makefile, `pyproject.toml`, `docker-compose.yml`, and package manifests;
- root `skills/` and generated `.claude/skills/`;
- current docs entrypoint `docs/README.md` and state report `docs/project-current-state.md`.

Do not write planned capabilities as completed. Use these status labels when documenting: implemented, partially implemented, design-only, not implemented, deprecated, or unknown.

## Project Mission

Autonomous Novel OS is not a one-off prompt generator. It is a platform for controlled, traceable, long-form fiction production.

The platform cares about:

- hot novel, published fiction, and classic literature deconstruction;
- mystery/suspense reading and craft analysis;
- genre, material, knowledge, template, style, and quality-standard libraries;
- topic, worldbuilding, character, outline, chapter plan, draft, review, revision, and feedback workflows;
- long-form stability, Canon, arcs, foreshadowing, character continuity, and villain operations;
- Context Builder, RAG, OS Envelope, ReviewIssue, Release Package, Quality Gate, Eval Center, Loop Engineering, Agent Center, and MKAOS;
- reader feedback loops, platform strategy, publishing gates, export/release readiness, and operational rollback.

## Content Types

Keep these categories separate in analysis, docs, schemas, and generated assets:

- material;
- deconstruction;
- genre;
- worldbuilding;
- character;
- outline;
- chapter plan;
- draft prose;
- review;
- feedback;
- training exercise;
- reusable template;
- engineering implementation;
- test evidence;
- roadmap.

Never mix raw source text with generated drafts. Reference works may be used only for abstract structural learning.

## Current Engineering State

The current verified code baseline is Novel Forge v6; the product target is Autonomous Novel OS. Important evidence paths:

- version/runtime: `pyproject.toml`, `src/novel_forge/__init__.py`, `src/novel_forge/api/app.py`;
- schema-backed assets: `src/novel_forge/schemas/assets.py`;
- CLI: `src/novel_forge/cli.py`;
- local workflow core: `src/novel_forge/workflows/`, `src/novel_forge/modules/`;
- product API: `src/novel_forge/api/`, especially `src/novel_forge/api/routers/__init__.py`;
- Web console: `web/admin/app/`;
- tests: `tests/unit/`, `tests/integration/`, `tests/acceptance/`;
- runtime skill source: root `skills/`; generated runtime copies: `.claude/skills/`.

Current blueprint control reports:

- `docs/reports/blueprint-gap-audit.md`;
- `docs/reports/module-maturity-matrix.md`;
- `docs/reports/data-model-gap-matrix.md`;
- `docs/reports/v1-v7-roadmap.md`;
- `docs/reports/next-production-slices.md`.

Use these reports to choose the next production-grade slice. They do not replace code evidence.

Implemented or substantially implemented:

- standard-library Python core with dataclass-like schemas and local JSON storage;
- CLI pipeline from source intake through feedback insight;
- FastAPI product API with many product/OS/MKAOS routers;
- Next.js admin console with pages for projects, assets, analysis, context, production, review, editor, quality, feedback, OS runtime, agent dispatch, KG, cost, trace, and MKAOS;
- optional Docker local stack for PostgreSQL, Redis/Celery, Qdrant, MinIO, FastAPI, worker, and Web;
- skills source/runtime sync tooling;
- MKAOS ingestion, quality, lineage, graph/pack/gate, and production integration slices;
- Context Builder, RAG/local vector/Qdrant/pgvector slices;
- ReviewIssue, revision task, editor patch, publishing gate, release package, and quality gate slices;
- Agent registry/scheduler first slices with operations, queue lifecycle, runner seams, retry, recovery, rollback, and dead-letter behavior;
- OS acceptance, long-chain, MKAOS, provider guard, publishing, and scheduler tests.
- PostgreSQL Book-to-Chapter coordination through the Chapter Authority command
  port, plus governed Reader Outcome and Long-form Recap operation slices. Their
  current proof uses scripted Provider/PostgreSQL integration and is not real
  Provider or sustained production proof.

Partially implemented and must not be overclaimed:

- complete autonomous Agent Center product;
- universal provider/model-call hard-stop coverage across every model-producing path;
- fully productized Eval Center and cost-quality routing;
- business-grade rollback for all multi-asset workflows;
- full publishing calendar/platform adapter operations;
- production-scale database-backed execution and distributed concurrency;
- full long-novel generation without operator intervention.

## Agent And Workflow Contract

Agents are roles and permission boundaries. Skills are reusable capabilities. Model adapters are execution interfaces.

Every production-grade Agent operation should have:

- operation registration;
- input schema and bounded context;
- OS Envelope or equivalent runtime evidence;
- provider/model-call policy evidence when a model is used;
- checkpoint, budget/SLA, gate, metric, trace, and cost records when applicable;
- versioned output artifact;
- recovery, retry, rollback, and dead-letter behavior for scheduled work;
- tests or a documented verification path.

Do not claim a complete autonomous Agent Center exists until operation coverage, UI depth, production hard-stop behavior, business rollback, and end-to-end OS acceptance are all demonstrated.

## Development Workflow

For each task:

1. Read this file.
2. Read `docs/README.md`.
3. Read `docs/project-current-state.md`.
4. Inspect the relevant code, tests, commands, and docs before deciding.
5. Make the smallest safe change that satisfies the task.
6. Run the smallest meaningful verification, plus broader tests when risk justifies it.
7. Update docs and reports when behavior, public contracts, architecture, or roadmap changes.

For large work, write a short plan before editing. For uncertain implementation state, say "not found in current code" or "partially implemented" and include evidence paths.

## Engineering Rules

- Prefer existing module patterns over new parallel architecture.
- Keep public CLI/API/schema contracts compatible unless the task explicitly asks for a breaking change.
- Do not delete historical docs; mark them historical or archive-index them.
- Do not edit `.claude/skills/` as source of truth. Change root `skills/`, then run `make sync-skills-dry-run` and `make sync-skills` when runtime copies need updating.
- Do not add external dependencies without explicit need and a dependency/security rationale.
- Do not bypass OS Envelope, Context Builder, Canon/KG, ReviewIssue, provider runtime policy, or publish/release gates for production paths.
- Do not hide test failures. Record failing commands and the next fix.
- Do not use mock/fallback behavior as proof of production readiness.
- Do not scatter durable prompts through unrelated service code; use Skill, prompt registry, module service, or workflow-node boundaries when appropriate.
- In production-like environments, submit Book/Chapter/Reader Outcome/Long-form
  changes through PostgreSQL Authority commands. `LocalStorage`, the Legacy
  Chapter Bus, legacy Recap, and fixture Book Authority are not production
  mutation paths.

## Copyright Boundary

Allowed from reference works:

- structure;
- rhythm;
- conflict mechanism;
- character mechanism;
- emotion curve;
- hook pattern;
- commercial readability logic;
- abstract craft technique.

Forbidden:

- original sentences or distinctive expression;
- protected characters, settings, scenes, and plot combinations;
- raw source text inside generated drafts;
- decomposition/analysis text treated as draft prose;
- direct imitation of a named work.

Reference-derived assets must preserve lineage and remain abstract.

## Skills Rules

Claude Code may select useful local Skills for engineering, creative, review, or governance tasks, but Skills never replace code evidence or project rules.

Rules:

- root `skills/` is the project source of truth;
- `.claude/skills/` is generated runtime output;
- use `make sync-skills-dry-run` before `make sync-skills`;
- use `docs/09-skills/agent-skill-map.md` for Agent-to-Skill selection;
- install new Skills only from trusted sources after reading `SKILL.md` and checking shell, network, credential, deletion, and upload risks;
- record Skill adoption or risk in the relevant report when it affects the project;
- Skill outputs must still pass schemas, storage boundaries, provider boundaries, copyright boundaries, and review gates.

## Repository Map

```text
src/novel_forge/          Python package: CLI, API, schemas, modules, workflows, storage
src/novel_forge/modules/  domain/application services and OS runtime modules
src/novel_forge/api/      FastAPI app, routers, product API service layer
web/admin/                Next.js admin console
tests/                    unit, integration, acceptance, fixtures
skills/                   project Skill source of truth
.claude/skills/           generated runtime Skill copies plus external runtime Skills
docs/                     current docs, architecture, reports, historical plans
scripts/                  local operations, validation, sync, smoke, data scripts
examples/                 deterministic sample inputs and outputs
data/                     ignored/generated local asset tree
.local/workspace/         ignored runtime workspace for local runs
```

## Common Commands

Use `PYTHONPATH=src` when running modules directly from the checkout.

```bash
make test                    # Python unittest suite + web admin node tests
make lint                    # Python compile check
make validate                # validate the local workspace structure and assets
make demo                    # run sample local pipeline
make sync-skills-dry-run     # preview root skills -> .claude/skills drift
make sync-skills             # update runtime Skill copies
make check-skills            # fail on Skill drift
make local-up                # Docker local production-style stack
make local-smoke             # local stack smoke test
make local-down              # stop stack
make api                     # FastAPI backend on local workspace
make worker                  # Celery worker on local workspace
make web-dev                 # Next.js dev console
PYTHONPATH=src python3 -m novel_forge.cli --help
PYTHONPATH=src python3 -m novel_forge.cli validate --root .local/workspace
npm --prefix web/admin test
npm --prefix web/admin run lint
```

Optional provider and browser smoke commands may require local secrets, installed browsers, or Docker services. Mark skipped or unavailable checks explicitly.

## Completion Standard

An Agent task is complete only when the smallest relevant verification exists:

- docs-only: consistency check against current code paths and current docs index;
- schema/code: tests plus validation;
- workflow changes: node status, recovery, retry, and artifact checks;
- scheduler changes: dispatch queue, lease, checkpoint, gate, budget/SLA, retry/dead-letter, and recovery checks;
- Skill changes: dry-run drift check;
- UI changes: route-level smoke or component/API tests when possible;
- production content: review report and quality gate result.

When verification is not possible in the current environment, record the exact blocker and the next command to run.
