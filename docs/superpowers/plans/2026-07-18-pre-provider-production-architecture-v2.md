# Pre-Provider Production Architecture V2 Implementation Plan

> **For agentic workers:** Execute inline task-by-task; subagent dispatch is not authorized for this workspace. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the provider, callback, semantic quality, continuity, catalog, Book Authority, generator, observability, and CI architecture required before real-provider validation.

**Architecture:** Extend the existing PostgreSQL Command Kernel through typed adapters and Authority Operations. Reuse generic Operation/Attempt/Saga/AssetVersion/Completion primitives; projections and fixtures remain non-authoritative.

**Tech Stack:** Python 3.12, PostgreSQL 16/pgvector, FastAPI, unittest, JSONB Authority assets, GitHub Actions.

## Global Constraints

- No real network, API key, paid Provider, real chapter, external publish, LocalStorage authority, or remote Git action.
- Never modify migrations 0001-0029; new migrations are append-only.
- Fixture evidence always records `fixture_protocol_only=true`, `real_model_call=false`, `production_verified=false`.
- Only PostgreSQL integration/replay/failure/isolation evidence can raise a Definition to `integration_proven`.

---

### Task 1: Provider v2 registry and mock SDK adapter

**Files:** create `provider_control/registry.py`, `openai_v2.py`, `conformance.py`; modify `authority_dependencies.py`; test `test_provider_v2_production_routing.py`.

**Interfaces:** produce `ProviderAdapterRegistry.qualify(route, environment)` and `OpenAIProviderAdapterV2` with injected transport; Chapter Authority consumes only qualified routes.

- [ ] Add tests for controlled/fixture/legacy route qualification, timeout/stable-key/request-ID/query/cancel/receipt behavior, malformed results, and zero network access.
- [ ] Implement registry/factory/route qualification and the transport-injected adapter.
- [ ] Replace legacy dependency construction for validation/production; keep explicit fixture construction in test/development.
- [ ] Run focused tests and commit `feat(provider): route authority through provider v2 registry`.

### Task 2: Durable callback and worker-health Authority

**Files:** create Migration 0030; create `provider_control/callback_authority.py`; create callback router; modify worker supervision; tests for callback PostgreSQL/API and health.

**Interfaces:** `accept_provider_callback(command)` verifies a registered provider, derives project from ExternalEffect, persists message/hash identity, invokes reconciliation, and returns an idempotent receipt.

- [ ] Write failing signature/replay/conflict/spoof/UNKNOWN/budget/concurrency tests.
- [ ] Add callback receipt/attempt and worker-health projection schema plus indexes.
- [ ] Implement callback command, signature verifier seam, trusted router, reconciliation/budget resume, Audit/Outbox, and worker-health upsert/query.
- [ ] Run Migration/API/PostgreSQL tests and commit `feat(callback): add durable provider callback authority`.

### Task 3: ChapterPlan Contract v3

**Files:** modify `chapter_plan_views.py`, handlers/definitions; create `chapter_plan_contract.py`; tests for profiles and replay.

**Interfaces:** one registered field set, `ChapterPlanQualificationProfile`, and `qualify_chapter_plan_v3(plan, profile)`.

- [ ] Test opening/payoff/climax requirements, thin Plan rejection, legacy mapping, frozen profile replay, wrong project/chapter.
- [ ] Add v3 fields and profile derivation without synthesizing missing semantics.
- [ ] Bind the frozen qualification profile/version into Plan output and all downstream views.
- [ ] Run unit/Chapter PostgreSQL tests and commit `feat(chapter-plan): enforce contract v3 profiles`.

### Task 4: Quality Context v2

**Files:** modify `context_views.py`, handlers/definitions; create `budget.py`; tests for entity preservation and strict budgets.

**Interfaces:** `QualityContextBudgeter.build(...) -> (view, QualityContextCoverageReport)` with replaceable `TokenEstimator`.

- [ ] Test multiple characters/relationships/foreshadows, typed empty state, deterministic compression, source isolation, exhaustion and critical overflow.
- [ ] Replace asset-type dictionary reduction with ordered entity-scoped state collections.
- [ ] Enforce pre-construction and final token limits, preserving identity/critical facts.
- [ ] Materialize coverage report and require it in Quality Completion.
- [ ] Run focused/Chapter PostgreSQL tests and commit `feat(quality): enforce multi-entity context budgets`.

### Task 5: PostgreSQL Calibration Authority

**Files:** create Migration 0031; add `calibration_authority.py`, definitions/handlers/codecs; tests for metrics and PostgreSQL operations.

**Interfaces:** five explicit Definitions create samples/decisions, run calibration, promote, and revoke; only promotion changes qualified calibration status.

- [ ] Test zero/partial/low-accuracy/duplicate/extra/wrong-profile/stale/revoked and replay cases.
- [ ] Implement policy metrics including confusion matrix, precision/recall, agreement and confidence interval.
- [ ] Implement Authority operations and dataset membership constraints.
- [ ] Run Content/Calibration PostgreSQL tests and commit `feat(calibration): add postgres calibration authority`.

### Task 6: Typed-empty producer and Canon generation governance

**Files:** create Migration 0032; add `empty_state_authority.py`, `reextraction_policy.py`; modify Canon scheduler/approval Authority.

**Interfaces:** `chapter.state.initialize_empty` creates the only trusted empty-state output; `evaluate_reextraction_generation` returns continue/operator-wait/cap/budget/deadline decisions.

- [ ] Test first/second chapter initialization, non-empty/reduction-incomplete conflicts, concurrency/replay/revocation.
- [ ] Test generation cap, repeated digest, no progress, budget/deadline, cancel/recovery, and stale approvals.
- [ ] Persist producer lineage, policy snapshot, digests/progress/cost/deadline and generation timeline steps in existing Saga structures.
- [ ] Run PostgreSQL tests and commit `feat(canon): govern empty state and re-extraction progress`.

### Task 7: Catalog supersession and Engine Generator seam

**Files:** modify `authority_coverage_manifest.py`; add `creative_generator.py` and Content handler/codec/definition; create supersession report tests.

**Interfaces:** Catalog entries expose status plus supersession fields; `creative.candidates.generate` consumes frozen CreativeBrief and a scripted Provider port, emitting multiple structured candidates.

- [ ] Test candidate/alias/superseded/deprecated semantics and historical preservation.
- [ ] Mark only proven overlaps; retain genuinely missing candidates.
- [ ] Implement scripted multi-candidate generation and deterministic evaluator handoff.
- [ ] Document Generator/Normalizer/Validator/Evaluator/Reducer/Approver classifications.
- [ ] Run Content Authority/catalog tests and commit `refactor(catalog): consolidate authority definitions`.

### Task 8: Book Production Authority skeleton

**Files:** create Migration 0033 and `modules/book_authority/`; add router/worker mapping; PostgreSQL fixture tests.

**Interfaces:** `BookAuthorityScheduler` admits existing Chapter root children, recap and plan-adjustment Operations under `book.production.run`, enforcing frozen policy and no-skip recovery.

- [ ] Test admission, 2-3 scripted child completions, 5/10 cadence calculation, plan proposal, pause/resume/cancel, budgets, no-progress and recovery.
- [ ] Implement Book Manifest/Progress/Budget/Acceptance/Recap/Adjustment/Trend AssetVersions.
- [ ] Register child dependencies in the shared Operation graph and expose trusted queries.
- [ ] Run PostgreSQL fixture tests and commit `feat(book): add production authority skeleton`.

### Task 9: Runtime health, CI, docs and final verification

**Files:** modify health router, CI, architecture guards, catalogs and required reports.

**Interfaces:** health response exposes liveness/readiness/worker freshness/DB/outbox/dead-letter/UNKNOWN counts; CI adds provider conformance, callback and Book proofs.

- [ ] Add health persistence/query tests and architecture regression guards.
- [ ] Regenerate Catalog/Coverage and all requested evidence reports.
- [ ] Run full unit, architecture, PostgreSQL, migrations, compileall, lint/validate and diff checks.
- [ ] Commit `docs: record pre-provider production architecture completion` without `.idea/misc.xml` or push.
