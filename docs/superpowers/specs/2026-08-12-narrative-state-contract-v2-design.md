# Narrative State Contract v2 Design

Date: 2026-08-12
Start SHA: `55b33675f223488fe7193d672ecdfc7e7df28737`
Branch: `refactor/narrative-state-contract-v2`

## Scope and decision

Narrative State v2 converges the semantics that connect accepted narrative events, current state, historical state, governed context, and future planning. It does not create a new narrative authority, replace PostgreSQL AssetVersion history, or redesign Book/Chapter Authority, Command Kernel, PlanChange, providers, or agent execution.

The selected approach is a shared typed contract carried by the existing Authority assets:

1. `ChapterOutcome` is the immutable, chapter-sized ledger batch of accepted actuals. Its v2 content contains normalized Narrative State events.
2. `StoryStateSnapshot` is the deterministic, compact current-state materialization produced from ordered ChapterOutcome events.
3. PostgreSQL views expose accepted events and accepted current snapshots. Temporal Query replays events at an inclusive chapter boundary.
4. Production Preparation and Book dispatch freeze the immediately preceding accepted StoryState and Canon snapshot, rather than every historical per-kind change asset.

This is deliberately not a new normalized event table. The existing immutable AssetVersion plus Book chapter-acceptance record remains the durable Authority boundary. The new SQL surfaces are rebuildable projections.

## Alternatives considered

### A. Patch only `reduce_story_state()`

Replacing `list.extend()` with a few keyed updates would reduce snapshot growth, but it would leave identity, temporal, supersession, provenance, and accepted-boundary semantics duplicated across Canon, Temporal Query, and Context. It would also preserve the unsafe Production Preparation query over globally active state outputs. Rejected because it treats symptoms.

### B. Shared event contract over existing Authority assets (selected)

Normalize events once when ChapterOutcome is built, reduce them through typed policies, project them through Book acceptance, and freeze compact accepted snapshots into Context. This preserves Authority/storage ownership, provides a deterministic v1 evidence adapter, and avoids a second runtime.

### C. New event/current-state Authority tables

Dedicated tables could enforce more SQL constraints, but they would duplicate ChapterOutcome and AssetVersion authority and introduce cross-authority transaction questions. Rejected because current immutable evidence is sufficient and the derived state must remain rebuildable.

## Current-code audit

| Surface | Current classification | Evidence and issue | v2 disposition |
|---|---|---|---|
| Canon patch and Canon approval | `TRUTH` candidate/decision boundary | `canon_graph/domain.py` validates structured changes and emits per-kind objects called snapshots, but each contains only `changes` | Keep Canon as validity authority; emit a true materialized Canon snapshot and feed normalized events to ChapterOutcome |
| Canon per-kind outputs | `STATE_EVENT`, mislabeled as snapshots | `_CanonHandler` emits 11 `role=state_snapshot` assets whose payloads are change arrays | Stop treating them as current state; ChapterOutcome v2 becomes the accepted event batch |
| ChapterOutcome | `ACCEPTED_ACTUAL` | `chapter_outcome/domain.py` is immutable evidence but duplicates untyped field names and lacks common identity/temporal/lineage fields | Replace the v1 flat delta fields in the canonical path with normalized `state_events`; retain a deterministic v1 evidence adapter for rebuild only |
| StoryStateSnapshot | `CURRENT_STATE` | `reduce_story_state()` applies one append-only reducer to 14 dimensions and carries the full change history forward | Materialize keyed entity state and lifecycle/balance transitions; retain append-only semantics only for event-like dimensions |
| Temporal Query | `TEMPORAL_PROJECTION` | The service independently guesses identity and accepts `supersedes_version_id`, `supersedes_asset_version_id`, and `state_version_id`; SQL orders partly by recorded time | Read normalized accepted events, use the same reducer semantics, and use recorded time only as evidence, never narrative chronology |
| Production Preparation | `EXECUTION_CONTEXT` selection | The resolver selects globally active per-kind snapshots, then relies on payload chapter metadata; an unaccepted Chapter output can be eligible | Resolve narrative state only through committed Book acceptance and require Project/Book/chapter scope |
| Governed Context Builder | `EXECUTION_CONTEXT` | Version, selected/rejected, source-isolation and token-budget contracts are sound, but StoryState content is not converted into compact structured facts | Keep the builder; add compact StoryState rendering and immutable state/event lineage refs |
| Book acceptance | Authority boundary for accepted actual | Transactionally records ChapterOutcome, StoryState, Canon snapshot and advances the book cursor | Preserve; its committed row is the only status that upgrades outcome events to accepted |
| Longform recap and Reader results | `OBSERVATION` | Reports explicitly prohibit mutation of accepted chapters | Keep read-only; consume accepted compact state and as-of evidence |
| Hierarchical Plan and ChapterPlan | `FUTURE_INTENT` | Planning contracts bind Project/Book, parent versions and execution scope | Keep separate; add plan lineage on ChapterOutcome only |
| PlanChange | `FUTURE_INTENT` governance | Owns proposal/approval/activation; it does not own actual state | No redesign |
| CharacterCard and World design assets | Design truth/candidate inputs, not accepted actual | Independent design contracts and version lineage | Do not collapse into Narrative State |
| KnowledgePack/KnowledgeCard | `RETRIEVABLE_KNOWLEDGE` | MKAOS owns evidence, qualification and source isolation | Do not treat knowledge retrieval as narrative truth or character knowledge |
| Quality/provider outputs | `OBSERVATION` until governed acceptance | Model outputs and quality reports are gated evidence | Never mutate Canon or StoryState directly |

## Shared semantic contract

Every v2 Narrative State event has one canonical shape and answers the required questions without field aliases:

- `event_id`: deterministic identity derived from scope, source ChapterOutcome identity, ordinal, state kind, entity identity, mutation and payload.
- `layer`: always `STATE_EVENT` for ledger entries.
- `state_kind`: one typed state kind.
- `scope`: `project_id` and `book_id`.
- `identity`: `identity_kind`, canonical `entity_key`, and typed `components`.
- `coordinate`: `source_chapter` and inclusive `effective_from_chapter`; the effective boundary may not exceed the accepted/source chapter. A closing boundary is represented by an explicit lifecycle/supersession event rather than a speculative implicit expiry.
- `authority`: the persisted event requires committed Book acceptance. A read projection supplies `status=ACCEPTED` and `accepted_chapter`; orphan assets remain non-authoritative.
- `mutation`: one of `UPSERT`, `TRANSITION`, `OPEN`, `CLOSE`, `ACTIVATE`, `SUPERSEDE`, `INCREMENT`, `DECREMENT`, or `APPEND` plus the typed payload.
- `version`: event contract version and entity-version intent.
- `supersession`: only `supersedes_event_id`. v1 aliases are accepted only by the rebuild adapter and are never emitted by v2.
- `provenance`: Canon patch AssetVersion, accepted draft AssetVersion, source Operation, trace, ChapterOutcome identity, and source event location.
- `confidence`, `coverage`, and `evidence`: explicit values copied from governed extraction evidence, never inferred from database timestamps.

The canonical event representation does not use `chapter`, `effective_chapter`, `supersedes_version_id`, `supersedes_asset_version_id`, or `state_version_id`. Those names remain readable only at the v1 evidence boundary.

## State kinds and reducer semantics

| State kind | Identity | Current materialization | Reducer semantics |
|---|---|---|---|
| `canon_fact` | `(subject, predicate)` | one accepted current value per semantic slot | explicit supersede or consistent upsert |
| `timeline_event` | `event_id` | ordered event ledger | append-only; duplicate event IDs are idempotent |
| `character_state` | `character_id` | merged current attributes and knowledge set | upsert; acquired/forgotten knowledge is set-aware; terminal life state is transition-checked |
| `relationship_state` | directed `(source_id, target_id)` | one current relationship edge | transition/upsert with declared-from validation |
| `world_rule` | `rule_id` | one current rule | activate/upsert/supersede; terminal inactive rules remain historical only |
| `resource_state` | `(entity_id, resource_id)` | current balance and attributes | set initial balance or apply checked increment/decrement |
| `power_state` | `character_id` | current tier/capabilities/availability | checked transition/upsert |
| `foreshadow_state` | `thread_id` | current lifecycle state | open/transition/close; terminal states cannot silently reopen |
| `reader_promise` | `promise_id` | current lifecycle state | open/transition/close; paid/cancelled are terminal |
| `plot_thread` | `thread_id` | current lifecycle state | open/transition/resolve |
| `narrative_debt` | source-kind plus source identity | only current open/resolved debt state | derived open/resolve transitions from promise and foreshadow events |
| `mystery_state` | `mystery_id` | current lifecycle state | open/transition/resolve |
| `antagonist_state` | `antagonist_id` | current adaptation/pressure state | upsert/transition |
| `arc_state` | `arc_id` | current arc contribution/status | upsert/transition |
| `reward_event` | `reward_id` or deterministic event identity | ordered reward ledger | append-only |
| `theme_movement` | deterministic movement identity | ordered movement ledger | append-only |

Reducers reject unknown state kinds, missing identities, illegal mutation kinds, scope drift, source/effective chapter drift, invalid predecessor state, unknown supersession targets, and inconsistent resource balances. Applying the same head ChapterOutcome twice returns the same snapshot. Applying an older outcome to a later snapshot fails closed as out of order.

## Event, current state, and temporal projection

### Immutable accepted event

`ChapterOutcome` v2 stores the event list and plan/release/quality/Canon lineage. The asset can be materialized before the Book commit, but it is not an accepted actual until a committed `authority_book_chapter_acceptance` row references it. The PostgreSQL event projection is therefore rooted at the acceptance row, not AssetVersion lifecycle or creation time.

### Materialized current state

`StoryStateSnapshot` v2 stores sorted entity-aware `current_state` collections, the accepted-through boundary, the immediately prior snapshot/outcome references, the latest reducer receipts, and a deterministic state hash. It does not carry every past change or every applied outcome ID. Timeline, reward and theme are the only intentionally append-only current dimensions.

### As-of temporal projection

Temporal Query loads accepted events for the requested Project, Book, and inclusive chapter boundary, sorts by `effective_from_chapter`, `source_chapter`, source outcome, and event ordinal, and invokes the same reducers used by StoryState. `recorded_at` is returned as audit evidence but is not part of narrative ordering. A future-effective or future-accepted event is excluded in SQL and rejected in Python.

## Supersession and time

- `recorded_at` means database audit time only.
- `source_chapter` is the chapter whose accepted outcome emitted the event.
- `accepted_chapter` comes only from the committed Book acceptance row and must equal the source outcome chapter for the canonical path.
- `effective_from_chapter` is the first inclusive narrative chapter at which the state applies and must be less than or equal to `accepted_chapter`.
- Lifecycle closing and supersession are explicit accepted events; v2 deliberately has no implicit `effective_to_chapter` expiry that could advance state without an accepted event.
- `supersedes_event_id` closes/replaces one earlier event with the same state kind, scope and entity identity. History is never updated or deleted.

## Future-leak invariant

The invariant is enforced at four boundaries:

1. Event construction rejects `effective_from_chapter > source_chapter`.
2. PostgreSQL projections begin at committed Book acceptance and filter `accepted_chapter <= requested chapter`.
3. Temporal replay filters both accepted and effective boundaries and fails on malformed persisted evidence.
4. Production Preparation and Book dispatch resolve only the immediately preceding committed StoryState/Canon snapshot for the same Project and Book. Direct active-AssetVersion scans cannot satisfy narrative-state requirements.

Quality, Reader, recap, planning and model context receive the same frozen ContextBundle. They cannot independently select later state.

## Ownership and prohibited flows

- Canon remains the validity/truth authority and produces governed change evidence plus the current Canon snapshot candidate.
- ChapterOutcome becomes accepted actual only at Book acceptance.
- StoryState is a deterministic projection and cannot authorize Canon changes.
- Temporal Query and rebuild are read-only.
- Plan remains future intent; ChapterOutcome records the source ChapterPlan version without auto-activating planned deltas.
- Context is immutable execution input and cannot mutate state.
- Knowledge remains MKAOS-governed external methodology/fact evidence and never becomes narrative or character knowledge through retrieval alone.
- Model, recap, Reader, Quality and feedback results cannot directly mutate Canon, current state or active plans.

## PostgreSQL migration and rebuild

Forward-only migration `20260812_0082_narrative_state_contract_v2` will:

1. replace the temporal event read surface with an accepted ChapterOutcome-rooted v2 projection and expose accepted v1/v2 outcomes through a separate rebuild source;
2. add a latest accepted current-state projection rooted at Book acceptance and StoryState/Canon AssetVersions;
3. extend reducer-application evidence with reducer semantics, accepted chapter, event IDs and entity identity;
4. add indexes needed for Project/Book/chapter as-of and current lookups.

No historical AssetVersion or acceptance row is updated. Rebuild reads accepted outcomes in Book/chapter order, adapts v1 evidence deterministically when necessary, replays through the v2 reducer, and returns a content/hash comparison. Persisting a rebuilt AssetVersion remains an owning Authority operation and is not performed by Temporal Query.

## Context integration

For chapters after the first, the canonical preparation requirement becomes:

- one immediately preceding accepted `story_state_snapshot` v2;
- one immediately preceding accepted `canon_snapshot` v2;
- normal frozen planning/profile/governance inputs.

StoryState is rendered into a bounded structured-fact list with one current item per materialized entity. Canon facts come from the separate accepted Canon snapshot, while append-only timeline/reward/theme evidence is requested through Temporal Query only when a stage explicitly needs it. The manifest continues to record exact AssetVersion refs, selected/rejected items, entity scope, token budget, source isolation, digest and qualification; the normal draft context does not receive every old delta.

## Compatibility strategy

There is one production runtime: v2.

Persisted v1 ChapterOutcome and Canon change assets are supported only by deterministic read/rebuild adapters. New ChapterOutcome, StoryState, Context and Temporal outputs emit v2 field names and semantics. The old flat StoryState append lists and the multiple supersession aliases are not emitted.

## Verification design

The semantic suite uses readable chapters and facts:

- Chapter 1: Lin is in Hangzhou.
- Chapter 10: Lin learns Secret-X.
- Chapter 20: Lin and Mei become hostile.
- Chapter 30: Lin moves to Beijing.
- Chapter 40: Promise-P opens.
- Chapter 50: WorldRule-R activates.
- Chapter 60: Resource-X decreases.
- Chapter 70: Foreshadow-F is paid.
- Chapter 80: Promise-P is paid.
- Chapter 90: Lin and Mei repair their relationship.
- Chapter 100: PlotThread-T resolves.

Unit tests prove contract validation, all reducer policies, idempotence, out-of-order failure, supersession, deterministic replay and missing state. Architecture tests prove ownership/import boundaries and prohibit Context/Temporal/Plan mutation paths. PostgreSQL integration tests prove accepted-only events/current state, future-leak exclusion, migration runtime behavior, rebuild equality, rollback/orphan exclusion and Book-to-Chapter consumption of compact current state.

## Exit criteria

Narrative State Contract v2 is complete when the production Chapter acceptance path emits only v2 ChapterOutcome and StoryState semantics; current state is entity-aware rather than a universal append list; Temporal Query and Context are accepted-only and Project/Book/chapter scoped; v1 evidence is rebuildable through a one-way adapter; migration, replay, Book integration and semantic future-leak tests pass; and all repository quality gates remain green.
