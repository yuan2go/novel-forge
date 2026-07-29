# Story Design Asset Authority

Status: `documented=true`, `implemented=true`, `handler_bound=true`,
`fixture_proven=true`, `integration_proven=true`,
`real_provider_proven=false`, `longform_proven=false`,
`production_verified=false`.

The implementation introduces one shared semantic authority for Creative,
Theme, Ending, World, Character, BookPlan, VolumePlan, ArcPlan,
ChapterGroupPlan and ChapterPlan candidates. It reuses the existing
PostgreSQL Command Kernel, Operation, Saga, Attempt, AssetVersion, audit and
outbox infrastructure; it does not add a second execution or asset store.

## Governed lifecycle

`story_design.lifecycle.transition` freezes the candidate AssetVersion and
executes through the existing Attempt scheduler. The semantic state dimensions
remain separate:

- lifecycle: candidate, materialized, active, superseded or rejected;
- qualification: pending, structurally valid, semantically valid, qualified or
  failed;
- approval: not requested, pending, approved or rejected;
- freshness: current, impacted or stale;
- planning scope: Book, Volume, Arc, ChapterGroup or Chapter.

Activation requires qualification and approval and atomically supersedes the
previous active semantic version for a logical key. Generated enrollment
requires Operation, Attempt, RouteSnapshot, InputManifest, validation, usage and
cost evidence. Legacy imports require an Authority Operation reference and
remain candidates until the same qualification and approval lifecycle is
completed.

Structural regeneration and semantic repair counts are stored and bounded by
the registered immutable `GeneratorDefinition`. A definition version cannot be
silently rebound to different semantics.

## Evidence boundary

`tests.integration.test_story_design_authority_postgres` proves the lifecycle,
single-active invariant, bounded repair, PEP evidence contract and legacy
import boundary with explicitly labelled fixture evidence. It does not prove a
real provider, real Codex execution or production operation.

The physical test AssetVersion is inserted as an eligible fixture asset so the
existing Command Kernel can freeze it. Its semantic Story Design status is
independently governed by the tables introduced in migration 0038; fixture
storage lifecycle must not be interpreted as semantic activation.
