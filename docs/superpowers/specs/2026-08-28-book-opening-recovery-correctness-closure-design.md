# Book Opening Recovery Correctness Closure Design

- Work package: `WP-BOOK-OPENING-RECOVERY-CLOSURE-01`
- Status: Approved for implementation
- Starting main: `611f92264af7ca143ba365a3746e53cea5976606`
- Starting migration head: `20260826_0101_quality_qualification`
- Scope: Book Opening execution and recovery correctness only

## Evidence and problem statement

The previous Quality Qualification left durable evidence of a cross-plane
orphan: the Book Opening remained `RUNNING`, its RuntimeJob and Attempt remained
`CHECKPOINTED`, its held RuntimeJob Lease had expired, and the current inner
semantic-evaluation Operation was terminal `CANCELLED` with a `LEASE_LOST`
Attempt, an `EXPIRED` Lease, and no ExternalEffect. The current implementation
cannot recover that state because:

1. `BookOpening.RUNNING` does not identify an execution generation, RuntimeJob,
   Attempt, Lease, or fencing token;
2. process disappearance bypasses the in-process `record_failure()` path;
3. generic RuntimeJob claim may take over an expired Opening lease silently;
4. `resume()` admits only `FAILED` and does not perform recovery assessment;
5. candidate-once semantic-evaluation identity cannot replace an immutable
   terminal Operation for the same candidate; and
6. durable inner progress is not projected into an Opening-owned evidence
   cursor.

The real qualification database is evidence only during this work package. It
must not be migrated, repaired, reconciled, recovered, or used for Provider
execution.

## Documentation governance classification

| Classification | Documents and required action |
|---|---|
| `CURRENT` | Authority ownership, PostgreSQL transaction governance, shared Production Execution, ExternalEffect reconciliation, active ADRs, and product boundaries remain authoritative. |
| `STALE` | Canonical/overview/runtime/worker descriptions that prove or imply only post-business-commit same-job retry must be updated with full execution-loss and recovery semantics. |
| `CONFLICTING` | The Quality runbook statement that recovery never creates replacement lineage must be narrowed to the frozen business request; terminal semantic execution may require a replacement execution generation. |
| `SUPERSEDED` | ADR 0003 remains explicitly historical. The completed 2026-08-27 correctness design is superseded by current canonical/ADR decisions and qualification evidence. |
| `DEAD` | The completed 2026-08-27 correctness implementation plan has no current operational or architectural authority and is removed. |
| `HISTORICAL_EVIDENCE` | Qualification records are immutable exact-SHA evidence. Their conclusions are not edited or promoted into current proof. |

## Authority ownership

Book Authority owns the Book Opening business lifecycle, current execution
generation, current exact execution binding, semantic checkpoint cursor, and
recovery decisions. RuntimeJob remains the operational scheduling plane and
owns Job, Attempt, Lease, fence, operational checkpoint, result, and event
history. Story Design owns qualification truth; Story Planning and Narrative
Search own generation/search/selection/activation truth; Command Kernel owns
Operation, Attempt, ExternalEffect, Dispatch, Receipt, and durable output.

The Recovery Application is an application coordinator over those Authorities.
It does not create a second scheduler, Provider path, workflow truth, planning
truth, or qualification truth. HTTP, CLI when operationally justified, workers,
and maintenance must call this same Application; none may contain repair SQL.

## Book Opening execution identity

Each Opening execution has an append-only positive generation and a durable
execution record. The Book Opening current pointer identifies exactly one
execution, which in turn binds one RuntimeJob and, while claimed or running,
one current Attempt, Lease, worker, and fencing token. Relational consistency
is enforced with foreign keys, unique constraints, checks, and CAS.

Lease time validity is deliberately not a static database invariant. Every
claim, heartbeat, start, checkpoint, complete, fail, abort, loss-convergence,
and recovery path rechecks the authoritative database clock while holding the
required rows. A bounded maintenance scan converges expired executions.

`RUNNING` is valid only when the relational binding is exact and the runtime
path has just revalidated the temporal lease condition. A stale worker cannot
checkpoint or commit after its fence is lost.

Opening executions freeze a release-stable Authority contract digest, while
each immutable Assessment freezes the exact application build/commit in a
release-bound Authority-version digest. Compatible deployment therefore does
not strand admitted work, but a pre-deployment Assessment cannot authorize a
post-deployment mutation.

## State machines

```text
BookOpening
ADMITTED -> RUNNING -> COMPLETE
    |          |
    |          +-> FAILED  (governed failure or execution loss)
    +-> ABORTED

FAILED -> ADMITTED  (only a successful Recovery admission, generation N+1)
FAILED -> ABORTED   (operator closes the failed Opening; execution stays terminal)
```

```text
OpeningExecution
SCHEDULED -> BOUND -> RUNNING -> SUCCEEDED
RUNNING -> FAILED
BOUND | RUNNING -> LOST
SCHEDULED | BOUND -> ABORTED  (only a governed, still-valid abort)
```

Terminal OpeningExecution, RuntimeJob, RuntimeJobAttempt, RuntimeJobLease, and
Command Kernel Operation history cannot be reopened or rewritten.

## Execution-loss convergence

Book Opening RuntimeJobs use an explicit `AUTHORITY_CONVERGENCE_REQUIRED`
lease-loss policy. Generic RuntimeJob claim excludes expired active jobs with
that policy; ordinary jobs retain their existing same-job takeover behavior.

The existing maintenance execution plane detects bounded expired Opening
executions and calls the Book Opening Recovery Application. Loss convergence:

1. records an immutable loss assessment;
2. locks and rereads Opening, execution, RuntimeJob, Attempt, and Lease in the
   canonical order;
3. revalidates generation, binding, fence, expiry, and snapshot hashes;
4. terminalizes the lost RuntimeJob execution and the Opening execution;
5. transitions the Book Opening to `FAILED`; and
6. commits loss receipt, StateEvent, audit, and outbox evidence.

Loss convergence does **not** create a `RecoveryIntent`. It does not authorize
generation N+1 and never calls a Provider. A commit followed by response loss
replays the existing convergence receipt by deterministic idempotency.

Active abort requires the exact Lease to remain valid at transaction time. An
expired Lease makes abort fail closed and leaves formal loss convergence as the
only terminalization path. The automatic loss key binds a fresh authoritative
snapshot, including release identity, so a committed-but-stale assessment is
preserved while a later scan creates a new assessment and converges.

## Recovery protocol

`RecoveryAssessment` is an immutable snapshot binding Opening/input/version,
current execution generation, RuntimeJob/Attempt/Lease/fence, checkpoint head,
semantic-evaluation generation head, ExternalEffect/Dispatch/Receipt set,
policy/config digest, and Authority contract versions.

Checkpoint reconciliation may append only evidence that already exists in the
owning Authority. It changes the assessment snapshot and therefore requires a
fresh assessment before recovery.

Only `FAILED -> ADMITTED` creates a `RecoveryIntent`. The preferred admission
is one short PostgreSQL unit of work containing all pure database mutations:

- RecoveryIntent;
- any safe replacement semantic-evaluation generation;
- generation-head CAS;
- generation-aware Operation admission/binding;
- new Opening execution generation;
- new RuntimeJob admission and binding;
- BookOpening CAS to `ADMITTED`;
- RecoveryReceipt, StateEvent, audit, and outbox.

Formal `*_in_uow` primitives may be added to existing Authorities so each
Authority retains its SQL ownership. Provider execution and durable-result
replay remain outside this transaction in the normal governed worker path.

Any input, checkpoint, generation, effect, policy/config, Authority-version, or
execution-binding drift rejects the recovery and requires reassessment.

The legacy `resume()` mutation is removed or fail-closed and cannot translate
an `expected_version` alone into recovery authorization. In-process failure
recording and operational entry points converge through the canonical Recovery
Application.

## Semantic-evaluation replacement lineage

An evaluation execution generation owns execution lineage only. Candidate
eligibility, Planning state, Narrative Search state, and qualification remain
owned by their existing Authorities.

Generation one preserves the legacy candidate identity for rolling
compatibility. A replacement generation is append-only, names its predecessor
generation and terminal predecessor Operation, binds the RecoveryIntent, and
uses generation-aware idempotency and concurrency identities. A per-candidate
head advances with CAS. The predecessor never changes.

Replacement is allowed only for a terminal predecessor and is bounded at
generation 3. A nonterminal semantic Operation remains the Command Kernel's
execution truth: the successor Opening re-enters the same deterministic
Operation and generation through normal governed replay. That includes a crash
after a Provider receipt became durable but before output materialization or
Operation terminalization; the proven receipt/result is consumed without a
second Provider invocation. A terminal proven-success replacement, when
needed, is likewise projection-only.

Recovery admission may reserve and admit a replacement Operation, but it may
not execute it. Normal Content Authority workers perform any later Provider
work. Admission crash boundaries converge by deterministic identities and an
exact generation/Operation binding.

## ExternalEffect safety

Recovery classifies predecessor external state as:

- `PROVEN_NO_EFFECT`: no dispatch exists; replacement may be admitted;
- `PROVEN_SUCCESS`: an exact verified receipt/durable result exists; replay or
  project that evidence without a Provider call;
- `PROVEN_TERMINAL_FAILURE`: exact terminal non-success evidence exists and
  replacement requires an existing policy that permits it; or
- `UNKNOWN_AMBIGUOUS`: fail closed until the existing ExternalEffect
  reconciliation path resolves it.

Human approval cannot override `UNKNOWN_AMBIGUOUS`. Loss, recovery, and Book
Opening checkpoint reconciliation never call the Provider.

## Semantic checkpoint

The Book Opening checkpoint is an append-only, monotonic hash chain of
confirmed evidence references. Each entry binds a semantic work key, owning
Authority, durable evidence identity/version/hash, frozen request digest,
execution generation, and predecessor checkpoint/hash.

The current verifier accepts exact Planning-owned Narrative Search,
PlanningGeneration evidence and Book input-snapshot resolution. It does not
copy another Authority's mutable status or treat a child Operation as completed
Opening progress.

Resume derives the expected work graph from the frozen request and rereads the
owning Authorities. Evidence committed before a checkpoint is deterministically
reprojected; only a checkpoint whose exact Planning-owned Narrative Search is
still `ACTIVATED` with the same selection decision safely skips a whole
semantic work item. Search ID, `future-N` branch and `EVALUATION_PENDING`
Planning-generation membership must match exactly. Drift fails closed. Logs
are never progress evidence.

## Transaction and lock model

Book Opening mutations use one transaction-scoped advisory lock per Opening and
the canonical row-lock order:

```text
BookOpening -> OpeningExecution -> RuntimeJob -> RuntimeJobAttempt
-> RuntimeJobLease -> checkpoint cursor -> evaluation generation head
-> evaluation generation -> ordered Operation/Effect/Dispatch/Receipt reads
```

Heartbeat does not acquire Book Opening locks, so it cannot form a reverse lock
cycle. Completion and loss convergence serialize on the same RuntimeJob/Lease
identity; whichever wins makes the other's snapshot stale or fence invalid.
Transactions contain database coordination only and remain short.

## Migration strategy

The work package uses an expand migration from
`20260826_0101_quality_qualification`:

- create recovery/execution/checkpoint/evaluation-generation structures;
- add legacy-compatible nullable pointers and versioned checks;
- add exact FK/UNIQUE/CHECK and immutable guards;
- add RuntimeJob lease-loss policy and make existing Book Opening jobs
  non-takeover without changing their execution status;
- deterministically bootstrap existing semantic-evaluation Operations as
  generation-one lineage without rewriting them; and
- require formal Authority reconciliation for legacy Opening bindings and
  checkpoints instead of guessing progress in migration SQL.

Fresh databases use the new contract. Upgraded legacy rows fail closed until
reconciled. Contract cleanup and global non-null validation are deferred until
a separately authorized real legacy-recovery qualification proves rollout
safety.

Legacy execution binding uses a distinct immutable
`LEGACY_EXECUTION_RECONCILIATION` assessment/receipt fact. Where no exact
historical RuntimeJob can be bound, reconciliation writes a deterministic,
non-executable, attempt-less `CANCELLED` RuntimeJob / `ABORTED`
OpeningExecution marker and fails the Opening. This is not checkpoint
reconciliation, does not authorize recovery and creates no `RecoveryIntent`.

Deferred DDL guards enforce monotonic exact Opening execution/checkpoint heads,
frozen request and checkpoint digests, active-current execution binding,
RecoveryAssessment/Intent/Receipt kind, cardinality and scope, semantic
generation-head CAS/recovery lineage, and immutable terminal execution history.

## Verification and stopping boundary

The first PostgreSQL regression constructs the old orphan shape and proves it
cannot progress safely under the legacy semantics. Implementation then proves
loss convergence, recovery idempotency, generation replacement, checkpoint
replay, ExternalEffect safety, concurrency races, and every required injected
crash boundary. Fresh and previous-head migration, focused suites, full tests,
the complete PostgreSQL Authority suite, and repository validation gates must
all pass without skip, xfail, weakened assertions, or relaxed invariants.

This work package stops after engineering qualification. Real orphan recovery,
real Provider execution, the next eight-Chapter campaign, human review,
literary-quality validation, and production qualification are explicitly
deferred and `NOT_RUN`.
