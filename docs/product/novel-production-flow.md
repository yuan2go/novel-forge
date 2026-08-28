# Novel production flow

This is a derived product view of [`canonical-overall-design.md`](../architecture/canonical-overall-design.md). It does not define a second architecture and must not upgrade target design to current proof.

## 1. Canonical target flow

```text
Idea / Material / Reader Promise
→ Creative Exploration (several materially distinct foundations)
→ evaluation / comparison / approval
→ Qualified Creative Foundation + Theme / Ending / Reader Promise
→ Qualified WorldBible
→ Qualified CharacterCast
→ Qualified BookDesign synthesis/reference contract
→ Narrative Threads + Transformation Maps
→ bounded Book / Volume / Arc future search
→ selected Progressive Structural Plan + Narrative Arc Network
→ Arc Working Set / ChapterArcContributions
→ qualified / approved / frozen causal Narrative Realization
→ active ChapterPlan
→ ChapterExecutionIntent
→ ChapterMemo
→ governed Context @ complete Accepted Boundary
→ PROTECTED / RETRIEVABLE / COMPRESSIBLE / EPHEMERAL evidence
→ Chapter Production Packet
→ Scene Plan
→ immutable Draft Candidate
→ Review / Revision / Re-review
→ CandidateComparison / BestCandidateSnapshot
→ Provisional Canon / Arc / Obligation extraction
→ Narrative Verification
→ Quality Gate
→ ACCEPT
→ AcceptedChapterOutcome
→ Canon + Narrative State + Arc Progress + Obligation State
→ re-evaluate affected future commitments
→ maintain plan or open a new bounded search
→ Next Chapter

Accepted Chapter
└→ Publish → Reader Outcome / Retrospective / MKAOS feedback / Analytics
             └→ governed future-only adaptation
```

The critical path and observation sidecars are intentionally separate.

## 2. Design and planning

A Book is ready for production only when exact active qualified Creative
Foundation, Theme Contract, Ending Intent, Reader Promise, WorldBible,
CharacterCast and BookDesign v5 reference bindings, a qualified Book/Volume/Arc
baseline, initial accepted boundary and required operational profiles resolve
to one immutable Book Production input snapshot. BookDesign does not copy
World/Character truth. Individually callable content generators are not an
opening flow, and an HTTP request may only admit/query/control the durable
formation/opening Operation.

At Book/Volume/Arc and consequential ChapterGroup decisions, Planning explores
a small number of immutable alternatives from the same frozen parent state.
Each alternative carries assumptions, consequences, opportunities, risks,
irreversible choices, creative-intelligence signals and remaining optionality.
Only independently qualified candidates enter deterministic comparison. Search
selection is evidence for the normal approval/activation gates; it does not
replace them.

### Book Opening execution and recovery

Book Opening is the business/recovery Authority for the bounded Book/Volume/Arc
search that establishes the production input snapshot. RuntimeJob remains its
operational plane. An Opening is not meaningfully `RUNNING` unless its current
execution generation is durably bound to the exact RuntimeJob, Attempt, Lease
and fencing token used by the worker.

The execution path is:

```text
ADMITTED generation N
→ exact RuntimeJob claim and execution binding
→ RUNNING
→ append-only semantic progress/evidence checkpoints
→ COMPLETE
```

An expired lease, lost fence or disappeared executor cannot be continued by
ordinary RuntimeJob takeover. The formal loss path is:

```text
active execution N
→ immutable loss assessment
→ Attempt / Lease / RuntimeJob / execution N terminal convergence
→ BookOpening FAILED
→ loss convergence receipt
```

Loss convergence only explains and terminalizes the failed execution; it does
not authorize replacement. A later `recover` uses a fresh immutable assessment
and one database admission transaction to create its RecoveryIntent, any safe
semantic-evaluation replacement generation, the next RuntimeJob, the
`FAILED -> ADMITTED` transition, events/outbox and RecoveryReceipt. Provider
work, if newly authorized, occurs only afterward through the normal governed
worker path.

Book Opening checkpoints are an append-only, hash/version-bound cursor over
exact durable evidence owned by Search, Planning and Story Design Authorities.
They identify the deterministic resume point and can be reprojected after a
crash, but they do not copy candidate eligibility, search status, Planning
activation or qualification truth.

A terminal semantic-evaluation Operation is never reopened. Where its
ExternalEffect is `PROVEN_NO_EFFECT` or otherwise conclusively safe under the
governed retry policy, recovery may append evaluation generation N+1 with
explicit predecessor lineage and a generation-aware Operation identity. A
verified successful Effect is consumed through durable output replay; an
`UNKNOWN_AMBIGUOUS` Effect blocks recovery pending reconciliation. Evaluation
generation owns execution lineage only; Story Design and Planning remain the
qualification and activation Authorities.

The four structures are:

```text
Organization/IP:       Studio → Portfolio → Universe → Series → Book
Narrative containment: Book → Volume → [Narrative Segment] → Chapter → Scene → Beat
Long-form change:      Arc Graph
Production control:    ChapterGroup
```

Arc is an orthogonal cross-time state-transformation graph. Narrative Segment is conditional: it is persisted only if a distinct contiguous dramatic interval has a real consumer independent of Volume, Arc and ChapterGroup. Planning uses lazy expansion: distant future stays strategic; current scopes are more explicit; the next several chapters are tactical; only the next Chapter becomes detailed execution intent/scene work.

`ChapterGroup` is a production/checkpoint construct, not the semantic replacement for Narrative Segment.

Before ChapterPlan generation, the same Hierarchical Planning Authority must
qualify, approve and freeze a typed Narrative Realization for the relevant
ChapterGroup/Arc intent. It is a causal correctness proof, not a new Plan scale
and not accepted actual. ChapterPlan binds only its exact event slice; accepted
Chapter outcomes consume that slice, while a multi-Chapter realization remains
partially covered until all required events have accepted evidence.

## 3. Narrative Arc production

A long-lived Narrative Thread is decomposed into bounded Macro/Meso/Micro Arc transformations. The complete Arc network may be large, but production derives a small working set. A Chapter normally carries one primary Arc contribution, a few secondary/touch contributions, and leaves the remainder dormant.

Arc Scheduler decides **what needs progression now**. Narrative Composer decides **how several required changes can become a small number of natural multi-function events**. Arc Progress only becomes authoritative after Accepted Chapter evidence.

In the current runtime the Book Supervisor asks a deterministic domain service
for this working set at the exact accepted boundary. Static ChapterGroup cadence
is a preferred bounded window and is corrected against the current VolumePlan
boundary when necessary to preserve the legal three-to-eight Chapter contract
without leaving a one- or two-Chapter fragment. The resulting exact range,
desired transformation and hard constraints are copied from Search Authority
into every branch's admitted generation command, Context Bundle, Provider
request and retry snapshot. The candidate range, Chapter Function Matrix and
realization-event coverage must match that frozen range. Historical executed
groups may remain current immutable records, but only one non-overlapping group
may cover the active cursor. Chapter planning must cover the selected Arcs in
its schedule, required contributions and Scene event graph; production admission
recomputes the same working set and fails closed on drift.

## 4. ChapterExecutionIntent and ChapterMemo

The active ChapterPlan remains authoritative. Before prose, establish immutable working artifacts describing at least:

- narrative purpose and entry state;
- required beats/outcome;
- forbidden changes;
- active Arc contributions/obligations;
- character and reader knowledge boundaries;
- reader-effect/hook intent;
- expected exit state.

ChapterExecutionIntent freezes the exact Plan interpretation and accepted boundary. ChapterMemo supplies execution-time creative strategy and retrieval needs. Neither may modify/activate the Plan, and an unqualified degraded fallback cannot reach Draft.

The current Intent compiles one Mission fingerprint and causal multi-function
event graph from the active ChapterPlan. Memo directives and Context execution
expectations must bind that exact Mission/Scene/Arc set, so Context no longer
bypasses the Intent by independently interpreting the Plan.

## 5. Evidence and Context

Build governed Context only after the Memo has produced its frozen query inputs:

```text
ChapterPlan
→ ChapterExecutionIntent
→ qualified ChapterMemo
→ Retrieval Query Plan
→ chapter.context.retrieve
→ immutable RetrievalResult
→ chapter.context.build
→ Draft
```

The Book command freezes the accepted boundary, protected Authority refs and
retrieval policy. It does not preselect historical prose before Memo. The
Retrieval Operation freezes every selected candidate AssetVersion and records
selected/rejected documents, ranking evidence and a result fingerprint so the
Context build is replayable.

Context Manifest v3 records four enforceable classes across three compilation stages:

1. PROTECTED correctness context that cannot be omitted/compressed and fails closed before Provider execution when it alone exceeds budget;
2. RETRIEVABLE task-specific state/evidence and COMPRESSIBLE evidence with source/compression provenance;
3. optional creative/professional enrichment, including EPHEMERAL input that is excluded from Memory/Search but frozen when sent to a Provider.

Examples: combat retrieves only currently legal skills/weapons/resources/injuries/environment; investigation retrieves relevant clues, known/unknown facts and beliefs. MKAOS enrichment may improve creative realization but cannot create Story Truth.

Retrieval first combines PostgreSQL Full-Text Search (`to_tsvector`,
`plainto_tsquery`, `ts_rank`) with exact entity/relationship, character
timeline, temporal, Arc and Narrative Obligation channels. This creates the
bounded legal candidate set. Compatible vector similarity may rerank only that
set and cannot add another document; when unavailable, lexical/structured
ranking is the deterministic fallback. This is PostgreSQL FTS ranking, not
BM25. Provider context must remain bounded as the Book grows.

Acceptance also rebuilds Recent Trail and Hook Debt projections from the same
accepted outcome/state evidence. Authoring APIs and the Chapter Transaction
Workspace expose them alongside immutable Chapter artifacts and current stale
future-plan evidence without acquiring Canon, State, Planning or Acceptance
Authority.

## 6. Chapter production

```text
ChapterPlan + ExecutionIntent + Memo
→ RetrievalResult + Context Manifest / Production Packet
→ Scene Plan
→ Draft Candidate
→ Review / bounded Revision / Re-review
→ Best Candidate
→ Provisional extraction
→ Narrative Verification
→ required Quality
→ Acceptance
```

Narrative Verification checks Mission completion, forbidden changes, Canon/state legality, knowledge leakage, temporal/spatial/resource legality, required obligation/Arc handling, and source-expression constraints as applicable.

## 7. Accepted outcome

Acceptance is the internal truth boundary:

```text
Final candidate
→ ACCEPT
→ immutable Accepted Chapter
→ AcceptedChapterOutcome
→ Canon/Narrative Events
→ Narrative State transition
→ Arc Progress / Obligation State
→ retrieval/summary/index projections
```

All model/retrieval/evaluation work completes before acceptance. The short PostgreSQL transaction runs deterministic reducers and commits the complete Chapter/Outcome/Canon/State/Arc/Obligation boundary. Chapter N+1 cannot start formal drafting until that set is complete.

Summaries, recaps, embeddings and indices are derived and rebuildable; they never replace accepted evidence.

External publication happens only after internal acceptance.

## 8. Chapter-to-Chapter liveness

Default blocking path:

```text
Accepted N
→ required Canon/State commit
→ next planning/admission eligibility
→ dispatch N+1
```

Reader Outcome, recap/long-form analytics, MKAOS feedback, calibration and other advisory work are asynchronous by default. They may block only through an explicit persisted `HARD_BLOCKING` governance decision.

A nonterminal Book must never remain unchanged for hours without a durable reason and recovery/wake condition.

## 9. Source/MKAOS use

Sources are not a plot-parts bin. The reusable path is:

```text
source-specific observation
→ abstraction
→ generalized narrative/domain mechanism
→ governed selection
→ project-specific creative recomposition
```

MKAOS may offer conflict, transformation, payoff, mystery, world-causality, theme/dilemma, reader-experience and scene patterns. The Arc/Scene Architect composes them under the current Book's constraints instead of copying a source-specific sequence.

Current Book/Volume/Arc/ChapterGroup/Chapter Planning uses a structured,
bounded MKAOS selection frozen in Planning Context. Recent selection lineage
feeds repetition-risk keys into later selection; this is not an effectiveness
or Reader-learning Authority.

## 10. Feedback

Reader Outcome, quality analytics and long-form retrospective create
evidence/proposals. Reader Outcome v3 carries continue intent, curiosity,
satisfaction, confusion, trust, character attachment, antagonist pressure,
promise expectation, payoff satisfaction, drop risk and repetition fatigue.
The accepted Chapter sequence, not an LLM summary, is the lineage root.

The reachable advisory path is:

```text
Accepted Chapter
→ Reader Outcome
→ longitudinal Reader State
→ Recap / trend evidence
→ bounded future recommendation or Replan proposal
```

It may affect future scheduling, MKAOS effectiveness evidence or a governed
PlanChange/Replan. It cannot directly mutate accepted Canon/Narrative State,
rewrite executed plans or turn a proposal into actual story state.

## 11. Quality Qualification

Internal Chapter acceptance and campaign-level Quality Qualification are
different decisions. Qualification persists three non-collapsible evidence
layers:

```text
L1 Hard Narrative Correctness
L2 Editorial / Literary Quality
L3 Reader / Longitudinal Outcome
```

A severe L1 failure cannot be averaged away. Chapter evidence answers whether
one Chapter is correct/effective/continue-worthy. Arc evidence measures causal
progress, interaction, escalation, setup/payoff and transformation. A bounded
Volume-slice report interprets multi-Arc rhythm, long promises, payoff
distribution, fatigue, cumulative evolution and ending reachability; it never
averages Chapter scores into a Volume score.

The canonical bounded comparison uses each Chapter's first draft as a
comparable baseline and its accepted revision as the Canonical candidate. Human
reviewers receive balanced blinded A/B pairs and cannot see Candidate identity,
Provider/model, Prompt, branch, Judge or system score. Two reviewers over eight
Chapter pairs plus the same Arc sequence provide bounded human preference
evidence only. One valid reviewer is `HUMAN_EVIDENCE_LIMITED`; incomplete human
work remains `WAITING_HUMAN_EVIDENCE / NOT_PROVEN`. A model must not fill a
human evidence gap.

Reader Outcome is advisory evidence, and automated Judge evidence records its
independence relationship. Same-model generation and judging cannot by itself
prove literary quality. Final statuses are `PASS`, `PASS_WITH_LIMITATIONS`,
`FAIL` and `NOT_PROVEN`.

## 12. Proof boundary

Always distinguish:

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
LONGFORM_PROVEN
PRODUCTION_QUALIFIED
```

One successful Chapter is not long-form proof. Eight accepted Chapters are
bounded Arc/Volume-slice evidence, not proof of autonomous million-word quality,
commercial success or Production Admission. `LONGFORM_PROVEN` requires bounded
autonomous forward progress, accepted-state propagation, context correctness,
recovery and sustained narrative evidence at the exact scope claimed.
