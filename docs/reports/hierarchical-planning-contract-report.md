# Hierarchical Planning Contract

Status: `documented=true`, `implemented=true`, `handler_bound=true`,
`fixture_proven=true`, `integration_proven=true`,
`real_provider_proven=false`, `longform_proven=false`,
`production_verified=false`.

Migration 0039 adds typed references over existing Authority AssetVersions. It
does not copy complete plan payloads into a second plan store.

## Model

The containment tree is:

```text
BookPlan
└─ VolumePlan
   └─ ChapterGroupPlan
      └─ ChapterPlan
```

ArcPlan is intentionally not a containment node. Typed
`asset_dependency_edge` rows represent Arc-to-Volume scope and
Arc-to-Chapter contribution, so one Arc can cross Volumes and one Chapter can
contribute to multiple Arcs.

All plan contracts share objective, entry/exit state, hard/soft constraints,
required/forbidden events and payoffs, state deltas, Arc contribution, Canon
dependencies, quality target, budget and context policy fields. Type-specific
validators enforce Book, Volume, Arc, ChapterGroup and Chapter semantics.
ChapterGroup contains three to eight chapters.

`ChapterFunctionMatrix` requires one primary function per chapter plus bounded
secondary functions, state progress, Arc contribution, promise, foreshadow,
reward and ending-hook intent. Three consecutive identical primary functions
or ending hooks fail closed.

## Authority invariants

- A binding requires an active Story Design AssetVersion.
- Volume, ChapterGroup and Chapter bind an exact parent AssetVersion.
- Exactly one active plan version exists per project, book and logical key.
- Replacing a Frozen plan requires explicit Authority approval.
- Executed plans cannot be replaced.
- Previous replaceable bindings become stale; historical AssetVersions remain.
- Planning horizon rows enforce executed ≤ frozen ≤ planned ≤ speculative.
- Hierarchy and dependency rows reference existing Authority AssetVersions.
- Binding emits audit, state event and outbox evidence under the governing
  Story Design activation Operation.

## Evidence

- `tests.unit.test_hierarchical_planning`
- `tests.integration.test_hierarchical_planning_postgres`

The PostgreSQL tests prove the Book→Volume→ChapterGroup→Chapter hierarchy,
exact parent binding, Arc cross-volume edges, multi-Arc chapter contribution,
single-active replacement, Frozen approval and Executed immutability. The test
assets use explicitly labelled fixture PEP evidence; no real provider or
long-form production claim is made.
