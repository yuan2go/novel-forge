# Current Engineering State

Updated: 2026-08-03

Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`

Implementation evidence SHA: `ea6876476287e90a206ec4a10b2345a881f67656`

This is the current engineering-state entrypoint. Detailed evidence and limitations are recorded in [`architecture-closure-current-head-reaudit.md`](architecture-closure-current-head-reaudit.md), [`track-a-current-sha-validation.md`](track-a-current-sha-validation.md), [`track-b-book-design-authority-slice.md`](track-b-book-design-authority-slice.md) and [`d0-provider-qualification-probe.md`](d0-provider-qualification-probe.md).

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
- Provider v2 capability and control contracts;
- a machine-checked Track A integrity/fitness baseline;
- a typed Book/BookDesign Authority vertical slice;
- an isolated Track B Authority-only local runtime with PostgreSQL, MinIO, Outbox, grouped workers and fail-closed Legacy settings;
- a D0 Provider probe harness that refuses to promote fixture evidence.

The project is not yet a production-proven Autonomous Novel OS. The following remain unproven:

```text
real_provider_proven=false
real_cost_proven=false
longform_proven=false
multi_book_proven=false
platform_publish_proven=false
production_verified=false
```

## 2. Current Blockers

The repository-integrity blocker from the 2026-08-01 remote audit is resolved. Current blockers are:

1. D0 real Provider execution is `BLOCKED_MISSING_CREDENTIALS`; SDK, API key and auth profile are absent.
2. Three high-severity Admin production dependency findings require a Track E security update and rebuild.
3. Public authentication, backup/PITR, capacity/SLO and browser E2E are not proven.
4. Real Provider chapter, Judge promotion/calibration and all long-form acceptance gates remain false.

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

Default development settings and the default Compose topology still favor the Legacy surface. The new Track B topology provides migration-aware database readiness, object-store reachability, PostgreSQL Outbox identity, delivery-only queue declaration and grouped worker health for the minimal Book/BookDesign slice. Provider qualification is intentionally outside that runtime and is blocked at D0.

Therefore:

```text
minimal_authority_only_runtime_verified=true
authority_deployment_closed=false
legacy_production_write_blocked_for_track_b=true
legacy_production_write_retired_globally=false
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

The full current-SHA matrix was executed. Results: architecture 60/60; unit 1,169/1,169; acceptance 2/2; PostgreSQL Authority 141/141 with no skips; full integration 222 passed and 9 optional-online-backend skips; Admin 11 passed and one Playwright skip; Admin and Docker production builds passed. See the SHA-bound validation report for command-level details.

## 7. Current Maturity

| Area | Current maturity | Evidence limit |
|---|---|---|
| Command Kernel | High | production load and recovery drills remain |
| PostgreSQL Authority | High for tested contracts | production load, PITR and operational hardening remain |
| Chapter protocol | Medium-high | fixture proof, no real Provider quality proof |
| Canon / Story State | Medium | semantic and long-horizon accuracy unproven |
| Quality / Review | Medium | Judge calibration incomplete |
| Book coordination | Medium | not a complete autonomous whole-book loop |
| Long-form | Medium-low | deterministic recap and fixture chains only |
| Provider execution | Medium-low | D0 harness present; real auth, usage, cost, query/cancel/UNKNOWN remain blocked |
| Web product | Medium | authentication and deep browser E2E incomplete |
| Deployment / operations | Medium-low | Track B minimum runs locally; Track E hardening and default cutover remain |
| Multi-book production | Low | no real parallel production proof |

## 8. Immediate Priorities

### P0

Preserve Track A and the Track B Book/BookDesign baseline. Do not reopen parallel shared-kernel work or add a second runtime state machine.

### P1

1. Supply an approved Secret Reference/model and pass D0 without fixture promotion.
2. Fix the three high-severity Admin production dependency findings.
3. Only after D0 passes, enter Track C1 BookDesign → Active Plan.

### P2

1. Implement a whole-book production coordinator over Book/Volume/Arc/ChapterGroup/Chapter Authority.
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
