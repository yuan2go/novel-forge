# Autonomous Novel OS Phase 1 Independent Audit

Date: 2026-07-12  
Auditor conclusion: `failed` — neither `engineering_audit_passed` nor `phase_01_verified_external` is warranted.

## Overall conclusion

Current code contains useful local-first production foundations, but it is not the
Phase-1 Autonomous Novel OS described by WP-1 through WP-7.  The principal
evidence is current code and a new local run, not prior completion reports.

- A real Codex CLI smoke succeeded with `CODEX_HOME=~/.codex-claude`; login is
  valid and no API key was used.
- The project PostgreSQL service was started with `make infra-up`; formal
  migrations completed.  Schema inspection found asset-sync and MKAOS tables,
  but none of the required operation/event/outbox/UoW tables.
- A new isolated 10-chapter Codex run started at
  `.local/phase01-real10-audit`. It created a parent
  `production-operation-production-operation-chapter-production-start-0b9285ec.json`
  and Codex ModelCallLogs, then failed in chapter 1 draft. The submitted prompt
  was 1,663,947 characters, above Codex's 1,048,576 limit.
- Deterministic/mock chapter reports and historical assets are not counted as
  real-provider proof.

The audit repaired two deterministic defects: chapter sequences now create
chapter runs through the Kernel, and the Codex adapter rejects unsafe prompt
sizes before launching a real provider subprocess. Neither repair substitutes
for the missing production PostgreSQL authority, lifecycle command model,
evidence contract, calibration, or long-chain acceptance.

## WP scorecard

| WP | Conclusion | Current evidence | Blocking gap |
| --- | --- | --- | --- |
| WP-1 Kernel convergence | partial | `production_kernel/service.py`; commit `857f4ea`; Kernel contract tests | registry covers only selected child families; legacy API/Workflow/Scheduler direct controls remain |
| WP-2 Lifecycle/reconciliation | failed | bounded local `pause/resume/cancel/recover`; read-only reconciliation | no versioned command store, lease, optimistic concurrency, timeout/compensate/dead-letter/replay contract or concurrent integration proof |
| WP-3 PostgreSQL UoW/outbox | failed | real PostgreSQL migration/status and schema query | Postgres is LocalStorage asset sync, not operation authority; required tables/repos/atomic transaction are absent |
| WP-4 production evidence | failed | ModelCallLog/trace files are written on some paths | no universal ContextManifest/route/cost completion enforcement; prompt serializes unbounded nested context |
| WP-5 Golden/human calibration | partial | real Codex smoke; local calibration readiness code/tests | no verified six-genre Golden set or two-real-human >=0.8 agreement evidence |
| WP-6 real 10 chapters | failed | new real Codex attempt and report `/private/tmp/phase01-real10-audit.md` | failed chapter 1; no single recoverable successful 10-chapter acceptance operation |
| WP-7 controlled 30 chapters | not_implemented | only generic bounded sequence and historical deterministic reports | no real 30-chapter operation, six-batch resume proof, or trend evidence |

## Evidence matrix

| Category | Evidence |
| --- | --- |
| Git baseline | branch `feat/v7-content-intelligence-and-longform-proof`; audit commits `857f4ea`, `5481f78` |
| Provider | `CODEX_HOME=~/.codex-claude codex --version` → `codex-cli 0.144.1`; `codex login status` → ChatGPT login; Adapter smoke returned `provider=codex`, `fixture=false` |
| PostgreSQL | `make infra-up`; `PostgresAssetStore.initialize()`; read-only `pg_tables`/`pg_indexes` query |
| 10 chapter run | `.local/phase01-real10-audit/data/runs/production-operation-production-operation-chapter-production-start-0b9285ec.json`; failed task status and ModelCallLogs; `/private/tmp/phase01-real10-audit.md` |
| Kernel repair test | `tests/unit/test_context_and_production_chain.py::ContextAndProductionChainTests.test_chapter_production_sequence_runs_10_chapter_v1_acceptance` |
| Provider repair test | `tests/unit/test_model_adapter.py::MockModelTests.test_codex_input_limit_fails_before_provider_process` |

## Production Kernel and lifecycle findings

`production_entrypoint_audit()` reports no direct calls only for its restricted
set: `dispatch_chapter_production`, `execute_workflow`, `dispatch_agent_run`,
and `run_loop`.  It does not constitute a complete entrypoint graph. Current
source retains direct child-control compatibility in:

- `api/routers/production_chain.py` (legacy resume/pause/cancel/recover);
- `modules/workflow_nodes/service.py` (chapter production resume);
- `modules/agent_scheduler/service.py` (chapter production resume).

`control_production_operation()` supports only pause/resume/cancel/recover,
has no persisted command id/version/expected-version, and writes LocalStorage
parent projections. This fails WP-2's concurrency, late-result, lease, retry,
compensation, dead-letter, and replay requirements.

## PostgreSQL and Outbox findings

The live database has `nf_assets`, `nf_asset_versions`, `nf_projects`,
`nf_task_statuses`, and MKAOS/review tables. It does not have
`production_operation`, `production_operation_command`, `state_event`,
`state_snapshot`, `outbox_event`, `idempotency_record`, `operation_lease`,
`operation_attempt`, `reconciliation_report`, or `audit_log` tables.

`storage/postgres.py` synchronizes JSON assets into `nf_assets`; it is not an
atomic UoW and cannot prove transaction rollback, `SKIP LOCKED`, consumer
idempotency, dead-letter handling, or projection rebuild. `state_bus/outbox.py`
is LocalStorage read/modify/write and cannot provide multi-worker atomic claim
semantics. WP-3 is therefore failed, not externally blocked.

## Provider and evidence findings

`model_adapters/providers.py` uses argument arrays, explicit working directory,
temporary schema/output files, timeout polling, and no `shell=True` for Codex.
The new input preflight is commit `5481f78`. It reports a context-budget breach
before provider invocation. The underlying context construction still lacks a
universal compacted manifest boundary; a 4 KB `actual_context` coexisted with a
1.66 MB serialized provider prompt.

The successful smoke is `real_provider` only for that individual call. The
failed long-chain run is also a real attempted provider run, but cannot be
classified as successful acceptance. No fixture is credited as real provider.

## Acceptance and calibration findings

Historical `v1-chapter-sequence-slow-acceptance.md` is explicitly mock/default
local evidence. It is not accepted for WP-6. No current successful real 10- or
30-chapter run exists. There is no verified two-human annotation ledger,
annotator roles, disagreement queue, or >=0.8 agreement computation tied to a
production calibration reference.

## Automated repair record

| Commit | Repair | Retest |
| --- | --- | --- |
| `857f4ea` | Route each chapter in `run_chapter_production_sequence()` through `dispatch_production_operation()` | sequence and Kernel contract focused tests passed |
| `5481f78` | Add fail-closed Codex input-size preflight and invalid-config test | focused adapter tests passed |

## Test status

Focused suites passed: Kernel contract, sequence contract, Codex adapter and
provider hard-stop suites (53 focused tests before the later input-limit test;
the two new/fake-Codex tests passed). `make lint`, `make validate`,
`make check-skills`, and `git diff --check` passed. Full Python, web test, and
web build have not reached a reliable final completion result in this audit run
and must not be claimed as passed.

## P0/P1 remaining work and 100-chapter decision

P0: PostgreSQL production UoW/outbox, universal lifecycle commands/concurrency,
universal production evidence, context compaction/manifest enforcement, real
10-chapter recovery, and real 30-chapter acceptance.

P1: Golden-set coverage and two-human calibration evidence.

Do not enter the 100-chapter phase. The required next milestone is a small
PostgreSQL-backed operation/event/outbox vertical slice with a bounded
ContextManifest passed to Codex, followed by a fresh chapter-1 real call and
then a recoverable 10-chapter run.
