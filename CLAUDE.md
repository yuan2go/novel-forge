# CLAUDE.md

This file defines project-level operating rules for Claude Code, Codex, and other coding agents working in Novel Forge V5.

It incorporates the practical coding discipline from `multica-ai/andrej-karpathy-skills` and adapts it to this repository's fiction-production, schema, workflow, and compliance boundaries.

## Project Goal

Novel Forge V5 is an industrialized AI writing system for long-term novel production.

It turns source materials, abstracted reference analysis, multidisciplinary knowledge, reusable material cards, and reader feedback into controlled fiction outputs.

The system is not a one-off chapter generator. It is a file-based production factory for:

- Source ingestion.
- Text cleaning.
- Abstract decomposition.
- Knowledge and material curation.
- Topic, world, character, outline, chapter plan, draft, review, revision, and feedback workflows.
- Reusable Skills, schemas, tests, progress logs, and acceptance records.

## Current Architecture

- Python 3.11+.
- CLI-first workflow.
- Markdown and JSON local assets.
- Dataclass schemas in `src/novel_forge/schemas/`.
- Local filesystem storage in `data/`.
- Workflow orchestration in `src/novel_forge/workflows/`.
- Module service logic in `src/novel_forge/modules/<module>/service.py`.
- Reusable creative capabilities in root `skills/`.
- Mock model adapter and local rule engine for tests.
- Provider adapter skeletons that fail closed until real implementations are approved.
- No external API calls in tests.

## Operating Discipline

These rules bias toward clarity and caution over speed. For trivial tasks, use judgment, but do not skip verification for code changes.

### 1. Think Before Coding

Do not assume. Do not hide confusion. Surface tradeoffs early.

Before implementing:

- State important assumptions if they affect design, safety, data, or tests.
- If multiple interpretations exist, choose the safest reasonable one and explain the tradeoff.
- If a simpler approach exists, prefer it and avoid speculative architecture.
- If something is unclear and a wrong assumption could damage data or architecture, stop and ask.

### 2. Simplicity First

Use the minimum code that solves the current verified problem.

- Do not add features beyond the task.
- Do not create abstractions for single-use code.
- Do not add configurability that is not needed now.
- Do not add external dependencies unless an ADR or explicit user instruction requires it.
- If a small local function is enough, do not introduce a framework.

### 3. Surgical Changes

Touch only what the task requires.

- Do not refactor unrelated files.
- Do not reformat unrelated code.
- Match existing style and naming.
- Clean up imports, variables, and helper functions made unused by your own changes.
- If you notice unrelated dead code or risk, mention it instead of deleting it.

Every changed line should trace to the current task, a failing test, a validation rule, or a documented acceptance criterion.

### 4. Goal-Driven Execution

Transform tasks into verifiable goals:

- "Add validation" means add a failing or meaningful test, implement validation, then make tests pass.
- "Fix a bug" means reproduce the bug or identify concrete evidence, fix it, then verify it.
- "Refactor" means preserve behavior, keep public contracts stable, and run tests before claiming completion.

For multi-step work, use a short plan:

```text
1. Step -> verify: check
2. Step -> verify: check
3. Step -> verify: check
```

Do not treat "code written" as "task complete". Completion requires verification.

## Agent Responsibilities

- Claude Code: product owner, project editor, workflow controller, audit owner.
- Codex: engineering editor, code implementation, tests, CLI, schema consistency.
- ChatGPT: advanced reviewer, multidisciplinary synthesis, commercial logic review.
- DeepSeek: future long-form draft producer behind a model adapter.
- MockModel: deterministic test adapter only.
- LocalRuleEngine: schema and quality rule checks.

Agents are roles and permission boundaries. Skills are reusable capabilities. Model adapters are execution interfaces.

## Skills Rules

Skills are reusable capabilities, not Agent roles, knowledge assets, templates, executable tools, or storage locations.

- Root `skills/` is the project source of truth.
- `.claude/skills/` is runtime output only and must be generated from root `skills/`.
- Use `make sync-skills-dry-run` before `make sync-skills`.
- Use `docs/09-skills/agent-skill-map.md` to select Skills by Agent role.
- Popular novel analysis must use `hot-novel-deconstruction` and then `anti-copy-abstraction`.
- Drafting must use `chapter-outline` before `prose-generation`.
- Draft outputs must pass `quality-review` before revision or final decisions.
- Reader feedback must use `reader-feedback` before it changes chapter plans or revisions.
- Professional knowledge must use `multidisciplinary-knowledge` before entering KnowledgeCard or review rules.
- Skills must not store source text, protected expression, concrete copyable plots, private material, or real secrets.
- Skills do not expand Agent permissions and do not replace schemas, workflows, or review gates.

## Copyright And Originality Boundary

Reference works may be used only for structural learning and abstract mechanism extraction.

Allowed:

- Structure.
- Rhythm.
- Conflict mechanism.
- Character mechanism.
- Emotion curve.
- Hook pattern.
- Commercial readability logic.

Forbidden:

- Copying original sentences or distinctive expressions.
- Reusing protected characters, settings, or plot combinations.
- Mixing raw source text with generated drafts.
- Treating decomposition reports as draft prose.
- Encouraging direct imitation of a specific work.

Reference-derived assets must remain abstract and must preserve source lineage.

## Data Boundary

Keep asset stages separate:

- Raw source: `data/raw/`.
- Cleaned source: `data/cleaned/`.
- Decomposition: `data/decompositions/`.
- Knowledge: `data/knowledge/`.
- Materials: `data/materials/`.
- Topics/worlds/characters/outlines/chapter plans/drafts: dedicated generated asset directories.
- Reviews and revisions: `data/reviews/`.
- Feedback: `data/feedback/`.
- Runs and task status: `data/runs/`.

Do not move or merge these directories without updating docs, tests, and validation.

## Model Adapter Boundary

Runnable local workflows use:

- `MockModelAdapter`
- `LocalRuleEngine`

Provider adapters for Claude Code, Codex, ChatGPT, and DeepSeek are contract skeletons only.

- `health_check()` is safe.
- Generation, analysis, review, revise, and batch operations fail closed until real implementations are approved.
- Do not call external APIs in tests.
- Do not hard-code provider-specific logic inside business workflows.
- Do not read secrets except through a documented future provider implementation.

Real provider support requires:

- ADR.
- Dependency policy.
- Secret policy.
- Mocked tests.
- No-network default test behavior.

## Required Commands

Use these commands for verification:

```bash
make lint
make test
make validate
make sync-skills-dry-run
```

Use `make demo` only when demo asset generation is relevant to the task.

## Testing Standard

Before claiming completion:

- Run the smallest relevant test first when possible.
- Run `make lint`, `make test`, and `make validate` for code or schema changes.
- Record test results in roadmap docs when the task changes project status.
- If a test fails, perform the smallest reasonable fix and rerun.
- If repeated fixes fail, stop and report the blocker.

Do not invent test results. If a command cannot run, state the exact command, failure reason, and evidence.

## File Modification Rules

Allowed when task-relevant:

- `src/`
- `tests/`
- `docs/`
- `skills/`
- `scripts/`
- `README.md`
- `CLAUDE.md`
- `AGENTS.md`
- `Makefile`
- `pyproject.toml`

Handle carefully:

- Existing generated assets under `data/`.
- `examples/sample_outputs/`.
- Any file containing user-provided source material.

Forbidden:

- Deleting `.git`.
- Deleting user directory files.
- Editing secrets, tokens, `.env`, or authentication files.
- Installing dependencies without explicit approval and documented reason.
- Broad cleanup of files not directly referenced by the current task.
- Destructive Git commands unless explicitly requested.

## Workflow For Code Changes

Use this loop:

```text
Read relevant docs and code
-> identify the smallest useful target
-> implement
-> test
-> fix failures
-> update docs/status when needed
-> summarize changed files and verification
```

For Novel Forge roadmap tasks, update:

- `docs/08-roadmap/v5-task-pool.md`
- `docs/08-roadmap/v5-progress-log.md`
- `docs/08-roadmap/v5-test-log.md`
- related module, workflow, schema, or operations docs when behavior changes

## Acceptance Standard

A feature is complete only when it has:

- Clear CLI or workflow entry when applicable.
- Schema-backed input and output.
- Correct local storage path.
- Tests or executable validation.
- Error handling.
- Documentation.
- Progress/status visibility.
- No copyright-boundary regression.
- No unrelated file churn.

If any item is missing, mark the work as partial and explain the remaining gap.
