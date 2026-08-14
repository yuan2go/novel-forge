# Canonical overall design

Novel Forge is a local-first, PostgreSQL-authoritative system for designing and
producing long-form fiction. The production invariant is simple:

> A downstream stage may produce an active artifact only from active, current,
> qualified upstream design. Prose production additionally requires a fresh,
> authoritative design-admission result.

This document is the canonical architectural map. Detailed runtime, Authority,
Narrative State, and production-execution documents refine it; they do not
define competing system shapes.

## One production plane

Novel Forge has one Command Kernel, one Production Execution Gateway, and named
Domain Authorities. A capability may generate or evaluate a candidate, but only
the owning Authority can validate, approve, activate, invalidate, or supersede
business state.

```text
Capability Pack + task-specific Context/MKAOS view
                         │
                         ▼
        Command Kernel / Attempt / Lease / Fence
                         │
                         ▼
          Production Execution Gateway / Provider
                         │
                         ▼
             typed candidate or evaluation
                         │
                         ▼
       owning Authority + PostgreSQL transaction/CAS
                         │
                         ▼
          active asset, projection, audit, outbox
```

The existing boundaries remain authoritative:

- Book Design Authority owns the whole-book Story Intent and Story Foundation
  root.
- Story Design Authority owns generated design-candidate qualification and its
  bounded repair lifecycle.
- Hierarchical Planning Authority owns active Book, Volume, Arc, ChapterGroup,
  and Chapter plan bindings.
- Plan Change Authority owns future-scoped replacement and requalification.
- Narrative State and Canon own accepted reality; plans cannot rewrite it.
- Chapter and Book Authorities own production and acceptance, using the shared
  execution plane rather than a parallel workflow engine.

## Progressive narrative design

The product progression and its current Authority/asset mapping are:

| Design layer | Canonical representation | Required downstream dependency |
|---|---|---|
| Story Intent | active BookDesign: premise, theme/philosophy, genre/reader promise, ending intent, core conflict | Story Foundation and Book Architecture |
| Story Foundation | active BookDesign: world rules, core characters, opposition forces, Narrative DNA | Book Architecture |
| Book Architecture | active `BOOK` planning contract | Volume, Arc, character, disclosure design |
| Volume Architecture | active `VOLUME` contract with Narrative Segments | Scheduling and ChapterGroup/Chapter plans in its range |
| Narrative Arc Graph | active cross-volume `ARC` contracts and typed relations | Scheduling and Chapter plans |
| Character Development | qualified trajectories embedded in Book/Arc contracts and projected state transitions | Scheduling and Chapter plans |
| Disclosure / Obligation | qualified truth, knowledge, belief, reader-disclosure, Promise, setup/payoff and obligation design in Book/Arc contracts | Scheduling and Chapter plans |
| Narrative Scheduling | active `CHAPTER_GROUP` contract and Chapter Function Matrix | Chapter plans |
| Chapter Execution Plan | active `CHAPTER` contract | Scene Architecture and production |
| Scene Architecture | governed `scene_plan` inside the Chapter contract | Prose production |

Volume is a timeline container. Containment is:

```text
Book → Volume → ChapterGroup → Chapter
```

Arc is an orthogonal narrative track:

```text
Thread → Arc → Arc Segment
Arc --CAUSES / ENABLES / BLOCKS / REVEALS / PAYS_OFF--> Arc
Arc --CONTRIBUTES_TO--> Volume / Chapter
```

An Arc may cross Volume boundaries. No second Arc State or Narrative Event
system is introduced; execution outcomes become accepted Narrative State events.

## Qualification lifecycle

Every generated design candidate follows the existing lifecycle:

```text
Candidate → Materialized → Structurally Valid → Semantically Valid
          → Qualified → Approved → Active
```

The two validation classes are intentionally separate.

Deterministic validation covers identity and lineage, parent/dependency
existence, ranges, Arc references and relations, setup/payoff ordering,
knowledge future leaks, impossible state transitions, duplicate identities,
constraint propagation, required fields, and activation freshness.

Narrative semantic evaluation uses layer-specific, versioned profiles rather
than a universal judge. Profiles evaluate only criteria meaningful to their
layer, including narrative capacity and ending reachability, conflict
sustainability, Volume differentiation, Arc causality/convergence/closure,
character-change causality, disclosure coherence, scheduling balance, Chapter
purpose, and scene-level exit-state reachability. Each evaluation records the
profile/version, criterion verdicts, evidence references, model/provider call
lineage when used, repair directives, and an aggregate verdict.

A failed deterministic or semantic result cannot be promoted. Recoverable
failures create a new candidate/version through bounded repair; exhaustion or a
non-recoverable violation rejects the candidate. Approval and activation use
compare-and-swap and never mutate an old result silently.

The canonical implementation is `NarrativeQualificationProfile v1` and
`NarrativeQualificationResult v1`. BookDesign v2 carries the Story Intent and
Story Foundation evaluations; Story Planning generator contracts v2 carry the
remaining layer evaluations. Passing results are persisted as immutable
`authority_narrative_design_qualification` receipts. BookDesign records its
receipts in the proposal transaction; Story Planning records a restart-safe
receipt before the corresponding semantic transition. Failed evaluations are
also retained as rejected/repair lineage and never satisfy admission. A receipt
is useful for admission only while its asset, profile hash, evaluation hash,
source Operation, and active binding remain current.

## Production admission

`LONGFORM_DESIGN_QUALIFIED` is a computed Authority result, not a new Authority.
It freezes the current active design roots, layer-qualification receipts,
planning bindings, dependency identities, and freshness at a Book cursor.

`CHAPTER_PRODUCTION_ADMITTED` requires:

- a current `LONGFORM_DESIGN_QUALIFIED` result;
- an active, current Narrative Scheduling contract for the Chapter range;
- an active, current Chapter Execution Plan and governed Scene Plan;
- the current accepted Narrative State/Canon cursor used by those plans;
- exact agreement between the scheduled Chapter function, Arc cadence,
  obligation actions, Reader Experience target, and the Chapter plan;
- no stale dependency or deterministic future-leak failure.

Book input resolution records the aggregate qualification. Chapter dispatch
rechecks it against the current active bindings and accepted cursor. A stale or
missing result fails closed before provider execution.

Arc generation may freeze cross-Volume scope and a related-Arc portfolio.
Scheduling classifies every frozen active Arc exactly once, while Chapter
planning receives only the non-dormant Arcs scheduled for that Chapter (bounded
to three). Provider schemas and Authority checks reject references outside the
frozen task-specific portfolio.

Migration 0089 stores the receipts, aggregate Book-input result, and current
qualification/admission projections. Migration 0090 adds the required scope
indexes and future `NARRATIVE_SEGMENT` / `ARC_SEGMENT` Replan scopes. These are
forward migrations; historical migrations remain immutable.

## Replan and invalidation

Accepted reality is immutable. Drift, reader evidence, review findings, or
quality evidence may propose a future-scoped PlanChange for a Volume, Narrative
Segment, Arc Segment, ChapterGroup, or Chapter range. Activation creates new
versions, retains lineage, regenerates and requalifies only the affected future
closure (`Book → Volume/Arc/Scheduling/Chapter`, `Volume or Narrative Segment →
Arc/Scheduling/Chapter`, `Arc or Arc Segment → Scheduling/Chapter`, or the
smaller corresponding closure), and activates it with CAS. Accepted chapters,
Canon, StoryState events, and past plan bindings are not rewritten.

## Context and knowledge boundary

All design generation and evaluation use:

```text
Authority → versioned projection → task-specific view → provider view
Task → knowledge requirement → MKAOS retrieval → selected knowledge references
```

Provider prompts do not receive complete Authority assets by default. Context
manifests record the exact selected projections and knowledge references; raw
source material remains isolated from draft prose.

## Scene execution boundary

Scene Plan is a formal, qualified design layer but remains embedded in the
Chapter contract. A separate Scene saga is justified only when independent
leasing, context, partial revision, or recovery becomes an observed need. The
current prose runtime continues to generate a governed whole-chapter candidate.

## Evidence boundary

Implementation, local fixture tests, and PostgreSQL integration establish
bounded runtime wiring. They do not establish real-provider quality, 30/100/300
chapter continuity, multi-book behavior, production authorization, or external
publishing.
