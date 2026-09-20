# Narrative Memory, Context, Retrieval, and Lifecycle Industrial Closure

> **PROPOSAL**
>
> **PARTIALLY_IMPLEMENTED — GATE A IMPLEMENTED; GATES B–E UNRESOLVED**
>
> **NOT_RUNTIME_AUTHORITY**
>
> **REMAINING DESIGN SCOPE — NO RUNTIME AUTHORITY**

Status: `PARTIALLY_IMPLEMENTED`
Reality baseline: `730facc12fe5e45a1f9a73ac6783edf547e5009b`
Baseline implementation identity:
`sha256:3e648d21e8761fe6b6c110f3dbc0dc2a57cfd621d8b8dd3035d3be44eb4f9ae7`

<!-- proposal-lifecycle
{
  "schema_version": "novel-forge.proposal-lifecycle.v1",
  "status": "PARTIALLY_IMPLEMENTED",
  "reviewed_on": "2026-09-21",
  "review_due": "2026-10-08",
  "reality_baseline": {
    "sha": "730facc12fe5e45a1f9a73ac6783edf547e5009b",
    "implementation_tree_sha": "sha256:3e648d21e8761fe6b6c110f3dbc0dc2a57cfd621d8b8dd3035d3be44eb4f9ae7"
  },
  "scope": [
    "src/novel_forge/modules/context_builder",
    "src/novel_forge/modules/chapter_authority/execution_gateway.py",
    "src/novel_forge/modules/production_execution",
    "src/novel_forge/storage/migrations",
    "src/novel_forge/workers/runtime_groups.py"
  ],
  "implemented_refs": [
    {
      "path": "src/novel_forge/modules/context_builder/governance.py",
      "symbol": "compile_effective_context_policy"
    },
    {
      "path": "src/novel_forge/modules/context_builder/domain.py",
      "symbol": "build_authority_context_bundle",
      "contains": "authority-context-bundle-v8"
    },
    {
      "path": "src/novel_forge/modules/context_builder/domain.py",
      "symbol": "replay_context_bundle"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/execution_gateway.py",
      "symbol": "_provider_effective_context_policy"
    },
    {
      "path": "src/novel_forge/modules/context_builder/reality_projection.py",
      "symbol": "project_role_context"
    },
    {
      "path": "src/novel_forge/modules/chapter_authority/provider_views.py",
      "symbol": "project_narrative_state_facts"
    },
    {
      "path": "src/novel_forge/modules/narrative_state/information.py",
      "symbol": "disclosed_fact_projection"
    }
  ],
  "superseding_refs": [],
  "remaining_decisions": [
    {
      "id": "digest-consumer-contract",
      "description": "DESIGN_REVIEW_REQUIRED: consumer-specific structured Digest coverage, deterministic generation and accepted-head timing.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/memory.py",
          "symbol": "NarrativeMemoryLayer"
        }
      ]
    },
    {
      "id": "diagnostic-retention-policy",
      "description": "DESIGN_REVIEW_REQUIRED: indexed per-source scan watermarks, replay/lookback bounds and observation receipt horizon.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/workers/runtime_groups.py"
        }
      ]
    },
    {
      "id": "representation-cutover-policy",
      "description": "DESIGN_REVIEW_REQUIRED: frozen coverage corpus, safe payload/header migration and fenced cutover/rollback behavior.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/production_retrieval.py"
        }
      ]
    }
  ],
  "remaining_work": [
    {
      "id": "gate-b-digest",
      "description": "Revision-bound structured Narrative Digest and freshness/head selection.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/memory.py"
        }
      ],
      "absent_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/digest.py"
        }
      ]
    },
    {
      "id": "gate-c-retention",
      "description": "Governed diagnostic projection, bounded retention and resumable GC.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/workers/runtime_groups.py"
        }
      ]
    },
    {
      "id": "gate-d-generations",
      "description": "Typed multi-source retrieval and active representation generations with prebuilt embeddings.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/production_retrieval.py"
        }
      ]
    },
    {
      "id": "gate-e-derived-lifecycle",
      "description": "Coverage-gated cutover, tombstone, grace and derived payload purge without protected-evidence deletion.",
      "evidence_refs": [
        {
          "path": "src/novel_forge/modules/context_builder/embedding_projection.py"
        }
      ]
    }
  ]
}
-->

Current scope review (2026-09-21): Gate A and current role Context/Provider behavior
are projected in [current-system](../../docs/current-system.md). Implemented Gate A
design, former reality matrices and duplicate final-architecture tables have been
removed. Craft uses the existing Context owner and adds no Digest, retention, GC,
retrieval representation or cutover owner. Routing campaign accounting and sample
isolation do not implement these memory lifecycle gates. Chapter sampling retains the
effective stage Context, schema and tool constraints in its producer identity; this
does not add Digest generation, retention, retrieval generations or lifecycle cutover. Gates B–E below remain proposed design,
not executable contracts or proven invariants; their stated bounds require qualification.

## 7. Gate B — Structured Narrative Digest

### 7.1 Authority boundary

The Narrative Digest is a schema-validated projection of accepted sources. It can be
programmatically derived, LLM-assisted, or mixed, but every field declares derivation
mode and provenance. It cannot activate a plan, accept a chapter, change Canon, or write
Canonical Narrative State. A missing or failed Digest never prevents the canonical
accepted-state read path.

Deterministic fields are projected first. LLM-derived fields remain explicitly marked
and must pass structural and source-coverage validation. A retry creates or resumes the
same idempotent projection identity; it cannot create competing current truth.

### 7.2 First-version scopes are consumer-driven

Gate B implements only scopes used by a current production Context/Retrieval consumer:

| First-version scope | Current consumer and evidence | Payload responsibility |
|---|---|---|
| `CHAPTER` | accepted-boundary chapter generation/review retrieval; current L3/L4 retrieval documents and `chapter_episodic_summary` candidate type | accepted chapter summary, nested scene outcomes, revealed facts, world/timeline/location changes, causal consequences |
| `CHARACTER_STATE` | character/entity filters and continuity Context; current `character_ids`, state facts, and L1/L2 channels | character deltas, knowledge, goal/status/location changes, continuity constraints |
| `RELATIONSHIP_STATE` | relationship filters and continuity Context; current `relationship_ids` channel | trust/power/alignment/obligation changes and evidence boundaries |
| `CONTINUITY_THREAD` | obligation and long-distance fact retrieval; current `obligation_ids`, foreshadow/clue/state facts | open/resolved thread, setup/payoff/clue/foreshadow/obligation status, due/closure evidence |

Standalone `SCENE` is deferred because current production retrieval is chapter-anchored;
scene data is nested in `CHAPTER` v1. `ARC` is deferred because current accepted arc
projection and L5 retrieval already serve the consumer, and another Arc digest would
duplicate state without a proven need. `VOLUME` is deferred because no current
production retrieval call requests a Volume Digest. These are design extension points,
not schema values, qualified capabilities, or placeholders that must be populated.

### 7.3 Structured payload contract

Each first-version payload is bounded and typed. Applicable fields include:

```text
summary
scene_outcomes
character_state_changes
relationship_changes
revealed_facts
world_state_changes
timeline_events
causal_consequences
location_changes
foreshadowing
clues
open_threads
resolved_threads
reader_promises
obligations
continuity_constraints
```

Not every scope owns every field. The schema defines allowed/required fields by scope,
cardinality and byte limits, stable fact/thread/entity identifiers, accepted chapter
coordinates, and per-field provenance. An unbounded catch-all JSON object is forbidden.

### 7.4 Digest identity and source model

Digest identity is the canonical hash of:

```text
project_id
book_id
branch_identity (= current book_run_id; no new generic branch Authority)
scope_type
scope_key
accepted_from_chapter
accepted_through_chapter
source_set_hash
payload_schema_version
generator_identity
generator_version
```

`source_set_hash` is computed from a sorted list of typed source identities, source
revisions/content hashes, accepted coordinates, and derivation roles. Digest rows are
immutable. A retry with the same identity is idempotent; a different source set,
schema, or generator is a different Digest.

The proposed storage split is:

- Digest header: identity, scope, accepted range, source-set hash, schema/generator
  identity, timestamps, disposition, operation/attempt/fence, and payload hash;
- Digest source membership: typed FK to each accepted source AssetVersion plus role,
  revision/hash, and accepted range;
- Digest payload: bounded schema-validated structured payload, derivation annotations,
  and validation hash;
- Digest head pointer: one pointer for each `(project, book, book_run, scope_type,
  scope_key)` logical scope.

The header/source/pointer is protected lineage; the payload is rebuildable and managed
by Gate E.

### 7.5 Freshness and disposition state model

The public `DigestFreshness` model is:

| State | Meaning | Retrieval/replay behavior |
|---|---|---|
| `CURRENT` | valid Digest selected by the logical-scope head pointer, and its accepted boundary equals the canonical accepted head bound by that pointer | eligible for current-head retrieval |
| `VALID_AS_OF` | valid Digest for an earlier accepted boundary, or a valid non-head boundary explicitly requested | eligible for matching historical accepted-boundary retrieval, exact replay, and future-only replan |
| `SUPERSEDED` | another validated Digest or representation replaced this one for the same logical scope and exact accepted boundary | excluded from normal retrieval; addressable by frozen historical manifest/round |
| `INVALIDATED` | source membership/hash, provenance, schema validation, or correctness has been revoked or proven corrupt | excluded from all new retrieval and Context; replay reports invalidation and cannot silently substitute it |

`CURRENT` is pointer-derived, not inferred from creation time. Stored disposition marks
valid, superseded, or invalidated rows; the head pointer plus accepted boundary exposes
`CURRENT` versus `VALID_AS_OF`. This prevents mass status rewrites and makes normal
accepted-head advancement safe.

The transitions are semantic, not age-based:

| Event | Prior view | Result |
|---|---|---|
| accepted head advances to a later chapter | `CURRENT` at the old boundary | `VALID_AS_OF`; the old Digest remains eligible for that exact historical boundary |
| new validated Digest is installed for the new head | no `CURRENT` at the new boundary | new row becomes `CURRENT`; earlier rows remain `VALID_AS_OF` |
| new schema/generator representation replaces a Digest for the same exact scope and boundary | `CURRENT` or `VALID_AS_OF` | old row becomes `SUPERSEDED`; frozen manifests/rounds may still address it |
| an accepted correction is appended at a later boundary | valid earlier Digest | remains `VALID_AS_OF` for the earlier boundary; the correction belongs to a later Digest |
| source identity/hash, provenance, or validation is proven false/corrupt | any valid view | `INVALIDATED`; never selected for a new request |

Changing a generator version by itself does not invalidate an older Digest. It creates
a different identity, and only a validated same-boundary replacement may supersede the
older representation.

On accepted-head advance:

1. the previous Digest remains valid;
2. it is exposed as `VALID_AS_OF`, never `INVALIDATED` or `SUPERSEDED` merely because a
   later chapter was accepted;
3. there may temporarily be no `CURRENT` Digest while the new accepted-head Digest is
   built;
4. canonical state remains readable during that gap;
5. a newly validated Digest atomically becomes the head pointer for that logical scope.

The database enforces one pointer per logical scope. A trigger or equivalent constrained
transaction verifies that the pointer target has the same project/book/book_run/scope,
is valid, and binds the pointer's accepted head. Two rows cannot both be `CURRENT`
because only the pointed row is current.

### 7.6 Generation, failure, and recovery

Digest generation enters through the existing Authority operation/attempt/lease/fence
runtime. Its output role is `derived_projection_candidate`. If a Provider is used, its
call uses the existing ExternalEffect and reconciliation path. The activation
transaction verifies the accepted head/source hashes again before installing the head
pointer.

Partial field extraction, lost worker, stale fence, and unknown effect do not publish a
payload or pointer. A bounded retry reuses the digest identity and missing-field plan.
A final failure records bounded structured evidence and leaves the canonical read path
unchanged. Rebuild selects a new generator/schema identity or reconstructs the same
identity only when its deterministic output hash agrees.

## 8. Gate C — Diagnostic Retention and GC

### 8.1 Separate lifecycle and source evidence

Gate C never compacts Narrative Memory. It projects operational observations from
existing runtime/effect/audit sources, while those protected sources retain their own
owners and policies. Deleting a diagnostic projection cannot mutate RuntimeJob,
Audit, Qualification, Recovery, or ExternalEffect evidence.

Diagnostic classes are:

```text
OPERATIONAL_DIAGNOSTIC
PROVIDER_DIAGNOSTIC
BUILD_CI_OUTPUT
EPHEMERAL_DEBUG_DATA
```

The source classification is stored independently:

```text
AUTHORITY_ACCEPTED_LINEAGE
AUDIT_EVIDENCE
QUALIFICATION_EVIDENCE
RECOVERY_EVIDENCE
PROVIDER_EFFECT_EVIDENCE
```

Only the first list enters ordinary diagnostic TTL/GC. A record cannot be protected
merely by calling raw logs “evidence.”

### 8.2 Pre-persistence redaction and bounding

All diagnostic ingestion passes through a versioned normalizer before persistence. It:

- drops credentials, authorization/cookie headers, secrets, API keys, signed URLs,
  request/response bodies, tool debug payloads, and arbitrary Provider payloads;
- allowlists structured fields such as error code/class, retryability, component,
  operation/job/effect identity, attempt/fence, timestamps, and bounded message excerpt;
- normalizes volatile identifiers before fingerprinting where policy permits;
- limits per-field length, object depth, array cardinality, and total serialized bytes;
- stores truncation/redaction decisions and policy version;
- rejects an observation that cannot be safely normalized.

Gate C also audits RuntimeJob and other protected error ingress. Protected recovery
evidence retains only the structured state transition, identity/fence, error
classification, retry decision, and required hashes. It does not retain unbounded stack
traces, headers, credentials, or raw Provider/debug data.

### 8.3 Bounded aggregation and receipt design

Repeated observations aggregate by:

```text
fingerprint
component / diagnostic class
bounded time window
first_seen
last_seen
occurrence_count
representative_sample
latest_bounded_context
```

The representative and latest samples are bounded and redacted. Updating the aggregate
does not append every stack trace.

An observation receipt exists only where exactly-once projection within a replay window
is necessary. Its identity binds source kind/ID/event or transition hash, normalizer
version, and aggregate window. Receipts are not permanent by default:

- active/retryable source receipts remain through the maximum retry/recovery horizon;
- terminal source receipts remain through `scan lookback + retry horizon + safety
  margin`;
- sealed-window receipts may be compacted into a bounded window summary and deleted;
- scanners never rescan events older than their explicit watermark/lookback;
- a small watermark per stream/partition may be protected; a permanent row per
  observation is forbidden;
- a receipt requiring longer retention must name a concrete unresolved recovery or
  qualification dependency and is reclassified as that source evidence, not as an
  immortal diagnostic receipt.

### 8.4 Retention and GC protocol

Each diagnostic policy declares class, normalizer version, aggregate window, hot
retention, receipt horizon, body expiry, protected-reference tests, batch size, and
deletion reason. GC is:

```text
ASSESS / DRY_RUN
→ lease and fence bounded batch
→ recheck expiry and protected/active references in transaction
→ delete or clear payload
→ write bounded batch summary/hash
→ advance checkpoint/watermark
```

It uses `FOR UPDATE SKIP LOCKED` or the repository's equivalent bounded lease pattern,
never a full-table long transaction. A crash can replay the same batch; deleted rows
are idempotently absent and aggregate/summary writes use stable keys. The GC audit
records policy, time range, counts, reason counts, aggregate hash, executor, operation,
attempt, and fence—not one immortal receipt per deleted observation.

The maintenance abstraction is not promoted into a generic scheduler. PR-C adds only
the minimum explicit RuntimeJob kind and executor needed for observation projection
and/or GC, using the current runtime group, lease, checkpoint, and failure paths.

## 9. Gate D — Retrieval Lifecycle Closure

### 9.1 Preserved retrieval order

The canonical order remains:

```text
accepted-boundary and read-generation eligibility
→ metadata/entity/timeline filters
→ deterministic/lexical candidate discovery
→ optional compatible semantic rerank
→ deterministic merge/tie-break
→ Context candidate with scores, reasons, and provenance
```

Semantic similarity is never the only channel and never introduces a candidate that
failed project/book, accepted range, source revision, Digest disposition, active
generation, entity/time, or policy eligibility. If a semantic embedding is unavailable
under a contract that requires it, retrieval fails closed. If the frozen contract says
semantic is optional, the recorded deterministic fallback is allowed and explicit.

### 9.2 Database-enforced typed source references

Gate D supports both existing AssetVersion sources and Narrative Digest sources. The
retrieval document therefore uses two nullable typed FKs:

```text
source_asset_version_id  FK → authority_asset_version
source_digest_id         FK → narrative_digest header
CHECK (num_nonnulls(source_asset_version_id, source_digest_id) = 1)
```

Equivalent portable XOR enforcement is acceptable. Application-only
`(source_kind, source_id)` is forbidden. Composite scope guards or triggers verify that
the chosen source belongs to the document's project/book/book_run, source revision and
accepted range. Embedding projection is FK-bound to the retrieval document and its
source/projection hash, rather than carrying an unchecked parallel polymorphic source.

Upgrade is backfilled and validated before constraints become `NOT NULL`/valid. The
existing AssetVersion source column remains the only populated arm for legacy rows;
new Digest documents populate only the Digest arm. Compatibility fields cannot become
two writable truth paths.

### 9.3 Logical representation, equivalence, and read generation

Definitions:

- **Logical source identity:** `(project, book, book_run, logical_source_key,
  accepted_from, accepted_through)`; it names narrative coverage, not a storage row.
- **Representation identity:** logical source identity + representation kind, source
  identity/revision, schema/generator/projection version, and payload hash.
- **Equivalence identity:** source-set hash plus deterministic coverage hash for the
  continuity-critical structured fields the replacement promises to preserve.
- **Read generation:** an immutable set of retrieval representation memberships for one
  project/book/book_run, selected by one active pointer.

Proposed constraints:

- read generation states are `PREPARING`, `VALIDATED_READY`, `ACTIVE`, `RETIRED`, or
  `INVALIDATED`;
- generation membership has a unique key on
  `(generation_id, logical_source_key, accepted_from, accepted_through)`;
- each membership references exactly one retrieval document;
- only one active-generation pointer exists per project/book/book_run;
- a pointer target must be `ACTIVE` and scope-matched;
- an active generation cannot contain an invalidated/superseded source;
- retrieval discovery joins the selected generation; table presence alone never makes
  a document readable.

This prohibits an old AssetVersion document and a replacement Digest document from
both entering the same candidate set for one logical source/range. Frozen historical
retrieval rounds/manifests keep their generation and representation IDs; exact replay
does not substitute the current generation.

### 9.4 Pre-cutover lexical and embedding construction

A replacement generation is populated while `PREPARING`. Its document payload and
generated lexical vector are created before validation. Compatible embedding
projections are then built or reconciled against those inactive documents using the
existing attempt/lease/fence/ExternalEffect semantics.

The current embedding scheduler already discovers missing document projections without
depending on a production-active flag. Gate D preserves that property and widens the
source loader to the typed Digest source. Production retrieval continues to join only
the active generation. Thus build visibility and read visibility are separate:

```text
Embedding worker visibility: PREPARING + VALIDATED_READY + ACTIVE documents
Production retrieval visibility: active generation membership only
```

Model identity, dimensions, projection version, route snapshot, source hash, document
hash, receipt, and failure status remain explicit. Partial indexing is observable but
cannot make the generation `VALIDATED_READY`. Lost-index rebuild is idempotent from the
protected header and Digest/source payload while it still exists.

### 9.5 Retrieval campaign and Context integration

Retrieval intent, every immutable campaign round, and final result freeze:

- accepted boundary;
- read generation ID;
- query/metadata constraints;
- lexical algorithm/version;
- semantic mode/model/dimensions/projection version;
- eligible document/representation IDs and source revisions;
- scores and reasons by channel;
- drop/dedup reasons;
- deterministic merge/tie-break version.

The final result yields candidates, scores, reasons, token cost, and provenance to Gate
A. It never returns an unexplained block that bypasses Context eligibility or budget.

## 10. Gate E — Derived Narrative Representation Compaction/Purge

### 10.1 Scope and protected boundary

Gate E is formally named **Derived Narrative Representation Compaction/Purge**. It
operates only on:

- structured Digest payloads;
- retrieval document payload/lexical materializations;
- embedding vectors and rebuildable projection payloads;
- their non-authoritative compact replacements.

It does not compact or purge Accepted Actual, Canon, Canonical Narrative State, active
planning Authority, required Authority/event lineage, Audit, Qualification, Recovery,
Provider-effect Evidence, or required source lineage. It also does not delete the
`DEFERRED_RETENTION` classes listed in section 5.

### 10.2 Eligibility

A source representation is eligible only when all are true:

- it is derived and marked `RETENTION_MANAGED`;
- its Authority/source lineage, hashes, accepted boundary, and rebuild contract exist;
- it is not the only representation required by an active or frozen historical
  manifest/round/recovery operation;
- no pending/running job, attempt, lease, effect, reconciliation, qualification run, or
  future-only replan references its payload;
- the replacement coverage is explicit and no accepted range is omitted;
- the policy permits this representation type and age;
- there is no legal/operational hold or continuity-loss witness.

Eligibility is a calculated fact captured in an immutable receipt. It is not a new
Authority status.

### 10.3 Compact artifact and manifest

A **Compact Artifact** is the prepared replacement set: Digest payloads, retrieval
documents/lexical materializations, compatible embeddings, and one immutable read
generation membership. It is derived, non-authoritative, and non-readable while being
prepared.

A **Compaction Manifest** is the protected plan header plus source and replacement
identities, policy/compiler versions, accepted coverage, equivalence identity, probe
corpus, operation/attempt/fence, state, and hashes of every required receipt. It does
not copy Accepted Actual, Canon, or Canonical Narrative State payloads.

### 10.4 Minimal persisted plan state

Only boundaries with distinct crash, recovery, fencing, or cutover invariants are
primary states:

| Persisted state | Why it must persist | Required evidence before transition |
|---|---|---|
| `PLANNED` | freezes source membership, target logical coverage, policy, operation, attempt, and fence before any replacement work | assessment/eligibility receipt |
| `PREPARING` | replacement rows and possibly in-flight lexical/embedding ExternalEffects exist; recovery must know what to resume/reconcile | prepared-artifact identity and build checkpoints |
| `VALIDATED_READY` | establishes the only state from which the active pointer may change | deterministic coverage receipt, probe-corpus retrieval receipt, complete required embedding receipt |
| `CUTOVER` | active read pointer has changed atomically, but post-cutover production-read verification/tombstone may not have completed | cutover transaction receipt with old/new generation IDs and fence |
| `TOMBSTONED` | old representation is durably non-readable and the grace clock has begun | post-cutover verification receipt and tombstone receipt |
| `PURGED` | protected header remains but managed payload is physically absent | grace/reference recheck and purge receipt |

There is no primary `ASSESSED`, `ELIGIBLE`, `LEXICAL_BUILT`, `INDEX_REBUILT`,
`VERIFIED`, or `PURGE_ELIGIBLE` state:

- assessment and eligibility are deterministic receipt contents attached to `PLANNED`;
- lexical build is a payload fact/checkpoint;
- embedding readiness is read from typed projection rows and summarized by a receipt;
- validation and post-cutover verification are immutable receipts;
- purge eligibility is recomputed from tombstone time, grace policy, active references,
  holds, and DB time immediately before purge.

A failed action leaves the plan in its last safe state with a bounded failure receipt.
Manual `BLOCKED` disposition may exist only for a non-retryable governance decision; it
is not another automatic phase.

Read-generation state and compaction-plan state are not duplicate workflows. A read
generation expresses whether one immutable representation set is discoverable;
the compaction plan records the fenced destructive operation, validation receipts,
grace, and purge outcome. Their transitions are cross-checked but owned separately.

### 10.5 Ordered lifecycle

```text
ASSESS / PLAN
→ PREPARE replacement
→ build lexical projection
→ prebuild or reconcile embedding projection
→ deterministic coverage validation
→ retrieval-behavior validation
→ VALIDATED_READY
→ atomic CUTOVER of active read-generation pointer
→ post-cutover verification through production read path
→ TOMBSTONE old representation
→ grace period
→ reference/hold/recovery recheck
→ PURGE managed payload
→ physical storage maintenance outside the cutover transaction
```

No deletion occurs before cutover, and no cutover occurs before the replacement's
required semantic projections are ready. A failed prebuild leaves the old generation
active. A failed post-cutover verification leaves the old payload intact and triggers a
fenced rollback of the read pointer when the old generation remains valid; it never
purges.

The cutover transaction locks the plan and active pointer, verifies the current fence,
revalidates `VALIDATED_READY`, makes the new generation active, retires the previous
generation, and records one immutable receipt. A duplicate request observes the same
pointer/receipt and returns replayed success. A stale fence cannot change either
generation.

Tombstone means excluded from every new read and from ordinary rebuild scheduling; it
does not mean payload deleted. Grace uses database time. Purge clears/deletes only the
payload rows and vectors, leaves protected header/lineage/tombstone/purge receipt, and
is idempotent when payload is already absent.

### 10.6 Deterministic coverage and retrieval-behavior qualification

Structured validation compares protected source/old representation and replacement for
sets and transitions covering at least:

```text
characters
relationships
timeline events/order
known/revealed facts
open/resolved threads
foreshadowing and clues
obligations
continuity constraints
accepted source lineage
```

Gate E also freezes a representative probe corpus in a schema-backed validation
artifact. It includes character, relationship, timeline, exact fact, open thread,
foreshadow/clue, obligation, and historical-callback probes. For each probe, the
contract defines required source/coverage identities, accepted-boundary eligibility,
minimum deterministic/lexical recall, optional semantic expectations, forbidden stale
or duplicate representation, and stable reason evidence.

Validation runs the same frozen probes before and after cutover and requires:

- every required recall witness remains present;
- no source beyond the requested accepted boundary appears;
- no old/new duplicate logical representation appears;
- no superseded/invalidated source is active;
- every result retains traceable provenance;
- continuity-critical structured coverage is equal or an explicitly stronger
  deterministic superset under the approved schema.

An LLM judge may add qualitative evidence but cannot admit destructive purge. Any
continuity-critical loss witness makes validation fail and prohibits
`VALIDATED_READY`, cutover, tombstone, and purge until a new replacement is prepared.

## 17. Unresolved risks and trade-offs

These are implementation-time design checks, not permission to widen scope:

1. **Tokenizer availability and serialization fidelity.** Some Provider SDKs may not
   expose the exact tokenizer/framing. PR-A must either prove a conservative
   provider/model-bound upper bound or fail closed for that route. It must not silently
   fall back to character estimates.
2. **Context policy source duplication.** Current Context, Stage, and Execution policies
   overlap. The compiler closes behavior without moving ownership. A later ownership
   consolidation is not authorized here; PR-A must surface contradictory current
   policy inputs as failures rather than guess intent.
3. **Digest generator choice.** Deterministic projection is preferred. Any LLM-derived
   field adds Provider/retry/cost variability and must have a real consumer and a
   deterministic coverage validator.
4. **Book branch identity.** Current executable production uses `book_run_id`; the Spec
   binds to it. If main introduces a first-class branch Authority before PR-B, the PR
   must re-audit and either map or revise the Spec before DDL.
5. **Digest timing.** Asynchronous generation deliberately permits no `CURRENT` Digest
   briefly after head advance. Canonical state stays correct; Context contracts must
   state whether `VALID_AS_OF` is acceptable or whether the task waits/fails.
6. **Payload/header split upgrade cost.** Current retrieval text and generated search
   vector share the document table. PR-D/E must benchmark safe backfill and query plans;
   the split cannot create dual writable payloads.
7. **Embedding prebuild cost and provider availability.** Prebuild is architecturally
   possible with the current scheduler seam, but a policy-required semantic generation
   may stay PREPARING during Provider outage. Availability is preserved by retaining
   the old active generation, not by cutting over early.
8. **Frozen historical read generations.** Retaining headers/memberships has growth
   cost. This work package bounds bulky payload but intentionally keeps the small
   lineage required for exact replay. Archival of that lineage is out of scope.
9. **Diagnostic source scan ordering.** Current source tables differ in event ordering.
   PR-C must choose an indexable watermark/lookback per concrete source rather than
   invent a universal event bus.
10. **Observation receipt horizon.** Too short permits old duplicate projection; too
    long increases storage. PR-C must derive the horizon from actual max recovery,
    replay, and scan lookback settings and prove bounded growth.
11. **Cutover rollback concurrency.** A new accepted head or independent representation
    change during post-cutover verification could make rollback unsafe. PR-E must lock
    or compare the active pointer generation/fence and block for operator review rather
    than overwrite a newer generation.
12. **Probe corpus representativeness.** The frozen corpus proves named retrieval
    invariants for the qualification fixture, not all future narrative semantics.
    Coverage schema and production incidents may add probes only through versioned
    evidence; no probe may be weakened to manufacture a pass.
13. **Qualified semantic equivalence.** Exact structured coverage and required recall
    are necessary destructive gates. They do not establish prose equivalence or human
    narrative quality.
