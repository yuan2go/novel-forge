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
real_provider_proven=false
longform_proven=false
multi_book_proven=false
production_verified=false
```

Do not use historical test counts or Fixture proof to override these flags.

## Required Reading Order

1. [`../CLAUDE.md`](../CLAUDE.md) — repository operating rules for coding agents.
2. [`project-current-state.md`](project-current-state.md) — current implementation fact table.
3. [`reports/current-engineering-state.md`](reports/current-engineering-state.md) — concise current engineering verdict.
4. [`reports/2026-08-01-code-audit-and-documentation-rebaseline.md`](reports/2026-08-01-code-audit-and-documentation-rebaseline.md) — detailed code audit, risks and evidence limits.
5. [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) — next-stage Epic governing architecture closure before full-book autonomy.
6. [`architecture-closure/README.md`](architecture-closure/README.md) — AC-00 through AC-19 implementation index.
7. [`architecture/module-map.md`](architecture/module-map.md) — current runtime and module boundaries.
8. [`product/capability-map.md`](product/capability-map.md) — capability maturity map.
9. [`quality/regression-tests.md`](quality/regression-tests.md) — required current-SHA verification matrix.
10. [`roadmap/current-roadmap.md`](roadmap/current-roadmap.md) — dependency-ordered implementation roadmap.
11. Relevant active design/blueprint documents for the task.
12. Historical reports only when researching lineage or a previous implementation pass.

## Next Stage Epic: Architecture Closure

The next engineering stage is defined by:

- [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) — overall Architecture Closure objective, phases, evidence levels and global Gate;
- [`architecture-closure/README.md`](architecture-closure/README.md) — execution order and dependency map;
- `architecture-closure/ac-00...ac-19` — twenty work packages covering ADRs, implementation plans, code locations, migration scripts, test matrices and Acceptance Gates.

These documents are target architecture and implementation specifications. They do not prove that the work has been implemented. AC status may only be advanced with current-SHA code, migration, test and deployment evidence.

The intended sequence is:

```text
Trusted repository baseline
→ shared Authority and execution kernel
→ novel planning/state/context closure
→ Agent/Provider/Quality closure
→ Book Production Supervisor and Authority-only deployment
→ Legacy retirement and L3/L10/L30 proof
```

## Documentation Authority Order

When documents disagree, use this order:

```text
current code and migrations
→ current-SHA runtime/test evidence
→ project-current-state.md
→ current engineering/audit reports
→ accepted ADR and active architecture
→ active implementation plans
→ blueprints
→ historical reports
```

A blueprint describes the target. A report describes its original baseline. A route, class, page, schema or fixture does not by itself prove product completion.

## Current Entry Documents

| Area | Current document | Purpose |
|---|---|---|
| Current state | [`project-current-state.md`](project-current-state.md) | implemented, partial, unproven and blocked capabilities |
| Current engineering verdict | [`reports/current-engineering-state.md`](reports/current-engineering-state.md) | concise state and priority summary |
| Detailed code audit | [`reports/2026-08-01-code-audit-and-documentation-rebaseline.md`](reports/2026-08-01-code-audit-and-documentation-rebaseline.md) | code facts, runtime limits, risks and staged recommendations |
| Next-stage Epic | [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) | architecture closure objective, phases, evidence model and final Gate |
| AC work packages | [`architecture-closure/README.md`](architecture-closure/README.md) | AC-00 through AC-19 ADR, implementation, migration, test and acceptance index |
| Architecture/module map | [`architecture/module-map.md`](architecture/module-map.md) | Authority/Legacy boundaries and module responsibilities |
| Product capability map | [`product/capability-map.md`](product/capability-map.md) | evidence-based capability maturity |
| Verification | [`quality/regression-tests.md`](quality/regression-tests.md) | static, unit, PostgreSQL, Provider, long-form and multi-book gates |
| Roadmap | [`roadmap/current-roadmap.md`](roadmap/current-roadmap.md) | P0-P8 dependency-ordered execution plan |
| Architecture overview | [`architecture/overview.md`](architecture/overview.md) | broader system layers and data flow; validate against current map |
| Extension guide | [`engineering/extension-guide.md`](engineering/extension-guide.md) | how to extend without bypassing Authority contracts |

## Active Product And Architecture Targets

These documents define target architecture and implementation intent. They are active references, not implementation proof.

- [`architecture-closure/autonomous-novel-os-architecture-closure-epic.md`](architecture-closure/autonomous-novel-os-architecture-closure-epic.md) — next-stage architecture convergence and anti-rework program.
- [`blueprint/autonomous-novel-os-full-blueprint.md`](blueprint/autonomous-novel-os-full-blueprint.md) — full functional blueprint.
- [`blueprint/novel-os-project-blueprint.md`](blueprint/novel-os-project-blueprint.md) — project blueprint and phase plan.
- [`architecture/production-execution-plane.md`](architecture/production-execution-plane.md) — unified production execution contracts, routing and recovery target.
- [`architecture/scoped-conversational-agent-architecture.md`](architecture/scoped-conversational-agent-architecture.md) — frozen-scope Agent collaboration architecture.
- [`design/hierarchical-story-planning-and-production-authority.md`](design/hierarchical-story-planning-and-production-authority.md) — Book/Volume/Arc/ChapterGroup/Chapter Authority design.
- [`design/book-design-authority-and-longform-closed-loop.md`](design/book-design-authority-and-longform-closed-loop.md) — semantic generators, Book Design, long-form state, feedback and completion design.
- [`plans/book-design-authority-implementation-plan.md`](plans/book-design-authority-implementation-plan.md) — detailed Epics and Work Packages.
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
Book coordination
Canon/Story State
Quality evidence
Provider control contracts
```

The critical remaining proof is:

```text
complete current HEAD
Authority-only deployment
real Provider single Chapter
real usage and cost
whole-book autonomous supervisor
Judge calibration
10/30/100/300 chapter proof
million-word stability
multi-book isolation and operations
real platform publishing and feedback
multi-user security
```

Current priority is convergence and proof, not adding more isolated modules.

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

Do not use `final`, `complete`, `production-ready` or equivalent wording without a defined acceptance gate and current-SHA evidence.

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
2. read the Architecture Closure Epic and relevant AC work packages;
3. inspect the relevant code, migration and tests;
4. verify that all referenced modules are committed;
5. follow the Authority dependency direction;
6. run the smallest focused test, then the required broader Gate;
7. record exact results against the current SHA;
8. update AC status, current-state, capability, verification and roadmap documents when the maturity verdict changes.

If current code contradicts an older report, code wins. Record the conflict instead of copying the older claim.
