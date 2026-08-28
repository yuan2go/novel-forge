# ADR 0008: Book Opening recovery is owned by Book Authority

- Status: Accepted
- Date: 2026-08-28
- Clarifies: ADR 0007 decision 10 and `authority-runtime-job-execution-plane`

## Context

The 2026-08-27 Quality Qualification exposed a cross-plane failure that the
post-business-commit RuntimeJob replay test did not cover. A Book Opening could
remain `RUNNING` after its outer RuntimeJob Attempt stopped and its Lease
expired, while an inner `story_design.semantic_evaluate` Operation was terminal
`CANCELLED`. The opening row did not bind an execution generation, RuntimeJob,
Attempt, Lease, fence or semantic checkpoint. Process loss bypassed the local
exception path, generic RuntimeJob claim could take over the expired job, and
candidate-once semantic-evaluation identity prevented a safe replacement.

RuntimeJob cannot decide whether another business execution is authorized.
Planning and Story Design cannot make Book Opening lifecycle decisions.
Reopening terminal Operation, Attempt, Lease or Job rows would destroy audit
history, while blind Provider replay after an uncertain effect could duplicate
an external side effect. A repair-only scheduler, CLI or SQL path would create a
second runtime or Authority.

The exact-SHA qualification record is immutable historical evidence of this
defect. It is not evidence that the recovery closure is implemented or proven.

## Decision

### 1. Authority ownership

Book Authority, through the Book Opening aggregate, owns:

- Book Opening lifecycle and frozen request;
- append-only opening execution generations and their current binding;
- execution-loss and recovery decisions;
- the current semantic checkpoint projection;
- recovery assessment, intent and receipt lineage.

RuntimeJob remains the non-business operational plane. It owns Job, Attempt,
Lease, fence, operational checkpoints, bounded retry and terminal operational
history. Planning, Narrative Search and Story Design retain their existing
candidate, generation, selection, activation and qualification truth.
Evaluation generation added by this decision owns execution lineage only.

Recovery is an application coordinator over these existing Authorities. It is
not a new Authority and stores no copied mutable child lifecycle.

### 2. Opening execution identity

Each Opening execution has an immutable identity and monotonically numbered
generation. Its active lifecycle advances only by CAS, and its terminal record
is immutable. The Book Opening points to at most one current nonterminal
execution. A running execution binds exactly:

```text
BookOpening
  -> OpeningExecution generation N
  -> RuntimeJob
  -> RuntimeJobAttempt
  -> RuntimeJobLease
  -> fencing token
```

Admission leaves the pair at `BookOpening.ADMITTED` /
`OpeningExecution.SCHEDULED`. Book Authority, not the generic RuntimeJob
claimer, creates the first Attempt/Lease and changes the execution to `BOUND`
in the same transaction. Worker start changes the exact bound pair to
`RUNNING`; a process loss from either `BOUND` or `RUNNING` uses the same formal
loss convergence.

Foreign keys, uniqueness, checks and optimistic versions protect this
relational identity. Lease expiry is temporal and cannot be guaranteed by a
static check constraint. Claim, heartbeat, checkpoint, completion, failure,
cancellation and recovery therefore reread `lease_expires_at` and the exact
fence inside their transaction. A time-bounded loss scan converges expired
bindings.

`BOUND` or `RUNNING` without a matching current execution, Job, Attempt, Lease
and fence is invalid. A late executor cannot checkpoint or commit after the
binding changes.

The execution row freezes a release-stable Authority contract digest derived
from the Authority and execution-contract versions, not the current build or
commit. This lets an already-admitted generation remain executable across a
rolling-compatible deployment. Each immutable assessment separately freezes a
release-bound Authority-version digest containing the exact application build
and commit; a deployment therefore makes an older assessment stale without
stranding the admitted execution.

### 3. Execution-loss convergence is not recovery authorization

`BOOK_OPENING_EXECUTE` does not permit generic expired-lease takeover. An
observed process, lease, fencing or irrecoverable RuntimeJob loss follows one
idempotent Authority path:

```text
active OpeningExecution
  -> immutable execution-loss assessment
  -> active Attempt ABANDONED / Lease EXPIRED
  -> RuntimeJob FAILED
  -> OpeningExecution LOST
  -> BookOpening FAILED
  -> immutable loss-convergence receipt and outbox/audit evidence
```

The command locks and rereads the current binding before mutation. Completion,
heartbeat or another loss convergence can win only through the same version and
fence checks. Duplicate calls return the same durable result; stale calls fail
closed. Existing terminal rows are never reopened or rewritten.

An active abort is authorized only while its exact held Lease is still valid at
transaction time. If that Lease has expired, abort fails closed without changing
history and the formal loss path must converge it. The bounded sweeper derives
its assessment idempotency identity from the fresh authoritative snapshot,
including runtime, checkpoint, semantic/effect, policy and release evidence. If
an assessment commits and any of those facts later drift, the next scan creates
a new immutable assessment instead of replaying the stale one forever.

Loss convergence creates no `RecoveryIntent`. It records that the old execution
is no longer valid; it does not authorize a successor.

### 4. Recovery authorization

Only a formal recovery from `BookOpening.FAILED` may authorize generation
`N+1`. `RecoveryAssessment` is an immutable snapshot bound to:

- frozen request and input digest;
- Book Opening and execution versions;
- current RuntimeJob/Attempt/Lease/fence lineage;
- checkpoint head, sequence and hash;
- semantic-evaluation generation head;
- Operation, ExternalEffect, Dispatch and Receipt evidence hash;
- policy, configuration and Authority contract versions;
- the resulting recovery disposition.

Recovery obtains locks in canonical order and rereads every authoritative
reference. Input, checkpoint, generation, policy/configuration,
ExternalEffect or Authority-version drift rejects the command and requires a
new assessment. There is no force flag.

For recovery admission whose participants are pure mutations in the same
PostgreSQL Authority database, one short unit of work atomically commits:

- the immutable `RecoveryIntent`;
- a safe replacement evaluation generation and Operation admission when
  required;
- evaluation-generation-head CAS;
- the successor Opening execution and RuntimeJob admission;
- `BookOpening.FAILED -> ADMITTED`;
- the immutable `RecoveryReceipt`, StateEvents and outbox records.

Provider calls and durable-result replay do not run in this transaction. A
crash after commit or a lost response deterministically replays the same receipt
and admissions by idempotency key.

### 5. Semantic checkpoint

The Opening checkpoint ledger is append-only and monotonic. Each entry binds:

- opening execution generation and frozen request digest;
- semantic work key and ordered sequence;
- exact external Authority/evidence identifier, version and content hash;
- prior checkpoint identifier and hash;
- the resulting checkpoint hash.

The Book Opening's current checkpoint is an idempotent projection of that
ledger. The current verifier accepts exact Planning-owned Narrative Search,
PlanningGeneration evidence and Book input-snapshot resolution; the ledger does
not own those states. Recovery queries their owning Authority before skipping
work.

The current Opening implementation treats a semantic work item as stage-skip
safe only when its checkpoint names the exact Planning-owned Narrative Search
and that search is still `ACTIVATED` with the same durable selection decision.
`SELECTED`, partially materialized branches and Planning membership by
themselves are not skip authority. Search identity is derived from the frozen
Opening request, generator and logical key; semantic inspection then follows
the exact search, `future-N` branch and `EVALUATION_PENDING` Planning generation
lineage. Prefix or latest-row inference is forbidden.

If durable evidence committed before its outer checkpoint, reconciliation may
append the missing checkpoint deterministically. Legacy evidence is handled by
the same application path. Logs and in-memory stage position are never treated
as progress evidence. Evidence drift invalidates the assessment.

### 6. Semantic-evaluation replacement lineage

A terminal semantic-evaluation Operation remains immutable. Safe continuation
for the same immutable candidate creates an append-only evaluation execution:

```text
Candidate C
  -> EvaluationExecution generation 1 -> Operation O1 -> terminal
  -> EvaluationExecution generation 2
       replacement_of generation 1
       predecessor_operation_id O1
       -> Operation O2
```

Candidate plus generation is unique. The generation head advances by CAS, and
idempotency/concurrency identity includes the generation. The predecessor link
and recovery intent are immutable. A concurrent recovery can admit at most one
successor; replay finds that same generation and Operation. The bounded Opening
policy admits at most generation 3.

Replacement is terminal-only. If the predecessor Operation is nonterminal, the
successor Opening re-enters the same deterministic command, evaluation
generation and Operation through the normal governed worker path. That path
also closes the crash window in which a Provider receipt is durable but output
materialization or Operation terminalization is not: it consumes the proven
receipt/output evidence without another Provider invocation. A terminal
`SUCCEEDED` predecessor may receive a projection-only successor generation
when the exact durable-success bundle must be replayed; that successor is still
forbidden from calling the Provider.

Evaluation execution does not decide candidate eligibility or qualification.
Story Design and Planning continue to validate those facts and own any
qualification or activation result.

### 7. ExternalEffect safety

Recovery classifies predecessor external state before authorizing continuation:

- `PROVEN_NO_EFFECT`: durable evidence proves no Provider effect was dispatched;
  a replacement execution may be admitted;
- `PROVEN_SUCCESS`: the unique verified receipt and durable output are replayed;
  a replacement Provider call is forbidden;
- `PROVEN_TERMINAL_FAILURE`: durable evidence proves a terminal non-success;
  replacement is allowed only when an existing policy authorizes it;
- `UNKNOWN_AMBIGUOUS`: dispatch outcome is uncertain or evidence conflicts;
  recovery fails closed until canonical ExternalEffect reconciliation resolves
  it.

`UNKNOWN_AMBIGUOUS` is the Book Opening recovery disposition that includes
Command Kernel `UNKNOWN_EXTERNAL_STATE`; it is not a second effect lifecycle.

Operator approval cannot override `UNKNOWN_AMBIGUOUS`. If a successful receipt
exists but the expected durable output is missing or inconsistent, the state is
reconciliation-required rather than replay-safe. Loss convergence, assessment,
checkpoint reconciliation and recovery admission never call a Provider. Only
the normal governed Operation/Attempt/Lease/ExternalEffect worker path may do
so.

### 8. Locking and mutation surfaces

Opening mutations use one canonical order:

```text
Book Opening advisory/aggregate lock
-> BookOpening
-> OpeningExecution
-> RuntimeJob
-> RuntimeJobAttempt
-> RuntimeJobLease
-> checkpoint cursor
-> evaluation generation head/execution
-> ordered Operation and external-effect evidence
```

Heartbeat remains a RuntimeJob/Lease operation and never acquires Book Opening
locks in reverse order. Transactions contain database reads, validation,
mutations, events and outbox only; network and Provider work stays outside.

HTTP, workers, maintenance and any operational CLI are adapters over the same
Recovery Application. No adapter may issue recovery SQL, bypass assessment or
force a transition. The legacy `resume()` mutation is removed, blocked or
internally reduced to the same full recovery protocol; two semantically
different recovery paths are forbidden.

### 9. Migration and proof boundary

Rollout follows expand, migrate, verify, then contract:

- add generation, binding, checkpoint and recovery structures compatibly;
- bootstrap legacy semantic evaluations as generation 1 without changing their
  Operation, Attempt, Lease, Effect or receipt history;
- require legacy Book Openings to reconcile from authoritative durable evidence
  instead of guessing a checkpoint;
- prohibit ordinary takeover for existing active Book Opening jobs;
- prove fresh database and previous-head upgrade paths;
- defer destructive contract cleanup until compatibility and recovery evidence
  justify it.

Migration does not rewrite historical terminal truth. The qualification
database and its current orphan remain read-only for this engineering work
package. Real orphan loss convergence/recovery, real Provider execution, a new
eight-Chapter campaign, human/quality validation and Production Admission are
separate user-authorized work.

Legacy execution binding is its own immutable
`LEGACY_EXECUTION_RECONCILIATION` assessment/receipt fact, not a recovery
authorization or semantic-checkpoint fact. If no exact historical RuntimeJob
can be bound, reconciliation creates a deterministic, non-executable,
attempt-less `CANCELLED` RuntimeJob / `ABORTED` OpeningExecution marker and
moves the Opening to `FAILED`; it neither invents progress nor creates a
`RecoveryIntent`.

Database guards enforce the exact execution and checkpoint heads, monotonic
successor/predecessor links, frozen-request digest binding, current-active
execution binding, RecoveryAssessment/Intent/Receipt fact cardinality and
scope, semantic generation-head CAS and recovery-intent lineage, and immutable
terminal history. These relational guards complement rather than replace the
transaction-time Lease-validity checks.

## Consequences

- Book Opening has one verifiable business execution identity and one canonical
  recovery mutation path.
- RuntimeJob remains reusable operational infrastructure without becoming
  recovery or qualification Authority.
- Process loss converges to an explicit terminal/waiting state instead of
  silent takeover or indefinite `RUNNING`.
- Terminal history and verified Provider effects are preserved; recovery adds
  explicit successor lineage rather than rewriting predecessors.
- The additional rows, indexes, constraints, lock ordering, reconciliation and
  tests are accepted complexity required for deterministic crash convergence.
- Engineering tests can qualify this correctness closure only. They do not
  establish real-provider, literary-quality, campaign or production proof.
