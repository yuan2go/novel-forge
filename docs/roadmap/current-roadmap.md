# Current Roadmap

Updated: 2026-07-11
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, commit `6f8f578`

This roadmap reflects current code evidence, not historical v5 plans. See `docs/08-roadmap/v5-*` only for history.

Product target note: the repository/package/CLI remain `novel-forge`, but the active product target is Autonomous Novel OS. For the blueprint-aligned v1-v7 execution plan, use `docs/reports/v1-v7-roadmap.md` and `docs/reports/next-production-slices.md`. This file remains the V7/runtime delta roadmap and should not be read as proof that v1 single-book production closure is complete.

## 2026-07-11 Phase 01 Runtime Kernel Slice

Status: `partial`.

`ProductionOperation` is now a schema-backed LocalStorage parent for registered `dispatch_production_operation` routes. It records the normalized Execution Envelope, request digest, idempotency key, child state-owner projection, result, and failure recovery instruction. Identical requests replay the stored parent; digest conflicts fail closed. A bounded runtime control API and static child-runner bypass scan now exist. This does not yet prove universal CLI/API/Worker/Revision/Recap/Publish control migration, complete retry/timeout/compensation lifecycle semantics, PostgreSQL transaction authority, or real 10/30 chapter production.

Next runtime slice: scan direct production callers, add parent lifecycle/status reconciliation contracts, then converge every approved production entrypoint before expanding creative or portfolio scope.

## 2026-07-05 V7 Content Intelligence Delta

The branch now has a verified foundation for Genre OS, Style OS, Canon Graph 2.0 plugins, Quality Eval 2.0, Long-chain Proof Center, and manual Publishing/Feedback Adapter 2.0. These capabilities are wired through schemas, services, product API routes, Agent operations, workflow processors, focused tests, and basic Web Admin consoles. See `docs/reports/v7-content-intelligence-foundation-report.md`.

This does not yet mean full autonomous premium long-form production. Provider-backed evaluation evidence, provider judge run reports, opt-in provider 50-chapter proof, generic platform API publishing, Fanqie/Qidian manual receipt parsing and adapter gates, project-level production Cockpit, multi-book schedule evidence, golden-set calibration assets, and UI artifact inspect/compare/repair foundations now exist. Remaining V7 proof work should focus on real external provider runs, official platform SDK/callback/rate-limit integrations, automatic schedule consumption, and richer guided repair workflows.

## V7 Follow-up Priorities

| Priority | Goal | Current Status | Dependencies | Acceptance Standard | Order |
|---|---|---|---|---|---|
| V7-P0-1 | Provider-backed quality judge/proof chain | Implemented governed aggregator | `modules/quality_eval/`, `modules/long_chain_proof/`, `modules/v7_provider_proof/`, provider runtime guard, runtime ledger | Opening 3, provider single-chapter quality loop, and provider 50 proof share route approval, model call log, runtime policy gate, cost ledger, and external-proof evidence | 1 |
| V7-P0-2 | Topic/outline/chapter/draft/revision use of Genre and Style policies | Implemented production gate foundation | Context Builder, topic/outline/chapter/draft/revision services, style/genre assets | Production model calls fail closed without V7 content-intelligence preflight evidence | 2 |
| V7-P0-3 | Publish/release package cites V7 quality evidence | Implemented hard-gate foundation | publishing module, Quality Eval 2.0, ReviewIssue, platform strategy | PublishGate and ReleasePackage hard-stop on failed/missing quality, provider judge, genre/style/canon/platform evidence | 3 |
| V7-P1-1 | UI artifact inspection and production Cockpit depth | Implemented foundation plus project production console and schedule view | Web Admin V7 consoles, OS Console, product API | Operators can load, compare, mark V7 assets for review, run provider/platform gates, inspect gate board, feedback approval queue, multi-book cost/quality dashboard, and parallel schedule evidence | 4 |
| V7-P1-2 | Real credentialed provider long-chain proof | Remaining operator task | long-chain proof, provider runtime policy, cost ledger, provider credentials | A credentialed 50-chapter provider proof is opt-in, budgeted through route policy, and produces external provider proof evidence | 5 |
| V7-P1-3 | Platform-specific publishing adapters | Manual-first Fanqie/Qidian slices implemented | generic HTTP adapter, platform strategy, publishing feedback adapters | Fanqie/Qidian manual rules, platform adapter gate, receipt parser, review status normalization exist; official SDK/callback/rate-limit integration remains future work | 6 |
| V7-P1-4 | Eval golden sets and provider judge calibration | Implemented foundation | Eval Center, Quality Eval 2.0, human annotation assets | Golden set suites, human annotations, and provider judge calibration reports can be created and surfaced through product API | 7 |

## P0 - Runtime Correctness And Production Safety

| Priority | Goal | Current Status | Dependencies | Acceptance Standard | Order |
|---|---|---|---|---|---|
| P0-1 | Universal provider/runtime evidence | Partially implemented | runtime policy, model router, guarded model adapter, runtime ledger | Every production model-producing path has provider route approval, model call log, cost ledger, timeout/cancel, and fail-closed behavior | 1 |
| P0-2 | Publish/release gate completeness | Partially implemented | publishing module, evaluation gate, provider gate, platform strategy, MKAOS risk, ReviewIssue | Ready release package is generated only through full evidence; missing/failed gates hard-stop | 2 |
| P0-3 | Agent operation coverage for key production roles | Partially implemented | agent registry, scheduler, workflow nodes, provider policy | Platform Compliance, Training, Longform Recap, publishing, and evaluation operations are registered, schedulable, and tested | 3 |
| P0-4 | Context/KG/Canon consistency | Partially implemented | context builder, MKAOS, Canon graph, Novel KG, continuity | Generation/release paths cannot bypass context source isolation or continuity gates | 4 |
| P0-5 | Environment policy for local vs production | Partially implemented | Postgres fallback policy, provider fallback, storage, Docker stack | Production mode has explicit no-silent-fallback policy; local mode remains testable | 5 |

## P1 - Maintainability And Service Boundaries

| Priority | Goal | Current Status | Dependencies | Acceptance Standard | Order |
|---|---|---|---|---|---|
| P1-1 | Continue large service splits | In progress | agent scheduler, audit/publishing, MKAOS, product API, workflow nodes | Public facades stay stable; seam tests cover registry, runner, lease, dead-letter, publishing, selection, quality, lineage, writer | 1 |
| P1-2 | Broad exception governance | In progress | `core.exception_policy`, workflow nodes, audit, MKAOS, product API | Production failures are not swallowed; local optional dependency misses are explicit | 2 |
| P1-3 | UI/ops evidence depth | Partially implemented | Web OS console, provider reports, publishing reports, evaluation reports | Operators can inspect provider approval, gate failures, trace/cost, rollback/recovery, and release readiness | 3 |
| P1-4 | Documentation drift control | Implemented this pass, ongoing | docs index, current state, module map, audit report | New durable changes update current docs and do not revive obsolete v5 claims | 4 |

## P2 - Product Depth And Long-Form Quality

| Priority | Goal | Current Status | Dependencies | Acceptance Standard | Order |
|---|---|---|---|---|---|
| P2-1 | Productize Eval Center | Partially implemented | evaluation center, model router, cost ledger, UI | Eval cases/results influence routing and release gates with operator-visible evidence | 1 |
| P2-2 | Strengthen long-form continuity | Partially implemented | Canon, Novel KG, longform recap, context builder | Multi-chapter fixtures show consistent character, arc, foreshadowing, and world rules | 2 |
| P2-3 | Reader feedback backflow | Partially implemented | feedback, feedback_backflow, editor chief, loop kernel | Reader feedback produces traceable plan/revision suggestions without silent mutation | 3 |
| P2-4 | Publishing/platform operations | Partially implemented | platform strategy, publishing adapters, UI | Platform-specific title/summary/hook/schedule/package checks are verifiable | 4 |

## P3 - Platformization

| Priority | Goal | Current Status | Dependencies | Acceptance Standard | Order |
|---|---|---|---|---|---|
| P3-1 | Industrial database-first production mode | Design/partial implementation | Postgres migrations, local JSON fallback policy, Docker stack | Production environment can run without silent local fallback | 1 |
| P3-2 | Multi-provider benchmarking and routing | Partially implemented | Eval Center, provider guards, cost ledger, model router | Model/provider routing uses verified quality/cost/latency evidence | 2 |
| P3-3 | Rich operator workflows in UI | Partially implemented | Web routes, API services, runtime reports | Key workflows are executable from UI, not just inspectable | 3 |
| P3-4 | Full long-novel production acceptance | Not fully implemented | all P0/P1/P2 runtime and quality work | A long project can move through repeated chapters with resumable, gated, auditable operations | 4 |

## Current Non-Goals

- Do not rename the repository/package/CLI to Novel Operating System without a dedicated migration.
- Do not add new parallel generation paths outside Context Builder, ReviewIssue, Canon/KG, provider policy, and publishing gates.
- Do not treat UI page existence as proof of complete product workflow maturity.
- Do not treat mock provider success as production provider proof.
