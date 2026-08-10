# Testing Strategy

## Purpose

Testing in Novel Forge must protect platform contracts, not only isolated functions.

A change is complete only when schema-backed assets, workflow/run records, copyright boundaries, provider behavior, and local deterministic validation remain safe.

## Current Runner

Pytest is the canonical Python runner. Existing `unittest.TestCase` suites remain
supported because pytest collects them. Required test modules must collect at
least one test; a tracked file or unittest discovery of zero cases is not evidence.

## Commands

```bash
make test
make lint
make validate
make authority-test
make postgres-authority-test
make authority-compose-config-check
make authority-smoke
npm --prefix web/admin test
make demo
make sync-skills-dry-run
make check-skills
```

`make demo` writes generated runtime assets to `.local/demo-workspace/`, which is ignored by Git. Deterministic fixtures are limited to `examples/sample_inputs/` and `tests/fixtures/`; generated `data/` assets and `examples/sample_outputs/` are runtime state.

For local production-style stack changes, use the smallest relevant Docker verification and `make local-smoke` when possible.

## Current Coverage Areas

- Schema common fields and review report shape.
- Local storage read/write.
- Local storage atomic overwrite backup and SQLite manifest.
- Mock model adapter methods.
- Provider adapter contract skeletons and fail-closed behavior.
- Provider runtime guard streaming paths, including OpenAI-compatible SSE/SDK usage events, live token cutoff, timeout/cancel evidence, and failed model-call logs.
- Claude Code manual handoff packet boundaries.
- CLI help and validation.
- Skills frontmatter and required sections.
- Skills runtime sync dry-run, copy behavior, and drift detection.
- External Claude Code resource intake command boundaries and import-decision sections.
- Source rights metadata validation on imported materials.
- Ingest, including directory batch fixtures for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3`.
- EPUB OPF spine ordering and extraction metadata.
- Clean, including OCR-style spacing noise, advertisement/watermark removal, repeated blank collapse, and chapter detection.
- Decompose, generation, review, revision.
- Pipeline TaskStatus and failed WorkflowRun recording.
- Pipeline run logs, recovery notes, and repeated sample cleanup.
- Automatic sample workspace updates during pipeline execution.
- Local asset search by category, type, tag, and keyword.
- Hybrid local vector retrieval with BM25-style lexical score and Chinese token features.
- Optional online pgvector sync/query using fake `psycopg` fixtures by default and real PostgreSQL/pgvector only in explicit local production smoke.
- Stricter semantic validation for feedback insight and workspace state shapes.
- Feedback trend metrics and multi-book workspace memory.
- End-to-end pipeline.
- Long-project fixture pressure test with six chapters and workspace memory.
- ToolGateway internal and HTTP JSON-RPC MCP discovery/invocation paths.
- Operation rollback preview/apply/verify, including logical rollback, previous-version restore, physical quarantine/restore, ledger compensation, and dirty-index markers.

## Novel OS Test Requirements

### Novel OS Acceptance Chain

The Novel Operating System end-to-end acceptance chain is not a full-novel generation test. It is the smallest complete vertical slice that proves the runtime can coordinate production through durable artifacts.

The P0 fixture should cover one project and one chapter-sized production target:

- `WorkflowDefinition` creation and DAG validation;
- workflow execution through the runtime state machine;
- ready-node queue claim/ack or controlled blocking;
- Agent dispatch queue materialization and scheduler tick/loop;
- context bundle or explicit fixture context;
- model call through the configured runtime boundary or deterministic mock adapter;
- `node_run`, `agent_run`, checkpoint, and recovery records;
- `trace_span`, `gate_result`, `model_call_log`, and `cost_ledger` evidence;
- Novel KG gate and continuity preflight;
- `review_issue -> revision_task -> editor_patch -> draft_version`;
- re-review and publish gate;
- downstream invalidation after an upstream change;
- resume from blocked or failed state;
- cost-quality dashboard or acceptance report.

Full-novel generation belongs to later long-chain acceptance. It should test continuity over many chapters, cost drift, quality drift, and editorial throughput after the P0 runtime chain is stable.

### Canonical Book vertical proof

Book production changes must run through the same composition builders used by
the Authority API and Book Worker. A test-local hand-built Supervisor is not
production evidence. The PostgreSQL two-chapter proof covers both:

- No-Replan: resolved admission through Chapter 1 acceptance, Reader/Recap, and
  Chapter 2 admission/execution.
- Explicit Replan: candidate/proposal creation, durable `APPROVAL_PENDING`,
  restart-safe waiting, formal Authority API approval, Plan activation, new
  input snapshot, Book resume, and Chapter 2 admission/execution.

The integration suite also retains retry, restart/resume, lease/fence, and
UNKNOWN ExternalEffect recovery coverage. Deterministic Provider results make
this fixture integration evidence, not real-provider or long-form proof.

### Context Builder

Context Builder changes must continue testing:

- schema validation;
- selected asset list;
- exclusion rules;
- token budget accounting;
- compression preview;
- actual sent context replay;
- prevention of raw protected source text entering draft context;
- policy rejection evidence when manual source selection requests raw sources, analysis reports, explicit `use_in_generation_rag=false` assets, or high-risk copyrighted material.

### Versioned Production Chain

Versioned production chain changes must continue testing:

- `outline_version` creation;
- `chapter_plan_version` creation;
- `generation_run` metadata;
- append-only draft versions;
- upstream change invalidation;
- chapter queue behavior;
- generation parameter trace.

### Analysis Center

Analysis Center changes must continue testing:

- common novel analysis schema;
- web fiction business analysis profile;
- published fiction craft analysis profile;
- classic literary depth analysis profile;
- analysis-to-asset conversion into knowledge, materials, templates, style profiles, and review rules;
- anti-copy abstraction gates and source lineage.

### AI Editor

AI Editor changes must continue testing:

- `editor_patch` schema;
- paragraph-level suggestions;
- preview and apply separation;
- single and batch apply;
- diff output;
- rollback;
- new draft version after apply.

### Long-Form Stability

Long-form stability changes must continue testing:

- timeline events;
- foreshadowing placement and payoff;
- relationship/faction/map/prop projections;
- `change_impact_report`;
- downstream invalidation when continuity changes.

### Agent Scheduler

Agent Scheduler work must test:

- `agent_contract` validation;
- `agent_run` state transitions through the scheduler;
- dispatch queue claim, lease, ack, retry, and dead-letter behavior;
- checkpoint creation;
- budget limit enforcement;
- gate result recording;
- metric recording;
- failure and recovery;
- rerun creating a new record.

### Trace And Cost Runtime

Runtime observability and cost work must test:

- parent/child trace span relationships across workflow, node, agent, gate, model, and cost spans;
- model call logs with provider, model, operation, usage, status, and trace ids;
- cost ledger writes from model calls and explicit cost events;
- budget policy checks before or during runtime execution;
- cost alerts on projected budget overrun;
- project, agent, and chapter cost snapshots;
- cost-quality dashboard aggregation.

### Remote Tools And Retrieval

Tool and retrieval runtime changes must continue testing:

- MCP server registration without granting broad local execution privileges;
- `tools/list` discovery through HTTP JSON-RPC;
- `tools/call` invocation with `tool_invocation` and `trace_span` evidence;
- remote-call failure capture without corrupting local assets;
- pgvector online upsert/query when `NOVEL_FORGE_PGVECTOR_ONLINE=1`;
- strict pgvector failure behavior when `NOVEL_FORGE_PGVECTOR_STRICT=1`;
- local vector fallback when optional PostgreSQL/pgvector dependencies are absent.

### Browser Cockpit Smoke

Web OS cockpit changes must continue testing:

- route/API contract coverage in `npm --prefix web/admin test`;
- optional Playwright route smoke when Playwright is installed;
- optional live backend fixture checks through `NOVEL_FORGE_API_BASE_URL`;
- strict browser smoke with `NOVEL_FORGE_REQUIRE_PLAYWRIGHT=1` only when browser dependencies and a backend are available.

### Feedback, Publishing, Model Evaluation

Feedback, publishing, and model-evaluation changes must continue testing:

- web feedback import;
- sentiment distribution;
- payoff/toxic-point clustering;
- role heat;
- retention/drop-off signals;
- feedback-to-revision-task loop;
- publishing plan/log;
- platform status;
- post-release data recovery;
- model profile, benchmark task, benchmark run, A/B comparison, cost-quality report, prompt regression, and routing decision.

## Test Selection Rule

Run the smallest relevant test first, then run broader checks before claiming completion.

Examples:

- Schema-only change: targeted unittest, then `make validate`.
- Workflow change: targeted workflow test, then `make test`, `make validate`.
- Skill change: targeted validation, then `make sync-skills-dry-run`, `make check-skills`.
- Docker/API/UI change: route or smoke test, then `make local-smoke` when possible.

## No-Network Default

Default tests must not call external providers, paid model endpoints, or remote services.

Use deterministic local paths:

- `MockModelAdapter`;
- `LocalRuleEngine`;
- local fixtures;
- dependency-gated optional adapters;
- explicit environment variables for real provider smoke tests.

## Reporting Standard

Before claiming completion, state exact verification:

```text
Verification:
- make lint: passed
- make test: passed
- make validate: passed
```

If verification was not possible, state why. Do not imply unrun tests passed.
