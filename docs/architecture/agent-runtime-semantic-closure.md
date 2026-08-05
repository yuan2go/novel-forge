# Agent Runtime Semantic Closure

## Runtime boundary

Novel Forge has two legal Agent execution embeddings. Chapter model nodes keep
their Chapter Operation, Attempt, Lease, and Fence under `CHAPTER_AUTHORITY`.
Standalone `agent.candidate.execute` operations keep their own Command Kernel
Attempt under `AGENT_RUNTIME_AUTHORITY`. An embedded Chapter turn never admits
a nested standalone Agent operation.

Both embeddings use `AgentTurnExecutionCoordinator` for immutable turn freeze,
PEP evidence validation, `AgentOutputEnvelope` validation, Candidate persistence,
and idempotent finalization. It owns no status table, Attempt, Lease, Fence,
ExternalEffect, or Provider runtime.

## Candidate and Domain commit

An Agent output is always a Candidate. The Chapter Domain Handler remains the
only writer of the Chapter `AssetVersion`. After that existing version is
materialized, the coordinator records an `ACCEPTED` Authority Decision and an
exact Collaboration Commit that references the same version. The Commit binds
Candidate, Decision, Domain Operation, Attempt, the current committing Fence,
AssetVersion, content hash, and receipt. The
Runtime Binding separately preserves the PEP execution Fence. It never
materializes another Chapter asset.

The query projection derives Candidate and Domain resolution independently.
A successful standalone candidate operation without a Domain consumer reports
`CANDIDATE_READY` and `NOT_REQUESTED`, never `DOMAIN_COMMITTED`. Agent-bound
Chapter asset lineage reports `EXACT_COLLABORATION_COMMIT` only when the exact
Commit foreign-key path exists; root-workflow proximity remains weaker evidence.

## Recovery

The frozen PEP identity and the current recovery authority are separate facts:

- `execution_fencing_token` is the original Fence frozen into the
  `InputManifest`, `ExecutionRequest`, `ExecutionHandle`, Runtime Binding,
  Provider request, and ExternalEffect evidence. It is immutable and does not
  grant a restarted worker current execution authority.
- `recovery_fencing_token` is the newest HELD and unexpired Command Kernel
  Lease/Fence owned by the recovery worker. It authorizes query, cancellation,
  result consumption, Candidate/Decision/Commit finalization, and Attempt
  result submission. It never replaces the Provider execution Fence.

`Frozen Execution Identity + Current Worker Lease/Fence` produces one immutable
`authority_execution_recovery_authorization` fact. The fact binds both fences,
the existing ExternalEffect, the recovery worker, and one explicit action. The
normal PEP `submit()` path remains strict: a stale execution Fence is rejected.
Recovery uses the separate `resume_planned_execution`,
`recover_existing_execution`, or `cancel_existing_execution` semantics. No
second Attempt state machine, ExternalEffect, PEP request, or Provider request
is admitted.

Chapter and standalone schedulers use the same ExternalEffect classification:

| Existing Effect | Recovery action |
|---|---|
| `READY` | authorize and dispatch the original planned request once |
| `DISPATCHING` / `DISPATCHED` | query the original Provider request first |
| `UNKNOWN` / `RECONCILIATION_REQUIRED` | query, cancel, or wait for operator reconciliation; never blind retry |
| `SUCCEEDED` | consume durable evidence and resume idempotent projections without Provider dispatch |
| final failure / cancelled | apply the frozen Operation retry, terminal, cancellation, or dead-letter policy |

Post-Provider recovery is idempotent at budget settlement, model/cost evidence,
Candidate, Domain AssetVersion, Authority Decision, Collaboration Commit, and
Attempt result boundaries. A Domain asset already present after a crash is read
as the atomic handler result instead of being recomputed under a new Fence. If
the Collaboration Commit already exists, it keeps its historical committing
Fence while the current recovery Fence authorizes only the remaining Attempt
finalization.

## Retry and supersession

Same-Attempt lease takeover retains the Attempt, ExternalEffect, Provider
request, Runtime Binding, WorkOrder, Session, and Candidate identities; only
the Lease and recovery Fence advance.

A retry after `FAILED_RETRYABLE` creates a new Attempt and therefore a new
ExternalEffect, Provider budget reservation, Runtime Binding, WorkOrder,
Session, and Candidate. The old Candidate remains immutable and receives one
`authority_agent_candidate_supersession` relation to the new Candidate. Its
Session terminates as `FAILED`; it cannot later commit. Query projections show
every Attempt and select only the non-superseded Candidate as effective.
Superseded and standalone-candidate-ready entries remain visible but are not
counted as Domain recovery backlog.

## Crash and quality gates

The PostgreSQL crash matrix destroys the old Scheduler/Application, clears
process-local gateway sessions and pools, expires the old Lease, and restarts
with a new worker before recovery. Its nine checkpoints cover work-order and
binding freeze, Effect planning, Provider success, Candidate persistence,
Domain materialization, Decision, Collaboration Commit, and pre-result
submission. The test-only crash derives from `BaseException`, so ordinary
`except Exception` handling cannot convert it into a normal worker failure.

Authority production surfaces are Ruff-clean through `make lint-authority`.
Repository-wide historical debt is explicit in
`architecture/manifests/ruff-legacy-baseline.json`; `make lint-ratchet` rejects
new diagnostics, increases, and edits to a baseline file that do not reduce its
total.

## Evidence ceiling

Scripted Fixture Provider runs can prove PostgreSQL orchestration, recovery,
fencing, and lineage mechanics only. They do not prove a real Provider, longform
quality, or production readiness. Required non-claims remain:

- `REAL_PROVIDER_PROVEN=false`
- `LONGFORM_PROVEN=false`
- `MULTI_BOOK_PROVEN=false`
- `PRODUCTION_VERIFIED=false`
