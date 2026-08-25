# ADR 0007: Foundation hierarchy and Narrative Realization Authority

- Status: Accepted
- Date: 2026-08-25
- Supersedes: ADR 0003 sections 1–2 where BookDesign was the monolithic Foundation root

## Context

`book-design.v4` embeds Creative, World and Character design, then projects
component assets after activation. This makes downstream lifecycle evidence
look complete while Creative → World → Character coherence is not an
unavoidable Authority chain. Separately, Book Supervisor currently moves from
ChapterGroup directly to ChapterPlan. The existing plan contracts describe
intent and Chapter events but do not prove the causal event chain that makes a
multi-Arc group legally realizable from current accepted state.

Adding another Story/Planning Authority, treating realization as another
narrative scale, or accepting planned events into state would create incorrect
parallel truth.

## Decision

1. Creative Foundation, Theme Contract, Ending Intent, Reader Promise,
   WorldBible and CharacterCast are exact independently qualified Foundation
   contracts. Each owns only its layer's stable design truth.
2. BookDesign v5 is a synthesis/reference contract. It binds exact upstream
   AssetVersions/content hashes and Book-level invariants, and cannot copy
   World/Character truth. Derived convenience snapshots disclose all source
   bindings and never become Authority.
3. Story Formation is a Command Kernel/Operation-backed, checkpointed process
   manager. It delegates activation to existing Authorities and owns no Story
   Truth. Formation/opening APIs admit and control durable work only.
4. Hierarchical Planning Authority owns an independent typed
   `NarrativeRealizationContract` between ChapterGroup/Arc intent and
   ChapterPlan. It reuses current artifact/lifecycle/evidence infrastructure but
   is not a `PlanContractType`, narrative scale, or new Authority.
5. The lifecycle terms are Qualified, Approved and Frozen. Only accepted
   Chapter outcomes become Actual.
6. ChapterPlan binds an exact realization slice. At Chapter acceptance the Plan
   becomes `EXECUTED` and accepted observations consume matching planned event
   coverage atomically. A group-level realization becomes `EXECUTED` only when
   every required event/slice has accepted coverage; deviations create evidence
   and future-only replan/staleness.
7. Missing, stale, mixed-lineage or digest-drifted Foundation, parent plan,
   realization proof, Working Set or accepted boundary fails closed at
   generation and production admission.

## Consequences

- No `NARRATIVE_REALIZATION` value is added to `PlanContractType`.
- No `AcceptedNarrativeRealization` artifact exists.
- Scene/Beat remain typed ChapterPlan children.
- Existing v4 and durable operation data remain query/replay compatible, but
  new production opening requires the v5 hierarchy.
- Platform/production profiles remain production constraints, not Story Truth.
- Unit/integration/runtime evidence does not imply long-form literary or
  production proof.
