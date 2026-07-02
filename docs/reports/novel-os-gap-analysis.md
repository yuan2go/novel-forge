# Novel Operating System Gap Analysis

Date: 2026-07-02

## Executive Judgment

Novel Forge v6 is already an early Novel Operating System runtime. It is no longer a one-off prompt generator and no longer lacks the basic OS skeleton. The repository has schema-backed assets, workflow execution, Agent dispatch, runtime policy, provider guard, trace/cost ledgers, KG and continuity gates, review/rework, rollback, long-chain smoke tests, Web OS console routes, and the new long-form stability control layer.

The remaining gap depends on the definition of "Novel Operating System":

| Target definition | Current maturity | Remaining gap | Judgment |
|---|---:|---:|---|
| P0 OS runtime vertical slice | 86%-88% | 12%-14% | Core chain exists and is tested, but strict enforcement and provider/scale proof need hardening. |
| Operator-grade local Novel OS product | 75%-80% | 20%-25% | Backend first slices are broad; UI depth, real adapters, operational runbooks, and recurring pressure acceptance remain. |
| Mostly autonomous long-novel production OS | 65%-70% | 30%-35% | Agent autonomy, semantic extraction quality, long-run creative control, feedback learning, and business rollback depth are not yet complete. |

Do not claim a complete autonomous Agent Center yet. Per `AGENTS.md`, the missing pieces are still UI depth, operation coverage, model usage hard-stop behavior, business rollback depth, and end-to-end OS acceptance breadth.

## Evidence Reviewed

- Product target: `README.md`, `docs/00-product/novel-operating-system.md`
- Roadmap: `docs/08-roadmap/novel-os-remaining-closure-plan.md`, `docs/08-roadmap/novel-os-remaining-closure-plan1.md`
- Architecture: `docs/01-architecture/system-architecture.md`, `docs/architecture/novel-operating-system-new-capabilities.md`
- Long-form stability: `docs/novel-os-final-optimization-blueprint.md`, `docs/architecture/longform-stability-architecture.md`, `docs/architecture/quality-gates.md`
- Reports: `docs/reports/current-system-analysis.md`, `docs/reports/e2e-quality-gate-test-report.md`, `docs/reports/longform-stability-ui-acceptance-report.md`
- Code modules under `src/novel_forge/modules/`
- API routers under `src/novel_forge/api/routers/`
- Admin UI under `web/admin/app/features/`
- Tests under `tests/unit/`, `tests/integration/`, `web/admin/tests/`

Internal module completion scoring also reports roughly `86%` code-side maturity when run from the repository root, but runtime asset scoring is workspace-root sensitive. This is useful as a code evidence signal, not as a definitive production readiness score.

## What Is Already OS-Level

| Capability | Current evidence | Status |
|---|---|---|
| Schema-backed artifact system | `schemas/`, `storage/local.py`, asset validation | Strong first slice |
| Workflow runtime | `workflow_nodes`, scheduler tick/resume/invalidation tests | Strong first slice |
| Agent runtime | `agent_runs`, `agent_scheduler`, dispatch queue, checkpoint, budget, gates | Strong first slice |
| Runtime policy | `runtime_policy`, strict/compat checks, legacy bypass audit | Strong first slice |
| Provider guard | `model_adapters`, provider runtime guard tests | Strong OpenAI-compatible/local slice |
| Trace/cost ledger | `runtime_ledger`, trace timeline, cost dashboard | Strong first slice |
| Novel KG | `novel_kg`, identity resolution, semantic enhancement, KG gate | Strong first slice |
| Review/rework loop | review issue -> revision task -> patch -> draft version -> re-review -> publish gate | Strong first slice |
| Rollback/recovery | `operation_transactions`, `operation_checkpoint` | Strong first slice, needs rehearsal depth |
| Feedback backflow | `feedback_backflow`, human-gated plan/rule/KG proposals | First slice |
| Long-form stability | `longform_stability`, Publishing Gate integration, UI page | New strong first slice |
| Web OS console | workflow, agent, KG, trace, cost, rollback, invalidation, rework, longform pages | Broad first slice |
| OS acceptance tests | `test_novel_os_acceptance.py`, long-chain smoke/pressure tests | Good fixture coverage |

## Main Gap

The project is not missing a skeleton. It is missing default, repeated, hard-to-bypass production proof.

The architecture has many correct first slices, but a complete Novel Operating System requires these same controls to be universal across every model-producing path, every chapter lifecycle, every operator page, and every long-running production scenario.

## Functional Gap Matrix

| Area | Current maturity | Remaining function gap | Priority |
|---|---:|---|---|
| Universal runtime enforcement | 84%-87% | Ensure every API/CLI/service path that mutates production or calls a model goes through one OS envelope by default. | P0 |
| Provider-native runtime control | 80%-84% | Add native SDK streaming/cancel/cost semantics for each production provider beyond OpenAI-compatible/local process adapters. | P0 |
| Model usage hard stop | 78%-82% | Prove token/cost timeout cancellation is fail-closed in real provider runs, not only mock/local fixtures. | P0 |
| Agent Center | 78%-82% | Move from dispatch/timeline first slice to full evidence cockpit: run graph, checkpoints, gates, budget burn, rollback, retry, dead-letter, SLA. | P0/P1 |
| Business rollback | 80%-84% | Add richer cross-node diff preview, rollback rehearsal, large-workspace confirmation, and recovery runbooks. | P0/P1 |
| Long-form stability | 82%-86% | Backfill real long novel assets, calibrate thresholds, run 12/50/100 chapter pressure acceptance as a normal gate. | P0/P1 |
| Model-assisted extraction | 72%-78% | Improve entity/relation/state extraction quality with evidence spans, confidence, merge adjudication, and regression fixtures. | P1 |
| Arc and volume control | 75%-80% | Add editable Arc Planner UI, arc progress graph, payoff quality scoring, and required-answer enforcement over chapter windows. | P1 |
| Foreshadowing lifecycle | 75%-80% | Score not only presence/payoff timing, but payoff quality and target-truth relevance. | P1 |
| Character state and debt ledgers | 78%-82% | Add state diff UI, liability thresholds, topic-specific sub-ledger templates, and cross-chapter contradiction checks. | P1 |
| Villain operation model | 76%-80% | Prove antagonist cadence and staged wins over real multi-chapter runs, with UI visibility and revision tasks. | P1 |
| Novel KG semantic depth | 80%-84% | Add provider-backed extraction in strict OS mode, stronger identity merge UX, motivation drift, power-scale/rule contradiction scoring. | P1 |
| Context/memory retrieval | 80%-84% | Operationalize L0-L5 policies, stale context invalidation, retrieval eval sets, pgvector tuning and migration rehearsal. | P1 |
| Feedback learning loop | 72%-78% | Connect real reader feedback adapters, clustering quality, human-gated plan mutation, and post-publish metric trends. | P1/P2 |
| Publishing operations | 76%-82% | Add platform-specific packages, calendars, title/hook variants, publish logs, and real publishing/feedback adapters. | P1/P2 |
| Web cockpit/UI | 78%-82% | Add deeper graph zoom/search/minimap, evidence drawers, form editors for every OS schema, browser smoke as default CI evidence. | P1/P2 |
| Long-chain scale acceptance | 75%-80% | Make 12/50+ chapter pressure runs routine, track quality drift/cost drift/continuity drift, and fail releases on regressions. | P0/P1 |
| Ops/deployment | 72%-78% | Harden local-up, optional dependency installation, API server smoke, Postgres/pgvector/Qdrant/MinIO backups, migrations, restore drills. | P0/P1 |

## How Far The Current Project Is From OS Completion

### 1. P0 Runtime OS

Remaining: about `12%-14%`.

The minimum OS chain is close: project fixture, workflow, Agent dispatch, context/model boundary, trace/cost ledger, KG/continuity gate, review/rework, publish gate, invalidation, resume, and cost-quality report all have test evidence. The missing work is broader enforcement and harsher real-environment proof.

Required closure:

- strict OS envelope over all production/model paths;
- real provider hard-stop proof;
- API/local-up smoke that always starts in a clean environment;
- recurring long-chain acceptance;
- Agent Center evidence UI deep enough for operator recovery.

### 2. Productized Local Novel OS

Remaining: about `20%-25%`.

The backend has many first slices, but product-grade usage needs richer operator workflows, schema editors, visual diff/recovery tools, and real data adapters. Current UI is broad, but some pages are still evidence dashboards rather than full management surfaces.

Required closure:

- Canon/Arc/Foreshadow/Character/Villain editors, not only reports;
- rollback rehearsal and recovery cockpit;
- feedback and publishing adapters;
- model benchmark datasets and routing regression;
- browser-backed smoke as normal acceptance, not optional.

### 3. Autonomous Long-Novel Factory

Remaining: about `30%-35%`.

The system can control one chapter-sized OS fixture and deterministic multi-chapter smoke, but full autonomy over a long novel requires creative-state reasoning that is deeper than deterministic extraction.

Required closure:

- model-assisted extraction calibrated on real drafts;
- semantic quality scoring for motivation drift, payoff quality, character agency, villain pressure, platform fit, and reader fatigue;
- multi-agent planning/review/revision arbitration;
- feedback-to-plan learning with human approval;
- reliable 50/100 chapter cost, continuity, quality, and recovery metrics.

## Critical Missing Functions

1. **Universal OS Mode Enforcement**
   Every draft/review/revision/analysis/feedback/evaluation path must be unable to write accepted production assets without context, trace, model log, cost ledger, gate result, and schema validation evidence.

2. **Real Provider Runtime Proof**
   The provider guard is credible for mock/local/OpenAI-compatible paths, but complete OS readiness needs provider-specific streaming usage, cancellation, exact cost capture, and timeout evidence for every enabled provider.

3. **Complete Agent Center**
   Agent runtime assets exist, but the operator still needs a full center for checkpoints, gates, budgets, retries, SLA, rollback, dead letters, operation coverage, and evidence timelines.

4. **Production-Scale Long-Form Acceptance**
   Long-form stability now exists, but it needs to run against real long-chain projects as a default acceptance gate. The system should treat 12/50/100 chapter drift reports as recurring OS health checks.

5. **Semantic Extraction Quality**
   Deterministic extraction is safe but shallow. Model-assisted extraction must become reliable enough to identify entity drift, relationship changes, clue lifecycle, motivation drift, payoff quality, and antagonist pressure with evidence spans.

6. **Editable OS Control Surfaces**
   The UI shows many runtime facts, but a complete OS needs editable management pages for canon, arc plans, motif budgets, foreshadowing graph, character/debt ledger, villain operations, prompt versions, model routes, and rollback plans.

7. **Operational Hardening**
   Local production mode needs repeatable dependency checks, FastAPI/worker/browser smoke, backup/restore rehearsal, migration dry-runs, pgvector index tuning, and runbook-level failure recovery.

## Best Next Iteration

### P0

1. Add a strict OS enforcement audit that enumerates every model-producing function, API endpoint, CLI command, and workflow processor, then marks each as enforced, compatible, or blocked.
2. Run a real 12-chapter longform stability pressure acceptance using the current test novel or a deterministic fixture, and persist the report.
3. Fix environment smoke so FastAPI, Web Admin, and API contract checks run cleanly from `make local-smoke`.
4. Expand Agent Center from dispatch table to full evidence cockpit.
5. Add provider-specific hard-stop tests for the selected production provider.

### P1

1. Build editable Longform Stability managers: Canon, Arc, Foreshadowing, Motif Budget, Character/Debt, Villain Operation.
2. Add model-assisted extraction calibration fixtures with expected entities, relationships, clues, debts, and antagonist actions.
3. Add arc payoff quality and villain pressure scoring.
4. Add rollback rehearsal and cross-node diff preview.
5. Add feedback adapter and human-gated plan mutation workflow.

### P2

1. Add publishing platform packages and post-publish feedback import.
2. Add graph/minimap/drawer polish for KG, Arc, and Invalidation pages.
3. Add prompt/model routing regression suites.
4. Add 50/100 chapter scheduled pressure reports for continuity, quality, cost, and recovery.

## Bottom Line

Novel Forge is approximately `86%-88%` complete as a P0 Novel OS runtime, but only `75%-80%` complete as an operator-grade local Novel Operating System product. The remaining work is not another writing prompt or another chapter generator. It is universal enforcement, production provider proof, richer Agent/UI operations, semantic extraction depth, and long-chain acceptance as a routine quality gate.
