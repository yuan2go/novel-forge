# Novel production flow

The governed flow designs and qualifies the novel before prose production:

```text
Story Intent → Story Foundation → Book Architecture → Volume Architecture
→ Narrative Arc Graph → Character / Disclosure / Obligation Design
→ Narrative Scheduling → Chapter Execution Plan → Scene Architecture
→ Prose Production → Acceptance → Reader/Recap → scoped Replan
```

Each arrow crosses an active, current, versioned contract. Coordinators do not
copy child execution state.

## 1. Book and design authority

An operator creates a Book and proposes/decides/activates BookDesign assets.
BookDesign is the qualified Story Intent and Story Foundation root. Starting
Book production resolves active Authority inputs and layer qualification into a
frozen input snapshot. Production does not accept an implicit local fixture
mode; tests that use synthetic resolved data must opt into that boundary.

## 2. Hierarchical planning

Story Design generation produces Book, Volume, cross-volume Arc, ChapterGroup,
and Chapter candidates. Each candidate receives deterministic validation and a
layer-specific Narrative Semantic Evaluation before qualification. Planning and
PlanChange Authority own active bindings and execution scope. ChapterGroup is
the Narrative Scheduling layer; Chapter contains the canonical Chapter
Execution Plan and formal Scene Plan.

Book production records `LONGFORM_DESIGN_QUALIFIED` only when every required
active design layer is current and qualified. Chapter dispatch separately
records or verifies `CHAPTER_PRODUCTION_ADMITTED` and fails closed on a stale
dependency or Narrative State cursor.

## 3. Chapter production

ChapterGroup coordinates admitted chapter requests. `chapter.slice.run`
executes the Chapter Authority's 18-node saga through governed Attempts and
ExternalEffects. The sequence includes task-specific context,
draft/review/revision, Canon, quality, release, and acceptance evidence. A
successful provider response alone cannot complete a chapter.

## 4. Acceptance and narrative state

Chapter execution produces a governed Canon patch and a `ChapterOutcome` v2
candidate containing immutable Narrative State events. A child success is not
acceptance. Book Authority atomically commits the ChapterOutcome, materialized
StoryState v2, Canon v2 snapshot and cursor through a CAS-guarded acceptance
record. Only that committed pointer set is visible to Temporal Query or the next
chapter.

StoryState materializes one current value per entity-aware key. Timeline/reward
events remain ledgers, while character, relationship, world-rule, power,
resource, Promise, foreshadow and plot-thread state use their own reducer
semantics. The current projection is rebuildable from accepted ChapterOutcome
evidence and never replaces Canon Authority.

## 5. Reader and recap follow-up

The governed Book scheduler submits Reader Outcome work after accepted chapters. At configured boundaries it also submits recap and ending-reachability work. These operations produce evidence and proposals; they do not mutate Canon or plans.

## 6. Replan

When an accepted recap emits a replan request, the Book supervisor resolves that evidence and starts a governed Book replan. Approval may be required according to risk. PlanChange Authority activates accepted semantic changes, impacted future inputs are rebound, and superseded ChapterGroup work is closed or replaced explicitly.

```text
BookDesign active
      ↓
Book production input snapshot
      ↓
ChapterGroupPlan → freeze
      ↓
ChapterPlan → freeze
      ↓
Chapter 18-node saga
      ↓
committed ChapterOutcome events + Canon v2 + StoryState v2
      ↓
Reader Outcome → Recap / ending evidence
      ↓ if governed request exists
PlanChange decision → affected future requalification/activation → resume
```

## Stop and recovery behavior

Book and Chapter work can pause, fail, retry, reconcile, or wait for approval
without erasing the previous Attempt. Stable idempotency, leases, fences,
checkpoints, activation CAS, immutable qualification receipts, and outbox
records allow another process to resume from PostgreSQL authority.

## What this flow does not prove

Fixture and PostgreSQL integration tests demonstrate bounded vertical slices. They do not prove a complete long novel, unattended multi-book operation, real-provider quality, or external publishing.
