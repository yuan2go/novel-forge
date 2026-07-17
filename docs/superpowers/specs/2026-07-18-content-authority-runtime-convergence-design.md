# Content Authority Runtime Convergence Design

Date: 2026-07-18  
Status: approved by the user task contract  
Scope: PostgreSQL authority convergence only; no real-provider or long-form generation runs

## Decision

Novel Forge will use one PostgreSQL authority execution envelope for chapter and
content-intelligence handlers. The existing Command Kernel remains the execution
authority. Content handlers are plugged into it through typed codecs and a registry;
they do not create a second operation, attempt, asset, qualification, audit, outbox,
or completion system.

The convergence boundary is:

```text
Command -> frozen OperationDefinition -> Operation -> Attempt/fence
        -> typed codec -> storage-free domain handler
        -> Authority AssetVersion + qualification + binding
        -> audit + outbox -> Completion Contract
```

## Generic authority handler runtime

The chapter runtime's proven load/fence/materialize/event sequence becomes a generic
runtime with typed request and output contracts. Chapter Authority adapts its existing
handlers to this runtime without changing its public application contract. Content
Authority supplies one explicit codec registration per OperationDefinition.

The runtime owns transactions, fencing checks, deterministic output identity,
idempotent materialization, qualification evidence, audit, outbox, and replay. A codec
owns frozen-input type checks, project/version/qualification validation, argument
binding, and domain-result encoding. A domain handler remains storage-free and cannot
open a transaction or invoke LocalStorage.

## Content definition maturity

The 22 content definitions remain disabled until their handler, codec, PostgreSQL
execution, Completion, idempotency, fencing, project isolation, stale-input, and replay
tests pass. Promotion is evidence based and proceeds in four batches: Creative,
World/Character, Theme/Ending, and Long-form. Registration alone remains
`handler_bound`, never `integration_proven`.

## Governed context content

`ContextBundle` is split logically into three immutable layers in one versioned
authority output:

- Context Manifest: selected/rejected versions and governance evidence.
- Context Segments: safe summaries and structured facts with allowed-use metadata.
- Stage Context View: ordered, budgeted content for the current production stage.

Raw source expression is excluded. `structure_only` becomes abstract structural
content; `review_only` is unavailable to Draft. Revoked, stale, quarantined, or
cross-project inputs fail closed. The context digest is calculated from the actual
stage view and manifest, so content changes invalidate the bundle.

The chapter command propagates context candidates, version references, and token
budget from the root request into every relevant child command.

## Review and re-review

Revision may only produce `RESOLUTION_CLAIMED`. A distinct
`chapter.revision.review` Operation consumes the original draft, initial review,
revision, context, and review rules. It creates a new immutable ReviewReport plus
`RevisionQualityDelta`. Only this operation can mark issues `RESOLVED`, `REOPENED`,
or create regressions. Quality and Publish Gate require the latest eligible re-review
with zero blockers and a passed decision.

## Stateful canon

Canon extraction and reduction are separated. Extraction derives assertion and state
change candidates from the accepted revision and governed context. Reduction consumes
the previous project-scoped snapshots, detects typed conflicts, and emits append-only
new snapshot versions. Missing first-chapter baselines are explicit; missing required
history after chapter one is an error.

State inputs include Canon, character and relationship state, timeline, foreshadow,
promise, reward, world-rule, and power state. Long-form semantic operations consume
these frozen AssetVersions through Content Authority codecs; fixture/provider/operator
evidence is labelled rather than implied.

## Quality and publish gate

Quality becomes an evidence aggregate. Each dimension records its score (when
available), gate status, evidence version, weight, blocking flag, calibration status,
and source kind. Missing real calibration is `UNCALIBRATED`; fixture evidence cannot
produce `production_verified` maturity. There is no production `score = 100` fallback.

Publish Gate consumes latest re-review, the aggregate, canon, source eligibility,
leakage, originality, anti-AI, platform, operator approval/checklist asset, and blob
verification. Missing or stale blocking evidence fails closed.

## Chapter Production Bus boundary

The legacy bus becomes a compatibility command adapter, authority query adapter, and
rebuildable projection builder. In production mode it cannot first-write migrated
chapter asset types or continue after a PostgreSQL failure. Development exports,
fixtures, projection caches, and compatibility reads remain explicitly
non-authoritative and emit migration telemetry.

## Failure and compatibility

- Database writes stay in short authority transactions.
- A crash before output creates no output; retry is safe.
- A crash after output before completion replays the stable output binding.
- A stale fence cannot materialize or complete output.
- Cross-project and non-eligible frozen inputs are rejected before domain execution.
- Existing committed migrations are not modified; new structures, if needed, use a
  forward-only migration and preserve existing data.

## Proof boundary

This iteration uses unit, architecture, deterministic fixture, and focused PostgreSQL
tests. It does not run real providers, 10/30/100-chapter generation, multi-book load,
or real publishing. Those maturity states remain false unless later evidence exists.
