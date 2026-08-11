# Novel production flow

The main governed flow is Book → Planning → Chapter → Reader/Recap → Replan. Each arrow crosses a versioned contract; coordinators do not copy child execution state.

## 1. Book and design authority

An operator creates a Book and proposes/decides/activates BookDesign assets. Starting Book production resolves active authority inputs into one frozen input snapshot. Production does not accept an implicit local fixture mode; tests that use synthetic resolved data must opt into the fixture boundary explicitly.

## 2. Hierarchical planning

The Book supervisor asks Planning to generate a missing ChapterGroup or Chapter plan. Generated content is a candidate. Planning and PlanChange Authority own activation and execution scope. A plan must be frozen before ChapterGroup or Chapter execution begins.

## 3. Chapter production

ChapterGroup coordinates chapter requests. `chapter.slice.run` executes the Chapter Authority's 18-node saga through governed Attempts and ExternalEffects. The sequence includes context, planning/draft/review/revision, Canon, quality, release, and acceptance evidence. A successful provider response alone cannot complete a chapter.

## 4. Acceptance and narrative state

Chapter acceptance commits the accepted revision, Canon decision, release/quality evidence, and `ChapterOutcome`. Deterministic reducers advance StoryState. The Book Authority accepts the chapter through CAS-guarded state and records checkpoint/outbox evidence.

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
accepted revision + Canon + ChapterOutcome + StoryState
      ↓
Reader Outcome → Recap / ending evidence
      ↓ if governed request exists
PlanChange decision → future-plan activation → resume
```

## Stop and recovery behavior

Book and Chapter work can pause, fail, retry, reconcile, or wait for approval without erasing the previous Attempt. Stable idempotency, leases, fences, checkpoints, and outbox records allow another process to resume from PostgreSQL authority.

## What this flow does not prove

Fixture and PostgreSQL integration tests demonstrate bounded vertical slices. They do not prove a complete long novel, unattended multi-book operation, real-provider quality, or external publishing.
