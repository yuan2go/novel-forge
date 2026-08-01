# Current Roadmap

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

This roadmap is ordered by dependency and proof value. It supersedes feature-count roadmaps for current execution priority. Historical V5/V6/V7 phase reports remain evidence for their original commits only.

## 1. Roadmap Principle

The current bottleneck is not missing isolated features. It is the absence of one fully proven path from a complete repository HEAD through Authority deployment, real Provider execution, whole-book progression and long-form acceptance.

Required order:

```text
Repository integrity
→ Authority deployment
→ Current-SHA test proof
→ Real Provider single Chapter
→ Whole-book supervisor
→ Judge calibration
→ Long-form proof
→ Multi-book proof
→ Platform/feedback production
```

Do not reorder later capabilities ahead of unresolved P0 dependencies.

## 2. P0 — Restore A Verifiable Repository Baseline

### P0-1 HEAD integrity

**Goal:** prove that every imported module, migration target, console script and required test is committed.

Required work:

- verify Project/Task/Source/MKAOS Authority package files;
- verify migrations `0043` through `0050`;
- verify Source/MKAOS worker entrypoints;
- verify focused PostgreSQL test modules;
- remove invalid registrations or commit missing files;
- run import smoke against exact HEAD.

Acceptance:

```text
head_integrity_verified=true
python_import_smoke_passed=true
migration_module_inventory_passed=true
console_script_target_inventory_passed=true
required_test_inventory_passed=true
```

### P0-2 Static integrity gates

Add CI checks that fail when:

- a module imported by an entrypoint is missing;
- a migration is registered but the module is absent;
- a `pyproject.toml` console script target is absent;
- a required test pattern matches zero tests;
- generated evidence is bound to another commit;
- `git diff --check` or compileall fails.

### P0-3 Current-SHA full validation

Run and publish exact results for:

```bash
python -m compileall -q src tests
python -m unittest discover -s tests/architecture -p 'test_*.py'
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

The report must record commit SHA, environment, dependency versions, count, failures, errors and skips.

## 3. P1 — Close Authority Deployment

### P1-1 Authority-only API service

Create a deployment profile that explicitly sets:

```text
NOVEL_FORGE_ENVIRONMENT=production
NOVEL_FORGE_STORAGE_AUTHORITY=postgresql
NOVEL_FORGE_APPLICATION_BUILD_ID
NOVEL_FORGE_COMMIT_SHA
NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT
Provider/model routes
Provider cost caps
Trusted principal configuration
```

Acceptance:

- API imports and starts without Legacy modules;
- production refuses Legacy authority;
- migrations are current before readiness;
- release identity is visible in health/readiness.

### P1-2 Durable worker topology

Deploy explicit services for:

```text
Chapter Authority worker
Book Follow-up worker
Provider callback worker
Outbox dispatcher/recovery worker
Source Authority worker
MKAOS Authority worker
```

Remove the assumption that the Legacy Celery worker executes Authority workloads.

Acceptance:

- admitted commands finish without synchronous fixture execution;
- worker restart resumes pending work;
- stale Fence results are rejected;
- worker health and last tick are queryable;
- dead-letter/outbox recovery is operator-visible.

### P1-3 Dependency-aware readiness

Readiness must check:

- database connectivity and migration version;
- Authority worker health;
- Provider Registry and route qualification;
- object store write/read proof;
- outbox lag threshold;
- stuck Saga threshold;
- configured release identity.

Static `{status: ready}` is insufficient.

### P1-4 Database operations

Add or prove:

- connection pool or PgBouncer;
- backup and point-in-time recovery;
- forward-fix migration policy;
- restore rehearsal;
- schema preflight and lock-risk reporting;
- rolling/blue-green deployment procedure.

## 4. P2 — Real Provider Single-Chapter Proof

### P2-1 Provider composition root

Build the real Provider Registry from explicit factories and secret references. No domain service may construct SDK clients or read raw credentials.

Start with one provider and one stage:

```text
OpenAI Draft
```

Then expand in order:

```text
Review
→ Revision
→ Re-review
→ Canon Extraction
→ five Quality groups
→ Reader Outcome
```

### P2-2 Control behavior proof

Each stage must prove:

- stable idempotency key;
- Provider request ID;
- timeout;
- query/retrieve;
- upstream cancellation where supported;
- callback verification where supported;
- duplicate callback replay;
- UNKNOWN reconciliation;
- late-result handling;
- restart recovery.

### P2-3 Real usage and cost

Replace `0 USD / not_provided` with one of:

- provider-billed cost receipt;
- versioned price-table calculation with model/token evidence;
- explicit `unavailable` status that blocks cost-sensitive production.

Acceptance:

```text
real_provider_proven=true
real_usage_proven=true
real_cost_proven=true
single_chapter_real_provider_proven=true
```

### P2-4 Editorial acceptance

Use Chinese web-novel ChapterPlans and human editors to evaluate:

- readability;
- reader promise;
- payoff and chapter economy;
- protagonist agency/charm;
- antagonist pressure;
- suspense and hook;
- continuity;
- originality/source leakage;
- style drift;
- platform fit.

A technically successful model call is not a quality proof.

## 5. P3 — Whole-book Autonomous Production Supervisor

Implement a single Authority-led supervisor for:

```text
BookDesign
→ VolumePlan
→ ArcPlan
→ ChapterGroupPlan
→ ChapterPlan
→ Chapter Authority
→ Chapter Acceptance
→ Reader Outcome
→ Longform Recap
→ Plan Change Decision
→ Next Chapter
→ Ending/Closure
```

Responsibilities:

- resolve the next production unit from frozen versions;
- admit child Operations and persist delegation;
- wait/reconcile instead of using process-local state;
- schedule recap according to cadence and risk;
- pause on unresolved Canon, quality, budget or approval gates;
- generate PlanChange proposals rather than mutate plans silently;
- propagate accepted plan versions to future ChapterPlans;
- prove ending reachability and completion criteria.

Acceptance starts with three real chapters and expands through 10 chapters without manual construction of every command payload.

## 6. P4 — Quality And Reader Calibration

### P4-1 Golden sets

Create versioned sets by:

```text
Genre × Platform × Stage × Quality Dimension
```

Each case needs target AssetVersion, human labels, evidence spans, disagreement and acceptance policy.

### P4-2 Judge validation

Measure:

- inter-judge agreement;
- human/Judge agreement;
- position/order sensitivity;
- mutation stability;
- adversarial prompt resistance;
- out-of-distribution behavior;
- false-positive and false-negative rates;
- threshold behavior across genres.

### P4-3 Production gate policy

Until calibrated:

```text
Reader Outcome = SHADOW
uncalibrated scores = non-probabilistic raw/ordinal evidence
provider-only quality = not sufficient for irreversible publish decisions
```

Acceptance:

```text
quality_judge_calibrated=true
reader_outcome_behavior_calibrated=true
release_thresholds_versioned=true
```

## 7. P5 — Long-form Proof Program

Use staged gates:

| Gate | Scope | Required proof |
|---|---|---|
| L10 | 10 real-provider chapters | recovery, state evolution, recap, cost |
| L30 | one meaningful arc/volume slice | arc progression, promise/payoff, replan |
| L100 | long-form chain | character/relationship/timeline/foreshadow stability |
| L300 | extended serial production | fatigue, repetition, cost/throughput and operator load |
| L1M | approximately one million Chinese characters | full-book stability, ending reachability and completion |

Every stage must record:

- accepted ChapterPlan and Draft versions;
- StoryState and Canon diffs;
- unresolved issues and debt ledgers;
- quality trends;
- actual token/cost/time;
- retry, cancel and recovery events;
- human review samples;
- plan changes and their downstream impact.

Do not promote deterministic 12/50-chapter fixtures to `longform_proven=true`.

## 8. P6 — Multi-book And Portfolio Production

Start only after L30 is stable.

Stages:

```text
3 books in parallel
→ 5 books
→ 10 books
```

Verify:

- project/book memory isolation;
- no cross-book Context contamination;
- worker fairness and concurrency caps;
- Provider budget caps;
- database connection and outbox pressure;
- per-book pause/resume/cancel;
- portfolio allocation decisions;
- operator alert volume;
- recovery after worker/database restart.

Acceptance:

```text
multi_book_proven=true
portfolio_dispatch_proven=true
cross_book_contamination_tests_passed=true
```

## 9. P7 — Platform Publishing And Feedback

After production quality is stable:

1. maintain manual upload as the safe first production mode;
2. add one official platform adapter with approved credentials;
3. prove submit/query/withdraw/callback/rate-limit/duplicate behavior;
4. import metrics and comments with privacy classification;
5. generate feedback proposals without silent Canon/plan mutation;
6. run controlled experiments before claiming causal learning;
7. require approval for high-risk production changes.

## 10. P8 — Security And Multi-user Productization

Before external or team deployment:

- OIDC/JWT or equivalent authentication;
- service accounts and worker identity;
- project-scoped RBAC;
- approval-role separation;
- secret manager integration;
- signed/mTLS callbacks where applicable;
- audit retention and export policy;
- tenant/project isolation tests;
- threat model and penetration testing.

## 11. Current Non-goals

Until P0-P2 are complete:

- no repository/package rename;
- no third production runtime;
- no broad new module expansion unrelated to closure;
- no public SaaS deployment;
- no automatic irreversible publishing;
- no claim that fixture, UI or design evidence is production proof.
