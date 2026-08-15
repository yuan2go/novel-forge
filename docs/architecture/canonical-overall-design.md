# Novel Forge / Autonomous Novel OS — Canonical Overall Design

> **Status:** Canonical target architecture baseline  
> **Scope:** product, domain, runtime, governance, qualification, and production-admission design  
> **Normative role:** this document defines what Novel Forge is intended to become. `overview.md`, `runtime.md`, `authority-model.md`, `production-execution.md`, `narrative-state.md`, and `source-and-knowledge.md` describe the currently reachable implementation and must not silently upgrade implementation evidence to target-state claims.

## 0. Reading and authority rules

Novel Forge has two different kinds of truth that must never be conflated:

1. **Product/architecture target truth** — this document is the design source of truth.
2. **Current implementation truth** — source code, migrations, architecture manifests, executable entry points, tests, and pinned-SHA runtime evidence outrank prose descriptions.

A later design change that contradicts this document must update this document in the same change set. ADRs record durable implementation decisions; they may refine this design but must not create a competing system shape.

Evidence and maturity are separate from design completeness. A capability may be well designed and still be `MISSING`, or implemented without being runtime-proven.

---

## 1. Executive summary

Novel Forge is a **Human-AI Collaborative Long-form Narrative Operating System with a Governed Autonomous Production Runtime**.

It is not merely a prompt chain, chapter generator, writing chatbot, or network of autonomous Agents. It combines two product surfaces over one governed domain/runtime foundation:

```text
              HUMAN AUTHOR
                   │
                   ▼
      CONVERSATIONAL CREATIVE STUDIO
      discussion / design / diagnosis / edit
                   │
                   ▼
      proposal / decision / semantic diff
                   │
                   ▼
        NARRATIVE DESIGN AUTHORITY
        + FUTURE INTENT / PLAN STATE
                   │
                   ▼
       CANONICAL PRODUCTION RUNTIME
 planning → context → provider → prose
 review → revision → correctness → quality
                   │
                   ▼
          ACCEPTED NARRATIVE LINEAGE
                   │
                   ▼
          PUBLISH → OBSERVE → LEARN
                   │
                   ▼
              GOVERNED REPLAN
```

The author remains the source of creative intent, taste, and high-impact creative decisions. Agents provide specialized reasoning, exploration, simulation, planning, generation, diagnosis, and editing. Domain Authorities own accepted business state. PostgreSQL is the production business Source of Truth.

The core architectural rule is:

> **Agents propose; Authorities commit. Conversation is an interaction surface, not story truth.**

Long-form correctness comes from an expanding but governed Narrative Authority combined with bounded task-specific provider context. It does not come from giving a model the entire manuscript or treating an Agent's chat history as memory.

---

## 2. Goals

Novel Forge must eventually support all of the following without creating parallel runtime or authority planes.

### 2.1 Human-AI creative collaboration

The author can converse with a Chief Editor or a specialist creative role to explore or adjust:

- topic, genre, premise, target readers, reader promise, and commercial positioning;
- theme, philosophical questions, tone, style, and creative constraints;
- world rules, institutions, factions, power systems, history, economics, and consequences;
- protagonists, supporting characters, relationships, motivation, knowledge, belief, and development;
- Book architecture, Volume design, Arc trajectories, Narrative Segments, Chapter plans, and Scene plans;
- imported material, research, creative seeds, and ways to integrate them into the story;
- chapter prose, wording, dialogue, scene behavior, reveals, hooks, and local or structural plot changes;
- longitudinal drift, narrative debt, reader outcome, and future replan.

The author may enter through the Chief Editor or directly through a specialist. The Chief Editor is the default coordinator, not the only conversational Agent.

### 2.2 Long-form narrative correctness

The system must keep coherent over hundreds or thousands of chapters:

- story direction and ending reachability;
- Canon and accepted event lineage;
- character identity, temporal state, knowledge, belief, relationships, and development;
- world invariants, structure, temporal state, realization, and visibility;
- story time, narrative position, POV, space, causality, and resource constraints;
- cross-time Arcs and their cadence;
- promises, mysteries, foreshadowing, open loops, obligations, and payoff debt;
- reader knowledge, disclosure, presentation, reader experience intent, and outcome;
- active plans, future intent, supersession, replan, and qualification lineage.

### 2.3 Governed autonomous production

When authorized, the system can continue producing chapters without continuous human input while preserving the same Authority, Context, Quality, recovery, trace, and cost rules used during supervised production.

Autonomous mode means the system can proceed within policy when the author is absent. It never means that the author loses the ability to inspect, pause, revise future intent, or make governed corrections.

### 2.4 Recoverability and auditability

For every important result the system must be able to answer:

- which Book and narrative scope was involved;
- which Authority versions and accepted-state cursor were read;
- which Agent definition, capabilities, Skill/Capability Pack, provider route, and context snapshot were used;
- which Operation, Attempt, ExternalEffect, and receipt produced the evidence;
- what proposal or revision was accepted, rejected, superseded, or deferred;
- what changed in Canon, Narrative State, planning, or future intent;
- how retry, recovery, replay, and concurrency ownership behaved.

### 2.5 Continuous learning without automatic story corruption

The system may learn from real reader outcomes, simulation, quality evidence, production metrics, and retrospectives. Those signals may change future planning, policies, MKAOS assets, or adaptation proposals. They may never directly rewrite accepted Canon.

### 2.6 Scale only after correctness

The architecture should remain compatible with multiple concurrent Books and future portfolio scheduling, but single-book correctness and recovery must be proven before multi-book scale becomes a production objective.

---

## 3. Non-goals

The target architecture does **not** require:

- one Agent, Authority, service, or workflow for every literary concept;
- a `BookAgent`, `VolumeAgent`, `ArcAgent`, `ChapterAgent`, and `SceneAgent` family multiplied by every domain;
- free-form Agent-to-Agent chat as a source of business state;
- chat history, vector retrieval, or model memory as Narrative Authority;
- a second workflow engine, second execution kernel, or second state plane for conversational features;
- a generic new `NarrativeChangeAuthority` when existing Collaboration, PlanChange, Revision, Corrective Action, and owning Domain Authorities can express the lifecycle;
- a new `WorkOrder` execution primitive parallel to the current Command/Operation/Attempt/RuntimeJob model;
- a pure Event Sourcing rewrite of the entire platform;
- a separate Authority for Theme, Philosophy, POV, Beat, Narrative Debt, World Realization, or each Arc type;
- a separate Scene execution plane before independent leasing, context, recovery, or revision requirements justify it;
- premature microservices or a distributed Agent mesh;
- full-world or full-book detailed planning before Chapter 1;
- multi-model optimization before one governed provider path is proven;
- automatic Canon mutation from reader feedback;
- fully autonomous external publishing before production admission.

Production-grade means robust semantics and evidence, not maximum abstraction count.

---

## 4. Core architecture principles and invariants

1. **PostgreSQL Authority is the production business Source of Truth.**
2. **Agent output is a proposal.** Agents never own Domain Authority.
3. **Conversation is not Authority.** A transcript may be durable evidence, but it becomes actionable only through a captured decision/proposal lifecycle.
4. **Author intent is future-facing design evidence, not accepted story truth.**
5. **Planning is future intent, never accepted reality.**
6. **Planned transitions are not Accepted Narrative Events.**
7. **Only accepted narrative lineage can advance Canon and current Narrative State.**
8. **Accepted Narrative Events provide causal evidence for important persistent state transitions.**
9. **Current Narrative State is a projection over accepted evidence, not an independent history source.**
10. **Temporal hierarchy and Arc graph are orthogonal.** Arc is not a mandatory child of Volume.
11. **The canonical temporal hierarchy is `Book → Volume → Narrative Segment → Chapter → Scene → Beat`.**
12. **Series is optional portfolio/shared-universe metadata, not a required single-book production level.**
13. **Character = stable identity + temporal state + development trajectory.**
14. **World Invariants, Structural World Model, Temporal World State, Realization, Visibility, and Accessibility are distinct.**
15. **Story Truth, Character Knowledge, Character Belief, Reader Knowledge, and Presentation are distinct.**
16. **Important disclosure and POV constraints are correctness boundaries, not prose preferences.**
17. **Promises, mysteries, foreshadowing, open loops, and Arc commitments create observable obligations/debt.**
18. **Future design is progressively elaborated.** Distant design preserves anchors while keeping legitimate open design space.
19. **Authority growth must not imply unbounded prompt growth.**
20. **Context is a derived, versioned execution view, never Authority.**
21. **Provider input is task-specific Minimum Sufficient Context.**
22. **MKAOS owns reusable knowledge/method assets, not story facts and not execution ownership.**
23. **Conversational Agent roles are stable product personas backed by versioned AgentDefinition + capabilities, not new Authorities.**
24. **User-facing Agent routing is a UX decision; Authority routing remains domain-driven.**
25. **A local edit may not silently become a Book-level change.** Change scope and impact must be classified.
26. **Accepted history is never mutated in place.** Corrections create new governed lineage or future-scoped changes.
27. **Replan changes future design and invalidates the smallest affected dependency closure.**
28. **Deterministic correctness should remain deterministic.** LLM Judges are reserved for genuinely semantic evaluation.
29. **Quality Judge and conversational Quality Editor are separate concerns.**
30. **The system has one production execution plane:** `Command → Operation → Attempt → Lease/Fence → ExternalEffect → Provider/Tool → Receipt → Domain Commit`.
31. **Technical retry and semantic revision are different business meanings.**
32. **Restart/recovery uses persisted Authority state, not reconstructed in-memory workflows.**
33. **Fixture proof must never be promoted to Real Provider, Long-form, Multi-book, or Production proof.**
34. **New abstractions require observed lifecycle, concurrency, recovery, or scale evidence.**

---

## 5. Business architecture

Novel Forge has five connected business loops.

### 5.1 Creative discovery and design loop

```text
Human Intent / Question / Idea
→ Conversational Creative Studio
→ Specialist reasoning + knowledge
→ Candidate design / alternatives
→ semantic proposal + rationale
→ impact / risk assessment
→ human or policy decision
→ owning Design/Planning Authority
→ active future design version
```

Typical use cases include starting a new Book, comparing premises, debating a philosophical theme, designing a world rule, deepening a protagonist, or changing a major future reveal.

### 5.2 Source and knowledge loop

```text
Source
→ Import
→ Normalize / Chunk
→ Classification / methodology selection
→ Deconstruction / observation / evidence
→ MKAOS Candidate
→ Governance
→ Knowledge Asset
→ Capability usage
→ Feedback
```

Sources and popular fiction may be analyzed for structure, pacing, conflict, character mechanisms, emotional curves, hooks, and commercial patterns. Raw copyrighted expression is not promoted into prose-generation context by default.

### 5.3 Progressive long-form design loop

```text
Story Intent
→ Story Foundation / Novel DNA
→ Book Architecture
→ Volume Portfolio
→ cross-time Arc Graph
→ Character / World Realization
→ Disclosure / Obligations
→ Narrative Scheduling
→ Chapter Execution Plan
→ Scene Architecture
→ progressive qualification
→ CHAPTER_PRODUCTION_ADMITTED
```

### 5.4 Chapter production and author editing loop

```text
Accepted current state + qualified future design
→ Context Compiler
→ Provider / prose generation
→ Draft
→ review / author Chapter Editor interaction
→ revision
→ correctness
→ Narrative Event extraction
→ Canon / State projection candidate
→ quality
→ acceptance
→ accepted chapter lineage
```

The primary conversational surface after a draft exists is **Chapter Editor**. It may invoke or consult Chapter Director, Character Director, Plot Doctor, Canon/Continuity, Style, or other capabilities behind the scenes. The author should not have to manually route every edit.

### 5.5 Publish / observe / learn / adapt loop

```text
Accepted Chapter
→ Publish
→ Observe
→ Reader Outcome
→ Attribution / Calibration
→ Long-form Retrospective
→ Adaptation / Replan proposal
→ impact / governance
→ future design
```

Reader outcome is evidence, not truth. It can influence future design and policies but never mutate accepted Canon directly.

---

## 6. Capability architecture

The capability map is organized by responsibility rather than by Agent count.

```text
Novel Forge
│
├ Creative Interaction
│  ├ Conversational sessions and scope
│  ├ decision capture
│  ├ proposal / semantic diff
│  ├ impact / risk
│  ├ human approval / rejection / deferral
│  └ chapter editing
│
├ Story Intelligence
│  ├ topic / genre / premise
│  ├ reader positioning
│  ├ commercial pattern analysis
│  └ story potential / differentiation
│
├ Narrative Design
│  ├ Novel DNA / Story Foundation
│  ├ Book Architecture
│  ├ Volume Portfolio
│  ├ Narrative Segments
│  ├ Arc Graph
│  ├ Character Development
│  ├ World Design / Realization
│  ├ Theme / philosophy
│  ├ Disclosure / Obligations
│  └ Narrative Scheduling
│
├ Narrative Execution
│  ├ Chapter Design
│  ├ Scene Design
│  ├ Context Compiler
│  ├ Prose / Dialogue / Description / Action
│  └ Revision
│
├ Narrative Correctness
│  ├ Canon
│  ├ Narrative State
│  ├ Narrative Event extraction
│  ├ knowledge / belief / disclosure
│  ├ temporal / spatial / causal checks
│  └ obligation consistency
│
├ Knowledge
│  ├ Source Intelligence
│  ├ research / evidence
│  ├ MKAOS
│  └ retrieval
│
├ Quality
│  ├ deterministic correctness
│  ├ Narrative Semantic Evaluation
│  ├ prose / style / character / world quality
│  ├ reader / commercial quality
│  ├ longitudinal quality
│  └ corrective action
│
├ Governance
│  ├ qualification
│  ├ approval / activation / supersession
│  ├ replan / retcon policy
│  └ Production Admission
│
└ Platform
   ├ Command Kernel
   ├ Agent Runtime / Collaboration
   ├ Provider Runtime
   ├ PostgreSQL Authority
   ├ object artifacts
   ├ RuntimeJob / worker execution
   ├ trace / metrics / cost
   └ retry / recovery / replay
```

Capabilities are versioned units of work with typed contracts and qualification/risk policy. Skills are reusable procedures. Capability Packs freeze compatible roles, capabilities, Skills, prompts, tools, policies, and gates. None of these owns story truth.

---

## 7. System architecture — six planes

The target system is best understood as six logical planes over one production runtime.

```text
┌──────────────────────────────────────────────────────────┐
│ 1. CREATIVE INTERACTION PLANE                            │
│ Human author / Novel IDE / Chief Editor / specialist     │
│ conversations / selected-text editing / approvals        │
└──────────────────────────┬───────────────────────────────┘
                           │ proposals / decisions
┌──────────────────────────▼───────────────────────────────┐
│ 2. NARRATIVE INTELLIGENCE & DESIGN PLANE                 │
│ story / world / character / theme / reader / planning    │
│ progressive realization / scheduling                     │
└──────────────────────────┬───────────────────────────────┘
                           │ versioned future design
┌──────────────────────────▼───────────────────────────────┐
│ 3. NARRATIVE AUTHORITY PLANE                             │
│ Canon / accepted events / Narrative State / active plans │
│ decisions / lineage / plan change                        │
└──────────────────────────┬───────────────────────────────┘
                           │
        ┌──────────────────┴───────────────────┐
        │                                      │
┌───────▼────────────────┐            ┌────────▼────────────┐
│ 4. KNOWLEDGE PLANE     │            │ 5. EXECUTION PLANE │
│ Source / MKAOS /       │            │ Command Kernel /   │
│ evidence / retrieval   │            │ RuntimeJob / PEP / │
│                        │            │ Provider / Quality  │
└───────┬────────────────┘            └────────┬────────────┘
        │                                      │
        └──────────────────┬───────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ 6. OBSERVATION, GOVERNANCE & LEARNING PLANE              │
│ trace / cost / quality / reader outcome / retrospective  │
│ qualification / recovery evidence / adaptation           │
└──────────────────────────────────────────────────────────┘
```

These are logical responsibility planes, not a mandate for six deployable services.

---

## 8. Long-form narrative architecture

### 8.1 Temporal hierarchy

The canonical temporal containment hierarchy is:

```text
Book → Volume → Narrative Segment → Chapter → Scene → Beat
```

- **Book** owns macro direction, ending, major transformations, major reader promise, and whole-book constraints.
- **Volume** is a timeline container with a distinct narrative function, entry/exit state, central pressure, climax, irreversible change, major payoffs, and bridge.
- **Narrative Segment** is the medium-scale story-design unit answering why a contiguous group of chapters exists together.
- **Chapter** is the publishable accept/reject business unit.
- **Scene** is the principal local dramatic unit.
- **Beat** remains an embedded planning value unless future evidence justifies more.

`ChapterGroup` is a production/scheduling/checkpoint construct and is not semantically interchangeable with Narrative Segment.

### 8.2 Arc graph is orthogonal

An Arc is a cross-time state-changing trajectory, not a Volume child:

```text
Narrative Thread  optional persistent concern/question
Narrative Arc     state-changing trajectory
Arc Segment       local phase of a long Arc
Arc Relation      causal/dependency relation
```

An Arc may span multiple Volumes and may have setup, echo, activation, reversal, payoff, and aftermath points. Plot, character, relationship, mystery, conflict, world, faction, resource, power, theme, and romance may share one Arc protocol rather than separate engines.

### 8.3 Progressive planning horizons

Planning uses three horizons:

- **Strategic:** Novel DNA, Book Architecture, Volume Portfolio, major Arcs, ending, major transformations.
- **Tactical:** upcoming Narrative Segments and next several-to-several-dozen chapters, including Arc cadence, disclosure, obligations, realization, reader experience, and density.
- **Operational:** current Chapter and Scene, derived just in time from accepted state plus active strategic/tactical design.

Future design distinguishes:

```text
HARD_CONSTRAINT
SOFT_INTENT
OPEN_DESIGN_SPACE
```

Open design space is intentional flexibility, not missing data.

### 8.4 Character architecture

```text
Character = Stable Identity
          + Current Temporal State
          + Development Trajectory
```

Temporal state may include location, physical/emotional condition, goals, knowledge, belief, relationships, reputation, resources, power, status, and access. Development may include belief, goal, identity, competence, responsibility, moral boundary, emotional state, relationship, power, status, resource, and reach.

Character growth should create causal consequences in access, responsibility, risk, worldview, and social/political reach rather than being modeled as a numeric power counter only.

### 8.5 World architecture

```text
World
├ World Invariants
├ Structural World Model
├ Temporal World State
├ World Knowledge
├ World Visibility
├ Accessibility
├ Discovery Frontier
└ Progressive Realization
```

Realization may use a small stable vocabulary such as `ANCHOR → DEFINED → DETAILED → ACTIVE`. The system should avoid both overdesigning the entire world before Chapter 1 and inventing everything only when prose needs it.

### 8.6 Knowledge, disclosure, and presentation

Keep separate:

```text
Story Truth
Character Knowledge
Character Belief
Reader Knowledge
Narrative Presentation
```

Every Scene can constrain POV/focalization, accessible knowledge, disclosure intent, and presentation mode. Future-fact leakage or hidden-knowledge leakage is a correctness error, not merely a style issue.

### 8.7 Narrative obligations and debt

Promises, mysteries, foreshadowing, unresolved conflicts, relationship commitments, world consequences, and Arc commitments create future obligations. Narrative Debt is a derived operational view, not a new Authority.

Useful signals include open/overdue obligations, due windows, dormant Arc age, character appearance gap, unresolved mystery age, relationship inactivity, and payoff congestion.

### 8.8 Reader experience

Story function and reader effect are separate dimensions. Scheduling can target curiosity, tension, awe, humor, warmth, romance, anger, shock, relief, satisfaction, catharsis, or reward while controlling density and fatigue.

Predicted reader experience and observed human outcome are always distinct.

---

## 9. Conversational Creative Studio

The Creative Studio is the canonical human interaction layer. It is **not** a second Agent runtime.

### 9.1 User-facing conversational roles

These are stable product roles backed by versioned `AgentDefinition` plus capabilities. They should not become one service/class/Authority per persona.

| Role | Primary responsibility | Typical scope |
|---|---|---|
| **Chief Editor** | default creative coordinator, trade-offs, cross-domain synthesis | Book → Chapter |
| **Story Architect** | mainline, Book/Volume/Segment/Arc architecture, ending reachability | Book → Segment |
| **Character Director** | identity, motivation, relationships, development, behavior | Book → Scene |
| **World Architect** | world rules, institutions, factions, consequences, realization | Book → Segment |
| **Theme & Philosophy Advisor** | theme, value conflict, philosophical questions, non-preachy embodiment | Book → Arc/Segment |
| **Reader & Commercial Strategist** | reader promise, hooks, reward cadence, serialization, positioning | Book → Chapter |
| **Plot Doctor** | diagnose existing plot problems, alternatives, re-routing, structural repair | Volume → Chapter |
| **Research & Material Curator** | research, creative seeds, evidence, compatibility and placement | Book → Scene |
| **Chapter Director** | pre-writing chapter/scene structure, conflict, reveal, pacing, hook | Chapter → Scene |
| **Chapter Editor** | post-draft wording, dialogue, scene and chapter revision; primary edit surface | Chapter → selected text |
| **Long-form Retrospective** | rolling-window/Volume/Book drift and debt diagnosis | Window → Book |
| **Reader Outcome Analyst** | interpret real reader outcomes and attribution | Chapter → Book |

Optional consultative roles include Canon/Continuity Consultant, Quality Editor, and Style/Voice Editor.

Background components such as Context Builder, retrieval, Writer Runtime, Canon extraction, Quality Judge, scheduler, Provider Router, Retry/Recovery, Trace/Cost, and Authority committers are not conversational personas.

### 9.2 Direct specialist entry

The Chief Editor is a default route, not a mandatory proxy. The author may directly open the World Architect, Character Director, Plot Doctor, Chapter Editor, or another specialist. The role changes the reasoning/context/capability profile; it does not change which Domain Authority owns accepted state.

### 9.3 Conversation Context Contract

A conversational execution should bind an immutable or reproducible context identity containing at least:

- workspace/project/book identity;
- narrative scope and selected entity;
- selected text/draft/revision when applicable;
- current accepted Narrative State/Canon cursor;
- active relevant design/plan versions;
- AgentDefinition / role / capability snapshot;
- allowed knowledge visibility and tools;
- relevant Author Intent / future design constraints;
- pending proposals/decisions relevant to the session;
- relevant MKAOS/research evidence;
- token/cost/context budget.

The author should be able to say “this line is wrong” after selecting text without re-uploading the Book state, while the provider still receives only task-relevant context.

### 9.4 Conversation → Decision Capture

Conversation may contain brainstorming, alternatives, rejected ideas, questions, provisional intent, or concrete decisions. It therefore cannot be copied wholesale into Narrative Authority.

The canonical lifecycle is:

```text
Conversation / Collaboration Session
→ candidate decision extraction
→ Accepted / Rejected / Open / Deferred classification
→ proposal + rationale + scope
→ semantic diff when changing existing design
→ impact / risk assessment
→ human or policy decision
→ owning Authority command
→ versioned commit / activation / supersession
```

A captured decision should preserve author rationale where it is important to downstream quality or planning.

### 9.5 Agent collaboration reuse

Conversational collaboration must extend the existing Agent Collaboration model: scope snapshots, read/proposal/authority boundaries, knowledge visibility, impact assessment, escalation, and human-decision-required semantics. Do not introduce a parallel “chat authority” unless an independent lifecycle, concurrency model, or recovery requirement appears that the existing collaboration domain cannot express.

---

## 10. Narrative Change Protocol

The system needs one coherent **protocol for change**, not one new universal change Authority.

Existing owning mechanisms should be reused:

- Agent Collaboration for scoped proposals, challenges, impact assessments, and human decisions;
- PlanChange Authority for semantic changes to future plans;
- Revision / Corrective Action for prose and quality-driven repair;
- Story/Book Design Authorities for foundational design versions;
- Canon/Narrative State acceptance boundaries for accepted reality;
- Replan for future dependency invalidation/regeneration.

### 10.1 Change levels

| Level | Meaning | Examples | Default handling |
|---|---|---|---|
| **L0 Text** | wording-only, no semantic story change | sentence compression, diction, style | Chapter Editor → revision |
| **L1 Scene** | local behavior/presentation with bounded story semantics | dialogue tone, action, information release | Chapter Editor + relevant specialist capability |
| **L2 Chapter Structural** | chapter function/scene order/reveal/hook changes | remove fight, delay reveal, replace climax | Chapter Director/Editor + chapter-plan/revision checks |
| **L3 Arc/Volume Future** | material change to future trajectory | change an Arc outcome, relationship stage, major reveal timing | Plot Doctor/Story Architect → semantic PlanChange + impact/requalification |
| **L4 Book/Canon Critical** | foundational or accepted-history-sensitive change | world rule, core reader promise, ending, major identity/fate | explicit high-risk governance; future replan or retcon/corrective workflow |

A provider or UI must not infer that a locally selected paragraph grants authority to make an L3/L4 change.

### 10.2 Draft, accepted, and published boundaries

- **Draft/revision:** freely revisionable within scope, with versioned evidence where required.
- **Accepted but not yet published:** never mutated in place. Any correction creates governed superseding/corrective lineage and must re-evaluate affected Canon/State/Quality before becoming current.
- **Published:** treated as locked history for ordinary editing. Corrections require explicit retcon/correction semantics and may only affect future design unless the product/platform explicitly supports a governed publication correction.

The normal author-editing UX should therefore keep Chapter Editor interaction before final acceptance whenever possible.

### 10.3 Author Intent

Author Intent records why a deliberate choice exists and what scope it should influence. Examples include intentional temporary weakness, delayed payoff, tonal restraint, or a future thematic contrast.

Canonical guidance:

- represent Author Intent as versioned future design evidence using the existing `FUTURE_INTENT` narrative layer and/or existing Story/Book/Planning assets when semantically sufficient;
- project task-relevant intent into Context;
- preserve rationale for Quality/replan where necessary;
- do **not** create an `AuthorIntentAuthority` by default.

### 10.4 What-if scenario branches

A useful P1 capability is governed scenario exploration:

```text
Canonical State + Active Future Design
→ isolated Scenario Branch
→ simulated alternative(s)
→ impact / quality comparison
→ merge proposal or discard
```

Scenario output is never Canon and cannot mutate active planning without the normal decision/change protocol.

---

## 11. Domain and Authority model

### 11.1 Authority classes

Long-lived canonical ownership remains with existing domain boundaries, including:

- Project / Book identity and production state;
- Story / Book Design;
- hierarchical/narrative Planning and active bindings;
- PlanChange / Replan;
- Canon and accepted chapter lineage;
- Narrative Events and current Narrative State projection;
- Source Authority and MKAOS knowledge assets;
- Chapter / Book production;
- Quality / Reader evidence where owned by current modules.

Do not create one Authority per literary noun.

### 11.2 Narrative truth classes

| Artifact/state | Authority meaning |
|---|---|
| Conversation transcript | evidence / interaction history, non-authoritative |
| Creative seed / material | candidate input, non-authoritative |
| Agent proposal | candidate, non-authoritative |
| Provider output | execution evidence, non-authoritative |
| Future intent / plan | authoritative future design version when activated, but not story truth |
| Draft / revision | content candidate, non-authoritative until acceptance |
| Quality result | evaluation evidence, not Canon |
| Accepted Narrative Event | authoritative evidence of accepted story transition |
| Canon | accepted story truth |
| Current Narrative State | rebuildable authoritative projection over accepted lineage |
| Reader outcome | observed evidence, not story truth |
| MKAOS asset | authoritative reusable knowledge/method asset, not story truth |

### 11.3 Versioning and lineage

Important design and narrative changes use immutable/versioned assets plus active bindings or accepted pointers. Avoid in-place mutation where it would destroy auditability.

Current materialized state should coexist with append-only accepted evidence sufficient for deterministic rebuild; this does not mandate a whole-platform Event Sourcing framework.

---

## 12. Data architecture

### 12.1 Authoritative relational data

PostgreSQL owns business state such as:

- Projects/Books and production state;
- design candidates, versions, qualification receipts, approvals, and active bindings;
- plans, dependencies, PlanChange/Replan decisions;
- Chapter production state and accepted lineage;
- Canon, accepted Narrative Events, current Narrative State, temporal cursors;
- Command Kernel Operation/Attempt/ExternalEffect/RuntimeJob state;
- Agent definitions/collaboration state where production-owned;
- quality, reader evidence, trace identity, and durable receipts.

### 12.2 Large artifacts

Raw sources, large provider payloads, snapshots, exports, reports, or other large immutable artifacts may live in object storage. PostgreSQL retains authoritative locator, hash, version, ownership, and provenance.

### 12.3 Derived read models

Embeddings, vector indices, search indices, caches, semantic projections, and materialized reports are rebuildable read models. They may accelerate retrieval but never become the only copy of accepted business truth.

### 12.4 Ephemeral data

Streaming tokens, temporary tool results, transient rendering state, and scratch reasoning may be ephemeral. Anything required for acceptance, retry/recovery, audit, or exact input provenance must cross a durable boundary.

---

## 13. Context, Memory, and Knowledge architecture

“Memory” is not one database or one Agent feature. Novel Forge distinguishes four memory classes.

### 13.1 Authority memory

Accepted Canon, Narrative State, active future design, decisions, and lineage in PostgreSQL. This is durable business memory and the only class that may define what the system currently believes is authoritative.

### 13.2 Working memory

The frozen/reproducible task-specific Context view for one execution. It contains Minimum Sufficient Context and is bounded by the capability contract.

### 13.3 Episodic interaction evidence

Conversation/collaboration history, rejected alternatives, human rationale, and decision provenance. It may support later retrieval or audit but is **not** automatically injected into prompts and is not Narrative Authority.

### 13.4 Retrieval memory

Embeddings/search projections over approved sources, past artifacts, or narrative evidence. It is derived, permissioned, freshness-aware, and rebuildable.

### 13.5 MKAOS knowledge

MKAOS is reusable methodology/professional knowledge, not per-Book episodic memory and not a prompt warehouse. Capabilities retrieve only relevant governed knowledge assets.

### 13.6 Minimum Sufficient Context

Each capability defines `MUST_INCLUDE`, `OPTIONAL`, and `MUST_EXCLUDE` classes. Context correctness should detect or measure at least:

- `NO_FUTURE_FACT`;
- `NO_HIDDEN_KNOWLEDGE_LEAK`;
- `NO_STALE_VERSION`;
- `NO_DUPLICATE_SEMANTIC_REPRESENTATION`;
- `NO_IRRELEVANT_FULL_ASSET`;
- `REQUIRED_LONG_DISTANCE_FACT_PRESENT`;
- task-relevant Author Intent present when required;
- pending proposal not mistaken for accepted state.

Persisted evidence is not automatically provider input.

---

## 14. Canonical runtimes

Novel Forge has several business flows but **one execution plane**.

### 14.1 Creative collaboration runtime

```text
Human request / selected text / creative seed
→ scoped collaboration session
→ frozen Agent/Context/knowledge permissions
→ governed capability/provider execution
→ proposal / alternative / diagnosis
→ decision capture
→ semantic diff + impact/risk when applicable
→ human/policy decision
→ owning Domain Authority command
→ versioned design/revision/plan state
```

Human turns may be synchronous from the product perspective, but any provider/tool work requiring durable recovery uses the same governed Operation/Attempt/ExternalEffect semantics as other production work.

### 14.2 Progressive design runtime

```text
Story Intent
→ Story Foundation
→ Book Architecture
→ Volume Portfolio
→ Arc Graph
→ Character/World Realization
→ Disclosure/Obligations
→ Scheduling
→ Chapter Execution Plan
→ Scene Architecture
→ deterministic + semantic qualification
→ production admission
```

An upstream layer that is stale, superseded, unqualified, or not current cannot silently become a production dependency.

### 14.3 Chapter production runtime

```text
Current accepted state + qualified active future design
→ Chapter admission
→ Context Compiler
→ Provider
→ Draft
→ Review / author edit / Revision / Re-review
→ Narrative Event extraction
→ deterministic correctness
→ Canon / State candidate
→ Quality
→ Book/Chapter acceptance transaction
→ Accepted Chapter + Canon/State cursor
```

A successful model call is never equivalent to an accepted Chapter.

### 14.4 Feedback runtime

```text
Accepted Chapter
→ Publication effect
→ Reader Outcome / observations
→ attribution / calibration
→ recap / drift / ending reachability / debt
→ governed replan proposal
→ impact + approval
→ minimal future invalidation / regeneration / requalification
```

---

## 15. Core workflows

### 15.1 New Book discovery

1. Create/select Project and Book scope.
2. Author discusses premise/reader/genre/theme with Chief Editor or specialists.
3. System produces explicit alternatives and assumptions, not hidden commitment.
4. Accepted decisions become Story/Book Design candidates.
5. Independent validation/evaluation qualifies design before activation.
6. Active Book baseline becomes input to progressive planning.

### 15.2 World or character redesign

1. Load current scope/version.
2. Discuss alternatives with World Architect or Character Director.
3. Produce proposed semantic changes and rationale.
4. Analyze affected future plans, hard constraints, and any conflict with accepted history.
5. Low-risk future design may follow configured approval; high-risk change requires explicit human decision.
6. Commit through owning design/planning Authority and requalify affected downstream assets.

### 15.3 Material / idea integration

```text
Raw Material / Idea
→ Creative Seed
→ research / provenance / transformation
→ compatibility analysis
→ placement recommendation
→ Narrative proposal
→ human decision
→ active plan/design version
→ eventual prose
→ acceptance / Canon
```

Material, idea, proposal, plan, draft, accepted story, and Canon are distinct lifecycle states.

### 15.4 Chapter generation and edit

1. Generate/admit Chapter plan and Scene architecture.
2. Build bounded Context.
3. Generate Draft.
4. Author may enter Chapter Editor at whole-Chapter, Scene, paragraph, or selected-text scope.
5. Change is classified L0–L4.
6. L0/L1 remain local if semantic checks confirm bounded impact.
7. L2 invokes chapter structural planning/revision checks.
8. L3/L4 escalates to PlanChange/Design governance rather than silently rewriting the Draft.
9. Revised content is re-reviewed/re-evaluated as required.
10. Only final accepted lineage updates Canon/State.

### 15.5 Long-form retrospective

Run at rolling chapter windows and meaningful Segment/Volume/Book boundaries. Inspect at least:

- Arc dormancy/cadence/convergence;
- character trajectory and disappearance;
- world expansion and realization;
- obligation/payoff debt;
- repeated scene/chapter structure;
- reader promise/reward cadence;
- theme drift and Author Intent drift;
- context growth and retrieval quality;
- correction/replan frequency.

Retrospective produces evidence and proposals, not direct mutation.

---

## 16. Quality, Judge, and evaluation architecture

### 16.1 Three quality classes

1. **Narrative Correctness** — Canon, state, chronology, knowledge, resources, identity, hard world rules, obligations, causal transitions, spatial feasibility where deterministic.
2. **Narrative Quality** — story structure, character depth, conflict, pacing, worldbuilding, mystery, theme, prose, style, scene effectiveness.
3. **Reader / Commercial Quality** — reader promise, hooks, reward cadence, serialization, platform fit, fatigue, readability.

Do not collapse these into one opaque number.

### 16.2 Independent semantic evaluation

A Generator must not be the sole evaluator that mints its own PASS.

Target trust boundary:

```text
Candidate Generation Operation
→ immutable candidate/content hash
→ independent Semantic Evaluation Operation
→ qualification evidence
→ repair / approval / activation
```

### 16.3 Judge vs Editor

- **Quality Judge:** reproducible evaluation role, evidence-oriented, protected from conversational persuasion.
- **Quality Editor:** conversational role that explains findings, discusses intent, and proposes repairs.

If the author supplies missing rationale, that rationale becomes evidence/intent and a new evaluation may be run. The Judge score is not manually edited because the author disagrees.

### 16.4 Multi-scale quality

Quality operates at Scene, Chapter, Segment, Arc, Volume, Book, and rolling longitudinal windows. A Chapter-only Judge cannot detect long-range drift.

### 16.5 Human override

Where policy allows, the author/operator can accept despite warnings. Override must record actor, rationale, exact state/version, findings, and downstream implications.

---

## 17. Reliability, retry, recovery, and replay

### 17.1 One execution kernel

All durable provider/tool work reuses the current production execution semantics:

```text
Command
→ Operation
→ Attempt
→ Lease / Fence
→ ExternalEffect
→ Provider / Tool
→ Receipt
→ Domain Commit
```

`RuntimeJob` remains the durable worker scheduling/execution primitive where used. Do not introduce a second `WorkOrder` model merely for creative chat.

### 17.2 Technical retry vs semantic revision

- **Technical retry:** same frozen logical task after timeout, temporary provider failure, network failure, or other retryable infrastructure issue; recorded as another governed Attempt/effect according to policy.
- **Semantic revision:** previous output was validly produced but failed quality/design intent; this is a business workflow and produces a revision, not a retry disguise.

### 17.3 Idempotency

Protect against duplicate:

- provider/tool side effects;
- AssetVersions;
- collaboration decisions;
- qualification receipts;
- Narrative Events;
- Chapter acceptance;
- Canon/State transitions;
- plan activation;
- publishing effects.

### 17.4 Recovery

Restart/resume is driven by durable Operation/Attempt/RuntimeJob/effect/Authority state. Leases and fence tokens prevent stale workers from committing after ownership transfer.

### 17.5 Replay

Distinguish:

- **Exact evidence replay:** reuse immutable recorded provider/tool result where policy permits.
- **Logical replay:** freeze the same Authority versions, context/capability/prompt/provider policy and invoke again; token-identical output is not guaranteed.

All replay needs provenance.

### 17.6 Concurrency

Use existing optimistic version/CAS and lease/fence patterns where relevant. Narrative or plan commits must reject stale expected versions instead of last-writer-wins mutation.

---

## 18. Governance, observability, cost, and operations

### 18.1 Governance

Governance covers:

- candidate/decision/activation/supersession;
- independent semantic qualification;
- Agent scope and tool permissions;
- human decision and high-risk escalation;
- PlanChange/replan/retcon policy;
- quality gates and override evidence;
- production admission.

Agent → direct SQL → Canon is forbidden.

### 18.2 Trace and inspection

A production result should be traceable across:

```text
Project / Book
→ Narrative Scope
→ design/state versions
→ Command / Operation / RuntimeJob / Attempt
→ Agent / Capability / Skill / Capability Pack
→ Context snapshot / knowledge selection
→ Provider / Tool effect
→ review / quality / decision
→ Domain commit / accepted lineage
```

A Runtime Inspector should eventually answer: what is running, waiting, failed, paused, stale, unqualified, or pending human decision, and why.

### 18.3 Metrics

Traditional metrics include latency, success/failure, retries, lease/fence health, DB health, provider latency, token usage, and cost.

Narrative operations additionally benefit from:

- active/dormant Arcs;
- open/overdue obligations;
- character appearance gaps;
- world expansion and realization rate;
- Narrative Load;
- reveal/payoff density;
- hook similarity;
- Canon correction rate;
- replan frequency;
- selected-context vs provider-input tokens;
- Prompt Amplification Ratio;
- Context Growth Slope;
- provider calls / accepted Chapter;
- wall time / accepted Chapter;
- author intervention/revision frequency by change level.

### 18.4 Cost governance

Cost evidence should be attributable by Book, Chapter, capability, provider, and workflow. Budget policies may later control per-Book/per-Chapter/per-capability spend without becoming a second scheduler.

---

## 19. Security and external boundaries

- Provider access goes through the governed Provider Gateway.
- Tools are default-deny and Capability/Agent-scope controlled.
- Secrets never enter Narrative State or ordinary provider Context.
- External sources are untrusted input; prompt injection must not alter system policy, tool permissions, or Authority semantics.
- Source provenance, snapshot/content hash, classification/methodology, license/eligibility where relevant, and derived lineage are preserved.
- MKAOS/source retrieval must prevent raw source leakage into prose contexts when disallowed.
- Workspace/project/book boundaries must be explicit enough for future multi-user/multi-book isolation.
- External publishing and human-reader data are explicit integrations with durable effect/evidence semantics.

---

## 20. Testing, qualification, and Production Admission

### 20.1 Engineering completion dimensions

Every implementation report must distinguish:

- `CODE_IMPLEMENTED` — code/schema/contracts exist;
- `CANONICAL_WIRED` — reachable through current production composition/entry path and owning Authority;
- `TEST_EXECUTED` — named tests actually ran against the pinned SHA;
- `RUNTIME_PROVEN` — the relevant real runtime composition/effects were exercised with recorded evidence;
- `PRODUCTION_QUALIFIED` — required admission campaign, operating environment, and production evidence passed.

These are dimensions, not replacements for the repository's more specific proof ladder:

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

For example, `TEST_EXECUTED` does not imply `REAL_PROVIDER_PROVEN`, and `WIRED` does not imply `LONGFORM_PROVEN`.

### 20.2 Test layers

Required according to capability risk:

- Unit/domain tests;
- contract tests;
- architecture/boundary tests;
- PostgreSQL integration tests;
- runtime composition tests;
- migration fresh-install and upgrade proof;
- retry/recovery/replay tests;
- real-provider proof;
- design-only E2E;
- stateful Chapter 1–5 proof;
- 30/100/300 Chapter long-form proofs;
- reader/effectiveness evaluation;
- multi-book isolation/scale proof;
- backup/restore and operational drills.

### 20.3 Long-form proof

Long-form qualification must exercise more than prose generation. It should prove:

- accepted-only state propagation;
- character/world/knowledge temporal correctness;
- Arc cadence and obligations;
- Context correctness and bounded growth;
- author change / PlanChange / replan behavior;
- pause/resume/recovery;
- Canon and accepted-lineage rebuild;
- real-provider failure accounting;
- longitudinal quality signals.

### 20.4 Production Admission

A representative admission sequence is:

```text
Clean pinned main / release SHA
→ Full Engineering Qualification
→ Fresh migration proof
→ Upgrade migration proof
→ PostgreSQL integration
→ provider/runtime proof
→ retry/recovery/replay proof
→ long-form correctness proof
→ backup/restore + security/ops review
→ multi-book proof when multi-book is in scope
→ Production Admission
```

No lower evidence class is automatically promoted.

---

## 21. Current implementation reality and gap policy

At the 2026-08-15 design convergence baseline, the repository already contains a substantial governed spine: Command Kernel, PostgreSQL Authorities, Provider/production execution composition, Chapter production, Story/Book Design, hierarchical planning, Narrative State, PlanChange/Replan, Agent Collaboration/Runtime, Source/MKAOS, quality/reader modules, publishing surfaces, and recovery/qualification infrastructure.

The target design therefore **extends and converges existing systems** rather than rebuilding them.

The following are design-priority gaps to verify against the latest code before implementation. A code review may find some partially or fully implemented; no item is considered missing merely because this document lists it.

### P0 — must close for the target product

1. **Human conversational collaboration lifecycle:** explicit author interaction over existing Agent Collaboration, including durable/recoverable decision capture where needed.
2. **Conversational role profiles:** Chief Editor and the core specialist roles expressed through existing AgentDefinition/capability contracts, not parallel runtime classes.
3. **Conversation Context Contract:** selected-text/entity scope, state/design cursor, intent, pending proposals, and knowledge visibility bound to provider work.
4. **Narrative Change integration:** L0–L4 classification and routing across Revision, PlanChange, owning Design Authorities, and corrective/retcon boundaries without a second change engine.
5. **Chapter Editor canonical path:** author post-draft edits remain inside revision/review/correctness/quality/acceptance lineage.
6. **Author Intent semantics:** future-intent/rationale projection sufficient for Context and Quality without creating another Authority by default.
7. **Independent semantic qualification trust:** generation and qualification evidence remain independently attributable and immutable.
8. **Context correctness and minimum-sufficient retrieval:** especially stale/future/hidden/pending-proposal separation.
9. **Exact-SHA Engineering Qualification of the current long-form runtime**, including fresh/upgrade migration and PostgreSQL integration.
10. **Real-provider production composition and failure semantics proof.**
11. **Stateful long-form correctness proof** rather than fixture-only claims.

### P1 — should close after the P0 collaboration/runtime seam

- governed What-if / Scenario Branch exploration;
- Runtime Inspector for human/Agent pending decisions and failed/stale work;
- stronger longitudinal quality and Narrative Operations reports;
- spatial/travel consistency where stories require it;
- reader outcome/attribution/calibration closure through governed replan;
- explicit serialization/style projections where current contracts are insufficient;
- real Author Intent drift and intervention analytics.

### P2 — later enhancement

- advanced Reader Simulator;
- automatic pacing/Arc portfolio optimization;
- Scene-level execution plane if operational evidence requires it;
- adaptive chapter length;
- multi-model routing/optimization;
- cross-book shared-universe governance;
- multi-book portfolio scheduling and cost optimization.

### Explicitly deferred / not required now

- new microservice per literary concept;
- free-form Agent mesh;
- full event-sourcing rewrite;
- independent vector-memory Authority;
- second execution/change/workflow engine;
- fully autonomous external publishing.

---

## 22. Target architecture

The completed system should behave as follows:

```text
SOURCE / RESEARCH / MKAOS
            │
            ├──────────────────────────────┐
            │                              │
            ▼                              ▼
   HUMAN CREATIVE INTENT          NARRATIVE INTELLIGENCE
            │                              │
            └─────────────┬────────────────┘
                          ▼
             CONVERSATIONAL CREATIVE STUDIO
          Chief Editor / specialist direct entry
                          │
                          ▼
             PROPOSAL / DIFF / IMPACT / DECISION
                          │
                          ▼
              ACTIVE FUTURE DESIGN AUTHORITY
                          │
                          ▼
   BOOK → VOLUME → SEGMENT → CHAPTER → SCENE
          + ORTHOGONAL ARC GRAPH / OBLIGATIONS
                          │
                          ▼
               LONGFORM_DESIGN_QUALIFIED
                          │
                          ▼
                 CURRENT ACCEPTED STATE
                          │
                          ▼
              CHAPTER_PRODUCTION_ADMITTED
                          │
                          ▼
                   CONTEXT COMPILER
                          │
                          ▼
                       PROVIDER
                          │
                          ▼
                        DRAFT
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
       CHAPTER EDITOR              REVIEW/JUDGE
              │                       │
              └───────────┬───────────┘
                          ▼
                       REVISION
                          │
                          ▼
           CORRECTNESS / EVENT EXTRACTION
                          │
                          ▼
              CANON / STATE PROJECTION
                          │
                          ▼
                        QUALITY
                          │
                          ▼
                  ACCEPTED LINEAGE
                          │
                          ▼
               PUBLISH → OBSERVE
                          │
                          ▼
             READER OUTCOME / RETROSPECTIVE
                          │
                          ▼
                 GOVERNED ADAPTATION
                          └──────────────→ future design
```

The system is autonomous only inside these governed boundaries. Human intervention and autonomous production use the same state, execution, quality, and recovery semantics.

---

## 23. Implementation roadmap

The roadmap follows actual dependency order and assumes the existing long-form runtime is retained.

### Phase 0 — Current-code truth and contract freeze

- pin latest `main` SHA;
- run code/doc/manifests/migration inventory;
- prove which canonical long-form P0 items are already implemented/wired;
- remove only real dead/legacy/AI residue;
- freeze/clarify the cross-domain contracts needed for human collaboration; do not redesign the production kernel.

### Phase 1 — Conversational collaboration closure

- extend existing Agent Collaboration for explicit human creative interaction where gaps exist;
- define canonical role profiles through AgentDefinition/capabilities;
- bind Conversation Context Contract;
- implement decision capture and Author Intent semantics;
- prove Agent output cannot bypass owning Authority.

### Phase 2 — Chapter Editor + Narrative Change integration

- make selected-text/Scene/Chapter editing a first-class governed revision path;
- implement L0–L4 classification/escalation;
- reuse PlanChange and owning Design Authorities for structural changes;
- prove accepted/published boundaries and corrective lineage.

### Phase 3 — Context / knowledge / long-form semantic closure

- make intent, pending proposals, temporal knowledge, MKAOS selection, and accepted state correctly separable in Context;
- close remaining independent semantic evaluation, dependency/replan, load/debt, progressive realization, and longitudinal-quality gaps demonstrated by current code review.

### Phase 4 — Full Engineering Qualification

- fresh + upgrade migrations;
- full PostgreSQL integration;
- architecture/contract/unit/integration suites;
- recovery/retry/replay;
- provider/tool/Capability Pack validation;
- clean worktree and exact-SHA evidence.

### Phase 5 — Real-provider Chapter 1–5 proof

Prove provider invocation, failure accounting, Context correctness, Agent/change semantics, Event→State, acceptance, pause/resume, and bounded provider input.

### Phase 6 — 30 / 100 / 300 Chapter proofs

Progressively prove long-distance continuity, Arc persistence, world/character development, obligations, replan, Narrative Debt, bounded Context, recovery, and operational feasibility.

### Phase 7 — Publish / reader feedback closure

Connect real publication outcomes to attribution, retrospective, calibration, and governed adaptation without allowing outcome data to rewrite Canon.

### Phase 8 — Multi-book and production scale

Only after single-book proof: isolation, scheduler/portfolio, budgets, scale, backup/restore, operational SLOs, external publishing automation, and Production Admission.

### Phase 9 — Optimization

Only after correctness and real usage evidence: multi-model strategy, advanced reader simulation, automatic pacing/portfolio optimization, and other data-driven improvements.

---

## 24. Final architectural position

Novel Forge is not “many Agents writing a novel.” It is a governed creative operating system in which:

```text
Human Creative Intent
        ↕
Conversational Creative Studio
        ↕
Specialized Agent Roles + Capabilities
        ↓
Proposal / Decision / Narrative Change Protocol
        ↓
Versioned Future Design + Canonical Narrative Authority
        ↓
Progressive Planning + Minimum Sufficient Context
        ↓
Governed Provider / Chapter Production
        ↓
Correctness + Quality + Accepted Lineage
        ↓
Publish / Observe / Learn / Governed Adaptation
```

The defining engineering property is not that a model can generate a chapter. It is that the same architecture can preserve creative intent, causal story truth, character/world development, knowledge boundaries, long-range obligations, author intervention, quality, recovery, and auditability while a Book grows to million-word scale — and can prove that behavior at a pinned runtime version before production admission.
