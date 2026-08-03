# Project Current State

Updated: 2026-08-03

Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`

Implementation evidence SHA: `ea6876476287e90a206ec4a10b2345a881f67656`

Autonomous Novel OS is the product target. The repository/package/CLI name remains `novel-forge` until a dedicated rename migration is approved.

This document is the current implementation fact table. Blueprints describe the target; historical reports describe their original commit; neither replaces current code and HEAD-bound runtime evidence.

Current re-audit: [`reports/architecture-closure-current-head-reaudit.md`](reports/architecture-closure-current-head-reaudit.md). Current-SHA matrix: [`reports/track-a-current-sha-validation.md`](reports/track-a-current-sha-validation.md).

## 1. Current Verdict

Track A is verified and the first Track B Book/BookDesign slice runs in an isolated Authority-only local deployment. The codebase is still not a production-proven autonomous premium long-form novel system.

```text
architecture_defined=true
command_kernel_proven=true
postgres_authority_fixture_proven=true
single_chapter_fixture_proven=true
book_coordination_fixture_proven=true

head_integrity_verified=true
current_head_import_verified=true
migration_chain_verified=true
current_sha_test_baseline_recorded=true
architecture_fitness_foundation_enabled=true
minimal_authority_only_runtime_verified=true

authority_only_runtime_verified=false
real_provider_proven=false
real_cost_proven=false
longform_proven=false
multi_book_proven=false
platform_publish_proven=false
production_verified=false
```

## 2. Baseline Resolution And Remaining Blockers

The historical missing-file warning is resolved at the implementation evidence SHA. Project, Task, Source, MKAOS and BookDesign Authority modules, workers, migrations `0043` through `0051` and focused tests are committed, importable and manifest checked. The migration chain has one head and clean PostgreSQL migration passes.

Remaining blockers are different in kind:

- D0 is `BLOCKED_MISSING_CREDENTIALS`; no real Provider execution, usage or cost is proven.
- `npm audit --omit=dev` reports three high-severity production dependency findings; fix before Track E security acceptance.
- Browser Playwright smoke, public authentication, backup/PITR, SLO/capacity and production-scale recovery are not executed.
- L3/L10/L30 and later long-form gates remain false.

## 3. Runtime Architecture

### 3.1 Production target runtime

```text
API / CLI / Operator Console
→ Production Preparation
→ PostgreSQL Authority Command
→ Operation / Saga / Attempt
→ Durable Authority Worker
→ Production Execution Gateway / Domain Handler
→ AssetVersion / External Effect / Receipt
→ Completion Contract / Gate
→ Strong Query / Projection
```

### 3.2 Current dual surface

The repository still contains:

```text
Legacy local-first runtime
PostgreSQL Authority runtime
```

Legacy remains available for development and compatibility. Production-like environments are intended to fail closed unless PostgreSQL Authority is selected, but default development settings and current Compose topology still start the Legacy-oriented path.

Do not add new production behavior to Legacy except migration/compatibility work. New production capabilities must use the shared Authority kernel and must not introduce a parallel state machine.

## 4. Capability Fact Table

| Capability | Current code fact | Evidence level | Current limit |
|---|---|---|---|
| Command Kernel | Operation Definition, Operation, Saga, Attempt, transition, retry, cancellation, compensation | PostgreSQL code and integration fixtures | production load/recovery drill not proven |
| Idempotency | stable key, request digest, replay/conflict | SQL unique key and application validation | cross-service operational policy still needs full deployment proof |
| Lease/Fence | one held lease, monotonic fencing token, stale result rejection | DB function, trigger, focused tests | real distributed worker pressure not proven |
| Asset Authority | Asset, AssetVersion, dependency, decision, activation, supersession, evidence and blob lifecycle | PostgreSQL integration and Track B runtime | generic metadata must not replace typed domain schemas |
| BookDesign Authority | typed `book-design.v1` Candidate, decision, activation, supersession and read model | unit, PostgreSQL and local Docker HTTP proof | BookPlan activation belongs to Track C1 |
| External Effects | dispatch, receipt, query/cancel/callback/reconciliation, Inbox/Outbox | protocol and fixture integration | real provider/platform behavior not proven |
| Chapter Authority | 18-node Chapter Saga | deterministic PostgreSQL integration | real Chinese prose and provider quality not proven |
| Production Preparation | frozen ChapterPlan/context/profile input manifest | code and fixture tests | end-to-end operator workflow needs deployment proof |
| Context consistency | manifest, frozen inputs and Context segments must match | fail-closed handler code | retrieval quality and long-horizon selection need calibration |
| Review/revision | Draft, Review, Revision, Re-review stages | Provider port plus deterministic fixture | semantic quality unproven |
| Canon | extraction, proposal, approval, patch and snapshots | Chapter Authority flow | semantic extraction accuracy and merge UX partial |
| Story State | Canon, Character, Relationship, Timeline, Foreshadow, Promise, Reward, World, Power snapshots | append-only fixture proof | million-word accuracy unproven |
| Quality | five groups, aggregate, 41 dimension evidence assets | fixture/human-calibrated test evidence | provider Judge remains uncalibrated |
| Release | Publish Gate, Export, Final Release Gate | local deterministic effect proof | real platform publishing disabled/unproven |
| Book Authority | persistent book run, sequential cursor, child delegation, acceptance, pause/resume/cancel | PostgreSQL fixture integration | external caller still supplies each frozen ChapterPlan |
| Reader Outcome | governed model sidecar and state candidate | Shadow contract | uncalibrated, non-blocking, no authority commit |
| Longform Recap | recap, deviation, adjustment proposal, optional replan request | deterministic Authority handler | no real long-form proof |
| Provider v2 | registry, capability profile, route qualification, OpenAI seam | unit/protocol code | real registry composition and billed cost unproven |
| Agent collaboration | frozen scope, work order, candidate graph, decision/commit slices | fixture protocol | not a complete autonomous Agent Center |
| MKAOS/Source | Authority modules, workers and migrations plus isolated Legacy migration path | current-SHA unit/PostgreSQL proof | real connector/model extraction remains unproven |
| Web Admin | Next.js operator consoles and API clients | static/node tests historically reported | authentication and full browser E2E incomplete |
| Portfolio/multi-book | allocation/isolation/reporting foundations | fixture/schema evidence | real multi-book scheduling and load unproven |

## 5. Chapter Production Chain

The authoritative Chapter chain is:

```text
Plan
→ Context
→ Draft
→ Review
→ Revision
→ Re-review
→ Canon Extraction
→ Canon Proposal
→ Canon Update
→ Quality Structural
→ Quality Commercial
→ Quality Source Originality
→ Quality Longform
→ Quality Platform
→ Quality Aggregate
→ Publish Gate
→ Export
→ Final Release Gate
```

The deterministic PostgreSQL test proves protocol behavior, including one injected retry, Saga forward recovery, stale Fence rejection, ambiguous external-effect reconciliation, duplicate receipt replay, output AssetVersion binding, audit/event/outbox evidence, 41 quality dimensions and nine state snapshots.

This proves the execution protocol. It does not prove output quality or real Provider reliability.

## 6. Whole-book Production State

Book Authority currently supports:

- stable Book root admission;
- frozen BookDesign/BookPlan/production and long-form versions;
- sequential chapter reservation;
- Chapter Authority delegation;
- recovery of incomplete delegation;
- Chapter acceptance and story-state advancement;
- pause, resume and cancellation;
- Reader Outcome and Longform Recap follow-up operations.

The missing autonomous loop is:

```text
BookDesign
→ Volume/Arc/ChapterGroup generation
→ next ChapterPlan generation
→ Chapter production
→ acceptance
→ reader/quality analysis
→ recap/replan
→ next chapter
→ ending/closure
```

A Book Production Coordinator must coordinate this progression without owning or bypassing domain Authority decisions.

## 7. Provider and Quality State

Provider v2 control contracts exist, but current automatic verification is mock-only. A real Provider proof must separately establish:

- explicit adapter construction and registration;
- authenticated route and secret reference resolution;
- stable idempotency behavior;
- timeout and query behavior;
- upstream cancel and callback receipts;
- UNKNOWN reconciliation;
- actual token usage;
- billed or reproducibly derived cost;
- normalized structured output;
- Chinese web-novel editorial quality.

Quality and Reader Outcome values must remain uncalibrated/Shadow until golden-set and human annotation evidence support production thresholds.

## 8. Deployment and Security State

`compose.authority-only.yml` establishes the Track B minimum: PostgreSQL Authority, MinIO, Redis delivery-only, migration job, dependency-aware Authority API and grouped Authority/Maintenance workers. It was built, started and restart-tested locally. The default Compose remains the broader Legacy-oriented development topology, and Track E hardening is not complete.

Authority routes use a trusted server-configured Principal and ignore request-supplied actor identity. This is safer than trusting payload identity, but it is not multi-user authentication. There is no demonstrated OIDC/JWT/API-key/mTLS boundary, and the default configured operator can have wildcard project scope.

Current deployment target is a trusted local operator environment, not a public or multi-tenant SaaS runtime. The narrower `minimal_authority_only_runtime_verified` flag is true; the broader production `authority_only_runtime_verified` flag remains false.

## 9. Verification Status

The complete current-SHA matrix is published in [`reports/track-a-current-sha-validation.md`](reports/track-a-current-sha-validation.md): architecture 60/60, unit 1,169/1,169, acceptance 2/2, core PostgreSQL 141/141 with zero skips, and full integration 222 passed with 9 optional-backend skips. Admin test/build and both Compose builds pass. Required Playwright browser smoke remains not executed.

## 10. Current Priority

```text
P0: preserve the verified Track A/Track B baseline
P1: unblock and pass D0 with one real Provider/model
P2: Track C1 BookDesign → Active Plan
P3: real Provider chapter and Judge promotion/calibration
P4: autonomous Book Coordinator L3/L10 and Track E hardening
P5: L30/L100/L300, multi-book, platform and production operations
```

Adding more isolated modules is not the current priority. The priority is converging existing capabilities into one buildable, deployable, recoverable and evidence-bound production path.
