# ADR 0002: Transaction Commands Are Single PostgreSQL Transactions

- Status: Accepted
- Date: 2026-08-04
- Baseline: `921d681635e0ce408024cf8335ca516971241660`

## Context

Project and Book/BookDesign are short, deterministic PostgreSQL commands with no
external side effect. The previous implementation admitted an Operation, moved
it to READY, created an Attempt and Lease, executed the handler inline in the
HTTP process, committed business state and Outbox, and only then submitted the
Attempt result in another transaction.

That mixed model had a demonstrated crash window: Book and AssetVersion state
could be committed while the Operation was not SUCCEEDED. The exception path
could then mark the Attempt failed. The runtime-group workers did not consume or
recover these Operations; they only scanned deadlines and wrote health state.

## Decision

Adopt true Transaction Command semantics for:

- Project create/update/transition and binding changes;
- Book create;
- BookDesign propose/decide/activate.

Admission, domain validation, business projection, AssetVersion, decision or
activation, audit/event/outbox, completion-contract evaluation, replay result,
and `Operation=SUCCEEDED` share one `AuthorityUnitOfWork` transaction.

A Transaction Command:

- remains ADMITTED only inside the uncommitted transaction and transitions
  directly to SUCCEEDED at commit;
- creates no Attempt, Lease, Fence, queue delivery, or RUNNING state;
- returns the persisted result for a same-key/same-digest replay;
- rejects a same-key/different-digest request;
- rolls back the whole command at every pre-commit fault point;
- can survive a lost HTTP response because the retry reads the committed result.

The kernel owns this protocol through `execute_transaction_command()` and
reuses `admit_command_in_uow()`. Domain applications provide only their bounded
handler and named fault checkpoints.

Provider calls, model execution, and other long or uncertain work remain
Durable Jobs, Sagas, or External Effects and continue to use Attempt/Lease/Fence
and reconciliation.

## Recovery semantics

`persistent_state_restart_proven` means committed PostgreSQL state survives a
process restart. It does not prove recovery of in-flight work.

For Transaction Commands, `inflight_command_recovery_semantics_proven` means an
in-flight process loss leaves no command state to recover because PostgreSQL
rolls the open transaction back. A post-commit response loss is recovered by
idempotent replay.

For Durable Jobs and External Effects, in-flight recovery still requires a real
worker claim/reclaim path. The generic runtime-group heartbeat/deadline loop is
not such a path.

## Consequences

- The former business-commit/Attempt-completion inconsistency is removed.
- Completion contracts are evaluated before the atomic terminal transition.
- Architecture fitness must reject Attempt/Lease imports from transaction
  command applications and reject worker definitions executed inline by APIs.
- Old non-terminal hybrid Operations, if any exist outside ephemeral test data,
  require an explicit migration/reconciliation procedure; the new runtime does
  not guess or re-run them.

