# Novel Forge / Autonomous Novel OS — Canonical Overall Design

> Status: Canonical architecture and product baseline
>
> Code reference snapshot: `main@7b9d96e6880e88b977ba31864c0f9c9ca00e59b7`
>
> This document distinguishes the current implemented runtime from the target narrative architecture. A target capability is not considered implemented or proven until it is wired into the canonical PostgreSQL production runtime and has matching evidence.

## 1. Executive Summary

Novel Forge is an **Autonomous Narrative Production Operating System** for sustained long-form fiction production. It is not a prompt-to-chapter generator. Its purpose is to maintain a coherent, evolving narrative system across hundreds of chapters while preserving engineering reliability, auditability, recovery, quality control, and reader feedback.

The target architecture converges on:

```text
Narrative DNA
+ Timeline Planning
+ Narrative Arc Graph
+ Temporal Narrative State
+ Knowledge / Disclosure
+ Reader Experience
+ Task-specific Context
+ Scene-oriented Chapter Production
+ Quality / Correction / Replan
+ Publish → Observe → Learn → Adapt
```

The most important invariant is:

> **The complete story authority may grow without bound, but each model invocation should receive only the minimum sufficient task-specific narrative view.**

This is the foundation for solving long-form asset growth, context explosion, narrative drift, character stagnation, story-line confusion, and provider cost/latency growth.

---

## 2. Goals and Non-Goals

### 2.1 Goals

1. Maintain canon, temporal state, character knowledge, relationships, world consequences, resources, obligations, mysteries, and long-horizon payoffs across 300+ chapters.
2. Keep per-task Provider context bounded as the full book grows.
3. Produce commercially readable fiction with structure, pacing, conflict, character, theme, suspense, reward, humor, emotion, and reader retention.
4. Support governed correction and future-only replanning without rewriting accepted history.
5. Preserve complete execution lineage for Provider effects, retry, recovery, replay, correction, cost, and quality decisions.
6. Support progressive proof: fixture → real Provider → 30 chapters → 100 chapters → 300 chapters → A/B → real reader → multi-book → production.

### 2.2 Non-Goals

The current target does **not** require:

- unrestricted autonomous agents;
- a separate workflow engine for every narrative concept;
- a microservice per Arc, Character Track, Disclosure type, or Quality dimension;
- one LLM call per deterministic fact check;
- full multi-model strategy before single-book proof;
- ten-book production admission before single-book correctness is proven.

---

## 3. Canonical Design Principles

### 3.1 Authority is not Context

PostgreSQL Authority stores durable truth and lineage. Context is a derived per-task projection and never becomes the source of truth.

### 3.2 Planning is not Canon

Planning describes future intent. Canon describes accepted truth. Future planning must never leak into current accepted state.

### 3.3 Canon is not Narrative State

Canon answers **what is true**. Narrative State answers **what is true at narrative position N**.

### 3.4 Memory is not State

Memory is retrievable history. State is the current temporal projection.

### 3.5 Volume is not Arc

A Volume is a timeline/production container. An Arc is a cross-cutting temporal trajectory of change. One Arc may cross several volumes; one chapter may advance several Arcs.

### 3.6 Truth, Knowledge, Belief, Reader Knowledge, and Presentation are distinct

The system must distinguish:

```text
Story Truth
Character Knowledge
Character Belief
Reader Knowledge
Narrative Presentation
```

### 3.7 Opposition is relational, not moral

Characters are modeled through goals, interests, beliefs, resources, constraints, fears, and moral boundaries. `Antagonistic Force` or `Conflict Actor` is preferred over assuming a permanent evil Villain role.

### 3.8 Asset growth must not imply prompt growth

The story database may become very large. Provider working context must remain bounded by task relevance.

### 3.9 Accepted lineage alone changes current narrative state

Rejected drafts, failed revisions, failed Provider calls, and abandoned candidates remain evidence only.

### 3.10 New abstractions require real value

Do not introduce a new Authority, workflow engine, compatibility layer, or framework unless a current production requirement cannot be represented safely by existing Authority / Command Kernel / Planning / Narrative State infrastructure.

---

## 4. Business Architecture

Novel Forge contains four core business loops.

### 4.1 Knowledge Loop

```text
Source
→ Import / Normalize
→ Deconstruction / Observation
→ MKAOS Candidate
→ Governance
→ Knowledge Asset / Pack
→ Runtime Consumption
→ Usage Evidence / Feedback
```

### 4.2 Narrative Design Loop

```text
Story Intelligence
→ Narrative DNA
→ World / Character Design
→ Book Architecture
→ Narrative Arc Graph
→ Volume Architecture
→ Coarse Chapter Function Map
→ Approved Baseline
```

### 4.3 Production Loop

```text
Current Accepted State
→ Chapter Intent
→ Arc Scheduling
→ Character Participation
→ Disclosure / Reader Experience
→ Scene Design
→ Task Context
→ Prose
→ Correctness / Review
→ Revision
→ Canon / State Delta
→ Quality
→ Acceptance
→ Reader Outcome
→ Recap / Replan
→ Next Chapter
```

### 4.4 Learning Loop

```text
Publish
→ Observe
→ Attribution
→ Learn
→ Adapt future Strategy / Planning / MKAOS / Quality / Reader Model
```

Historical accepted Canon is immutable under this loop.

---

## 5. Capability Architecture

### 5.1 Story Intelligence

- Topic / Premise Intelligence
- Reader Positioning
- Genre / Platform Positioning
- Commercial Pattern Analysis
- Premise Evaluation

### 5.2 Narrative Design

- Narrative DNA
- Book Architecture
- World Design
- Character Design
- Character Development Direction
- Narrative Thread / Arc Design
- Theme / Philosophy Design
- Major setup/payoff design

### 5.3 Timeline Planning

```text
Book
→ Volume
→ Narrative Segment
→ Chapter Group
→ Chapter
→ Scene
→ Beat
```

This axis answers **when** narrative work happens.

### 5.4 Narrative Graph

```text
Narrative Thread
→ Narrative Arc
→ Arc Segment
```

This axis answers **what is changing**.

### 5.5 Temporal Narrative State

Includes Canon facts and temporal projections for character, relationship, knowledge, belief, world, faction, location, resource, power, conflict, consequence, mystery, Arc state, obligations, and payoff.

### 5.6 Disclosure / Reader Knowledge

Controls when characters and readers obtain facts, partial facts, hints, misdirection, confirmation, and withheld information.

### 5.7 Reader Experience

Plans desired effects such as curiosity, suspense, tension, reward, humor, warmth, romance, fear, awe, sadness, anger, shock, relief, satisfaction, and catharsis.

### 5.8 Context Engine

Builds stage-specific minimum sufficient context from current task, narrative position, Arc schedule, state, Canon, knowledge boundaries, obligations, historical evidence, and relevant MKAOS knowledge.

### 5.9 Chapter Production

- Chapter Intent
- Arc Scheduling
- Character Participation
- Required State Transition design
- Disclosure design
- Scene architecture
- Beat planning
- Scene / Scene-group prose generation
- Chapter integration

### 5.10 Quality / Correction / Replan

- deterministic correctness checks;
- subjective Quality Judges;
- corrective revision;
- rereview and re-evaluation;
- scoped future-only Replan.

### 5.11 Execution / Governance Platform

Keep the existing semantics:

- **Skill** = reusable methodology;
- **Capability** = stable functional contract;
- **Capability Pack** = frozen runtime realization;
- **Agent** = governed reasoning executor, never a Domain Authority;
- **Operation** = durable execution authority.

---

## 6. System Architecture

Novel Forge should continue using one canonical production execution plane:

```text
Authority API / Workers / Schedulers
            ↓
       Command Kernel
            ↓
Operation → Attempt → Lease/Fence
            ↓
      ExternalEffect
            ↓
Production Execution Gateway
            ↓
Provider Runtime
            ↓
Candidate / Evidence
            ↓
Domain Authority Decision
            ↓
PostgreSQL Authority + Artifact Store
```

Narrative capabilities must plug into this plane instead of creating parallel runtimes.

---

## 7. Canonical Narrative Architecture

### 7.1 Narrative DNA

Narrative DNA defines why the work remains the same book across hundreds of chapters:

- premise;
- theme / philosophy;
- genre promise;
- reader promise;
- tone range;
- narrative voice;
- moral complexity;
- world logic;
- humor style;
- romance style;
- violence style;
- mystery fairness;
- reader reward pattern;
- ending intent.

All Volumes, Arcs, Chapters, and Scenes should remain compatible with this DNA.

### 7.2 World Architecture

Separate relatively stable rules from evolving state:

```text
World Rules
Institutions
Cultures
Power / Technology Systems
       ↓
World State
Faction State
Location State
Resource State
Consequence State
```

### 7.3 Character Architecture

A character consists of:

```text
Stable Identity
+ Current Temporal State
+ Development Trajectory
```

Stable Identity may include background, personality tendencies, core need, fear, initial trauma, value origin, talent, long-term desire, and moral boundaries.

Current State may include physical state, emotion, location, knowledge, belief, resources, power, social status, reputation, and relationships.

### 7.4 Character Development Trajectory

Long-running characters may have development tracks such as:

```text
BELIEF
VALUE
GOAL
IDENTITY
PERSONALITY_EXPRESSION
KNOWLEDGE
COMPETENCE
POWER
STATUS
RESOURCE
MORAL_BOUNDARY
EMOTIONAL
RESPONSIBILITY
REPUTATION
```

These are not separate runtime engines. They are a unified planning/view concept built on existing Character identity, Narrative Arc design, and accepted Narrative Events / State projections.

Personality growth should normally change expression and behavior rather than arbitrarily replacing stable traits. Power progression should affect access, responsibility, status, resources, factions, and relationships instead of acting as an isolated numeric level.

---

## 8. Timeline Planning

The canonical timeline hierarchy is:

```text
Book
→ Volume
→ Narrative Segment
→ Chapter Group
→ Chapter
→ Scene
→ Beat
```

### 8.1 Book

Defines premise, core conflicts, major transformations, ending intent, global stakes, reveal structure, theme, and reader promise.

### 8.2 Volume

A Volume is a temporal container with goal, pressure, conflict, reward, cost, climax, payoff, ending escalation, and intended state changes.

### 8.3 Narrative Segment

`Narrative Segment` replaces the old semantic assumption that a hierarchical `ArcPlan` is the same thing as a cross-book Narrative Arc.

A Segment represents a bounded stage of work inside a Volume, for example:

```text
Volume 2
├─ enter the condemned district
├─ locate the witness
├─ faction collision
└─ escape / volume payoff
```

### 8.4 Coarse planning vs JIT planning

Before production, freeze:

- Narrative DNA;
- World and core Character design;
- Book Architecture;
- Volume Architecture;
- Core Arc Graph;
- major turning points;
- long-horizon setup/payoff expectations;
- coarse chapter function map.

Do **not** freeze detailed Scene plans for all 300 chapters. Chapter Execution Plans and Scene plans should be generated Just-In-Time from current accepted state.

---

## 9. Narrative Arc Graph

### 9.1 Narrative Thread

A Thread is a persistent narrative concern: a mystery, relationship, goal, conflict, philosophical question, institutional struggle, or unresolved problem.

Suggested lifecycle:

```text
OPEN → ACTIVE ↔ DORMANT → RESOLVING → CLOSED
```

### 9.2 Narrative Arc

An Arc is the temporal state trajectory of a Thread:

```text
Initial State
→ Transitions
→ Terminal / Payoff State
```

Common Arc types:

```text
PLOT
CHARACTER
RELATIONSHIP
MYSTERY
CONFLICT
WORLD
FACTION
RESOURCE
POWER
THEME
ROMANCE
```

Do not create a separate engine per type.

### 9.3 Arc Function and Reader Effect

Arc type, narrative function, and reader effect are distinct.

Example:

```text
type: RELATIONSHIP
primary_function: CHARACTER_DEVELOPMENT
secondary_functions: [PLOT_ADVANCEMENT, THEME]
reader_effect: HUMOR → WARMTH → PAIN → CATHARSIS
```

### 9.4 Arc Span and Cadence

A long Arc needs both span and cadence. It may be active, dormant, echoed, reactivated, or paid off at selected positions rather than appearing in every chapter.

This supports long foreshadowing and `草蛇灰线` patterns without forcing full-Arc context into every chapter.

### 9.5 Arc Segment

A long Arc is divided into stages that are useful for local planning. Arc Segments may cross Volume boundaries.

### 9.6 Arc Graph relations

Useful relation types include:

```text
CAUSES
ENABLES
BLOCKS
DELAYS
ACCELERATES
REQUIRES
CONFLICTS_WITH
REVEALS
TRANSFORMS
PAYS_OFF
MIRRORS
CONTRASTS_WITH
SHARES_CHARACTER
SHARES_RESOURCE
```

The graph enables multi-line narrative convergence instead of maintaining independent story-line lists.

### 9.7 No duplicate Arc Event Authority

Do not create a second event system. Actual developments should continue through accepted Narrative Events and existing state kinds such as `ARC_STATE`, `CHARACTER_ARC`, `THEME_MOVEMENT`, `RELATIONSHIP_STATE`, and `NARRATIVE_OBLIGATION`.

Planning only needs Arc schedules / intended touchpoints; actual truth comes from accepted events.

---

## 10. Knowledge, Disclosure, and Presentation

### 10.1 Knowledge layers

Maintain separate semantics for:

```text
Story Truth
Character Knowledge
Character Belief
Reader Knowledge
```

### 10.2 Disclosure

Disclosure planning controls when a fact is hinted, partially revealed, misdirected, confirmed, or withheld for characters and readers.

Example:

```text
Reality: Ch1
Reader hint: Ch20
Reader suspicion: Ch40
Reader confirmation: Ch65
Hero learns: Ch80
```

Reader knowledge should be a derived projection of accepted presentation/disclosure events, not part of Canon truth.

### 10.3 Presentation

What happened and how the reader experiences it are separate concerns. Presentation channels may include direct experience, observation, dialogue, hearsay, rumor, documents, news, records, memories, flashbacks, object clues, environmental traces, body language, subtext, fragmented evidence, unreliable narration, negative space, or off-screen consequences.

---

## 11. Chapter Execution Architecture

A chapter is not one prompt. It is a bounded unit of narrative work.

### 11.1 Chapter Execution Plan

The Chapter Planner should produce an execution-oriented plan containing only what the runtime actually needs, for example:

- chapter function / intent;
- primary / secondary / touch / hold Arcs;
- setups and payoffs;
- required characters;
- goals and conflicts;
- character knowledge boundaries;
- required state transitions;
- required information gain;
- reader disclosure targets;
- reader emotion curve;
- scene architecture;
- hook;
- expected exit state.

Avoid a universal giant DTO.

### 11.2 Arc Scheduling

For the current chapter, classify relevant Arcs as:

```text
PRIMARY
SECONDARY
TOUCH
SETUP
PAYOFF
HOLD
```

This prevents every story line from being advanced every chapter.

### 11.3 Character Participation

Character participation should contain current goal, relevant state, knowledge, unknown facts, belief, emotion, resources, relationships, and expected change—not only character IDs.

### 11.4 Scene architecture

Scene / Scene Group is the preferred prose-generation granularity when it materially improves context locality and revision quality.

A Scene may contain:

- location;
- participants;
- goal;
- conflict;
- relevant Arc progress;
- information gain;
- state transition;
- entry state;
- exit state;
- reader effect.

### 11.5 Beat

Beat should normally remain a nested value object inside Scene planning, not a new Authority surface.

---

## 12. Context and Prompt Information Architecture

This is a critical production requirement.

### 12.1 Canonical flow

```text
PostgreSQL Authority
→ Task
→ Narrative Position
→ Arc Schedule
→ Relevant State
→ Relevant Canon
→ Relevant Knowledge
→ Due Obligations
→ Relevant Historical Evidence
→ Relevant MKAOS
→ Task-specific Projection
→ Provider Context View
→ Prompt
```

### 12.2 Minimum Sufficient Context

The objective is not the smallest context. It is the **minimum sufficient context** required to perform the task correctly.

Each stage should have explicit `MUST_INCLUDE`, `OPTIONAL`, and `MUST_EXCLUDE` semantics.

### 12.3 Stage-specific views

Typical intent:

**Draft / Scene generation**
- current Scene / Chapter Plan;
- relevant Arc Segment;
- current Character state and knowledge boundaries;
- relevant Canon and World rules;
- due obligations;
- relevant MKAOS craft knowledge.

**Review**
- produced prose;
- chapter/scene intent;
- relevant constraints;
- review methodology.

**Revision**
- prose;
- actionable review findings;
- only context required to repair those findings.

**Rereview**
- revised prose;
- previous findings;
- revision summary/diff;
- relevant constraints.

**Canon extraction**
- final candidate prose;
- relevant prior Canon/State;
- extraction schema.

### 12.4 Authority Evidence must not leak into Prompt by default

Persisted manifests, hashes, projections, audit metadata, and multiple internal DTO representations may all be valuable for replay and audit. They should not all be serialized into model input.

Large semantic bodies should have one authoritative rendered representation per task. IDs, hashes, and provenance references may be repeated as lightweight metadata.

### 12.5 Asset references over copying

Planning and execution assets should primarily reference `arc_refs`, `character_refs`, `state_refs`, `knowledge_refs`, `obligation_refs`, and `world_rule_refs` instead of repeatedly embedding full assets.

### 12.6 Authority → Projection → Provider View

```text
Canonical Asset
→ Temporal / Current Projection
→ Task-specific Projection
→ Provider View
```

The closer data is to the Provider, the smaller and more task-specific it should become.

---

## 13. MKAOS Architecture

MKAOS is a governed knowledge/methodology system, not a prompt warehouse.

```text
Task
→ Capability
→ Knowledge Requirement
→ MKAOS Retrieval
→ Relevant Knowledge
→ Provider
```

Book design may use narratology, philosophy, genre, reader psychology, and commercial structure. Character design may use psychology and character-arc methodology. Mystery design may use logic, evidence, misdirection, and fair-play reasoning. Scene writing should receive only the writing knowledge relevant to the current task.

MKAOS selection and actual Provider consumption must remain separately observable.

---

## 14. Correctness, Quality, Correction, and Replan

### 14.1 Correctness vs Quality

Use deterministic checks wherever correctness can be computed reliably:

- future-knowledge leakage;
- illegal resource use;
- impossible state transition;
- terminal obligation reopening;
- hard world-rule contradiction;
- identity/supersession errors.

Use LLM Judges for subjective or semantic quality such as prose, structure, depth, commercial appeal, platform fit, reader effect, and long-form craft.

### 14.2 Quality execution

Independent Quality Judges should support bounded safe concurrency while preserving independent Operation / Attempt / ExternalEffect / Trace / Evidence identity. Aggregation waits for required terminal outcomes.

### 14.3 Correction

```text
Quality Issue
→ Corrective Action
→ Targeted Revision
→ Rereview
→ Canon / State re-evaluation
→ Quality re-evaluation
→ Resolved / Escalated
```

During correctness proof, prefer full post-revision regression unless there is evidence that selective rerun is safe.

### 14.4 Replan

```text
Plan V1
→ Accepted production
→ Actual State / Drift / Reader / Quality Evidence
→ Replan Candidate
→ Evaluation / Approval
→ Plan V2
```

Replan changes future intent only. It never rewrites accepted chapters, Canon, or accepted Narrative Events.

Replan should support scoped change to Arc Segment, Volume, Narrative Segment, future chapter range, or payoff window rather than rebuilding the entire book by default.

---

## 15. Reliability, Recovery, Security, and Governance

Continue the existing canonical runtime semantics:

```text
Command
→ Operation
→ Attempt
→ Lease/Fence
→ ExternalEffect
→ Provider
→ Receipt
→ Domain Commit
```

Requirements:

- stable idempotency identity;
- bounded retry;
- no premature terminalization of retryable failures;
- no nested retry storms;
- restart-safe recovery;
- no duplicate Chapter / Canon / Resource / Obligation effects;
- stale fence rejection;
- append-only failure evidence;
- default-deny tool policy;
- Provider Gateway required;
- no direct DB/state mutation by Agents;
- Capability Pack / Skill / Prompt identities frozen per execution.

---

## 16. Observability and Operations

Narrative production observability should include:

- selected context tokens;
- final Provider input tokens;
- output / cached tokens;
- wall time;
- Provider calls;
- cost;
- revision count;
- quality rounds;
- context recall / precision when Ground Truth exists;
- long-distance retrieval recall;
- prompt amplification ratio;
- prompt growth slope by chapter.

A Provider invocation should be inspectable by information contribution, e.g. system instruction, Skill, Plan, State, Canon, prose, review, MKAOS, schema, and duplicate representations.

Operational invariant:

> **As chapter number grows, task context must remain bounded by relevance rather than historical accumulation.**

---

## 17. Testing and Qualification

Evidence maturity remains:

```text
MISSING
→ SKELETON
→ IMPLEMENTED
→ WIRED
→ FIXTURE_PROVEN
→ REAL_PROVIDER_PROVEN
→ LONGFORM_PROVEN
→ MULTIBOOK_PROVEN
→ PRODUCTION_PROVEN
```

Testing / proof ladder:

```text
Unit
→ Integration
→ PostgreSQL Integration
→ Fixture Runtime
→ Real Provider Composition
→ 30 Chapter Proof
→ 100 Chapter Proof
→ 300 Chapter Proof
→ MKAOS / Quality / Replan A-B
→ Real Reader Calibration
→ Multi-book
→ Production Admission
```

Passing local tests never establishes long-form or production proof.

### 17.1 Long-form proof goals

**30 chapters**: stateful continuation, Canon, knowledge boundary, obligations, recovery, bounded context.

**100 chapters**: Arc persistence, character development, relationship evolution, long-distance recall, context degradation, Replan.

**300 chapters**: very-long-horizon continuity, Character trajectory, Arc payoffs, World consequences, context scalability, Provider/runtime feasibility.

---

## 18. Current-to-Target Convergence

The current Planning runtime still models:

```text
BOOK → VOLUME → ARC → CHAPTER_GROUP → CHAPTER
```

The target meaning is:

```text
BOOK → VOLUME → NARRATIVE_SEGMENT → CHAPTER_GROUP → CHAPTER → SCENE → BEAT
```

while a separate cross-cutting Narrative Graph models:

```text
THREAD → ARC → ARC_SEGMENT
```

The preferred migration is semantic convergence over wholesale replacement:

1. keep Book Plan and Volume Plan;
2. reinterpret / migrate hierarchical `ArcPlan` toward `NarrativeSegmentPlan` where it is actually a volume-local phase;
3. extend existing Story Design Authority for cross-volume Narrative Thread / Arc design rather than introducing a second runtime;
4. evolve Chapter Plan into an execution-oriented plan that schedules Arcs, characters, disclosure, state transitions, reader effect, and Scenes;
5. reuse existing Narrative State kinds such as `PLOT_THREAD`, `ARC_STATE`, `CHARACTER_ARC`, `CHARACTER_BELIEF`, `RELATIONSHIP_STATE`, `RESOURCE_STATE`, `WORLD_STATE`, `NARRATIVE_OBLIGATION`, and `PAYOFF_EVENT` rather than adding another state engine;
6. derive Character Development views from existing character identity + Arc design + accepted events/state instead of creating duplicate Character trajectory truth.

---

## 19. Gap Analysis

### P0 — Must close

1. **Context / Prompt Information Architecture** — remove semantic duplication and separate audit evidence from Provider working context.
2. **Minimum Sufficient Context** — stage-specific context views with bounded information growth.
3. **Timeline vs Arc Graph separation** — stop treating cross-cutting Arcs as a simple hierarchy child of Volume.
4. **Chapter Execution Plan** — make chapter production explicitly schedule Arcs, characters, disclosure, state transitions, reader experience, and Scenes.
5. **Character Development Trajectory** — unify long-horizon development over current temporal state without duplicating state authority.
6. **Disclosure / Reader Knowledge** — establish reader information timing separately from truth and character knowledge.
7. **Scene-oriented production** — improve locality and correction granularity where real runtime evidence supports it.
8. **Real runtime requalification** — prove the converged architecture on the canonical Provider path.

### P1 — Should close

- bounded parallel Quality execution;
- deterministic correctness pre-checks;
- Provider semantic contract audit;
- prompt information attribution metrics;
- Arc Graph query/index support;
- scoped Replan;
- Story Intelligence → downstream lineage proof.

### P2 — Later enhancement

- advanced pacing intelligence;
- automatic Arc balancing;
- adaptive chapter length;
- richer Reader Experience prediction;
- scene-level controlled experiments;
- advanced commercial modeling.

### Future — Do not build yet

- ten-book production scale;
- multi-model strategy engine;
- large-scale automated publishing;
- online real-reader learning loops;
- production auto-admission.

---

## 20. Target Architecture

```text
                         SOURCE
                           │
                  Source Intelligence
                           │
                         MKAOS
                           │
                           ▼
                    NARRATIVE DNA
                           │
              ┌────────────┴────────────┐
              │                         │
            WORLD                   CHARACTER
              │                         │
              └────────────┬────────────┘
                           ▼
                    BOOK ARCHITECTURE
                           │
              ┌────────────┴─────────────┐
              │                          │
       TIMELINE PLANNING             ARC GRAPH
              │                          │
            Volume                    Thread
              │                          │
           Segment                       Arc
              │                          │
       Chapter Group                Arc Segment
              │                          │
           Chapter ◄─────────────────────┘
              │
              ├──── Character Development
              ├──── Narrative State
              ├──── Knowledge / Disclosure
              ├──── Reader Experience
              ├──── Obligations
              └──── MKAOS
              │
              ▼
       CHAPTER EXECUTION PLAN
              │
              ▼
            Scene
              │
             Beat
              │
              ▼
         CONTEXT ENGINE
              │
              ▼
   MINIMUM SUFFICIENT CONTEXT
              │
              ▼
          PROVIDER
              │
              ▼
        PROSE / REVIEW
              │
          REVISION
              │
              ▼
      CANON / STATE DELTA
              │
              ▼
          QUALITY
              │
              ▼
        ACCEPTED CHAPTER
              │
              ▼
      READER / RECAP / REPLAN
              │
              └──────────────► NEXT CHAPTER
```

---

## 21. Roadmap

```text
Phase A  Canonical Narrative Architecture Freeze
    ↓
Phase B  Context / Prompt Information Architecture Convergence
    ↓
Phase C  Timeline Planning ↔ Narrative Arc Graph Separation
    ↓
Phase D  Character Development + Disclosure
    ↓
Phase E  Chapter Execution Plan + Scene Runtime
    ↓
Phase F  Quality / Correction Runtime Optimization
    ↓
Phase G  Full Engineering Qualification
    ↓
Phase H  30 Chapter Proof
    ↓
Phase I  100 Chapter Proof
    ↓
Phase J  300 Chapter Proof
    ↓
Phase K  MKAOS / Quality / Replan A-B
    ↓
Phase L  Real Reader Calibration
    ↓
Phase M  Publish → Observe → Learn → Adapt
    ↓
Phase N  Multi-book / Production Admission
```

The first implementation priority is **Narrative Information Architecture + Context Information Architecture**, because the current long-form campaign has already shown that relevant narrative information can be much smaller than the final serialized Provider input. Long-form proof should continue only after the canonical runtime can keep Provider working context bounded and semantically task-specific.

---

## 22. Canonical Architecture Invariants

1. PostgreSQL Authority is the production source of truth.
2. Agents never own Domain Authority.
3. Planning is never Canon.
4. Context is never Authority.
5. Volume / Chapter / Scene are timeline containers.
6. Arc is a cross-cutting temporal trajectory.
7. Character development is time-dependent, not a static character card.
8. Reader knowledge and character knowledge are distinct.
9. Assets prefer references over repeated embedded bodies.
10. Provider input is a task-specific projection.
11. Narrative-history growth must not create unbounded prompt growth.
12. Current narrative state derives from accepted lineage only.
13. Replan changes future intent only.
14. Deterministic correctness and subjective quality are separate.
15. Deterministic problems use deterministic validators where practical.
16. MKAOS knowledge is retrieved by task; the knowledge base is not injected wholesale.
17. Failure evidence is append-only.
18. Fixture evidence never promotes Real Provider or Long-form proof.
19. Single-book proof never promotes Multi-book proof.
20. Every new abstraction must solve a demonstrated runtime or domain problem.
