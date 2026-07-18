# Pre-Provider Runtime Hardening

Date: 2026-07-18. Evidence boundary: deterministic fixtures and local PostgreSQL only.

## Result

The Chapter and Content workers now share `AuthorityWorkerExecutionBoundary` and
`WorkerFailureClassifier`. Known task failures are persisted and isolated; a later
task in the same batch still runs. Programming defects are reported only after the
batch has been made durable. PostgreSQL proof is in
`test_content_authority_scheduler_recovery_postgres.py`.

Handler exceptions now terminate or checkpoint the fenced Attempt instead of
leaving it RUNNING until lease expiry. Retryable/final failures, cancellation, and
unknown external state use separate transitions. Output materialization remains
idempotent when a process fails before Completion. The shared Handler Runtime probes
the frozen deadline before execution, after execution, and immediately before
materialization, so an over-deadline local result cannot become an eligible output.

Frozen Operation, Attempt, Saga, and ExternalEffect deadlines are stored by
migration `0024`. Lease heartbeat renews ownership but does not change the business
deadline. A timeout before dispatch is retryable; a possibly-sent Provider request
becomes UNKNOWN and keeps its budget reservation. Chapter and Content worker loops
also invoke the idempotent deadline scanner; the root Saga freezes its own deadline.

ExternalEffect receipts and reconciliation can resume a waiting Operation. Manual
resolution is permissioned and idempotent. Cancellation records adapter results and
does not claim Provider cancellation when the adapter reports unsupported/unknown.
Root cancellation prevents unstarted children, signals active Attempts, and dispatches
cancel to active model/blob effects through their registered adapters.

Budget dimensions are explicit: `operation_total`, `chapter_total`,
`project_daily`, `project_total`, `provider_project_daily`,
`provider_project_total`, and `global_daily`. Daily scopes use an explicit timezone;
a transaction advisory lock serializes cap decisions. UNKNOWN and cost overruns
remain held for manual resolution. The focused suite covers more than ten budget
boundary/concurrency scenarios.

Release identity now requires a full 40-character hexadecimal Git SHA in API,
Definition generation, tests, and catalog evidence. Chapter/Content queries and
recovery commands require a trusted Principal and project scope.

## Evidence

- Commits: `c4b4346`, `353bff8`, `8d77444`, `ca30753`, `ed57fb3`, `97a4ba5`, `e52f980`, `159b1e2`.
- Migration: `v20260718_0024_pre_provider_runtime_hardening.py`.
- Fixture maturity: `integration_proven`.
- `real_provider_proven=false`; `production_verified=false`.

## Remaining limit

Real SDK timeout/cancel/query behavior has not been exercised. Provider-specific
reconciliation modes must be verified during the next credentialed single-chapter
stage.
