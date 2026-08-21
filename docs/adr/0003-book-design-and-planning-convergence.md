# ADR 0003: BookDesign and Planning Authority Convergence

- Status: Accepted
- Date: 2026-08-04
- Updated: 2026-08-20

## Context

The repository already contains BookDesign Authority, Story Design candidate/qualification lifecycle, hierarchical planning, PlanChange/Replan, Book production, active plan bindings, planning horizon and production cursor. Creating another BookPlan/StoryDesign/Arc Authority would establish competing roots and execution state machines.

The target Canonical Design now also distinguishes the **semantic structural hierarchy** from production scheduling and makes Narrative Arc an orthogonal state-transformation graph.

## Decisions

### 1. BookDesign remains the whole-book design root

The active qualified BookDesign version is the formal root for Book-level future design such as Story Foundation, Reader Promise, ending direction, core world/character constraints, core conflict and commercial positioning. Component proposals do not become a parallel active Book root.

### 2. StoryDesign owns governed candidate generation/qualification, not a second root

StoryDesign may generate and qualify planning/design candidates through the shared production execution plane. Activation remains an explicit owning-domain decision. Provider output never becomes an active plan merely because candidate generation succeeded.

### 3. Hierarchical Planning remains the Plan Authority

No new Plan Authority or parallel BookPlan storage/runtime is introduced. Formal plan activation retains its own transaction/idempotency/version/audit semantics and may record causation from StoryDesign/PlanChange operations.

### 4. Structural narrative semantics and production grouping are distinct

The target model has four orthogonal structures:

```text
Organization/IP:     Studio → Portfolio → Universe → Series → Book
Narrative containment: Book → Volume → [Narrative Segment] → Chapter → Scene → Beat
Long-form change:    Arc Graph
Production control:  ChapterGroup
```

Organizational concepts are not mandatory Aggregate roots. `Narrative Segment` is admitted only when a stable contiguous dramatic interval has a distinct invariant, versioning value and real consumer independent of Arc, Volume and ChapterGroup. The audited baseline has no such consumer, so convergence must not add a Segment persistence/Authority layer merely to complete the tree.

`ChapterGroup` remains a scheduling/checkpoint/planning coordination construct. Scene is an addressable/versioned Chapter child whose outcome is accepted with its Chapter; Beat remains embedded unless a real independent lifecycle appears.

### 5. Arc remains orthogonal to containment

Arc is a cross-time desired state-transformation dimension. A Chapter may contribute to several Arcs; an Arc may cross Volume boundaries. The target may progressively enrich Arc semantics with Threads, scoped Macro/Meso/Micro transformations, relations, obligations, working-set scheduling and progress evidence, but these extend the existing Plan Authority rather than create an Arc-specific workflow/Authority plane.

### 6. Planned Arc graph is not Story Truth

Arc/Plan relations describe future intent. Important realized causality and Arc progress are established only through accepted Chapter Outcome/Narrative State evidence. Future Replan may split/merge/spawn/supersede planned Arcs; accepted history is immutable.

The Arc contract family distinguishes `ArcPlan`, `ArcActualState`, `ArcProgress`, `ArcOutcome`, `ArcCheckpoint` and future-only `ArcRevision`. Missing actual evidence is explicit `NOT_OBSERVED`, `NOT_MATERIALIZED` or `UNKNOWN`; ChapterPlan declarations are never promoted to `ACTUAL`.

### 7. Book Acceptance owns the complete Chapter truth boundary

All model calls, retrieval, embedding and semantic evaluation finish before acceptance. The short Book Acceptance transaction performs only fence/CAS and lineage validation, deterministic reducers, authoritative writes/current-pointer advancement and outbox. One accepted boundary logically completes Chapter, ChapterOutcome, Canon, Narrative State, ArcProgress and Narrative Obligation state before Chapter N+1 drafting may start.

### 8. Cross-domain reads remain versioned/frozen

Planning may consume frozen AssetVersion/query/snapshot contracts. Book coordination may consume Planning projections/cursors. Neither domain imports another domain's concrete repository to assemble private mutable truth. Quality/Agents emit evidence or proposals and cannot directly mutate Planning/Chapter/Canon state.

## Consequences

- No `Book → Volume → Arc → Chapter` containment model is introduced as the canonical hierarchy.
- No second Story/Plan/Arc runtime is justified by the richer Narrative Arc OS target.
- No Narrative Segment root is created until code/runtime evidence proves its independent consumer and lifecycle.
- Progressive planning can preserve distant open design space while elaborating near-term Arc/Chapter detail.
- Current implementations/tests remain evidence of current semantics only; this ADR does not establish real-provider or long-form proof.
