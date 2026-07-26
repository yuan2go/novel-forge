# Repository Production Execution Migration Implementation Plan

> **For agentic workers:** Execute inline task-by-task; subagent dispatch is not authorized for this workspace. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate every production-reachable uncertain execution and external side effect to the PostgreSQL Authority-bound Production Execution Plane while preserving deterministic domain decisions in their owning modules.

**Architecture:** PostgreSQL `authority_operation` and `authority_attempt` remain the only final work-state authority. An Attempt freezes a governed capability, input manifest, route snapshot, and ExternalEffect; `ProductionExecutionGateway` delegates execution to a qualified backend and returns evidence contracts, while domain materializers, validators, approval policies, reducers, and AssetVersion activation remain outside the gateway.

**Tech Stack:** Python 3.12, stdlib dataclasses/AST/unittest, PostgreSQL 16, psycopg 3, FastAPI, JSONB Authority assets, local Authority object store, append-only migrations.

## Global Constraints

- Do not execute real Provider requests, paid calls, real publishing/withdrawal, real feedback/source fetch, reader experiments, long-book pressure, or production deployment.
- Keep `real_provider_proven`, `single_chapter_real_provider_proven`, `book_to_chapter_delegation_proven`, `longform_proven`, `reader_outcome_behavior_calibrated`, `causal_experiment_validated`, `multi_book_proven`, and `production_verified` false.
- Reuse `authority_operation`, `authority_saga`, `authority_attempt`, `authority_lease_acquisition`, `authority_external_effect`, `authority_external_effect_dispatch`, `authority_external_receipt`, `authority_budget_reservation`, `authority_asset`, `authority_asset_version`, `authority_asset_qualification`, and `authority_asset_approval`.
- Do not create a second Attempt, Saga, Budget, Approval, or final execution-status authority.
- Fixture evidence always records `fixture_protocol_only=true`, `real_model_call=false`, and `production_verified=false`.
- Controlled environments are exactly `validation`, `provider-validation`, and `production`; legacy execution and LocalStorage fallback must fail before network/process launch.
- Retry reuses the frozen RouteSnapshot by default. Re-route creates a new Authority Attempt or explicit generation.
- Each work package ends with focused verification and its own commit.

---

### Task 0: Repository execution inventory

**Files:**
- Create: `src/novel_forge/tools/production_execution_inventory.py`
- Create: `tests/unit/test_production_execution_inventory.py`
- Create: `docs/reports/production-execution-migration-ledger.json`
- Create: `docs/reports/production-execution-migration-ledger.md`

**Interfaces:**
- Produces: `build_execution_inventory(repo_root: str | Path) -> dict[str, Any]`
- Produces: `write_execution_inventory(repo_root, json_output, markdown_output) -> dict[str, Any]`
- Consumes: Python ASTs under `src/` and `scripts/`; no runtime imports or network calls.

- [x] Write tests proving alias imports, SDK clients, subprocess wrappers, HTTP clients, model methods, callback/publish/fetch symbols, deterministic calls, and fixture-only paths are classified.
- [x] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_production_execution_inventory -v` and verify red.
- [x] Implement receiver-aware AST classification with the required nine categories, stable owner IDs, production reachability, Authority/Gateway bindings, blocking `LEGACY_UNKNOWN`, and deterministic JSON hashes.
- [x] Generate both ledgers and verify every record has the required schema fields.
- [x] Run the focused test, `compileall`, and ledger schema checks.
- [x] Commit `audit: inventory repository execution and side-effect paths`.

### Task 1: Governed capability registry

**Files:**
- Create: `src/novel_forge/modules/production_execution/capabilities.py`
- Create: `src/novel_forge/modules/production_execution/capability_registry.py`
- Modify: `src/novel_forge/modules/production_execution/__init__.py`
- Create: `tests/unit/test_production_execution_capabilities.py`

**Interfaces:**
- Produces: `CapabilityDefinition`, `RiskClass`, `ExecutionDomain`
- Produces: `CapabilityRegistry.register(definition)`, `resolve(capability_id)`, `require_route(capability_id, backend_profile, environment)`
- Produces: `default_capability_registry()`

- [x] Test the complete required capability list, unique IDs, schema/policy refs, backend/runtime allowlists, fixture/production rules, and duplicate conflict behavior.
- [x] Implement immutable serializable definitions and a fail-closed registry; constants are the only business-facing capability identifiers.
- [x] Export the registry; Admission binding follows in Task 2 when `ExecutionRequest.capability` exists, without importing domain modules.
- [x] Run capability/gateway/architecture tests.
- [x] Commit `feat: add governed production execution capability registry`.

### Task 2: Cross-domain execution contracts

**Files:**
- Modify: `src/novel_forge/modules/production_execution/contracts.py`
- Modify: `src/novel_forge/modules/production_execution/gateway.py`
- Modify: `src/novel_forge/modules/production_execution/routing.py`
- Modify: all construction sites found by `rg -n "ExecutionRequest\\(" src tests`
- Modify: `tests/unit/test_production_execution_contracts.py`

**Interfaces:**
- Extends `ExecutionRequest` with `root_operation_id`, `workspace_id`, `domain`, `capability`, `validation_policy_ref`, `commit_policy_ref`, and typed target scope.
- Defines `TargetScope` with project/book/volume/arc/chapter-group/chapter/asset/reader/experiment identifiers.
- Preserves `ExecutionBackend.submit/reconcile/cancel` signatures.

- [x] Add red tests for round-trip serialization, stable hash, same-ID contract conflict, scope validation, route freeze, and explicit re-route identity.
- [x] Implement the minimal contract changes and update all request factories.
- [x] Make Admission resolve the capability definition and enforce matching domain/risk/backend/fixture rules.
- [x] Run contract, gateway, Chapter, and architecture tests.
- [x] Commit `refactor: generalize production execution contracts across domains`.

### Task 3: Versioned prompt, skill, and input manifests

**Files:**
- Create: `src/novel_forge/modules/production_execution/bundles.py`
- Create: `src/novel_forge/modules/production_execution/policies.py`
- Modify: `src/novel_forge/modules/production_execution/contracts.py`
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Create: `tests/unit/test_production_execution_bundles.py`

**Interfaces:**
- Produces: `PromptBundle`, `SkillBundle`, `ContextPolicy`, `SourcePolicy`, `ValidationPolicy`, `CommitPolicy`.
- Extends `InputManifest` with frozen context/prompt/skill/canon/story/planning/quality versions, asset hashes, source eligibility, read set, and target scope.

- [x] Test stable hashes, version changes, missing content hashes, secret rejection, source eligibility, and path-only input rejection.
- [x] Implement immutable contracts and manifest consistency validation.
- [x] Materialize Chapter prompt/skill/input bundle assets through existing Authority AssetVersion storage.
- [x] Run bundle/contract/Chapter PostgreSQL tests.
- [x] Commit `feat: add versioned prompt skill and input execution manifests`.

### Task 4: Authority-backed execution recovery

**Files:**
- Create: `src/novel_forge/modules/production_execution/recovery.py`
- Modify: `src/novel_forge/modules/production_execution/postgres.py`
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Add append-only migration only if existing receipt/effect uniqueness cannot represent callback/process bindings.
- Create: `tests/integration/test_production_execution_recovery_postgres.py`

**Interfaces:**
- Produces: `AuthorityExecutionRecoveryStore.put_request/put_handle/put_receipt/put_manifest/load_session`
- Stores evidence in existing ExternalEffect dispatch/receipt and Authority AssetVersion/object-store records; projections cannot own terminal state.

- [x] Test crash points before send, after send, before receipt, before commit, after CommitManifest, duplicate/conflict/late callback, PID reuse, corrupt result, and object-store partial failure.
- [x] Replace production use of `InMemoryExecutionRecordStore`/worker-local session state with an Authority-backed store; retain in-memory stores only in fixtures.
- [x] Ensure UNKNOWN is reconciled and never blindly resubmitted.
- [x] Run recovery, ExternalEffect, callback, migrations, and restart tests.
- [x] Commit `feat: make production execution recovery durable and authority-backed`.

### Task 5: Backend lifecycle conformance

**Files:**
- Split focused implementations from `backends.py` only where behavior changes together:
  `remote_provider_backend.py`, `codex_cli_backend.py`, `scripted_backend.py`,
  `remote_external_action_backend.py`, `agent_workspace_backend.py`
- Create: `src/novel_forge/modules/production_execution/conformance.py`
- Create: `tests/unit/test_execution_backend_conformance.py`
- Modify: `tests/unit/test_process_supervisor.py`

**Interfaces:**
- All backends implement the unchanged `ExecutionBackend` protocol.
- Produces reusable `BackendConformanceSuite` scenarios for duplicate submit, contract conflict, fence, query, cancel, callback, unknown, timeout, malformed output, receipts, and recovery.

- [x] Write conformance cases and failure injectors before backend changes.
- [x] Complete Provider query/cancel/callback verification and usage/cost availability semantics.
- [x] Add supervisor cancellation by execution identity; Codex cancel records SIGTERM/SIGKILL evidence, PID token checks, and late-result quarantine.
- [x] Add non-model external-action and Agent workspace contracts plus fixture backends.
- [x] Enforce fixture proof flags and `UNAVAILABLE` usage/cost rather than numeric zero.
- [x] Run all conformance/process tests.
- [x] Commit `feat: complete qualified backend conformance and lifecycle contracts`.

### Task 6: Governed route resolution

**Files:**
- Modify: `src/novel_forge/modules/production_execution/routing.py`
- Modify: `src/novel_forge/modules/production_execution/contracts.py`
- Modify: `src/novel_forge/modules/model_router/service.py`
- Create: `tests/unit/test_production_execution_routing.py`

**Interfaces:**
- Produces `FallbackPolicy(mode, allowed_route_ids, triggers, maximum_route_changes, approval_required, quality_revalidation_required)`.
- `RouteResolver.freeze(...) -> RouteSnapshot`; Model Router exposes resolution only and cannot invoke an adapter.

- [x] Test stable aliases, no provider/model/reasoning/prompt/skill/schema drift, explicit fallback approval, retry snapshot reuse, and re-route generation.
- [x] Implement versioned fallback policies and route qualification.
- [x] Remove production execution responsibility from Model Router while keeping a development compatibility facade that delegates to PEP.
- [x] Run route, model-router, gateway, and architecture tests.
- [x] Commit `refactor: reduce model router to governed route resolution`.

### Task 7: Chapter Authority lifecycle closure

**Files:**
- Modify: `src/novel_forge/modules/chapter_authority/execution_gateway.py`
- Modify: `src/novel_forge/modules/chapter_authority/model_effects.py`
- Modify: `src/novel_forge/api/authority_dependencies.py`
- Modify: Chapter integration/unit tests.

**Interfaces:**
- All ten Chapter model stages use the shared Gateway and Authority recovery store.
- Legacy `ChapterModelExternalEffectAdapter` is test/development compatibility only and fails closed in controlled environments.

- [x] Test stage coverage, Attempt/Effect/Budget/Route/Input/Receipt/Output/Validation/Commit evidence, callback, cancel, restart, UNKNOWN, and late result.
- [x] Remove remaining production responsibility from the legacy adapter without rewriting the Chapter Saga.
- [x] Record `chapter_authority_gateway_fixture_integrated=true` and `single_chapter_real_provider_proven=false`.
- [x] Run Chapter Authority and callback PostgreSQL suites.
- [x] Commit `refactor: finalize chapter authority execution gateway migration`.

### Task 8: Content generation migration

**Files:**
- Create: `src/novel_forge/modules/production_execution/domain_execution.py`
- Modify: `chapter_plan`, `outline`, `world`, `characters`, `topics`, `drafting`, `editor`, `revision`, `review` service modules identified by the ledger.
- Create: `tests/unit/test_content_generation_execution_migration.py`

**Interfaces:**
- Produces `GenerationCandidate`, `RawStructuredOutput`, `ExecutionEvidence`.
- Domain services call an injected Authority execution port, then materialize/validate/approve/activate through their existing domain stores.

- [ ] Add vertical-slice tests in order: ChapterPlan, ChapterGroup, World, Character, Book/Volume/Arc, Creative/Theme/Ending, Draft/Revision.
- [ ] Replace direct ModelAdapter/Router calls with capability-bound execution ports.
- [ ] Keep activation and bounded repair in domain modules and prove Gateway cannot activate assets.
- [ ] Run each domain test group and update the ledger.
- [ ] Commit each independently reviewable domain slice; finish with `refactor: migrate content generation execution to PEP`.

### Task 9: Quality, review, and evaluation migration

**Files:**
- Modify: `modules/quality_eval/`, `modules/evaluation_center/`, `modules/review/`, `modules/style_os/`, and ledger-identified judge modules.
- Create: `tests/unit/test_quality_execution_migration.py`

**Interfaces:**
- Produces `JudgeExecutionEvidence` binding JudgeProfile version, target AssetVersion, manifests, route, raw score/evidence, calibration status, disagreement, usage/cost.
- Deterministic aggregation, thresholds, blocking, and approval remain in Quality/Eval.

- [ ] Test intrinsic/originality/platform/style/semantic/reader/pairwise/mutation/OOD capability routing and uncalibrated naming.
- [ ] Replace direct adapter/router calls.
- [ ] Prohibit uncalibrated probability claims.
- [ ] Run quality/evaluation/review suites.
- [ ] Commit `refactor: migrate quality review and evaluation execution to PEP`.

### Task 10: MKAOS and retrieval migration

**Files:**
- Modify: ledger-identified `mkaos_*` provider/extraction modules and remote retrieval adapters.
- Create: `tests/unit/test_mkaos_retrieval_execution_migration.py`

**Interfaces:**
- Embedding evidence binds model, dimension, chunk hash, eligibility, batch, index version, usage/cost, partial failure, and dirty-index state.
- Rerank evidence binds candidate-set version and ordered scoring evidence.

- [ ] Test extraction/rule/template/classification/dedup/judge plus embedding/rerank evidence.
- [ ] Route uncertain execution through PEP while preserving Rights, License, Source Eligibility, Isolation, schema, lineage, and weights in MKAOS.
- [ ] Run MKAOS unit/acceptance/PostgreSQL tests.
- [ ] Commit `refactor: migrate MKAOS model and retrieval execution to PEP`.

### Task 11: Longform analysis migration

**Files:**
- Modify: `modules/longform_recap/`, `modules/longform_stability/`, `modules/long_chain_proof/`, and related planning services.
- Create: `tests/unit/test_longform_execution_migration.py`

**Interfaces:**
- PEP produces analysis or `PlanChangeProposal` candidates only.
- Deterministic reducers produce Story State; semantic diff, impact analysis, approval, new AssetVersion, activation, and supersession remain domain-owned.

- [ ] Test recap/drift/closure/reachability/forecast/extraction capabilities and reducer import isolation.
- [ ] Remove direct model execution and direct future-plan overwrite.
- [ ] Run longform/reducer/canon tests without real 10/30 chapter runs.
- [ ] Commit `refactor: migrate longform analysis and preserve deterministic reducers`.

### Task 12: Agent and Loop execution migration

**Files:**
- Modify: `modules/agent_scheduler/`, `modules/agent_runs/`, `modules/loop_kernel/`, `agents/runtime.py`.
- Create: `tests/unit/test_agent_workspace_execution_migration.py`

**Interfaces:**
- Agent/Loop output is one of Patch Candidate, Structured Decision, Analysis Report, Proposed AssetVersion, Workspace Manifest.
- Domain Authority accepts or rejects structured output; workspace changes alone never imply commit success.

- [ ] Test Provider/process selection prohibition, structured-result validation, tool/command/network/write-set limits, and explicit commit rejection.
- [ ] Route side effects through `agent.workspace.execute`; keep Claude Code optional.
- [ ] Run Agent Scheduler/Loop/permission tests.
- [ ] Commit `refactor: route agent and loop side effects through production execution`.

### Task 13: Publishing, feedback, and remote fetch migration

**Files:**
- Modify: `modules/publishing_feedback_adapters/`, `modules/feedback/`, `modules/source_intake/`, notifications/webhook entrypoints.
- Create: `tests/unit/test_external_action_execution_migration.py`

**Interfaces:**
- Uses `RemoteExternalActionBackend` with stable key, request identity, query/reconcile, cancel/withdraw, callback verification, rate/quota, partial success, receipt, classification, and privacy refs.

- [ ] Add no-network fixtures for publish/query/withdraw/callback, feedback, source fetch, RSS/Git/HTTP, notification, and webhook.
- [ ] Replace direct external calls and preserve domain publish decisions/source/feedback policies.
- [ ] Run external-action, source, publishing, feedback, and callback tests.
- [ ] Commit `refactor: govern publishing feedback and remote fetch external effects`.

### Task 14: Credential, environment, and workspace security

**Files:**
- Modify: PEP contracts/backends/process supervisor and Authority dependency construction.
- Create: `tests/architecture/test_production_execution_security_boundaries.py`

**Interfaces:**
- Persist only `auth_profile_ref`, `credential_scope`, and `secret_version_ref`.
- Workspace policies bind cwd/snapshot/read/write/commands/tools/network/output/file-count/file-size/result contract.

- [ ] Test secret-name/value rejection in every persisted contract and evidence payload.
- [ ] Test explicit environment allowlists and workspace path containment.
- [ ] Enforce the policies before backend launch.
- [ ] Run security/process/gateway tests.
- [ ] Commit `security: enforce execution credentials environment and workspace boundaries`.

### Task 15: Repository architecture guards

**Files:**
- Create: `tests/architecture/test_repository_execution_boundaries.py`
- Modify: `src/novel_forge/tools/production_execution_inventory.py`

**Interfaces:**
- AST guard reports exact file/symbol/import/call for forbidden SDK, subprocess, backend, legacy, reducer, activation, and fixture-proof boundaries.

- [ ] Add red characterization tests from every remaining ledger violation.
- [ ] Make controlled legacy/model/local-storage paths fail before execution.
- [ ] Enforce domain→Gateway protocol imports only, Gateway→no-domain, Backend→no-activation, Reducer→no-Gateway.
- [ ] Run architecture and inventory suites.
- [ ] Commit `test: enforce repository-wide production execution architecture boundaries`.

### Task 16: Strangler completion, documentation, and verification

**Files:**
- Modify: legacy adapter/model-router/provider compatibility modules.
- Modify: all requested architecture/current-state/reports/catalog/coverage files.
- Modify: ledger JSON/Markdown.

**Interfaces:**
- Every capability has one of `DISCOVERED`, `CLASSIFIED`, `CONTRACT_DEFINED`, `GATEWAY_BOUND`, `FIXTURE_PROVEN`, `INTEGRATION_PROVEN`, `REAL_PROVIDER_PENDING`, `LEGACY_BLOCKED`, `LEGACY_REMOVED`.

- [ ] Prove every caller migrated before marking legacy blocked/removed; retain development/test compatibility with usage evidence.
- [ ] Regenerate migration ledger, PostgreSQL authority coverage, and OperationDefinition catalog.
- [ ] Run clean/upgrade migrations, full PostgreSQL Authority suite, ExternalEffect/Budget/Callback/Chapter/PEP suites, compileall, unit, architecture, formatting/type checks available in the repository, workspace validation, Skill drift, and `git diff --check`.
- [ ] Perform a local two-axis review from the pre-migration fixed point: repository standards and this specification.
- [ ] Update factual flags without upgrading any real/longform/production proof.
- [ ] Commit `refactor: block legacy production execution paths after PEP migration`, followed by `docs: record repository production execution migration evidence` if documentation changes are independently reviewable.
