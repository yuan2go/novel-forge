# Authority Production Runtime Convergence

Date: 2026-07-18. Scope: deterministic/fixture functional convergence only.

> Current addendum: the pre-Provider closure extends this original twelve-node
> baseline to eighteen nodes plus root, adds Canon Approval and five Quality child
> Operations, adds a dedicated Canon decision Operation, and raises the Catalog to
> 124 Definitions / 42 integration-proven.
> See `pre-provider-runtime-hardening.md`, `quality-authority-real-gate.md`, and
> `canon-approval-authority.md` for current evidence.

## Result

The production surface now admits a chapter as a durable PostgreSQL Saga and returns
HTTP 202. `ProductionPreparationService` resolves qualified, project-scoped
AssetVersions, freezes the selected versions and Context inputs, and blocks admission
with repair actions when required evidence is absent. `ChapterAuthorityScheduler`
advances one durable node at a time; the worker can resume READY,
FAILED_RETRYABLE, or expired-lease EXECUTING work without using request memory.

The chapter chain is:

`Plan -> Context -> Draft -> Review -> Revision -> Re-review -> Canon Extraction -> Canon Reduction -> Quality -> Publish Gate -> Export -> Final Release Gate`.

Implementation evidence: `0bc22a1`, `6dbcb02`, `9f33ff3`, `1a75aa7`,
`4f3bb65`, `f57aef0`, `1ab7b57`, `b9aee6e`, and `d58d31e`.

Final review repairs are `d3a3738` (chapter-targeted prepared inputs), `ab37474`
(explicit per-Definition permissions), `a7a7fad` (API test extras), and `de738d6`
(actual Content request-body binding and TestClient proof).

## Production preparation and identity

- API payload actor IDs are compatibility metadata only. A trusted local operator is
  resolved from server configuration and checked against project scope.
- Chapter inputs are resolved from Authority AssetVersions with ACTIVE / ELIGIBLE /
  CLEAR and latest eligible qualification checks.
- Chapter 2+ fails closed without the prior Canon, character, relationship, timeline,
  foreshadow, promise, reward, and power snapshots.
- Explicit version overrides are project-scoped and auditable; a cross-project,
  revoked, stale, or quarantined override is rejected.
- The production API is the PostgreSQL-only `authority_app`; it imports no
  LocalStorage or fallback service.

## Runtime and recovery

- `POST /product/production/chapter-authority/commands` returns 202 with root
  Operation/Saga/query/control identifiers and does not execute the Saga inline.
- Node admission is progressive, so each child freezes only already-materialized
  upstream inputs.
- Attempt leases, monotonic fencing, retry/dead-letter, cancellation, audit, outbox,
  Completion, and output replay reuse Command Kernel primitives.
- Provider effects retain UNKNOWN for ambiguous dispatches and reconcile through
  `execute/query/cancel`; unsupported query capability requires manual resolution.
- A Kernel lease guard actively heartbeats Attempt and ExternalEffect leases around
  blocking handler/adapter calls; one-second slow fixtures prove renewal.
- Provider budget is reserved before dispatch and settled or released afterward;
  UNKNOWN holds the reservation.

## Content authority product entry

All 22 Content Intelligence Definitions have a shared API command surface, strong
queries, cancellation/recovery controls, an independent polling worker, and explicit
Agent/Workflow mappings. AgentRun and WorkflowRun are dispatch/projection records;
Operation/Attempt remain execution authority. The 22 Definitions remain
`integration_proven`, not `production_verified`.

## Verification

- Unit/architecture/API: 41 preparation/principal, Canon semantic, quality aggregate,
  actual FastAPI TestClient, boundary, and Definition contract tests passed.
- PostgreSQL: 47 migration, chapter scheduler, prepared-input vertical slice,
  deterministic one-chapter slice, five-effect model fixture, Content runtime/crash
  recovery, Attempt lease/fencing, cancellation, ExternalEffect lifecycle, and budget
  reservation tests passed.
- Catalog at the time of this report: 117 Definitions: 65 candidate, 17 mapped, 35 integration_proven, 0
  production_verified.

## Honest remaining limits

- P1: Provider semantic Canon extraction is effect/budget/completion integrated with
  a typed fixture, but has no real-provider proof.
- Closed by the current addendum: Quality uses five independent child Operations and
  an Aggregate fan-in. Semantic evidence remains intentionally uncalibrated until a
  Provider/human result targets the current Revision.
- P1: legacy LocalStorage product services remain available only on the explicitly
  selected development/legacy surface; they are not deleted.
- P2: minimal Cockpit UI for Content commands remains unimplemented; API plus
  Agent/Workflow mappings are the current product entrypoint.

Real Provider, paid calls, 3/10/30/100 chapter runs, multi-book load, network
connectors, and real platform publishing were not run.

## Final two-axis review

Standards review found and repaired broad infrastructure exception downgrading,
request-supplied actor propagation on the compatibility route, Definition permission
auto-expansion, request-body annotation binding, test-extra drift, and whitespace.
Spec review added the missing Preparation-to-Scheduler vertical proof and chapter-
target checks. No unresolved P0 finding remains in this focused slice.
