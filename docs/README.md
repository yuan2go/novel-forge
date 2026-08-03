# Autonomous Novel OS Documentation

Updated: 2026-08-02  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited code HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

This directory is the documentation entrypoint for the Autonomous Novel OS target implemented in the `novel-forge` repository.

The repository/package/CLI name remains Novel Forge v6 until an explicit rename migration is approved. Authority API metadata may use a V7 Authority version, but this does not constitute a repository-wide rename.

## Current Status Warning

The 2026-08-01 audit found a repository-integrity warning: current entrypoints and migration indexes reference new Project, Task, Source and MKAOS Authority modules, workers, migrations and tests, while some target files could not be resolved from the same exact HEAD through the repository content interface.

Until a local checkout verifies the complete file set and imports, use:

```text
head_integrity_verified=false
current_head_build_verified=false
authority_only_runtime_verified=false
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
```

Do not use historical test counts, document completion, UI presence or Fixture proof to override these flags.

## Required Reading Order

1. [`../CLAUDE.md`](../CLAUDE.md) — repository operating rules for coding agents.
2. [`project-current-state.md`](project-current-state.md) — current implementation fact table.
3. [`reports/current-engineering-state.md`](reports/current-engineering-state.md) — concise current engineering verdict.
4. [`reports/2026-08-01-code-audit-and-documentation-rebaseline.md`](reports/2026-08-01-code-audit-and-documentation-rebaseline.md) — detailed code audit, risks and evidence limits.
5. [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) — six-track Architecture Closure Epic.
6. [`architecture-closure/README.md`](architecture-closure/README.md) — vertical Slice execution index and AC reference map.
7. [`roadmap/current-roadmap.md`](roadmap/current-roadmap.md) — current six-track delivery order.
8. [`architecture/module-map.md`](architecture/module-map.md) — current runtime and module boundaries.
9. [`product/capability-map.md`](product/capability-map.md) — capability maturity map.
10. [`quality/regression-tests.md`](quality/regression-tests.md) — required current-SHA verification matrix.
11. Relevant active design/blueprint documents for the selected Slice.
12. Historical reports only when researching lineage or a previous implementation pass.

## Next Stage Epic: Six-track Architecture Closure

The next engineering stage is no longer organized as AC-00 through AC-19 parallel work packages.

The current execution model is:

```text
Track A — Trusted Baseline And Governance
→ Track B — Shared Authority Kernel And Storage
→ D0 — Real Provider Qualification Probe
→ Track C — Novel Domain And Context
→ Track D — Intelligence, Execution And Quality
→ Track E — Autonomous Book Runtime And Operations
→ Track F — Migration, Long-form And Scale Proof
```

Primary documents:

- [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) — target architecture, six Tracks, vertical Slices, Gate definitions and final exit criteria;
- [`architecture-closure/README.md`](architecture-closure/README.md) — execution index, AC reference mapping, WIP rules and Slice Gate Report template;
- [`architecture-closure/minimal-stable-contracts.md`](architecture-closure/minimal-stable-contracts.md) — Book Completion、Human Intervention、Judge 晋升、Context 失效、StoryState 更正、Read Model、Object Store 和 Outbox/Worker 最小契约；
- `architecture-closure/ac-00...ac-19` — architecture references and Reviewer checklists, not independent delivery units.

## Vertical Slice Rule

A valid delivery Slice must cover a complete path:

```text
API / CLI / Parent Saga
→ identity and scope
→ command and idempotency
→ transaction/job/saga/effect
→ domain validation
→ Candidate and Authority Decision
→ PostgreSQL Authority Commit
→ Object Store evidence when needed
→ query projection
→ recovery and operator visibility
→ current-SHA tests and Gate report
```

The following do not count as completed delivery by themselves:

- Schema or database table;
- interface or abstract class;
- Web page;
- Scripted Provider Fixture;
- LocalStorage-only path;
- historical test report;
- document status change.

## AC-00 Through AC-19 Status

The AC files remain active architecture references. They contain ADR material, code locations, migration guidance, test matrices and Acceptance Gate checklists.

They must not be scheduled as twenty parallel implementation streams and must not maintain independent completion percentages.

Their implementation status is derived from the six Track Slices:

| Track | Main AC references |
|---|---|
| A | AC-00、AC-01、AC-02、AC-18、AC-19 |
| B | AC-02、AC-03、AC-04、AC-05、AC-06、AC-15、AC-16、AC-17、AC-18 |
| C | AC-06、AC-07、AC-08、AC-09、AC-10、AC-13、AC-18 |
| D | AC-09、AC-11、AC-12、AC-13、AC-18 |
| E | AC-04、AC-05、AC-07、AC-08、AC-09、AC-13、AC-14、AC-15、AC-16、AC-18 |
| F | AC-03、AC-07、AC-08、AC-10、AC-13、AC-15、AC-16、AC-17、AC-18、AC-19 |

## Architecture Terminology Update

The current Epic uses narrower terminology to avoid Authority and orchestration overreach:

- `Context Builder` should be implemented as a `Context Compiler`: domains declare requirements; the compiler selects, assembles, compresses, validates and records evidence.
- `Book Production Supervisor` should be implemented as a `Book Production Coordinator`: it owns Root Saga/Cursor coordination, not creative state or domain computation.
- `Quality Authority` is split into `Production Quality Gate` and `Evaluation And Calibration Lab`.
- `Source`, `Material` and `Knowledge` are separate layers.
- The shared asset model uses common metadata plus strongly typed domain payloads, not unrestricted generic JSON.
- Execution is classified as Transaction Command, Durable Job, Saga or External Effect; not every operation becomes a Saga.
- Event sourcing is selective, primarily for Saga, StoryState reducer, Canon changes, receipts, audit and outbox.
- Minimal Authority-only Runtime belongs to Track B; Track E hardens deployment, readiness, PITR, SLO, security, capacity and operator control.
- Critical Legacy Writer cutover is part of every vertical Slice; Track F only retires residual non-critical Legacy.

## Documentation Authority Order

When documents disagree, use this order:

```text
current code and migrations
→ current-SHA runtime/test evidence
→ accepted ADR and current architecture
→ project-current-state.md
→ current engineering/audit reports
→ six-track Architecture Closure Epic
→ active implementation plans
→ blueprints
→ historical reports
```

A blueprint describes the target. A report describes its original baseline. A route, class, page, schema or Fixture does not by itself prove product completion.

## Current Entry Documents

| Area | Current document | Purpose |
|---|---|---|
| Current state | [`project-current-state.md`](project-current-state.md) | implemented, partial, unproven and blocked capabilities |
| Current engineering verdict | [`reports/current-engineering-state.md`](reports/current-engineering-state.md) | concise state and priority summary |
| Detailed code audit | [`reports/2026-08-01-code-audit-and-documentation-rebaseline.md`](reports/2026-08-01-code-audit-and-documentation-rebaseline.md) | code facts, runtime limits, risks and staged recommendations |
| Next-stage Epic | [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) | six Tracks, vertical Slices, evidence model and final Gate |
| Execution index | [`architecture-closure/README.md`](architecture-closure/README.md) | Track order, AC reference map, WIP and Gate Report template |
| Current roadmap | [`roadmap/current-roadmap.md`](roadmap/current-roadmap.md) | current Track and Slice priority |
| Architecture/module map | [`architecture/module-map.md`](architecture/module-map.md) | Authority/Legacy boundaries and module responsibilities |
| Product capability map | [`product/capability-map.md`](product/capability-map.md) | evidence-based capability maturity |
| Verification | [`quality/regression-tests.md`](quality/regression-tests.md) | static, unit, PostgreSQL, Provider, long-form and multi-book gates |
| Architecture overview | [`architecture/overview.md`](architecture/overview.md) | broader system layers and data flow; validate against current map |
| Extension guide | [`engineering/extension-guide.md`](engineering/extension-guide.md) | how to extend without bypassing Authority contracts |

## Active Product And Architecture Targets

These documents define target architecture and implementation intent. They are active references, not implementation proof.

- [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) — current architecture convergence program.
- [`blueprint/autonomous-novel-os-full-blueprint.md`](blueprint/autonomous-novel-os-full-blueprint.md) — full functional blueprint.
- [`blueprint/novel-os-project-blueprint.md`](blueprint/novel-os-project-blueprint.md) — project blueprint and phase plan.
- [`architecture/production-execution-plane.md`](architecture/production-execution-plane.md) — unified production execution contracts, routing and recovery target.
- [`architecture/scoped-conversational-agent-architecture.md`](architecture/scoped-conversational-agent-architecture.md) — frozen-scope Agent collaboration architecture.
- [`design/hierarchical-story-planning-and-production-authority.md`](design/hierarchical-story-planning-and-production-authority.md) — hierarchical planning design; use the current Epic terminology and constraints when implementing.
- [`design/book-design-authority-and-longform-closed-loop.md`](design/book-design-authority-and-longform-closed-loop.md) — semantic generators, Book Design, long-form state, feedback and completion design.
- [`plans/book-design-authority-implementation-plan.md`](plans/book-design-authority-implementation-plan.md) — detailed historical Epics and Work Packages; reconcile with six-track execution before use.
- [`plans/novel-os-final-blueprint-completion-plan.md`](plans/novel-os-final-blueprint-completion-plan.md) — target completion plan.

## Current Engineering Interpretation

The strongest implemented foundation is:

```text
PostgreSQL Command Kernel
Operation / Saga / Attempt
Lease / Fencing
AssetVersion
External Effect / Receipt
18-node Chapter Authority
Book coordination slices
Canon/Story State slices
Quality evidence
Provider control contracts
```

The critical remaining proof is:

```text
complete current HEAD
Authority-only deployment
real Provider single Chapter
real usage and cost
Book Coordinator L3/L10
Recap and replan recovery
L30 Arc proof
critical Legacy Writer retirement
multi-book and platform proof after closure
```

Current priority is one validated vertical Slice at a time, not module count, document count or UI count.

## Current Documentation Rules

Every new current-state, architecture or proof document must include:

- date;
- branch;
- full baseline commit SHA;
- code fact versus runtime verification distinction;
- exact commands and results when tests were run;
- explicit `NOT_EXECUTED` or `BLOCKED_PRECONDITION` when not run;
- evidence paths;
- real Provider, long-form, multi-book and production flags;
- links from this index when it replaces a current entrypoint.

Do not use `final`, `complete`, `production-ready` or equivalent wording without a defined Gate and current-SHA evidence.

## Historical Documents

The following remain useful for lineage but are not current implementation truth unless explicitly refreshed:

- `docs/00-product/` through `docs/09-skills/`;
- `docs/new/`;
- older files under `docs/design/` and `docs/plans/`;
- V5/V6/V7 phase reports;
- reports whose baseline predates the current audit;
- files with `current`, `final`, `complete` or `proof` in the name that are not linked above as current.

Do not delete historical documents during routine cleanup. Preserve them as evidence, mark them historical, or move them only through an explicit archive migration.

## Claude Code Workflow

Before changing production architecture or claiming completion:

1. read this index and the current-state documents;
2. read the six-track Epic and identify the current Track/Slice;
3. use AC documents only as architecture and Reviewer references;
4. inspect relevant code, migrations and tests;
5. verify that all referenced modules are committed;
6. complete one vertical path from entrypoint to Authority Commit and query/recovery evidence;
7. run the Slice-focused tests and required broader Gate;
8. record exact results against the current SHA;
9. update only the current state, roadmap, verification matrix and Slice Gate report when maturity changes.

If current code contradicts an older report or design, code wins. Record the conflict instead of copying the older claim.
