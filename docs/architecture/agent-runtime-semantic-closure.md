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

The Agent worker scans fresh, retryable, frozen, waiting-external,
reconciliation, and cancellation work. A takeover resolves the frozen
WorkOrder and Runtime Binding before execution and keeps the stable idempotency
key. The current Command Kernel Fence authorizes recovery progress, exact
Domain commit, and final Attempt submission. Existing ExternalEffect state is
queried first; UNKNOWN or reconciliation-required state is not converted into
success and is not blindly redispatched.

Post-Provider recovery is idempotent at Candidate, Domain AssetVersion,
Authority Decision, Collaboration Commit, and Attempt result boundaries. A
Domain asset already present after a crash is validated by exact operation,
attempt, content hash, and current committing fence before Decision/Commit
finalization; the Runtime Binding retains the original execution fence.

## Evidence ceiling

Scripted Fixture Provider runs can prove PostgreSQL orchestration, recovery,
fencing, and lineage mechanics only. They do not prove a real Provider, longform
quality, or production readiness. Required non-claims remain:

- `REAL_PROVIDER_PROVEN=false`
- `LONGFORM_PROVEN=false`
- `PRODUCTION_VERIFIED=false`
