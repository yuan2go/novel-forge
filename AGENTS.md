# Repository agent rules

## Authority

Executable code, schema, migrations, runtime wiring and tests are the only evidence of
current behavior. `architecture/reality-evidence.json` and canonical docs are checked
projections of those facts; they never override implementation.

Before changing or reporting a capability, resolve its real entry point, application,
domain owner, mutation boundary, repository/UoW, migration, Provider path, gate and
recovery path. Do not infer reachability from a class, fixture or document.

Use these evidence states exactly: `CODE_EXISTS`, `WIRED`, `EXECUTABLE`, `QUALIFIED`,
`PRODUCTION_PROVEN`. A lower state never implies a higher one. Scripted, fixture, test,
human, real-Provider, long-form and production evidence remain separate.

## Runtime boundaries

- PostgreSQL owns production business and execution facts.
- Command Kernel owns Operation, Attempt, Lease, Fence and ExternalEffect lifecycle.
- RuntimeJob coordinates execution only; it does not own business truth.
- Repositories are persistence mechanics inside an owning UoW, not business Authorities.
- External I/O occurs outside business transactions and is reconciled from durable
  intent/receipt evidence.
- Unknown external or commit outcomes fail closed and require reconciliation.
- Retry and recovery append versioned evidence; they do not rewrite terminal history.
- Story generators create candidates. Story Design owns semantic decisions;
  Hierarchical Planning and Plan Change own active typed plan mutation.
- ChapterGroup and Book coordination reference Chapter work; they do not copy Chapter
  Attempt, Lease, Fence, ExternalEffect or receipt state.
- Book acceptance owns the accepted chapter cursor and binds ChapterOutcome, Canon,
  Narrative State and projection evidence atomically.
- Reader, recap, preference and behavior observations are evidence or proposals. They do
  not directly mutate accepted Canon, current Narrative State or active plans.
- Agent Runtime owns definition/session/provenance facts. Domain Authorities validate and
  commit domain assets.

## Execution evidence

Schema-backed output must retain the applicable project/workspace, input artifacts,
schema/version, output location, model/provider, prompt/Skill version, validation and
gate status, trace/span identity, model-call/cost evidence, and downstream artifact or
revision task.

Do not use chat memory where an artifact, command result, checkpoint, receipt, review
issue, gate result or ledger record is required. A rerun creates a new versioned record.

## Copyright and source isolation

Reference works may inform abstract structure, pacing, conflict, character mechanisms,
emotion, hooks and craft. Do not copy protected expression, characters, settings, scenes
or distinctive plot combinations. Raw source text and analysis assets are not draft
inputs unless a governed context contract explicitly permits the material.

## Documentation and comments

The only canonical docs are listed in `docs/README.md`. Do not add delivery histories,
session reports, completed plans or parallel architecture sources.

Comments and docstrings explain invariants, constraints, security, compatibility,
non-obvious algorithms or third-party limitations. They do not narrate architecture,
record former versions or store future design. Production module docstrings require an
`INVARIANT:`, `CONSTRAINT:`, `SECURITY:`, or `COMPATIBILITY:` prefix.

## Skills

Root `skills/` is the source. Generate `.claude/skills/` with `make sync-skills`; never
hand-edit generated copies. Skills cannot bypass Authority, schema, storage, copyright,
Provider, permission or quality gates.

## Verification

Run the smallest focused check during development and the complete applicable matrix in
`docs/runtime-operations.md` before claiming completion. A green fixture or structural
check does not upgrade the evidence ceiling.
