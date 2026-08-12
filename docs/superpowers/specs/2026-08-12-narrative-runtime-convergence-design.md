# Narrative Runtime Convergence Design

Date: 2026-08-12
Start SHA: `42944de24bc083ca1e6dd12c68cbfa0f96602807`
Target branch: `main`

## Decision

Extend the accepted `ChapterOutcome -> StoryStateSnapshot -> Book chapter acceptance`
chain instead of introducing another Narrative Authority. Canon remains approved truth,
ChapterOutcome remains accepted actual evidence, StoryState remains a rebuildable current
projection, Temporal Query remains read-only, and Context remains an immutable task input.

The existing Narrative State v2 envelope is retained for immutable evidence compatibility,
but new events use event-contract version 2 and add the missing temporal position, entity
version, explicit knowledge/belief state, world consequences, and unified obligation
semantics. Promise, foreshadowing, mystery, conflict, open loop, and payoff are normalized
into `narrative_obligation` in the production Canon-to-Outcome path. Their older state kinds
remain readable only for immutable evidence replay.

## Runtime model

1. A Canon patch emits typed Narrative State events with Project/Book scope, Book/Volume/
   Arc/Chapter/Sequence position, an effective chapter range, source evidence, Canon status,
   entity version, and reducer semantics.
2. Character knowledge and belief are separate entity facts. Retrieval of a fact does not
   make a character know it; only an accepted knowledge event can do that.
3. Character, relationship, character arc, world, faction, location, rule, consequence, and
   conflict events reduce through the same deterministic StoryState reducer.
4. Narrative obligations have one lifecycle: `PROPOSED -> OPEN -> DEVELOPING -> DUE ->
   FULFILLED`, with `CANCELLED` as a governed terminal alternative. A fulfilled obligation
   requires payoff evidence and terminal obligations cannot silently reopen.
5. Context Builder emits a reproducible Narrative Context Manifest containing exact task,
   capability, narrative position, accepted state boundary, selected/rejected inputs,
   inclusion reasons, knowledge lineage, budget, algorithm version, and digests.
6. PostgreSQL read projections connect Context selections to the consuming Operation,
   Capability, MKAOS KnowledgePack/KnowledgeCard versions, and produced results. These views
   are evidence surfaces, not write authorities.
7. Quality and Reader observations normalize into typed issues and required actions. Local
   defects stay bounded to revision; chapter/arc/volume/book changes require the existing
   PlanChange and Book Replan approval/activation path and preserve executed plans.

## Planning and action governance

Planning candidates carry a deterministic constraint envelope derived from their frozen
parent inputs. The envelope records inherited invariants, forbidden outcomes, required
obligations, accepted-state boundary, parent version hashes, and the permitted repair scope.
Chapter execution freezes that envelope in the ChapterPlan and Context Manifest. A local
quality issue cannot request arc-or-higher replan without evidence that explicitly crosses
the configured scope threshold.

## Capability, Skill, Pack, Source, and MKAOS boundary

- Skill is methodology content and never runtime authority.
- Capability is the stable operation contract used by workflow nodes.
- Capability Pack is the immutable realization binding workflow, capability, skills,
  prompts, context/provider policies, and gates.
- Source classification and methodology hashes remain independent from source identity;
  changing either creates new analysis work even when source bytes are unchanged.
- MKAOS usage means an eligible KnowledgePack/Card version was selected into a frozen
  Context Manifest and that Context was consumed by a named Operation. Selection is usage
  evidence, not proof that the model followed the knowledge.

## Failure and proof boundaries

All scope, temporal, lifecycle, transition, payoff-evidence, state-boundary, and manifest
integrity errors fail closed before Provider dispatch or Authority acceptance. Instrumentation
records measurable future leakage, contradictions, obligation violations, context precision,
planning drift, action effects, MKAOS consumption, Provider usage/cost, and trace lineage.
Passing deterministic and PostgreSQL tests establishes engineering closure only. It does not
establish long-form, multi-book, reader-effectiveness, or production proof.
