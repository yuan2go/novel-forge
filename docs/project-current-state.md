# Project Current State

Updated: 2026-07-26
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`, source commit `12f3ff7`
Latest execution-plane source commit: `4aecfa1`

Autonomous Novel OS is the product target: a local-first operating system for long-term, low-manual-intervention, quality-gated premium web-novel production.

The current code/runtime baseline is Novel Forge v6. The repository/package/CLI name remains `novel-forge`; do not rename code paths without a dedicated migration.

Current priority: v1 single-book production closure before broader multi-book, SaaS, or platform automation.

## 2026-07-26 Chapter Authority Gateway Closure

The existing Chapter Saga is unchanged, but all ten uncertain Chapter stages now
compose only through `ProductionExecutionGatewayExternalEffectAdapter`:
draft, review, revision, rereview, Canon extraction, and the five independent
Quality groups. A PostgreSQL integration slice proves ten Authority Attempts and
leases, ten ExternalEffects, ten budget reservations, ten external receipts, ten
RouteSnapshots, ten InputManifests, ten Prompt/Skill bundles, ten normalized outputs
and ValidationManifests, ten execution CommitManifests, and ten model-call/cost
ledgers. The same slice reconstructs an execution result from the Authority-backed
recovery projection after the worker-local session is destroyed.

`ChapterModelExternalEffectAdapter` remains only as an explicit test/development
compatibility adapter. It is absent from the production composition root and now
fails closed before an adapter call in `validation`, `provider-validation`, and
`production`. Callback duplicate/conflict, cancel/late-result, UNKNOWN reconciliation,
and restart behavior use the shared qualified Backend contract fixtures; no Chapter
Saga-specific execution state machine was added.

```text
chapter_authority_gateway_fixture_integrated=true
single_chapter_real_provider_proven=false
real_provider_proven=false
production_verified=false
```

## 2026-07-26 Domain Candidate Execution Boundary

Topic, Outline/Book planning, ChapterPlan, Draft, Review, RevisionPlan, and Editor
revision execution now request candidates through `DomainExecutionPort`. The
Gateway-backed implementation accepts only pre-bound Authority `ExecutionRequest`
contracts and returns structured candidate output plus Route/Input/Output/Validation,
usage, and cost evidence. It has no Authority Asset writer and cannot approve or
activate domain assets. Existing domain services still own parsing, bounded repair,
semantic checks, version creation, governance, approval, and activation.

Development/test model compatibility is centralized inside the execution plane. In a
controlled environment, a missing Gateway port fails before `model_from_env` or a
wrapped model is called. World, Character, ChapterGroup, Theme, and Ending code paths
found in this slice are deterministic materializers and remain in their domains.
Fixture compatibility evidence always records `real_model_call=false` and
`production_verified=false`.

Quality Eval v2 and Evaluation Center Provider judges now use the same candidate
port. Typed Judge execution evidence binds JudgeProfile version, target AssetVersion,
InputManifest, RouteSnapshot, evidence spans, disagreement, usage, cost, and
calibration status. Intrinsic, originality, platform, style, semantic, reader
outcome, pairwise, mutation, and OOD families resolve only to governed
Capabilities. Uncalibrated values are named Raw Score, Ordinal Band, or Pairwise
Preference; the contract rejects probability claims without calibration.

## 2026-07-22 Next Authority Implementation Baseline

WP-00 has audited the execution, Chapter, Book, Context, Evaluation, and storage
boundaries for the next production closure. The code facts show three direct model
execution owners, an ephemeral/full-environment local Codex launcher, mutable
LocalStorage compatibility writes, and a fixture-only Book chapter dispatch. The
PostgreSQL Chapter Authority and its ExternalEffect seam remain the migration anchor;
they are not being rewritten.

The detailed current-path/target-path/removal-gate matrix is in
`docs/reports/next-authority-implementation-baseline.md`. This documentation baseline
does not change production behavior or maturity. `real_provider_proven`,
`book_to_chapter_delegation_proven`, `longform_proven`,
`reader_outcome_behavior_calibrated`, `causal_experiment_validated`, and
`production_verified` remain false.

## 2026-07-22 Production Execution Gateway And Backends

WP-03 adds the Attempt-bound `ProductionExecutionGateway`, explicit Backend Registry,
Admission Controller, Capability Probe, stable ModelProfile/RoutePolicy registries,
immutable Route resolver, Result Normalizer/structural Validator/Reconciler, and
Codex CLI, Remote Provider v2, and scripted fixture backends. The production
PostgreSQL adapter reuses current Attempt/Lease fencing and Authority AssetVersions;
there is no second execution Attempt table or mutable route authority.

The Model Router no longer directly invokes old adapters. Repository-owned legacy
ChatGPT/DeepSeek/Codex/Claude-Code implementations reject controlled production or
validation calls before network/process launch and direct callers to the gateway.
Injected test doubles remain available for policy tests and cannot establish real
Provider proof. Duplicate request, stale fence, Provider UNKNOWN, Callback
deduplication/conflict, cancel/late-result race, local receipt identity, and corrupt
structured output have fixture/integration evidence.

This is gateway and protocol proof, not Chapter migration or production proof.
`production_execution_gateway_proven=true`,
`remote_provider_backend_protocol_proven=true`, and
`codex_cli_backend_fixture_proven=true`; `chapter_authority_migrated`,
`single_chapter_real_provider_proven`, and `production_verified` remain false. WP-04
must connect the existing Chapter ExternalEffect runtime and persist recovery evidence
in PostgreSQL.

Gate-00 was evaluated after the baseline and was not run: paid-call authorization and
the real Provider route, trusted identity/scope, budgets, release identity, object
store, reachable PostgreSQL, and verifiable frozen production inputs were not all
present. This is a recorded precondition result, not a failed Provider run, and it
does not block local WP-01 implementation.

## 2026-07-22 Production Execution Plane Contracts

WP-01 adds pure, serializable Production Execution Plane contracts under
`modules/production_execution/`. Execution request/handle/result/cancellation,
RouteSnapshot, and all five Manifests bind to the existing Authority Attempt and
fencing token; no `execution_attempt` table, repository, scheduler, Provider call, or
production behavior was added. ModelProfile uses stable aliases and requires exact
Capability Probe evidence. Route qualification binds backend/model/version/probe and
rejects any reasoning-effort change, including `xhigh` to `high`.

Cancellation evidence now distinguishes local process termination from upstream
Provider cancellation, and a successful upstream cancel requires a real Provider
request ID and cancellation receipt. Validation acceptance freezes its policy and
required checks. InputManifest uses a typed generic target scope so the same contract
can support Book, World, Character, Arc, ChapterGroup, and Chapter execution.

`execution_plane_contract_proven=true` means contract/unit/integration boundaries are
verified; `production_execution_gateway_proven`, `codex_cli_backend_proven`,
`remote_provider_backend_proven`, and all real-provider/production flags remain false.

## 2026-07-22 Persistent Codex Process Supervisor

WP-02 replaces the local Codex/Claude-Code worker's ephemeral process launcher with a
persistent execution directory and process-group supervisor. Every launch now has
durable metadata, stdout/stderr, result, and `ProcessReceipt`; successful production
bindings carry the existing Authority `operation_id`, `attempt_id`, and fencing token.
Concurrent duplicate submissions launch once, startup failures are durable, timeout
and local cancellation use SIGTERM/SIGKILL process-group evidence, and worker restart
recovery distinguishes recoverable output, corrupt output, PID reuse, and
unverifiable identity.

Child processes receive only the documented environment allowlist. Local CLI evidence
uses `LOCAL_CLI_REMOTE_INFERENCE`, a real `local_execution_receipt_id`, and null
Provider request/response identifiers; killing the local CLI does not claim upstream
Provider cancellation. Legacy unbound calls are explicitly non-production.

This changes the local Codex execution seam but does not yet establish the
PostgreSQL-backed `ProductionExecutionGateway` or a qualified Codex backend. No real
Provider call ran. `persistent_process_supervisor_proven=true`, while
`production_execution_gateway_proven`, `codex_cli_backend_proven`,
`real_provider_proven`, and `production_verified` remain false.

## 2026-07-18 Pre-Provider Production Architecture v2

The bounded architecture is now `PRE_PROVIDER_PRODUCTION_ARCHITECTURE_COMPLETE`.
Provider v2 routes are registry-qualified, callbacks are durable PostgreSQL receipts,
ChapterPlan v3 and multi-entity Quality Context are strict, Calibration and Typed
Empty creation use Authority Operations, Canon re-extraction is policy-bounded and
visible in the Root Saga timeline, and worker health persists as a projection. A Book
Root Saga fixture proves orchestration/recap/plan-adjustment and pause/resume without
generating prose. Catalog supersession no longer counts replaced Draft/Export names
as missing implementations.

This is architecture completion before validation. `real_provider_proven`,
`longform_proven`, `multi_book_proven`, and `production_verified` remain false.

## 2026-07-18 Pre-Provider Production Closure

Functional convergence now preserves the complete frozen ChapterPlan, represents
explicit empty history with nine typed logical Snapshot declarations, and supplies
five stage-specific Quality context views compiled from frozen profile content.
Provider Adapter v2 adds explicit request identity, stable-key, timeout,
query/cancel/callback capability contracts plus a scripted control-plane proof;
legacy adapters remain validation-ineligible. Canon DEFER can reopen or expire, and
REQUEST_REEXTRACTION now creates a superseding Extraction/Proposal generation before
the same root Saga can resume. Worker supervision has explicit fatal exit/restart
semantics, and CI separates architecture, unit, PostgreSQL, migration, and catalog
binding jobs.

The earlier phase state was `FUNCTIONALLY_READY_FOR_PROVIDER_VALIDATION`. This is not a
claim of real Provider, long-form, or production proof.

The PostgreSQL-only chapter Authority slice now contains an eighteen-node business
chain plus root Saga. It adds a multi-asset `ProductionInputManifest`, governed
Context consistency evidence, independent Re-review, semantic Canon extraction and
per-change Approval gates, nine independent Snapshot AssetVersions, five parallel
Quality groups with an Aggregate fan-in, internal Publish Gate, verified Export, and
a post-Blob Final Release Gate. Forty-two Definitions are `integration_proven`:
chapter root plus eighteen nodes, all 22 content-intelligence Definitions, and the
per-decision `canon.change.approve` Authority Definition.

Workers isolate task failures, persist exceptional Attempt outcomes, enforce frozen
business deadlines, propagate cancellation, resume reconciled ExternalEffects, and
serialize scoped budget reservations. This is deterministic/fixture and local
PostgreSQL proof. It is not real-Provider, production, or long-form proof. The
LocalStorage Chapter Bus remains only on the production-disabled legacy/development
surface. Quality dimensions without calibrated current-Revision evidence fail
closed, and external publishing remains disabled. See
`docs/reports/real-provider-single-chapter-readiness.md` and
`docs/reports/operation-definition-maturity-matrix.md`.

This document describes the current state as observed from code, tests, configuration, routes, and skills. It does not treat historical docs as truth unless code evidence exists.

## Evidence Base

- Product blueprints: `docs/blueprint/autonomous-novel-os-full-blueprint.md`, `docs/blueprint/novel-os-project-blueprint.md`
- Current blueprint control reports: `docs/reports/blueprint-gap-audit.md`, `docs/reports/module-maturity-matrix.md`, `docs/reports/data-model-gap-matrix.md`, `docs/reports/v1-v7-roadmap.md`, `docs/reports/next-production-slices.md`
- CLI: `src/novel_forge/cli.py`
- API: `src/novel_forge/api/app.py`, `src/novel_forge/api/routers/`
- Product services: `src/novel_forge/api/services/`
- Domain/runtime modules: `src/novel_forge/modules/`
- Schemas: `src/novel_forge/schemas/assets.py`
- UI: `web/admin/app/`
- Tests: `tests/unit/`, `tests/integration/`, `tests/acceptance/`
- Commands: `Makefile`, `pyproject.toml`, `web/admin/package.json`, `docker-compose.yml`
- Skills: `skills/`, `.claude/skills/`, `scripts/sync_claude_skills.py`

## V7 Content Intelligence Foundation State

The current branch has implemented the first V7 content intelligence foundation as schema-backed assets, services, API routes, Agent operations, workflow processors, tests, and basic Web Admin consoles. This is a foundation slice, not proof of full autonomous long-novel production.

| Capability | Current Status | Evidence | Remaining Gap |
|---|---|---|---|
| Genre OS | Implemented foundation | `modules/genre_os/`, `api/routers/genre_os.py`, `tests/unit/test_genre_os.py` | More calibrated packs per platform/genre and deeper draft-policy use |
| Style OS | Implemented foundation | `modules/style_os/`, `api/routers/style_os.py`, `tests/unit/test_style_os.py` | Provider-assisted style review and richer corpus comparison |
| Canon Graph 2.0 plugins | Implemented foundation plus typed graph reducer | `modules/canon_graph/service.py`, `tests/unit/test_canon_graph_plugins.py` | Human-grade conflict resolution and graph UI depth |
| Quality Eval 2.0 | Implemented provider-evidence, provider run report, and golden-set calibration foundation | `modules/quality_eval/`, `modules/evaluation_center/`, `modules/model_router/`, `tests/unit/test_quality_eval_v2.py` | Real external provider calibration still requires credentials and operator approval |
| Long-chain Proof Center | Implemented deterministic plus opt-in provider 50 proof and V7 provider proof manifest | `modules/long_chain_proof/`, `modules/v7_provider_proof/`, `/product/provider-proof/v7`, `tests/unit/test_long_chain_proof.py`, `tests/unit/test_v7_provider_proof.py` | Real credentialed provider proof is not a default local test |
| Publishing/Feedback Adapter 2.0 | Implemented manual plus generic HTTP API adapter, Fanqie/Qidian project-scoped rules, adapter gate, receipt parser confidence, approved feedback patch/AgentTask application chain | `modules/publishing_feedback_adapters/`, API router, unit tests | Commercial platform SDK/callback/rate-limit behavior remains future work; feedback AgentTasks are planned, not auto-dispatched |
| Agent/Workflow coverage | Implemented foundation plus provider/platform/V7 proof operations | `modules/agent_scheduler/service.py`, `modules/workflow_nodes/service.py` | Production provider adapters still require explicit environment configuration |
| Web Admin V7/OS consoles | Implemented foundation plus Artifact Inspector, provider judge controls, platform gate controls, and project production Cockpit | `web/admin/app/features/content-intelligence/`, `web/admin/app/features/os/`, route pages | Browser smoke remains optional without Playwright; guided repair remains review-only |

## Capability Fact Table

| Capability | Current Status | Evidence | Main Gap | Docs Update Needed | Expansion Risk |
|---|---|---|---|---|---|
| Project management | Implemented | `api/routers/projects.py`, `modules/project_operations/service.py`, `web/admin/app/projects/page.tsx`, `tests/unit/test_project_operations.py` | Product UX depth and multi-user semantics remain partial | Yes | Medium |
| Genre/topic library | Implemented | `modules/topics/service.py`, `modules/platform_strategy/service.py`, `schemas/assets.py`, `skills/topic-development/` | Market feedback loop is partial | Yes | Medium |
| Genre OS content intelligence | Implemented foundation | `modules/genre_os/service.py`, `api/routers/genre_os.py`, `tests/unit/test_genre_os.py` | Deeper platform-calibrated strategy packs and generation-policy use | Yes | Medium |
| Material library | Implemented | `modules/materials/service.py`, `modules/ingestion/service.py`, `web/admin/app/assets/page.tsx`, `tests/unit/test_mkaos_source_eligibility.py`, `tests/unit/test_analysis_services.py`, `tests/unit/test_context_builder_stage_profiles.py`, `tests/unit/test_mkaos_usage_feedback_governance.py` | MKAOS-derived and analysis-converted material cards inherit source eligibility, Context Bundles write `material_usage_event` records, and lineage governance consumes usage feedback without auto-reweighting | Yes | Medium |
| Source Governance | Implemented foundation | `modules/source_intake/service.py`, `modules/source_intake/diff_repair.py`, `modules/source_intake/connector_runner.py`, `modules/source_intake/connector_adapters.py`, `modules/source_intake/stale_sweep.py`, `modules/source_intake/retention_sweep.py`, `modules/source_intake/runtime_gate.py`, `api/routers/handoffs.py`, `schemas/assets.py`, `modules/mkaos_lineage/service.py`, `tests/unit/test_source_intake.py`, `tests/unit/test_context_builder_stage_profiles.py`, `tests/unit/test_mkaos_usage_feedback_governance.py`, `tests/unit/test_product_api_routes.py` | Audit-only source refresh reports cover stale/hash/sync evidence, weight governance emits reviewable invalidation recommendations, connector execution plans are approval-gated/no-side-effect, approved local-file connector runner produces refreshed SourceSnapshot/SourceRefreshReport evidence inside a sandbox, non-local connector adapter lifecycle writes rate-limit/callback/no-default-network receipts without network execution, source diff repair plans write ChangeImpactReport/ReviewIssue/planned AgentTask evidence, approved source repair apply can mark downstream assets stale with rollback_plan evidence, source-aware rollback restores metadata/task state with rollback_result evidence, stale/quarantine sweep writes context-denial evidence plus ReviewIssue/AgentTask plans, retention/expiry sweep writes no-delete cleanup plans, and source governance runtime gate writes production fail-closed GateResult evidence; caller integration into all production readiness paths remains partial | Yes | High |
| Knowledge library | Implemented | `modules/knowledge/service.py`, `modules/mkaos/`, `schemas/assets.py` | Production selection quality still improving | Yes | Medium |
| MKAOS | Partially implemented, broad coverage; uncertain extraction PEP-bound | `modules/mkaos*`, `modules/production_execution/retrieval_execution.py`, `tests/unit/test_mkaos_*.py`, `tests/integration/test_mkaos_*.py` | Model-assisted analysis/extraction returns candidates through governed execution contracts; Rights, isolation, lineage, review, approval, and weights remain domain-owned. Real Provider/retrieval validation and full production learning depth remain pending | Yes | High |
| Longform analysis and recap | Fixture-integrated through PEP; real longform unproven | `modules/longform_recap/`, `modules/longform_stability/`, `modules/long_chain_proof/`, `modules/production_execution/longform_execution.py` | Uncertain analysis/remote similarity return candidates and evidence; deterministic reducers remain local. Recap emits approval-gated future-plan proposals and does not overwrite ArcPlan. Real Provider 10/30+ chapter behavior remains unverified | Yes | High |
| Web-fiction deconstruction | Implemented | `modules/decomposition/service.py`, `modules/analysis/service.py`, `skills/hot-novel-deconstruction/` | Provider-backed high-quality extraction is partial | Yes | Medium |
| Published/classic fiction analysis | Partially implemented | `modules/analysis/service.py`, `skills/published-fiction-craft-analysis/`, `skills/classic-literary-depth-analysis/` | Product workflow depth and corpus-scale evaluation are partial | Yes | Medium |
| Hot novel business deconstruction | Partially implemented | `skills/hot-novel-business-deconstruction/`, `modules/analysis/service.py` | Business analytics integration is partial | Yes | Medium |
| Outline generation | Implemented | `modules/outline/service.py`, `skills/long-outline/`, tests under `test_module_services.py` | Agent operation and platform feedback coupling are partial | Yes | Medium |
| Chapter plan / detailed outline | Implemented with embedded blueprint contract | `modules/chapter_plan/service.py`, `tests/unit/test_chapter_blueprint_contract.py`, `skills/chapter-outline/` | Standalone scene-beat lifecycle and final full-loop proof remain pending | Yes | Medium |
| Draft generation | Implemented for local/runtime slices with blueprint, readable-gate, mobile-reading, chapter-economy, and character-pressure evidence | `modules/drafting/service.py`, `modules/content_quality_loop/service.py`, `modules/mobile_reading/service.py`, CLI `draft`, `tests/unit/test_chapter_blueprint_contract.py`, `tests/unit/test_content_quality_loop.py`, `tests/unit/test_mobile_reading.py` | Production provider hard-stop coverage and final unified full-loop proof remain pending | Yes | High |
| Style OS | Implemented foundation | `modules/style_os/service.py`, `api/routers/style_os.py`, `tests/unit/test_style_os.py` | Provider-backed style judge and richer style library workflows | Yes | Medium |
| Review center | Implemented, still deepening | `modules/review/service.py`, `modules/review_issue/service.py`, `web/admin/app/review/page.tsx`, tests | Semantic/model-assisted review quality is partial | Yes | High |
| Revision/editor | Implemented with issue strategy contract | `modules/review_issue/service.py`, `modules/editor/service.py`, `modules/revision/service.py`, `modules/loop_kernel/service.py`, `web/admin/app/editor/page.tsx` | Multi-version UX, rollback depth, and real improvement metrics are partial | Yes | Medium |
| Long-form stability | Partially implemented with reducer and recap cadence evidence | `modules/longform_stability/`, `modules/longform_recap/`, `tests/unit/test_longform_stability.py`, `tests/unit/test_longform_recap_agent.py`, `tests/integration/test_novel_os_long_chain_*` | Promise lifecycle, operator cadence configuration, and full novel-scale autonomous stability are not proven | Yes | High |
| Long-chain proof | Implemented deterministic plus opt-in provider 50 proof and provider-proof manifest | `modules/long_chain_proof/service.py`, `modules/v7_provider_proof/service.py`, `tests/unit/test_long_chain_proof.py`, `tests/unit/test_v7_provider_proof.py`, `tests/integration/test_long_chain_50_chapter_content_intelligence.py` | Real provider-backed chapter generation proof is not default local test | Yes | High |
| Canon | Partially implemented | `modules/canon_graph/service.py`, `web/admin/app/canon-console/page.tsx`, `tests/unit/test_canon_graph*.py` | Human-grade conflict resolution and merge workflows are partial | Yes | High |
| Canon Graph 2.0 plugins | Implemented foundation plus shared reducer target | `modules/canon_graph/service.py`, `modules/longform_stability/service.py`, `tests/unit/test_canon_graph_plugins.py`, `tests/unit/test_longform_stability.py` | Genre-specific conflict fix UX remains partial | Yes | High |
| Arc / foreshadowing | Partially implemented with reducer projection | schemas `ArcPlan`, `ForeshadowingGraph`, UI routes `arc-console`, `foreshadowing-console`, `modules/longform_stability/service.py` | Payoff SLA/status transitions remain shallow | Yes | Medium |
| Character / villain | Partially implemented with character-pressure gate foundation | `modules/characters/service.py`, `modules/character_pressure/service.py`, schemas `CharacterCard`, `VillainOperationPlan`, `ProtagonistCharmReport`, `AntagonistPressureReport`, UI `character-console`, `tests/unit/test_character_pressure.py` | Character pressure scoring is deterministic and needs calibration plus guided repair UI depth | Yes | Medium |
| Context Builder | Partially implemented with stage profile contract | `modules/context_builder/service.py`, `api/routers/context_builder.py`, `web/admin/app/context/page.tsx`, `tests/unit/test_context_builder_stage_profiles.py` | Selected/rejected/compressed summaries now carry source eligibility in production; manual controls, KG-backed context, invalidation warnings, and final full-loop profile assertions still need depth | Yes | High |
| RAG / memory | Partially implemented; controlled remote embedding PEP-bound | `storage/retrieval_index.py`, `storage/qdrant_index.py`, `modules/production_execution/retrieval_execution.py`, `modules/pgvector_store/service.py`, `modules/long_memory/service.py` | Deterministic local retrieval remains local; controlled remote embedding requires an execution port with frozen evidence. Real Provider retrieval quality and external service coverage remain unverified | Yes | High |
| OS Envelope | Partially implemented | `modules/os_envelope/service.py`, `modules/production_kernel/`, `api/routers/runtime.py`, `schemas/assets.py`, `tests/unit/test_production_entrypoint_contract.py` | v2 canonical envelope is persisted inside `ProductionOperation` parent records for registered Kernel dispatches with idempotency replay/conflict, child failure evidence, bounded lifecycle control, alias-aware static bypass scanning, and a non-mutating runtime coverage report that distinguishes legacy child runs from new missing-parent/missing-envelope runs; legacy control migration, universal enforcement and industrial transaction authority remain incomplete | Yes | High |
| Agent Center | Partially implemented | `modules/agent_registry/`, `modules/agent_scheduler/`, `modules/production_kernel/`, `web/admin/app/agent-*`, tests | Registered Agent dispatch can be parented by `ProductionOperation`; operation coverage, direct-caller migration, lifecycle commands, production UI depth and industrial recovery remain partial | Yes | High |
| Approval / permission gates | Implemented foundation | `modules/permission_center/service.py`, `/product/permission-center/*`, `tests/unit/test_permission_center.py` | High-risk callers still need staged migration to `approval_request` refs | Yes | High |
| Feedback loop | Partially implemented | `modules/feedback/`, `modules/feedback_backflow/`, `web/admin/app/feedback*`, tests | Real reader cohort analytics and plan mutation governance need depth | Yes | Medium |
| Publishing/feedback adapters | Implemented manual plus generic HTTP adapter, Fanqie/Qidian parser/status/gate/rule-snapshot slices, and feedback mutation apply chain | `modules/publishing_feedback_adapters/service.py`, API router, `tests/unit/test_publishing_feedback_adapters.py` | Specific platform SDKs, callbacks, real platform rate limits, and automatic feedback-task dispatch are not integrated | Yes | Medium |
| Quality gate | Partially implemented | `modules/evaluation_center/`, `modules/mkaos_quality/`, `modules/mkaos_production_gate/`, tests | Unified gate semantics across all releases are still being hardened | Yes | High |
| Quality Eval 2.0 | Implemented provider-evidence, provider run report, and golden-set calibration foundation | `modules/quality_eval/service.py`, `modules/evaluation_center/service.py`, API routers, `tests/unit/test_quality_eval_v2.py` | Real external provider calibration remains environment-dependent | Yes | High |
| Release package / publishing | Partially implemented | `modules/publishing/`, `api/routers/audit.py`, `web/admin/app/publish-gate/page.tsx`, tests | Platform adapters/calendar and explicit gate checks need more production coverage | Yes | High |
| UI console / Project Cockpit | Implemented shell plus project production Cockpit, provider/platform controls, source readiness/runtime gate surfacing, multi-book schedule depth, and V1 artifact coverage data | `modules/novel_os_cockpit/service.py`, `web/admin/app/`, `web/admin/app/features/os/`, `web/admin/app/features/content-intelligence/`, `tests/unit/test_novel_os_cockpit.py` | Guided repair workflows remain review-only; dashboard does not replace final acceptance proof | Yes | Medium |
| Portfolio OS | Implemented foundation | `modules/portfolio_os/service.py`, `/product/portfolio/*`, `tests/unit/test_portfolio_os.py` | Cross-book similarity/contamination guard, scheduler plan approval boundary, and pause/kill lifecycle recommendations exist as local evidence; actual dispatch and status mutation remain non-automatic and approval-gated | Yes | Medium |
| Database | Partially implemented | local JSON storage, `docker-compose.yml`, Postgres migrations/tests, `modules/pgvector_store/` | Postgres/local fallback strategy is still being hardened | Yes | High |
| Tests | Implemented broad suite | `tests/unit`, `tests/integration`, `tests/acceptance`, `Makefile` | Browser smoke is optional; full provider tests need secrets/fixtures | Yes | Medium |
| Export | Partially implemented with v1 local handoff | `modules/chapter_production_bus/service.py`, release package/publishing assets, local markdown export manifest/provenance/checklist paths | Platform-specific export adapters and final unified multi-chapter publish handoff coverage are partial | Yes | Medium |
| Platform adaptation | Partially implemented | `modules/platform_strategy/service.py`, `skills/platform-strategy-os/` | Real platform policy/API integration is partial | Yes | Medium |
| Skills | Implemented | root `skills/`, `.claude/skills/`, `scripts/sync_claude_skills.py`, tests | Runtime drift must stay checked; external runtime skills are not project source | Yes | Medium |
| CLI / scripts | Implemented | `src/novel_forge/cli.py`, `scripts/`, `Makefile` | README commands must prefer module invocation unless package installed | Yes | Low |
| Eval Center | Partially implemented with golden set and calibration assets | `modules/evaluation_center/service.py`, `api/routers/evaluation.py`, `web/admin/app/evaluation/page.tsx`, tests | Full provider benchmarking/routing governance is partial | Yes | High |
| Loop Engineering | Partially implemented | `modules/loop_kernel/service.py`, `web/admin/app/loop-runs/page.tsx`, tests | Productized planning/retry/learning loops need depth | Yes | Medium |
| Longform Recap Agent | Partially implemented with explicit cadence | `modules/longform_recap/service.py`, `api/routers/longform_recap.py`, `tests/unit/test_longform_recap_agent.py`, scheduler tests | End-to-end production Agent coverage is not complete for all related roles | Yes | High |

## Current Risks

As of 2026-07-18, the PostgreSQL-only production surface includes server-side
multi-asset input preparation, 202 Saga admission, isolated background workers,
Provider UNKNOWN/reconciliation and serialized budget reservation, evidence-bearing
Canon proposals and Approval gates, 41-dimension grouped Quality evidence, verified
Blob export, and a post-Blob Final Release Gate. See
`reports/pre-provider-runtime-hardening.md` and
`reports/quality-authority-real-gate.md`.

1. Historical docs still contain v5 wording and can mislead implementation decisions.
2. Several features have schemas, routes, and UI pages but are not complete product workflows.
3. Agent runtime and provider policy have strong slices, but universal production hard-stop coverage must continue to be verified.
4. Legacy local JSON remains available only for development/import/export/read compatibility; production Authority endpoints fail closed instead of falling back to it.
5. MKAOS, Context Builder, Canon/KG, ReviewIssue, Eval, and publishing must stay unified; new features should not create parallel paths.
6. The current implementation has broad V6/V7 runtime foundations, but the v1 single-book production loop is not yet proven as a 10-30 chapter closed workflow.

## Next Priorities

See [reports/v1-v7-roadmap.md](reports/v1-v7-roadmap.md), [reports/next-production-slices.md](reports/next-production-slices.md), and [reports/autonomous-novel-os-phase-01-report.md](reports/autonomous-novel-os-phase-01-report.md). The most important next work is to close the v1 single-book production loop, continue Kernel direct-entrypoint migration and lifecycle/status reconciliation, then harden context/KG consistency, provider evidence, release/publish gates, calibrated reader-promise/chapter-economy/character-pressure/mobile-reading detection, and productized UI verification.
