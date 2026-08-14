# Novel Forge / Autonomous Novel OS — Canonical Overall Design

> Status: Canonical architecture baseline
>
> Purpose: the single design baseline for architecture, implementation, code review, qualification, long-form proof, and production admission. Detailed runtime or Authority documents may refine this design, but must not define a competing system shape.

## 1. Executive summary

Novel Forge is not a prompt chain that expands `outline → chapter → prose`. It is a PostgreSQL-authoritative, governed Narrative Production Operating System for designing, producing, validating, recovering, and continuously evolving long-form web fiction.

The core problem is not merely whether a model can remember hundreds of chapters. The system must keep the following coherent over hundreds or thousands of chapters while keeping per-call provider context bounded:

- story direction and ending reachability;
- world rules, world state, and progressive world discovery;
- character identity, state, development, and expanding scope/reach;
- narrative threads and cross-cutting arcs;
- story time, causality, and accepted narrative events;
- Story Truth, Character Knowledge, Belief, Reader Knowledge, and Presentation;
- promises, foreshadowing, mysteries, obligations, and payoff debt;
- reader experience, serialization rhythm, and long-term quality;
- planning, qualification, activation, replan, recovery, and audit lineage.

The canonical model is therefore:

```text
                         NOVEL DNA
                            │
                            ▼
                      BOOK DESIGN
                            │
                            ▼
                    VOLUME PORTFOLIO
                            │
             ┌──────────────┼────────────────┐
             │              │                │
             ▼              ▼                ▼
      NARRATIVE SEGMENTS  ARC GRAPH   WORLD / CHARACTER
             │              │         REALIZATION
             │              │                │
             └──────────────┼────────────────┘
                            │
                   NARRATIVE STATE
                            │
                  KNOWLEDGE / DISCLOSURE
                            │
                 NARRATIVE OBLIGATIONS
                            │
                   READER EXPERIENCE
                            │
                            ▼
                  NARRATIVE SCHEDULING
                            │
                            ▼
                 CHAPTER EXECUTION PLAN
                            │
                            ▼
                    SCENE ARCHITECTURE
                            │
                POV / STORY TIME / LOCATION
                            │
                            ▼
                     CONTEXT COMPILER
                            │
                            ▼
                         PROVIDER
                            │
                            ▼
                          PROSE
                            │
                            ▼
                 NARRATIVE EVENT EXTRACTION
                            │
                            ▼
                     CORRECTNESS GATE
                            │
                            ▼
                CANON / STATE PROJECTION
                            │
                            ▼
                       QUALITY GATE
                            │
                            ▼
                    ACCEPTED CHAPTER
                            │
            ┌───────────────┴────────────────┐
            ▼                                ▼
       NEXT CHAPTER                        PUBLISH
                                             │
                                           OBSERVE
                                             │
                                      RECAP / DRIFT
                                             │
                                           REPLAN
```

The architecture is built around six Narrative Axes, five industrial control systems, and three foundation protocols.

### Six Narrative Axes

1. Temporal Hierarchy
2. Narrative Arc Graph
3. Narrative State
4. Knowledge / Disclosure
5. Reader Experience
6. Realization / Visibility

### Five Industrial Control Systems

A. Progressive Planning
B. Narrative Scheduling
C. Context Compiler
D. Qualification / Governance
E. Runtime / Feedback / Recovery

### Three Foundation Protocols

I. Event → State Commit Protocol
II. Planning Dependency / Replan Protocol
III. Context Contract

---

## 2. Goals

Novel Forge must support:

- long-form narrative correctness from Chapter 1 through 30, 100, 300, and eventually much longer serials;
- coherent character development with causal state changes rather than static character cards;
- progressive expansion of world scope without repeatedly replacing the story with unrelated new maps and casts;
- cross-volume plot, character, relationship, mystery, faction, world, resource, power, and theme arcs;
- correct temporal, spatial, knowledge, resource, and obligation continuity;
- progressive design qualification before prose production;
- bounded provider working context even while Narrative Authority grows indefinitely;
- deterministic correctness where possible, semantic judgement where necessary;
- idempotent, restart-safe, retry-safe, replayable production;
- auditable versioning, approval, activation, supersession, and future-scoped replan;
- reader feedback and long-term quality signals without allowing external outcomes to rewrite accepted history;
- eventual multi-book and portfolio production only after single-book correctness is proven.

---

## 3. Non-goals

The target architecture does not require one service, Authority, Agent, or workflow for every literary concept.

Do not create by default:

- ThemeAuthority;
- PhilosophyAuthority;
- ComedyAuthority;
- ReaderEmotionAuthority;
- BeatAuthority;
- WorldRealizationService;
- CharacterTrajectoryService;
- NarrativeDebtService;
- POVAuthority;
- Arc-type-specific engines;
- a second workflow engine;
- a second state plane;
- a separate Scene saga before runtime evidence justifies it.

A concept should remain a value object, policy, projection, contract, or validator unless it develops an independent lifecycle, concurrency model, authority boundary, recovery semantics, or operational scale that justifies a separate runtime component.

---

## 4. Core invariants

1. PostgreSQL Authority is the production Source of Truth.
2. Agent output is a proposal; Agents never own Domain Authority.
3. Planning is future intent, never accepted truth.
4. Planned transitions are not Accepted Narrative Events.
5. Context is a derived execution view, never Authority.
6. Only accepted chapter lineage can advance Canon or Narrative State.
7. Volume, Narrative Segment, Chapter, and Scene are temporal containers.
8. Arc is a cross-time state-changing trajectory, not a Volume child.
9. Narrative Thread is optional persistent concern, not a mandatory Arc parent.
10. Character is stable identity + temporal state + development trajectory.
11. World Invariants, World Structure, World State, World Realization, and World Visibility are distinct.
12. Story Truth, Character Knowledge, Character Belief, Reader Knowledge, and Presentation are distinct.
13. Important state changes must be traceable to Accepted Narrative Events.
14. Current Narrative State is a projection, not a second history source.
15. Future design is progressively elaborated instead of fully detailing hundreds of chapters up front.
16. World and character assets are progressively realized according to narrative horizon.
17. Authority growth must not cause unbounded prompt growth.
18. Provider inputs are task-specific Minimum Sufficient Context.
19. Narrative load must be governed before Context construction.
20. Narrative obligations and debt must be observable.
21. Replan may alter future design only; accepted history is immutable.
22. Replan should invalidate and requalify the smallest dependency closure that is actually affected.
23. Deterministic correctness must be deterministic whenever possible.
24. Narrative Semantic Evaluation requires trustworthy, immutable evidence lineage.
25. Fixture proof must never be upgraded to Real Provider or Production proof.
26. One-book proof must never be upgraded to Multi-book proof.
27. New abstractions must solve observed problems rather than speculative future ones.

---

## 5. Business architecture

### 5.1 Knowledge loop

```text
Source
→ Import
→ Normalize / Chunk
→ Deconstruction
→ Observation
→ MKAOS Candidate
→ Governance
→ Knowledge Asset
→ Usage
→ Feedback
```

MKAOS owns reusable creative methods and professional knowledge. It does not own story facts.

### 5.2 Narrative design loop

```text
Story Intent
→ Story Foundation
→ Book Architecture
→ Volume Portfolio
→ Narrative Arc Graph
→ Character Development
→ World / Character Realization
→ Disclosure / Obligation Design
→ Narrative Scheduling
→ Progressive Qualification
→ LONGFORM_DESIGN_QUALIFIED
```

An upstream design layer that has not reached a current, qualified, approved/active state may not silently become a production dependency.

### 5.3 Narrative execution loop

```text
Current Accepted Narrative State
→ Tactical / Operational Plan
→ Chapter Execution Plan
→ Scene Architecture
→ Context Compiler
→ Provider
→ Prose
→ Correctness
→ Review / Revision
→ Narrative Event Extraction
→ Canon / State Projection
→ Quality
→ Accepted Chapter
```

### 5.4 Publish / learn loop

```text
Accepted Chapter
→ Publish
→ Observe
→ Reader Outcome
→ Attribution
→ Recap / Drift
→ Governed Replan
→ Future Design
```

External reader outcomes may influence future planning, Reader Model, Quality policy, MKAOS, or replan. They never mutate accepted Canon directly.

---

## 6. Capability architecture

```text
Novel Forge
│
├ Story Intelligence
│  ├ Topic / Premise
│  ├ Reader Positioning
│  ├ Genre Intelligence
│  └ Commercial Pattern Analysis
│
├ Narrative Design
│  ├ Novel DNA
│  ├ Book Architecture
│  ├ Volume Architecture
│  ├ Narrative Segments
│  ├ Arc Graph
│  ├ Character Development
│  ├ World Design / Realization
│  ├ Disclosure / Obligation
│  └ Narrative Scheduling
│
├ Narrative Execution
│  ├ Chapter Design
│  ├ Scene Design
│  ├ Context Compiler
│  ├ Prose
│  └ Revision
│
├ Narrative Correctness
│  ├ Canon
│  ├ Narrative State
│  ├ Narrative Event Extraction
│  ├ Knowledge
│  ├ Temporal / Spatial
│  └ Obligation Consistency
│
├ Knowledge
│  ├ Source Intelligence
│  ├ MKAOS
│  └ Retrieval
│
├ Quality
│  ├ Narrative Quality
│  ├ Longitudinal Quality
│  ├ Corrective Action
│  └ Reader Evaluation
│
├ Governance
│  ├ Qualification
│  ├ Approval
│  ├ Activation
│  ├ Replan
│  └ Production Admission
│
└ Platform
   ├ Command Kernel
   ├ Provider Runtime
   ├ Agent Runtime
   ├ PostgreSQL Authority
   ├ Trace / Cost
   ├ Recovery
   └ Operations
```

---

## 7. Axis 1 — Temporal Hierarchy

The canonical hierarchy is:

```text
Book
→ Volume
→ Narrative Segment
→ Chapter
→ Scene
→ Beat
```

No additional primary hierarchy level should be introduced without strong evidence.

### 7.1 Book

Owns the whole-book macro trajectory: initial state, ending state, major conflict development, major character transformation, world expansion, major mystery, major relationships, major obligations, reader promise, and length strategy.

### 7.2 Volume

A Volume is a timeline container with a distinct narrative function, not a file-size partition.

A Volume should define at least:

- Narrative Function;
- Entry State;
- Exit State;
- Central Pressure;
- Major Conflict;
- Major Arc Movements;
- Character Transformation;
- World Realization/Expansion target;
- Reader Experience Curve;
- Midpoint;
- Climax;
- Irreversible Change;
- Cost;
- Major Payoffs;
- Next-volume Bridge.

### 7.3 Narrative Segment

A Narrative Segment is the canonical medium-scale story unit between Volume and Chapter. It answers: why do these chapters exist together?

Typical examples include entering a new city, establishing a faction relationship, investigating one sub-problem, preparing a major reveal, or completing one local transformation stage.

### 7.4 Chapter

A Chapter is a publishable, accept/reject business unit. It is not merely a free-form piece of prose.

### 7.5 Scene

Scene is the principal local dramatic unit and should carry goal, opposition, information gain, state movement, reader effect, time, location, and POV.

Scene may become a prose generation granularity later, but a separate Scene execution plane is not required until evidence justifies it.

### 7.6 Beat

Beat remains an embedded Scene planning value. It is not a separate Authority.

### 7.7 Narrative Segment vs Chapter Group

These must remain conceptually separate:

```text
Narrative Segment = story-design unit
Chapter Group      = production/runtime batching and checkpointing unit
```

They may map 1:1 in a specific implementation, but must not share one semantic responsibility.

---

## 8. Axis 2 — Narrative Arc Graph

Arc is orthogonal to temporal containment.

```text
Narrative Thread   optional persistent concern/question
Narrative Arc      state-changing trajectory
Arc Segment        local phase of a long Arc
Arc Relation       causal/dependency relation between Arcs
```

### 8.1 Arc definition

```text
Arc = Narrative Concern
      from Initial State
      through meaningful transitions
      to a Terminal / Payoff State
```

A single joke, face-slap, clue, scene, or reward is not automatically an Arc.

### 8.2 Arc types

A shared Arc protocol may use types such as:

- PLOT
- CHARACTER
- RELATIONSHIP
- MYSTERY
- CONFLICT
- WORLD
- FACTION
- RESOURCE
- POWER
- THEME
- ROMANCE

These types must not become independent engines by default.

### 8.3 Arc relations

Support typed relations such as:

- CAUSES
- ENABLES
- BLOCKS
- DELAYS
- ACCELERATES
- REQUIRES
- REVEALS
- PAYS_OFF
- TRANSFORMS
- MIRRORS
- CONTRASTS_WITH

### 8.4 Span and cadence

Every long-running Arc requires both span and cadence. A start/end chapter alone is insufficient.

Example:

```text
Ch5    SETUP
Ch22   ECHO
Ch52   REINFORCE
Ch73   ACTIVATE
Ch90   REVERSE
Ch118  PAYOFF
Ch120  AFTERMATH
```

Dormancy is valid; accidental disappearance is not.

### 8.5 Narrative convergence

Scheduling should support explicit convergence points where multiple independent Arcs collide to create a major turn or climax. Convergence is a planning property, not a new Authority.

---

## 9. Character architecture

A character is:

```text
Stable Identity
+
Current Temporal State
+
Development Trajectory
```

### 9.1 Stable identity

Includes relatively stable facts such as background, deep fear, need, value origin, enduring tendencies, history, long-term desire, talent, and moral boundaries.

### 9.2 Current state

May include:

- physical state;
- emotion;
- location;
- current goal;
- knowledge;
- belief;
- resource;
- power;
- status;
- reputation;
- relationships.

### 9.3 Development trajectory

Character development may track:

- BELIEF
- GOAL
- IDENTITY
- PERSONALITY_EXPRESSION
- KNOWLEDGE
- COMPETENCE
- POWER
- STATUS
- RESOURCE
- RELATIONSHIP
- MORAL_BOUNDARY
- EMOTIONAL
- RESPONSIBILITY
- REPUTATION

Do not build separate Authorities for each dimension. Development should be represented through planned Arcs plus accepted Narrative State projections.

### 9.4 Scope / reach

Web-novel growth is not only numeric power progression. Character reach may expand through:

- Geographic Reach;
- Social Reach;
- Political Reach;
- Economic Reach;
- Information Reach;
- Network Reach;
- Responsibility Reach.

Power progression should produce consequences in access, resources, risk, status, faction attention, responsibility, and worldview.

### 9.5 Opposition model

`Villain` is not a required domain primitive. Opposition may come from:

- Character;
- Faction;
- Institution;
- Law;
- Class;
- Scarcity;
- Technology;
- Nature;
- History;
- Time;
- Protagonist Self.

Conflict emerges from incompatible goals, interests, beliefs, resources, and constraints.

---

## 10. World architecture and progressive realization

World must not be modeled as one mutable encyclopedia.

The canonical structure is:

```text
World
├ World Invariants
├ Structural World Model
├ Temporal World State
├ World Knowledge
├ World Visibility
├ Discovery Frontier
├ Realization Level
└ World Arc
```

### 10.1 World Invariants

Stable rules such as power systems, physical limits, technology boundaries, death rules, resource rules, or core institutional constraints.

### 10.2 Structural World Model

Regions, factions, institutions, locations, political structures, economies, and other persistent world topology.

### 10.3 Temporal World State

What the world is currently like: war, occupation, regime change, resource depletion, technological breakthrough, destroyed/rebuilt locations, faction shifts, etc.

### 10.4 Realization vs visibility

These are distinct:

```text
Design Realization = how precisely the system has designed an entity
Visibility         = what a character/reader can currently perceive or know
Accessibility      = what a character can actually reach/use/influence
```

### 10.5 Progressive realization levels

Use a small, stable vocabulary, for example:

```text
ANCHOR
DEFINED
DETAILED
ACTIVE
```

Meaning:

- ANCHOR: existence, future function, and hard boundary only;
- DEFINED: key rules and relationships fixed;
- DETAILED: sufficient to support upcoming tactical planning;
- ACTIVE: current prose directly uses the entity.

Do not fully detail the entire world before Chapter 1.

### 10.6 Progressive world discovery

The world should expand through narrative causality rather than abrupt authorial replacement.

```text
local anomaly
→ evidence of a wider institution
→ access to a larger region
→ discovery of wider political/economic structure
→ new conflict and knowledge
```

Old regions, characters, debts, reputations, and consequences should remain causally relevant after expansion.

### 10.7 Recontextualization

A stable Canon Fact may acquire new interpretations without rewriting history. The fact remains true; Character Belief or Reader Knowledge changes.

---

## 11. Axis 3 — Narrative State

Narrative State answers: what is true now at the current accepted cursor?

It may project:

- Character State;
- Relationship State;
- World State;
- Location State;
- Faction State;
- Resource State;
- Power State;
- Conflict State;
- Mystery State;
- Character Knowledge;
- Character Belief;
- Reader Knowledge;
- Promise / Foreshadow / Obligation State;
- Arc State;
- Theme Movement.

Current State is a projection, not independent historical truth.

---

## 12. Event → State Commit Protocol

All important accepted state transitions must be traceable to an Accepted Narrative Event.

```text
Accepted Prose
→ Narrative Event Extraction
→ Deterministic / governed validation
→ Accepted Narrative Event
→ Canon / Narrative State projections
```

A Narrative Event should be able to carry:

- event identity;
- story time;
- narrative position;
- participants;
- cause refs;
- preconditions;
- fact changes;
- state effects;
- knowledge effects;
- obligation effects;
- Arc effects.

This does not require converting the whole application to a pure Event Sourcing framework. The invariant is simply that significant state changes are causally explainable and replayable from accepted evidence.

---

## 13. Story time and spatial correctness

Narrative position and story time are distinct.

```text
Narrative Position = Chapter 82 / Scene 3
Story Time         = Year 18 / Day 73 / 21:30
```

The domain must be able to represent flashback, flashforward, parallel timeline, memory, and non-linear presentation without corrupting causal chronology.

Spatial correctness may use a lightweight model of:

- Location;
- Parent Location;
- travel/access constraints;
- current occupancy;
- capability-dependent travel rules.

Impossible deterministic travel or co-location errors should be rejected without using an LLM Judge.

---

## 14. Axis 4 — Knowledge / Disclosure / Presentation

Strictly separate:

```text
Story Truth
Character Knowledge
Character Belief
Reader Knowledge
Narrative Presentation
```

The same fact may be true from Chapter 1 while different characters and the reader learn or believe different things at different times.

### 14.1 Disclosure

Disclosure plans control:

- target audience;
- fact/proposition;
- timing;
- mode;
- amount;
- presentation channel.

Typical modes include:

- HINT
- PARTIAL
- MISDIRECT
- CONFIRM
- WITHHOLD

### 14.2 Presentation

Presentation is how information is experienced, e.g. direct experience, observation, dialogue, rumor, hearsay, document, diary, news, memory, flashback, object clue, environmental trace, subtext, unreliable narration, negative space, or off-screen consequence.

### 14.3 POV / focalization

Every Scene should be able to state:

- POV character or narrator;
- focalization;
- narrative distance;
- accessible knowledge.

POV, Character Knowledge, and Disclosure must agree. Knowledge correctness is not complete if a forbidden fact leaks through narrative voice.

---

## 15. Narrative obligations and debt

Promises, foreshadowing, mysteries, unresolved relationship commitments, world consequences, and Arc commitments create future obligations.

The system should expose Narrative Debt metrics such as:

- open obligations;
- overdue obligations;
- obligations due in the next N chapters;
- dormant Arc age;
- unresolved mystery age;
- relationship inactivity;
- character appearance gap;
- unconsumed setup/payoff windows.

Narrative Debt is a derived operational view, not a new Authority.

Planning and Scheduling should actively consume these metrics.

---

## 16. Axis 5 — Reader Experience

Story Function and Reader Effect are separate.

A chapter may perform `Relationship Development` while targeting `Humor + Warmth`, or perform `Mystery Progress` while targeting `Curiosity + Shock`.

Reader effects may include:

- Curiosity;
- Tension;
- Fear;
- Awe;
- Humor;
- Warmth;
- Romance;
- Anger;
- Shock;
- Relief;
- Satisfaction;
- Catharsis;
- reward / 爽感.

### 16.1 Narrative density

Do not force every Chapter to advance every subsystem. Scheduling may deliberately create high-, medium-, low-density, breathing, transition, slice-of-life, humor, atmosphere, or intimacy chapters.

### 16.2 Reader intent vs outcome

```text
Reader Experience Intent
→ Publish
→ Reader Outcome Observation
→ Calibration
```

Predicted experience and observed human outcome must remain distinct. Reader simulators never substitute for real reader data.

---

## 17. Axis 6 — Realization / Visibility

Realization controls how much of the future world/character design is actually specified. Visibility controls what current characters and readers know or can access.

The system should support progressive character and world realization according to narrative horizon, while preserving hard future constraints and open design space.

This axis prevents two opposite failures:

- designing the whole million-word world at full precision before production;
- inventing every new region, character, or faction only at the moment it appears.

---

## 18. Progressive Planning

Long-form planning uses three horizons.

### 18.1 Strategic Horizon

Low-frequency, long-range assets:

- Novel DNA;
- Book Architecture;
- Volume Portfolio;
- major Arcs;
- major character transformations;
- major world expansion;
- ending.

### 18.2 Tactical Horizon

Upcoming Narrative Segments / approximately the next several to several-dozen chapters:

- Segment goals;
- Arc cadence;
- Character development;
- Disclosure;
- Payoff windows;
- World Realization;
- Reader Experience;
- narrative density.

### 18.3 Operational Horizon

Current Chapter and Scene design, generated just in time from accepted current state plus active strategic/tactical design.

### 18.4 Progressive elaboration

Planning detail increases as the narrative approaches execution. Distant future design should preserve anchors and constraints while leaving open design space.

### 18.5 Commitment levels

Future design may distinguish:

```text
HARD_CONSTRAINT
SOFT_INTENT
OPEN_DESIGN_SPACE
```

Hard constraints should be rare and meaningful; soft intent may move through replan; open design space should not be mistaken for missing data.

---

## 19. Volume Portfolio

The canonical global design is a portfolio of qualified Volume plans, not one unique Volume design existing at a time.

```text
Book
→ Volume Portfolio
   ├ V1
   ├ V2
   ├ V3
   └ ...
→ Cross-volume Arc Graph
```

`current_volume` is a runtime projection selected by accepted chapter cursor/range, not the only valid active Volume asset.

A cross-volume Arc may reference multiple qualified Volume plans.

No separate `VolumePortfolioAuthority` is required; reuse Planning Authority and versioned plan bindings.

---

## 20. Narrative Scheduling

Scheduling maps cross-cutting systems onto temporal containers.

A Chapter schedule may state:

```text
PRIMARY    Mystery A
SECONDARY  Relationship B
TOUCH      Theme C
HOLD       Faction D
PAYOFF     Setup from Ch31
SETUP      Mystery for Ch83
READER     Tension → Relief → Suspicion
DENSITY    MEDIUM
```

Scheduling is where Arc cadence, obligations, reader experience, progressive realization, and chapter functions converge.

---

## 21. Narrative Complexity / Load Budget

AI production needs explicit guardrails against overloading one Chapter or Scene.

Reasonable policies may limit or warn on:

- simultaneous primary Arcs;
- secondary/touch Arcs;
- new important characters;
- new major concepts;
- major reveals;
- large state transitions;
- major payoffs;
- obligation congestion.

These are configurable guardrails, not universal literary laws.

Load should be governed before Context construction; otherwise Context optimization merely treats the symptom.

---

## 22. Chapter Execution Plan

The canonical detailed chapter design should include:

- Chapter Intent;
- Primary Function;
- Secondary Functions;
- Arc Schedule;
- Character Participation;
- Knowledge Boundaries;
- Disclosure;
- Required State Transitions;
- Reader Experience;
- Setup / Payoff;
- Prohibited Outcomes;
- Narrative Density;
- Scene Architecture;
- Expected Exit State.

A Chapter plan must derive from active strategic/tactical assets plus the current accepted Narrative State. It must not independently redesign long-range story direction.

---

## 23. Scene Architecture

A governed Scene plan may include:

- Scene Purpose;
- Location;
- Story Time;
- POV / Focalization;
- Participants;
- Entry State;
- Character Goal;
- Opposition;
- Conflict;
- Information Gain;
- Arc Progress;
- State Transition;
- Disclosure;
- Reader Effect;
- Beats;
- Exit State.

A separate Scene execution plane is introduced only when independent leasing, context construction, partial revision, or recovery becomes an observed requirement.

---

## 24. MKAOS role

MKAOS is a task-specific methodology and knowledge retrieval system, not a global prompt warehouse.

```text
Task
→ Knowledge Requirement
→ MKAOS Retrieval
→ Selected Relevant Knowledge
→ Provider
```

Examples:

- Book Architecture: narratology, genre, philosophy, reader psychology, commercial structure;
- World Design: history, politics, economics, sociology, technology;
- Character: psychology, behavior, social relations, character development;
- Mystery: evidence, logic, fair play, misdirection;
- Prose: only the relevant style/POV/dialogue/suspense guidance.

Knowledge assets remain governed and versioned; raw source material should not be copied into prose prompts by default.

---

## 25. Context Compiler

Context is an execution compilation problem.

```text
Authority
→ Versioned Projection
→ Task-specific Projection
→ Provider View
```

For a Scene or Chapter task the compiler may use:

```text
Narrative Position
+ Story Time / POV
+ Active Arc Schedule
+ Relevant Characters
+ Relevant Current State
+ Knowledge Boundary
+ Relevant World Horizon
+ Due Obligations
+ Reader Experience Target
+ Relevant MKAOS
→ Minimum Sufficient Working Context
```

### 25.1 Minimum Sufficient Context

Each Capability defines:

- MUST_INCLUDE;
- OPTIONAL;
- MUST_EXCLUDE.

The target is not the smallest prompt; it is the smallest prompt that remains sufficient for correct task execution.

### 25.2 Context Correctness Contract

Context qualification should be able to enforce or measure:

- NO_FUTURE_FACT;
- NO_HIDDEN_KNOWLEDGE_LEAK;
- NO_STALE_VERSION;
- NO_DUPLICATE_SEMANTIC_REPRESENTATION;
- NO_IRRELEVANT_FULL_ASSET;
- REQUIRED_LONG_DISTANCE_FACT_PRESENT.

### 25.3 Persisted Evidence ≠ Prompt Content

Audit manifests, lineage, hashes, provider receipts, and complete Authority representations remain persisted for replay/audit. They do not automatically enter provider input.

---

## 26. Progressive Narrative Qualification

The desired design admission path is:

```text
Story Intent
↓ QUALIFY
Story Foundation
↓ QUALIFY
Book Architecture
↓ QUALIFY
Volume Portfolio
↓ QUALIFY
Narrative Arc Graph
↓ QUALIFY
Character Development
↓ QUALIFY
World / Character Realization
↓ QUALIFY
Disclosure / Obligation
↓ QUALIFY
Narrative Scheduling
↓ QUALIFY
Chapter Execution Plan
↓ QUALIFY
Scene Architecture
↓ QUALIFY
Prose Admission
```

Qualification is a policy and evidence layer over existing Authorities, not a separate execution plane.

### 26.1 Deterministic validation

Use deterministic checks for identity, lineage, ranges, dependencies, Arc refs, time, spatial impossibility, setup/payoff ordering, knowledge future leaks, resource/state impossibility, duplicate identities, stale versions, and activation freshness.

### 26.2 Narrative Semantic Evaluation

Use layer-specific semantic profiles for narrative capacity, ending reachability, conflict sustainability, Volume differentiation, Arc causality/convergence/closure, character-change causality, disclosure coherence, scheduling balance, chapter purpose, and scene reachability.

Do not use one universal literary Judge.

### 26.3 Independent evaluation trust boundary

A Candidate Generator must not be the sole authority minting its own PASS.

Target flow:

```text
Candidate Generation Operation
→ Immutable Candidate AssetVersion
→ Independent Semantic Evaluation Operation
→ Qualification Receipt
→ Repair / Approval / Activation
```

Reuse the existing Command Kernel, Provider Gateway, Capability Pack, and Story Design Authority.

### 26.4 Authority-bound evidence

Qualification evidence must resolve to immutable current-project/current-book evidence and bind to the exact candidate/content hash and source operation lineage.

---

## 27. Production admission

`LONGFORM_DESIGN_QUALIFIED` is a computed authoritative admission result over current qualified design roots. It is not a new Authority.

`CHAPTER_PRODUCTION_ADMITTED` additionally requires the current Narrative Scheduling, Chapter Execution Plan, Scene design, current accepted Narrative State/Canon cursor, and required Context correctness constraints to agree.

Admission fails closed if any required design becomes stale, superseded, incomplete, or no longer qualified.

---

## 28. Planning dependency and replan protocol

Every downstream plan binds exact upstream AssetVersions.

```text
Upstream Version
→ Downstream Version
→ Dependency / Reference Graph
```

When future design changes:

```text
Accepted Reality
→ Drift / Reader / Quality / Operator Evidence
→ Replan Candidate
→ Impact Analysis
→ Affected Future Assets STALE
→ Regenerate
→ Requalify
→ Activate New Versions
```

Accepted chapters, Canon, accepted Narrative Events, and past Narrative State projections are not rewritten.

### 28.1 Minimal invalidation

Use asset dependency lineage to compute the smallest affected future closure rather than making the entire Book stale.

A change to an Arc Segment may affect future Scheduling, Chapter Plans, Disclosure timing, Character trajectories, or payoff windows while leaving unrelated Volume designs and accepted history intact.

### 28.2 Replan scopes

Useful scopes include:

- BOOK;
- VOLUME;
- NARRATIVE_SEGMENT;
- ARC;
- ARC_SEGMENT;
- CHAPTER_GROUP;
- CHAPTER.

---

## 29. Canonical execution plane

Novel Forge has one production execution plane:

```text
Command
→ Operation
→ Attempt
→ Lease
→ Fence
→ ExternalEffect
→ Provider / Tool
→ Receipt
→ Domain Commit
```

No Narrative feature may introduce a competing workflow or provider path merely for convenience.

---

## 30. Reliability and recovery

### 30.1 Retry

Retryable failures use bounded retry and must not produce retry amplification between Operation and ExternalEffect layers.

### 30.2 Idempotency

Recovery/replay must prevent:

- duplicate provider side effects;
- duplicate AssetVersions;
- duplicate Qualification receipts;
- duplicate Narrative Events;
- duplicate Chapters;
- duplicate Canon/State transitions;
- duplicate activations;
- duplicate publishing effects.

### 30.3 Recovery semantics

Restart/resume uses persisted Authority state, not reconstructed in-memory workflow state. Lease/fence semantics prevent stale workers from committing after ownership transfer.

---

## 31. Quality architecture

Quality is separated into three categories.

### 31.1 Narrative Correctness

Prefer deterministic validation for:

- Canon;
- chronology;
- spatial feasibility;
- knowledge;
- resources;
- identity;
- hard world rules;
- obligations;
- state transitions.

### 31.2 Narrative Quality

Semantic Judges evaluate structure, character depth, prose, theme, conflict, mystery, worldbuilding, pacing, and long-form craft.

### 31.3 Reader / Commercial Quality

Separate evaluation for hooks, reader promise, serialization rhythm, reward cadence, platform fit, and commercial readability.

Do not collapse all three into one opaque overall score.

---

## 32. Multi-scale and longitudinal quality

Quality must operate at multiple scales:

```text
Book
Volume
Arc
Narrative Segment
Chapter
Scene
```

Longitudinal windows should inspect approximately 10-chapter, 30-chapter/Volume, and longer trends such as:

- hook convergence;
- Arc dormancy;
- character disappearance;
- payoff density;
- obligation debt;
- world expansion rate;
- repeated scene structure;
- dialogue/prose drift;
- reader reward interval;
- Context growth;
- correction/replan frequency.

A Chapter Judge cannot detect these problems alone.

---

## 33. Serialization strategy

Web-novel production strategy is not Canon. It may define:

- target chapter length;
- publishing cadence;
- hook diversity;
- short-term reward cadence;
- major payoff cadence;
- Volume climax distance;
- reader fatigue controls;
- recap strategy;
- platform/commercial constraints.

Scheduling may consume these constraints without storing them as story truth.

---

## 34. Observability and Narrative Operations

Traditional telemetry remains required: logs, traces, DB health, provider latency, token/cost, operation/attempt/effect status, worker/lease/fence health.

Narrative operations should additionally expose metrics such as:

- Active Arcs per Chapter;
- dormant Arc age;
- open/overdue obligations;
- character appearance gap;
- Narrative Load;
- world expansion rate;
- new concepts per Chapter;
- reader reward interval;
- hook similarity;
- state transition density;
- Canon correction rate;
- replan frequency;
- selected context tokens;
- provider input tokens;
- Prompt Amplification Ratio;
- Context Growth Slope;
- provider calls / accepted Chapter;
- wall time / accepted Chapter.

The core scalability invariant is:

```text
Chapter Number ↑
Narrative Authority ↑
Provider Working Context must remain bounded and task-relevant
```

---

## 35. Security and boundaries

- Provider access must use the governed Provider Gateway.
- Tools are default-deny and Capability-controlled.
- Agents cannot directly mutate Domain Authority.
- No direct database mutation may bypass owning Authority semantics.
- Source eligibility and lineage remain governed.
- Audit evidence is persisted and immutable where required.
- External publishing, human-reader data, and third-party services are explicit boundary integrations rather than implicit side effects.

---

## 36. Domain and Authority model

Do not create one Authority per literary term.

### Long-lived Authorities / canonical owners

- Story / Book Design;
- World Rules / foundational design through existing design authority;
- Character Identity through existing design authority;
- Hierarchical / Narrative Planning;
- Canon;
- Narrative Event lineage;
- Narrative State;
- MKAOS;
- Book / Chapter production;
- Plan Change / Replan;
- Quality / Reader evidence where already owned by existing modules.

### Versioned planning assets

- BookPlan;
- VolumePlan;
- NarrativeSegmentPlan or equivalent Volume-local segment representation;
- ArcPlan;
- ChapterGroupPlan;
- ChapterPlan / ChapterExecutionPlan.

### Derived projections

- Current Character State;
- Current Relationship State;
- Current Volume;
- Arc Progress;
- Reader Knowledge;
- Narrative Debt;
- World Horizon;
- Realization/visibility projections.

### Ephemeral execution assets

- Provider Task View;
- Provider Context View;
- prompt materialization;
- review/revision views.

Ephemeral execution views never become truth sources.

---

## 37. Data lifecycle

Design asset lifecycle:

```text
Candidate
→ Immutable AssetVersion
→ Deterministic Validation
→ Semantic Evaluation
→ Qualification
→ Approval
→ Active Binding
→ Downstream Version Reference
```

Narrative history lifecycle:

```text
Accepted Prose
→ Accepted Narrative Events
→ Canon / State / Knowledge / Arc / Obligation Projections
```

Plan versions and accepted reality remain separately addressable and auditable.

---

## 38. Testing and qualification model

Strict proof ladder:

```text
Unit
→ Integration
→ PostgreSQL Integration
→ Runtime Composition
→ Recovery / Replay
→ Design-only E2E
→ Real Provider Composition
→ Chapter 1–5 Stateful Proof
→ 30 Chapter Proof
→ 100 Chapter Proof
→ 300 Chapter Proof
→ Effectiveness A/B
→ Real Reader Calibration
→ Multi-book Proof
→ Production Admission
```

Proof vocabulary:

```text
MISSING
SKELETON
IMPLEMENTED
WIRED
FIXTURE_PROVEN
REAL_PROVIDER_PROVEN
LONGFORM_PROVEN
MULTIBOOK_PROVEN
PRODUCTION_PROVEN
```

A lower proof class never implies a higher one.

---

## 39. Design-only proof

Before prose proof, the system should prove the design production chain itself:

```text
Story Intent
→ Story Foundation
→ Book Architecture
→ Volume Portfolio
→ Cross-volume Arc Graph
→ Character Development
→ World / Character Realization
→ Disclosure / Obligation
→ Narrative Scheduling
→ Chapter Execution Plan
→ Scene Architecture
→ CHAPTER_PRODUCTION_ADMITTED
```

Stop before prose. This isolates design correctness from prose/runtime quality.

---

## 40. Current-to-target gaps

### P0 — must close

1. Independent Narrative Semantic Evaluation: the generator must not be the only judge minting its own PASS.
2. Authority-bound qualification evidence: evidence refs must resolve to exact immutable lineage.
3. Multi-Volume Portfolio semantics: multiple qualified Volume plans must coexist while runtime selects the current Volume as a projection.
4. Exact-SHA Engineering Qualification for current Progressive Narrative Design changes.
5. Strategic / Tactical / Operational Planning Horizons in canonical contracts and orchestration.
6. Progressive World and Character Realization in planning/contracts without creating a new execution plane.
7. Event → State causality for important accepted state transitions.
8. Story Time / POV / Knowledge boundary correctness.
9. Narrative Complexity / Load Budget.
10. Narrative Debt metrics and planning consumption.
11. Asset dependency graph / minimal stale propagation and requalification.
12. Context Correctness Contract.
13. Multi-scale / Longitudinal Quality.

### P1 — should close

- spatial/travel consistency;
- HARD_CONSTRAINT / SOFT_INTENT / OPEN_DESIGN_SPACE planning semantics;
- Serialization Strategy;
- Character Scope / Reach;
- explicit Narrative Convergence planning;
- Style Bible / voice projection;
- Reader Experience Intent vs Outcome calibration;
- Narrative operational metrics and reports;
- world expansion-rate governance.

### P2 — later enhancement

- automatic pacing optimization;
- Arc portfolio optimization;
- Scene-level prose runtime if evidence justifies it;
- bounded Quality Judge concurrency;
- adaptive chapter length;
- advanced Reader Simulator;
- multi-model routing;
- multi-book production portfolio optimization.

### Not required now

Do not create separate World Realization, Character Development, Narrative Debt, POV, Beat, Causality, Arc Graph, or Scene workflow microservices unless observed runtime requirements justify them.

---

## 41. Roadmap

### Phase A — Architecture Correctness Closure

Close the semantic trust boundary, Volume Portfolio semantics, Progressive Planning/Realization contracts, Event→State contract, and Time/POV correctness.

### Phase B — Planning and Governance Closure

Implement Narrative Load, Narrative Debt, dependency-driven invalidation, Context Correctness, and longitudinal quality foundations.

### Phase C — Design Production Closure

Run the full canonical design chain through qualification and `CHAPTER_PRODUCTION_ADMITTED`, without prose.

### Phase D — Full Engineering Qualification

Fresh migration, upgrade migration, PostgreSQL integration, unit/integration tests, runtime composition, recovery/replay, lint/type/build, Capability Pack/skill validation.

### Phase E — Chapter 1–5 Stateful Runtime Proof

Measure continuation correctness, Event→State, knowledge boundaries, provider input growth, prompt amplification, retry/recovery, and actual chapter acceptance.

### Phase F — 30 Chapter Proof

Prove short long-form continuity, context correctness, obligations, state progression, and bounded runtime behavior.

### Phase G — 100 Chapter Proof

Prove Arc persistence, character trajectories, world expansion, long-distance retrieval, Narrative Debt, Progressive Realization, and longitudinal quality.

### Phase H — 300 Chapter Proof

Prove genuine single-book long-form correctness and operational feasibility.

### Phase I — Effectiveness

Paired/frozen A/B evaluation of MKAOS, Quality/Correction, and Replan effectiveness.

### Phase J — Real Reader Calibration

Use real human outcome data with temporal integrity and holdout evaluation.

### Phase K — Multi-book / Production Admission

Only after single-book long-form proof succeeds: multi-book proof, scale, portfolio scheduling, publishing automation, operational admission, and production authorization.

---

## 42. Final target runtime

```text
SOURCE / MKAOS
        ↓
STORY INTELLIGENCE
        ↓
NOVEL DNA
        ↓
BOOK ARCHITECTURE
        ↓
VOLUME PORTFOLIO
        ↓
ARC GRAPH
        ↓
WORLD / CHARACTER REALIZATION
        ↓
DISCLOSURE / OBLIGATION
        ↓
NARRATIVE SCHEDULING
        ↓
LONGFORM_DESIGN_QUALIFIED
        ↓
CURRENT ACCEPTED STATE
        ↓
CHAPTER EXECUTION PLAN
        ↓
SCENE ARCHITECTURE
        ↓
CHAPTER_PRODUCTION_ADMITTED
        ↓
CONTEXT COMPILER
        ↓
PROVIDER
        ↓
PROSE
        ↓
CORRECTNESS
        ↓
REVIEW / REVISION
        ↓
NARRATIVE EVENT EXTRACTION
        ↓
CANON / STATE PROJECTION
        ↓
QUALITY
        ↓
ACCEPTED CHAPTER
        ↓
PUBLISH / OBSERVE
        ↓
RECAP / DRIFT
        ↓
GOVERNED REPLAN
```

---

## 43. Final architectural position

The canonical hierarchy is now stable:

```text
Book → Volume → Narrative Segment → Chapter → Scene → Beat
```

Industrial-grade long-form capability does not come from adding more hierarchy levels. It comes from the six Narrative Axes and five industrial control systems around that hierarchy:

```text
Temporal Hierarchy
Arc Graph
Narrative State
Knowledge / Disclosure
Reader Experience
Realization / Visibility

+

Progressive Planning
Narrative Scheduling
Context Compiler
Qualification / Governance
Runtime / Feedback / Recovery
```

The three most important long-term architectural upgrades are:

1. Progressive Planning: Strategic → Tactical → Operational rather than one-time full-book detailing.
2. Progressive Realization: world and characters move from Anchor → Defined → Detailed → Active as the narrative horizon approaches.
3. Event → State: accepted narrative events provide causal evidence for every important persistent state transition.

The resulting system is not merely an AI capable of generating a 300-chapter novel. It is a governed Narrative Operating System capable of treating a continuously expanding long-form web novel as an evolving, versioned, recoverable, auditable system while preserving causality, character growth, world expansion, knowledge boundaries, obligations, reader experience, and bounded provider context at million-word scale.
