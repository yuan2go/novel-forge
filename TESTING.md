# TESTING.md

## Purpose

Testing in Novel Forge must protect the platform contract, not only individual functions.

A change is not complete because a prompt, page, or service was added. It must preserve schema-backed assets, workflow/run records, copyright boundaries, provider fail-closed behavior, and local deterministic validation.

## Current Runner

v6 uses Python standard-library `unittest` for the executable core. Avoid adding test dependencies unless an ADR or explicit task approves the dependency policy.

## Required Commands

For most code, schema, workflow, or storage changes:

```bash
make lint
make test
make validate
```

For Skills changes:

```bash
make sync-skills-dry-run
make check-skills
```

For local production-style stack changes:

```bash
make local-smoke
```

For full local stack verification when relevant:

```bash
make local-up
make local-logs
make local-down
```

Do not claim tests passed if the commands were not run. State the exact command result or the reason verification could not be executed.

## Testing Layers

| Layer | What To Verify |
|---|---|
| Schema | common fields, asset type, metadata, references, validation errors |
| Storage | local JSON write/read, atomic backup, manifest, path safety |
| Workflow | task status, workflow run, failure recovery, dead letters, sample cleanup |
| Workflow runtime | DAG validation, ready-node queue, processor registry, gate pipeline, pause/resume/cancel, scheduler tick/loop, invalidation |
| Module service | deterministic input/output behavior and schema-backed asset write |
| Model adapter | mock determinism, provider fail-closed, strict JSON validation |
| Context | selected assets, exclusion rules, compression, token budget, actual-context replay |
| Production | outline/chapter-plan/draft versions, generation run trace, invalidation warnings |
| Review | quality/style/originality/chapter/continuity/platform reports and revision tasks |
| Editor | patch preview, diff, single/batch apply, rollback, new draft version |
| Agent | contract, checkpoint, budget, gate, metric, recovery, state transitions |
| Trace / Cost | span hierarchy, model call log, cost ledger, budget policy, cost alert, cost snapshots |
| Novel KG | ontology snapshot, query/path/impact/conflict, KG gate, continuity preflight |
| API | route contract, project scoping, error handling, no direct bypass of services |
| UI | critical flows through FastAPI, clear state, no hidden mutation |
| Infrastructure | Postgres sync, Qdrant index/search, MinIO sync, Celery task behavior |
| Compliance | rights metadata, source lineage, anti-copy abstraction, no raw source in draft context |

## Current Coverage Areas

Current tests should continue covering:

- schema common fields and review report shape;
- local storage read/write, atomic overwrite backup, and SQLite manifest;
- mock model adapter methods;
- provider adapter skeletons and fail-closed behavior;
- Claude Code manual handoff packet boundaries;
- CLI help and validation;
- Skills frontmatter, required sections, sync, and drift detection;
- external resource intake boundaries;
- source rights metadata on imports;
- ingestion including directory batch fixtures for `.txt`, `.md`, `.epub`, `.mobi`, and `.azw3`;
- EPUB OPF spine ordering and extraction metadata;
- cleaning, including OCR-style spacing noise, advertisement/watermark removal, repeated blank collapse, and chapter detection;
- decomposition, generation, review, revision;
- pipeline `TaskStatus` and failed `WorkflowRun` recording;
- run logs, recovery notes, and repeated sample cleanup;
- automatic sample workspace updates;
- local asset search and hybrid vector retrieval;
- feedback insight and workspace state shape validation;
- feedback trend metrics and multi-book workspace memory;
- end-to-end pipeline;
- long-project fixture pressure test with six chapters and workspace memory.

## Novel OS Test Requirements

As Novel OS platform work changes, keep or add tests for:

### 0. Novel OS Acceptance Chain

The OS end-to-end acceptance chain is not a full-novel generation test. P0 should use one project and one chapter-sized fixture to prove the operating layer works:

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

Full-novel generation is a later long-chain acceptance scenario for scale, continuity drift, quality drift, and cost control.

### 1. Context Builder

- `context_build_plan` schema validation;
- asset selection and exclusion;
- token budget accounting;
- compression preview;
- final `context_bundle` content;
- actual-context replay;
- guarantee that raw protected source text is not used in draft context.
- API routes for creating context plans and bundles.

### 2. Versioned Production Chain

- `outline_version` creation;
- `chapter_plan_version` creation;
- `draft_version` creation;
- `generation_run` metadata;
- draft version append-only behavior;
- API routes for production version records;
- upstream change invalidation;
- chapter queue behavior.

### 3. Analysis Center

- common analysis report schema;
- web fiction business analysis profile;
- published fiction craft analysis profile;
- classic literary depth analysis profile;
- analysis-to-asset conversion into materials, knowledge, templates, style profiles, and review rules;
- anti-copy abstraction gates.

### 4. AI Editor

- `editor_patch` schema;
- paragraph-level patch targeting;
- preview vs apply;
- single apply and batch apply;
- rollback;
- diff output;
- new draft version after apply.

### 5. Long-Form Stability

- timeline event creation;
- foreshadowing placement and payoff;
- relationship/faction/map/prop graph projections;
- `change_impact_report`;
- downstream invalidation when continuity changes.

### 6. Agent Scheduler

- `agent_contract` validation;
- `agent_run` state transitions through the scheduler;
- dispatch queue claim, lease, ack, retry, and dead-letter behavior;
- checkpoints;
- budget limits;
- gate results;
- metrics;
- failure and recovery;
- rerun creates a new record.

### 7. Trace And Cost Runtime

- trace span parent/child relationships across workflow, node, agent, gate, model, context, cost, and feedback spans;
- model call logs with provider, model, operation, usage, status, and trace ids;
- cost ledger writes from model calls and explicit cost events;
- budget policy checks before or during runtime execution;
- cost alerts on projected budget overrun;
- project, agent, and chapter cost snapshots;
- cost-quality dashboard aggregation.

### 8. Feedback and Publishing

- web feedback import;
- sentiment distribution;
- payoff/toxic-point clustering;
- role heat;
- retention/drop-off signals;
- feedback-to-revision-task loop;
- publishing plan/log;
- platform status;
- post-release data recovery.

### 9. Model Evaluation

- model profile;
- benchmark task;
- benchmark run;
- A/B comparison;
- cost-quality report;
- prompt regression;
- routing decision.

## Test Selection Rule

Run the smallest relevant test first, then run broader checks before claiming completion.

Examples:

- A schema-only change: targeted unittest for the schema, then `make validate`.
- A workflow change: targeted workflow test, then `make test`, `make validate`.
- A Skill change: targeted skill validation, then `make sync-skills-dry-run`, `make check-skills`.
- A Docker/API/UI change: route or smoke test, then `make local-smoke` when possible.

## No-Network Default

Default tests must not call external providers, external APIs, paid model endpoints, or remote databases.

Use:

- `MockModelAdapter`;
- `LocalRuleEngine`;
- local fixtures;
- dependency-gated optional tests;
- explicit environment variables for real provider smoke tests.

## Acceptance Language

Use precise test reporting:

```text
Verification:
- make lint: passed
- make test: passed
- make validate: passed
```

If not run:

```text
Verification not run: repository was not available in this environment.
```

Do not write "should pass" as if it passed.
