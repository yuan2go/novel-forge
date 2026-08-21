# Post-Merge Correctness Closure Design

Status: APPROVED

Date: 2026-08-21

Baseline: `main` at `5f13c079d1f98380541851a82b6d43d327d00642`

Scope: WP-1 through WP-4 only. This design closes correctness, runtime wiring,
migration safety, production composition, recovery, and necessary tests. It does
not qualify long-form generation, run campaigns, or add new business capability.

## 1. Non-Negotiable Boundaries

The implementation preserves one PostgreSQL Authority, one Book/Chapter accepted
boundary, one Production Execution Platform (PEP), one Agent Harness runtime, and
one Artifact lineage/invalidation authority.

The following distinctions are mandatory in code, tests, and documentation:

```text
DEFINED
!= WIRED
!= RUNTIME_REACHABLE
!= PERSISTED
!= AUTHORITY_GOVERNED
!= RECOVERY_PROVEN
!= PROVIDER_PROVEN
!= PRODUCTION_QUALIFIED
```

The implementation must not:

- edit migration 0094;
- reconstruct Actual state from planned or expected contribution;
- mutate Canon, StoryState, ArcActual, obligations, accepted chapters, or active
  plans outside their current Authority applications;
- call a model or embedding provider outside PEP ExternalEffect and Receipt;
- make client-supplied Agent tool policy authoritative;
- make semantic index readiness a precondition of authoritative migration repair;
- generate ArcRevision or invoke PlanChange inside Book Acceptance;
- select historical retrieval evidence before ChapterMemo exists;
- mislabel PostgreSQL FTS ranking;
- materialize one database aggregate per L0-L9 taxonomy layer.

## 2. Reconciliation Findings

### 2.1 Migration 0094

Migration 0094 creates the long-form projection tables and adds
`authority_book_production.active_longform_projection_set_id` and
`authority_book_chapter_acceptance.longform_projection_set_id`. It does not
discover, register, or rebuild pre-existing accepted history.

The live Book runtime requires a COMPLETE active projection set aligned with the
accepted chapter, StoryState, and Canon. Therefore an installation with accepted
chapters and a null pointer can apply 0094 successfully but cannot admit Chapter
N+1.

### 2.2 Agent Harness

The API can admit `agent.session.execute` in controlled environments, but the
scheduler filters those operations when no scripted factory is present. Scripted
Harness execution is fixture-only. There is no production Agent Model Turn PEP
binder, so the accepted operation remains READY indefinitely.

### 2.3 Arc and Obligation

The domain reducers prevent simple Plan-to-Actual promotion, but the production
Book Acceptance caller passes empty overdue-obligation and dependency-blocker
sets. Frozen ArcPlan completion criteria, dependency Arc state, target windows,
and accepted obligation lifecycle are not consumed. ArcRevision exists as a
contract without a production path to PlanChange.

### 2.4 Context Retrieval

Book dispatch selects historical context before ExecutionIntent and ChapterMemo.
ChapterMemo records `retrieval_queries`, but no consumer uses them. PostgreSQL FTS
uses `to_tsvector`, `plainto_tsquery`, and `ts_rank`; query embeddings are empty,
and accepted retrieval documents do not have complete production metadata or a
governed embedding producer.

## 3. Architecture Overview

```text
WP-1
0095 registration
  -> RuntimeJob -> Operation -> Attempt -> Lease/Fence
  -> shared canonical long-form projector
  -> chapter projection checkpoints
  -> terminal validation
  -> one terminal pointer CAS

WP-2
Agent Session admission
  -> server-side effective tool policy
  -> Operation -> Attempt -> Lease/Fence
  -> Agent Harness -> PEP Agent Model Turn ExternalEffect
  -> durable Receipt -> Tool Observation -> Transcript
  -> reconciliation/resume

WP-3
Book Acceptance
  -> accepted obligation reducer
  -> accepted Arc progress/actual/checkpoint
  -> durable follow-up signal
  -> post-acceptance ArcRevision candidate workflow
  -> existing PlanChange Authority

WP-4
ChapterPlan -> ExecutionIntent -> ChapterMemo
  -> chapter.context.retrieve
  -> immutable RetrievalResult
  -> Context Build -> Draft
```

## 4. WP-1: Upgrade Repair

### 4.1 Forward Migration 0095

Migration 0095 is forward-only and has 0094 as its down revision. It performs
only bounded schema work and set-based repair discovery:

- add `authority_book_projection_repair` as repair registration and status;
- add chapter checkpoint records keyed by repair and chapter;
- add indexes and terminal consistency constraints;
- discover both installations upgraded directly from 0093 and installations
  already at 0094 by selecting accepted Books whose active pointer is absent or
  not aligned;
- register an existing RuntimeJob subject for each affected Book without running
  projection business logic in the migration transaction.

Repair status distinguishes:

- `REGISTERED`
- `RUNNING`
- `CHECKPOINTED`
- `AUTHORITATIVE_REPAIR_COMPLETE`
- `FAILED_RETRYABLE`
- `FAILED_TERMINAL`

Semantic retrieval readiness is separately represented as:

- `NOT_REQUESTED`
- `PENDING`
- `RETRIEVAL_SEMANTIC_PROJECTION_READY`
- `FAILED_RETRYABLE`
- `UNAVAILABLE_BY_POLICY`

### 4.2 Shared Canonical Projector

Live Book Acceptance and upgrade repair call the same pure deterministic
projector. The projector accepts an explicit accepted-evidence input and returns
the complete projection payload plus a source/evidence digest. Persistence stays
owned by Book Authority repositories.

The input includes only:

- committed Book acceptance;
- accepted ChapterOutcome;
- accepted StoryState snapshot;
- accepted CanonSnapshot;
- frozen planning asset references captured by the Chapter request/input
  snapshot;
- accepted operation/effect evidence;
- previous accepted projection state when one exists.

The adapter for an older evidence contract records:

- source contract/version;
- adapted fields;
- unavailable fields;
- adaptation reason;
- observation status selected because evidence was absent;
- source asset IDs and hashes.

Missing Arc evidence produces `NOT_OBSERVED`, `NOT_MATERIALIZED`, or `UNKNOWN`.
The projector never substitutes ChapterPlan expected contribution for Actual.

### 4.3 Durable Execution and Idempotency

Repair runs through existing RuntimeJob, Operation, Attempt, Lease, Fence,
checkpoint, retry, and dead-letter facilities. Each attempt processes a bounded
number of consecutive chapters. Every projection identifier and checkpoint
digest is derived from Book, chapter, accepted evidence, and projector version.

Retry uses upsert plus full equality validation. A conflicting existing row is a
terminal integrity error rather than a silent overwrite. Completed chapters are
skipped only after their stored source digest and projection digest match.

### 4.4 Terminal Pointer Activation

Per-chapter projection rows and acceptance pointer metadata may be prepared while
the Book remains unrepaired. The active Book pointer is changed exactly once at
terminal completion.

Terminal validation proves:

- accepted chapters form `1..N` without gaps;
- every committed acceptance has one COMPLETE projection set;
- each projection set references the exact accepted outcome, StoryState, Canon,
  frozen plan, and accepted evidence hashes;
- chapter checkpoints form the same `1..N` sequence;
- the final projection is for N;
- no accepted narrative asset or content hash changed.

Activation uses the current Book version, accepted-through chapter, expected null
or stale active pointer, repair fence token, and terminal digest in one CAS. A
stale worker cannot activate. Partial repair never advances the active pointer.

### 4.5 Retrieval Projection Separation

Authoritative repair completes after accepted Arc, obligation, state, Canon, and
pointer validation. Retrieval documents and semantic embeddings are rebuildable
derived projections scheduled by follow-up jobs. Their status cannot roll back or
block `AUTHORITATIVE_REPAIR_COMPLETE`.

At Chapter admission, the frozen Context policy decides whether semantic
readiness is required:

- required semantic profile: fail closed with the explicit projection status;
- policy-approved hybrid fallback: use PostgreSQL FTS, graph, Arc, obligation,
  and temporal signals and record `SEMANTIC_SIGNAL_UNAVAILABLE`;
- no silent downgrade is allowed.

### 4.6 Upgrade Proofs

PostgreSQL integration tests cover both:

```text
A: 0093 + accepted 1..N -> 0094 -> 0095 -> repair -> Chapter N+1
B: 0094 + accepted 1..N + null pointers -> 0095 discovery -> repair -> Chapter N+1
```

Both prove accepted assets/hashes unchanged, idempotent rerun, partial failure and
resume, incomplete repair not COMPLETE, terminal CAS, and pointer alignment.

## 5. WP-2: Production Agent Harness Composition

### 5.1 Effective Tool Policy

The client may submit requested intent, but the effective tool surface is derived
server-side from the frozen combination of:

- Agent Definition;
- Agent role;
- active Capability Pack deployment;
- Skill bindings as instruction-only inputs;
- server Tool policy;
- Authority policy;
- runtime environment.

Admission persists the server policy snapshot and digest. A caller-supplied
policy is either absent or must exactly equal the resolved snapshot; it never
adds permission. Unknown, unbound, disabled, or environment-ineligible tools
reject admission.

### 5.2 Production Model Turn Port

PEP receives one new Agent Model Turn execution binder and route. It uses the
existing provider routing, model/capability policy, budget reservation,
ExternalEffect, Receipt, timeout, cancellation, reconciliation, model-call log,
and cost ledger.

Each Agent turn has a deterministic effect identity based on session, operation,
attempt generation, turn ordinal, input transcript digest, and route snapshot.
The flow is:

```text
Agent Operation/Attempt
-> reserve turn/token/cost budget
-> PEP plan effect
-> submit/reconcile ExternalEffect
-> provider receipt
-> materialize AgentModelTurn
-> append transcript event
```

If the provider succeeds and the worker crashes before materialization, recovery
reconciles the existing Receipt. It does not issue a second provider call. Fence
checks protect transcript append and completion.

Controlled admission checks the route, provider binding, effective tool bindings,
and budget policy before creating a session or READY operation. Missing binding
fails closed.

### 5.3 Production Tool Bindings

The minimum server registry contains:

1. `narrative.query_accepted` (`READ_ONLY_QUERY`): reads only accepted projection
   views at the frozen boundary.
2. A typed Capability Runtime submission (`TYPED_CAPABILITY`): invokes the
   existing Capability Runtime and returns an immutable Candidate/operation
   identity. It cannot activate or accept the candidate.
3. An Authority command submission (`AUTHORITY_COMMAND`): invokes an existing
   Authority Application command-admission method and returns only submitted
   command/operation identity.

Authority command handlers cannot receive repositories or database cursors.
Direct mutations of Canon, NarrativeState, ArcActual, obligation lifecycle, plan
pointers, or Chapter acceptance remain forbidden by tool contract and tests.

Scripted model turns and fixture tools remain reachable only when the runtime
profile explicitly permits fixtures. Production maturity is reported as
`PROVIDER_WIRED` until real provider evidence exists.

## 6. WP-3: Arc and Obligation Correctness

### 6.1 Short Book Acceptance Transaction

The Acceptance transaction may execute deterministic local logic and persist:

- accepted ChapterOutcome;
- accepted obligation lifecycle state;
- ArcProgress;
- ArcActualState;
- ArcOutcome;
- ArcCheckpoint;
- accepted projection set and lineage;
- a durable outbox/follow-up intent.

It performs no provider call, ArcRevision generation, PlanChange invocation, or
external workflow. The outbox transactionally records a correction/replan signal
when the checkpoint returns `CORRECT` or `REPLAN_REQUIRED`.

### 6.2 Frozen ArcPlan Consumption

The canonical projector resolves frozen ArcPlan versions and consumes:

- objective;
- completion criteria IDs;
- dependency Arc IDs;
- target chapter window;
- expected progress and milestones.

Accepted outcome evidence can observe progress, consequence, phase, milestone,
resolution, and completion-criterion IDs. Unknown or absent evidence never moves
Actual.

Dependency state is derived from accepted ArcActual projections as:

- `COMPLETED`
- `BLOCKED`
- `UNKNOWN`
- `ABANDONED`

The checkpoint uses the real derived dependency set rather than empty defaults.

### 6.3 Deterministic Obligation Lifecycle

The obligation reducer receives accepted chapter number, target window, previous
accepted state, accepted evidence, and a frozen lifecycle policy. It derives:

- `DUE`
- `OVERDUE`
- `STALE`
- `FULFILLED`
- `VIOLATED`
- unresolved dependency and urgency.

Fulfillment and payoff require accepted payoff event/asset evidence. Violation
requires accepted violation evidence or the explicit deterministic policy after
the due window. Staleness is based on the last accepted observation chapter and
the frozen stale-after interval. Provider output is only an evidence candidate.

### 6.4 Checkpoint and Post-Acceptance Workflow

Checkpoint decisions are deterministic:

- `UNKNOWN`: insufficient accepted evidence;
- `CONTINUE`: observed progress is within the plan window and dependencies;
- `CORRECT`: overdue/stale obligation or recoverable progress variance;
- `REPLAN_REQUIRED`: blocked/abandoned dependency, violated obligation, missed
  plan window, or unrecoverable completion mismatch;
- `COMPLETED`: every required completion criterion has accepted evidence and
  dependencies are satisfied.

After commit, the durable follow-up workflow creates an immutable ArcRevision
Candidate from the accepted checkpoint and evidence. It validates the candidate,
submits a proposal to the existing PlanChange Authority, and lets existing
semantic diff, invalidation, approval, and activation rules decide future plan
changes. ArcActual never mutates a future plan directly.

New ArcRevision, checkpoint-signal, and PlanChange artifacts receive the minimum
lineage edges required for replay and invalidation. Existing freshness and
Artifact invalidation remain under the same Planning/PlanChange Authority; tests
assert their projections cannot disagree for newly changed assets.

## 7. WP-4: Context Retrieval v2

### 7.1 Runtime Order

The Chapter graph becomes:

```text
PLAN
-> EXECUTION_INTENT
-> MEMO
-> RETRIEVAL
-> CONTEXT
-> DRAFT
```

Book Authority freezes only the accepted boundary, protected authoritative Asset
references, Context/retrieval policy references, and governance assets. It does
not select historical retrievable evidence.

The RETRIEVAL operation builds its query plan from the frozen Intent and Memo,
including every qualified `ChapterMemo.retrieval_queries` entry. It reads only
documents whose accepted boundary is at or before the Intent boundary.

### 7.2 Immutable Retrieval Result

`chapter.context.retrieve` emits one immutable `RetrievalResult` artifact with:

- project, Book, chapter, and accepted boundary;
- Intent and Memo AssetVersion IDs and hashes;
- normalized query plan;
- selected retrieval document IDs;
- selected source AssetVersion IDs and hashes;
- PostgreSQL FTS, semantic, entity, character, relationship, temporal, Arc,
  obligation, and recency scores/reasons;
- embedding model, provider, route, version, Receipt, and projection identity when
  used;
- rejected future, stale, policy-ineligible, and over-budget items;
- retrieval policy version;
- compression trace and content fingerprints;
- deterministic result fingerprint.

Context Build consumes the RetrievalResult plus its selected immutable source
AssetVersions. The Context manifest records RetrievalResult lineage and verifies
the exact partition between protected, selected retrievable, rejected, and
compressed inputs.

### 7.3 Accepted Retrieval Documents

Book Acceptance creates or schedules rebuildable retrieval documents from
accepted sources with real deterministic producers:

- recent accepted prose and full archive locator;
- accepted ChapterOutcome and scene/episodic history;
- character timeline/history;
- relationship history;
- Canon and StoryState;
- Arc state/history;
- Narrative Obligation state/history;
- governed external knowledge when policy permits it.

Entity, character, relationship, Arc, and obligation IDs are extracted from the
accepted structured source. A field is marked wired only when its producer and
test exist. L0-L9 remains an ownership taxonomy stored through the shared
retrieval-document projection, not ten mechanical aggregates.

### 7.4 Governed Embeddings

Document embeddings are produced by a rebuildable projection operation:

```text
accepted source
-> embedding projection operation
-> PEP ExternalEffect
-> embedding Receipt
-> versioned embedding projection
```

Query embedding is produced inside RETRIEVAL through the same PEP route and is
recorded in RetrievalResult. No hidden network call is permitted. Provider,
model, dimensions, route snapshot, input hash, effect/receipt identity, cost, and
version are stored as provenance.

Production wiring without a real call is reported as `PROVIDER_WIRED` and
`NOT_PROVIDER_PROVEN`.

### 7.5 Ranking and Compression

Lexical retrieval is named PostgreSQL Full-Text Search or FTS ranking. It uses the
database FTS score as one signal. Hybrid rerank combines FTS, semantic, entity,
character, relationship, temporal, recency, Arc, and obligation signals under a
versioned deterministic policy.

Protected Context is never replaced with retrieval compression. Protected
overflow fails closed and requires replan. Retrievable compression records source
ID/hash, selection reason, input/output size, method, source-span/provenance where
available, and output fingerprint.

## 8. Failure and Recovery

- Repair crash: lease expires; next attempt resumes from the last matching
  checkpoint; terminal pointer remains unchanged.
- Repair conflict: digest mismatch fails terminally with audit evidence.
- Agent provider success then crash: Receipt reconciliation materializes the same
  turn without another provider effect.
- Agent cancellation/budget/turn/token/cost limit: hard-stop, transcript event,
  attempt completion/failure, no further model or tool call.
- Stale worker: fence rejects projection, transcript, checkpoint, and completion
  writes.
- Arc follow-up failure: accepted checkpoint remains valid; durable follow-up is
  retryable/dead-lettered without changing Actual.
- Semantic projection unavailable: explicit status and policy decision; no silent
  fallback and no rollback of authoritative repair.
- Retrieval future/stale candidate: rejected and recorded in RetrievalResult.
- Protected Context overflow: fail closed before Draft.

## 9. Test Strategy

### WP-1

- migration schema and discovery unit tests;
- fresh migration smoke;
- 0093 accepted history -> 0094 -> 0095 -> repair;
- existing 0094 accepted history -> 0095 discovery -> repair;
- shared live/rebuild projector equality;
- missing legacy Arc evidence remains unknown;
- idempotent rerun, crash/resume, partial state not complete, stale fence, terminal
  CAS, accepted asset/hash preservation, Chapter N+1 readiness.

### WP-2

- Harness contract and server effective-policy tests;
- caller policy escalation rejection;
- controlled composition and unbound admission rejection;
- all three production tool bindings;
- repository/direct-mutation rejection;
- cancellation and hard limits;
- provider success/crash/receipt recovery with no duplicate effect.

### WP-3

- Plan cannot become Actual;
- missing evidence and unknown state;
- frozen completion criteria and target window;
- dependency completed/blocked/unknown/abandoned;
- deterministic due/overdue/stale/fulfilled/violated/payoff;
- real CONTINUE/CORRECT/REPLAN_REQUIRED/COMPLETED/UNKNOWN decisions;
- accepted-only mutation;
- Acceptance outbox and post-commit ArcRevision -> PlanChange proposal;
- freshness/invalidation invariant.

### WP-4

- Memo queries are Retrieval Query Plan inputs;
- future/stale/accepted-boundary rejection;
- PostgreSQL FTS ranking;
- governed document and query embedding evidence;
- entity, character, relationship, temporal, Arc, obligation, and recency signals;
- real metadata producers for accepted sources;
- immutable RetrievalResult replay/fingerprint;
- protected overflow and compression provenance;
- Context Manifest reproducibility and Draft consumption.

No long campaign, load test, multi-Book sustained generation, large provider
spend, or literary benchmark is part of acceptance.

## 10. Documentation Reconciliation

Canonical architecture, runtime, narrative-state, production-execution, and
novel-production-flow documents will be updated to match the final code and proof
level. Lexical ranking is named PostgreSQL FTS throughout.

The 2026-08-20 exact-SHA convergence design is retained as historical context and
marked SUPERSEDED. Its implementation plan is removed because it is an obsolete
execution checklist tied to the prior SHA and claims a closure superseded by this
work.

Final status reports use only evidence earned by tests. Scripted or deterministic
provider tests do not establish PROVIDER_PROVEN or PRODUCTION_QUALIFIED.

## 11. Delivery

Implementation order is WP-1, WP-2, WP-3, WP-4, transitional-path cleanup,
targeted tests, canonical documentation, explicit commits, feature-branch push,
and Draft PR. Work stops after these four packages.

## 12. Implemented Proof Boundary

The four packages are implemented through their production compositions and
targeted PostgreSQL recovery tests. Their earned status is deliberately narrower
than production qualification:

| Package | DEFINED | WIRED | RUNTIME_REACHABLE | PERSISTED | AUTHORITY_GOVERNED | RECOVERY_PROVEN | UNIT_TESTED | POSTGRES_SMOKE_TESTED | PROVIDER_WIRED | PROVIDER_PROVEN | PRODUCTION_QUALIFIED |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WP-1 | yes | yes | yes | yes | yes | yes | yes | yes | n/a | no | no |
| WP-2 | yes | yes | yes | yes | yes | yes | yes | yes | yes | no | no |
| WP-3 | yes | yes | yes | yes | yes | yes | yes | yes | n/a | no | no |
| WP-4 | yes | yes | yes | yes | yes | yes | yes | yes | yes | no | no |

`RECOVERY_PROVEN` means the bounded failure/retry/receipt scenarios named in this
specification passed targeted tests. It does not mean sustained operations under
production load. Scripted provider receipts prove governed composition and
reconciliation, not provider behavior. No real-provider, long-form, multi-Book,
load, literary-quality, or production qualification was performed.
