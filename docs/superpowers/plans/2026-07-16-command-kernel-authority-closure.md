# Command Kernel Authority Closure Implementation Plan

> Execution authority: the user-approved Task 0–7 specification dated 2026-07-16.
> This plan uses targeted PostgreSQL fixtures and does not run costly long-form provider proof.

## Baseline

- Branch: `feat/v7-content-intelligence-and-longform-proof`
- Starting source baseline: `32250ff8df20bea7727fce730759e6b0c2f9d5fe`
- Preserve the existing Task 3 regression expectation committed at that HEAD.
- Current generated authority evidence is stale: 63 definitions in the checked-in catalog versus 84 definitions from the current generator.

## Execution slices

1. Make authority evidence generation self-consistent with its source snapshot, regenerate the coverage manifest, catalog, legacy action map, and Markdown summaries, and verify architecture checks.
2. Add a forward-only migration that project-scopes ExternalEffect idempotency and converges legacy Blob effect/dispatch states onto the generic protocol.
3. Route Blob upload planning, dispatch, receipt ingestion, verification, failure, retry, stale fencing, and duplicate receipt behavior through the generic ExternalEffect runtime. Keep only an explicit, non-default compatibility boundary for legacy callers.
4. Define completion policies and harden generic dispatch exception, cancellation, receipt, reconciliation, dead-letter, replay, and compensation semantics without leaving held leases.
5. Keep successful worker Attempts in `RESULT_SUBMITTED` until the frozen Completion Contract is satisfied; finalize Attempt and Operation together and preserve retry/resume semantics.
6. Add operation-scoped AssetVersion output binding, effective qualification evaluation, action-specific audit evidence, and role-aware Blob requirements.
7. Replace Saga prototype shortcuts with standard child admission, compensation child operations, evidence-producing transitions, coordinator lease/fencing, and forward recovery foundations.
8. Document authority/projection ownership and prepare the PostgreSQL-only single-chapter operation/output-binding foundation without executing long-form proof.
9. Run targeted tests after each slice, then the prescribed authority/integration/unit/lint/validate/skill checks, produce the closure report, review diffs, and create logical commits.

## Invariants

- No `Attempt=SUCCEEDED` while its `Operation` is in a waiting state.
- Stable ExternalEffect keys are unique only within one project and effect type.
- Adapter exceptions and cancellation cannot leave a live orphan dispatch lease.
- A provider acknowledgment is not final business success unless the frozen completion policy says it is synchronous-final.
- Completion may consume only explicitly operation-bound AssetVersions and the latest effective qualification.
- Blob dispatch has one production state machine, one lease/fencing path, and one receipt inbox.
- Every material Operation/Saga transition produces StateEvent, AuditLog, and Outbox evidence.
- LocalStorage remains compatibility/projection infrastructure; new authority writes use the PostgreSQL Command Kernel.
