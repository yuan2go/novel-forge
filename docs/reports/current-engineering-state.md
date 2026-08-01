# Current Engineering State

Updated: 2026-08-01  
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`  
Audited HEAD: `aa991b53039cdf2e4e7911d4483052b9a6a752a1`

This is the current engineering-state entrypoint. Detailed evidence and limitations are recorded in [`2026-08-01-code-audit-and-documentation-rebaseline.md`](2026-08-01-code-audit-and-documentation-rebaseline.md).

## 1. Executive Verdict

Novel Forge is an advanced Autonomous Novel OS engineering prototype with a strong PostgreSQL Authority foundation. The most credible implemented capabilities are:

- Operation Definition, Operation, Saga and Attempt;
- idempotency, request digest, retry, lease and fencing token;
- AssetVersion, qualification and output evidence;
- External Effect, dispatch, receipt, callback, reconciliation, Inbox and Outbox;
- an 18-node Chapter Authority production protocol;
- Canon proposal/approval/update and append-only Story State snapshots;
- five independent Quality groups and aggregate release gates;
- persistent Book Authority coordination and Chapter child-Saga delegation;
- Reader Outcome and Longform Recap Authority contracts;
- Provider v2 capability and control contracts.

The project is not yet a production-proven Autonomous Novel OS. The following remain unproven:

```text
real_provider_proven=false
real_cost_proven=false
longform_proven=false
multi_book_proven=false
platform_publish_proven=false
production_verified=false
```

## 2. Current Blocking Issue

The audited HEAD contains a high-confidence repository-integrity warning.

Reference sites import or register new Project, Task, Source and MKAOS Authority modules, workers, migrations `0043` through `0050`, and focused tests. Some corresponding target files could not be resolved from the same branch or exact HEAD through the repository content interface.

This may be caused by omitted/untracked files or a repository indexing anomaly. Until a local checkout proves otherwise, use:

```text
head_integrity_verified=false
current_head_build_verified=false
```

Required verification:

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

## 3. Architecture State

### PostgreSQL Authority

The Command Kernel is the strongest part of the current system. Database-level constraints protect idempotency, state transitions, monotonic Attempt numbers, one active Attempt, one held Lease, monotonic fencing tokens, project isolation and dependency acyclicity.

### Chapter Authority

The current Chapter protocol is:

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

Current integration evidence is deterministic/fixture-based. It proves protocol behavior, recovery and evidence materialization; it does not prove real model quality.

### Book Authority

Book Authority persists book-level coordination, sequential Chapter submission, child delegation, Chapter acceptance, Story State/Canon advancement, pause/resume/cancel/recovery and follow-up scheduling.

It does not yet autonomously generate every next ChapterPlan, continuously execute the entire book, replan and reach an ending without an external caller supplying frozen chapter inputs.

### Provider Runtime

Provider v2 contracts are present, including query, cancel, callback and usage/cost receipt semantics. Automated CI is mock-only, the real Provider composition root is not yet proven, and current OpenAI cost evidence is not a real billed cost.

## 4. Deployment State

The repository still has two runtime surfaces:

```text
Legacy local-first runtime
PostgreSQL Authority runtime
```

Default development settings and the current Compose topology still favor the Legacy surface. The independent Chapter Authority worker is not part of the default Compose topology. Authority readiness also lacks checks for database migration, worker state, outbox lag, Provider registration and object-store access.

Therefore:

```text
authority_deployment_closed=false
legacy_production_write_retired=false
```

## 5. Security State

Authority routes ignore request-supplied actor identity and use a trusted server-configured Principal. This prevents direct actor spoofing, but it is not a complete HTTP authentication system.

Current limitations:

- no demonstrated OIDC/JWT/API-key/mTLS user authentication;
- one configured local operator can receive broad permissions;
- default project scope can be `*`;
- no production multi-user RBAC proof.

The current model is appropriate for a trusted local operator deployment, not an exposed multi-tenant service.

## 6. Runtime Verification Status

No commands were executed during the 2026-08-01 remote audit because no authenticated local checkout was available. Historical reports remain useful evidence for their original commit only.

The next HEAD-bound validation must include:

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

## 7. Current Maturity

| Area | Current maturity | Evidence limit |
|---|---|---|
| Command Kernel | High | production load and recovery drills remain |
| PostgreSQL Authority | Medium-high | current Authority migration and HEAD integrity need verification |
| Chapter protocol | Medium-high | fixture proof, no real Provider quality proof |
| Canon / Story State | Medium | semantic and long-horizon accuracy unproven |
| Quality / Review | Medium | Judge calibration incomplete |
| Book coordination | Medium | not a complete autonomous whole-book loop |
| Long-form | Medium-low | deterministic recap and fixture chains only |
| Provider execution | Medium-low | real adapter composition, cost and cancellation unproven |
| Web product | Medium | authentication and deep browser E2E incomplete |
| Deployment / operations | Low | default runtime remains Legacy-oriented |
| Multi-book production | Low | no real parallel production proof |

## 8. Immediate Priorities

### P0

1. Resolve HEAD integrity and commit all required modules, migrations and tests.
2. Add static existence/import checks for migration targets, console scripts and required tests.
3. Build an Authority-only Compose topology with API and durable workers.
4. Run the complete validation suite against the exact HEAD.
5. Publish a SHA-bound verification report.

### P1

1. Complete a real Provider single-chapter vertical slice.
2. Record actual usage, billed/derived cost, timeout, cancel, callback and reconciliation evidence.
3. Validate Chinese web-novel output with human editorial review.

### P2

1. Implement a whole-book production supervisor over Book/Volume/Arc/ChapterGroup/Chapter Authority.
2. Calibrate Quality and Reader Outcome judges.
3. Complete real 10/30/100/300-chapter and multi-book proof stages.

## 9. Documentation Rule

Use the following order when assessing current implementation:

1. current code and migrations;
2. HEAD-bound test and runtime evidence;
3. `docs/project-current-state.md`;
4. this report and the 2026-08-01 audit;
5. active design and blueprint documents;
6. historical phase reports.

Do not describe blueprint intent, fixture success, UI route existence or historical test output as production implementation proof.
