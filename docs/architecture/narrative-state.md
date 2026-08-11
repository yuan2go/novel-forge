# Narrative state

Novel Forge separates narrative truth, accepted chapter consequences, reduced state, temporal reads, generation context, and reusable knowledge. They are related but not interchangeable.

| Concept | Responsibility | May mutate authority? |
|---|---|---|
| Canon | Validates candidate facts and continuity changes against accepted narrative evidence; emits governed Canon decisions/snapshots. | Only through Canon/Chapter acceptance authority. |
| ChapterOutcome | Immutable summary of one accepted chapter: plan/release/quality lineage plus occurred events and typed deltas. | No; it is accepted evidence. |
| StoryState | Deterministic reduction of ordered ChapterOutcome versions across timeline, characters, relationships, world, resources, promises, debts, and arcs. | Only its owning acceptance path persists versions. |
| Temporal Query | Read-only, as-of-chapter projection over accepted snapshots and event evidence. | Never. |
| ContextBundle | Immutable, budgeted selection of versioned assets sent to a specific production stage. | No; it records selection and isolation. |
| Knowledge | Abstract, evidence-linked reusable principles, constraints, conflict generators, and checks produced through MKAOS. | MKAOS Authority governs candidate approval and pack construction. |

## Acceptance boundary

A draft or model response is not narrative truth. After Chapter gates pass, Canon extraction produces candidates and conflict evidence. The acceptance path freezes the accepted revision, Canon decision, quality and release evidence, then constructs a `ChapterOutcome`. StoryState reduction is deterministic, append-only by outcome version, and idempotent.

## Temporal semantics

Temporal Query returns only evidence accepted by or before the requested chapter. The boundary is inclusive. Supersession lineage is applied without rewriting history, and missing state is an explicit result rather than an invented default. The service is a read model and cannot activate, supersede, or roll back an asset.

## Context semantics

Context building selects versioned candidates by stage profile, project scope, relevance, source risk, and token budget. Required asset types must be present; forbidden source content and raw-source ratios fail closed. The ContextBundle records what was selected, rejected, and sent. It does not become Canon merely because a model saw it.

## Feedback and replan

Reader outcomes and recaps are evidence. They may request a replan, but cannot rewrite active plans. Book coordination resolves the request, PlanChange Authority decides/activates governed semantic changes, and future frozen inputs are rebound with explicit lineage.
