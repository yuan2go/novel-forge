# Post-Merge Runtime Hardening Design

> **Status:** ACTIVE IMPLEMENTATION BASELINE
> **Baseline:** latest `main` at execution start; exact SHA is recorded in the
> qualification evidence and Draft PR.

This specification reconciles the 0095 design with the production runtime. It
does not add a new Authority, provider runtime, Agent runtime, Context runtime,
retry runtime, Arc type or memory taxonomy.

## Reconciled latest-main facts

| Work package | Current code fact | Unearned claim |
|---|---|---|
| Arc follow-up | Durable follow-up and success path exist, but reconciliation recognizes `SUCCEEDED`, non-canonical `FAILED`, and `CANCELLED` only. | `RECOVERY_PROVEN` |
| Embedding projection | Operation/Attempt/Lease/Fence/ExternalEffect/Receipt and stable projection identity exist, but broad exception handling submits every failure as retryable. | unknown-state recovery |
| Agent Harness | Server policy resolution, transcript and PEP model turns exist; full execution identity is not Session-frozen or checked before each turn, and child costs/effects are not aggregated. | frozen execution contract and aggregate budget |
| Retrieval v2 | Memo drives FTS/graph/recent candidate discovery and query embeddings rerank that frozen set. | independent semantic candidate retrieval |

The former post-merge correctness specification and plan are
`SUPERSEDED / HISTORICAL_ONLY`. Historical migrations remain immutable;
persistence changes are forward-only.

## Arc follow-up closure

Book Acceptance remains immutable truth. A follow-up may affect only future
production. The follow-up coordinator consumes canonical Operation states:

```text
READY -> RUNNING -> PROPOSED -> WAITING_APPROVAL -> COMPLETED
                  |             |
                  |             -> REPLAN_APPROVAL_PENDING Book
                  -> retryable / reconciliation / governed terminal
```

`FAILED_RETRYABLE` keeps the stable follow-up/idempotency identity and is
actionable for retry. Exhaustion, `FAILED_FINAL`, `DEAD_LETTER` and unresolved
reconciliation record terminal evidence and place the Book in the existing
non-advancing governed/manual state. `CANCELLED` records cancellation evidence,
clears no accepted pointer and requires an explicit new checkpoint request or
operator recovery. No failure rewrites Accepted Chapter, Canon, Story State or
Arc Actual.

## Embedding unknown-state closure

`UNKNOWN_EXTERNAL_STATE` checkpoints the current Attempt. Recovery acquires a
new lease/fence for that same Attempt and reconciles its original
ExternalEffect/Dispatch/Receipt through the shared PEP recovery policy:

```text
receipt success -> consume original result -> READY projection
confirmed not executed -> FAILED_RETRYABLE -> governed new Attempt
confirmed final/cancelled -> matching terminal state
still ambiguous -> RECONCILIATION_REQUIRED; no dispatch
```

Logical projection identity is source AssetVersion + source content hash +
projection version. A READY row is immutable and conflict-checked.

## Agent execution contract closure

Controlled admission persists one content-addressed execution contract on the
Session/Operation containing Definition identity, role, Tool/Skill/Capability
Pack identities, prompt/context policies, provider/model/reasoning/route,
release SHA, runtime contract and policy hashes, Accepted Boundary and budget.
Every model turn validates the Attempt's binding against that contract. Exact
frozen bindings may replay; drift fails closed and requires re-admission.

Session usage is a read/guard projection over authoritative lineage:

```text
session Operation
  + model-turn effects/ledgers
  + descendant Typed Capability effects/ledgers
  + remote Tool effects/ledgers
  = aggregate Session budget usage
```

No child ledger is copied. Child Operations must carry parent/root/causation
lineage to the Session Operation. Authority Commands remain submit-only.

## Retrieval Candidate v3

The query plan declares `REQUIRED`, `FALLBACK_ALLOWED`, or `DISABLED` semantic
policy and an explicit ranking policy/version. A governed query embedding is
available before candidate discovery. PostgreSQL runs bounded channels in
parallel semantics:

```text
FTS + VECTOR + ENTITY/RELATIONSHIP/CHARACTER/ARC/OBLIGATION + TEMPORAL
-> union -> document dedupe -> freeze source AssetVersions
-> versioned hybrid rerank -> immutable RetrievalResult -> Context
```

Each selected candidate records every contributing channel. Vector search uses
the PostgreSQL embedding projection and applies project, book, accepted
boundary, lifecycle, source hash, projection version, model and dimensions
inside candidate eligibility. `REQUIRED` fails closed without a compatible
projection; `FALLBACK_ALLOWED` records the exact fallback; `DISABLED` makes no
query-embedding call.

## Qualification gate

Real-provider qualification starts only after all four packages pass changed
unit/domain/architecture tests, targeted PostgreSQL integration and failure
injection. It is limited to one Agent Session, one document/query embedding
proof and one Chapter Memo→Retrieval→Draft slice. Evidence records release,
environment, provider/model/route, policy/Pack identity, Operation/Attempt/effect/
receipt ids, cost/tokens, Accepted Boundary and retrieval/context fingerprints.

Passing this gate earns only the covered `PROVIDER_PROVEN` claims. It does not
earn `LONGFORM_PROVEN` or `PRODUCTION_QUALIFIED`.
