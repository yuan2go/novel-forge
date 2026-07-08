# Regression Tests

Updated: 2026-07-08
Baseline checked: branch `feat/v7-content-intelligence-and-longform-proof`

Novel Forge keeps a dependency-light test core and optional industrial/browser checks. Run the smallest relevant verification for each change, then broaden when runtime, API, Agent, or publishing behavior changes.

## Primary Commands

```bash
make test
make lint
make validate
make v1-slow-acceptance
npm --prefix web/admin test
npm --prefix web/admin run lint
PYTHONPATH=src python3 -m novel_forge.cli --help
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_acceptance
PYTHONPATH=src python3 -m unittest tests.integration.test_novel_os_long_chain_smoke
```

## V7 Content Intelligence Focused Commands

Run these when changing Genre OS, Style OS, Canon Graph 2.0 plugins, Quality Eval 2.0, Long-chain Proof, Publishing/Feedback adapters, or related product routes:

```bash
python3 -m unittest tests.unit.test_genre_os tests.unit.test_style_os tests.unit.test_canon_graph_plugins tests.unit.test_quality_eval_v2 tests.unit.test_long_chain_proof tests.unit.test_publishing_feedback_adapters
python3 -m unittest tests.integration.test_content_intelligence_context_builder tests.integration.test_genre_style_quality_to_draft_chain tests.integration.test_feedback_to_mutation_proposal tests.integration.test_long_chain_50_chapter_content_intelligence
python3 -m unittest tests.unit.test_product_api_routes tests.unit.test_schemas tests.integration.test_novel_os_acceptance
python3 -m compileall -q src/novel_forge tests
npm --prefix web/admin run lint
npm --prefix web/admin test
```

Current verified result for the V7 foundation and risk closure pass: all commands above passed. `make test` passed with Python 527 tests OK, skipped=2, and Web Admin 10 passed, 1 optional browser-related skipped test.

## Governance Dead-Letter Focused Regression

Run this when changing Agent Scheduler governance drift handling, dead-letter repair, Agent Center repair audit evidence, or related UI/API surfaces. It intentionally excludes chapter production acceptance and provider proof:

```bash
make governance-dead-letter-regression
python3 scripts/run_governance_dead_letter_regression.py
python3 scripts/run_governance_dead_letter_regression.py --skip-ui
python3 scripts/run_governance_dead_letter_regression.py --list
```

The command bundle covers scheduler dead-letter failure fixtures, reviewed repair preflight, direct recovery blocking, Agent Center API evidence, repair audit/readiness evidence, compileall, and optional Web Admin static/type checks.

## Runtime Growth Focused Regression

Run this when changing chapter production runtime artifact policies, AgentRun/AgentEvent policy, Workflow runtime policy propagation, Agent Center event summary visibility, or related UI/API surfaces. It intentionally excludes chapter sequence acceptance and provider proof:

```bash
make runtime-growth-regression
python3 scripts/run_runtime_growth_regression.py
python3 scripts/run_runtime_growth_regression.py --skip-ui
python3 scripts/run_runtime_growth_regression.py --list
```

The command bundle covers compact TaskStatus/NodeRun behavior, failure NodeRun/trace preservation, AgentRun event growth characterization, success-summary event compaction, failure event preservation, workflow runtime-policy propagation, Agent Scheduler chapter production start/resume operation coverage, Agent Center summary/API evidence, compileall, and optional Web Admin static/type checks.

## Makefile Targets

| Command | Purpose | Notes |
|---|---|---|
| `make test` | Python unittest discovery plus web admin node tests | Default broad local check |
| `make lint` | Python compile check | No style formatter implied |
| `make validate` | Validate local workspace structure/assets | Uses `.local/workspace` by default |
| `make demo` | Run sample pipeline in `.local/demo-workspace` | Writes ignored runtime outputs |
| `make sync-skills-dry-run` | Preview root Skill to runtime Skill sync | Use before syncing |
| `make check-skills` | Fail if runtime Skills drift from source | Required for Skill changes |
| `make local-up` | Docker local stack and smoke | Requires Docker and free ports |
| `make local-smoke` | Smoke running local stack | Requires services |
| `make v1-slow-acceptance` | Run explicit true 10-chapter V1 slow acceptance | Writes `docs/reports/v1-chapter-sequence-slow-acceptance.md`; not part of default `make test` |
| `make governance-dead-letter-regression` | Run focused governance dead-letter regression | Does not run chapter acceptance or provider proof |
| `make runtime-growth-regression` | Run focused runtime write-growth regression | Does not run chapter acceptance or provider proof |
| `make web-dev` | Next.js dev console | Requires Node deps |

## Test Coverage Map

| Area | Test Evidence | Current Coverage |
|---|---|---|
| CLI and local pipeline | `tests/unit/test_cli.py`, `tests/integration/test_pipeline.py`, `tests/integration/test_workflow_steps.py` | Good local coverage |
| Schemas/storage | `tests/unit/test_schemas.py`, `test_storage.py`, `test_storage_graph.py` | Good core coverage |
| Product API | `tests/unit/test_product_api.py`, `test_product_api_routes.py` | Good route/service coverage |
| Agent runtime | `test_agent_scheduler.py`, `test_agent_registry_scheduler_integration.py`, `test_agent_runtime_profiles.py`, `test_agent_center_v2.py` | First-slice coverage |
| Provider/runtime policy | `test_provider_runtime_guard.py`, `test_provider_hard_stop_proof.py`, `test_runtime_policy.py`, `test_runtime_ledger.py` | Active hardening coverage |
| Context/RAG | `test_context_builder_stage_profiles.py`, `test_context_builder_mkaos_flow.py`, `test_context_and_production_chain.py`, `test_pgvector_source_isolation.py`, `test_storage.py` | Partial but meaningful; stage profile/source isolation contracts have focused unit coverage, rejected manual high-risk context selections now record ApprovalRequest refs, source eligibility is preserved in selected/rejected/compressed summaries, production context rejects failed source-derived eligibility, and RAG no longer implicitly rebuilds local vector index during context generation |
| Source Governance | `test_source_intake.py`, `test_mkaos_source_eligibility.py`, `test_analysis_services.py`, `test_context_builder_stage_profiles.py`, `test_mkaos_usage_feedback_governance.py`, `test_schemas.py`, `test_product_api_routes.py` | SourcePolicy/LicenseCheckResult/SourceRiskReport/SourceSnapshot/SourceSyncJob lifecycle, audit-only SourceRefreshReport and `/product/sources/refresh-report`, approval-gated `/product/sources/connector-execution-plan`, non-local `/product/sources/connector-adapter-lifecycle`, sandboxed `/product/sources/connector-run`, reviewable `/product/sources/diff-repair-plan`, approval-bound `/product/sources/diff-repair-apply`, source-aware `/product/sources/diff-repair-rollback`, stale/quarantine sweep and `/product/sources/stale-sweep`, retention/expiry sweep and `/product/sources/retention-sweep`, R0-R4 eligibility, high-risk ApprovalRequest hook, quarantine behavior, MKAOS/material/analysis/context caller eligibility refs, context-selected knowledge/material usage feedback, reviewable source-refresh invalidation recommendations, production fail-closed behavior, schema registration, and `/product/sources/*` route coverage |
| Chapter blueprint | `test_chapter_blueprint_contract.py`, `test_context_and_production_chain.py`, `test_module_services.py` | Embedded `chapter-blueprint-contract-v1` is covered across plan, version, and draft handoff |
| Chapter Production Bus | `test_context_and_production_chain.py`, `test_product_api_routes.py` | Bus run/resume covers draft quality-loop status capture, final/revision content quality-loop execution, bounded `quality_repair` patch/diff/version evidence, re-review content loop, export provenance/checklist evidence, v1 sequence coverage fields, API sync/async runtime policy propagation, worker policy preservation, and production fail-closed helper behavior; chapter acceptance remains deferred |
| MKAOS | Many `test_mkaos_*.py`, including `test_mkaos_source_eligibility.py`, `test_mkaos_usage_feedback_governance.py`, MKAOS integration and acceptance tests | Broad coverage, including source eligibility contract propagation into knowledge cards, production Knowledge Pack selection, material-card inheritance, context-selected usage feedback, and reviewable usage/source-refresh weight governance; still evolving |
| Canon/KG/continuity | `test_canon_graph*.py`, `test_novel_kg*.py`, `test_longform_stability.py`, `test_context_and_production_chain.py`, long-chain integration tests | CanonGraph plugin reducer coverage plus v1 accepted-chapter reducer coverage; full long-form proof remains deferred |
| Reader Promise Ledger | `test_reader_promise_ledger.py`, `test_longform_stability.py`, `test_context_and_production_chain.py`, `test_product_api_routes.py` | Promise creation, normal ledger, broken-promise ReviewIssue/RevisionTask hook, longform reducer evidence, chapter bus output path, and route registration are covered; payoff calibration remains future work |
| Chapter Economy / Pleasure Points | `test_chapter_economy.py`, `test_content_quality_loop.py`, `test_longform_stability.py`, `test_context_and_production_chain.py`, `test_product_api_routes.py` | High-value chapter pass, water-chapter block, PleasurePoint/ChapterEconomyReport schema, ReviewIssue/RevisionTask hook, content loop step, longform reducer evidence, chapter bus output, and route registration are covered |
| Character Pressure | `test_character_pressure.py`, `test_content_quality_loop.py`, `test_longform_stability.py`, `test_context_and_production_chain.py`, `test_product_api_routes.py` | Visible-agency/pressure pass, weak-agency/pressure block, ProtagonistCharmReport/AntagonistPressureReport schema, ReviewIssue/RevisionTask hook, content loop step, longform reducer evidence, chapter bus output, and route registration are covered |
| Mobile Reading Gate | `test_mobile_reading.py`, `test_content_quality_loop.py`, `test_longform_stability.py`, `test_context_and_production_chain.py`, `test_product_api_routes.py`, `test_review_issue.py` | Mobile-friendly pass, dense single-paragraph block, MobileReadingReport schema, mobile_reading_friction ReviewIssue, mobile_paragraph_reflow RevisionTask hook, content loop step, chapter bus output, and route registration are covered |
| Golden Opening Gate | `test_content_quality_loop.py`, `test_review_issue.py`, `test_context_and_production_chain.py` | Chapters 1-3 `golden-opening-gate-v1` content-loop step, weak opening blocking ReviewIssue, opening rewrite RevisionTask evidence, chapter bus final quality-loop evidence, and bounded repair/re-review path are covered; provider/human calibration remains future work |
| Longform recap | `test_longform_recap_agent.py`, `test_agent_registry_scheduler_integration.py` | 5-chapter light recap, 10-chapter formal recap, overdue formal recap, forced checkpoints, next-chapter context, and scheduler operation coverage |
| Review/revision/publishing | `test_review_issue.py`, `test_content_quality_loop.py`, `test_agent_scheduler.py`, `test_publishing_center.py`, `test_publish_feedback_loop.py`, publishing fixtures | Readable prose and golden opening gates create ReviewIssue/RevisionTask evidence; ReviewIssue-to-Revision strategy fixtures cover candidate, task/plan, provider-loop, local-loop, and Agent Scheduler dispatch paths; platform publish adapters record Permission Center approval refs before external/manual publish |
| Eval/quality | `test_evaluation_center_general.py`, `test_longform_quality_gate_e2e.py`, MKAOS quality tests | Partial production eval coverage |
| Provider Proof Harness | `test_v7_provider_proof.py`, `test_quality_eval_v2.py`, `test_provider_hard_stop_proof.py`, `test_product_api_routes.py` | External-provider positive fixture, fixture-denied negative fixture, provider-proof manifest classification, quality judge external proof, provider hard-stop policy, and `/product/provider-proof/v7` route registration are covered |
| V7 content intelligence | `test_genre_os.py`, `test_style_os.py`, `test_canon_graph_plugins.py`, `test_quality_eval_v2.py`, `test_long_chain_proof.py`, `test_publishing_feedback_adapters.py`, and V7 integration tests | Foundation coverage plus provider quality evidence, opt-in provider 50 proof, platform API adapter, Fanqie/Qidian rule snapshot/parser/gate fixtures, feedback mutation ApprovalRequest refs, feedback mutation patch/AgentTask application fixtures, routes, context, and proof fixtures |
| Portfolio OS | `test_portfolio_os.py`, `test_schemas.py`, `test_product_api_routes.py` | PortfolioProject, BookPotentialScore, CrossBookSimilarityReport, BookLifecycleGateReport, ResourceAllocationPlan schema/API/service coverage with two-book isolation, cost-quality rollup, contamination guard, non-dispatching allocation plan, blocking ApprovalRequest, planned AgentTask scheduler evidence, and continue/pause/kill recommendations |
| UI | `npm --prefix web/admin test`, optional Playwright smoke | Node tests exist; browser smoke may be skipped without browsers |
| Industrial services | `test_industrial_integration.py`, `test_online_backends_e2e.py`, Docker smoke targets | Optional, environment-dependent |

## When To Add Tests

Add tests when changing:

- schemas or asset validation;
- CLI/API contracts;
- workflow node execution or task state;
- Agent scheduler queue, lease, runner, gate, budget, retry, recovery, rollback, or dead-letter behavior;
- provider route resolution or model-call policy;
- Context Builder, RAG, Canon/KG, ReviewIssue, MKAOS, publishing, release package, or eval gates;
- broad exception handling or fallback policy;
- UI API contracts or visible operational evidence.

For large service splits, add characterization tests before refactoring. Keep tests at the behavior boundary rather than asserting private helper internals unless the helper is an intentional seam.

## Known Gaps

- Browser route smoke is optional and may be skipped when Playwright browsers are not installed.
- Production provider tests require explicit fixtures/secrets or safe mock-success fixtures that prove evidence shape without calling external APIs.
- Full long-novel generation is not a default regression test; current long-chain tests are smoke/pressure slices.
- True V1 10-chapter slow acceptance passed on 2026-07-07 with 10/10 coverage and 1460.716s runtime. It is intentionally not part of default `make test`; run `make v1-slow-acceptance` when changing chapter bus, context/review/revision loops, or longform/export coverage.
- V1 local export package hardening is covered by the focused `test_chapter_production_bus_runs_and_resumes_end_to_end` fixture, which checks markdown export, manifest path, provenance evidence, source-isolation handoff, and operator checklist. This is development verification, not a replacement for the deferred unified chapter acceptance phase.
- ApprovalRequest foundation is covered by `tests.unit.test_permission_center` plus the product router OpenAPI fixture. These tests cover local non-blocking requests, production/high-risk blocking requests, approved/rejected decisions, expiry, snapshot aggregation, and route registration.
- V1 cockpit artifact coverage is covered by `tests.unit.test_novel_os_cockpit`, which verifies `project_metric_snapshot` includes V1 required-output coverage, reducer/recap/export status, and ApprovalRequest summary. This is operator evidence display, not the deferred chapter acceptance pass.
- Source Governance foundation is covered by `tests.unit.test_source_intake`, `tests.unit.test_mkaos_source_eligibility`, `tests.unit.test_analysis_services`, `tests.unit.test_context_builder_stage_profiles`, `tests.unit.test_mkaos_usage_feedback_governance`, `tests.unit.test_schemas`, and the product route fixture. It proves schema-backed lifecycle, eligibility behavior, audit-only source refresh reports, approval-gated no-side-effect connector execution plans, non-local connector adapter lifecycle receipts, sandboxed approved local-file connector execution, network connector default-deny receipts, reviewable source diff repair plans, approval-bound source repair stale marking, source-aware rollback execution, stale/quarantine sweep evidence, retention/expiry no-delete cleanup planning, MKAOS/material/analysis/context caller propagation, context-selected knowledge/material usage feedback, reviewable weight/invalidation governance, and production fail-closed behavior; it does not yet prove real network connector execution or automatic weight-governance application.
- Optional industrial services require Docker and ports; local unit tests should not depend on them.
- Some UI pages are console/reporting slices and need more end-to-end operator workflow tests.

## Docs-Only Changes

For docs-only updates, run at least:

```bash
git diff --check
rg -n "ARCHITECTURE.md|WORKFLOW.md|TESTING.md|Novel Forge V5|V5 structure" README.md CLAUDE.md docs Makefile
```

If docs changed command claims, verify the command exists in `Makefile`, `pyproject.toml`, `src/novel_forge/cli.py`, or `web/admin/package.json`.
