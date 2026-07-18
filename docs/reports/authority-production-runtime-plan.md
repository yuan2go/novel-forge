# Authority Production Runtime Convergence Plan

Date: 2026-07-18  
Branch: `feat/v7-content-intelligence-and-longform-proof`  
Baseline HEAD: `a5cabc035d8aea365fb9aed5fc2b1614302178ba`

## Scope and evidence boundary

This plan is based on the current source tree, migrations, runtime code, API contracts,
tests, and generated OperationDefinition catalog. Historical reports are supporting
context only. The slice does not run a real or paid provider, network source connector,
platform publication, or 3/10/30/100 chapter proof. `production_verified`,
`real_provider_proven`, and `longform_proven` therefore remain false.

## Current implementation

- `modules/command_kernel` already owns Operation, Attempt, Saga, Completion, fencing,
  cancellation, ExternalEffect UNKNOWN/reconciliation, effect heartbeat, audit, outbox,
  Blob verification, and qualification semantics.
- `modules/chapter_authority` provides a twelve-node Chapter Saga and independent Canon
  snapshot AssetVersions, but `run_single_chapter_slice()` admits and executes every node
  in one process while keeping predecessor outputs in memory.
- `api/routers/chapter_authority.py` exposes only a synchronous `/run` route and trusts
  `actor_id`, title, premise, and caller-provided context-shaped data.
- `modules/content_authority` has typed codecs/handlers and a recovery-aware single-
  Operation scheduler. Its application still builds permissions from the registry and
  has no public PostgreSQL-only command/query/control API.
- Context Manifest, Segments, and Stage Context Views exist. The missing boundary is a
  server-side resolver that selects eligible project assets and freezes their identities
  before Chapter admission.
- ExternalEffect already records stable idempotency, provider correlation, UNKNOWN,
  query reconciliation, heartbeat, receipt, and cancellation coordination. Missing
  production-provider pieces are explicit reconciliation capability, provider request
  identity, request deadlines, and pre-dispatch budget reservation/settlement.
- Canon extraction/reduction and nine snapshot types exist, but extraction requires an
  evidence-bearing unified semantic contract and an optional Provider ExternalEffect
  boundary rather than treating the revision digest as semantic state.
- `ChapterQualityAggregate` exists, while the Chapter node does not yet fan out all
  required web-fiction evidence dimensions as independently traceable Authority outputs.
- Legacy LocalStorage Permission Center and Chapter Production Bus remain compatibility
  surfaces and cannot be used as PostgreSQL production authority.

## Architecture decisions

1. **One Command Kernel.** Chapter and Content schedulers coordinate existing Kernel
   primitives. No second Operation, Attempt, Saga, asset, effect, audit, or outbox model.
2. **Admission is not execution.** Public POST routes resolve a trusted Principal,
   prepare/freeze inputs, admit durable operations, and return `202`. Workers own
   execution.
3. **Preparation is a deep boundary.** `production_preparation` owns authoritative asset
   resolution, stage requirements, selection reasons, readiness issues, and construction
   of the frozen Chapter command. It never reads LocalStorage.
4. **Durable graph state.** Chapter child Operations and dependencies are admitted before
   the API returns. Scheduler ticks derive readiness and predecessor outputs from
   PostgreSQL, never an in-memory output map.
5. **Trusted identity.** API actor fields are compatibility metadata only. Admission
   actor and permissions come from a configured local/service Principal and a project-
   scoped policy. Worker identity comes from worker configuration.
6. **Effect lifecycle remains generic.** Provider execute/query/cancel, request timeout,
   reconciliation mode, heartbeat, stable request identity, and budget reservation are
   extensions of ExternalEffect, not a parallel provider job protocol.
7. **Evidence before aggregate.** Quality dimensions produce target-bound, calibrated
   evidence. The aggregate and publish gate validate latest eligible evidence for the
   accepted revision. Fixture evidence stays explicitly uncalibrated.
8. **Canon extraction is evidence-bearing.** Deterministic extraction, optional Provider
   extraction, and operator annotations merge into one typed result. High-impact or
   low-confidence changes require approval before reduction.
9. **Projection is never Completion evidence.** ChapterProductionRun, AgentRun, and
   WorkflowRun remain rebuildable operator views.

## Implementation slices

### 1. Production preparation and trusted command construction

Add `modules/production_preparation/{contracts,resolver,policies,service,command_builder,queries}.py`.
The resolver selects project-scoped ACTIVE/ELIGIBLE/CLEAR versions plus latest eligible
qualification, rejects stale/revoked/quarantined/cross-project overrides, records why
each version was selected, and enforces first-chapter versus continuing-chapter Canon
requirements. The service emits a schema-shaped `ProductionPreparationReport` and only
builds a `SingleChapterRequest` when READY. Context candidates and version refs are
frozen into the command.

Modify:

- `api/models.py`
- `api/authority_dependencies.py`
- `api/routers/chapter_authority.py`
- `modules/chapter_authority/orchestrator.py`

### 2. Asynchronous Chapter admission and scheduler

Split Chapter orchestration into:

- `admit_chapter_saga()` — registers definitions, admits root/children and dependencies,
  returns root/saga IDs without executing handlers;
- `ChapterAuthorityScheduler.tick()` — coordinates readiness, creates or takes over a
  fenced Attempt, loads frozen predecessor outputs from Authority bindings, executes one
  node, completes it, and coordinates the next state;
- `workers/chapter_authority.py` — bounded polling loop with configured worker Principal,
  concurrency, heartbeat, retry/dead-letter and graceful stop.

The old synchronous facade remains explicit fixture/development-only and production
fail-closed. Add command/status/cancel/recover routes. Cancellation delegates to the
existing Kernel cancellation protocol.

### 3. Provider lifecycle and budgets

Extend the existing adapter contract with explicit `query()` capability metadata and
`cancel()`. Add a compatible migration only where current tables lack fields/tables:

- provider request ID / model ID / request deadline / last provider heartbeat;
- reconciliation mode and manual-resolution flag;
- project-scoped `authority_budget_reservation` with stable uniqueness, estimate,
  reserved/settled/released amounts, status, effect/operation binding, and audit time.

Budget service reserves before effect dispatch, settles actual usage on a validated
receipt, and releases on pre-dispatch failure/cancel. UNKNOWN holds the reservation until
reconciliation; it is never directly retried.

### 4. Quality Authority evidence

Reuse storage-free quality domain functions through adapters. Register concrete Chapter
quality definitions for the implemented dimensions and fan them out after accepted
revision/re-review/Canon. Each report binds to the target revision AssetVersion and
records gate type, score, threshold, blocking, calibration status, source, locations,
confidence, and revision strategy. Aggregate waits for required terminal evidence;
Publish Gate rejects stale/wrong-target/missing/blocking evidence and never upgrades
fixtures to production verification.

### 5. Canon semantic extraction

Add `CanonSemanticExtraction` and evidence-bearing change records for facts, character,
relationship, timeline, foreshadow, promise, reward, world rules, power, narrative
patterns, theme movement, and antagonist pressure. Keep accepted-revision digest only as
identity evidence. Add deterministic fixture extraction and a typed optional Provider
ExternalEffect port. Reduction rejects low-confidence/high-impact changes without valid
approval and continues producing append-only project-scoped snapshots.

### 6. Content product entrypoints

Expose PostgreSQL-only Content command/query/cancel/recover routes. Admission validates
Definition, handler/codec, frozen inputs, project, permission, and approval server-side.
Map the established 22 content definitions to Agent capabilities and a minimal workflow
descriptor while leaving Operation/Attempt/Saga as execution authority. Extend the
existing Cockpit only if it cannot submit and inspect these commands through current
generic operation UI.

### 7. Legacy closure and evidence regeneration

Classify Chapter/Context/Draft/Review/Revision/Canon/Quality/Publishing/Content legacy
entrypoints as migrated, adapter-backed, development-only, mapped, unmapped, or
production-blocked. Production LocalStorage first-write paths remain fail-closed.
Regenerate Catalog and coverage from current HEAD, then update current-state and maturity
reports without claiming provider, long-form, or production proof.

## Migration policy

Any migration is append-only, idempotently deployable, project-scoped, indexed for ready
queue/reconciliation/budget lookup, and compatible with existing rows. Existing migration
files are immutable. Existing Authority asset/effect/attempt tables are reused.

## Focused test plan

- Production preparation: latest eligible selection, qualification failure, cross-project
  override, second-chapter Canon baseline, approval/checklist, context selection,
  auditable override, idempotency, repair actions.
- Chapter scheduler: API 202/no inline execution, dependency ordering, lease takeover,
  attempt/effect heartbeat, crash before output and after output, Completion replay,
  cancellation, dead-letter, root Saga recovery.
- Provider lifecycle: pre-dispatch reserve, success settle, failure release, UNKNOWN hold,
  reconciliation, unsupported/manual mode, request identity, cancel evidence, stable-key
  duplicate protection.
- Quality: required dimensions, target version, stale/latest selection, blocking failure,
  uncalibrated fixture identity, non-waivable gates.
- Canon: semantic changes and evidence, digest-only rejection, approval gate, continuity,
  timeline/world/power conflict, lifecycle state, rollback/rebuild, project isolation.
- Security: caller actor is not trusted, unauthorized admission, worker capability scope,
  missing/expired approval, rejection audit.
- Architecture: no LocalStorage import in new authority modules; no projection in
  Completion; ExternalEffect required for provider/network/object-store work.

## Explicitly deferred

Real/paid Provider calls, real Git/RSS access, external platform publishing, multi-book
dispatch, large UI redesign, multi-model strategy, and 3/10/30/100 chapter proofs are not
run in this slice. Their maturity remains unproven.
