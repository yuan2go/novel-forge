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

The defining model is a governed Narrative Evolution loop:

```text
Creative Foundation + Accepted Reality S(n)
→ explore several bounded narrative futures
→ compare / select / freeze the near future
→ progressively elaborate one operational Chapter
→ AcceptedChapterOutcome(n+1)
→ Canon + NarrativeState(n+1)
→ re-evaluate commitments and reopen only affected future space
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
21. Story formation coordinates qualified design Authorities; it never becomes Story Truth.
22. Narrative Realization is a causal/correctness contract inside Hierarchical Planning Authority, not another narrative scale and never Accepted Actual.

---

## 5. Business architecture

Novel Forge is organized around six connected loops.

### 5.1 Discover and design

```text
Human Intent / Material / Question
→ divergent Creative Exploration
→ evaluated and approved Creative Foundation
→ qualified Theme Contract + Ending Intent + Reader Promise
→ qualified WorldBible
→ qualified CharacterCast
→ BookDesign synthesis/reference contract
→ Narrative Threads / transformation directions
→ strategic future design
```

The production-grade opening boundary is `Book Ready for Production`, not the
existence of disconnected DTOs. A complete opening freezes exact qualified
versions and content hashes for Creative Foundation, Theme Contract, Ending
Intent, Reader Promise, WorldBible, CharacterCast and a BookDesign
synthesis/reference contract, plus a qualified Book/Volume/Arc planning
baseline, initial accepted-boundary projections, and the operational profiles
required to resolve one immutable Book Production input snapshot. Platform and
production profiles are constraints, not Story Truth. Candidate generation,
semantic qualification, comparison, approval and activation remain separate
evidence-bearing steps.

### 5.2 Progressive long-form planning

```text
Book Design + Current Accepted State
→ Volume / Narrative Segment planning
→ Narrative Arc Network
→ active Arc working set
→ Chapter Arc Contributions
→ qualified / approved / frozen causal Narrative Realization
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
    ├── frozen Definition/role/Tool/Skill/Pack/provider/model/route/release
    ├── frozen Accepted Boundary and aggregate budget
    ├── append-only transcript events
    ├── model-turn ExternalEffect / Receipt
    ├── Tool observation
    └── next turn / checkpoint / stop / escalation
```

It must support multi-turn resume, dynamic allowlisted Tool selection, Skill id/version/hash provenance, cancellation/deadline checks, token/cost/turn/effect hard stops, committed-request restoration and runtime trace. Every turn validates the Attempt execution binding against the immutable admission contract; restart or configuration drift never silently replaces provider, model, route, Pack or policy. Session budgets aggregate Agent turns plus descendant Typed Capability and Tool tokens, cost and effects through authoritative Operation/ledger lineage rather than copied accounting rows. Skill discovery starts from one admission-frozen catalog. User or model activation is an explicit Harness event bound to the exact Skill id/version/hash and catalog hash; it grants neither Tool nor business-Authority permission. An Agent may query, invoke Capabilities and submit typed Authority Commands; it cannot directly mutate Canon, accepted Narrative State, Arc actuals, Narrative Obligations, active plans or Chapter acceptance.

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

### 12.1 Divergent Narrative Search

Important strategic/tactical decisions are not reduced to one provider sample.
Book Architecture, Volume, Arc and consequential ChapterGroup planning support
a bounded search portfolio:

```text
exact parent design / accepted boundary + frozen constraints
→ several immutable future candidates
→ candidate-specific projection / simulation
→ independent semantic qualification
→ deterministic cross-candidate comparison
→ select one candidate with recorded reason
→ owning Authority approval and activation
```

The search portfolio is a Planning-owned lifecycle over existing generation
Operations and immutable candidates, not a second Planning Runtime. It records
the exact parent state and planning horizon, assumptions, projected
consequences, opportunities, risks, irreversible decisions, future optionality,
creative-intelligence signals, evaluation evidence, rejected alternatives and
selection lineage. Search selection grants no activation permission. A
search-created candidate cannot activate unless it is the selected member of
the current, non-stale portfolio and the normal StoryDesign/Planning approval
and activation gates also pass.

The Search row alone is not a Provider contract. Its complete planning horizon,
desired transformation and hard constraints must be copied into every admitted
branch command, frozen Context Bundle and Provider request, then compared on
retry/recovery. Consequential ChapterGroup search additionally freezes one exact
three-to-eight Chapter range. Provider schema and structural Authority both
require the candidate range, ordered Chapter Function Matrix and realization
event coverage to match that range; branch strategy cannot silently resize it.

Candidate projections must expose how the future changes conflict pressure,
character agency and transformation, costly choice/consequence, reversal and
reveal paths, setup/payoff debt, emotional/pacing variation, relationship and
world consequences, pattern repetition risk, Arc momentum, reader promise and
remaining optionality. These are structured decision inputs rather than a
single universal literary score. Deterministic comparison may rank qualified
candidates; semantic quality remains independently evaluated and attributable.

Technical retry reuses the same candidate branch and frozen Context. Mutation,
hybridization or a newly opened future is a new semantic branch/generation.
Rejected candidates remain immutable lineage. A changed complete Accepted
Boundary, active parent version or frozen constraint digest makes an unselected
portfolio stale and requires a new search generation; it is never silently
edited.

### 12.2 Rolling-wave stability

Future intent has explicit stability by horizon:

```text
Book / Ending     strategic anchors; change only through governed high-impact replan
Volume            stable direction with bounded future replacement
Arc               selected hypothesis; re-open when accepted evidence changes viability
ChapterGroup      tactical window; accepted reality may correct or replace it
Chapter           frozen operational mission
Scene / Beat      just-in-time typed children of ChapterPlan
```

One accepted Chapter never rewrites accepted history or automatically discards
the Book strategy. It may invalidate the smallest future closure, trigger a new
search portfolio at that scope, and then regenerate affected descendants.

### 12.3 Qualified Foundation hierarchy

The complete Foundation Set is an exact, immutable binding set:

```text
Qualified Creative Foundation
  ├→ Qualified Theme Contract
  ├→ Qualified Ending Intent
  └→ Qualified Reader Promise
            ↓
Qualified WorldBible
            ↓
Qualified CharacterCast
            ↓
Qualified BookDesign synthesis/reference contract
            ↓
BookPlan
```

Each layer owns only its design truth. WorldBible owns stable world rules and
their narrative consequences. CharacterCast owns stable character foundations
and relationship seeds. BookDesign owns cross-layer synthesis, Book invariants,
architecture and exact references; it does not copy World/Character truth.
Any denormalized convenience view is a derived snapshot bound to each source
AssetVersion and content hash.

Every transition freezes parent versions and hashes, performs layer-specific
structural validation, independent semantic evaluation and cross-layer
coherence validation, then follows qualification, approval and activation.
Parent replacement makes affected future descendants stale; it never modifies
executed history. BookPlan generation fails closed unless the complete current
Foundation Set and BookDesign reference contract agree exactly.

Story Formation is a durable, idempotent, restartable coordinator using the
existing Command Kernel, Operation/Attempt execution, checkpoints, receipts and
workers. It owns process progress and output bindings only. It cannot directly
change StoryDesign or BookDesign truth, and an API request only admits or
controls the durable run; it never owns the Provider chain.

Every child candidate declares the exact parent role → AssetVersion/content-hash
map, and its generation Operation must contain those same frozen parent assets.
A RuntimeJob freezes the Formation stage and version it may advance; a stale
technical retry cannot advance a later semantic stage. Resume cancels a pending
stale job and schedules a new job for the current persisted stage/version.

Book opening follows the same durable boundary: API admission persists the
frozen request and schedules `BOOK_OPENING_EXECUTE`; the worker runs existing
Narrative Search/Planning/Input Resolver applications. Query/resume/abort are
commands over the persisted run, and post-commit worker failure reconciles the
stored result without another semantic search.

Creative Search may reuse immutable candidate/evaluation/comparison/selection
primitives with Narrative Search, but Creative is not forced into a Planning
scope. Search selection is evidence for normal design qualification and
approval; it grants no activation authority.

### 12.4 Narrative Realization contract

Between ChapterGroup/Arc intent and ChapterPlan, Hierarchical Planning owns an
independent typed `NarrativeRealizationContract`:

```text
frozen ChapterGroup + relevant Arc intent + current Accepted Boundary
→ executable causal event chain
→ structural and semantic realization proof
→ Qualified → Approved → Frozen Narrative Realization
→ ChapterPlan slice
```

Narrative Realization is not a new `PlanContractType`, a new narrative scale, a
parallel Authority, or accepted reality. It reuses Planning's immutable
artifact, lifecycle, binding, qualification and evidence infrastructure while
retaining a distinct causal-proof contract. Its event chain records stable
event identity, causes, actor/motivation, preconditions, knowledge boundary,
action/decision, resistance, consequences, typed state deltas, disclosures,
obligation/promise/payoff/foreshadowing actions, Arc contributions,
irreversible changes and next-event causality. The proof binds the exact
Foundation Set, Book/Volume/Arc/ChapterGroup versions, Accepted Boundary and
Working Set and establishes goal coverage, Canon/state/world/knowledge legality,
motivation, causal escalation, state-transition coverage, obligation/Arc
coverage, load bounds and legal Chapter decomposition.

The proof is not projected from scheduling success. ChapterGroup qualification
records a separate versioned `NARRATIVE_REALIZATION_PROOF` receipt with exact
criterion evidence for Canon/state legality, character motivation, world rules,
knowledge boundaries, causal escalation, state transitions, obligation and Arc
coverage, Narrative Load and Chapter decomposition. Every criterion must be an
independent PASS with rationale and evidence references. Planned disclosures
must be permitted by the frozen reader knowledge boundary.

No current Qualified/Approved/Frozen realization means no ChapterPlan. A
ChapterPlan keeps ChapterGroup as its structural parent and binds the exact
realization slice and planned event identities. Production admission recomputes
all parent, boundary, Working Set, proof and content digests and fails closed on
stale or mixed lineage.

Consumption records this one-way evidence relation:

```text
Planned Event → Observed Event → Accepted Chapter Outcome → Accepted Actual
```

A ChapterPlan becomes `EXECUTED` atomically with its accepted Chapter. A
multi-Chapter realization advances only the accepted event/slice coverage and
becomes `EXECUTED` only after every required event is accepted and every
optional event is either accepted or explicitly not observed. Unobserved
planned events never advance Canon, Narrative State, Arc Actual or obligation
state. Missing, additional, causal, state-delta or disclosure drift creates
immutable deviation/replan evidence and stale only affected future intent.
They never rewrite accepted history or silently alter the frozen realization.

---

## 13. World and Character architecture

### 13.1 Character

```text
Character = Stable Identity + Current Temporal State + Development Trajectory
```

Stable identity may define desire, fear, values, voice, core contradictions, long-term goals and intended development. Current Narrative State owns what is currently true: location, health, knowledge, belief, relationship, reputation, resources, power, status and access.

Character Arc planning expresses desired transformations; only accepted behavioral/state evidence advances reality.

The qualified CharacterCast owns stable Character Foundations with at least
desire, need, fear, wound, false belief, values, moral boundary, agency,
capability/cost, weakness, voice, secret, relationships and Arc direction. It
binds the exact qualified Creative/Theme/Ending/Promise and WorldBible inputs.
Planning/Context consume these stable definitions together with the exact
accepted dynamic Character/Relationship state; neither substitutes for the
other.

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

The qualified WorldBible owns World rules as
`Rule → Cost → Exception → Consequence → Conflict Potential → Narrative Function`.
It binds the exact qualified Creative/Theme/Ending/Promise inputs.
Planning/Context combine those stable constraints with accepted Faction,
Resource, Power, Location and Knowledge state. Accepted actions alone advance
the temporal side of that model.

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

### 14.2 Governed Context Contract and Chapter Production Packet

The Writer should not receive Book Bible + all characters + all history. Context is compiled only at the latest complete Accepted Boundary:

```text
ChapterPlan
→ ChapterExecutionIntent
→ qualified ChapterMemo
→ Retrieval Query Plan at the frozen Accepted Boundary
→ PostgreSQL FTS plus exact structured accepted-evidence discovery
→ bounded lexical/structured candidate set
→ optional semantic rerank inside that exact set
→ compressible evidence compression
→ immutable RetrievalResult
→ Context Manifest
→ Chapter Production Packet
```

The Context classes are operational invariants, not labels:

- **PROTECTED** includes the exact active ChapterPlan, qualified ChapterExecutionIntent/ChapterMemo constraints, accepted Canon/current state, hard world rules, critical character/relationship state, due obligations, relevant Arc actual/checkpoint state and forbidden/knowledge boundaries. Protected entries are typed, never filename-classified. If protected tokens alone exceed the safe provider budget, compilation fails before provider execution; none is silently dropped, compressed or semantically weakened.
- **RETRIEVABLE** is rebuildable accepted-history or governed-knowledge evidence selected from the frozen retrieval candidate set.
- **COMPRESSIBLE** may be rendered through a governed compact projection only when its exact source AssetVersion and compression provenance remain in the manifest.
- **EPHEMERAL** is excluded from long-lived Memory/Search. If sent to a provider, its exact content/identity is still frozen in Attempt evidence for replay and audit.

Retrievable evidence includes accepted historical chapter/scene text, episodic summaries, entity/relationship history, character timelines, Arc/obligation history, world consequences, prior setup/payoff and external governed knowledge. Candidate discovery is lexical-first: PostgreSQL Full-Text Search (`ts_rank`) and exact entity/relationship/timeline/temporal/Arc/obligation channels produce one bounded set under Project, Book, Accepted Boundary and lifecycle eligibility. Optional compatible vector similarity may rerank only members of that frozen set; it cannot introduce a candidate. If semantic projection/provider support is unavailable, ranking deterministically falls back to lexical/structured signals. PostgreSQL FTS is not called BM25.

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

Context Manifest v3 records accepted boundary, selected/rejected artifact versions, all four Context classes, retrieval reasons/scores/provenance, protected/other token partitions, compression lineage, ephemeral Attempt-evidence policy, policy/Skill/capability versions and a replayable fingerprint.

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

Engineering correctness, narrative correctness, Judge score, editorial quality,
human preference, Reader Outcome, long-form quality and commercial success are
different claims. Likewise, code existence, wiring, integration proof,
real-provider proof, human comparison, long-form proof and production proof are
different evidence levels. A campaign must not collapse either distinction into
one score or status.

### 19.1 Non-collapsible evidence layers

Quality Qualification uses three separately persisted layers:

1. **L1 Hard Narrative Correctness:** Canon, identity, timeline, world rule,
   knowledge boundary, causal continuity, Narrative Realization, required state
   transition, obligation/payoff, forbidden-change and accepted-history
   immutability evidence.
2. **L2 Editorial/Literary Quality:** prose clarity, scene effectiveness,
   character agency, dialogue differentiation, emotional movement, conflict,
   pacing, hook, information release, payoff strength, originality, repetition,
   narrative economy and reader-promise delivery.
3. **L3 Reader/Longitudinal Outcome:** momentum, conflict/agency/antagonist
   trends, promise aging/payoff cadence, setup-to-payoff latency, unresolved
   debt, semantic repetition/fatigue, Arc evolution, long-span continuity and
   Reader Proxy trends.

A severe or blocking L1 failure cannot be offset by L2 prose or L3 preference.
Missing evidence is `NOT_PROVEN`, never a zero that can be averaged with known
evidence. All evidence binds exact accepted Chapter/version boundaries, source
AssetVersions, release SHA, Provider/model route, Capability Pack, Prompt/Skill
hashes and evaluation/profile versions.

### 19.2 Evaluation roles and independence

Generator output cannot mint its own PASS. Keep `JudgeEvaluation`,
`HumanEvaluation`, blind pair preference, adjudication, Reader Outcome,
calibration result and versioned Quality Profile distinct. Record the
generator/reviewer/Judge Provider and model plus their independence
relationship. A same-model Judge is dependent evidence, even when its score is
high.

Human comparison is blinded to Canonical/Baseline identity, Provider/model,
Prompt/branch and system/Judge scores. Candidate ordering is balanced across
reviewers. Raw choices include A, B, Tie and Cannot Judge; dimension scores,
confidence, rationale, scope, protocol/evaluation version, disagreement and
adjudication remain append-only. Two independent reviewers over one bounded
sequence provide bounded human preference evidence, not statistical Judge
calibration. One valid reviewer is `HUMAN_EVIDENCE_LIMITED`; no completed human
review leaves the campaign `WAITING_HUMAN_EVIDENCE / NOT_PROVEN`. An LLM must
never be recorded as a human reviewer.

A single subjective literary opinion is not `GroundTruth`; that term is
reserved for objectively decidable facts. Do not add more Judges until the
current Judge has evidence for agreement, false positives/negatives,
confidence, position bias, preference stability and independence. Insufficient
samples remain `UNCALIBRATED / BOUNDED_EVIDENCE`.

### 19.3 Chapter, Arc and Volume interpretation

Chapter evaluation asks whether the Chapter is correct, effective and worth
continuing. Arc evaluation uses accepted causal progression, protagonist/
antagonist interaction, escalation, setup/payoff and credible transformation;
it distinguishes activity from progress and identifies stagnation, repetition
and fake escalation. A bounded Volume-slice evaluation interprets Arc rhythm,
long-promise progress, payoff distribution, fatigue, cumulative world/
character/conflict evolution and ending reachability. It is not an average of
Chapter or Arc scores.

Final campaign decisions are `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL` or
`NOT_PROVEN`. Severe correctness failure, incomplete lineage/provider evidence
or material evidence contamination fails closed. `PASS` is never inferred from
one model score, one reviewer or an incomplete campaign.

---

## 20. Publish / Observe / Learn / Adapt

Reader Outcome and analytics are Reader Proxy/advisory observations. Outcome v3
keeps all dimensions explicit: continue intent, curiosity, satisfaction,
confusion, trust, character attachment, antagonist pressure, promise
expectation, payoff satisfaction, drop risk and repetition fatigue. They may
influence:

- future Arc scheduling;
- story/reader strategy proposals;
- MKAOS effectiveness evidence;
- quality policy calibration;
- future PlanChange/Replan.

They may not directly mutate accepted Canon/Narrative State.

The governed path is Chapter → Reader Outcome → longitudinal Reader State →
Recap/trend evidence → bounded future recommendation or Replan proposal. Reader
evidence cannot directly mutate Canon, executed plans, accepted Narrative
State, or turn future intent into actual state. Real reader learning is a future
qualification layer. Simulated Reader Outcome remains advisory/shadow until
calibrated against human outcomes.

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
L2  one explicitly bounded multi-Chapter slice advances unattended
L3  worker/API crash resumes without manual state repair
L4  provider timeout/retry ends in progress or explicit terminal/wait state, never silent stall
L5  one complete Arc-level campaign at an explicitly frozen scope
L6  separately authorized sustained long-form progression
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
- scope-specific bounded campaigns followed only by separately authorized
  sustained campaigns;
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

### P0 — Correctness closure baseline — PARTIALLY HARDENED

The convergence implementation now preserves the industrial base and has:

- frozen the four orthogonal hierarchy responsibilities without adding empty organizational/Segment roots;
- added explicit ArcPlan/ActualState/Progress/Outcome/Checkpoint/Revision and removed plan-to-actual fallback;
- completed accepted-only Narrative Obligation semantics;
- added ChapterExecutionIntent/ChapterMemo before accepted-bound Context compilation;
- added enforceable four-class Context Manifest v3, layered accepted-memory
  projections and lexical-first PostgreSQL retrieval with bounded optional
  semantic reranking;
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

Post-merge runtime hardening closes the four 0095 follow-on gaps without adding
a parallel Authority or runtime: Arc follow-up consumes canonical Operation
retry/final/dead-letter/cancellation states; embedding unknown outcomes
checkpoint and reconcile the original ExternalEffect/Receipt; Agent admission
freezes and validates the complete execution binding while Session budgets
aggregate descendant ledgers; and PostgreSQL vector search is an independent,
accepted-boundary-governed candidate channel before hybrid reranking. Targeted
PostgreSQL recovery tests cover those contracts. The 2026-08-22 exact-SHA small
qualification additionally proves the real Provider wiring for one Agent
Session, document/query embeddings and one Memo→Retrieval→Draft slice. This is
bounded `PROVIDER_PROVEN` evidence only. None of these capabilities is
`LONGFORM_PROVEN` or `PRODUCTION_QUALIFIED`.

### P1 — Bounded quality qualification

The current runtime contains an exact two-by-four Quality Qualification
contract: one Book, two consecutive four-Chapter ChapterGroups, eight accepted
Chapters, one bounded Volume slice, at least one Arc evaluation, a comparable
first-draft-versus-accepted-revision baseline, Reader Outcome v3 longitudinal
evidence and two reviewer-specific blind packs. The campaign freezes exact
release/migration/Provider/model/Pack/Prompt/Skill/Foundation/Planning/
Realization/Context/profile/budget lineage and forbids Chapter 9 or background
continuation.

Implementation and scripted PostgreSQL recovery proof do not establish the
real-provider or human result. The exact-SHA qualification artifact owns that
claim. Until the bounded real-provider run and required human evidence are
recorded, the correct status is `NOT_PROVEN`; incomplete human work remains
`WAITING_HUMAN_EVIDENCE`.

Larger sustained campaigns, real-reader outcomes, statistical Judge
calibration, million-word retrieval quality and growth-slope evidence remain
separate future qualifications. They are not prerequisites for this bounded
campaign and must not be started implicitly.

### P1 — Canonical hierarchy closure (implemented; bounded integration proven)

The current runtime uses separately qualified Foundation contracts,
reference-only BookDesign v5, durable Formation/Opening coordination and the
Planning-owned Narrative Realization contract. Book/Chapter production rejects
missing, stale or mixed lineage; accepted outcome evidence consumes planned
event coverage and future-only Replan invalidates affected intent. PostgreSQL
integration proves bounded formation, planning, 1–4 Chapter execution,
acceptance, partial/full coverage, deviation/staleness, retry/recovery/replay
and fresh/upgrade migration behavior.

This evidence is engineering qualification, not sustained literary quality or
production proof. Real-provider Arc/Volume campaigns, human blind comparison,
reader evidence, long-form stability and multi-book operation remain later
independent qualifications.

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
HUMAN INTENT ─────────┼────────── CREATIVE FOUNDATION / WORLD / CHARACTER
                      ▼
                NARRATIVE THREADS
                      ▼
       DIVERGENT BOOK / VOLUME / ARC SEARCH
        + PROJECTION / EVALUATION / SELECTION
                      ▼
        SELECTED STRUCTURAL PLAN + ARC NETWORK
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
  RE-EVALUATE / REOPEN     ASYNC SIDECARS
  AFFECTED FUTURE SPACE    reader / recap /
             │             MKAOS feedback /
             ▼             analytics / learning
       NEXT CHAPTER              │
                                 ▼
                         GOVERNED FUTURE REPLAN
```

The final system should be globally rich but locally bounded: the Book may accumulate a large narrative network, yet each Chapter receives only a small working set and minimum sufficient evidence.

---

## 29. Final architectural position

Novel Forge is not “many Agents writing chapters.” It is a **Narrative Evolution Operating System** in which:

- Narrative State is the truth center;
- Planning/Arc is the future-change center;
- Narrative Search explores qualified possibilities inside Planning without
  becoming Authority;
- Chapter is the expression and acceptance unit;
- MKAOS is the reusable intelligence layer;
- Agents are deliberative creative actors;
- Authorities own durable business truth;
- the execution plane guarantees recoverable model/tool work;
- Quality and Reader systems produce governed evidence;
- forward progress is a first-class correctness property.

The architecture succeeds only when a pinned system can repeatedly prove that it can move from accepted state to the next accepted state, preserve long-range narrative constraints and quality, recover from failures, and keep provider context bounded as the Book grows to million-word scale.
