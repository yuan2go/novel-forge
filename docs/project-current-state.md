# Project Current State

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

Autonomous Novel OS is the product target. The repository/package/CLI name remains `novel-forge` until a dedicated rename migration is approved.

This document is the current implementation fact table. Blueprints describe the target; historical reports describe their original commit; neither replaces current code and HEAD-bound runtime evidence.

Detailed audit: [`reports/2026-08-01-code-audit-and-documentation-rebaseline.md`](reports/2026-08-01-code-audit-and-documentation-rebaseline.md).

## 1. Current Verdict

The codebase has an advanced PostgreSQL Authority and production-control foundation. It is not yet a production-proven autonomous premium long-form novel system.

```text
architecture_defined=true
command_kernel_proven=true
postgres_authority_fixture_proven=true
single_chapter_fixture_proven=true
book_coordination_fixture_proven=true

head_integrity_verified=false
current_head_build_verified=false
real_provider_proven=false
real_cost_proven=false
longform_proven=false
multi_book_proven=false
platform_publish_proven=false
production_verified=false
```

## 2. Blocking Baseline Condition

The current HEAD contains references to new Project, Task, Source and MKAOS Authority modules, workers, migrations `0043` through `0050`, and focused tests. Some target files could not be resolved from the same exact HEAD through the repository content interface.

Possible causes are omitted/untracked files or a repository indexing anomaly. Until a local checkout verifies all files and imports, the current HEAD must not be described as buildable.

Required first checks:

```bash
git status --short
git ls-files src/novel_forge/modules/project_authority
git ls-files src/novel_forge/modules/task_authority
git ls-files src/novel_forge/modules/source_authority
git ls-files src/novel_forge/modules/mkaos_authority
git ls-files src/novel_forge/storage/migrations/versions/v20260801_00*
python -c "import novel_forge.api.authority_app"
python -c "import novel_forge.storage.migrations"
```

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
| Asset Authority | Asset, AssetVersion, qualification, output binding, blob references | PostgreSQL schema/runtime | current Project/Source/MKAOS migration integrity needs verification |
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
| MKAOS/Source | broad Legacy modules and new Authority migration references | mixed | current Authority file integrity must be verified |
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

A Book Production Supervisor must own this progression without bypassing domain Authority decisions.

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

Current Compose does not establish a complete Authority-only deployment. The independent Chapter Authority worker is not part of the default topology, and Authority health is not a dependency-aware readiness probe.

Authority routes use a trusted server-configured Principal and ignore request-supplied actor identity. This is safer than trusting payload identity, but it is not multi-user authentication. There is no demonstrated OIDC/JWT/API-key/mTLS boundary, and the default configured operator can have wildcard project scope.

Current deployment target is a trusted local operator environment, not a public or multi-tenant SaaS runtime.

## 9. Verification Status

The 2026-08-01 audit did not execute tests because no authenticated local checkout was available. Do not copy historical pass counts into a current claim.

The next current-SHA report must record exact commands, duration, test count, skips, environment, database image, Node/Python versions and commit SHA for:

```bash
python -m compileall -q src tests
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m unittest discover -s tests/acceptance -p 'test_*.py'
python scripts/run_authority_postgres_tests.py
python -m unittest discover -s tests/integration -p 'test_*.py'
npm --prefix web/admin ci
npm --prefix web/admin test
npm --prefix web/admin run build
docker compose config
docker compose build
```

## 10. Current Priority

```text
P0: restore and prove a complete HEAD
P1: deploy Authority API + durable workers
P2: prove one real Provider single-chapter loop
P3: implement whole-book autonomous supervisor
P4: calibrate judges and prove 10/30/100/300 chapters
P5: prove multi-book, platform and production operations
```

Adding more isolated modules is not the current priority. The priority is converging existing capabilities into one buildable, deployable, recoverable and evidence-bound production path.
