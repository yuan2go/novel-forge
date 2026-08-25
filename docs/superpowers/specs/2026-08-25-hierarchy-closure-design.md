# WP-HIERARCHY-CLOSURE-01 Design

> Status: approved implementation specification. The Canonical Overall Design remains the only target architecture source of truth. This file records the bounded implementation design for the active work package and is removed after its durable decisions and exact-SHA evidence converge into canonical documentation.

## Objective

Close one governed, durable hierarchy from qualified story formation through causal narrative realization, Chapter production, accepted reality, and future-only replan. The work extends existing StoryDesign, BookDesign, Hierarchical Planning, Book Authority, Chapter Authority, Narrative State, and Command Kernel boundaries; it does not create another Story, Planning, Workflow, or Agent Authority.

## Authority model

The Foundation Set has six independently versioned, qualified design contracts:

1. Creative Foundation owns premise, target reader, genre, differentiation, narrative engine, and creative invariants.
2. Theme Contract owns the thematic question and permitted answer space.
3. Ending Intent owns direction and required terminal transformation without prematurely fixing scene detail.
4. Reader Promise owns the emotional, genre, serialization, and payoff contract.
5. WorldBible owns stable world rules and their costs, exceptions, consequences, conflict potential, and narrative function.
6. CharacterCast owns stable character foundations and relationship seeds.

BookDesign v5 is a qualified synthesis/reference contract. It binds the exact AssetVersion and content hash of all six contracts, records cross-layer invariants and narrative architecture, and never copies WorldBible or CharacterCast truth. Any convenience snapshot is explicitly derived and carries all source bindings.

Platform and production profiles remain operational constraints. They are frozen production inputs but are not Foundation truth.

## Story formation

`StoryFormationApplication` is a durable, idempotent, restartable process manager. API admission creates an existing Command Kernel Operation and a persisted formation run. A worker advances named checkpoints, delegates candidate creation/evaluation/approval/activation to existing owning Authorities, and records every immutable output binding. It never activates a design directly and owns no story truth.

Creative exploration uses a thin Creative Search application over shared immutable candidate, evaluation, comparison, and selection primitives. Creative candidates do not become Planning scopes merely to reuse Narrative Search. Selection is evidence for StoryDesign approval, not activation authority.

Each downstream layer freezes exact upstream bindings. Layer validators contain:

- structural checks for the layer's typed contract;
- independent semantic evaluation with provider/Attempt lineage;
- cross-layer coherence checks against exact parent hashes;
- freshness checks at approval, activation, Book opening, and production admission.

An upstream replacement marks only future dependent design/planning bindings stale. Executed history remains immutable.

## Narrative realization

`NarrativeRealizationContract` is an independent typed causal/correctness contract governed by Hierarchical Planning Authority. It is not `PlanContractType.NARRATIVE_REALIZATION`, not a new narrative scale, and not accepted actual.

The contract binds exact Book/Volume/Arc/ChapterGroup plan versions, the complete accepted boundary, Arc Working Set, Foundation Set, constraints, and the immutable realization content/proof assets. Its lifecycle is `PROPOSED → QUALIFIED → APPROVED → FROZEN → EXECUTED`, with terminal or corrective `REJECTED`, `STALE`, and `SUPERSEDED` states. Only qualified and approved contracts may freeze; only a current frozen contract may authorize ChapterPlan generation.

The content is an AEC2-style executable causal event chain. Each planned event has stable identity, group slice, causes, actor, motivation, preconditions, knowledge boundary, action/decision, resistance, consequences, typed state deltas, disclosures, obligation/promise/payoff/foreshadow actions, Arc contributions, irreversible changes, and next-event causality. The proof establishes upper-plan coverage, Canon/state legality, motivation, world legality, knowledge legality, causal escalation, expected state transitions, obligation/Arc coverage, narrative-load bounds, and legal Chapter decomposition.

Scene and Beat remain embedded typed children of ChapterPlan. ChapterPlan binds a realization slice and exact planned event IDs while retaining ChapterGroup as its structural parent.

## Consumption and accepted reality

Realization consumption maps `Planned Event → Observed Event → Accepted Actual` without changing the Plan/Actual boundary. A ChapterPlan is atomically marked `EXECUTED` during successful Chapter acceptance. A multi-Chapter realization advances only the accepted slice coverage represented by that outcome. It becomes `EXECUTED` only when every required event/slice has accepted coverage.

An unobserved planned event never advances state. Missing, additional, or materially divergent observation produces immutable deviation evidence, marks affected future realization/plan bindings stale, and requests governed future-only replan. It never rewrites the accepted Chapter or silently edits the realization.

## Fail-closed production chain

The following are production invariants:

- World activation requires current Qualified Creative Foundation, Theme Contract, Ending Intent, and Reader Promise bindings.
- Character activation requires those bindings plus a current Qualified WorldBible.
- BookDesign v5 activation requires the complete current Qualified Foundation Set.
- BookPlan generation requires active BookDesign v5 and the exact complete Foundation Set.
- ChapterPlan generation requires a current Qualified/Approved/Frozen Narrative Realization for the target ChapterGroup slice.
- Chapter dispatch recomputes Foundation, parent-plan, realization/proof, accepted-boundary, Working Set, and Mission bindings and rejects stale, mixed-lineage, or drifted input.

No HTTP request owns a provider chain. Formation/open/production endpoints admit Commands/Operations and expose query, approval, resume, abort, and recovery surfaces. Existing workers and shared execution infrastructure perform provider work.

## Recovery and replay

Technical retry reuses the same frozen inputs, Context, skill/capability versions, provider binding, and semantic generation. A semantic regeneration creates a new candidate or realization version. Each checkpoint can be reclaimed after lease expiry. Duplicate commands resolve idempotently. Crash after materialization but before result submission reconciles the existing ExternalEffect/receipt. Resume advances only from persisted Authority state.

## Compatibility

`book-design.v4`, old Book opening calls, and existing durable operation payloads remain readable/replayable during migration, but new production admission cannot create or activate v4 Foundation roots. No `PlanContractType` value is added. Existing StoryDesign and plan tables remain authoritative; new tables store process-manager lineage and Narrative Realization bindings/coverage only.

## Verification boundary

Unit, contract, API, PostgreSQL integration, fresh/upgrade migration, retry/recovery/replay/resume, concurrency, and a bounded one-to-three-Chapter vertical fixture are required. Full regression must pass. This work cannot establish long-form literary quality, real-reader alignment, million-word stability, multi-book behavior, or production proof.
