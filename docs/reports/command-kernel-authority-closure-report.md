# Command Kernel Authority Closure Report

Date: 2026-07-16

## 1. Baseline

- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Starting HEAD: `32250ff8df20bea7727fce730759e6b0c2f9d5fe`
- Ending implementation HEAD: `2c536e39ea7d1c012198cd21b4a43b883b005b47`
- HEAD-bound evidence commit: `d6fee4a`
- Report pre-commit HEAD: `d6fee4a`
- Starting worktree: clean after preserving the existing Task 3 regression change that had been committed concurrently at `32250ff`
- Final worktree target: clean after this report commit

Current Authority coverage:

| Measure | Result |
|---|---:|
| OperationDefinitions | 84 |
| Entrypoint-mapped definitions | 17 |
| Migration candidates | 67 |
| Families | 19 |
| Receiver-aware findings / legacy actions | 2,125 |
| Mapped side effects | 480 |
| Unmapped side effects | 0 |
| Unknown classifications | 4 |

The prior `63 / 17 / 46` catalog was stale. The refreshed artifacts are bound to
source commit `2c536e3` and source tree
`e1223c2ea1565a9338f910354d8cea8e937dcf64`.

## 2. Fixed Problems

### Blob / ExternalEffect — Completed

- Removed the legacy Blob repository dispatcher implementation.
- Kept the old Blob-shaped public functions only as translation boundaries;
  they now call Generic ExternalEffect prepare/receipt/reconciliation paths.
- Blob upload uses one intent, lease/fencing dispatcher, receipt inbox, Blob
  projection, verification, and AssetVersion binding chain.
- Legacy `DISPATCHABLE / IN_FLIGHT / SENT` rows are migrated to the generic
  protocol; new runtime code does not emit those states.

### Project scope — Completed

- Added `project_id` to authoritative ExternalEffect rows.
- Replaced global `(effect_type, stable_idempotency_key)` uniqueness with
  `(project_id, effect_type, stable_idempotency_key)`.
- Added cross-project replay coverage with the same stable key and payload.

### Cancel / lease / adapter exception — Completed for the generic worker path

- Adapter exceptions before known submission become retryable failures.
- Exceptions after known submission and untyped exceptions conservatively
  become `UNKNOWN`.
- Both paths record evidence and release the HELD lease before returning a
  typed Kernel error.
- Cancellation changes dispatch state, releases HELD leases, and routes
  reversible work to compensation or uncertain work to reconciliation.
- Stale fencing-token results and heartbeats remain rejected and audited.

### Receipt semantics — Completed for synchronous-final and callback flows

- Added frozen completion policies: `synchronous_final`, `async_ack`,
  `callback_receipt`, and `poll_reconciliation`.
- A successful adapter call first becomes `DISPATCHED / ACKNOWLEDGED`.
- Synchronous-final work materializes a verified receipt through the generic
  inbox before business success.
- Callback work remains acknowledged until a separate receipt arrives.
- Receipt rows distinguish `RECEIVED / VERIFIED / REJECTED`; current accepted
  runtime receipts persist as `VERIFIED`.

### Compensation — ExternalEffect foundation completed

- `compensate_external_effect()` creates a project-scoped, linked,
  idempotent compensation Effect.
- Compensation dispatch uses the same adapter, lease, receipt, and completion
  path and transitions the original Effect to `COMPENSATED`.

### Attempt / Completion — Completed

- Worker success now transitions Attempt to `RESULT_SUBMITTED` first.
- Missing approval/child/effect/gate/asset/blob/evidence keeps Attempt at
  `RESULT_SUBMITTED` while Operation enters the appropriate waiting state.
- Completion finalization moves Attempt and Operation to `SUCCEEDED` in the
  same PostgreSQL transaction.
- The invalid `Attempt=SUCCEEDED / Operation=WAITING_GATE` assertion was
  removed and replaced with the correct lifecycle proof.

### Operation output binding — Completed

- Added `authority_operation_output_asset` with Operation, Asset,
  AssetVersion, output key, role, and content hash.
- Completion only discovers explicitly bound outputs of the current Operation.
- Project-level unrelated historical Assets cannot satisfy Completion.

### Qualification / audit / Blob evidence — Completed

- Qualification evaluation now uses the latest effective decision per
  AssetVersion, so `ELIGIBLE -> REVOKED` no longer passes.
- Completion supports specific `required_audit_actions`; admission audit alone
  cannot satisfy generic audit evidence.
- Blob requirements support status, role, and minimum count over bound output
  AssetVersions.

### Saga coordinator — Partially completed

- Added coordinator owner, lease id, fencing token, expiry, heartbeat timestamp,
  and forward-recovery attempt count.
- Saga coordination acquires/releases a fenced lease for every tick.
- Retryable children enter `FORWARD_RECOVERY` and return to `READY` with
  transition evidence.
- Coordinator-driven child/root changes now produce StateEvent, AuditLog, and
  Outbox evidence.
- A new integration proof admits a real child through `admit_command`, runs an
  Attempt, submits a worker result, evaluates Completion, and completes Saga.

## 3. Remaining Gaps

| Area | Status | Remaining work |
|---|---|---|
| Attempt/Completion state machine | Completed | No known contradictory success/waiting state remains. |
| Generic Blob dispatch | Completed | Remove the deprecated Blob-shaped translation functions after callers migrate. |
| Project-scoped Effect replay | Completed | None in current P0 boundary. |
| Adapter exception/orphan lease | Completed | Provider-specific adapters still need production conformance tests. |
| Receipt completion policies | Partially Completed | Add dedicated runtime behavior/tests for `async_ack` and `poll_reconciliation`, plus an explicit receipt-reject command. |
| Effect reconciliation/dead-letter | Partially Completed | UNKNOWN, reconciliation and exhaustion exist; operator replay/manual-intervention commands and evidence UI remain. |
| Saga compensation | Partially Completed | Saga still plans `REQUIRED` in reverse order; it does not yet automatically admit and execute compensation child Operations. |
| Saga lease | Partially Completed | Per-tick fencing exists; a long-running coordinator heartbeat/takeover command is not yet exposed. |
| Unified Operation transitions | Partially Completed | Saga repository updates now emit evidence, but `set_ready()` and `complete_root()` are not yet routed through the shared lifecycle CAS service. |
| Authority/projection migration | Partially Completed | The target boundary is documented; legacy runtimes remain operational. |
| PostgreSQL-only chapter slice | Deferred | Evidence contract/runbook exists; node handlers and migration adapters are not implemented end to end. |
| High-cost long-form proof | Deferred | Intentionally not run in this architecture-fix round. |

## 4. Tests

Final successful commands:

| Command | Passed | Failed | Skipped |
|---|---:|---:|---:|
| targeted Completion PostgreSQL suite | 4 | 0 | 0 |
| targeted lifecycle unit suite | 3 | 0 | 0 |
| targeted ExternalEffect + Blob suite | 19 | 0 | 0 |
| targeted combined authority protocol suite | 35 | 0 | 0 |
| Saga PostgreSQL suite | 6 | 0 | 0 |
| `python scripts/run_authority_postgres_tests.py` equivalent using `.venv` | 85 | 0 | 0 |
| PostgreSQL integration discovery | 103 | 0 | 0 |
| full unittest discovery | 939 | 0 | none reported |
| authority/architecture guardrails | 12 | 0 | 0 |
| `make lint` | passed | 0 | n/a |
| `make validate` | passed | 0 | n/a |
| `make check-skills` | passed | 0 | n/a |
| `git diff --check` | passed | 0 | n/a |

Two failures were found and corrected during development:

1. targeted tests initially asserted pre-convergence Effect/dispatch states;
2. the full Authority suite exposed an old schema fixture that omitted the new
   required Effect `project_id`.

Both failing sets were fixed and rerun successfully. No real model-provider or
long-form chapter acceptance was executed.

## 5. Architecture State

### Is LocalStorage still production authority?

Yes, for substantial existing Novel OS business chains. This round does not
claim PostgreSQL-only production authority across the application.

### What PostgreSQL Authority now owns

- Command admission and frozen definitions;
- Operation/Attempt lifecycle and Completion finalization;
- authoritative Asset/AssetVersion/qualification and operation output binding;
- Blob reservation/verification and Generic ExternalEffect-backed upload;
- project-scoped ExternalEffect intent, dispatch lease/fencing, receipt,
  reconciliation, dead-letter, cancellation, and compensation foundation;
- Operation graph and fenced Saga coordination foundation.

### What is still not migrated

- existing Chapter Production Bus business persistence;
- Context Builder, Review/Revision, Canon, Quality, and Publishing chains as one
  PostgreSQL-only operation graph;
- LocalStorage JSON authority and `nf_*` synchronization paths across legacy modules;
- AgentRun, WorkflowRun, LoopRun, ChapterProductionRun, and ProductionOperation
  still have compatibility/runtime write responsibilities rather than being
  purely rebuildable projections.

### Next PostgreSQL vertical slice

One deterministic chapter from ChapterPlan through ContextBundle, Draft,
Review, Revision, Canon, Quality Gate, and Export, using fake provider/object
store adapters and operation-scoped output evidence.

## 6. Architecture Review

### Standards axis

- Passed: forward-only migrations, typed command contexts, explicit Kernel
  errors, project scoping, transaction boundaries, idempotency, fencing,
  StateEvent/Audit/Outbox evidence, and no new framework dependency.
- Remaining judgement call: ExternalEffect runtime remains a large orchestration
  module and should be split by dispatch, receipt, reconciliation, and
  compensation after semantics stabilize.
- Remaining hardening: Saga direct repository status updates should converge on
  the common lifecycle CAS abstraction.

### Specification axis

- Completed: Tasks 0, 1, 3, and 4; core Task 2 behavior; Task 6 boundary docs.
- Partial: Task 2 operator commands and all completion-policy variants; Task 5
  automatic compensation children; Task 7 handler implementation.
- No scope creep into new genre engines, Agent roles, UI consoles, publishing
  platforms, or high-cost long-form generation.

## 7. Next Recommended Work

The single highest-priority remaining package is:

**Automatic Saga compensation child execution through standard Command Kernel admission.**

It should:

1. select compensations in strict reverse order;
2. admit each compensation child idempotently from its registered definition;
3. run it through Attempt/Completion rather than SQL fixtures;
4. link it through `compensation_operation_id`;
5. retry partial failures under coordinator fencing;
6. enter manual intervention only with explicit evidence;
7. then use the same mechanism in the first PostgreSQL-only single-chapter fixture.
