# Production Foundation and Provider-Domain Design

> **Authority clarification:** This document's production-foundation work is
> governed by [PostgreSQL Command Kernel Authority Design](2026-07-12-postgresql-command-kernel-authority-design.md).
> PostgreSQL is the sole production authority for both control state and
> domain assets/versions. Local JSON is only a pre-refactor, read-only frozen
> snapshot and optional migration evidence; it is not a production artifact
> store, projection, compatibility reader, or fallback.

## Goal

Build a Head-bound, fail-closed production foundation for Novel Forge, then use
that foundation for real Codex-driven Topic, World, and Character outputs.

## Scope and order

1. **Head-bound CI baseline.** Every required Python, workspace, skill, web,
   migration, and targeted PostgreSQL integration test runs against the exact
   checked-out commit. CI emits the commit SHA and refuses stale/generated
   artifacts. A green result means the whole selected matrix is green, not a
   cached or partial job.
2. **Production command convergence and validity.** `ProductionOperation` is
   the only creation/control boundary for Workflow, Agent Scheduler, Chapter
   Bus, and migrated legacy pipeline paths. `ContentValidityGate` is separate
   from artifact coverage: a chapter is valid only when it has measurable
   narrative movement, non-empty meaningful prose, and the required
   draft/review/revision progression.
3. **Story state authority and performance.** Append immutable,
   project-scoped `StoryStateEvent`s; derive state only through deterministic
   reducers; persist versioned snapshots and verify replay hash equality.
   Replace all-directory scans on hot chapter paths with project-scoped indexed
   queries and bounded runtime writes.
4. **Universal production evidence.** All production entrypoints require an
   Envelope, bounded ContextManifest/Bundle, source eligibility, ReviewIssue
   handling, route approval, and completion evidence. Missing evidence blocks
   production completion. Legacy JSON is accessible only to the explicit,
   offline migration tool and never to a production runtime path.
5. **Real Provider domain outputs.** Topic, World, and Character operations
   use the unified Model Gateway and the logged-in Codex CLI adapter in
   production. Deterministic fixtures remain explicitly test-only and cannot
   be labelled real-provider evidence.

## Architectural decisions

- PostgreSQL is the production authority for operation command/event/outbox
  transactions and all domain assets, versions, qualifications, lineage and
  object references. PostgreSQL Read Models are rebuildable projections only.
  Object storage contains immutable bytes referenced and qualified by
  PostgreSQL; Local JSON has no production-runtime role.
- `StoryStateEvent` is append-only and project-scoped. The reducer is pure,
  idempotent, and deterministic; snapshots carry stream version and state hash.
- The ContextManifest is the model-call input contract. It records selected
  references, compacted payload digests, budget, source eligibility, and
  truncation/omission decisions before Codex is spawned.
- `ContentValidityGate` consumes output metadata and content-quality analysis;
  it does not lower existing quality gates or use a fixture to create a pass.
- CI has a fast required lane and a PostgreSQL integration lane; real Codex
  calls and human calibration are explicit manual/credentialed acceptance jobs,
  never faked in CI.

## Failure handling

- A missing parent, invalid state transition, missing ContextManifest, source
  gate failure, missing ReviewIssue disposition, or missing model/cost evidence
  produces a persisted failed command/event and blocks completion.
- Provider input over budget is rejected before process creation with a compact
  recovery instruction. No silent truncation occurs outside the recorded
  ContextManifest compaction step.
- Reducer/snapshot hash mismatch, outbox duplicate, lease conflict, or
  cross-project reference is an integration-test failure and a production
  fail-closed condition.

## Acceptance criteria

- CI is green for the commit under test and reports the SHA plus test matrix.
- All migrated creation/control paths create or resolve a single parent
  operation; direct legacy child control is rejected.
- Story state replay rebuilds the same snapshot hash from PostgreSQL events.
- Hot chapter operations use bounded project-scoped queries; performance tests
  detect directory-wide scan regressions and write-amplification growth.
- Topic/World/Character real Codex calls have ProductionOperation,
  ContextManifest, route approval, ModelCallLog, usage/cost evidence, output
  asset, and ContentValidityGate evidence.

## Non-goals

- This work does not claim successful 10/30/100 chapter acceptance before the
  above foundations and separate real-provider acceptance runs pass.
- It does not replace logged-in Codex CLI with API-key providers or weaken
  source/copyright boundaries.
