# Narrative State Contract v2

Narrative State v2 unifies the semantic protocol between accepted narrative
events, materialized current state, historical as-of state, governed context,
and future planning. It does not merge their Authorities or storage lifecycles.

## Ownership and classification

| Surface | Classification | Owner and rule |
|---|---|---|
| Canon decision and accepted Canon snapshot | `TRUTH` | Canon and Book acceptance decide narrative validity. Model output is only a candidate. |
| ChapterOutcome v3 | `ACCEPTED_ACTUAL` | Immutable state, Arc, obligation and Scene evidence for one chapter; authoritative only when a committed Book acceptance points to the AssetVersion. |
| NarrativeStateEvent v2 | `STATE_EVENT` | Append-only delta stored inside ChapterOutcome; never updated or deleted. |
| StoryStateSnapshot v2 | `CURRENT_STATE` | Deterministic, entity-aware projection of accepted events; rebuildable and not an Authority replacement. |
| ArcProgress / NarrativeObligationState | `ACCEPTED_PROJECTION` | Deterministic ChapterOutcome projections at the exact accepted boundary; never inferred from ChapterPlan. |
| Temporal query result | `TEMPORAL_PROJECTION` | Read-only replay at an inclusive accepted chapter boundary. |
| ChapterPlan and hierarchical plans | `FUTURE_INTENT` | Planning/PlanChange Authority owns candidates and activation; plans never become actuals automatically. |
| ContextBundle | `EXECUTION_CONTEXT` | Frozen, isolated and token-budgeted input with exact AssetVersion refs. It cannot mutate state. |
| KnowledgeCard/KnowledgePack | `RETRIEVABLE_KNOWLEDGE` | MKAOS-governed external facts and methods; retrieval does not make them Canon or character knowledge. |
| Reader, recap and quality output | `OBSERVATION` | Evidence/proposals only; no direct Canon, StoryState or plan mutation. |

The accepted flow is:

```text
committed Book chapter acceptance
  -> immutable ChapterOutcome v3 events
  -> deterministic StoryState/Canon/Arc/Obligation current projections
  -> accepted-only temporal replay and compact Context
  -> future planning candidate
```

## Shared event contract

Every v2 event carries:

- `state_kind` and a typed `identity` with a stable `entity_key`;
- `scope.project_id` and `scope.book_id`;
- `coordinate.source_chapter` and inclusive `effective_from_chapter`;
- pending/accepted Authority boundary semantics;
- a typed reducer mutation;
- only `supersedes_event_id` for supersession;
- Canon patch, accepted draft, ChapterOutcome, source Operation and trace lineage;
- confidence, coverage and governed evidence.

`recorded_at` is audit time and never narrative time. New v2 evidence rejects
the v1 aliases `effective_chapter`, `supersedes_version_id`,
`supersedes_asset_version_id`, and `state_version_id`. Persisted
`chapter-outcome-v1` evidence remains readable only through the deterministic
rebuild adapter.

## Event, current state and temporal projection

ChapterOutcome stores what an accepted chapter changed. The event list is
immutable and replayable. Creating an AssetVersion is not acceptance: the SQL
event view starts at `authority_book_chapter_acceptance` rows whose status is
`COMMITTED` and whose acceptance Operation succeeded.

StoryState stores what is currently true through the latest accepted chapter.
It has one sorted entry per state kind and entity identity. Character location,
relationship status, Promise lifecycle, rule status and resource balance are
materialized values, not ever-growing change arrays. Timeline, reward and
theme movements remain append-only because their business meaning is an event
ledger.

Temporal Query filters by Project, Book and `accepted_chapter <= N`, then
replays the same reducers used by current state. It never orders by
`created_at`, never reads unaccepted child outputs and never exposes events
accepted after the requested boundary.

## Reducer matrix

| State kind | Identity | Reduction |
|---|---|---|
| Canon fact | subject + predicate | consistent upsert; changed definition requires explicit supersession |
| Timeline event | event id | append-only |
| Character | character id | attribute upsert and knowledge-set merge; death/invalidation cannot silently reopen |
| Relationship | directed source + target | checked transition/upsert |
| World rule | rule id | activate/upsert; definition change requires explicit supersession |
| Resource | entity + resource | initial balance or reconciled increment/decrement |
| Power | character id | checked tier/state transition |
| Narrative Obligation | obligation id | unified promise/foreshadow/mystery/open-loop/conflict/hook/commitment/expectation/debt lifecycle with development/payoff evidence |
| Legacy foreshadow/promise/plot thread/debt/mystery | legacy identity | deterministic input adapter into Narrative Obligation; not a parallel target projection |
| Antagonist | antagonist id | entity-aware upsert/transition |
| Arc | arc id | entity-aware lifecycle |
| Reward and theme movement | event identity | append-only |

All reducers are deterministic, order-aware, idempotent at the already-applied
head, replayable and fail closed on scope drift, missing identity, invalid
predecessors, broken balances or incorrect supersession targets.

## Future-leak invariant

Four boundaries enforce the invariant that Chapter N cannot consume Narrative
State created or accepted after N:

1. Event construction rejects future-effective changes.
2. PostgreSQL views expose only committed Book acceptance evidence.
3. Temporal Query requires Project/Book scope and filters accepted/effective
   chapter boundaries before replay.
4. Production Preparation resolves only the immediately preceding accepted
   StoryState v2 and Canon v2 pointers for the same Book. A globally active,
   unaccepted AssetVersion and a typed-empty fixture cannot satisfy the state
   requirement.

## Context behavior

Continuing chapters freeze exactly one accepted StoryState v2 and one accepted
Canon v2 snapshot. StoryState is flattened to bounded structured facts with one
current value per entity, while preserving source event, effective chapter,
confidence, coverage and evidence. The existing Context Builder still owns
selection, rejection, source isolation, immutable refs and token budgets.
Historical evidence is obtained through an explicit temporal read; the normal
Context is not an unbounded history list.

Context v2 protects the exact active plan and critical accepted
state/Canon/Arc/Obligation entries from token trimming, then retrieves
historical evidence through lexical, embedding, entity/relationship, timeline,
temporal, Arc and obligation signals. The 22-node Chapter composition consumes
the resulting Manifest/Bundle after ExecutionIntent and Memo. Missing protected
budget fails closed; vector similarity is only one retrieval signal.

## Arc observation defect at the audit baseline

At baseline `4fdf6adaa25ef085e4e6abab1f5b6ac71d86607a`, the post-acceptance Arc
checkpoint code fell back from missing ChapterOutcome actual contributions to
ChapterPlan declarations and recorded them as `ACTUAL`. Forward migration 0094
and the current reducer remove that fallback. Only qualified accepted Arc
evidence may materialize actual progress; absent evidence stays
`NOT_OBSERVED`, `NOT_MATERIALIZED`, or `UNKNOWN`.

## Migration and rebuild

Forward-only migration `20260812_0082_narrative_state_contract_v2` established:

- accepted-only event and current-state views;
- an accepted v1/v2 rebuild-source view;
- event/entity/reducer/accepted-chapter evidence on reducer receipts;
- replay indexes keyed by Project, kind, entity and accepted chapter.

Forward-only migration `20260820_0094_industrial_autonomous_novel_os` extends
the accepted event and rebuild views to `chapter-outcome-v3` and adds the
atomic long-form projection set. Neither migration rewrites AssetVersion,
ChapterOutcome or Book acceptance history. `NarrativeStateRebuildService`
reads accepted outcomes in chapter order, adapts earlier evidence at the input
boundary, replays deterministic reducers and returns a projection/hash without
mutating Authority.

Migration `20260821_0095_post_merge_correctness_repair` is the forward repair
for installations that upgraded through 0094 with accepted history but missing
or stale projection pointers. The migration only discovers/registers work.
The durable runtime executes bounded repair Operations under Attempt lease and
fence, and uses the same canonical accepted-evidence projector as live Book
Acceptance. It validates the continuous `1..N` acceptance sequence, exact
AssetVersion hashes and all projection components before a single terminal CAS
activates Chapter N. Partial repair never advances the Book pointer. Missing
legacy Arc evidence remains `UNKNOWN`; planned contribution is forbidden as a
substitute.

`AUTHORITATIVE_REPAIR_COMPLETE` is independent from
`RETRIEVAL_SEMANTIC_PROJECTION_READY`. Document embeddings are versioned,
receipt-backed, rebuildable projections and cannot block correct Canon/State
recovery or an explicitly frozen FTS/graph/temporal fallback profile.

## Qualification boundary

Semantic unit tests and real PostgreSQL integration establish local validation
of the bounded Narrative State v2 slice, including Book acceptance, replay,
rebuild equality and future-leak exclusion. They do not establish real-provider
quality, sustained 1000-chapter operation, production authorization, multi-book
scale or long-form content qualification.
