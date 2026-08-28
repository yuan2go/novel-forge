# Runtime

## Process entry points

`novel-forge serve-api` constructs the full Authority API. `compose.yml` runs migrations first, then the API, then the specialized worker fleet. `novel-forge authority-migrate` is the schema migration command; `novel-forge-migrate` is a separate offline data-import program.

The current worker groups are:

| Worker | Responsibility |
|---|---|
| Agent Authority | Executes bounded multi-turn Agent sessions and isolated migration-compatible Agent candidates on Operation/Attempt/Lease/Fence. |
| Chapter Authority | Coordinates chapter saga jobs and recovery. |
| Content Authority | Materializes non-Chapter authority handler outputs. |
| Source Authority | Commits governed source transformations and deconstruction observations. |
| Source Import | Acquires, normalizes, chunks, and records source repository imports. |
| MKAOS Authority | Commits, approves, and packs abstract knowledge candidates. |
| Book Authority | Advances one deterministic Book coordination action per tick. |
| Book Followup Authority | Admits and executes Reader/Recap sidecars from frozen acceptance snapshots without consuming Book coordination capacity. |
| Outbox | Delivers durable outbox effects and owns only delivery state. |
| Maintenance | Reconciliation and maintenance runtime group. |

The manifest is authoritative for worker identity, queue, health, and recovery class.

## Command path

An API router authenticates a principal, validates a typed request, and calls an Authority application. Admission freezes identity, scope, input assets, idempotency, definition version, trace, and causation. Atomic commands execute in one governed transaction; durable jobs create RuntimeJobs for workers; sagas coordinate child operations without copying child Attempt state.

Workers claim jobs with leases and fences. Provider and object-store work is
represented by `ExternalEffect`; receipts are reconciled before retry. A lost
lease or late result cannot commit over a newer fence. Generic expired-lease
takeover is available only when the owning domain's execution contract permits
the same operational execution to continue. Successful handler output is
materialized as a versioned asset and linked to the operation.

## Book and Chapter coordination

Book coordination is a saga entry (`book.production.coordinate`). The Book supervisor performs one production-critical business action per tick. Its reads use `PostgresBookProductionQuery`; mutations call `PostgresBookAuthority`, Planning Authority, ChapterGroup Authority, or PlanChange Authority. It does not execute direct SQL, own Chapter Attempts, or execute Reader/Recap provider work.

After Chapter acceptance atomically commits AcceptedOutcome, Story State, Canon, and the accepted cursor, a separate `book_followup` RuntimeJob group admits Reader Outcome and Longform Recap Operations from the immutable snapshot stored with that acceptance. The Book Followup worker uses the same Command Kernel Attempt/lease/fence and shared Production Execution Composition as other provider work, but has an isolated deployment process and database pool. Followup completion cannot mutate the Book cursor or active future plan; any Replan output remains an Authority-pending proposal.

Acceptance always returns the Book to `READY`, including the final Chapter. This lets any mandatory ChapterGroup production closure commit before the supervisor moves the Book to terminal `COMPLETED` and coordinates the root Saga.

`GET /product/production/book-authority/runs/{book_run_id}/progress` is a PostgreSQL read projection. It separates the last accepted narrative progress timestamp and production blocker from non-blocking sidecar admission/Operation backlog.

Chapter production is a 22-node explicit saga (`chapter.slice.run`), including
ExecutionIntent, Memo, immutable RetrievalResult, and deterministic Best Candidate selection. Chapter-specific
binders and policies turn frozen inputs into work orders. All provider and
object-store execution comes from the shared production execution composition.

## Book Opening execution and recovery

This section records the accepted contract; engineering status still depends on
the migration and test evidence described in the architecture overview. Book
Authority owns the Book Opening aggregate's business lifecycle, execution
generation, current execution binding, semantic checkpoint cursor and recovery
authorization.
RuntimeJob owns only the corresponding operational Job, Attempt, Lease, fence,
checkpoint and result. A `RUNNING` opening binds one exact execution generation
to one current RuntimeJob/Attempt/Lease/fencing token. PostgreSQL foreign keys,
uniqueness and checks protect this relational identity; claim, heartbeat,
checkpoint, complete, fail, cancel and recovery commands also verify
`lease_expires_at` at transaction time. The complete ownership decision is
[ADR 0008](../adr/0008-book-opening-recovery-authority.md).

`BOOK_OPENING_EXECUTE` uses an Authority-convergence lease-loss policy. A
generic claim cannot take over its expired active lease. A bounded maintenance
scan invokes the same Book Opening Recovery Application used by operator
surfaces to:

1. assess the observed loss against frozen input, execution, checkpoint,
   policy/configuration, Authority-version and ExternalEffect evidence;
2. lock and reread the authoritative rows in canonical order;
3. terminalize the lost operational execution without rewriting prior terminal
   history;
4. mark the opening execution `LOST` and the Book Opening `FAILED`;
5. commit immutable convergence receipt, audit event and outbox evidence.

Execution-loss convergence does not create a `RecoveryIntent`. A successor is
authorized only by formal recovery from `FAILED` using a fresh assessment. The
recovery admission uses one short PostgreSQL unit of work for
`RecoveryIntent`, safe semantic-evaluation replacement generation and Operation
admission, generation-head CAS, successor RuntimeJob, Opening transition,
`RecoveryReceipt`, events and outbox. A commit-response loss therefore replays
the same receipt rather than admitting duplicate work.

The opening checkpoint is append-only semantic progress evidence. Entries form
a monotonic hash chain and reference exact durable Narrative Search, Planning,
Story Design or Input Resolver evidence and its version/hash. The current cursor
is an idempotent projection. Reconciliation can append a missing projection
from authoritative legacy evidence, but cannot copy or change candidate,
search, plan-activation or qualification state.

A terminal semantic-evaluation Operation is never reopened. Safe continuation
creates a generation-aware evaluation execution whose immutable
`replacement_of` lineage points to its predecessor. The generation owns only
execution lineage; Story Design and Planning retain eligibility and
qualification truth. Recovery classifies external state as
`PROVEN_NO_EFFECT`, `PROVEN_SUCCESS`, `PROVEN_TERMINAL_FAILURE` or
`UNKNOWN_AMBIGUOUS`. Proven success uses the existing receipt/durable output;
proven terminal failure permits replacement only under an existing policy; and
unknown or ambiguous state blocks until the Command Kernel's canonical
ExternalEffect reconciliation completes. `UNKNOWN_AMBIGUOUS` includes Command
Kernel `UNKNOWN_EXTERNAL_STATE`. Recovery, loss convergence and checkpoint
reconciliation never invoke a Provider.

All mutation adapters call this single Recovery Application. HTTP and workers
contain no recovery SQL; a CLI, if exposed by the operational surface, is only
a thin adapter. Legacy `resume` cannot bypass assessment, generation, effect or
checkpoint validation.

## Agent Harness

Only autonomous roles with goal decomposition, dynamic Tool selection,
observation and adaptive replanning use the Agent Harness. Draft, Review,
Revision, planning and other one-task model work are typed Capabilities and
freeze Capability Pack execution without a synthetic Agent binding.

An admitted Agent session runs inside the existing Agent Authority worker. Each
model turn is a governed ExternalEffect; the append-only transcript records
model requests, Tool requests/results, checkpoints and the final response with
Operation/Attempt/trace lineage. Lease takeover restores a committed transcript
and cannot duplicate an already committed model effect. Tools are restricted to
accepted-boundary reads, typed Capability invocation and typed Authority Command
submission. No Tool directly commits Canon, accepted Narrative State, Arc
Actual, Obligation state, plan activation or Chapter acceptance.

Admission freezes a Skill catalog with exact id/version/hash and one catalog
hash. User selection or the Harness-native `skill.activate` meta-tool records a
`SKILL_ACTIVATED` transcript event; activation does not expand the admitted Tool
allowlist or Authority permissions. A Skill activation observation also cannot
satisfy the mandatory accepted-boundary grounding query.

The repository's scripted Harness adapter is fixture-only. Controlled
validation/production composition now resolves the Agent Definition, Role,
Capability Pack, Skill bindings, Tool policy and Authority policy on the server,
then executes Agent model turns through PEP. If that binding is absent,
admission fails before a READY Operation is created. Runtime hardening now
persists the complete Definition/Tool/Skill/Pack/prompt/context/provider/model/
reasoning/route/release/Accepted-Boundary/budget contract and validates it before
every model turn. Restart or deployment drift cannot silently substitute a new
binding. Session usage aggregates Agent turns and descendant Capability/Tool
effects from authoritative Operation lineage and ledgers without copying child
costs. The bounded exact-SHA qualification ran two real model turns around one
`narrative.query_accepted` observation and recovered a committed transcript.
This earns `PROVIDER_PROVEN` only for that small Agent slice; it does not earn
long-form or production qualification.
New fixed per-stage Agent bindings and Agent-candidate runs are retired. Their
old OperationDefinitions are disabled, the migration namespace has no create
route, and canonical Chapter/Planning compositions cannot admit through them.
Queries plus retry/recovery/cancel/replay handlers remain for already-persisted
durable Operations; physical schema removal requires a later migration audit.

## Health and shutdown

- `/liveness` proves the API process is alive.
- `/readiness` requires current migrations, PostgreSQL, MinIO, a buildable provider route, operation definitions, and controlled-environment pack activation.
- `/runtime/readiness` additionally requires worker heartbeats.
- Shutdown closes provider sessions and all database runtimes.

`runtime_ready` only means the configured stack is operational. When the provider route is scripted, readiness is explicitly `fixture_only` and does not prove a real provider or production deployment.

## Recovery invariants

- Stable idempotency keys replay an existing admission instead of duplicating business work.
- CAS/version checks prevent stale business transitions.
- Attempt leases and fences prevent stale worker commits. Relational execution
  identity is database-constrained; temporal lease validity is checked by every
  mutating runtime command and bounded loss scan.
- A Book Opening expired lease converges through its owning Authority; ordinary
  RuntimeJob takeover cannot silently continue it.
- Execution loss and successor recovery authorization are separate immutable
  decisions. Only the latter creates a `RecoveryIntent`.
- Recovery assessments are immutable snapshots. Recovery locks and rereads
  authoritative state; any input, checkpoint, generation, policy/configuration,
  ExternalEffect or Authority-version drift requires reassessment.
- Terminal Operation, Attempt, Lease, RuntimeJob and opening-execution rows are
  immutable. Continuation uses explicit append-only generation lineage.
- ExternalEffect identity and receipts are the required mechanism preventing
  blind re-execution after uncertain outcomes. Each worker classifies
  `UNKNOWN_EXTERNAL_STATE` as reconciliation, not ordinary retry; Book Opening
  exposes that disposition as `UNKNOWN_AMBIGUOUS`. Embedding
  projection recovery is covered by the current bounded PostgreSQL suite.
- Book Opening loss, recovery and checkpoint reconciliation never call a
  Provider. `UNKNOWN` or ambiguous effect evidence cannot be overridden by an
  operator approval.
- Outbox records are committed with business state and delivered later.
- Supervisor checkpoints and trace/correlation identities survive process restarts.
