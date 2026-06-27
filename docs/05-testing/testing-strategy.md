# Testing Strategy

## Purpose

Testing in Novel Forge must protect platform contracts, not only isolated functions.

A change is complete only when schema-backed assets, workflow/run records, copyright boundaries, provider behavior, and local deterministic validation remain safe.

## Current Runner

V5 uses Python stdlib `unittest` because dependency installation is intentionally avoided during rebuild. Do not introduce pytest or other test dependencies without an ADR or explicit task.

## Commands

```bash
make test
make lint
make validate
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
- Stricter semantic validation for feedback insight and workspace state shapes.
- Feedback trend metrics and multi-book workspace memory.
- End-to-end pipeline.
- Long-project fixture pressure test with six chapters and workspace memory.

## Platform Migration Test Requirements

### Context Builder

Future `context_build_plan` and `context_bundle` work must test:

- schema validation;
- selected asset list;
- exclusion rules;
- token budget accounting;
- compression preview;
- actual sent context replay;
- prevention of raw protected source text entering draft context.

### Versioned Production Chain

Future outline/chapter/draft versioning must test:

- `outline_version` creation;
- `chapter_plan_version` creation;
- `generation_run` metadata;
- append-only draft versions;
- upstream change invalidation;
- chapter queue behavior;
- generation parameter trace.

### Analysis Center

Future Analysis Center work must test:

- common novel analysis schema;
- web fiction business analysis profile;
- published fiction craft analysis profile;
- classic literary depth analysis profile;
- analysis-to-asset conversion into knowledge, materials, templates, style profiles, and review rules;
- anti-copy abstraction gates and source lineage.

### AI Editor

Future editor work must test:

- `editor_patch` schema;
- paragraph-level suggestions;
- preview and apply separation;
- single and batch apply;
- diff output;
- rollback;
- new draft version after apply.

### Long-Form Stability

Future stability work must test:

- timeline events;
- foreshadowing placement and payoff;
- relationship/faction/map/prop projections;
- `change_impact_report`;
- downstream invalidation when continuity changes.

### Agent Industrialization

Future Agent work must test:

- `agent_contract` validation;
- `agent_run` state transitions;
- checkpoint creation;
- budget limit enforcement;
- gate result recording;
- metric recording;
- failure and recovery;
- rerun creating a new record.

### Feedback, Publishing, Model Evaluation

Future product centers must test:

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

## Future ADR

Introduce pytest only after dependency policy is approved.
