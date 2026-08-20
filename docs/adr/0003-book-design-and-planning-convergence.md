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

The **target semantic hierarchy** is:

```text
Book → Volume → Narrative Segment → Chapter → Scene → Beat
```

The **current production implementation** may use `ChapterGroup` as a scheduling/checkpoint/planning execution construct. `ChapterGroup` is not redefined as Narrative Segment merely to make the trees match. Convergence should map/extend existing planning only when the target semantic distinction has real runtime value; do not create a duplicate hierarchy by default.

### 5. Arc remains orthogonal to containment

Arc is a cross-time desired state-transformation dimension. A Chapter may contribute to several Arcs; an Arc may cross Volume boundaries. The target may progressively enrich Arc semantics with Threads, scoped Macro/Meso/Micro transformations, relations, obligations, working-set scheduling and progress evidence, but these extend the existing Plan Authority rather than create an Arc-specific workflow/Authority plane.

### 6. Planned Arc graph is not Story Truth

Arc/Plan relations describe future intent. Important realized causality and Arc progress are established only through accepted Chapter Outcome/Narrative State evidence. Future Replan may split/merge/spawn/supersede planned Arcs; accepted history is immutable.

### 7. Cross-domain reads remain versioned/frozen

Planning may consume frozen AssetVersion/query/snapshot contracts. Book coordination may consume Planning projections/cursors. Neither domain imports another domain's concrete repository to assemble private mutable truth. Quality/Agents emit evidence or proposals and cannot directly mutate Planning/Chapter/Canon state.

## Consequences

- No `Book → Volume → Arc → Chapter` containment model is introduced as the canonical hierarchy.
- No second Story/Plan/Arc runtime is justified by the richer Narrative Arc OS target.
- `Narrative Segment` and `ChapterGroup` stay semantically distinct until code/runtime evidence justifies a concrete convergence mapping.
- Progressive planning can preserve distant open design space while elaborating near-term Arc/Chapter detail.
- Current implementations/tests remain evidence of current semantics only; this ADR does not establish real-provider or long-form proof.
