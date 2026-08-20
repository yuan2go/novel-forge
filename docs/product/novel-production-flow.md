# Novel production flow

This is a derived product view of [`canonical-overall-design.md`](../architecture/canonical-overall-design.md). It does not define a second architecture and must not upgrade target design to current proof.

## 1. Canonical target flow

```text
Idea / Material / Reader Promise
→ Story / World / Character Design
→ Narrative Threads + Transformation Maps
→ Progressive Structural Plan + Narrative Arc Network
→ Arc Working Set / ChapterArcContributions
→ Narrative Composer
→ active ChapterPlan
→ ChapterExecutionIntent
→ ChapterMemo
→ Context v2 @ complete Accepted Boundary
→ Protected Context + hybrid retrieved evidence
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
→ Next Chapter

Accepted Chapter
└→ Publish → Reader Outcome / Retrospective / MKAOS feedback / Analytics
             └→ governed future-only adaptation
```

The critical path and observation sidecars are intentionally separate.

## 2. Design and planning

The four structures are:

```text
Organization/IP:       Studio → Portfolio → Universe → Series → Book
Narrative containment: Book → Volume → [Narrative Segment] → Chapter → Scene → Beat
Long-form change:      Arc Graph
Production control:    ChapterGroup
```

Arc is an orthogonal cross-time state-transformation graph. Narrative Segment is conditional: it is persisted only if a distinct contiguous dramatic interval has a real consumer independent of Volume, Arc and ChapterGroup. Planning uses lazy expansion: distant future stays strategic; current scopes are more explicit; the next several chapters are tactical; only the next Chapter becomes detailed execution intent/scene work.

`ChapterGroup` is a production/checkpoint construct, not the semantic replacement for Narrative Segment.

## 3. Narrative Arc production

A long-lived Narrative Thread is decomposed into bounded Macro/Meso/Micro Arc transformations. The complete Arc network may be large, but production derives a small working set. A Chapter normally carries one primary Arc contribution, a few secondary/touch contributions, and leaves the remainder dormant.

Arc Scheduler decides **what needs progression now**. Narrative Composer decides **how several required changes can become a small number of natural multi-function events**. Arc Progress only becomes authoritative after Accepted Chapter evidence.

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

## 5. Evidence and Context

Build Context v2 in three stages:

1. protected correctness context that fails closed on budget overflow;
2. task-specific state/evidence retrieval;
3. optional creative/professional enrichment.

Examples: combat retrieves only currently legal skills/weapons/resources/injuries/environment; investigation retrieves relevant clues, known/unknown facts and beliefs. MKAOS enrichment may improve creative realization but cannot create Story Truth.

Retrieval combines lexical/BM25-style full text, embedding, entity/relationship, character timeline, temporal, Arc and Narrative Obligation relevance, rerank and compressible-evidence compression. Provider context must remain bounded as the Book grows; protected entries cannot be silently dropped.

## 6. Chapter production

```text
ChapterPlan + ExecutionIntent + Memo + Production Packet
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

## 10. Feedback

Reader Outcome, quality analytics and long-form retrospective create evidence/proposals. They can affect future scheduling, MKAOS effectiveness evidence or PlanChange/Replan. They cannot directly mutate accepted Canon.

## 11. Proof boundary

Always distinguish:

```text
CODE_IMPLEMENTED
CANONICAL_WIRED
TEST_EXECUTED
RUNTIME_PROVEN
LONGFORM_PROVEN
PRODUCTION_QUALIFIED
```

One successful Chapter is not long-form proof. `LONGFORM_PROVEN` requires bounded autonomous forward progress, accepted-state propagation, context correctness, recovery, and sustained narrative evidence.
