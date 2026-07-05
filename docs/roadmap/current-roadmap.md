# Current Roadmap

Updated: 2026-07-05
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, starting commit `3f68522`

This roadmap reflects current code evidence, not historical v5 plans. See `docs/08-roadmap/v5-*` only for history.

## 2026-07-05 V7 Content Intelligence Delta

The branch now has a verified foundation for Genre OS, Style OS, Canon Graph 2.0 plugins, Quality Eval 2.0, Long-chain Proof Center, and manual Publishing/Feedback Adapter 2.0. These capabilities are wired through schemas, services, product API routes, Agent operations, workflow processors, focused tests, and basic Web Admin consoles. See `docs/reports/v7-content-intelligence-foundation-report.md`.

This does not yet mean full autonomous premium long-form production. Provider-backed evaluation evidence, opt-in provider 50-chapter proof, generic platform API publishing, and UI artifact inspect/compare/repair foundations now exist. Remaining V7 proof work should focus on real external provider runs, deeper draft/revision integration, platform-specific adapters, and richer operator workflows.

## V7 Follow-up Priorities

| Priority | Goal | Current Status | Dependencies | Acceptance Standard | Order |
|---|---|---|---|---|---|
| V7-P0-1 | Provider-backed quality judge proof | Implemented foundation | `modules/quality_eval/`, provider runtime guard, runtime ledger | Quality gate can cite provider route approval, model call log, runtime policy gate, cost ledger, and fail-closed behavior in production mode | 1 |
| V7-P0-2 | Draft/revision use of Genre and Style policies | Partial foundation | Context Builder, draft/revision services, style/genre assets | Draft and revision requests consume strategy/style policy via context without raw sample leakage | 2 |
| V7-P0-3 | Release package cites V7 quality evidence | Partial foundation | publishing module, Quality Eval 2.0, ReviewIssue, platform strategy | Release package can hard-stop on failed/missing quality suite evidence | 3 |
| V7-P1-1 | UI artifact inspection depth | Implemented foundation | Web Admin V7 consoles, product API | Operators can load, compare, and mark V7 assets for review from the console | 4 |
| V7-P1-2 | Opt-in provider long-chain proof | Implemented foundation | long-chain proof, provider runtime policy, cost ledger | A 50-chapter provider proof is opt-in, budgeted through route policy, and produces model call/cost/runtime evidence | 5 |
| V7-P1-3 | Platform-specific publishing adapters | New gap | generic HTTP adapter, platform strategy, publishing feedback adapters | A named platform adapter handles auth, upload, status callback, rate limits, and terms constraints with operator approval | 6 |

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
