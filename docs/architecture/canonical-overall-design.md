# Novel Forge / Autonomous Novel OS — Canonical Overall Design

> **Status:** Canonical target architecture baseline  
> **Normative role:** single source of truth for the intended final product and architecture  
> **Evidence rule:** source code, migrations, executable composition, tests, and pinned runtime evidence define what exists today. This document defines what the system should converge toward; it never upgrades implementation proof.

## 0. Documentation and evidence authority

Novel Forge separates three kinds of truth:

1. **Accepted story truth** — accepted chapter lineage, Canon, accepted Narrative Events, and current Narrative State.
2. **Target architecture truth** — this document.
3. **Current implementation truth** — executable code and pinned evidence, which outrank prose when judging present capability.

ADRs may refine implementation decisions but must not create a second target architecture. Product/operations/development documents are derived views. A design concept is not `IMPLEMENTED`; code is not `RUNTIME_PROVEN`; a passing fixture is not `LONGFORM_PROVEN`.

---

## 1. Vision

Novel Forge is an **Industrial Autonomous Novel OS**: a governed Human-AI long-form narrative operating system able to design, produce, evaluate, recover, audit, and continuously improve high-quality serial fiction over hundreds or thousands of chapters.

It is not a prompt chain, chapter generator, chat memory system, or free-form multi-Agent demo. The system must remain correct while the manuscript grows, while plans change, while providers fail, and while production continues without continuous human supervision.

The defining model is:

```text
S(n) + governed future intent
→ bounded chapter production
→ AcceptedChapterOutcome(n+1)
→ Canon + NarrativeState(n+1)
→ future-only planning evolution
```

The system first determines **what the next chapter must accomplish and what is currently true**; generative models decide **how to express the authorized transformation as effective prose**.

---

## 2. Goals

Novel Forge must eventually provide:

- high-quality long-form story design and prose production;
- reliable continuity over 300–1000+ chapters;
- explicit character, relationship, world, information, resource, mystery, promise, payoff, theme, and Arc progression;
- progressive planning rather than prematurely detailing the whole book;
- bounded task-specific context whose size is driven by the current task, not total manuscript length;
- reusable source-derived narrative/professional intelligence without copying source-specific expression or plots;
- specialized Agents for creative reasoning without giving Agents business Authority;
- independent review, correctness verification, quality evaluation, and governed revision;
- accepted-only Canon/Narrative State propagation;
- autonomous Chapter-to-Chapter forward progress with bounded blocking semantics;
- idempotent, recoverable, replayable, observable provider/runtime execution;
- real reader feedback and governed adaptation without retroactively corrupting accepted history;
- future multi-book scheduling and portfolio operation after single-book correctness is proven.

## 3. Non-goals

The target architecture does not require:

- one Agent/service/Authority per literary concept or narrative level;
- a second workflow/runtime/state plane for Agent collaboration, Arc planning, or chat;
- Agent-owned private memory as story truth;
- a graph database merely because Arc relationships form a graph;
- a pure event-sourcing rewrite of the platform;
- full detailed planning of hundreds of future chapters before Chapter 1;
- permanent blocking of chapter production on advisory Reader/analytics work;
- automatic mutation of Canon from quality scores or reader feedback;
- a generic abstraction layer without an observed lifecycle/concurrency/recovery need;
- fully autonomous external publishing before explicit Production Admission.

**Production-grade, not Maximum Complexity.**

---

## 4. Architecture principles and invariants

1. PostgreSQL is the production business Source of Truth.
2. Agents, models, prompts, chats, drafts, retrieval results, and MKAOS assets are never Story Authority.
3. **Agents propose; owning Authorities commit.**
4. Planning is future intent; accepted lineage is reality.
5. Only an accepted outcome can advance Canon or current Narrative State.
6. Accepted history is immutable; corrections create governed superseding/corrective lineage.
7. Narrative State is a deterministic/rebuildable current projection over accepted evidence.
8. Structural time hierarchy and Arc graph are orthogonal.
9. Context is a derived execution view, never Authority.
10. Provider input is **Minimum Sufficient Context**, not a dump of everything known.
11. Character knowledge, character belief, reader knowledge, story truth, and presentation are separate.
12. Stable Character/World design definitions and temporal Narrative State are separate.
13. MKAOS owns reusable knowledge/method intelligence, not story truth or planning Authority.
14. Deterministic constraints stay deterministic; LLM Judges are used only for semantic evaluation.
15. Technical retry and semantic revision are distinct.
16. One production execution plane serves Chapter, Book, Agent, Source, MKAOS, Planning, Quality, and follow-up work.
17. No advisory/observational operation may block Chapter N+1 unless an explicit persisted governance decision marks it `HARD_BLOCKING`.
18. Every nonterminal production state must be claimable, explainable, recoverable, or explicitly waiting on a durable external/human condition.
19. Long-form planning evolves future-only; accepted history is never rewritten to make a plan look correct.
20. Scale follows proof: single-book liveness/correctness/quality before multi-book optimization.

---

## 5. Business architecture

Novel Forge is organized around six connected loops.

### 5.1 Discover and design

```text
Human Intent / Material / Question
→ Story Intelligence
→ Story Foundation / Book Design
→ World + Character Design
→ Narrative Threads / transformation directions
→ strategic future design
```

### 5.2 Progressive long-form planning

```text
Book Design + Current Accepted State
→ Volume / Narrative Segment planning
→ Narrative Arc Network
→ active Arc working set
→ Chapter Arc Contributions
→ Chapter Mission
→ Scene architecture
```

### 5.3 Chapter production

```text
Chapter Mission + Current Narrative State
→ Evidence Enrichment
→ Chapter Production Packet
→ Scene Plan
→ Draft
→ Editorial Diagnosis
→ Revision
→ Prose Polish
→ Narrative Verification
→ Quality Decision
→ ACCEPT
```

### 5.4 Accepted outcome

```text
Accepted Chapter
→ AcceptedChapterOutcome
→ Canon Events / NarrativeState transitions
→ Arc Progress Evidence
→ accepted lineage / retrieval projections
→ next-chapter eligibility
```

Acceptance is internal story governance. External publication is a later side effect.

### 5.5 Publish / observe / learn / adapt

```text
Accepted Chapter
→ Publish
→ Reader Outcome / operational observations
→ Attribution / calibration / retrospective
→ adaptation or replan proposal
→ future-only governance
```

### 5.6 Source / knowledge intelligence

```text
Source
→ governed import / rights / provenance
→ source-specific deconstruction
→ observations
→ abstraction / cross-source generalization
→ MKAOS Narrative & Domain Intelligence
→ governed selection
→ planning/context usage evidence
→ effectiveness feedback
```

---

## 6. Capability architecture

Capabilities are organized by responsibility, not Agent count.

```text
Creative Interaction
├ conversation / selected scope / decision capture
├ semantic proposal / impact analysis
└ author editing / approval

Story Intelligence
├ topic / genre / premise / differentiation
├ reader positioning / commercial logic
└ story potential / ending direction

Narrative Design
├ Story Foundation / Book Architecture
├ World / Character / Relationship design
├ Narrative Threads / transformation maps
├ Narrative Arc OS
├ Volume / Narrative Segment design
├ disclosure / obligations / payoff design
└ progressive scheduling

Narrative Execution
├ Chapter Mission
├ bounded Context / Evidence Compiler
├ Scene composition
├ prose generation
├ diagnosis / revision / polish
└ narrative verification

Narrative Authority
├ Accepted Chapter lineage
├ Canon / Narrative Events
├ Narrative State / temporal query
├ active future plan bindings
└ governed PlanChange / Replan

Knowledge
├ Source Intelligence
├ MKAOS Narrative Intelligence
├ professional/domain knowledge
└ retrieval projections

Quality
├ deterministic correctness
├ independent semantic evaluation
├ prose / character / world / structural quality
├ reader / commercial quality
└ longitudinal quality

Platform & Governance
├ Command Kernel / RuntimeJob
├ Provider Runtime / external effects
├ Agent Runtime / Collaboration
├ PostgreSQL Authority / object artifacts
├ trace / metrics / cost
├ retry / recovery / replay
├ qualification / admission
└ security / policy
```

---

## 7. System architecture

Use six logical planes over one execution foundation:

```text
1. Creative Interaction Plane
   Human / Novel IDE / Chief Editor / specialist roles

2. Narrative Intelligence & Design Plane
   Story / World / Character / Threads / Arc / Planning / MKAOS intelligence

3. Narrative Authority Plane
   active design + plan bindings / accepted lineage / Canon / Narrative State

4. Context & Knowledge Plane
   Source / MKAOS / retrieval / context compilation

5. Production Execution Plane
   Command / Operation / Attempt / RuntimeJob / Provider / Quality / persistence

6. Observation & Governance Plane
   trace / cost / reader outcome / retrospective / qualification / admission
```

These are responsibility boundaries, not a requirement for six services.

---

## 8. Domain, Authority, and State

### 8.1 Story truth classes

| Object | Meaning |
|---|---|
| Stable Book/World/Character design | approved design definitions and constraints |
| Future Plan / Arc intent | desired future transformation; never accepted reality |
| Draft / Revision | candidate prose |
| Accepted Chapter | immutable accepted text/version |
| AcceptedChapterOutcome | immutable accepted semantic outcome of one chapter |
| Canon Event / Narrative Event | accepted evidence of what happened or became true |
| Narrative State | current accepted truth projected from accepted evidence |
| Summary / Recap / Embedding / Index | derived and rebuildable |
| Reader / Quality observation | evidence, not story truth |

### 8.2 Authority boundaries

Long-lived ownership should remain with the smallest existing domain that owns a real lifecycle. Do not create one Authority per literary noun.

Canonical ownership includes:

- Project / Book identity and production lifecycle;
- Book/Story Design;
- Planning / active bindings / PlanChange / Replan;
- Chapter/Book acceptance and accepted lineage;
- Canon / Narrative Event / Narrative State projection;
- Source/MKAOS governance;
- Quality/Reader evidence where existing domains own the lifecycle;
- production execution state and durable external effects.

### 8.3 State categories

Keep distinct:

- **Design state:** stable intended definitions.
- **Future planning state:** desired transformations and scheduling.
- **Accepted narrative state:** current story truth.
- **Execution state:** Operation/Attempt/RuntimeJob/lease/retry/checkpoint.
- **Observation state:** quality, reader, analytics, retrospective evidence.

No category silently promotes itself into another.

---

## 9. Agent / Capability / Skill / Tool / Workflow / Authority architecture

### 9.1 Definitions

- **Autonomous Agent:** a bounded, governed reasoning actor that decomposes goals, observes tool results, and may adapt its next step across multiple turns. It produces typed candidates/proposals and never owns story truth.
- **Conversational Role:** stable user-facing persona backed by AgentDefinition, capabilities, context/tool policy, and budget.
- **Typed Capability:** one semantic callable task contract that produces an immutable candidate/evidence artifact. A model-backed task is not an Agent merely because it reasons internally.
- **Skill:** versioned method/procedure — how a capability is performed.
- **Tool:** a typed read query, Capability invocation, or Authority Command submission endpoint exposed under a frozen permission policy.
- **Capability Pack:** immutable deployment binding of compatible capability, Skill, prompt, provider/model route, tools, context policy, evaluation policy, budget, and approval constraints.
- **Domain Service:** deterministic validation, reduction, comparison, diff, scheduling or projection logic.
- **Workflow:** explicit durable transitions deciding when bounded work executes and how it recovers.
- **Authority:** the sole boundary allowed to validate and commit its business state.
- **Rule:** deterministic constraint.
- **Template:** structured scaffold.
- **Knowledge Asset:** governed reusable external/generalized knowledge.

### 9.2 Agent responsibilities

Autonomous Agents are justified only when a task needs goal decomposition, multi-step reasoning, dynamic Tool choice, observation and adaptive replanning. The preferred initial set is small:

- **Studio/Director Agent:** explores goals, queries accepted/design state, invokes typed creative capabilities, and submits Authority Commands.
- **Research/Knowledge Agent:** plans bounded research/retrieval, invokes source/knowledge capabilities, and submits governed knowledge candidates.

Worldbuilding, Character Design, Outline, Chapter Planning, Draft, Review, Revision, Provisional Canon Extraction and Quality Judge are normally Typed Capabilities. They do not become Agents simply because an LLM executes them.

Authorities retain:

- accepted-state mutations;
- plan activation/supersession;
- Canon commit;
- leases/fences/retry ownership;
- budgets/admission;
- publication policy.

Do not create `BookAgent / VolumeAgent / ArcAgent / ChapterAgent / SceneAgent` families merely to mirror hierarchy.

### 9.3 Unified Agent Harness

The Harness executes inside the existing durable plane:

```text
RuntimeJob / Operation / Attempt / Lease / Fence
└── Agent Session
    ├── frozen role, Tool policy, Skill bindings and budgets
    ├── append-only transcript events
    ├── model-turn ExternalEffect / Receipt
    ├── Tool observation
    └── next turn / checkpoint / stop / escalation
```

It must support multi-turn resume, dynamic allowlisted Tool selection, Skill id/version/hash provenance, cancellation/deadline checks, token/cost/turn/effect hard stops, committed-request restoration and runtime trace. Skill activation never grants permission. An Agent may query, invoke Capabilities and submit typed Authority Commands; it cannot directly mutate Canon, accepted Narrative State, Arc actuals, Narrative Obligations, active plans or Chapter acceptance.

---

## 10. Novel OS hierarchy and structural narrative architecture

The system has four orthogonal structures rather than one artificial containment tree:

```text
Organization / IP     Studio → Portfolio → Universe → Series → Book
Narrative containment Book → Volume → [Narrative Segment] → Chapter → Scene → Beat
Long-form change      Arc Graph across structural scopes
Production control    ChapterGroup over a Chapter range
```

Organization/IP concepts are formal domain responsibilities, not mandatory Aggregate roots. Studio and Portfolio may remain lightweight workspace/production scopes. Universe or Series receives an independent lifecycle, version, shared Canon boundary or Authority only when real cross-Book consumers require it. Book remains the accepted narrative root.

- **Book:** macro promise, ending reachability, major transformations and constraints.
- **Volume:** major timeline container with entry/exit state, pressure, climax and irreversible change.
- **Narrative Segment:** an optional stable contiguous dramatic interval independent of Arc and ChapterGroup. It enters persistence only after a distinct invariant and production consumer are proven; it must not be introduced merely to complete the tree.
- **Chapter:** publishable and accept/reject business unit.
- **Scene:** addressable/versioned typed child of ChapterPlan and ChapterOutcome. Scene facts become accepted only with their Chapter; Scene has no second Acceptance Authority.
- **Beat:** embedded typed Scene child unless an independent lifecycle/concurrency need is proven.

`ChapterGroup` owns production range, planning coordination, budget, checkpoint and correction window. It is not a Narrative Truth parent and owns no Canon Authority.

---

## 11. Narrative Arc OS

### 11.1 Arc definition

A Narrative Arc is a **bounded desired state transformation under dramatic pressure**. It has an initial state, target state, dramatic question, pressure/conflict, milestones/beats, expected consequences/payoffs, completion criteria, and accepted progress evidence.

Arc is not a structural parent of Chapter. Chapters participate in several Arcs.

The canonical contract family is explicit:

- **ArcPlan:** desired transformation, dependencies, target window, expected contributions and completion criteria.
- **ArcActualState:** current accepted materialized state at an exact Book boundary.
- **ArcProgress:** immutable per-Chapter accepted observation and deterministic deviation accounting.
- **ArcOutcome:** immutable accepted completion/abandonment evidence.
- **ArcCheckpoint:** long-range continue/correct/replan/completion decision evidence.
- **ArcRevision:** future-only PlanChange candidate; it never rewrites accepted progress.

An expected ChapterPlan contribution is never actual evidence. If qualified ChapterOutcome evidence is absent, the observation is explicitly `NOT_OBSERVED`, `NOT_MATERIALIZED` or `UNKNOWN` according to policy. No plan field may be used as an `ACTUAL` fallback.

### 11.2 Scale model

Use separate dimensions:

```text
Narrative Thread          long-lived concern / question / transformation direction
  ↓
Macro / Meso / Micro Arc bounded transformation cycles at different scopes
  ↓
Arc Beat                  concrete progression intent
```

A million-character book may contain tens of Threads, hundreds to roughly a thousand meaningful Arcs, thousands of Arc Beats/obligations, and many thousands of state/scene events. Do not turn every event into an Arc.

### 11.3 Arc type vs scope

`scope` and `type` are independent.

Representative primary types:

- Plot/Conflict;
- Character;
- Relationship;
- World/Faction;
- Mystery/Information;
- Power/Resource;
- Reader Experience/Payoff;
- Theme/Philosophy.

One Arc may have a primary type plus secondary functions/effects. Split two Arcs only when their initial/target states, dramatic questions, lifecycles, payoff, or completion criteria are materially independent.

### 11.4 Arc relation planes

Arc relationships form a semantic graph. Use typed relationship families rather than one vague `related_to`:

- **Structural:** part/refinement/decomposition.
- **Dependency:** requires/enables/blocks/mutual exclusion. The hard dependency subgraph must not deadlock; model it as an acyclic dependency contract where possible.
- **Causal:** causes/triggers/escalates/delays/spawns/invalidates. Important causal transitions should normally be mediated by Accepted Outcome → Narrative State → activation guard, rather than asserting plan-to-plan causality as truth.
- **Temporal:** precedes/follows/overlaps/interleaves/resumes/dormant-during.
- **Conflict:** conflicts/counteracts/undermines/forces-choice.
- **Information:** setup/foreshadow/deepen/misdirect/recontextualize/reveal/payoff/reopen.
- **Thematic:** mirror/contrast/counterpoint/echo/dialectic opposition.
- **Composition:** intersects/converges/shared climax/co-resolves.
- **Evolution:** split/merge/supersede/branch/alternative/reopen/abandon.
- **Reader-experience:** build tension/amplify/delay payoff/release/cooldown/surprise.

Do not materialize every possible relation. Persist relations only when they carry planning, correctness, scheduling, explainability, or creative value.

### 11.5 Narrative Obligation

Promises, mysteries, foreshadowing, open loops, unresolved conflicts, hooks, character commitments, reader expectations, narrative debt and planned payoffs should create a first-class **Narrative Obligation** when they need durable scheduling/accountability.

An Obligation can be created, deepened, partially paid, recontextualized, transferred, rescheduled, resolved, or explicitly abandoned under governance. This is more expressive than encoding every setup/payoff as pairwise Arc edges.

The contract preserves identity/type, introduced accepted boundary/source artifact, status/current development, append-only development history, dependencies, target window, urgency, reader visibility, expected/actual payoff, overdue/stale state, related character/Arc/Volume and resolution evidence. Only accepted ChapterOutcome obligation events advance the authoritative projection. Drafts, Memos, Reviews, Agent messages and provisional extraction remain candidates/evidence.

### 11.6 Arc Bundle and Arc Junction

- **Arc Bundle:** a narrative window in which multiple active Arcs are intentionally composed together.
- **Arc Junction:** a concrete key event where multiple Arcs intersect, climax, diverge, or resolve.

A Bundle reduces planning fragmentation; a Junction expresses multi-function events without a dense pairwise graph.

### 11.7 Arc Effect Footprint

An Arc may forecast effects across character, relationship, world, information, resources, reader experience, and theme. Effect footprints prevent creating duplicate Arcs just because one transformation serves multiple narrative functions.

### 11.8 Planning graph vs realized graph

Keep distinct:

```text
Planned Arc Graph = desired future transformation network
Realized Arc Evidence = what accepted chapters actually achieved
```

If accepted prose creates an unexpected but valuable consequence, the system may propose `SPAWN / SPLIT / MERGE / REPLAN` for future design. It never rewrites accepted history to match the old graph.

Before Book acceptance, model-backed extraction may create provisional Arc evidence bound to the selected immutable candidate. Narrative Correctness qualifies the evidence. The short acceptance transaction runs only deterministic reducers, records ArcProgress/ArcActualState at the accepted boundary, and emits checkpoints/outbox. Retrieval, embedding and semantic evaluation never execute inside that transaction.

### 11.9 Dramatic phase vs runtime status

These are independent:

```text
Dramatic phase: SEED → PRESSURE → ESCALATION → REVERSAL → CRISIS → CLIMAX → PAYOFF → AFTERMATH
Runtime status: SPECULATIVE / PLANNED / READY / ACTIVE / DORMANT / BLOCKED / PAYOFF_READY / COMPLETED / ABANDONED
```

A dormant Arc can already be in an escalation phase.

### 11.10 Arc working set and narrative bandwidth

The complete graph never enters a chapter prompt. The scheduler derives a small working set, then Chapter contributions such as:

```text
PRIMARY     1
SECONDARY   1–3
TOUCH       0–3
DORMANT     everything else
```

These are soft narrative bandwidth constraints, not literary laws. Detect overload, starvation, collision, drift, stale plans, dead ends, payoff debt, reveal debt, and excessive coupling.

### 11.11 Arc production roles

- **Arc Architect:** transforms state-change goals into dramatically viable Arc proposals, optionally using MKAOS Narrative Intelligence.
- **Arc Scheduler:** mostly deterministic/governed selection of what needs attention now.
- **Narrative Composer:** creative synthesis of several Arc contributions into a small number of natural multi-function events.
- **Arc Progress Analyst:** proposes structured evidence of what the accepted chapter actually advanced.

Only accepted outcome/evidence may advance authoritative Arc runtime projections.

---

## 12. Progressive planning

Do not detail 500 chapters up front. Use lazy narrative expansion:

```text
Far future      Thread + strategic transformation anchors
Mid future      Macro/Meso Arc + Volume/Segment direction
Near future     Micro Arc + major beats / next several chapters
Next chapter    Chapter Mission + Scene architecture
```

Future design distinguishes `HARD_CONSTRAINT`, `SOFT_INTENT`, and `OPEN_DESIGN_SPACE`.

Planning can create/extend/split/merge/spawn/supersede/abandon future Arc candidates, but accepted history is immutable. Replan invalidates the smallest affected future dependency closure and requalifies it.

---

## 13. World and Character architecture

### 13.1 Character

```text
Character = Stable Identity + Current Temporal State + Development Trajectory
```

Stable identity may define desire, fear, values, voice, core contradictions, long-term goals and intended development. Current Narrative State owns what is currently true: location, health, knowledge, belief, relationship, reputation, resources, power, status and access.

Character Arc planning expresses desired transformations; only accepted behavioral/state evidence advances reality.

### 13.2 World

Separate:

```text
World Invariants
Structural World Model
Temporal World State
World Knowledge
Visibility / Accessibility
Discovery Frontier
Progressive Realization
```

World consequences should follow:

```text
Action → Consequence → World State Change → Future Constraint
```

Professional/history/economics/politics/military knowledge from MKAOS may supply causal mechanisms; it never becomes world Canon merely because it was retrieved.

---

## 14. Context, Memory, and Knowledge

### 14.1 Narrative Memory layers

```text
L0 Recent Accepted Verbatim Window
L1 Accepted Current Narrative State
L2 Canon Fact Graph
L3 Character / Relationship Timeline
L4 Narrative Obligation Graph
L5 Arc / Long-range Narrative Debt State
L6 Chapter / Scene Episodic Summaries
L7 Lexical / Vector / Graph Retrieval Index
L8 Full Accepted Historical Text Archive
L9 External Knowledge / Reference
```

L1/L2/L4/L5 and accepted lineage are authoritative story projections. L3/L6/L7 are rebuildable consumers. L9 is Source/MKAOS-governed external evidence, never Canon. Working Context and interaction transcripts are frozen execution evidence, not another memory Authority. No private Agent memory may silently override these boundaries.

### 14.2 Context Contract v2 and Chapter Production Packet

The Writer should not receive Book Bible + all characters + all history. Context is compiled only at the latest complete Accepted Boundary:

```text
ChapterPlan
→ ChapterExecutionIntent
→ qualified ChapterMemo
→ Retrieval Query Plan at the frozen Accepted Boundary
→ PostgreSQL FTS / graph / temporal retrieval
→ optional governed semantic signal
→ rerank
→ compressible evidence compression
→ immutable RetrievalResult
→ Context Manifest v2
→ Chapter Production Packet
```

**Protected Context** includes the exact active ChapterPlan, qualified ChapterExecutionIntent/ChapterMemo constraints, accepted Canon/current state, hard world rules, critical character/relationship state, due obligations, relevant Arc actual/checkpoint state and forbidden/knowledge boundaries. Protected entries are typed, never filename-classified. If they exceed budget, compilation fails; none is silently dropped or semantically weakened.

**Retrievable Context** includes accepted historical chapter/scene text, episodic summaries, entity/relationship history, character timelines, Arc/obligation history, world consequences, prior setup/payoff and external governed knowledge. PostgreSQL retrieval combines Full-Text Search (`ts_rank`), governed embedding projection, entity/relationship, timeline/temporal, Arc and obligation relevance, accepted-boundary eligibility, rerank and optional compression. Vector similarity is one signal, never the memory system.

The bounded packet contains only what the chapter needs, conceptually including:

- Chapter Mission;
- entry Narrative State / previous accepted outcome;
- required beats/outcomes and forbidden changes;
- selected Arc contributions and obligations;
- character/reader knowledge boundaries;
- eligible current characters, skills, equipment, resources and locations;
- relevant world/conflict/mystery state;
- only necessary historical evidence;
- selected MKAOS knowledge/creative enrichment;
- style/voice requirements;
- Scene Plan.

Context Manifest v2 records accepted boundary, selected/rejected artifact versions, protected/retrievable class, retrieval reasons/scores/provenance, token partitions, compression lineage, policy/Skill/capability versions and a replayable fingerprint.

### 14.3 Three-stage context compilation

1. **Protected correctness context:** Mission/Intent/Memo constraints, current state, accepted predecessor, knowledge boundaries, due obligations, relevant Arc state and hard plan constraints.
2. **Task-specific evidence:** e.g. combat skills/weapons/injuries/environment; romance relationship/history/secrets; investigation clues/known/unknown/beliefs.
3. **Creative enrichment:** sensory, culture, architecture, professional knowledge, narrative mechanisms.

Creative enrichment may enrich expression but cannot change Story Truth.

Every context block is attributable to source/version, retrieval reason, authority class, temporal validity, priority, token cost and compression lineage. If the system cannot explain why a large block is present, it is not default provider input.

---

## 15. Source Intelligence and MKAOS Narrative Intelligence

MKAOS should evolve from a general knowledge store into a governed **Narrative & Domain Intelligence Layer**, without becoming a second planning system.

### 15.1 Source boundary

```text
Source
→ rights/provenance/import
→ source-specific observation/deconstruction
→ abstraction
→ cross-source generalization
→ governed reusable asset
```

Specific copyrighted expression or distinctive source-specific event sequences must not be promoted as reusable production assets.

### 15.2 Reusable asset families

MKAOS may contain:

- Narrative Primitives and Mechanisms;
- Arc/ArcBeat patterns;
- conflict/escalation/reversal/payoff patterns;
- character transformation/relationship patterns;
- mystery/clue/reveal patterns;
- world consequence/faction dynamics patterns;
- power/resource progression patterns;
- reader pleasure/emotional curve patterns;
- theme dialectic/moral dilemma patterns;
- scene/interaction patterns;
- anti-patterns and failure conditions;
- professional/domain causal knowledge.

Web fiction may contribute commercial pacing/reward mechanisms; published/classic fiction may contribute character/subtext/theme mechanisms; professional/history/social-science sources may contribute realistic causal mechanisms. Analysis profiles must remain source-type aware.

### 15.3 Production use

Arc/Story/Scene design sends a structured need to a **Narrative Intelligence Resolver** or equivalent selection capability. Selection returns mechanisms/patterns/evidence, not a ready-made copied plot. The project-specific Arc/Scene is newly composed under current Story Strategy + Narrative State + constraints.

Maintain four conceptual layers:

1. Source Observation — source-bound evidence.
2. Generalized Knowledge — reusable abstraction.
3. Project Candidate — proposed use for one Book.
4. Project Planning Authority — approved future intent.

Usage/effectiveness may be learned from downstream results, but knowledge feedback cannot directly mutate Canon or active planning.

---

## 16. ChapterPlan, ChapterExecutionIntent, ChapterMemo and Scene composition

The active ChapterPlan is authoritative future intent. Production derives two immutable, versioned working artifacts before Context:

- **ChapterExecutionIntent:** exact execution interpretation of one active ChapterPlan at one accepted boundary: objective, required/forbidden effects, Arc/obligation focus, entry/expected exit and reader tension.
- **ChapterMemo:** execution-time creative strategy: scene approach, pacing, transitions, retrieval needs, risk controls and alternatives.

Neither artifact may mutate or activate ChapterPlan. A degraded/unqualified fallback cannot enter Context or Draft.

The ChapterPlan/ExecutionIntent must answer:

- narrative purpose;
- entry state;
- required beats and outcomes;
- prohibited semantic changes;
- Arc contributions;
- knowledge/disclosure boundaries;
- reader effect / hook intent;
- expected exit state and unresolved obligations.

The mission is not prose and should remain compact.

Narrative Composer converts multiple Arc requirements into a small number of multi-function events. Scene planning turns those events into goal, conflict, action, choice, turn, cost, reaction and consequence. Avoid a scene-per-concern checklist; one event should often advance plot, character, relationship, world, mystery, power, theme and reader experience together.

---

## 17. Canonical Chapter Production Runtime

The target critical path is:

```text
Accepted state + qualified future design
→ Chapter admission
→ Arc Working Set / ChapterArcContributions
→ Narrative composition
→ active ChapterPlan
→ ChapterExecutionIntent
→ ChapterMemo
→ Retrieval Query Plan
→ immutable RetrievalResult
→ Context compilation
→ Chapter Production Packet
→ Scene Plan
→ immutable Draft Candidate
→ Review / bounded Revision / Re-review
→ CandidateComparison / BestCandidateSnapshot
→ Provisional Canon / Arc / Obligation extraction
→ Narrative Verification
→ required Quality Gate
→ ACCEPT
→ Accepted Outcome Transaction
→ complete Canon + Narrative State + Arc + Obligation projection set
→ Chapter N+1 eligibility / dispatch
```

The Writer has freedom over expression, dialogue, action, imagery, rhythm and local creative realization; it does not have authority to change Canon, Mission, forbidden constraints, or required outcome.

Revision never wins merely because it is newer. Reviews bind to exact candidate hashes. A deterministic comparison gate retains the prior best unless the new candidate has no disqualifying regression and exceeds the minimum net improvement policy. `BestCandidateSnapshot` preserves comparison evidence and rollback pointer. Quality Judge is evidence; deterministic Quality/Domain policy decides qualification.

### 17.1 Narrative Verification

Before acceptance, verify as appropriate:

- Mission and required outcomes completed;
- forbidden changes absent;
- Canon/state/world constraints respected;
- character and reader knowledge boundaries respected;
- skills/items/resources/location/time legal at chapter entry;
- important Arc/obligation handling matches policy;
- no future-fact leakage;
- no unacceptable source-expression leakage.

Use deterministic checks for structured invariants and independent semantic evaluation for genuinely literary/semantic judgments.

### 17.2 Acceptance before publication

Correct order:

```text
Final candidate
→ Internal Acceptance
→ AcceptedChapterOutcome / Canon / State commit
→ durable publication effect
```

External publication must never be the event that decides internal story truth.

### 17.3 Short deterministic acceptance transaction

All LLM calls, retrieval, embedding, compression, network work and semantic evaluation complete before acceptance as immutable candidates/evidence. The PostgreSQL transaction performs only fence/CAS and lineage validation, deterministic reducers, authoritative inserts/pointer advancement, checkpoints and outbox.

One acceptance establishes a logically complete boundary:

```text
AcceptedChapter N
+ ChapterOutcome N
+ Canon N
+ NarrativeState N
+ ArcProgress N
+ NarrativeObligationState N
```

Canon/accepted events are source evidence; materialized projections are deterministic consumers, not competing Authorities. Chapter N+1 cannot start formal drafting until this projection set is complete at N.

---

## 18. Artifact lifecycle, accepted lineage and semantic invalidation

Creative/model outputs use the immutable lifecycle:

```text
CANDIDATE → QUALIFIED → APPROVED → ACTIVE
                           └──────→ SUPERSEDED / INVALIDATED
```

The lineage contract records artifact/version/type, project/Book scope, source/parent versions, accepted boundary, context fingerprint, capability/Skill/model/provider/runtime identity, Operation/Attempt/trace, qualification and timestamps.

After acceptance preserve:

- immutable Accepted Chapter text/version;
- AcceptedChapterOutcome;
- accepted Canon/Narrative Events;
- deterministic Narrative State transition/projection;
- character/relationship/world/resource/knowledge/mystery/obligation changes;
- Arc Progress Evidence;
- source Operation/Attempt/provider/context/quality lineage.

Derived artifacts such as summary, recap, embedding, search index and prose snippets are rebuildable. Never use `Chapter → LLM summary → summary becomes truth`.

New cross-artifact dependencies use one canonical typed edge/invalidation surface. Semantic diff traverses only affected descendants, marks stale future artifacts, regenerates/requalifies selectively, and requires the owning Authority for activation. Existing domain-specific dependency tables may be isolated migration inputs/read compatibility but normal runtime must not dual-write competing graphs.

World/Character/Arc changes may invalidate future plans, Intent/Memo, Context and candidates. They never invalidate accepted Chapters/Outcomes or rewrite accepted Canon/State/Arc/Obligation evidence.

---

## 19. Quality and Evaluation

Keep three quality classes separate:

1. **Narrative Correctness:** Canon/state/time/knowledge/resource/world-rule/obligation legality.
2. **Narrative Quality:** structure, character depth, conflict, pacing, mystery, theme, prose, voice, scene effectiveness.
3. **Reader/Commercial Quality:** reader promise, hook/reward cadence, serialization, readability, fatigue and platform fit.

Generator output cannot mint its own PASS. Semantic evaluation must be independently attributable and candidate-hash/version bound.

Avoid Judge monoculture and Goodhart loops. Quality qualification should progressively combine deterministic invariants, calibrated model judges, human editorial evidence, and eventually real reader evidence.

Do not add more Judges until existing Judges have evidence for calibration, disagreement handling, stability and independence.

---

## 20. Publish / Observe / Learn / Adapt

Reader Outcome and analytics are observations. They may influence:

- future Arc scheduling;
- story/reader strategy proposals;
- MKAOS effectiveness evidence;
- quality policy calibration;
- future PlanChange/Replan.

They may not directly mutate accepted Canon/Narrative State.

Real reader learning is a future qualification layer. Simulated Reader Outcome remains advisory/shadow until calibrated against human outcomes.

---

## 21. Canonical execution plane and Provider Runtime

All durable model/tool work uses one execution semantics:

```text
Command
→ Operation
→ Attempt
→ Lease/Fence
→ ExternalEffect reservation/execution
→ Provider / Tool
→ immutable Receipt
→ Domain Commit
```

`RuntimeJob` is the durable scheduling/execution primitive where existing runtime uses it. A new WorkOrder/Workflow Engine/Agent Kernel must not be created in parallel without demonstrated inability of the existing execution plane.

Provider adapters do not own retry policy or business acceptance. Exact provider route/model/config/input identity and usage/cost evidence should be preserved to the level supported by the provider; unsupported exact cost must not be fabricated.

---

## 22. Long-form liveness and blocking semantics

Long-form correctness includes **safety and liveness**. A system that never corrupts Canon but cannot advance from Chapter 1 to Chapter 2 has failed long-form production.

The minimal blocking path after Chapter N is accepted is:

```text
Final Acceptance
→ AcceptedChapterOutcome
→ required Canon commit
→ required Narrative State transition
→ minimal next-plan/context eligibility
→ Chapter N+1 planning/admission/dispatch
```

Default **non-blocking sidecars** include, unless explicit persisted policy elevates them:

- Reader Outcome / Reader Judge;
- Long-form diagnostic/recap analytics;
- MKAOS feedback;
- quality analytics and calibration;
- noncritical literary analysis;
- cost/telemetry aggregation.

Legitimate hard blockers include:

- acceptance/Canon/State commit failure;
- explicit hard consistency violation;
- explicit replan approval requirement;
- persisted governance checkpoint whose policy is `HARD_BLOCKING`.

Every waiting production state must expose why it waits, since when, expected next transition, blocker identity, retry/recovery condition, and relevant operation/job identifiers.

### 22.1 Liveness proof ladder

```text
L0  one chapter completes
L1  Chapter 1 → 2 advances automatically within bounded time
L2  10 chapters unattended
L3  worker/API crash resumes without manual state repair
L4  provider timeout/retry ends in progress or explicit terminal/wait state, never silent stall
L5  30-chapter Arc/Segment campaign
L6  100+ chapter sustained progression
L7  multiple Books maintain isolated forward progress
```

`LONGFORM_PROVEN` is impossible while L1 is unproven or failed.

---

## 23. Reliability, recovery, replay and idempotency

Implement only mechanisms justified by real failure semantics, but preserve the following properties where applicable:

- stable idempotency for provider/tool effects, acceptance, state transitions, plan activation and publication;
- technical retry using the same frozen logical task;
- semantic revision as a new business candidate, not retry disguise;
- lease/fence protection against stale worker commits;
- CAS/optimistic version checks on mutable Authority state;
- recover/resume from PostgreSQL, not reconstructed in-memory workflow state;
- explicit `UNKNOWN` handling for uncertain non-idempotent external effects;
- exact evidence replay where recorded effect reuse is allowed, and logical replay where provider re-invocation is required;
- forward migrations and fresh/upgrade migration proof;
- backup/restore proof before production admission.

---

## 24. Observability and Operations

The system should answer:

- what Book/Chapter is running, waiting, failed, paused, blocked or stale;
- accepted-through chapter and last forward-progress time;
- next expected transition and blocking reason;
- current Operation/Attempt/RuntimeJob/lease/retry status;
- exact provider/context/capability/skill/pack versions;
- cost and provider calls per accepted Chapter;
- active/dormant/starved Arcs and overdue obligations/payoffs;
- context token composition and growth slope;
- quality/revision/replan frequency;
- reader/long-form sidecar backlog without confusing backlog with critical-path blockage.

A **Progress Inspector / Stall Watchdog** is a target operational capability, not a new Authority. It derives from durable runtime/domain state and detects lack of forward progress.

---

## 25. Governance and Security

- Provider/tool access is default-deny and capability/scope governed.
- Secrets never enter normal narrative context.
- external sources are untrusted and cannot change system policy or tool permissions;
- source provenance/rights/hash/lineage are preserved;
- Agent → direct SQL → Canon/Plan/Book State is forbidden;
- human override records actor, rationale, exact versions and downstream implications;
- high-impact future design change routes through semantic diff, impact analysis and PlanChange/Replan;
- multi-user/multi-book scope boundaries must be explicit before portfolio production.

---

## 26. Testing, Qualification and Production Admission

### 26.1 Completion dimensions

Always report separately:

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
LONGFORM_PROVEN
PRODUCTION_QUALIFIED
```

Repository maturity may additionally use:

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

No lower level implies a higher one.

### 26.2 Engineering evidence

According to changed risk, qualification should include:

- unit/domain/contract/architecture tests;
- PostgreSQL integration;
- fresh and upgrade migrations;
- worker/runtime composition;
- retry/recovery/replay/fence tests;
- real-provider proof;
- liveness proof;
- context correctness/bounded growth;
- accepted-only state propagation/rebuild;
- human editorial/quality evaluation;
- 10/30/100/300 chapter campaigns;
- multi-book isolation/scale only after single-book proof;
- backup/restore and security/operations drills.

Mock/fixture/code review evidence may validate code semantics; it cannot establish Real Provider, long-form quality, sustained liveness, multi-book, or Production proof.

### 26.3 Narrative quality proof ladder

A representative quality campaign is:

```text
Q0 fixture/prompt
Q1 real single chapter
Q2 multi-chapter coherence
Q3 Arc/Segment
Q4 Volume
Q5 sustained long-form
Q6 human editorial blind evaluation
Q7 real reader evidence
Q8 sustained production
```

---

## 27. Current gap policy and priority roadmap

The existing repository already contains a substantial governed foundation: PostgreSQL Authorities, Command Kernel, RuntimeJob, shared production execution, Chapter/Book production, progressive planning, Narrative State, PlanChange/Replan, Agent Collaboration/Runtime, Source/MKAOS, quality/reader surfaces and qualification infrastructure.

Therefore the target system **converges the existing architecture**; it does not rebuild it.

Every Work Package begins by re-reading the latest code and current runtime evidence. The ordering below changes if later evidence proves a gap is already closed.

### P0 — Correctness closure — WIRED / RUNTIME_REACHABLE / TARGETED POSTGRES TESTED

The convergence implementation now preserves the industrial base and has:

- frozen the four orthogonal hierarchy responsibilities without adding empty organizational/Segment roots;
- added explicit ArcPlan/ActualState/Progress/Outcome/Checkpoint/Revision and removed plan-to-actual fallback;
- completed accepted-only Narrative Obligation semantics;
- added ChapterExecutionIntent/ChapterMemo before accepted-bound Context compilation;
- added Protected/Retrievable Context v2, layered memory and PostgreSQL hybrid retrieval;
- added persistent CandidateComparison/BestCandidateSnapshot/minimum improvement/rollback;
- provided one semantic lineage/invalidation contract and isolated legacy parallel graphs;
- added a multi-turn Tool-calling Agent Harness inside Operation/Attempt/ExternalEffect while classifying ordinary creative work as Typed Capabilities;
- committed the complete accepted Chapter/Canon/State/Arc/Obligation projection set through a short deterministic Book Acceptance transaction;
- replaced stale architecture string assertions with behavior/contract tests.

Forward migration 0095 now registers durable post-0094 projection repair;
repair and live acceptance share the same deterministic accepted projector and
only terminal fenced CAS activates the repaired head. Agent Harness controlled
composition is server-policy-owned and PEP-backed. Arc/Obligation checkpoint
inputs are accepted and deterministic, with post-commit ArcRevision/PlanChange.
Memo now drives a durable RetrievalResult before Context, and semantic document
and query embeddings use the same ExternalEffect/Receipt governance as other
provider calls.

These capabilities have domain contracts, production composition, runtime
reachability, persistence, Authority governance, downstream consumption and
bounded unit/PostgreSQL tests. Agent and embedding routes are
`PROVIDER_WIRED`; scripted receipts are not `PROVIDER_PROVEN`. They are not
long-form or production qualified; those remain later evidence work.

### P1 — Long-form and Provider qualification

After convergence is implemented and bounded smoke tests pass:

- current-SHA real-provider Chapter proof;
- independent judge/calibration qualification;
- 10 → 30 → 100 → 300 chapter campaigns with failure injection;
- human editorial comparison;
- bounded-context and long-distance obligation proof;
- million-word retrieval quality and growth-slope evidence.

### P2 — Creative collaboration and author IDE

Complete Chief Editor / specialist conversations, Chapter Editor, selected-text change routing, Author Intent and what-if branches by extending existing Agent Collaboration and PlanChange paths. Do not create a second chat Authority/runtime.

### P2 — Publish / Reader learning closure

Connect real publication observations to attribution/calibration/governed future adaptation; keep simulated reader evidence advisory until calibrated.

### P3 — Multi-book and portfolio production

Only after single-book liveness/correctness/quality:

- isolation and fairness;
- per-book budgets/backpressure;
- portfolio scheduling;
- provider capacity/cost controls;
- operational SLOs;
- production admission.

### Deferred / Future

- automatic pacing/Arc portfolio optimization;
- Scene-level durable execution plane unless evidence requires it;
- advanced Reader Simulator;
- multi-model optimization;
- cross-book shared-universe Authority;
- fully autonomous public publishing.

---

## 28. Target architecture

```text
SOURCE / RESEARCH / MKAOS NARRATIVE INTELLIGENCE
                      │
HUMAN INTENT ─────────┼────────── STORY / WORLD / CHARACTER DESIGN
                      ▼
                NARRATIVE THREADS
                      ▼
             NARRATIVE ARC NETWORK
          + STRUCTURAL PROGRESSIVE PLAN
                      ▼
                 ARC SCHEDULER
                      ▼
            CHAPTER ARC CONTRIBUTIONS
                      ▼
              NARRATIVE COMPOSER
                      ▼
             ACTIVE CHAPTER PLAN
                      ▼
       EXECUTION INTENT → CHAPTER MEMO
                      ▼
      CONTEXT V2 @ COMPLETE ACCEPTED BOUNDARY
                      ▼
       PROTECTED + HYBRID RETRIEVED EVIDENCE
                      ▼
             SCENE PLAN → DRAFT
                      ▼
         REVIEW → REVISION → RE-REVIEW
                      ▼
     BEST CANDIDATE + PROVISIONAL EXTRACTION
                      ▼
        NARRATIVE VERIFICATION + QUALITY
                      ▼
                    ACCEPT
                      ▼
            ACCEPTED CHAPTER OUTCOME
                      ▼
  CANON + STATE + ARC PROGRESS + OBLIGATIONS
                      │
             ┌────────┴─────────┐
             ▼                  ▼
       NEXT CHAPTER        ASYNC SIDECARS
                           reader / recap /
                           MKAOS feedback /
                           analytics / learning
                                  │
                                  ▼
                         GOVERNED FUTURE REPLAN
```

The final system should be globally rich but locally bounded: the Book may accumulate a large narrative network, yet each Chapter receives only a small working set and minimum sufficient evidence.

---

## 29. Final architectural position

Novel Forge is not “many Agents writing chapters.” It is a **Narrative Change Operating System** in which:

- Narrative State is the truth center;
- Planning/Arc is the future-change center;
- Chapter is the expression and acceptance unit;
- MKAOS is the reusable intelligence layer;
- Agents are deliberative creative actors;
- Authorities own durable business truth;
- the execution plane guarantees recoverable model/tool work;
- Quality and Reader systems produce governed evidence;
- forward progress is a first-class correctness property.

The architecture succeeds only when a pinned system can repeatedly prove that it can move from accepted state to the next accepted state, preserve long-range narrative constraints and quality, recover from failures, and keep provider context bounded as the Book grows to million-word scale.
