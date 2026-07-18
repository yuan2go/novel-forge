# Content Authority Runtime Convergence

Updated: 2026-07-18  
Source commit: `c698a36`  
Scope: focused deterministic and PostgreSQL functional proof; no real-provider or long-form run

## Result

Content Intelligence now uses the same fenced PostgreSQL execution envelope as
Chapter Authority. The 22 definitions have explicit codecs and pass a PostgreSQL
fixture that creates Operation, Attempt, frozen input snapshots, qualified
AssetVersion outputs, audit/outbox evidence, and Completion. They are
`integration_proven`, not `production_verified`.

The shared runtime is implemented in `modules/authority_handler_runtime/` and the
content bindings in `modules/content_authority/`. `ContentHandlerCodec` validates the
admitted project, exact ordered frozen input versions, required asset types, and
domain arguments. It never calls a domain function through untyped `**payload`.

## Definition batches

| Batch | Definitions | Status | PostgreSQL evidence |
|---|---:|---|---|
| Creative | 4 | integration_proven | brief, two evaluations, clustering, approved proposal |
| World / Character | 4 | integration_proven | world generation/validation, two characters, relationship |
| Theme / Ending | 6 | integration_proven | question, arc, anti-preaching, closure, payoff, ending gate |
| Long-form | 8 | integration_proven | motivation, merge, foreshadow, rule, power, pattern, debt, recap |

`tests/integration/test_content_authority_runtime_postgres.py` executes 24 Operations
covering all 22 definitions. `tests/integration/test_chapter_authority_runtime_postgres.py`
proves stable output replay at the shared runtime boundary. An incomplete application
replay fails with `CONTENT_OPERATION_RECOVERY_REQUIRED`; the scheduler must resume the
fenced Attempt instead of treating an existing output as completed.

## Context content closure

`ContextBundle` now contains a `context_manifest`, safe `context_segments`, and a
budgeted `stage_context_view`. Context candidates are admitted as real frozen
AssetVersion inputs to `chapter.context.build`; metadata must match those inputs.
`structure_only` produces structural abstraction, evidence-only release assets do not
enter Draft text, and raw/review-only/revoked/stale/quarantined/cross-project data fail
closed. The digest covers actual safe content.

## Re-review, Canon, and Quality

The chapter Saga is now:

```text
Plan -> Context -> Draft -> Review -> Revision -> Re-review
     -> Canon Extraction -> Canon Reduction -> Quality -> Publish Gate -> Export
```

Revision only writes `RESOLUTION_CLAIMED`; Re-review owns `RESOLVED`/`REOPENED` and
`RevisionQualityDelta`. Canon Extraction is independent of Revision provider metadata,
and Reduction checks historical Canon, character, relationship, timeline, foreshadow,
promise, reward, world-rule, and power state.

`ChapterQualityAggregate` has no fixed score 100. Dimensions preserve evidence,
weights, blocking status, calibration, and source. Missing calibration remains
`UNCALIBRATED`; fixture evidence cannot set `production_verified`. Publish Gate
requires Re-review, Canon, source-isolation/leakage, and frozen operator
checklist/approval evidence. Blob verification remains Export Completion evidence
after the pre-export Publish Gate.

## Chapter Production Bus

`ChapterProductionAuthorityAdapter` submits through Chapter Authority and builds a
non-authoritative, rebuildable projection from authoritative queries. The legacy
LocalStorage bus remains for development fixtures. Production calls fail closed with
`LEGACY_CHAPTER_BUS_PRODUCTION_DISABLED` after OS envelope validation.

## Focused verification

- Unit/domain/adapter group: 43 passed, 2 skipped by existing optional guards.
- Context/Source/Chapter group: 24 passed.
- Stateful Canon group: 15 passed.
- PostgreSQL shared chapter runtime: 1 passed.
- PostgreSQL complete chapter Saga: 2 passed.
- PostgreSQL content proof: 1 suite passed, covering all 22 definitions.
- Catalog and coverage evidence regenerated against source commit `c698a36`.

No real provider, 10/30/100-chapter generation, multi-book load, connector network,
or real platform publishing was run.

## Remaining limits

- P0: none found inside the focused deterministic functional slice.
- P1: separately materialize Canon snapshot candidates as AssetVersions; add a
  post-Blob final release gate; add scheduler-driven Content application recovery proof.
- P2: retire development LocalStorage bus steps after all callers use the adapter;
  calibrate quality dimensions with provider/human sets.
- P3: deeper UI and real platform adapters remain deferred.
