# ADR 0003: BookDesign and Planning Authority Convergence

- Status: Accepted
- Date: 2026-08-04
- Implementation baseline: `d58710de6d4efa51e935df39176167d127b29ea9`

## Context

The repository already contains BookDesign Authority, Story Design Authority,
Content Authority, hierarchical planning, PlanChange Authority, Book Authority,
`story_plan_binding`, `active_story_plan_version`, `planning_horizon`, and
`story_production_cursor`. Creating another BookPlan or Story Design subsystem
would introduce a third active root and another execution state machine.

The code review also confirmed that `bind_active_contract()` previously copied
the Operation that last activated a StoryDesign AssetVersion into Planning's
formal binding and activation rows. That made two different authoritative state
changes appear to be one Operation and provided no Planning-specific expected
version, decision, audit, or outbox boundary.

## Decision

### BookDesign is the unique whole-book design root

The active BookDesign AssetVersion is the only formal root for the book's:

- Theme and thematic question;
- Reader Promise;
- Ending contract;
- World constraints;
- Character core;
- Core conflict;
- Commercial positioning.

`authority_book.current_design_asset_version_id` and the active BookDesign
projection identify that root. Theme, ending, world, character, or commercial
candidates produced elsewhere are evidence or proposals until a BookDesign
Transaction Command incorporates and activates them. They cannot establish a
parallel active book root.

### StoryDesign owns candidate lifecycle, not the BookDesign root

Story Design Authority retains:

- versioned `GeneratorDefinition` records;
- candidate enrollment and materialization evidence;
- structural and semantic validation;
- bounded repair and qualification;
- approval lifecycle;
- activation of a typed planning candidate by logical key.

Its `book_plan.generate`, `volume_plan.generate`, `arc_plan.generate`,
`chapter_group_plan.generate`, and `chapter_plan.generate` definitions produce
planning candidates. Its theme, ending, world, and character definitions may
produce component proposals, but those proposals do not replace the active
BookDesign root. A C1 BookPlan candidate must explicitly depend on the active
BookDesign AssetVersion.

### Content Authority is a deterministic handler runtime

Content Authority admits typed Operations and executes registered deterministic
handlers through the shared Command Kernel Attempt/Lease/Fence runtime. It may
materialize candidate or receipt AssetVersions, but it does not own StoryDesign
approval state, Planning activation, a second workflow graph, or a second
scheduler authority. `ContentAuthorityScheduler` is a worker-facing adapter to
the shared runtime, not an independent workflow engine.

### Hierarchical Planning remains the Plan Authority

The existing Planning tables and module remain authoritative. No new Plan
Authority or parallel BookPlan tables will be created.

Containment uses:

```text
Book → Volume → ChapterGroup → Chapter
```

Arc uses the orthogonal-track model:

```text
Arc --ARC_CONTRIBUTION--> Volume / Chapter
```

An Arc can cross volumes and a chapter can contribute to multiple arcs. Arc is
therefore not a containment parent between Volume and ChapterGroup. The current
validator, dependency projection, and PostgreSQL test
`test_arc_crosses_volumes_and_chapter_contributes_to_multiple_arcs` already
implement this meaning. Book Coordinator consumes the versioned Planning read
model; it must not reconstruct containment or arc semantics itself.

### Formal Plan Binding has its own Transaction Command

`planning.binding.activate` is the only formal path for a new active Planning
binding. It has its own:

- idempotency key and request digest;
- authenticated Principal and Project/Book scope;
- expected active AssetVersion;
- replacement decision evidence;
- Operation and completion contract;
- Planning mutation, active projection, audit, and outbox event;
- causation reference to a StoryDesign or PlanChange Operation.

All of these records commit in one PostgreSQL transaction. The command creates
no Attempt or Lease. `created_by_operation_id` and
`activated_by_operation_id` now refer to the Planning Operation rather than the
StoryDesign Operation. A same-key replay returns the committed result; a fault
after outbox insertion rolls back Operation, binding, activation, audit, and
outbox together.

### Cross-domain reads

Planning may consume frozen AssetVersion references and versioned query or
snapshot contracts. Book Coordinator may consume Planning projections and
cursors. Neither may import another domain's concrete repository to assemble
private state. Quality can emit evidence or decisions but cannot mutate Chapter
or Planning rows directly.

## C1 dependency contract

If the C1 gate later passes, the existing `book_plan.generate` path will create
a typed BookPlan candidate with explicit dependencies on:

- `active_book_design_asset_version_id`;
- `generator_definition_version`;
- `context_manifest_version`;
- `route_snapshot`;
- `provider_receipt`.

Qualification and StoryDesign approval precede the independent
`planning.binding.activate` command. The existing Planning projection and
PlanChange path are reused.

## Current constraints and consequences

- This ADR is accepted as the convergence decision; it is not evidence that C1
  or real-provider generation has run.
- Older StoryDesign and PlanChange lifecycle applications still use synchronous
  facades over worker-classified Content operations. They are not new C1
  production entries and must not be exposed as inline HTTP worker execution.
  C1 must admit and let a worker claim them, or explicitly reclassify a purely
  deterministic transition as a Transaction Command.
- PostgreSQL scope constraints from Migration 0052 reject cross-Project,
  cross-Book, and mismatched Workspace/Book planning links.
- C1 remains blocked while the real D0 Provider gates are false.
