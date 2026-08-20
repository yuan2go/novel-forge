# Industrial Autonomous Novel OS Convergence Design

> **Status:** APPROVED implementation specification
> **Canonical architecture:** `docs/architecture/canonical-overall-design.md`
> **Novel Forge audit baseline:** `4fdf6adaa25ef085e4e6abab1f5b6ac71d86607a`
> **InkOS architecture input:** `Narcooo/inkos@5da9fad03d65882adc030dc0043da8e8bc197dbd`
> **Evidence rule:** this specification freezes the approved convergence and implementation acceptance criteria. It does not upgrade code or tests to runtime, long-form, provider, or production proof.

## 1. Problem and desired outcome

Novel Forge already has a strong industrial execution and truth-settlement base: PostgreSQL Authority, immutable Assets, Operation/Attempt, RuntimeJob, Lease/Fence, ExternalEffect/Receipt, Book/Chapter acceptance, accepted Canon/Narrative State, recovery, replay, trace, and cost evidence. The latest code does not yet provide the complete intelligence layer implied by the product target:

- hierarchy semantics are mixed with production grouping;
- planned Arc contributions can be recorded as actual evidence;
- Narrative Obligation is only a partial accepted-state projection;
- Agent Runtime is a fixed candidate execution path, not a multi-turn tool-calling harness;
- Context is accepted-bound but not protected/retrievable or hybrid-retrieval driven;
- ChapterExecutionIntent and ChapterMemo are not production artifacts;
- revision has no persistent best-candidate/minimum-improvement protection;
- lineage and semantic invalidation use overlapping domain-specific graphs.

The target is one system:

```text
InkOS-style interaction, tool use, Skills and context intelligence
+ Novel Forge Authority, Narrative Correctness and Durable Runtime
= Industrial Autonomous Novel OS
```

No InkOS filesystem/runtime ownership is transplanted. Intelligence runs inside Novel Forge's industrial execution boundaries.

## 2. Reconciliation findings

### 2.1 Proven current foundations

The audited baseline has real production code for:

- Planning candidate generation, qualification, activation and PlanChange/Replan;
- Book and Chapter durable coordination;
- immutable ChapterOutcome creation and Book acceptance;
- accepted-only Canon and Narrative State reduction;
- PostgreSQL transaction commands, CAS, fences, outbox and recovery;
- versioned ContextBundle with accepted-boundary evidence;
- Agent candidate provenance and immutable collaboration artifacts;
- model/tool calls routed through Production Execution and ExternalEffect.

These foundations are retained and deepened, not reimplemented in parallel.

### 2.2 Contradictions and missing links

1. `book_production/checkpoints.py` reads `actual_arc_contributions` from ChapterOutcome, but `chapter-outcome-v2` does not produce it. Missing evidence falls back to planned contributions and is stored with `contribution_kind='ACTUAL'`. This violates `PLAN != ACTUAL`.
2. Arc checkpoints count contributions and chapter position but do not own an explicit `ArcActualState / ArcProgress / ArcOutcome / ArcRevision` contract.
3. Unified obligations cover only a subset of required types and fields; provider output does not exercise the complete contract.
4. `agent.candidate.execute` binds fixed Chapter stages to one model ExternalEffect. Agent Collaboration can store turns but does not implement dynamic tool observation/replanning.
5. Context selection sorts pre-resolved candidates and trims by budget. It has no explicit protected partition, retrieval plan, compression lineage, or long-form hybrid retrieval index.
6. Chapter intent is embedded in ChapterPlan; no execution-time Intent/Memo versions are persisted and consumed.
7. Revision always advances the latest candidate. No durable comparison, minimum net improvement, best snapshot or rollback pointer exists.
8. `authority_asset_dependency`, `asset_dependency_edge`, and source-specific content dependency/invalidation surfaces overlap without a canonical cross-artifact invalidation contract.
9. Two architecture tests still assert ownership removed by the current liveness runtime: worker-local active states and Book-owned follow-up completion.

## 3. Approved convergence strategy

Extend the existing industrial plane forward. Do not create a replacement Novel OS kernel, parallel workflow engine, Arc Authority stack, context runtime, Agent truth store, or filesystem persistence path.

Implementation proceeds as vertical contracts whose completion requires:

```text
DEFINED
→ WIRED
→ RUNTIME_REACHABLE
→ PERSISTED
→ AUTHORITY_GOVERNED
→ CONSUMED
→ UNIT/SMOKE_TESTED
```

## 4. Four orthogonal structures

### 4.1 Organization and IP scope

```text
Studio → Portfolio → Universe → Series → Book
```

These names define responsibilities, not mandatory Aggregate roots.

| Concept | Responsibility | Current implementation decision |
|---|---|---|
| Studio | operator/tenant policy, model/provider governance, budgets | lightweight scope over Workspace/Project; no new Authority root without independent lifecycle evidence |
| Portfolio | production grouping, scheduling, cost/capacity view | lightweight optional scope; no narrative Authority |
| Universe | optional shared-world/Canon boundary across Books/Series | domain concept only in this slice; persistence deferred until shared-Canon consumers exist |
| Series | optional ordered Book set and cross-book promise/trajectory | lightweight Book metadata/scope; no empty Series Authority |
| Book | accepted narrative and production root | existing Book Design, Planning and Book Acceptance Authorities remain canonical |

No organizational scope may mutate Book Canon merely because it contains the Book.

### 4.2 Narrative containment

```text
Book → Volume → [Narrative Segment] → Chapter → Scene → Beat
```

- Book and Volume are strategic planning scopes.
- Chapter is the publishable and acceptance unit.
- Scene is an addressable/versioned typed child of ChapterPlan and ChapterOutcome. It has no independent Acceptance Authority.
- Beat remains a lightweight typed Scene child unless an independent lifecycle, concurrency or consumer appears.

`Narrative Segment` is admitted only if code proves all of the following:

1. a stable contiguous dramatic interval independent of Arc and ChapterGroup;
2. distinct planning semantics or invariant;
3. at least one production consumer that cannot use Volume, Arc or ChapterGroup without semantic loss;
4. version/lineage/invalidation value.

The baseline has no such consumer. This implementation therefore does **not** create a Narrative Segment table, repository or Authority. The term stays conditional in the target model.

### 4.3 Long-form change graph

Arc remains a cross-cutting graph. It may span Volumes, ChapterGroups and Chapters. It is never a containment parent.

### 4.4 Production coordination

ChapterGroup owns chapter range, production batch, plan coordination, budget, checkpoint and correction window. It owns neither Scene/Chapter truth nor Canon Authority.

## 5. Plan, actual and Authority contracts

| Scope | Planned artifact | Actual/projection | Outcome/checkpoint | Authority |
|---|---|---|---|---|
| Book | BookDesign / BookPlan | accepted Book narrative cursor | BookOutcome/ending reachability | Design/Planning for intent; Book Acceptance for actual |
| Volume | VolumePlan | VolumeActualState projection | VolumeCheckpoint/Outcome | Planning for intent; accepted-outcome reducer for actual |
| Arc | ArcPlan | ArcActualState + ArcProgress | ArcCheckpoint + ArcOutcome | Planning/PlanChange for intent; Book Acceptance for actual projection |
| ChapterGroup | ChapterGroupPlan | production coordination state | group checkpoint/correction window | Planning + ChapterGroup/Book coordination |
| Chapter | ChapterPlan | accepted ChapterOutcome | AcceptedChapter | Planning for intent; Book Acceptance for fact |
| Scene | typed ScenePlan child | typed SceneOutcome child | carried by ChapterOutcome | Chapter Acceptance transaction only |
| Beat | typed ScenePlan/Outcome child | embedded evidence | none independently | inherited from Chapter |

Planning artifacts and actual projections must never share a status or pointer that allows implicit promotion.

## 6. Arc and long-form narrative control

### 6.1 Contract family

- `ArcPlan`: desired transformation, dependencies, target window, expected contribution schedule and completion criteria.
- `ArcActualState`: accepted materialized current state at an exact Book acceptance boundary.
- `ArcProgress`: immutable per-Chapter accepted evidence and deterministic progress/deviation accounting.
- `ArcOutcome`: immutable accepted completion/abandonment evidence.
- `ArcCheckpoint`: boundary snapshot used for continue/correct/replan decisions.
- `ArcRevision`: immutable future-only PlanChange candidate; never mutates accepted progress.

### 6.2 Evidence rule

`ChapterPlan.expected_arc_contributions` is PLAN. Before acceptance, a model-backed extraction capability may produce `ProvisionalArcEvidence`. Narrative Correctness validates it against the selected immutable Chapter candidate and ChapterPlan scope. `ChapterOutcome.arc_evidence` contains only qualified observed evidence.

At acceptance:

```text
observed evidence present and valid → materialize ArcProgress
evidence explicitly says no materialization → NOT_MATERIALIZED
required observation unavailable → NOT_OBSERVED
evidence ambiguous/invalid → block acceptance or UNKNOWN by governed policy
```

There is no fallback from expected contribution to actual contribution.

### 6.3 Progress and deviation

ArcProgress records:

- accepted boundary and ChapterOutcome lineage;
- observation status;
- contribution kind and magnitude/effect dimensions;
- milestone/phase transition evidence;
- actual consequences and obligation effects;
- deviation from expected contribution;
- progress confidence from deterministic qualification, not self-reported model certainty.

ArcCheckpoint deterministically evaluates dependency readiness, temporal window, stagnation, overdue promises/debt, completion criteria, divergence and ending contribution. It emits `CONTINUE`, `CORRECT`, `REPLAN_REQUIRED`, `COMPLETED`, or an explicit unobserved status.

## 7. Unified Narrative Obligation

The authoritative obligation projection is accepted-only and extensible. It supports at least:

- promise;
- foreshadowing;
- mystery;
- open loop;
- conflict;
- hook;
- character commitment;
- reader expectation;
- narrative debt.

Each obligation records identity/type, introduced boundary/source, status, current development, append-only development history, dependencies, target window, urgency, reader visibility, expected payoff, actual payoff, overdue/stale state, related characters/Arcs/Volumes, and resolution evidence.

Only `ChapterOutcome.obligation_events` accepted by Book Authority advances the authoritative projection. Drafts, Reviews, Memos, Agent messages and provisional extraction remain evidence/candidates.

## 8. Agent, Capability, Skill, Tool, Workflow, Service and Authority taxonomy

| Kind | Definition | May decide dynamically? | May mutate authority state? |
|---|---|---:|---:|
| Autonomous Agent | bounded goal decomposition, multi-step reasoning, tool observation and adaptive replanning | yes | only by submitting typed Authority Commands |
| Typed Capability | one semantic task producing a typed candidate/evidence artifact | internally, within contract | no |
| Skill | versioned procedure/guidance bound to an Agent or Capability | no authority effect | no; Skill never grants permission |
| Tool | typed query, capability invocation, or Authority Command submission endpoint | invoked by Agent/workflow | only the Authority Command endpoint may request mutation |
| Durable Workflow | explicit durable transition sequence and recovery policy | deterministic branching | via owning Authority only |
| Domain Service | deterministic validation, reduction, comparison, diff or projection | no model discretion | only when executed inside owning Authority UoW |
| Authority | validates and commits business truth/current pointers | deterministic/governed | yes, within scope |

The initial autonomous role set remains deliberately small:

- Studio/Director Agent: explores goals, inspects state, invokes capabilities and submits commands;
- Research/Knowledge Agent: plans bounded research/retrieval and submits governed knowledge candidates.

Worldbuilding, Character Design, Outline, Chapter Planning, Draft, Review, Revision, Canon Extraction and Quality Judge are Typed Capabilities unless they later demonstrate a real autonomous tool/replanning lifecycle.

## 9. Unified Agent Harness

### 9.1 Runtime placement

```text
RuntimeJob / Operation / Attempt / Lease / Fence
└── Agent Session operation
    ├── frozen role + tool policy + Skill bindings + budgets
    ├── append-only transcript events
    ├── model turn ExternalEffect + Receipt
    ├── tool query/capability/command ExternalEffect or domain read
    ├── observation
    └── next turn / stop / checkpoint / escalation
```

The session is not authoritative business state. Every model/network/tool side effect remains an ExternalEffect with receipt/reconciliation semantics.

### 9.2 Required behavior

- multi-turn session and durable resume;
- dynamic selection from a role/operation-specific allowlist;
- Skill activation with id/version/hash/source/reason;
- structured capability invocation;
- read-only accepted-boundary domain queries;
- typed Authority Command submission;
- cancellation and deadline checks before each turn/tool;
- token, cost, turn and external-effect hard budgets;
- trace/span, operation/attempt and provider lineage;
- committed-request transcript restoration;
- foreground/background mutation-tool filtering.

### 9.3 Forbidden tools

No Agent tool can directly mutate Canon, accepted Narrative State, ArcActualState, Narrative Obligation state, active plans or Chapter acceptance. Command submission creates a proposal/admission; the owning Authority revalidates it.

## 10. Context Contract v2

### 10.1 Compilation chain

```text
Accepted Boundary
→ Context Requirement Plan
→ Protected Context resolution
→ hybrid retrieval
→ deterministic/semantic rerank
→ compressible evidence compression
→ Context Manifest v2
→ immutable ContextBundle
```

### 10.2 Protected Context

Protected entries include:

- exact active ChapterPlan;
- ChapterExecutionIntent and ChapterMemo required constraints;
- accepted Canon/current Narrative State at Chapter N-1;
- hard world rules;
- critical character/relationship state;
- due/critical Narrative Obligations;
- relevant ArcActualState/ArcCheckpoint;
- forbidden changes and reader/character knowledge boundaries.

Protected entries are selected by typed authority/criticality metadata, not filenames. If they exceed budget, compilation fails with `PROTECTED_CONTEXT_BUDGET_EXCEEDED`; none may be silently removed or compressed into a semantically weaker form.

### 10.3 Retrievable Context

Retrievable evidence includes historical chapter/scene text, episodic summaries, entity history, character/relationship timeline, Arc history, obligation history, world consequences, prior setup/payoff and external governed knowledge.

The PostgreSQL-backed hybrid retriever combines:

- lexical/full-text scoring;
- embedding similarity where available;
- entity and relationship overlap;
- character timeline relevance;
- temporal distance/window;
- Arc membership/relevance;
- Narrative Obligation relevance/urgency;
- accepted-boundary eligibility;
- deterministic and optional model-backed rerank.

Vector search is one signal, never the memory system.

### 10.4 Manifest

Context Manifest v2 records accepted boundary, selected/rejected artifacts and versions, protected/retrievable class, retrieval query/reasons/scores, provenance, token partitions, compression input/output lineage, policy/Skill/capability versions and a replayable context fingerprint.

## 11. Narrative Memory layers

| Layer | Content | Authority/owner | Mutation/index rule |
|---|---|---|---|
| L0 | recent accepted verbatim window | Accepted Chapter lineage | append by Book acceptance; bounded view |
| L1 | current accepted Narrative State | Book Acceptance projection | deterministic accepted reducer |
| L2 | Canon fact graph | Canon Authority within Book acceptance | accepted facts only |
| L3 | character/relationship timeline | accepted event projection | rebuildable from accepted events |
| L4 | Narrative Obligation graph | accepted obligation reducer | accepted events only |
| L5 | Arc/long-range debt state | accepted Arc reducer/checkpoint | accepted evidence only |
| L6 | chapter/scene episodic summaries | derived artifact pipeline | rebuildable, never truth |
| L7 | lexical/vector/graph retrieval index | retrieval projection owner | rebuildable and boundary-filtered |
| L8 | full accepted historical text archive | Accepted Chapter lineage | immutable archive |
| L9 | external knowledge/reference | Source/MKAOS Authority | rights/provenance governed; never Canon |

Only L1/L2/L4/L5 and accepted lineage are authoritative story projections. L3/L6/L7 are rebuildable consumers. L9 is external evidence.

## 12. ChapterExecutionIntent and ChapterMemo

```text
active ChapterPlan
→ ChapterExecutionIntent candidate
→ qualification
→ ChapterMemo candidate
→ qualification
→ Context Manifest v2
→ Draft Candidate
```

- `ChapterExecutionIntent` freezes the execution interpretation of an exact active ChapterPlan and accepted boundary: objective, required/forbidden effects, Arc/obligation focus, entry/expected exit and reader tension.
- `ChapterMemo` is an execution-time creative strategy: scene approach, pacing, transitions, retrieval needs, risk controls and optional alternatives.
- Both are immutable versioned working artifacts with plan/boundary lineage.
- Neither may activate or modify ChapterPlan.
- A degraded/unqualified fallback cannot enter Context or Draft.

## 13. Review, Revision and Best Candidate

Each Draft/Revision is immutable. Review evidence is bound to the exact candidate hash/version and evaluator policy.

```text
Candidate
→ Review evidence + deterministic blockers
→ Revision Candidate
→ Re-review
→ CandidateComparison
→ BestCandidateSnapshot
```

CandidateComparison uses:

- hard correctness blockers and regressions;
- qualified quality dimensions;
- resolved/new issue severity;
- minimum net improvement threshold;
- policy-defined tie/uncertainty handling.

The current best changes only when the new candidate is eligible and materially better. Otherwise the previous best remains selected. The snapshot records comparison evidence and rollback pointer; no artifact is overwritten.

Stop conditions include quality satisfied, correction budget exhausted, marginal improvement below threshold, deterministic blocker and escalation required. Quality Judge remains evidence; deterministic Quality/Domain gate controls qualification.

## 14. Artifact lifecycle, lineage and semantic invalidation

All important outputs use one lifecycle:

```text
CANDIDATE → QUALIFIED → APPROVED → ACTIVE
                           └──────→ SUPERSEDED / INVALIDATED
```

Accepted story history is immutable and is not invalidated by a future plan change.

The canonical lineage contract records artifact/version/type, project/Book scope, parents/source versions, accepted boundary, context fingerprint, capability/Skill/model/provider/runtime identity, operation/attempt/trace, qualification state and timestamps.

One canonical dependency edge surface replaces overlapping planning/design/content graph semantics for new writes. It supports semantic dimensions and invalidation policy. Existing tables remain isolated migration inputs/read compatibility until their consumers move; normal runtime must not dual-write competing graphs.

Invalidation flow:

```text
semantic diff
→ dependency traversal
→ stale/impact classification
→ selective invalidation
→ regeneration/requalification
→ owning Authority activation
```

World/Character/Arc changes invalidate only future dependent plans, Intent/Memo, Context and candidates whose semantic inputs changed. Accepted Chapters, Outcomes and their Canon/State/Arc/Obligation evidence remain preserved.

## 15. Book Acceptance transaction

All model work, retrieval, embedding, semantic evaluation and network calls finish before acceptance and produce immutable candidates/evidence.

The short transaction performs only:

- operation/admission/lease/fence and expected-version validation;
- final candidate/gate/evidence lineage validation;
- deterministic ChapterOutcome, Canon, Narrative State, Arc and Obligation reducers;
- authoritative immutable inserts and current-pointer/CAS advancement;
- acceptance/checkpoint rows and outbox.

The logical accepted projection set is:

```text
AcceptedChapter N
+ ChapterOutcome N
+ Canon N
+ NarrativeState N
+ ArcProgress N
+ NarrativeObligationState N
```

Canon/accepted events are the source evidence; projections are deterministic consumers, not competing Authorities. Chapter N+1 admission requires the set to be complete at the same accepted boundary.

## 16. Canonical production chain

```text
User / Studio Intent
→ Design candidates and Story Design Authority
→ Book / Volume / Arc / ChapterGroup planning candidates
→ Planning Authority activation
→ ChapterPlan
→ ChapterExecutionIntent
→ ChapterMemo
→ Context Compilation @ latest complete Accepted Boundary
→ Draft Candidate
→ Review / Revision / Re-review
→ CandidateComparison / BestCandidateSnapshot
→ Provisional Canon + Arc + Obligation evidence extraction
→ Narrative Correctness validation
→ Quality fan-out / aggregate
→ deterministic Release Gate
→ ChapterOutcome preparation
→ atomic Book Acceptance
→ complete accepted projection set
→ outbox / derived memory and retrieval projections
→ asynchronous Reader Outcome / Recap
→ continue / correct / governed future Replan
→ next Chapter
```

## 17. InkOS harvest decision

### TRANSPLANT semantics

- real multi-turn dynamic tool loop;
- Skill guidance does not grant permission;
- committed-request append-only transcript semantics;
- protected/compressible context fail-closed behavior;
- Review/Revision/Re-review and minimum improvement;
- mutation-tool filtering while production is active.

### ADAPT to Novel Forge

- session serialization becomes PostgreSQL lease/fence;
- transcript becomes PostgreSQL append-only events;
- Chapter Intent/Memo become immutable governed working artifacts;
- BM25/rerank expands to PostgreSQL hybrid retrieval;
- best snapshot becomes persisted lineage and rollback evidence;
- Agent action proposals become typed Authority Commands.

### REJECT

- PipelineRunner God Object;
- Writer-owned truth settlement/persistence;
- direct truth-file mutation tools;
- filesystem authority, local lock and rename transaction;
- in-memory scheduler/recovery;
- degraded result automatically becoming current plan/truth;
- blind provider retry without ExternalEffect/Receipt reconciliation;
- a second chat context runtime.

## 18. Legacy and documentation convergence

The implementation will:

- update the canonical design and derived product/runtime views;
- remove the exact-SHA historical implementation plan from current docs;
- remove the obsolete reusable prompt that names the completed liveness package as current priority;
- update stale architecture tests to assert state semantics and follow-up ownership behavior;
- remove or isolate duplicate Agent execution, context, dependency and mutation paths after consumers move;
- never hand-edit `.claude/skills`; root `skills/` remains source of truth.

Historical migrations remain immutable. All persistence changes are forward-only and non-destructive.

## 19. Test and proof boundary

Required in this phase:

- contract/domain invariant tests;
- Arc plan-vs-actual/progress/checkpoint/revision tests;
- accepted-only obligation tests;
- Book Acceptance atomic projection tests;
- Agent Harness tool/budget/cancellation/authority-boundary tests;
- Context protected-budget/hybrid-selection/manifest tests;
- memory boundary/index tests;
- Intent/Memo lineage/consumption tests;
- Best Candidate/minimum-improvement/rollback tests;
- semantic invalidation traversal/selective-regeneration tests;
- repository/migration tests;
- architecture tests and bounded integration smoke tests.

Explicitly out of scope for this phase:

- million-word or multi-volume campaign;
- long-running real-provider qualification;
- multi-book generation/load tests;
- large model-quality benchmark;
- production admission.

Final reporting must distinguish `IMPLEMENTED`, `WIRED`, `UNIT_TESTED`, `SMOKE_TESTED`, `NOT_LONGFORM_PROVEN`, `NOT_PROVIDER_QUALIFIED`, and `NOT_PRODUCTION_QUALIFIED`.
