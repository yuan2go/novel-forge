# Development Gap Final Convergence Design

## Baseline and evidence order

This design targets `origin/main` at
`919536482df802404c66967c4b05ba87e34f5b0b`, with migration head
`20260812_0083_narrative_runtime_convergence`. Current code, PostgreSQL
constraints, production composition, and executable tests are authoritative;
historical documents are not acceptance evidence.

## Reassessment

### Source analysis identity: partially present

`SourceContentProfile`, `SourceAnalysisPlan`, `AnalysisTask`, Observation, and
MKAOS extraction already freeze most input and methodology identities. Analyzer
fingerprints include Skill version and exact root `SKILL.md` content hash, and
Observation/MKAOS reuse checks bind downstream lineage.

The remaining defect is before Analysis Plan Authority: the Source Import
analysis-planning child is admitted from only Profile AssetVersion and routing
policy. The resolved strategy is loaded later by the worker. A Skill or profile
change between admission and execution can therefore run under an Operation
identity that did not admit that strategy. The fix freezes the complete resolved
strategy at child admission and uses its existing `strategy_contract_hash` as
the one Analysis Strategy Fingerprint. No duplicate fingerprint column is
introduced.

The identity equation is:

```
LogicalDocument/Profile AssetVersion
+ Analysis Strategy Fingerprint
+ governed AnalysisPlan AssetVersion
= Analysis Task and Observation identity
```

The strategy fingerprint freezes resolved content type, profile id/version,
routing policy, analyzer/prompt/schema contract, Skill id/version/content hash,
Capability id/version, provider and aggregation policy, window limits, MKAOS
Capability, and abstraction policy. Classifier identity remains the owner of
Profiling invalidation; Source Snapshot/Transform/Chunk identities remain
content and transform-policy identities.

### Narrative measurement plumbing: confirmed

`measure_narrative_runtime()` currently defaults absent planning, MKAOS, and
provider evidence to empty collections and writes numeric zero. The production
Quality handler supplies none of those inputs. This is a false-zero bug.

Measurement v2 uses explicit observation states (`MEASURED`, `NOT_OBSERVED`,
`NOT_AVAILABLE`, `NOT_APPLICABLE`) and nullable metric values. The Quality
Operation freezes the active ChapterPlan plus upstream Provider evidence assets
that consumed its exact ContextBundle. Existing `model_call_log`, `cost_ledger`,
ExternalEffect, Attempt, Operation, and Context assets remain the owners;
measurement only derives an observation.

The existing distance heuristic is renamed to “long-distance context selected”.
Recall and precision are only measured when a deterministic expected relevant
set is supplied; otherwise they are explicitly not observed.

### Corrective action lifecycle: partially present

Review→Revision→Re-review and Longform Recap→Replan→PlanChange→Activation each
retain useful local lineage, but there is no cross-domain query contract and no
authoritative resolution link for Quality/Reader/Longform issues.

Migration 0084 adds the smallest common contract:

- `authority_corrective_action_lineage_projection`, derived from successful
  Review, Quality, Reader Outcome, Longform Recap, Revision, Re-review, Replan,
  and PlanChange Authority records;
- `authority_book_replan_reevaluation`, the one new fact that could not be
  derived from existing evidence: whether a later narrative-position Recap
  resolved or escalated an activated Replan.

Existing Chapter and Book operations execute the work; the shared projection
does not schedule, retry, lease, fence, approve, or mutate plans. A read-only
query returns the complete lineage. Reader evidence remains future-only and can
never mutate accepted body, Canon, or executed plans.

### MKAOS runtime consumption: partially present

Migration 0083 derives Context and MKAOS usage when any successful Operation
references a ContextBundle. That proves selection and downstream reference, not
Provider consumption.

Migration 0084 separates:

- selection: a KnowledgePack was frozen in a successful Context Manifest;
- consumption: a successful model ExternalEffect, the frozen Attempt reference,
  matching Context identity in the Provider request, and a generated/reviewed
  result all exist. Capability Pack snapshot identity is exposed when the
  consuming Attempt used a deployed Pack.

The consumption projection references existing identities and receipts instead
of copying Provider accounting. It exposes Chapter/position, Capability,
Capability Pack, Operation, Attempt, ExternalEffect, route/model, Context,
KnowledgePack/Card, trace, and result lineage. Token/cost/retry observations stay
derived from their existing Provider evidence assets in Narrative Measurement.

## Runtime wiring

```
Source Import admission
  -> frozen Analysis Strategy Fingerprint
  -> existing AnalysisPlan Authority
  -> existing deconstruction/MKAOS Operations

Chapter Saga
  -> ChapterPlan + Context
  -> Provider-backed Draft/Review/Revision/Quality-group Operations
  -> immutable model_call_log/cost_ledger
  -> Quality input snapshot
  -> NarrativeRuntimeMeasurement v2

Successful Authority outputs
  -> corrective lineage projection
  -> existing Revision or Book Replan/PlanChange execution
  -> later Quality or Longform re-evaluation
  -> resolution projection

Context Manifest selection
  + successful Provider ExternalEffect/Attempt/Capability snapshot
  + result AssetVersion
  -> MKAOS consumption projection
```

## Failure and replay rules

- Admission freezes identities before worker execution.
- Existing Operation/Attempt/Lease/Fence and ExternalEffect idempotency remain
  the only durable execution controls.
- Book Replan re-evaluation uses deterministic keys, Command Kernel replay, and
  database uniqueness; the other corrective states remain projections over
  existing immutable Authority evidence.
- MKAOS consumption is a deterministic projection over immutable evidence, so
  retry/replay cannot create duplicate logical receipts.
- Missing evidence never becomes zero and never promotes proof status.
- No implementation in this work may claim long-form, multi-book, real-provider,
  or production proof.
