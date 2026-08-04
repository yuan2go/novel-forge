# Track B.5 Execution Semantics And Recovery Hardening

- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Implementation evidence SHA: `8d0c49973ad3f58ca325e3d39941fd89cb5d5f5e`
- Date: 2026-08-04
- Decision: ADR 0002, true Transaction Commands for Project, Book,
  BookDesign, and formal Planning binding

## Review findings

| Review question | Finding | Code evidence |
|---|---|---|
| Could business state commit before Attempt completion? | **Confirmed in the replaced path.** Admission, Attempt/Lease, business UoW, and `submit_attempt_result()` used separate transactions, leaving a crash window after business/outbox commit. | Historical regression in `test_crash_after_business_commit_cannot_leave_partial_command`; replacement in `command_kernel/service.py::execute_transaction_command` |
| Could exception handling mark an Attempt failed after business commit? | **Confirmed in the replaced path.** A post-commit exception entered Attempt failure handling even though business state was durable. | Same crash-window regression; Project and BookDesign no longer create an Attempt |
| Did authority/maintenance workers recover Project or BookDesign commands? | **No.** Their scope was deadline scanning and health/maintenance; they did not claim these READY Operations or execute their domain handlers. | Worker manifests and dispatch roots; Project/BookDesign are now request-thread Transaction Commands |
| Was execution classification drifting? | **Confirmed and corrected for formal production entries.** Project had worker metadata while executing inline; BookDesign declared a Transaction Command while manufacturing Attempt/Lease state. | Operation definitions, production-entry manifest, and classification fitness test |

## Final execution model

`execute_transaction_command()` owns one `AuthorityUnitOfWork` across:

```text
idempotency admission
→ domain validation
→ business rows / typed AssetVersion / projection
→ audit + outbox
→ Operation SUCCEEDED with replay result
→ PostgreSQL commit
```

It does not create an Attempt, acquire a Lease/Fence, enqueue work, or expose a
`RUNNING` state. A failed checkpoint rolls the entire transaction back. A
same-key/same-digest replay returns the stored result; a same-key/different
digest is rejected. A fault after commit but before the HTTP response models
response loss and is recovered by replay.

Provider/model calls and other uncertain external work remain Durable Job,
Saga, or External Effect work. The generic authority and maintenance workers
therefore do **not** claim recovery credit for Transaction Commands.

## Fault-injection proof

Project and BookDesign integration tests inject the following exact points:

| Checkpoint | Required durable result |
|---|---|
| `before_admission` | no Operation, business row, asset, audit, or outbox |
| `after_admission_before_business_mutation` | all rolled back |
| `after_domain_validation` | all rolled back |
| `after_asset_version_insert` | all rolled back |
| `after_business_projection_update` | all rolled back |
| `after_outbox_insert` | all rolled back |
| `before_operation_completion` | all rolled back |
| `after_operation_completion_before_response` | all committed and replayable |

The assertions inspect Operation, Attempt, Book/Project, BookDesign candidate,
AssetVersion, Decision, Activation, audit, and outbox. Successful Transaction
Commands have one `SUCCEEDED` Operation and zero Attempts.

Idempotency coverage includes same-key/same-digest replay,
same-key/different-digest rejection, concurrent duplicate admission, HTTP
timeout/retry, and committed-response-loss replay.

Formal `planning.binding.activate` follows the same model. It owns its own
Operation, expected active version, replacement decision, audit, and outbox;
it no longer reuses the StoryDesign activation Operation.

## Recovery semantics

These evidence dimensions are intentionally separate:

- `persistent_state_restart_proven=true`: committed authority state is read
  from PostgreSQL after application reconstruction.
- `transaction_command_atomicity_proven=true`: precise fault tests prove only
  all-rolled-back or all-committed outcomes.
- `inflight_command_recovery_semantics_proven=true` for Transaction Commands:
  an uncommitted in-flight request disappears by rollback; a committed request
  is recovered by idempotent replay. This is not a worker-resume claim.
- generic worker recovery of arbitrary Project/BookDesign READY Operations is
  not applicable because those Operations are no longer worker work.

## Migration and scope evidence

Migration 0052 removes the `legacy-unversioned.v1` default after backfill and
makes `schema_version` explicit and `NOT NULL`. It adds Project/Workspace/Book
and AssetVersion scope guards for BookDesign and Planning links. Migration 0054
adds indexes supporting the new composite foreign keys. The migrations are
forward-only, declare preflight/forward-fix/backup requirements, and do not
invent downgrade behavior.

An isolated database was initialized at Migration 0051 and upgraded through
the actual current migration head. The result had no missing or extra migration
IDs, and `authority_asset_version.schema_version` had no default and was
`NOT NULL`. Clean-install and cross-scope rejection are covered by PostgreSQL
integration tests.

## Evidence classification

```text
architecture_defined=true
implementation_present=true
unit_verified=true
postgres_integration_verified=true
local_deployment_verified=VALIDATION_PENDING
external_execution_proven=false
longform_proven=false
production_verified=false
```

The final command matrix and exact counts are recorded in the current
engineering-state report. This report does not use Fixture evidence as a
production or real-provider claim.
