# Regression And Verification Guide

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

> Note: the 2026-08-01 remote audit did not execute tests because no authenticated local checkout was available. This guide defines the required verification matrix; it does not claim that the audited HEAD passed it.

## 1. Evidence Rules

Never collapse different proof layers into “all tests passed”.

| Layer | Evidence | What it proves | What it does not prove |
|---|---|---|---|
| Static integrity | file inventory, import smoke, compileall, architecture checks | repository completeness and importability | runtime behavior |
| Unit | deterministic Python/Node tests | local contracts and domain rules | PostgreSQL concurrency or real external behavior |
| PostgreSQL integration | pgvector PostgreSQL service and Authority tests | SQL invariants, transaction/recovery protocols | real Provider quality or production load |
| Migration | clean and legacy schema tests | migration chain and schema assumptions | rollback/restore operations unless explicitly rehearsed |
| Browser E2E | Playwright against running stack | operator interaction and API state transitions | real Provider/platform behavior unless connected |
| Real Provider | credentialed, budgeted, SHA-bound run | model behavior, usage, latency and recovery | long-form quality from one Chapter |
| Real platform | approved pilot with receipts | submission/query/withdraw/callback semantics | broad platform production readiness |
| Long-form acceptance | staged real-provider books | state/quality/cost stability over chapters | multi-book isolation unless parallel |
| Multi-book acceptance | parallel projects/books | isolation, fairness, capacity and recovery | public SaaS security unless tested separately |

Every verification report must include:

```text
commit_sha
branch
python_version
node_version
postgres_image
command
start/end time
test_count
failure_count
error_count
skip_count
external side effects
credentials/profile refs
result classification
```

## 2. P0 Repository Integrity Gate

Run before installing dependencies or trusting any current-state report:

```bash
git status --short
git diff --check

git ls-files src/novel_forge/modules/project_authority
git ls-files src/novel_forge/modules/task_authority
git ls-files src/novel_forge/modules/source_authority
git ls-files src/novel_forge/modules/mkaos_authority
git ls-files src/novel_forge/workers/*authority*.py
git ls-files src/novel_forge/storage/migrations/versions/v20260801_00*
git ls-files tests/integration/test_*authority_postgres.py

PYTHONPATH=src python -c "import novel_forge"
PYTHONPATH=src python -c "import novel_forge.api.app"
PYTHONPATH=src python -c "import novel_forge.api.authority_app"
PYTHONPATH=src python -c "import novel_forge.storage.migrations"
```

Required CI assertions:

- every migration listed in `VERSION_MODULES` exists and imports;
- every `project.scripts` target imports;
- every required Authority router/service package exists;
- every required test module exists;
- each focused discovery pattern matches at least one test;
- the tested SHA equals the workflow SHA.

`unittest.discover()` matching zero files is not a valid proof.

## 3. Complete Local Validation

### 3.1 Installation

```bash
python -m pip install -e '.[test]'
npm --prefix web/admin ci
```

Use an isolated virtual environment. Record the lock/resolution output when dependencies are not fully pinned.

### 3.2 Static and architecture

```bash
python -m compileall -q src tests
git diff --check
make head-integrity-check
make authority-parity-check
python -m unittest discover -s tests/architecture -p 'test_*.py'
make lint
make validate
make check-skills
```

### 3.3 Unit and acceptance

```bash
python -m unittest discover -s tests/unit -p 'test_*.py'
python -m unittest discover -s tests/acceptance -p 'test_*.py'
```

Report optional dependency and browser skips explicitly. A skipped required Authority test is a failure.

## 4. PostgreSQL Authority Validation

Start a clean PostgreSQL 16 + pgvector database.

```bash
export NOVEL_FORGE_DATABASE_URL='postgresql://novel_forge:novel_forge@localhost:5432/novel_forge_core_os_test'

python -m novel_forge.cli authority-migrate
python scripts/run_authority_postgres_tests.py
python -m unittest discover -s tests/integration -p 'test_*.py'
```

Minimum focused suites:

```bash
python -m unittest tests.integration.test_postgresql_only_chapter_slice
python -m unittest tests.integration.test_chapter_authority_scheduler_postgres
python -m unittest tests.integration.test_content_authority_scheduler_recovery_postgres
python -m unittest tests.integration.test_external_effect_runtime_postgres
python -m unittest tests.integration.test_provider_callback_authority_postgres
python -m unittest tests.integration.test_worker_health_postgres
python -m unittest tests.integration.test_book_authority_postgres
python -m unittest tests.integration.test_book_to_chapter_authority_vertical_postgres
python -m unittest tests.integration.test_book_followup_authority_postgres
```

Source/MKAOS Authority suites may be added only after the test modules are confirmed present in the current HEAD.

### 4.1 Required PostgreSQL assertions

The integration suite must prove at least:

- idempotency replay and digest conflict;
- immutable Operation Definition version;
- status/version CAS conflict;
- one active Attempt;
- monotonic Attempt number;
- one held Lease and monotonic Fence;
- stale Worker result rejection;
- retryable and final failure paths;
- cancellation and late-result races;
- ExternalEffect UNKNOWN/reconciliation;
- callback duplicate/conflict handling;
- Saga dependency readiness and completion;
- cross-project reference rejection;
- output AssetVersion and content hash binding;
- audit, State Event and Outbox evidence;
- worker restart recovery;
- Book child delegation and acceptance.

## 5. Migration Validation

Run against both a clean database and a supported legacy snapshot.

```bash
python -m unittest tests.integration.test_authority_migrations_postgres
python -m unittest tests.integration.test_authority_schema_postgres
python -m novel_forge.cli authority-migrate --status
```

Required checks:

- migration chain has no break or duplicate ID;
- clean install reaches `LATEST_MIGRATION_ID`;
- registered migration modules all exist;
- applying migrations twice is safe where designed;
- legacy migration records source hash and quarantine;
- migration verification reconciles row counts and hashes;
- forward-fix/restore procedure is documented for migrations without downgrade statements.

Do not claim rollback support merely because a downgrade API exists.

## 6. Web Validation

```bash
npm --prefix web/admin test
npm --prefix web/admin run lint
npm --prefix web/admin run build
```

`lint` currently means TypeScript validation unless a separate formatter/linter is configured.

Browser validation:

```bash
NOVEL_FORGE_REQUIRE_PLAYWRIGHT=1 npm --prefix web/admin run smoke:browser
```

A skipped Playwright smoke must be reported as `not executed`, not passed.

Required E2E journeys after Authority deployment closes:

1. create/query an Authority project;
2. inspect frozen assets and versions;
3. admit a Chapter command;
4. observe worker/Saga/Attempt progress;
5. cancel/recover a failed Operation;
6. inspect Canon/Quality/Release evidence;
7. start a Book run and delegate/accept a Chapter;
8. inspect Reader Outcome/Recap proposals;
9. verify unauthorized or out-of-scope requests fail.

## 7. Docker And Deployment Validation

```bash
docker compose config
docker compose build
docker compose up -d
```

Before calling the stack Authority-ready, verify the running API reports:

```text
storage_authority=postgresql
environment=production
release build id and commit SHA
latest migration applied
Authority worker healthy
Provider route registry qualified
object store reachable
outbox lag within threshold
```

The current static `/health` response is not sufficient. Add a dependency-aware readiness endpoint and test it.

Deployment recovery tests:

- terminate a Chapter worker during RUNNING;
- expire a Lease and let a new worker acquire a higher Fence;
- restart API and workers with pending External Effects;
- restart PostgreSQL after committed operations;
- restore a backup into a fresh environment;
- verify Outbox replay and duplicate handling;
- verify no Legacy production write occurs.

## 8. Provider v2 Conformance

Mock protocol tests:

```bash
python -m unittest tests.unit.test_provider_adapter_v2
python -m unittest tests.unit.test_chapter_authority_dependencies
python -m unittest tests.unit.test_creative_generator_boundary
```

These tests prove control contracts only.

### 8.1 Real Provider gate

A real Provider run requires explicit authorization, budget and secret references. The report must include:

- provider/model/profile version;
- RouteSnapshot and capability probe;
- Prompt/Skill content hashes;
- stable idempotency key;
- Provider request ID;
- actual input/output tokens;
- billed or reproducibly calculated cost;
- timeout/query/cancel/callback evidence;
- normalized output and ValidationManifest;
- CommitManifest and output AssetVersion;
- real editorial assessment.

Use status values:

```text
PASSED
FAILED
NOT_EXECUTED
BLOCKED_PRECONDITION
```

Never convert `BLOCKED_PRECONDITION` or Fixture success into `real_provider_proven=true`.

## 9. Chapter Acceptance Matrix

### Fixture protocol gate

The deterministic Chapter integration should prove:

- all 18 nodes succeed;
- one injected retry recovers;
- 41 quality dimensions materialize;
- 9 state snapshots materialize;
- Manifest/frozen inputs/Context segments match;
- stale Fence and duplicate receipt behavior are correct;
- Export and Final Release evidence are bound.

### Real single-Chapter gate

Add:

- Chinese ChapterPlan and prose;
- real Provider stages;
- human review;
- actual usage/cost;
- no raw source leakage;
- controlled cancel/recovery drill;
- release gate negative and positive cases.

## 10. Whole-book And Long-form Gates

Do not use one generic “50 chapter test”. Use staged, named gates:

| Gate | Minimum validation |
|---|---|
| L3 | supervisor generates/submits/accepts three sequential Chapters |
| L10 | recap, state evolution, retries, cost and operator workflow |
| L30 | Arc/Volume progression and PlanChange propagation |
| L100 | continuity, promise/payoff, foreshadowing and repetition trends |
| L300 | operational throughput, cost, fatigue and recovery |
| L1M | approximately one million Chinese characters and ending closure |

Every gate must use real Provider output for the claimed chapters and sample human editorial labels. Deterministic/state-only tests remain regression fixtures.

## 11. Multi-book Validation

Stages: 3, 5 and 10 parallel books.

Verify:

- Context and AssetVersion isolation;
- no cross-book Canon/knowledge contamination;
- scheduling fairness;
- per-project/provider/global cost caps;
- database connection pressure;
- outbox lag;
- worker restart recovery;
- per-book pause/cancel;
- portfolio decision audit;
- operator alert volume.

## 12. Security Validation

Before multi-user exposure, add tests for:

- authentication required;
- invalid token/API key rejected;
- project-scoped RBAC;
- approval-role separation;
- service/worker identity;
- callback signature/mTLS;
- secret redaction and no inline credential persistence;
- CORS and CSRF policy where applicable;
- rate limiting and audit trail;
- cross-project ID enumeration and reference rejection.

Trusted server configuration alone is not a complete web authentication proof.

## Runtime Growth Focused Regression

Run:

```bash
make runtime-growth-regression
```

This bounded bundle verifies runtime write-growth policy, workflow governance, cockpit evidence and calibration readiness. It excludes chapter sequence acceptance and provider proof; those remain separate, slower evidence levels and must not be inferred from this bundle.

## Source Governance Focused Regression

Run:

```bash
make source-governance-regression
```

This read/contract-focused bundle verifies source eligibility, leakage preflight, guarded apply readiness and downstream evidence propagation. It excludes connector execution, chapter acceptance, and provider proof, so it performs no network connector or real-model side effect.

## 13. Current Verification Flags

Until a new current-SHA report is published:

```text
head_integrity_verified=false
current_head_build_verified=false
real_provider_proven=false
real_cost_proven=false
longform_proven=false
multi_book_proven=false
platform_publish_proven=false
production_verified=false
```
